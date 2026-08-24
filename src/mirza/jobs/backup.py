"""Database + file backup job - parity for cronbot/backupbot.php.

Dumps the DB via pg_dump/mysqldump (auto-detected) and sends the archive to
the backup report topic.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)


async def run_backup(ctx) -> None:
    from mirza.config import get_settings
    settings = get_settings()
    url = settings.database_url
    stamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d_%H%M")

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / f"backup_{stamp}.sql"
        if url.startswith("postgres"):
            cmd = ["pg_dump", url, "-f", str(dump_path), "--no-owner"]
        elif "mysql" in url:
            # asyncpg URL -> mysqldump args
            parts = url.split("://", 1)[1]
            userhost, _, dbname = parts.rpartition("/")
            userpass, _, hostport = userhost.partition("@")
            user, _, password = userpass.partition(":")
            host = hostport.split(":")[0]
            cmd = ["mysqldump", "-h", host or "localhost",
                   "-u", user, f"-p{password}", "--no-tablespaces", dbname]
        else:   # sqlite dev
            dbfile = url.split("///")[-1]
            cmd = ["sqlite3", dbfile, ".dump"]
            proc = await asyncio.create_subprocess_exec(
                *cmd[:2], stdout=open(dump_path, "w"), stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
            cmd = None  # type: ignore[assignment]
        if cmd:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                log.error("db dump failed: %s", err.decode()[:400])
                return

        zip_path = Path(tmp) / f"backup_{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dump_path, arcname=dump_path.name)

        if ctx.bot is not None:
            chat = await _backup_chat(ctx)
            if chat:
                with open(zip_path, "rb") as fh:
                    await ctx.bot.send_document(
                        chat, fh, caption=f"🗄 backup {stamp}",
                        filename=zip_path.name)


async def _backup_chat(ctx) -> int | None:
    from sqlalchemy import select as sa_select
    from mirza.models import Setting
    async with ctx.session_factory() as s:
        res = await s.execute(
            sa_select(Setting.value).where(Setting.key == "Channel_Report"))
        val = res.scalar_one_or_none()
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None
