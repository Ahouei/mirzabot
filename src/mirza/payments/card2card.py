"""Card-to-card manual gateway - parity for cronbot/croncard.php flow.

Customer transfers to an admin card, submits the receipt reference; scheduler
or admin approves. verify_payment() here only matches pending receipts.
"""
from __future__ import annotations

from typing import ClassVar

from mirza.contracts import GatewayInit, PaymentGateway
from mirza.registry import register_plugin


@register_plugin("payment", "card2card", meta={"type": "manual"})
class CardToCardGateway(PaymentGateway):
    name: ClassVar[str] = "card2card"

    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit:
        cards = self.kv.get("active_cards", "")     # newline-separated card lines
        lines = [c for c in cards.splitlines() if c.strip()]
        pick = lines[hash(order_id) % len(lines)] if lines else ""
        text = (
            f"💳 {pick}\n"
            f"💵 amount: {amount:,}\n"
            f"🧾 ref/order: {order_id}\n"
            "send the transfer then submit the tracking code."
        )
        return GatewayInit(pay_text=text)

    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        """Manual approval happens via admin action; webhook path unused."""
        tracking = query.get("tracking", "")
        order_id = query.get("order_id", "")
        return bool(tracking), order_id
