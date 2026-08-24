"""Plisio crypto gateway - parity for cronbot/plisio.php (70 lines).

Invoice-based: create invoice -> poll status until 'completed'.
"""
from __future__ import annotations

from typing import Any, ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin

API = "https://plisio.net/api/v1"


@register_plugin("payment", "plisio", meta={"type": "crypto"})
class PlisioGateway(PaymentGateway):
    name: ClassVar[str] = "plisio"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        params = {
            "source_currency": "USD",
            "source_amount": max(round(amount / 1_000_000, 2), 1.0),
            "order_number": order_id,
            "order_name": description[:60],
            "callback_url": f"{self.callback_base}/pay/plisio/callback",
            "success_url": f"{self.callback_base}/pay/plisio/success",
            "api_token": self.kv.get("plisio_api", ""),
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API}/invoices/new", params=params) as resp:
                body: dict[str, Any] = await resp.json(content_type=None)
        data = body.get("data") or {}
        if data.get("invoice_url") or data.get("id"):
            return GatewayInit(redirect_url=data.get("invoice_url"),
                               raw={"invoice_id": data.get("id"), **data})
        return GatewayInit(pay_text="gateway error", raw=body)

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        track = query.get("track", "") or query.get("invoice_id", "")
        order_id = query.get("order_number", "")
        if not track:
            return False, order_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API}/operations/{track}",
                             params={"api_token": self.kv.get("plisio_api", "")}) as resp:
                body = await resp.json(content_type=None)
        status = (body.get("data") or {}).get("status", "")
        return status == "completed", order_id
