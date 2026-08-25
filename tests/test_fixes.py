"""Tests for the security/parity fix batch:
- Telegram WebApp initData HMAC verification
- webpanel settings auth gate + Setting/PaySetting split
- settle_direct_buy product resolution + GB→bytes conversion
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("MIRZA_DATABASE_URL",
                      "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MIRZA_SESSION_SECRET", "test-secret")
os.environ["MIRZA_API_KEY"] = "123456:TESTTOKEN"

from mirza.api.miniapp import verify_init_data  # noqa: E402


def _make_init_data(bot_token: str, user_id: int = 424242,
                    auth_date: int | None = None) -> str:
    auth_date = auth_date or int(time.time())
    params = [("auth_date", str(auth_date)),
              ("query_id", "AAF"),
              ("user", f'{{"id":{user_id},"first_name":"T"}}')]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(),
                      hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    params.append(("hash", sig))
    return urlencode(params)


def test_init_data_valid():
    d = _make_init_data("123456:TESTTOKEN")
    user = verify_init_data(d, "123456:TESTTOKEN")
    assert user is not None and user["id"] == 424242


def test_init_data_wrong_token_rejected():
    d = _make_init_data("123456:OTHERTOKEN")
    assert verify_init_data(d, "123456:TESTTOKEN") is None


def test_init_data_tampered_param_rejected():
    d = _make_init_data("123456:TESTTOKEN", user_id=111111)
    # change the user id without re-signing -> hash must not match
    tampered = d.replace("id%22%3A111111", "id%22%3A999999")
    assert tampered != d
    assert verify_init_data(tampered, "123456:TESTTOKEN") is None


def test_init_data_stale_rejected():
    old = int(time.time()) - 3 * 86400
    d = _make_init_data("123456:TESTTOKEN", auth_date=old)
    assert verify_init_data(d, "123456:TESTTOKEN") is None


def test_init_data_empty_rejected():
    assert verify_init_data("", "123456:TESTTOKEN") is None
