"""User handler routers aggregation + channel membership hook."""
from __future__ import annotations

from aiogram import Router


def routers() -> list[Router]:
    from .menu import router as menu_router
    from .buy import router as buy_router
    from .services import router as services_router
    from .misc import router as misc_router
    return [menu_router, buy_router, services_router, misc_router]


async def ChatMemberHandler(event, bot=None) -> None:
    """Parity for index.php chat_member block: notify users who leave the
    mandatory channel."""
    try:
        status = event.new_chat_member.status
    except AttributeError:
        return
    if status not in ("left", "kicked", "restricted"):
        return
    user_id = getattr(event.new_chat_member.user, "id", None)
    if user_id is None:
        return
    try:
        await bot.send_message(
            user_id,
            "📢 Please rejoin the channel to keep using the bot.")
    except Exception:
        pass
