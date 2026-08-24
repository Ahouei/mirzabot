"""Wallet / trial / wheel / affiliates / support handlers.

Parity for: accountwallet (wallet menu, top-up), text_usertest (trial),
text_wheel_luck (lucky wheel), text_affiliates (referral system), support.
"""
from __future__ import annotations

import secrets
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Invoice, Setting, User, WheelList
from mirza.panels.service import PanelService

router = Router(name="misc")


# ── wallet ───────────────────────────────────────────────────────
@router.message(F.text.regexp(r"(?i)(💼|کیف پول|Wallet)"))
async def wallet_menu(message: Message, db_user=None):
    session = get_sessionmaker()()
    try:
        from mirza.payments.wallet import WalletService
        wallet = WalletService(session)
        balance = await wallet.get_balance(str(db_user.id))
        history = await wallet.history(str(db_user.id), limit=5)
    finally:
        await session.close()
    lines = [f"💼 balance: {balance:,}"]
    for h in history:
        sign = "+" if h.delta >= 0 else ""
        lines.append(f"• {sign}{h.delta:,} ({h.reason})")
    await message.answer(
        "\n".join(lines),
        reply_markup=_inline_kb([("💳 top-up " + g, f"wtopup#{g}")
                                 for g in ("zarinpal", "iranpay", "card2card")]))


@router.callback_query(F.data.startswith("wtopup#"))
async def wallet_topup(cb: CallbackQuery, db_user=None):
    gw = cb.data.split("#", 1)[1]
    _TOPUP[str(db_user.id)] = {"gateway": gw}
    await cb.message.answer("💵 send the amount to top up:")


_TOPUP: dict[str, dict] = {}


@router.message(F.text.regexp(r"^\d{4,15}$"))
async def topup_amount(message: Message, db_user=None):
    info = _TOPUP.get(str(db_user.id)) or {}
    if not info:
        return
    amount = int(message.text or "0")
    gateway_name = info.pop("gateway", "")
    from mirza.config import get_settings
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        from mirza.payments.service import PaymentService
        svc = PaymentService(session)
        order = await svc.create_order(str(db_user.id), amount,
                                       gateway_name, bot_type="main")
        kv = {"zarinpal_merchant": await svc.kv("zarinpal_merchant"),
              "iranpay_base": await svc.kv("iranpay_base"),
              "apiiranpay": await svc.kv("apiiranpay"),
              "active_cards": await svc.kv("active_cards")}
    finally:
        await session.close()
    from mirza.registry import registry
    base = f"https://{settings.domain_hosts}"
    gateway = registry.get("payment", gateway_name)(kv, callback_base=base)
    init = await gateway.create_payment(order.order_id, amount, "wallet topup")
    if init.redirect_url:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="💳 پرداخت / Pay", url=init.redirect_url)
        await message.answer("⬇️ complete payment",
                             reply_markup=kb.as_markup())
    else:
        await message.answer(init.pay_text or "gateway error")


# ── trial config (usertest) ──────────────────────────────────────
@router.message(F.text.regexp(r"(?i)(🎁|تستی|trial)"))
async def free_trial(message: Message, db_user=None):
    uid = str(db_user.id)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.user_id == uid,
                                     Invoice.status == "test"))
        already = res.scalars().first()
        res2 = await session.execute(
            sa_select(Setting.value_json).where(Setting.key == "test_limits"))
        limits = res2.scalar_one_or_none() or {"free": 1}
    finally:
        await session.close()
    if already is not None or limits.get("free", 1) <= 0:
        await message.answer("❌ trial already used / disabled")
        return
    async with PanelService() as panels:
        username = "T" + PanelService.generate_username("random", 7)
        result = await panels.create_user(
            await _first_test_panel(), "", username,
            data_limit=1 * 1024 ** 3,          # 1 GB default; panel overrides apply
            expire_ts=int(time.time()) + 3 * 86400,
            user_id=uid, tg_username=db_user.username or "", kind="test")
    if result.ok:
        session = get_sessionmaker()()
        try:
            inv = result.invoice
            inv.status = "test"
            session.add(inv)
            await session.commit()
        finally:
            await session.close()
        await message.answer(f"🎁 trial ready\n{result.subscription_url or ''}")
    else:
        await message.answer(f"❌ {result.error}")


async def _first_test_panel() -> str | None:
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Setting.value).where(Setting.key == "default_panel"))
        val = res.scalar_one_or_none()
        return val
    finally:
        await session.close()


# ── lucky wheel ──────────────────────────────────────────────────
WHEEL_PRIZES = [0, 5_000, 10_000, 20_000, 50_000]


@router.message(F.text.regexp(r"(?i)(🎡|گردونه|wheel)"))
async def lucky_wheel(message: Message, db_user=None):
    uid = str(db_user.id)
    today = time.strftime("%Y-%m-%d")
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(WheelList).where(WheelList.user_id == uid))
        spins = list(res.scalars())
        if any(s.spun_at == today for s in spins):
            await message.answer("🎡 come back tomorrow!")
            return
        prize = secrets.choice(WHEEL_PRIZES)
        session.add(WheelList(user_id=uid, spun_at=today,
                              first_name=message.from_user.first_name,
                              wheel_code=secrets.token_hex(4), prize=prize))
        await session.commit()
    finally:
        await session.close()
    if prize > 0:
        from mirza.payments.wallet import WalletService
        wsess = get_sessionmaker()()
        try:
            await WalletService(wsess).change(uid, prize, "wheel")
        finally:
            wsess.close()
        await message.answer(f"🎉 you won {prize:,}!")
    else:
        await message.answer("😕 no luck — try tomorrow")


# ── referrals ────────────────────────────────────────────────────
@router.message(F.text.regexp(r"(?i)(👥|زیرمجموعه|Referral)"))
async def affiliates(message: Message, db_user=None, bot=None):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{db_user.id}"
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(User).where(User.referrer_id == str(db_user.id)))
        refs = len(list(res.scalars().all()))
    finally:
        await session.close()
    await message.answer(
        f"👥 your link:\n{link}\nreferred users: {refs}")


# ── support ──────────────────────────────────────────────────────
@router.message(F.text.regexp(r"(?i)(☎️|پشتیبانی|Support)"))
async def support(message: Message, db_user=None):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Setting.value).where(Setting.key == "support_id"))
        sid = res.scalar_one_or_none()
    finally:
        await session.close()
    await message.answer(f"☎️ support: {sid or '@admin'}")


def _inline_kb(items: list[tuple[str, str]]):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for label, data in items:
        kb.button(text=label, callback_data=data)
    kb.adjust(1)
    return kb.as_markup()
