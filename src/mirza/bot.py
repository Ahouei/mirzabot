"""Bot bootstrap - dispatcher assembly (replaces index.php webhook entry).

Wires: middlewares (auth, i18n, channel-join, ban-check), user routers,
admin router, whitelabel child dispatchers, APScheduler.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

log = logging.getLogger(__name__)


def build_bot(token: str) -> Bot:
    return Bot(token=token,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # routers are module-level singletons; aiogram forbids attaching one
    # Router to two Dispatchers, so clone fresh instances per build.
    from mirza.handlers.admin import routers as admin_routers
    from mirza.handlers.middleware import AuthMiddleware, I18nMiddleware
    from mirza.handlers.user import routers as user_routers

    def _fresh(routers_list):
        out = []
        import copy

        from aiogram import Router as _Router
        for r in routers_list:
            clone = _Router(name=r.name + f"#{id(dp)%100000}")
            # deep-copy observer state (handlers+filters+middlewares)
            for obs_name in ("message", "callback_query", "chat_member",
                             "pre_checkout_query"):
                src_obs = getattr(r, obs_name, None)
                dst_obs = getattr(clone, obs_name, None)
                if src_obs is None or dst_obs is None:
                    continue
                dst_obs.handlers = copy.deepcopy(src_obs.handlers)
            out.append(copy.deepcopy(r)) if False else None
            out.append(clone)
        return out

    for r in _fresh(user_routers()):
        r.message.middleware(AuthMiddleware())
        r.callback_query.middleware(AuthMiddleware())
        r.message.middleware(I18nMiddleware())
        r.callback_query.middleware(I18nMiddleware())
        dp.include_router(r)
    for r in _fresh(admin_routers()):
        dp.include_router(r)

    # Telegram Stars checkout lifecycle (pre_checkout + successful_payment)
    from mirza.payments.stars import routers as stars_routers
    for r in stars_routers():
        dp.include_router(_fresh([r])[0])

    # legacy chat_member handling (channel left/kicked notifications)
    from mirza.handlers.user import ChatMemberHandler
    dp.chat_member.register(ChatMemberHandler)

    return dp


async def run_polling(token: str) -> None:
    """Dev mode; production uses webhook server."""
    bot = build_bot(token)
    dp = build_dispatcher()
    from mirza.jobs.scheduler import build_scheduler
    sched = build_scheduler(bot)
    sched.start()
    try:
        await dp.start_polling(bot)
    finally:
        sched.shutdown(wait=False)


async def process_update(token: str, secret: str, payload: dict) -> None:
    """Webhook entry - verifies X-Telegram-Bot-Api-Secret-Token (fixes the
    missing webhook-secret validation of the legacy PHP)."""
    from mirza.config import get_settings
    if get_settings().webhook_secret and secret != get_settings().webhook_secret:
        log.warning("webhook rejected: bad secret")
        return
    bot = build_bot(token)
    try:
        from aiogram.types import Update
        dp = build_dispatcher()
        await dp.feed_webhook_update(bot, Update.model_validate(payload))
    finally:
        await bot.session.close()
