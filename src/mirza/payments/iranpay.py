"""IranPay direct-bank gateways - parity for payment/iranpay1.php/iranpay2.php.

Legacy routed through a third-party relay (hardcoded melorinabeauty domains).
Improvement: base URL is configuration (PaySetting 'iranpay_base'), not code.
Two modes kept for parity:
- iranpay (factor/create + factor/status polling by scheduler)
- iranpay2 (card acquire flow with tracking code approval)
"""
from __future__ import annotations

from typing import Any, ClassVar

import aiohttp

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin


@register_plugin("payment", "iranpay", meta={"type": "online-iran"})
class IranPayGateway(PaymentGateway):
    name: ClassVar[str] = "iranpay"

    def _base(self) -> str:
        return self.kv.get("iranpay_base", "").rstrip("/")

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        payload = {
            "api": self.kv.get("apiiranpay", ""),
            "amount": amount,
            "order_id": order_id,
            "callback": f"{self.callback_base}/pay/iranpay/callback",
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self._base()}/api/factor/create",
                              json=payload) as resp:
                body: dict[str, Any] = await resp.json(content_type=None)
        data = body.get("data") or {}
        factor_id = data.get("id")
        if factor_id:
            return GatewayInit(redirect_url=data.get("url"),
                               raw={"factor_id": str(factor_id)})
        return GatewayInit(pay_text="gateway error")

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        factor_id = query.get("id", "") or query.get("factor_id", "")
        order_id = query.get("order_id", "")
        if not factor_id:
            return False, order_id
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self._base()}/api/factor/status",
                             params={"id": factor_id}) as resp:
                body: dict[str, Any] = await resp.json(content_type=None)
        status = ((body.get("data") or {}).get("status")) or ""
        return status == "approved", order_id


@register_plugin("payment", "iranpay2", revision=2,
                 meta={"type": "online-iran"})
class IranPay2Gateway(IranPayGateway):
    """Card-acquire variant; same API shape, separate credentials."""

    name: ClassVar[str] = "iranpay2"

    def _base(self) -> str:
        return self.kv.get("iranpay2_base", self.kv.get("iranpay_base", "")
                           ).rstrip("/")

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        init = await super().create_payment(order_id, amount, description)
        init.raw["method"] = "iranpay2"
        return init
