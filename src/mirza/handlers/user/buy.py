"""Purchase flow - parity for index.php sell/category/product/invoice steps.

Flow: buy -> category -> product list -> panel (location) pick -> confirm
(price, discount code) -> gateway selection -> payment.
"""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Category, Discount, Product
from mirza.panels.service import PanelService
from mirza.registry import registry

router = Router(name="buy")

# FSM-light: step kept in user.step like legacy; payload in-memory per process
_pending: dict[str, dict] = {}


@router.message(F.text.regexp(r"(?i)(🛒|buy)"))
async def buy_start(message: Message, db_user=None):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Category).order_by(Category.sort_order))
        cats = list(res.scalars().all())
    finally:
        await session.close()
    if not cats:
        await _list_products(message, None)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=c.title, callback_data=f"cat#{c.id}")
    kb.adjust(2)
    await message.answer("🗂", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cat#"))
async def cat_pick(cb: CallbackQuery):
    cat_id = int(cb.data.split("#")[1])
    await _list_products(cb, cat_id)


async def _list_products(target, cat_id: int | None):
    session = get_sessionmaker()()
    try:
        q = sa_select(Product)
        if cat_id is not None:
            q = q.where(Product.category_id == cat_id)
        res = await session.execute(q)
        products = list(res.scalars().all())
    finally:
        await session.close()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p.name_product} — {p.price_product:,}",
                  callback_data=f"prod#{p.code_product}")
    kb.adjust(1)
    text = "🛒 <b>select a plan</b>" if products else "no plans available"
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb.as_markup())
    else:
        await target.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("prod#"))
async def product_pick(cb: CallbackQuery, db_user=None):
    code = cb.data.split("#", 1)[1]
    _pending[str(db_user.id)] = {"code": code}
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ confirm & pay", callback_data=f"buygo#{code}")
    kb.button(text="🎟 discount code", callback_data="discount")
    kb.adjust(1)
    await cb.message.answer("🧾 confirm purchase?", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("buygo#"))
async def buy_confirm(cb: CallbackQuery, db_user=None, bot=None):
    code = cb.data.split("#", 1)[1]
    info = _pending.get(str(db_user.id), {})
    price_off = info.get("discount", 0)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Product).where(Product.code_product == code))
        product = res.scalar_one_or_none()
    finally:
        await session.close()
    if product is None:
        await cb.answer("product missing", show_alert=True)
        return
    price = max(product.price_product - price_off, 0)

    # wallet-first path (parity: legacy offers balance pay when sufficient)
    from mirza.payments.wallet import WalletService
    wsess = get_sessionmaker()()
    try:
        wallet = WalletService(wsess)
        balance = await wallet.get_balance(str(db_user.id))
    finally:
        wsess.close()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    if balance >= price and price > 0:
        kb.button(text="💼 pay with wallet",
                  callback_data=f"paywallet#{code}#{price}")
    for gw in sorted(registry.names("payment")):
        kb.button(text=f"💳 {gw}", callback_data=f"paygw#{gw}#{code}#{price}")
    kb.adjust(1)
    await cb.message.answer(f"💳 total: {price:,}",
                            reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("paywallet#"))
async def pay_wallet(cb: CallbackQuery, db_user=None):
    _, code, price = cb.data.split("#")
    session = get_sessionmaker()()
    try:
        # charge FIRST with an atomic conditional decrement — a config is
        # never provisioned before the money is secured (anti double-spend)
        from mirza.payments.wallet import WalletService
        wallet = WalletService(session)
        change = await wallet.change(str(db_user.id), -int(price), "purchase")
        if not change.ok:
            await session.rollback()
            await cb.message.answer("❌ insufficient funds")
            return
    finally:
        await session.close()

    session = get_sessionmaker()()
    try:
        async with PanelService(session) as panels:
            username = PanelService.generate_username("random", 8,
                                                      prefix="MZ")
            result = await panels.create_user(
                await _default_panel(session), code, username,
                data_limit=await _product_gb(session, code) * 1024 ** 3,
                expire_ts=_in_days(await _product_days(session, code)),
                user_id=str(db_user.id),
                tg_username=db_user.username or "")
            if not result.ok:
                # provision failed: refund the charge in the same breath
                await wallet.change(str(db_user.id), int(price),
                                    "refund", note=f"provision failed {code}")
                await cb.message.answer(f"❌ {result.error}")
                return
    except Exception:
        # panel error after charge: refund so money is never lost
        from mirza.db import get_sessionmaker as _gsm
        rs = _gsm()()
        try:
            from mirza.payments.wallet import WalletService as _W
            await _W(rs).change(str(db_user.id), int(price), "refund",
                                note=f"provision error {code}")
        finally:
            await rs.close()
        raise
    finally:
        await session.close()
    await _deliver(cb.message, result)


