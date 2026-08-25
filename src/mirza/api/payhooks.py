"""Payment gateway webhook handlers - parity for pay/*.php callback pages.

Every handler: parse -> gateway.verify_payment() -> claim_paid() (idempotent)
-> settle (direct buy or wallet top-up) -> notify user + report channel.
"""
from __future__ import annotations

import logging

from aiohttp import web
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import PaymentReport, Setting

log = logging.getLogger(__name__)


def _base_url() -> str:
    from mirza.config import get_settings
    return f"https://{get_settings().domain_hosts}"


async def _kv(session, names: list[str]) -> dict[str, str]:
    from mirza.models import PaySetting
    res = await session.execute(
        sa_select(PaySetting.name_pay, PaySetting.value_pay)
        .where(PaySetting.name_pay.in_(names)))
    return {k: v or "" for k, v in res.all()}


async def _notify_user(bot, uid: str, text: str) -> None:
    if bot is None:
        return
    try:
        await bot.send_message(int(uid), text, parse_mode="HTML")
    except Exception:
        log.debug("notify failed for %s", uid)


def _app_bot(request: web.Request | None) -> object | None:
    """Bot handle stashed on the aiohttp app at startup (None in tests)."""
    if request is None:
        return None
    return request.app.get("bot")


async def _report(s, kind: str, text: str, bot=None) -> None:
    """Post a payment report to the configured channel/topic."""
    try:
        res = await s.execute(
            sa_select(Setting.value).where(Setting.key == "Channel_Report"))
        chat = res.scalar_one_or_none()
        if not chat or bot is None:
            log.info("payment report (%s) not deliverable: chat=%r bot=%r",
                     kind, chat, bot is not None)
            return
        await bot.send_message(chat, text)
    except Exception:
        # never fail the webhook over reporting; but make it loud
        log.exception("payment report delivery failed (%s)", kind)


async def settle_tuple(request_body: bytes, query: dict[str, str],
                       gateway_name: str, kv_extra: list[str]) -> tuple[bool, str]:
    """Verify + idempotent settle; returns (paid, order_id)."""
    from mirza.payments.service import PaymentService
    from mirza.registry import registry
    session = get_sessionmaker()()
    try:
        svc = PaymentService(session)
        kv = await _kv(session, kv_extra)
        gateway = registry.get("payment", gateway_name)(kv,
                                                        callback_base=_base_url())
        ok, order_id = await gateway.verify_payment(request_body, query)
        if not ok or not order_id:
            return False, order_id
        order = await svc.get_order(order_id)
        if order is None:
            return False, order_id
        if not await svc.claim_paid(order_id):
            return True, order_id   # replay: already settled
        if order.invoice_id:
            result = await svc.settle_direct_buy(order)
            text = f"✅ config ready\n{result.subscription_url or ''}" \
                if result and result.ok else "✅ payment received"
        else:
            await svc.settle_wallet_topup(order)
            text = f"💼 wallet topped up by {order.price:,}"
        await _notify_user(None, order.user_id, text)
        return True, order_id
    finally:
        await session.close()


async def settle(request_body: bytes, query: dict[str, str],
                 gateway_name: str, kv_extra: list[str],
                 request: web.Request | None = None) -> web.Response:
    from mirza.payments.service import PaymentService
    from mirza.registry import registry
    bot = _app_bot(request)
    session = get_sessionmaker()()
    try:
        svc = PaymentService(session)
        kv = await _kv(session, kv_extra)
        gateway = registry.get("payment", gateway_name)(kv,
                                                        callback_base=_base_url())
        ok, order_id = await gateway.verify_payment(request_body, query)
        if not ok or not order_id:
            return web.Response(text="not paid", status=400)
        order = await svc.get_order(order_id)
        if order is None:
            return web.Response(text="order missing", status=404)
        if not await svc.claim_paid(order_id):
            return web.Response(text="already processed")   # idempotent replay
        if order.invoice_id:
            result = await svc.settle_direct_buy(order)
            text = f"✅ config ready\n{result.subscription_url or ''}" \
                if result and result.ok else "✅ payment received"
        else:
            await svc.settle_wallet_topup(order)
            text = f"💼 wallet topped up by {order.price:,}"
        await _notify_user(bot, order.user_id, text)
        await _report(session, "paymentreport",
                      f"💳 {gateway_name} | {order.user_id} | "
                      f"{order.price:,} | {order_id}", bot=bot)
        return web.Response(text="OK")
    finally:
        await session.close()


