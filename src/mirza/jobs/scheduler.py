"""Scheduler setup - APScheduler cron jobs, parity for function.php activecron().

Each legacy cronbot/*.php becomes a Job plugin registered with its cron spec.
Jobs are toggleable via setting.status_cron (day/volume/remove/... keys).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from mirza.registry import registry

log = logging.getLogger(__name__)


def build_scheduler(bot=None) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=_tz())
    ctx = _JobContext(bot)
    for entry in registry.list("job"):
        if not entry.enabled:
            continue
        cron: str = entry.meta.get("cron", "*/15 * * * *")
        try:
            trigger = CronTrigger.from_crontab(cron)
        except ValueError:
            log.warning("bad cron spec for job %s: %s", entry.key.name, cron)
            continue
        job = entry.factory()
        sched.add_job(job.run, trigger, args=[ctx], id=entry.key.name,
                      max_instances=1, coalesce=True,
                      misfire_grace_time=120)
        log.info("scheduled job %s @ %s", entry.key.name, cron)
    return sched


class _JobContext:
    def __init__(self, bot):
        from mirza.db import get_sessionmaker
        self.session_factory = get_sessionmaker()
        self.bot = bot

    async def send_report(self, kind: str, text: str) -> None:
        """Send to the report supergroup topic mapped by kind (topicid table)."""
        if self.bot is None:
            return
        from sqlalchemy import select as sa_select

        from mirza.models import TopicId
        async with self.session_factory() as s:
            res = await s.execute(
                sa_select(TopicId.topic_id).where(TopicId.report == kind))
            topic = res.scalar_one_or_none() or 0
            chat = await _report_chat(s)
        if not chat:
            return
        kwargs = {"text": text, "parse_mode": "HTML"}
        if topic:
            kwargs["message_thread_id"] = topic
        try:
            await self.bot.send_message(chat, **kwargs)
        except Exception:
            log.exception("send_report failed for %s", kind)


async def _report_chat(session) -> int | None:
    from sqlalchemy import select as sa_select

    from mirza.models import Setting
    res = await session.execute(
        sa_select(Setting.value).where(Setting.key == "Channel_Report"))
    val = res.scalar_one_or_none()
    try:
        return int(val) if val else None
    except (TypeError, ValueError):
        return None


def _tz() -> str:
    from mirza.config import get_settings
    return get_settings().timezone
