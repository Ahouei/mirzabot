"""Unit tests for the CubePay gateway (offline: fee math, HMAC, result page)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mirza.payments.cubepay import (
    CubePayGateway,
    _apply_fee,
    payable_amount,
    result_page,
)


def test_fee_math_matches_php():
    # <=100 -> percent with ceil; >100 -> flat add; disabled -> untouched
    assert _apply_fee(100_000, 5) == 105_000
    assert _apply_fee(100_000, 0.5) == 100_500
    assert _apply_fee(100_000, 20_000) == 120_000
    assert _apply_fee(100_000, 0) == 100_000
    off = {"feestatusternado": "offfeeternado", "feeternado": "5"}
    on_pct = {"feestatusternado": "onfeeternado", "feeternado": "5"}
    on_flat = {"feestatusternado": "onfeeternado", "feeternado": "20000"}
    assert payable_amount(100_000, off) == 100_000
    assert payable_amount(100_000, on_pct) == 105_000
    assert payable_amount(100_000, on_flat) == 120_000


def test_signed_callback_accepts_valid():
    gw = CubePayGateway({"apiternado": "sekret"}, callback_base="https://x")
    sig = hmac.new(b"sekret", b"ord1|paid|105000",
                   hashlib.sha256).hexdigest()
    body = json.dumps({"order_id": "ord1", "status": "paid",
                       "amount_toman": "105000", "sig": sig}).encode()
    ok, oid = asyncio.run(gw.verify_payment(body, {"_order_price": "105000"}))
    assert ok and oid == "ord1"


def test_signed_callback_rejects_tamper_and_underpay():
    gw = CubePayGateway({"apiternado": "sekret"}, callback_base="https://x")
    good = hmac.new(b"sekret", b"ord1|paid|105000",
                    hashlib.sha256).hexdigest()
    bad_sig = good[:-1] + ("0" if good[-1] != "0" else "1")
    body_bad = json.dumps({"order_id": "ord1", "status": "paid",
                           "amount_toman": "105000",
                           "sig": bad_sig}).encode()
    ok, _ = asyncio.run(gw.verify_payment(body_bad, {"_order_price": "105000"}))
    assert not ok
    under = hmac.new(b"sekret", b"ord1|paid|90000",
                     hashlib.sha256).hexdigest()
    body_low = json.dumps({"order_id": "ord1", "status": "paid",
                           "amount_toman": "90000", "sig": under}).encode()
    ok2, _ = asyncio.run(gw.verify_payment(body_low,
                                           {"_order_price": "105000"}))
    assert not ok2


def test_result_page_states():
    for state in ("success", "already", "failed", "expired", "notfound"):
        html = result_page(state, lang="fa", order_id="o1",
                           price=105000, bot_username="@mirzabot")
        assert "<html" in html and "card" in html
    rtl = result_page("success", lang="fa")
    ltr = result_page("success", lang="en")
    assert "dir=rtl" in rtl
    assert "dir=ltr" in ltr
