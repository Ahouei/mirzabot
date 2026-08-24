"""Aqayepardakht gateway - parity for payment/aqayepardakht.php (140 lines)."""
from __future__ import annotations

from typing import ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin

API = "https://panel.aqayepardakht.ir/api/v2"


@register_plugin("payment", "aqayepardakht", meta={"type": "online-iran"})
class AqayePardakhtGateway(PaymentGateway):
    name: ClassVar[str] = "aqayepardakht"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        payload = {
            "pin": self.kv.get("aqayepardakht_pin", ""),
            "amount": amount,
            "callback": f"{self.callback_base}/pay/aqayepardakht/callback",
            "invoice_id": order_id,
            "description": description[:100],
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API}/create", json=payload) as resp:
                body = await resp.json(content_type=None)
        if body.get("code") in ("1", 1) and body.get("transid"):
            return GatewayInit(
                redirect_url=f"https://panel.aqayepardakht.ir/startpay/"
                             f"{body['transid']}",
                raw={"transid": body["transid"]})
        return GatewayInit(pay_text=f"gateway error: {body.get('code')}")

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        transid = query.get("transid", "")
        order_id = query.get("invoice_id", "")
        if not transid:
            return False, order_id
        payload = {
            "pin": self.kv.get("aqayepardakht_pin", ""),
            "amount": int(query.get("amount", "0")),
            "transid": transid,
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{API}/verify", json=payload) as resp:
                body = await resp.json(content_type=None)
        ok = str(body.get("code")) == "1"
        if str(body.get("code")) == "70":   # already verified
            ok = True
        return ok, order_id
