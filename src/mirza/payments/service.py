"""Payment service - order lifecycle shared by all gateways.

Parity for the scattered DirectPayment/claimPaymentPaid logic:
- create_order(): writes an Unpaid Payment_report row
- claim_paid(): atomic Unpaid->paid transition (idempotency guard)
- settle(): delivers the product (direct buy) or tops up wallet
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update

from mirza.models import Invoice, PaymentReport, PaySetting
from mirza.panels.service import PanelService, ProvisionResult


class PaymentService:
    def __init__(self, session):
        self.session = session

    # ── settings ──────────────────────────────────────────────────
    async def kv(self, name: str, default: str = "") -> str:
        res = await self.session.execute(
            sa_select(PaySetting.value_pay).where(PaySetting.name_pay == name))
        return res.scalar_one_or_none() or default

    # ── orders ────────────────────────────────────────────────────
    async def create_order(self, user_id: str, amount: int, method: str,
                           invoice_id: str | None = None,
                           bot_type: str | None = None) -> PaymentReport:
        order = PaymentReport(
            order_id=secrets.token_hex(10),
            user_id=user_id,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            price=amount,
            payment_method=method,
            payment_status="Unpaid",
            invoice_id=invoice_id,
            bot_type=bot_type,
        )
        self.session.add(order)
        await self.session.commit()
        return order

    async def get_order(self, order_id: str) -> PaymentReport | None:
        res = await self.session.execute(
            sa_select(PaymentReport).where(PaymentReport.order_id == order_id))
        return res.scalar_one_or_none()

    async def claim_paid(self, order_id: str) -> bool:
        """Atomic Unpaid->Paid. Returns False when already claimed."""
        res = await self.session.execute(
            sa_update(PaymentReport)
            .where(PaymentReport.order_id == order_id,
                   PaymentReport.payment_status == "Unpaid")
            .values(payment_status="paid",
                    updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            .returning(PaymentReport.id))
        claimed = res.scalar_one_or_none()
        await self.session.commit()
        return claimed is not None

    async def mark_failed(self, order_id: str) -> None:
        await self.session.execute(
            sa_update(PaymentReport)
            .where(PaymentReport.order_id == order_id)
            .values(payment_status="Failed",
                    updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        await self.session.commit()

    # ── settlement ────────────────────────────────────────────────
    async def settle_direct_buy(self, order: PaymentReport) -> ProvisionResult | None:
        """Deliver the config attached to a direct-buy order.

        Resolves the product row (authoritative volume/days/panel) rather
        than trusting free-text invoice fields, and converts GB to bytes.
        """
        if not order.invoice_id:
            return None
        res = await self.session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == order.invoice_id))
        inv = res.scalar_one_or_none()
        if inv is None:
            return None

        from mirza.models import Product
        product: Product | None = None
        if inv.product_name:
            product = (await self.session.execute(
                sa_select(Product).where(
                    Product.code_product == inv.product_name)
            )).scalar_one_or_none()

        volume_gb = float(product.volume_gb) if product else 0.0
        if not volume_gb:
            try:
                raw = abs(float(inv.volume or 0))
                volume_gb = raw if raw <= 1000 else raw / (1024 ** 3)
            except ValueError:
                volume_gb = 0.0
        data_limit = int(volume_gb * 1024 ** 3)

        days = float(product.service_days) if product else 30.0
        if not product:
            try:
                days = float(str(inv.service_time or "30")
                             .replace("D", "").replace("d", "").strip())
            except ValueError:
                days = 30.0
        location = (product.location if product else None) \
            or inv.service_location
        code = product.code_product if product else (inv.product_name or "")

        async with PanelService() as panels:
            result = await panels.create_user(
                location,
                code,
                inv.uuid or "",
                data_limit=data_limit,
                expire_ts=_now_ts() + int(days * 86400),
                user_id=order.user_id,
                tg_username=inv.username or "",
                kind="buy",
            )
        if result.ok and result.subscription_url:
            inv.user_info = {**(inv.user_info or {}),
                             "sub_url": result.subscription_url}
            # M7: on-hold products start their clock at activation. The
            # Product model has no on-hold flag yet (panel-level on_hold_test
            # lives on MarzbanPanel); wire it via panel row until a product
            # column exists.
            inv.status = "enable"
            await self.session.commit()
        return result

    async def settle_wallet_topup(self, order: PaymentReport,
                                  cashback_pct: int = 0) -> int | None:
        """Credit a paid top-up (+ optional cashback %) to the buyer's wallet.

        The claim_paid() gate already guarantees single settlement; the
        ledger ref makes any double-call visible in the audit trail.
        Returns the new balance, or None when the credit was refused.
        """
        from mirza.payments.wallet import WalletService
        wallet = WalletService(self.session)
        change = await wallet.change(
            order.user_id, order.price, reason="topup", ref=order.order_id)
        if not change.ok:
            return None
        if cashback_pct:
            bonus = order.price * cashback_pct // 100
            if bonus > 0:
                await wallet.change(order.user_id, bonus, reason="cashback",
                                    ref=order.order_id)
        return change.new_balance


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())
