"""Mock-edge gateway harness.

Drives the REAL payment pipeline (order creation -> gateway.create_payment
-> callback verification -> claim_paid idempotency -> settlement) with only
the outbound HTTP call to the gateway replaced by recorded/fixture responses.

Proves our side of every handshake. The operator's live transaction then
only validates their keys against the real API.
"""
from __future__ import annotations

import json as _json
from typing import Any

from mirza.contracts import PaymentGateway


class FakeResponse:
    def __init__(self, status: int = 200, body: dict | None = None):
        self.status = status
        self._body = body or {}

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return _json.dumps(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class MockSession:
    """Replaces aiohttp.ClientSession inside gateway code under test."""

    def __init__(self, script: dict[str, list[FakeResponse]]):
        # script: URL fragment -> queue of responses to serve in order
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, url, **kw):
        return self._serve("GET", url, kw)

    def post(self, url, **kw):
        return self._serve("POST", url, kw)

    def _serve(self, method: str, url: str, kw: dict):
        self.calls.append((method, url, kw))
        for frag, queue in self.script.items():
            if frag in url and queue:
                return queue.pop(0)
        return FakeResponse(500, {"error": "no scripted response"})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ── per-gateway fixtures (recorded shapes from legacy PHP) ────────
def fixture_zarinpal_request_ok():
    return {"data": {"authority": "A0000000000000000000000000",
                     "code": 100}, "errors": []}


def fixture_zarinpal_verify_ok():
    return {"data": {"code": 100, "ref_id": "123456"}, "errors": []}


def fixture_nowpayment_invoice():
    return {"id": "NP123", "invoice_url": "https://nowpayments.io/i/NP123"}


def fixture_nowpayment_status_finished():
    return {"payment_id": "NP123", "payment_status": "finished",
            "order_id": "ord1"}


def fixture_plisio_invoice():
    return {"data": {"id": "PL1",
                     "invoice_url": "https://plisio.net/i/PL1"}}


def fixture_plisio_completed():
    return {"data": {"status": "completed"}}


def fixture_aqaye_create():
    return {"code": 1, "transid": "AQ9"}


def fixture_aqaye_verify():
    return {"code": 1}


def fixture_iranpay_create():
    return {"data": {"id": "F77", "url": "https://pay.example/f/F77"}}


def fixture_iranpay_approved():
    return {"data": {"status": "approved"}}


def fixture_cubepay_create():
    return {"payment_link": "https://cubevps.ir/pay/xyz"}


def fixture_card2card_none():
    return {}


FIXTURES: dict[str, dict[str, dict]] = {
    "zarinpal": {
        "create": fixture_zarinpal_request_ok(),
        "verify": fixture_zarinpal_verify_ok(),
    },
    "nowpayments": {
        "invoice": fixture_nowpayment_invoice(),
        "status": fixture_nowpayment_status_finished(),
    },
    "plisio": {
        "invoice": fixture_plisio_invoice(),
        "status": fixture_plisio_completed(),
    },
    "aqayepardakht": {
        "create": fixture_aqaye_create(),
        "verify": fixture_aqaye_verify(),
    },
    "iranpay": {
        "create": fixture_iranpay_create(),
        "status": fixture_iranpay_approved(),
    },
    "cubepay": {
        "create": fixture_cubepay_create(),
    },
    "card2card": {},
}


def build_gateway(name: str, kv_overrides: dict | None = None,
                  mock_session: MockSession | None = None) -> PaymentGateway:
    from mirza.registry import registry
    cls = registry.get("payment", name)
    kv = dict(FIXTURES_KV.get(name, {}))
    kv.update(kv_overrides or {})
    gw = cls(kv, callback_base="https://test.local")
    if mock_session is not None:
        # inject mock transport where gateways create sessions inline
        original_cls = type(gw)

        class Patched(original_cls):  # type: ignore[valid-type,misc]
            async def create_payment(self, order_id, amount, description):
                import aiohttp
                real_session = aiohttp.ClientSession
                aiohttp.ClientSession = (  # monkey-patch scoped to call
                    lambda **kw: mock_session)  # type: ignore[assignment]
                try:
                    return await original_cls.create_payment(
                        self, order_id, amount, description)
                finally:
                    aiohttp.ClientSession = real_session

        return Patched(kv, callback_base="https://test.local")
    return gw


FIXTURES_KV: dict[str, dict] = {
    "zarinpal": {"zarinpal_merchant": "test-merchant"},
    "nowpayments": {"nowpayment_api": "np-key"},
    "plisio": {"plisio_api": "pl-key"},
    "aqayepardakht": {"aqayepardakht_pin": "aq-pin"},
    "iranpay": {"apiiranpay": "ip-key", "iranpay_base": "https://ip.example"},
    "cubepay": {"apiternado": "cube-secret"},
    "card2card": {"active_cards": "6037-9999-1111-1 | Test Bank"},
}
