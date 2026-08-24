"""NowPayments crypto gateway - parity for payment/nowpayment.php (48 lines).

Webhook POST {payment_status: finished, payment_id, invoice_id}; status is
double-checked against the API before settling (legacy behavior kept).
"""
from __future__ import annotations

import json
from typing import Any, ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin

API = "https://api.nowpayments.io/v1"


@register_plugin("payment", "nowpayments", meta={"type": "crypto"})
class NowPaymentsGateway(PaymentGateway):
    name: ClassVar[str] = "nowpayments"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        payload = {
            "price_amount": max(round(amount / 1_000_000, 2), 1.0),
            "price_currency": "usd",
            "order_id": order_id,
            "order_description": description[:120],
            "ipn_callback_url": f"{self.callback_base}/pay/nowpayment/callback",
            "success_url": f"{self.callback_base}/pay/nowpayment/success",
        }
        headers = {"x-api-key": self.kv.get("nowpayment_api", "")}
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API}/invoice", json=payload,
                              headers=headers) as resp:
                body: dict[str, Any] = await resp.json(content_type=None)
        if body.get("invoice_url") or body.get("id"):
            return GatewayInit(redirect_url=body.get("invoice_url"),
                               raw={"payment_id": body.get("id"), **body})
        return GatewayInit(pay_text="gateway error", raw=body)

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        try:
            data = json.loads(request_body)
        except Exception:
            return False, ""
        if data.get("payment_status") != "finished":
            return False, str(data.get("order_id", ""))
        pid = data.get("payment_id")
        headers = {"x-api-key": self.kv.get("nowpayment_api", "")}
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API}/payment/{pid}", headers=headers) as resp:
                check: dict[str, Any] = await resp.json(content_type=None)
        ok = check.get("payment_status") == "finished"
        return ok, str(data.get("order_id", ""))
