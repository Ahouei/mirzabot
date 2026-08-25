"""Web panel settings: auth gate + Setting/PaySetting split verification.

Boots the FULL api app (webpanel is a /panel/ sub-app of it) on a migrated
SQLite DB, exactly like production.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIRZA_SESSION_SECRET", "test-secret")
os.environ["MIRZA_API_KEY"] = "123456:TESTTOKEN"

import bcrypt  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture()
async def client(tmp_path):
    from mirza.config import get_settings
    from mirza.db import dispose_engine

    dbfile = tmp_path / "panel.db"
    url = f"sqlite+aiosqlite:///{dbfile}"
    # in-process engine must point at the SAME file the subprocess migrated
    os.environ["MIRZA_DATABASE_URL"] = url
    env = dict(os.environ)
    subprocess.run([str(ROOT / ".venv/bin/alembic"), "upgrade", "head"],
                   cwd=str(ROOT), env=env, check=True, capture_output=True)
    # drop cached engine/sessionmaker bound to a previous URL, then rebuild
    await dispose_engine()
    get_settings.cache_clear()

    from aiohttp import CookieJar
    from aiohttp.test_utils import TestClient, TestServer
    from mirza.api import make_app
    client = TestClient(TestServer(make_app()),
                        cookie_jar=CookieJar(unsafe=True))
    await client.start_server()
    yield client
    await client.close()


async def _login(client):
    from mirza.db import get_sessionmaker
    from mirza.models import Admin
    s = get_sessionmaker()()
    pw = bcrypt.hashpw(b"s3cretpw", bcrypt.gensalt(rounds=12)).decode()
    s.add(Admin(id_admin="77", username="qa",
                password_hash=pw.replace("$2b$", "$2y$")))
    await s.commit()
    s.close()
    r = await client.post("/panel/login",
                          data={"username": "qa", "password": "s3cretpw"},
                          allow_redirects=False)
    assert r.status == 302


async def test_settings_requires_auth(client):
    # unauthenticated GET must redirect to login
    r = await client.get("/panel/settings", allow_redirects=False)
    assert r.status in (301, 302, 303), f"expected redirect, got {r.status}"
    assert "/login" in r.headers.get("Location", "")

    # unauthenticated POST must also be gated
    r = await client.post("/panel/settings", data={"channel_lock": "@x"},
                          allow_redirects=False)
    assert r.status in (301, 302, 303)


async def test_settings_split_setting_vs_paysetting(client):
    from sqlalchemy import select as sa_select
    from mirza.db import get_sessionmaker
    from mirza.models import PaySetting, Setting

    await _login(client)
    r = await client.post("/panel/settings", data={
        "channel_lock": "@mychan",          # shop key -> setting
        "zarinpal_merchant": "MERCH-123",   # gateway key -> PaySetting
    }, allow_redirects=False)
    assert r.status == 200

    s = get_sessionmaker()()
    shop = (await s.execute(
        sa_select(Setting).where(Setting.key == "channel_lock")
    )).scalar_one_or_none()
    pay = (await s.execute(
        sa_select(PaySetting).where(PaySetting.name_pay == "zarinpal_merchant")
    )).scalar_one_or_none()
    wrong = (await s.execute(
        sa_select(Setting).where(Setting.key == "zarinpal_merchant")
    )).scalar_one_or_none()
    s.close()

    assert shop is not None and shop.value == "@mychan"
    assert pay is not None and pay.value_pay == "MERCH-123"
    assert wrong is None, "gateway key leaked into shop settings table"
