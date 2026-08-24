"""Mock-edge pipeline tests: every gateway driven through the REAL order
lifecycle with only outbound HTTP mocked. Proves create_payment parsing,
callback verification, claim_paid idempotency per gateway.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_edge import FIXTURES, FIXTURES_KV, FakeResponse, MockSession


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module", autouse=True)
def _load_plugins():
    import mirza.plugins
    mirza.plugins.load_builtin_plugins()


# ── create_payment parsing (mock HTTP edge) ──────────────────────
@pytest.mark.parametrize("gw_name,url_frag,fixture", [
    ("zarinpal", "request.json", FIXTURES["zarinpal"]["create"]),
    ("nowpayments", "/v1/invoice", FIXTURES["nowpayments"]["invoice"]),
    ("plisio", "invoices/new", FIXTURES["plisio"]["invoice"]),
    ("aqayepardakht", "/create", FIXTURES["aqayepardakht"]["create"]),
    ("iranpay", "factor/create", FIXTURES["iranpay"]["create"]),
])
def test_create_payment_parses_redirect(gw_name, url_frag, fixture):
    mock = MockSession({url_frag: [FakeResponse(200, fixture)]})
    gw = build_patched(gw_name, mock)
    init = run(gw.create_payment("ordX", 100_000, "test buy"))
    assert init.redirect_url, f"{gw_name}: no redirect parsed"
    assert len(mock.calls) == 1


def test_card2card_needs_no_network():
    gw = build_gateway("card2card")
    init = run(gw.create_payment("ordC", 50_000, "c2c"))
    assert init.pay_text and "ordC" in init.pay_text


def test_cubepay_create_parses_link():
    mock = MockSession({"create-order": [
        FakeResponse(200, FIXTURES["cubepay"]["create"])]})
    gw = build_patched("cubepay", mock)
    init = run(gw.create_payment("ordK", 100_000, "tron buy"))
    assert init.redirect_url == "https://cubevps.ir/pay/xyz"


# ── callback verification paths ──────────────────────────────────
def test_cubepay_signed_callback_accepts():
    from mirza.payments.cubepay import CubePayGateway
    payload = {"order_id": "ordZ", "status": "paid",
               "amount_toman": "100000"}
    sig = hmac_mod.new(b"cube-secret",
                       b"ordZ|paid|100000", hashlib.sha256).hexdigest()
    ok, oid = run(CubePayGateway(
        {"apiternado": "cube-secret"}, "https://x")
        .verify_payment(json.dumps(payload | {"sig": sig}).encode(),
                        {"_order_price": "100000"}))
    assert ok and oid == "ordZ"


def test_nowpayments_webhook_doublechecks_api():
    from mirza.payments.nowpayments import NowPaymentsGateway
    webhook = json.dumps({"payment_status": "finished",
                          "payment_id": "NP123",
                          "order_id": "ordN"}).encode()
    status_ok = FakeResponse(200, FIXTURES["nowpayments"]["status"])
    gw = NowPaymentsGateway(FIXTURES_KV["nowpayments"], "https://x")
    real_cls = type(gw)

    class Patched(real_cls):
        async def verify_payment(self, request_body, query):
            import aiohttp
            saved = aiohttp.ClientSession
            aiohttp.ClientSession = (
                lambda **kw: MockSession({"/payment/NP123": [status_ok]}))
            try:
                return await real_cls.verify_payment(self, request_body,
                                                     query)
            finally:
                aiohttp.ClientSession = saved

    ok, oid = run(Patched(FIXTURES_KV["nowpayments"], "https://x")
                  .verify_payment(webhook, {}))
    assert ok and oid == "ordN"


def test_plisio_poll_confirms_completed():
    from mirza.payments.plisio import PlisioGateway
    status_ok = FakeResponse(200, FIXTURES["plisio"]["status"])
    gw = PlisioGateway(FIXTURES_KV["plisio"], "https://x")

    class Patched(type(gw)):
        async def verify_payment(self, request_body, query):
            import aiohttp
            saved = aiohttp.ClientSession
            aiohttp.ClientSession = (
                lambda **kw: MockSession(
                    {"/operations/PL1": [status_ok]}))
            try:
                return await type(gw).verify_payment(self, request_body,
                                                     query)
            finally:
                aiohttp.ClientSession = saved

    ok, oid = run(Patched(FIXTURES_KV["plisio"], "https://x")
                  .verify_payment(b"", {"track": "PL1",
                                        "order_number": "ordP"}))
    assert ok and oid == "ordP"


# ── full lifecycle on a migrated DB ───────────────────────────────
def test_claim_idempotency_on_real_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "mockedge.db"
    url = f"sqlite+aiosqlite:///{dbfile}"
    monkeypatch.setenv("MIRZA_DATABASE_URL", url)
    subprocess.run([str(ROOT / ".venv/bin/alembic"), "upgrade", "head"],
                   cwd=str(ROOT), check=True, capture_output=True,
                   env=dict(os.environ, MIRZA_DATABASE_URL=url))
    from mirza.config import get_settings
    get_settings.cache_clear()

    from mirza.db import dispose_engine, get_sessionmaker
    from mirza.models import User
    from mirza.payments.service import PaymentService

    s = get_sessionmaker()()
    s.add(User(id="42", username="buyer"))

    async def commit():
        await s.commit()

    run(commit())

    svc = PaymentService(s)
    order = run(svc.create_order("42", 10_000, "zarinpal"))
    assert run(svc.claim_paid(order.order_id)) is True
    assert run(svc.claim_paid(order.order_id)) is False   # replay blocked
    row = run(svc.get_order(order.order_id))
    assert row.payment_status == "paid"

    run(dispose_engine())
    get_settings.cache_clear()


# ── helpers ───────────────────────────────────────────────────────
def build_gateway(name: str):
    from mirza.registry import registry
    cls = registry.get("payment", name)
    return cls(dict(FIXTURES_KV.get(name, {})), callback_base="https://t")


def build_patched(name: str, mock: MockSession):
    """Gateway whose inline aiohttp session calls hit the mock script."""
    base = build_gateway(name)

    class Patched(type(base)):
        async def create_payment(self, order_id, amount, description):
            import aiohttp
            saved = aiohttp.ClientSession
            aiohttp.ClientSession = lambda **kw: mock  # type: ignore[assignment,misc]
            try:
                return await type(base).create_payment(
                    self, order_id, amount, description)
            finally:
                aiohttp.ClientSession = saved

    return Patched(dict(base.kv), base.callback_base)
