"""Middlewares - auth/ban/channel-join/i18n (parity for index.php gates)."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.i18n import t
from mirza.models import Setting, User


class AuthMiddleware(BaseMiddleware):
    """Upserts the user row, blocks banned users, enforces channel join."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        session = get_sessionmaker()()
        try:
            res = await session.execute(
                sa_select(User).where(User.id == str(tg_user.id)))
            user = res.scalar_one_or_none()
            if user is None:
                user = User(id=str(tg_user.id),
                            username=tg_user.username or "none",
                            register_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                            lang="fa")
                session.add(user)
                await session.commit()
            elif user.user_status == "block":
                if isinstance(event, (Message, CallbackQuery)):
                    await _safe_reply(event, "🚫 " + t("users.blocked", "en"))
                return None
            data["db_user"] = user

            # forced channel membership (setting.channel_lock = @channel)
            res2 = await session.execute(
                sa_select(Setting.value).where(Setting.key == "channel_lock"))
            lock = res2.scalar_one_or_none()
            if lock and not user.join_channel_ok and \
                    not _is_admin(int(tg_user.id)):
                ok = await _check_member(data.get("bot"), str(lock),
                                         int(tg_user.id))
                if not ok:
                    if isinstance(event, Message):
                        from aiogram.utils.keyboard import InlineKeyboardBuilder
                        kb = InlineKeyboardBuilder()
                        kb.button(text="✅ عضو شدم / Joined",
                                  callback_data="confirmchannel")
                        kb.button(text="📢 کانال / Channel", url=f"https://t.me/{str(lock).lstrip('@')}")
                        await event.answer(
                            t("users.channel.left_channel", user.lang),
                            reply_markup=kb.as_markup())
                    return None
        finally:
            await session.close()
        return await handler(event, data)


class I18nMiddleware(BaseMiddleware):
    """Injects per-user language + t() into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("db_user")
        lang = getattr(user, "lang", None) or "fa"
        data["lang"] = lang

        def _t(key: str, **fmt) -> str:
            return t(key, lang, **fmt)

        data["t"] = _t
        return await handler(event, data)


def _is_admin(tg_id: int) -> bool:
    from mirza.config import get_settings
    return tg_id == get_settings().admin_number


async def _check_member(bot, channel: str, user_id: int) -> bool:
    if bot is None:
        return True
    try:
        member = await bot.get_chat_member(channel.lstrip("@"), user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return True   # fail-open like legacy


async def _safe_reply(event, text: str) -> None:
    try:
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
    except Exception:
        pass