async def plisio_callback(request: web.Request) -> web.Response:
    body = await request.read()
    q = dict(request.rel_url.query)
    return await settle(body, q, "plisio",
                        ["plisio_api"], request=request)


async def nowpayment_callback(request: web.Request) -> web.Response:
    body = await request.read()
    q = {"order_id": ""}
    import json as _j
    try:
        data = _j.loads(body)
        q["order_id"] = str(data.get("order_id", ""))
    except Exception:
        pass
    return await settle(body, q, "nowpayments", ["nowpayment_api"],
                        request=request)


async def zarinpal_callback(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    q.setdefault("amount", q.get("amount", "0"))
    return await settle(b"", q, "zarinpal", ["zarinpal_merchant"],
                        request=request)


async def aqaye_callback(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    return await settle(b"", q, "aqayepardakht", ["aqayepardakht_pin"],
                        request=request)


async def iranpay_callback(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    return await settle(b"", q, "iranpay",
                        ["iranpay_base", "apiiranpay"], request=request)


async def cubepay_callback(request: web.Request) -> web.Response:
    """CubePay: POST = signed gateway callback (JSON ack), GET = browser
    redirect -> customer-facing HTML result card (legacy cubepay_emit)."""
    import json as _json

    from mirza.payments.cubepay import result_page

    is_browser = (request.method == "GET"
                  and "text/html" in request.headers.get("Accept", "").lower())
    body = await request.read() if request.method == "POST" else b""
    q = dict(request.rel_url.query)

    order_id = ""
    try:
        parsed = _json.loads(body) if body else {}
        if isinstance(parsed, dict):
            order_id = str(parsed.get("order_id", ""))
    except Exception:
        pass
    order_id = order_id or q.get("order_id", "")

    from mirza.config import get_settings
    settings = get_settings()
    session = get_sessionmaker()()
    try:
        from mirza.models import PaySetting, User
        res = await session.execute(
            sa_select(PaySetting.name_pay, PaySetting.value_pay)
            .where(PaySetting.name_pay.in_(
                ["apiternado", "feeternado", "feestatusternado",
                 "chashbackiranpay2"])))
        kv = {k: v or "" for k, v in res.all()}
        price = 0.0
        payer_lang = "fa"
        order_status = ""
        if order_id:
            res2 = await session.execute(
                sa_select(PaymentReport).where(
                    PaymentReport.order_id == order_id))
            order = res2.scalar_one_or_none()
            if order:
                # signed path compares against payable amount incl. fee
                from mirza.payments.cubepay import payable_amount
                price = float(payable_amount(order.price, kv))
                order_status = order.payment_status
                res3 = await session.execute(
                    sa_select(User.lang).where(User.id == order.user_id))
                payer_lang = res3.scalar_one_or_none() or "fa"
    finally:
        await session.close()

    verify_q = dict(q)
    verify_q["_order_price"] = str(price)
    paid, _oid = await settle_tuple(body, verify_q, "cubepay", list(kv))

    if not is_browser:
        return web.json_response({"status": bool(paid)})

    if order_status == "paid":
        state = "already"
    elif order_status == "expire":
        state = "expired"
    else:
        state = "success" if paid else "failed"
    html_card = result_page(
        state, lang=payer_lang, order_id=order_id or None,
        price=price or None,
        bot_username=settings.username_bot,
        texts={})
    return web.Response(text=html_card, content_type="text/html")
