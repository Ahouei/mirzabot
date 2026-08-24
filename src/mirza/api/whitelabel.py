"""White-label child-bot webhook dispatcher - parity for vpnbot/index.php.

Each registered child bot (botsaz table) gets its own webhook endpoint
/wl/{bot_username}; updates are dispatched through a per-child Dispatcher
with the owner's admin ids and channel settings applied.
"""
from __future__ import annotations

import logging

from aiohttp import web
from sqlalchemy import select as sa_select

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import Botsaz, User

log = logging.getLogger(__name__)

_child_dps: dict[str, object] = {}


async def _child_dispatcher(bot_token: str, row: Botsaz):
    key = bot_token[-12:]
    if key in _child_dps:
        return _child_dps[key]
    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    dp = Dispatcher(storage=MemoryStorage())
    dp["child_row"] = row
    _child_dps[key] = dp
    return dp


async def whitelabel_webhook(request: web.Request) -> web.Response:
    settings = get_settings()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.webhook_secret and secret != settings.webhook_secret:
        return web.Response(status=403)
    username = request.match_info.get("bot_username", "")
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Botsaz).where(Botsaz.bot_username == username))
        row = res.scalar_one_or_none()
    finally:
        await session.close()
    if row is None:
        return web.Response(status=404)

    # ensure the acting user exists & channel-lock gate (vpnbot parity)
    msg = payload.get("message") or {}
    tg_user = (msg.get("from") or {})
    uid = str(tg_user.get("id", ""))
    if uid:
        sess = get_sessionmaker()()
        try:
            exists = await sess.get(User, uid)
            if exists is None:
                sess.add(User(id=uid, username=tg_user.get("username", "none"),
                              bot_type=f"wl:{username}"))
                await sess.commit()
        finally:
            await sess.close()

    from aiogram.types import Update
    dp = await _child_dispatcher(row.bot_token, row)
    from aiogram import Bot
    bot = Bot(token=row.bot_token)
    try:
        await dp.feed_webhook_update(bot, Update.model_validate(payload))
    finally:
        await bot.session.close()
    return web.Response(text="OK")
