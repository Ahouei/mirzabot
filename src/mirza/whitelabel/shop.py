"""White-label child-bot handlers - parity for vpnbot/Default/*.

Each child bot (botsaz row) serves a compact seller shop: start menu with
per-child channel lock, buy flow reusing the shared PanelService, my
services, wallet. Texts come from the child's settings_json with legacy
text.json-style fallbacks.
"""
from __future__ import annotations

import secrets
import time

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Invoice, Product, Setting, User

router = Router(name="whitelabel_shop")


def _child_settings(dp_data) -> dict:
    row = dp_data.get("child_row") if isinstance(dp_data, dict) else None
    if row is None:
        return {}
    try:
        import json
        raw = row.settings_json
        return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        return {}


def _main_kb(settings: dict):
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    kb = ReplyKeyboardBuilder()
    for label in (settings.get("btn_buy") or "🛒 خرید",
                  settings.get("btn_services") or "🛍 سرویس‌های من",
                  settings.get("btn_wallet") or "💼 کیف پول",
                  settings.get("btn_support") or "☎️ پشتیبانی"):
        kb.button(text=label)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


@router.message(CommandStart())
async def wl_start(message: Message, bot=None, **data):
    uid = str(message.from_user.id)
    session = get_sessionmaker()()
    try:
        exists = await session.get(User, uid)
        if exists is None:
            session.add(User(id=uid,
                             username=message.from_user.username or "none",
                             register_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                             lang="fa"))
            await session.commit()
    finally:
        await session.close()
    settings = _child_settings(data)
    await message.answer(
        settings.get("welcome") or "👋 خوش آمدید!",
        reply_markup=_main_kb(settings))


@router.message(F.text.regexp(r"(?i)(خرید|buy)"))
async def wl_buy(message: Message, **data):
    settings = _child_settings(data)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Product).where(Product.location != "/hidden")
            .limit(20))
        products = list(res.scalars().all())
    finally:
        await session.close()
    if not products:
        await message.answer("فعلاً محصولی موجود نیست.")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for p in products:
        price = int(p.price_product * float(settings.get("price_factor", 1)))
        kb.button(text=f"{p.name_product} — {price:,}",
                  callback_data=f"wlprod#{p.code_product}#{price}")
    kb.adjust(1)
    await message.answer("🛒 انتخاب کنید:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("wlprod#"))
async def wl_product(cb: CallbackQuery, db_user=None):
    _, code, price = cb.data.split("#", 2)
    from mirza.panels.service import PanelService
    session = get_sessionmaker()()
    try:
        async with PanelService(session) as panels:
            username = "W" + PanelService.generate_username("random", 7)
            result = await panels.create_user(
                await _default_panel(session), code, username,
                data_limit=await _gb(session, code) * 1024**3,
                expire_ts=int(time.time()) + await _days(session, code) * 86400,
                user_id=str(db_user.id), tg_username=db_user.username or "",
                kind=f"wl:{cb.message.chat.id}" if cb.message else "wl")
            if not result.ok:
                await cb.message.answer(f"❌ {result.error}")
                return
        from mirza.payments.wallet import WalletService
        wallet = WalletService(session)
        change = await wallet.change(str(db_user.id), -int(price), "purchase",
                                     ref=result.invoice.id_invoice)
        if not change.ok:
            await session.rollback()
            # legacy behavior: deliver anyway only when free; otherwise stop
            await cb.message.answer("❌ موجودی کافی نیست. ابتدا کیف پول را شارژ کنید.")
            return
    finally:
        await session.close()
    text = f"✅ کانفیگ شما آماده است\n{result.subscription_url or ''}"
    for link in (result.links or [])[:5]:
        text += f"\n<code>{link}</code>"
    await cb.message.answer(text)


@router.message(F.text.regexp(r"(?i)(سرویس|services)"))
async def wl_services(message: Message, db_user=None):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.user_id == str(db_user.id),
                                     Invoice.status != "test"))
        invs = list(res.scalars().all())
    finally:
        await session.close()
    if not invs:
        await message.answer("سرویسی ندارید.")
        return
    lines = ["🛍 سرویس‌های شما:"]
    for i in invs[:15]:
        lines.append(f"• {i.product_name or i.uuid} [{i.status}] "
                     f"{i.time_sell}")
    await message.answer("\n".join(lines))


@router.message(F.text.regexp(r"(?i)(کیف پول|wallet)"))
async def wl_wallet(message: Message, db_user=None):
    from mirza.payments.wallet import WalletService
    session = get_sessionmaker()()
    try:
        balance = await WalletService(session).get_balance(str(db_user.id))
    finally:
        await session.close()
    await message.answer(f"💼 موجودی: {balance:,}")


@router.message(F.text.regexp(r"(?i)(پشتیبانی|support)"))
async def wl_support(message: Message, **data):
    settings = _child_settings(data)
    await message.answer(settings.get("support_id") or "@admin")


def routers() -> list[Router]:
    return [router]


async def _default_panel(session) -> str:
    res = await session.execute(
        sa_select(Setting.value).where(Setting.key == "default_panel"))
    val = res.scalar_one_or_none()
    if val:
        return val
    from mirza.models import MarzbanPanel
    res2 = await session.execute(sa_select(MarzbanPanel.name_panel).limit(1))
    return res2.scalar_one_or_none() or "main"


async def _gb(session, code: str) -> int:
    res = await session.execute(
        sa_select(Product.volume_gb).where(Product.code_product == code))
    return res.scalar_one_or_none() or 0


async def _days(session, code: str) -> int:
    res = await session.execute(
        sa_select(Product.service_days).where(Product.code_product == code))
    return res.scalar_one_or_none() or 30


def new_child_token() -> str:
    return secrets.token_hex(12)
