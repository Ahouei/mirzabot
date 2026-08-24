"""End-to-end integration test on a real file-backed SQLite DB:
alembic up (subprocess) -> ORM round-trips -> wallet ledger ->
payment claim idempotency -> panel service against a fake adapter.

Migrations run via subprocess so env.py's asyncio.run() never touches
pytest's event loop. Engine/sessionmaker caches are reset around the
fixture so the new URL takes effect.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
async def db(tmp_path, monkeypatch):
    dbfile = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{dbfile}"

    import subprocess

    def _migrate(direction: str) -> None:
        env = dict(os.environ, MIRZA_DATABASE_URL=url)
        cmd, *args = direction.split()
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), cmd, *args],
            cwd=str(ROOT), env=env, check=True,
            capture_output=True)

    from mirza.config import get_settings
    get_settings.cache_clear()   # lru_cache would pin the pre-fixture URL
    monkeypatch.setenv("MIRZA_DATABASE_URL", url)

    from mirza.db import dispose_engine
    await dispose_engine()
    _migrate("upgrade head")
    yield url
    _migrate("downgrade base")
    await dispose_engine()
    get_settings.cache_clear()


async def test_schema_roundtrip(db):
    from sqlalchemy import select as sa_select

    from mirza.db import get_sessionmaker
    from mirza.models import Invoice, Product, User

    session = get_sessionmaker()()
    session.add(User(id="100", username="tester", balance=500_000))
    session.add(Product(code_product="p1", name_product="1GB/30d",
                        price_product=90_000, volume_gb=1,
                        service_days=30, location="main"))
    await session.commit()

    session.add(Invoice(id_invoice="tok123", user_id="100",
                        service_location="main", uuid="cfguser1",
                        product_name="1GB/30d"))
    await session.commit()

    got = (await session.execute(
        sa_select(Invoice).where(Invoice.id_invoice == "tok123"))).scalar_one()
    assert got.user_id == "100"
    prod = (await session.execute(
        sa_select(Product).where(Product.code_product == "p1"))).scalar_one()
    assert prod.price_product == 90_000


async def test_wallet_ledger_and_claim_idempotency(db):
    from mirza.db import get_sessionmaker
    from mirza.models import User
    from mirza.payments.service import PaymentService
    from mirza.payments.wallet import WalletService

    s = get_sessionmaker()()
    s.add(User(id="200", username="u2", balance=0))
    await s.commit()

    wallet = WalletService(s)
    assert (await wallet.change("200", 250_000, "topup")).ok
    assert (await wallet.change("200", -50_000, "purchase")).ok
    denied = await wallet.change("200", -10_000_000, "purchase")
    assert not denied.ok and denied.error == "insufficient balance"
    history = await wallet.history("200")
    assert [h.delta for h in history] == [-50_000, 250_000]

    svc = PaymentService(s)
    order = await svc.create_order("200", 50_000, "zarinpal")
    assert await svc.claim_paid(order.order_id) is True
    assert await svc.claim_paid(order.order_id) is False   # replay blocked
    row = await svc.get_order(order.order_id)
    assert row.payment_status == "paid"


async def test_panel_service_with_fake_adapter(db, monkeypatch):
    from mirza.contracts import PanelResult, PanelUser
    from mirza.db import get_sessionmaker
    from mirza.models import MarzbanPanel
    from mirza.panels.service import PanelService

    s = get_sessionmaker()()
    s.add(MarzbanPanel(code_panel="c1", name_panel="main",
                       url_panel="https://fake.example",
                       panel_type="marzban"))
    await s.commit()

    import mirza.panels.service as ps

    def fake_adapter(panel):
        class A:
            name = "marzban"

            def __init__(self, creds):
                pass

            async def create_user(self, username, *, data_limit, expire_ts,
                                  note="", data_limit_reset="no_reset",
                                  product=None):
                u = PanelUser(username=username,
                              subscription_url=f"https://fake/sub/{username}",
                              links=[f"vless://x@host:443#{username}"])
                return PanelResult(ok=True, user=u)

            async def close(self):
                return None

        return A({})

    monkeypatch.setattr(ps.PanelService, "_adapter_for",
                        staticmethod(fake_adapter))

    async with PanelService(s) as panels:
        result = await panels.create_user(
            "main", "p1", "testuser3", data_limit=1024**3,
            expire_ts=9_999_999_999, user_id="100", tg_username="tester")
    assert result.ok, result.error
    assert result.subscription_url.startswith("https://fake/sub/")
    assert result.invoice.uuid == "testuser3"
