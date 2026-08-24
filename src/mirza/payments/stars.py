"""Telegram Stars (XTR) payments - parity for index.php startelegrams flow.

Legacy: createInvoiceLink(currency=XTR) with star amount derived from
Toman->USD->stars conversion (rate_arze), min/max range check, then
pre_checkout_query ack + successful_payment -> DirectPayment + cashback.

Rewrite: native aiogram invoice link, same conversion math, atomic
claim_paid settlement via PaymentService.
"""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery, Message, PreCheckoutQuery, SuccessfulPayment)
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import PaySetting, PaymentReport, Setting
from mirza.registry import registry

router = Router(name="stars")

STARS_PER_USD_FALLBACK = 50   # ≈ $0.02/star; legacy used usd*0.016 per star


async def _rate_usd() -> float | None:
    """USD/Toman rate; legacy rate_arze() equivalent (cached upstream API)."""
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Setting.value).where(Setting.key == "usd_rate"))
        raw = res.scalar_one_or_none()
    finally:
        await session.close()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def stars_for(amount_toman: int, usd_rate: float) -> int:
    """Legacy math: starAmount = usd * 0.016; stars = toman / starAmount."""
    per_star_toman = usd_rate * 0.016
    return max(int(amount_toman / per_star_toman), 1)


@router.callback_query(F.data == "startelegrams")
async def stars_start(cb: CallbackQuery, db_user=None):
    _PENDING[str(db_user.id)] = {"gateway": "stars"}
    await cb.message.answer("💫 send the amount (Toman):")


_PENDING: dict[str, dict] = {}


@router.message(F.text.regexp(r"^\d{4,15}$"))
async def stars_amount(message: Message, db_user=None, bot=None):
    info = _PENDING.get(str(db_user.id)) or {}
    if info.pop("gateway", None) != "stars":
        return
    amount = int(message.text or "0")
    session = get_sessionmaker()()
    try:
        def kv_q(name: str):
            return sa_select(PaySetting.value_pay).where(
                PaySetting.name_pay == name)
        lo = session.execute(kv_q("minbalancestar")).scalar_one_or_none()
        hi = session.execute(kv_q("maxbalancestar")).scalar_one_or_none()
    finally:
        await session.close()
    lo = int(lo or 0)
    hi = int(hi or 10**12)
    if not (lo <= amount <= hi):
        await message.answer(f"⚠️ allowed range: {lo:,} – {hi:,}")
        return
    usd = await _rate_usd()
    if usd is None:
        # fall back to fixed stars-per-usd so the feature still works offline
        stars = max(int(amount / 600 / (1 / STARS_PER_USD_FALLBACK)), 1)
    else:
        stars = stars_for(amount, usd)
    order_id = secrets.token_hex(5)
    session = get_sessionmaker()()
    try:
        session.add(PaymentReport(
            order_id=order_id, user_id=str(db_user.id),
            created_at=_now_iso(), price=amount,
            payment_status="Unpaid", payment_method="Star Telegram",
            gateway_payload={"stars": stars}))
        await session.commit()
    finally:
        await session.close()
    link = await _invoice_link(bot, order_id, amount, stars)
    if not link:
        await message.answer("❌ could not create Stars invoice")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="💫 Pay with Stars", url=link)
    await message.answer(
        f"💫 {order_id}\nstars: {stars} ⭐️\namount: {amount:,}",
        reply_markup=kb.as_markup())


async def _invoice_link(bot, payload: str, amount: int,
                        stars: int) -> str | None:
    if bot is None:
        return None
    from aiogram.methods import CreateInvoiceLink
    try:
        return await bot(CreateInvoiceLink(
            title=f"Top-up {amount:,}",
            description="Mirza wallet top-up",
            payload=payload,
            currency="XTR",
            prices=[{"label": "Price", "amount": stars}],
        ))
    except Exception:
        return None


# ── checkout lifecycle ───────────────────────────────────────────
@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery, bot=None):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(PaymentReport).where(
                PaymentReport.order_id == q.invoice_payload))
        exists = res.scalar_one_or_none() is not None
    finally:
        await session.close()
    await q.answer(ok=exists)


@router.message(F.successful_payment)
async def successful_payment(message: Message, db_user=None):
    sp: SuccessfulPayment = message.successful_payment
    order_id = sp.invoice_payload
    from mirza.payments.service import PaymentService
    session = get_sessionmaker()()
    try:
        svc = PaymentService(session)
        order = await svc.get_order(order_id)
        if order is None:
            return
        order.gateway_payload = {
            **(order.gateway_payload or {}),
            "telegram_charge_id": sp.telegram_payment_charge_id,
            "stars": sp.total_amount,
        }
        if not await svc.claim_paid(order_id):
            return   # replay guard (legacy paid-check parity)
        result = None
        if order.invoice_id:
            result = await svc.settle_direct_buy(order)
        else:
            cashback_kv = await svc.kv("chashbackstar", "0")
            pct = int(cashback_kv or 0)
            await svc.settle_wallet_topup(order, cashback_pct=pct)
        await session.commit()
    finally:
        await session.close()
    if result is not None and getattr(result, "ok", False):
        await message.answer(
            f"✅ config ready\n{result.subscription_url or ''}")
    else:
        await message.answer(f"💼 wallet topped up ({sp.total_amount} ⭐️)")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def routers() -> list[Router]:
    return [router]
