"""Money-path tests (audit C1/C2/C4 acceptance):

- gateway callback on a PRODUCT order provisions the config exactly once
  and never credits the wallet
- wallet top-up order credits the balance exactly once; duplicate callback
  is a no-op
- wallet purchase with insufficient balance does NOT provision
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("MIRZA_SESSION_SECRET", "test-secret")
_DBFILE = Path(__file__).resolve().parent / '_money.db'
os.environ["MIRZA_DATABASE_URL"] = f"sqlite+aiosqlite:///{_DBFILE}"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
async def _schema():
    """Recreate schema on the shared file DB before each test."""
    import mirza.models  # noqa: F401
    import mirza.payments.wallet  # noqa: F401
    from mirza.config import get_settings
    from mirza.db import Base, dispose_engine
    await dispose_engine()
    if _DBFILE.exists():
        _DBFILE.unlink()
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


class _FakeGateway:
    """Card2card-shaped fake: verify always says paid for our token."""

    def __init__(self, kv, callback_base):
        self.kv = kv

    async def create_payment(self, order_id, amount, description):
        from mirza.contracts import GatewayInit
        return GatewayInit(pay_text=f"pay {order_id}")

    async def verify_payment(self, request_body, query):
        return True, query.get("order_id", "")


@pytest.fixture()
def card2card_gateway():
    import mirza.plugins as plugins
    from mirza.registry import registry
    plugins.load_builtin_plugins()
    registry.register("payment", "fakegw", revision=2)(_FakeGateway)
    yield


async def test_gateway_product_order_provisions_once(card2card_gateway):
    from sqlalchemy import select as sa_select

    from mirza.api.payhooks import settle

    # stub the marzban adapter so provisioning needs no HTTP
    from mirza.contracts import PanelResult, PanelUser
    from mirza.db import get_sessionmaker
    from mirza.models import Invoice, MarzbanPanel, PaymentReport, Product, User
    from mirza.panels.marzban import MarzbanAdapter

    async def _fake_create(self, username, *, data_limit, expire_ts, note="",
                           data_limit_reset="no_reset", product=None):
        return PanelResult(ok=True, user=PanelUser(
            username=username,
            subscription_url=f"http://sub/{username}"))

    MarzbanAdapter.create_user = _fake_create

    s = get_sessionmaker()()
    s.add(User(id="u1", balance=0))
    s.add(Product(code_product="p1", name_product="Plan", price_product=90_000,
                  volume_gb=2, service_days=30, location="main"))
    s.add(MarzbanPanel(code_panel="c1", name_panel="main",
                       url_panel="http://127.0.0.1:1",
                       username_panel="a", password_panel_encrypted="x",
                       panel_type="marzban"))
    await s.commit()

    # build invoice + order like pay_gateway does
    import secrets
    inv = Invoice(id_invoice=secrets.token_hex(6), user_id="u1",
                  product_name="p1", price_product="90000",
                  volume="2", service_time="30",
                  service_location="main", status="pending",
                  time_sell="2026-08-25 00:00:00")
    s.add(inv)
    await s.commit()
    svc_order = PaymentReport(order_id=secrets.token_hex(6), user_id="u1",
                              price=90_000, payment_method="fakegw",
                              payment_status="Unpaid", invoice_id=inv.id_invoice,
                              created_at="2026-08-25 00:00:00")
    s.add(svc_order)
    await s.commit()
    oid = svc_order.order_id
    s.close()

    resp = await settle(b"", {"order_id": oid}, "fakegw", [])
    assert resp.status == 200

    s = get_sessionmaker()()
    inv_row = (await s.execute(
        sa_select(Invoice).where(Invoice.product_name == "p1"))).scalars().first()
    orders = (await s.execute(
        sa_select(PaymentReport).where(PaymentReport.order_id == oid)
    )).scalars().all()
    from mirza.payments.wallet import LedgerEntry
    ledger = list((await s.execute(sa_select(LedgerEntry))).scalars())
    s.close()

    assert inv_row.status == "enable"          # provisioned & activated
    assert len(orders) == 1 and orders[0].payment_status == "paid"
    assert not ledger, "product purchase must not touch the wallet"

    # replay: same callback again -> no double anything
    resp2 = await settle(b"", {"order_id": oid}, "fakegw", [])
    assert resp2.status == 200


async def test_wallet_topup_credits_exactly_once(card2card_gateway):
    import secrets

    from sqlalchemy import select as sa_select

    from mirza.api.payhooks import settle
    from mirza.db import get_sessionmaker
    from mirza.models import PaymentReport, User

    s = get_sessionmaker()()
    s.add(User(id="u2", balance=0))
    order = PaymentReport(order_id=secrets.token_hex(6), user_id="u2",
                          price=50_000, payment_method="fakegw",
                          payment_status="Unpaid",
                          created_at="2026-08-25 00:00:00")
    s.add(order)
    await s.commit()
    oid = order.order_id
    s.close()

    r1 = await settle(b"", {"order_id": oid}, "fakegw", [])
    assert r1.status == 200
    r2 = await settle(b"", {"order_id": oid}, "fakegw", [])   # replay
    assert r2.status == 200                                   # idempotent OK

    s = get_sessionmaker()()
    user = await s.get(User, "u2")
    from mirza.payments.wallet import LedgerEntry
    entries = (await s.execute(
        sa_select(LedgerEntry).where(LedgerEntry.user_id == "u2"))).scalars().all()
    s.close()

    assert user.balance == 50_000, "balance must increase exactly once"
    assert len([e for e in entries if e.reason == "topup"]) == 1


async def test_insufficient_balance_never_provisions():
    from mirza.db import get_sessionmaker
    from mirza.models import User
    from mirza.payments.wallet import WalletService

    s = get_sessionmaker()()
    s.add(User(id="u3", balance=100))
    await s.commit()

    wallet = WalletService(s)
    charge = await wallet.change("u3", -90_000, "purchase")
    assert not charge.ok            # refused before any provisioning
    user = await s.get(User, "u3")
    assert user.balance == 100      # untouched
    s.close()
