"""CubePay (TRON / crypto, cubevps.ir) gateway - parity for the late-upstream
payment/iranpay2.php + function.php trnado()/cubepay* fee helpers.

Two verification paths (both ported):
1. Signed callback: sig = HMAC-SHA256(order_id|status|amount, token),
   accepted when status=='paid' and amount >= price.
2. Authority verify: POST /smspay/api/verify-payment.php; HTTP 200+success or
   409 counts as verified when order_id matches and amount >= price*10 (rial).

Also ports the optional customer-paid fee (percent <=100 or flat amount).
"""
from __future__ import annotations

import hashlib
import hmac
import math
from typing import Any, ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin

BASE = "https://cubevps.ir"


def _fee_value(kv: dict[str, str]) -> float:
    raw = kv.get("feeternado", "0") or "0"
    try:
        return float(str(raw).replace(",", "").replace("،", ""))
    except ValueError:
        return 0.0


def _apply_fee(base: int, fee: float) -> int:
    base = int(base)
    if fee <= 0:
        return base
    return int(math.ceil(base * (1 + fee / 100))) if fee <= 100 \
        else base + int(round(fee))


def payable_amount(price: int, kv: dict[str, str]) -> int:
    if kv.get("feestatusternado") != "onfeeternado":
        return int(price)
    return _apply_fee(int(price), _fee_value(kv))


@register_plugin("payment", "cubepay", meta={"type": "crypto-tron"})
class CubePayGateway(PaymentGateway):
    name: ClassVar[str] = "cubepay"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        payload = {
            "price_amount": payable_amount(amount, self.kv),
            "order_id": order_id,
            "callback_url": f"{self.callback_base}/pay/cubepay/callback",
        }
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.kv.get('apiternado', '')}"}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{BASE}/pay/create-order.php", json=payload,
                              headers=headers) as resp:
                body: dict[str, Any] = await resp.json(content_type=None)
        link = body.get("payment_link") or body.get("pay_page_url")
        if link:
            return GatewayInit(redirect_url=link,
                               raw={"payable": payload["price_amount"], **body})
        return GatewayInit(pay_text="gateway error", raw=body)

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        """Callback check only; page rendering lives in api/payhooks."""
        import json as _json
        try:
            data = _json.loads(request_body) if request_body else {}
        except Exception:
            data = {}
        data.update(query)

        order_id = str(data.get("order_id", ""))
        token = self.kv.get("apiternado", "")
        price = float(data.get("_order_price", "0") or 0)
        status = str(data.get("status", ""))
        amount_raw = data.get("amount_toman", data.get("amount", ""))
        sig = str(data.get("sig", ""))

        # path 1: signed callback
        if sig and order_id:
            expected = hmac.new(
                token.encode(),
                f"{order_id}|{status}|{amount_raw}".encode(),
                hashlib.sha256).hexdigest()
            signed_ok = hmac.compare_digest(expected, sig)
            ok = (signed_ok and status == "paid"
                  and amount_raw != ""
                  and float(amount_raw) >= price > 0)
            return ok, order_id

        # path 2: authority verify against the API
        authority = str(data.get("authority", ""))
        if not authority or not order_id:
            return False, order_id
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{BASE}/smspay/api/verify-payment.php",
                              json={"authority": authority},
                              headers=headers) as resp:
                http_status = resp.status
                body: dict[str, Any] = await resp.json(content_type=None)
        amount_rial = int(price) * 10
        matches_order = (str(body.get("order_id", "")) == order_id
                         and int(body.get("amount", 0)) >= amount_rial)
        ok = ((http_status == 200 and bool(body.get("success")))
              or http_status == 409) and matches_order
        return ok, order_id


def result_page(state: str, *, lang: str = "fa", order_id: str | None = None,
                price: float | None = None, bot_username: str = "",
                texts: dict[str, str] | None = None) -> str:
    """Customer-facing HTML result card (parity for cubepay_emit)."""
    t = texts or {}
    def pick(key: str, fb: str) -> str:
        return t.get(key) or fb

    meta = {
        "success": ("✓", "#2ecc71",
                    pick("resultSuccessTitle", "Payment completed"),
                    pick("resultSuccessText", "")),
        "already": ("✓", "#2ecc71",
                    pick("resultAlreadyTitle", "Already confirmed"),
                    pick("resultAlreadyText", "")),
        "failed": ("✕", "#e74c3c",
                   pick("resultFailedTitle", "Payment was not confirmed"),
                   pick("resultFailedText", "")),
        "expired": ("⏱", "#e67e22",
                    pick("resultExpiredTitle", "This payment has expired"),
                    pick("resultExpiredText", "")),
        "notfound": ("?", "#e67e22",
                     pick("resultNotFoundTitle", "Transaction not found"),
                     pick("resultNotFoundText", "")),
    }
    icon, colour, title, body = meta.get(state, meta["failed"])
    import html as _html
    esc = lambda v: _html.escape(str(v), quote=True)  # noqa: E731

    rows = ""
    if order_id:
        rows += (f"<div class=row><span>{esc(pick('resultOrderLabel', 'Order id'))}"
                 f"</span><b>{esc(order_id)}</b></div>")
    if price:
        rows += (f"<div class=row><span>{esc(pick('resultAmountLabel', 'Amount'))}"
                 f"</span><b>{float(price):,.0f}</b></div>")
    bot_link = ""
    handle = bot_username.lstrip("@").strip()
    if handle and "{" not in handle:
        bot_link = (f'<a class=btn href="https://t.me/{esc(handle)}">'
                    f"{esc(pick('resultBackToBot', 'Back to the bot'))}</a>")
    direction = "rtl" if lang in ("fa", "ar") else "ltr"
    align = "right" if direction == "rtl" else "left"
    return (
        f'<!DOCTYPE html><html lang="{esc(lang)}" dir={direction}><head>'
        f'<meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title><style>"
        "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
        "background:#0f1115;color:#e8eaed;font-family:Tahoma,Arial,sans-serif;padding:20px}"
        ".card{width:100%;max-width:360px;background:#181b21;border:1px solid #262a33;"
        "border-radius:18px;padding:28px 24px;text-align:center}"
        ".icon{width:58px;height:58px;line-height:58px;border-radius:50%;margin:0 auto 14px;"
        "font-size:28px;color:#fff;background:" + colour + "}"
        "h1{font-size:17px;margin:0 0 8px}p{color:#9aa0aa;font-size:13px;line-height:2;margin:0}"
        ".row{display:flex;justify-content:space-between;gap:12px;font-size:12.5px;"
        "border-top:1px solid #262a33;padding:9px 0;color:#9aa0aa}.row b{color:#e8eaed}"
        f".rows{{margin-top:18px;text-align:{align}}}"
        ".btn{display:block;margin-top:18px;padding:11px;border-radius:11px;background:#2b6ef2;"
        'color:#fff;text-decoration:none;font-size:13.5px}'
        f'</style></head><body><div class=card><div class=icon>{icon}</div>'
        f"<h1>{esc(title)}</h1><p>{esc(body)}</p>"
        + (f"<div class=rows>{rows}</div>" if rows else "")
        + bot_link + "</div></body></html>")
