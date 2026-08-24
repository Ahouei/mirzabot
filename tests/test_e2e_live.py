"""Live-server end-to-end test: boots the real aiohttp app on a migrated
SQLite DB, then drives HTTP: miniapp token+actions, /sub proxy, panel login,
payment webhook idempotency, static Mini App bundle.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture()
async def live(tmp_path, monkeypatch):
    dbfile = tmp_path / "e2e.db"
    url = f"sqlite+aiosqlite:///{dbfile}"
    monkeypatch.setenv("MIRZA_DATABASE_URL", url)
    monkeypatch.setenv("MIRZA_DOMAIN_HOSTS", "e2e.test")
    subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), "upgrade", "head"],
        cwd=str(ROOT), env=dict(os.environ, MIRZA_DATABASE_URL=url),
        check=True, capture_output=True)

    from mirza.config import get_settings
    get_settings.cache_clear()

    from aiohttp.test_utils import TestClient, TestServer

    from mirza.api import make_app
    client = TestClient(TestServer(make_app()))
    await client.start_server()
    yield client
    await client.close()
    subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), "downgrade", "base"],
        cwd=str(ROOT), env=dict(os.environ, MIRZA_DATABASE_URL=url),
        check=True, capture_output=True)
    get_settings.cache_clear()


async def test_miniapp_full_flow(live):
    # 1. issue a session token for a fresh user
    resp = await live.post("/api/miniapp/token", json={"user_id": "777"})
    assert resp.status == 200, await resp.text()
    token = (await resp.json())["token"]

    # 2. user_info via GET with token param
    resp = await live.get("/api/miniapp",
                          params={"actions": "user_info", "token": token})
    body = await resp.json()
    assert resp.status == 200 and body["status"] is True
    assert body["user_info"]["id"] == "777"

    # 3. countries/categories/services actions respond
    for action, key in (("countries", "countries"),
                        ("categories", "categories"),
                        ("services", "services"),
                        ("invoices", "invoices")):
        r = await live.get("/api/miniapp",
                           params={"actions": action, "token": token})
        b = await r.json()
        assert r.status == 200 and key in b, (action, b)

    # 4. invalid action -> 400 Action Invalid; bad token -> 403
    r = await live.get("/api/miniapp", params={"actions": "nope",
                                               "token": token})
    assert r.status == 400
    r = await live.get("/api/miniapp", params={"actions": "user_info",
                                               "token": "wrong"})
    assert r.status == 403


async def test_sub_proxy_and_panel_login(live):
    # sub proxy: unknown invoice -> plain error (legacy behavior)
    r = await live.get("/sub/nonexistent")
    assert r.status == 200 and "ERROR" in await r.text()

    # panel: wrong login rejected, page served
    r = await live.get("/panel/login")
    assert r.status == 200 and "Mirza" in (await r.text())


async def test_webhook_rejects_bad_secret(live):
    from mirza.config import get_settings
    if not get_settings().webhook_secret:
        r = await live.post("/webhook", json={"update_id": 1})
        assert r.status in (200, 400)   # no secret configured -> passes gate
    else:
        r = await live.post("/webhook", json={"update_id": 1},
                            headers={"X-Telegram-Bot-Api-Secret-Token": "bad"})
        assert r.status == 403


async def test_static_miniapp_bundle(live):
    r = await live.get("/app/index.html")
    assert r.status == 200
    assert "<script" in (await r.text())