@router.callback_query(F.data.startswith("paygw#"))
async def pay_gateway(cb: CallbackQuery, db_user=None, bot=None):
    _, gw_name, code, price = cb.data.split("#")
    from mirza.config import get_settings
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        # pending invoice FIRST so gateway settlement provisions the product
        import secrets as _secrets
        import time as _time

        from mirza.models import Invoice
        prod = await _product_row(session, code)
        inv_token = _secrets.token_hex(10)
        session.add(Invoice(
            id_invoice=inv_token, user_id=str(db_user.id),
            username=db_user.username or "",
            service_location=(prod.location if prod else
                              await _default_panel(session)),
            product_name=code,
            price_product=str(price),
            volume=str(await _product_gb(session, code)),
            service_time=str(await _product_days(session, code)),
            time_sell=_time.strftime("%Y-%m-%d %H:%M:%S"),
            status="pending"))
        await session.commit()

        from mirza.payments.service import PaymentService
        svc = PaymentService(session)
        order = await svc.create_order(str(db_user.id), int(price), gw_name,
                                       invoice_id=inv_token, bot_type="main")
        kv = {
            "zarinpal_merchant": await svc.kv("zarinpal_merchant"),
            "aqayepardakht_pin": await svc.kv("aqayepardakht_pin"),
            "nowpayment_api": await svc.kv("nowpayment_api"),
            "plisio_api": await svc.kv("plisio_api"),
            "iranpay_base": await svc.kv("iranpay_base"),
            "apiiranpay": await svc.kv("apiiranpay"),
            "iranpay2_base": await svc.kv("iranpay2_base"),
            "active_cards": await svc.kv("active_cards"),
        }
    finally:
        await session.close()
    base = f"https://{settings.domain_hosts}"
    gateway = registry.get("payment", gw_name)(kv, callback_base=base)
    init = await gateway.create_payment(order.order_id, int(price),
                                        f"mirza order {code[:12]}")
    if init.redirect_url:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        kb = InlineKeyboardBuilder()
        kb.button(text="💳 پرداخت / Pay", url=init.redirect_url)
        kb.button(text="🔄 check status",
                  callback_data=f"chkorder#{order.order_id}")
        await cb.message.answer("⬇️ complete the payment",
                                reply_markup=kb.as_markup())
    elif init.pay_text:
        await cb.message.answer(init.pay_text)


@router.callback_query(F.data.startswith("chkorder#"))
async def check_order(cb: CallbackQuery, db_user=None):
    oid = cb.data.split("#", 1)[1]
    session = get_sessionmaker()()
    try:
        from mirza.models import PaymentReport
        res = await session.execute(
            sa_select(PaymentReport).where(PaymentReport.order_id == oid))
        order = res.scalar_one_or_none()
    finally:
        await session.close()
    state = order.payment_status if order else "?"
    emoji = {"paid": "✅", "Unpaid": "⏳", "Failed": "❌"}.get(state, "•")
    await cb.answer(f"{emoji} {state}", show_alert=True)


@router.callback_query(F.data == "discount")
async def discount_prompt(cb: CallbackQuery, db_user=None):
    _pending.setdefault(str(db_user.id), {})["await"] = "discount"
    await cb.message.answer("🎟 send the discount code:")


@router.message(F.text & F.text.regexp(r"^[A-Za-z0-9_-]{4,32}$"))
async def discount_code(message: Message, db_user=None):
    info = _pending.get(str(db_user.id)) or {}
    if info.get("await") != "discount":
        return
    info.pop("await", None)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Discount).where(Discount.code == message.text.strip()))
        disc = res.scalar_one_or_none()
    finally:
        await session.close()
    if disc is None or (disc.usage_limit and disc.used_count >= disc.usage_limit):
        await message.answer("❌ invalid/expired code")
        return
    off = disc.price_discount or 0
    info["discount"] = off
    await message.answer(f"🎟 −{off:,} applied. tap your product again to pay.")


# ── helpers ──────────────────────────────────────────────────────
async def _deliver(message: Message, result) -> None:
    lines = ["✅ <b>config ready</b>"]
    if result.subscription_url:
        lines.append(result.subscription_url)
    for link in (result.links or [])[:10]:
        lines.append(f"<code>{link}</code>")
    await message.answer("\n".join(lines))


def _in_days(days: int) -> int:
    import time
    return int(time.time()) + days * 86400


async def _default_panel(session) -> str:
    res = await session.execute(
        sa_select(Product.location).where(Product.location != "/all").limit(1))
    loc = res.scalar_one_or_none()
    return loc or "main"


async def _product_gb(session, code: str) -> int:
    res = await session.execute(
        sa_select(Product.volume_gb).where(Product.code_product == code))
    return res.scalar_one_or_none() or 0


async def _product_row(session, code: str) -> Product | None:
    res = await session.execute(
        sa_select(Product).where(Product.code_product == code))
    return res.scalar_one_or_none()


async def _product_days(session, code: str) -> int:
    res = await session.execute(
        sa_select(Product.service_days).where(Product.code_product == code))
    return res.scalar_one_or_none() or 30


def new_invoice_token() -> str:
    return secrets.token_hex(12)
