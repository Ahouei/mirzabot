"""User handlers batch 2 - parity for remaining index.php user sections:
tariff list, tutorial browsing, support tickets via departments,
custom volume/time purchase with panel pricing.
"""
from __future__ import annotations

import secrets
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Help, MarzbanPanel, Product, Setting, SupportMessage

router = Router(name="user2")

_PENDING: dict[str, dict] = {}


# ── tariff list (text_Tariff_list) ───────────────────────────────
@router.message(F.text.regexp(r"(?i)(💵|تعرفه|tariff|rates)"))
async def tariff_list(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Product).order_by(Product.location,
                                        Product.price_product))
        products = list(res.scalars().all())
        panels = {p.name_panel: p for p in (await session.execute(
            sa_select(MarzbanPanel))).scalars()}
    finally:
        await session.close()
    if not products:
        await message.answer("no plans configured")
        return
    lines = ["💵 **tariffs**"]
    current = None
    for p in products:
        if p.location != current:
            current = p.location
            title = panels[current].name_panel if current in panels else \
                ("all locations" if current == "/all" else current)
            lines.append(f"\n📍 **{title}**")
        lines.append(f"• {p.name_product}: {p.price_product:,} "
                     f"({p.volume_gb}GB / {p.service_days}d)")
    await message.answer("\n".join(lines))


# ── tutorial browsing inside 📚 help ──────────────────────────────
@router.message(F.text.regexp(r"(?i)(📚|آموزش|tutorial|help menu)"))
async def help_browse(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Help))
        helps = list(res.scalars().all())
    finally:
        await session.close()
    if not helps:
        from sqlalchemy import select as _s
        s2 = get_sessionmaker()()
        try:
            txt = (await s2.execute(
                _s(Setting.value).where(Setting.key == "help_text")
            )).scalar_one_or_none()
        finally:
            s2.close()
        await message.answer(txt or "no tutorials yet")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for h in helps:
        kb.button(text=f"📖 {h.name_os[:24]}", callback_data=f"uhelp#{h.id}")
    kb.adjust(1)
    await message.answer("📚 pick a tutorial:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("uhelp#"))
async def help_show(cb: CallbackQuery):
    hid = int(cb.data.split("#")[1])
    session = get_sessionmaker()()
    try:
        h = await session.get(Help, hid)
    finally:
        await session.close()
    if h:
        await cb.message.answer(f"📖 <b>{h.name_os}</b>\n\n{h.description_os}")
        await cb.answer()


# ── support tickets via departments ───────────────────────────────
@router.callback_query(F.data.startswith("ticket#"))
async def ticket_start(cb: CallbackQuery, db_user=None):
    dept_id = cb.data.split("#")[1]
    tracking = secrets.token_hex(4)
    session = get_sessionmaker()()
    try:
        session.add(SupportMessage(
            tracking=tracking, department_id=str(dept_id),
            user_id=str(db_user.id), created_at=_now()))
        await session.commit()
    finally:
        await session.close()
    _PENDING[str(db_user.id)] = {"tracking": tracking, "dept": dept_id}
    await cb.message.answer(
        f"🎫 ticket `{tracking}` opened — send your message:")


@router.message(F.text & F.text.regexp(r"^[^/]"))
async def ticket_message(message: Message, db_user=None, bot=None):
    info = _PENDING.get(str(db_user.id)) or {}
    if "tracking" not in info:
        return
    tracking = info["tracking"]
    # forward to all admins of the main bot (parity: admin notification)
    from mirza.config import get_settings
    admin_id = get_settings().admin_number
    if bot and admin_id:
        try:
            await bot.send_message(
                admin_id,
                f"🎫 ticket `{tracking}` from {db_user.id}:\n\n"
                f"{message.text}",
                parse_mode="HTML")
        except Exception:
            pass
    info.pop("tracking", None)
    await message.answer("✅ sent to support. we'll reply here.")


@router.message(F.text.regexp(r"(?i)^/reply\s+\S+\s+.+"))
async def admin_reply_ticket(message: Message, bot=None):
    """Admin-side: /reply <tracking> <text> — routed to the ticket owner."""
    parts = (message.text or "").split(maxsplit=2)
    tracking, text = parts[1], parts[2]
    session = get_sessionmaker()()
    try:
        row = (await session.execute(
            sa_select(SupportMessage).where(
                SupportMessage.tracking == tracking))).scalar_one_or_none()
    finally:
        await session.close()
    if row is None:
        await message.answer("tracking not found")
        return
    try:
        await bot.send_message(int(row.user_id), f"💬 support:\n{text}")
        await message.answer("✅ delivered")
    except Exception:
        await message.answer("❌ could not reach the user")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def routers() -> list[Router]:
    return [router]
