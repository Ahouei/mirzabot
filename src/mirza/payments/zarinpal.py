"""Zarinpal gateway - parity for payment/zarinpal.php (150 lines).

PG v4: /pg/v4/payment/request.json -> StartPay redirect;
callback verifies via /pg/v4/payment/verify.json using Authority.
"""
from __future__ import annotations

from typing import ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin

API = "https://api.zarinpal.com/pg/v4"


@register_plugin("payment", "zarinpal", meta={"type": "online-iran"})
class ZarinpalGateway(PaymentGateway):
    name: ClassVar[str] = "zarinpal"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        payload = {
            "merchant_id": self.kv.get("zarinpal_merchant", ""),
            "amount": amount,                      # Rial/Toman per shop config
            "callback_url": f"{self.callback_base}/pay/zarinpal/callback",
            "description": description[:100],
            "metadata": {"order_id": order_id},
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API}/payment/request.json",
                              json=payload) as resp:
                body = await resp.json(content_type=None)
        data = (body.get("data") or {})
        authority = (data.get("authority") or [None])[0] if isinstance(
            data.get("authority"), list) else data.get("authority")
        if authority:
            url = f"https://www.zarinpal.com/pg/StartPay/{authority}"
            return GatewayInit(redirect_url=url,
                               raw={"authority": authority})
        errors = body.get("errors") or {}
        return GatewayInit(pay_text=f"gateway error: {errors}")

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        authority = query.get("Authority") or query.get("authority") or ""
        if not authority:
            return False, ""
        payload = {
            "merchant_id": self.kv.get("zarinpal_merchant", ""),
            "amount": int(query.get("amount", "0")),
            "authority": authority,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API}/payment/verify.json",
                              json=payload) as resp:
                body = await resp.json(content_type=None)
        code = ((body.get("data") or {}).get("code")) or 0
        ok = code in (100, 101)   # 101 = already verified (idempotent)
        ref = str(query.get("order_id", ""))
        return ok, ref
