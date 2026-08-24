"""Live run: fake Marzban panel + full buy→deliver→extend cycle in ONE loop.

Everything runs in a single asyncio loop so the TestServer port stays open
while PanelService's aiohttp client connects to it.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault(
    "MIRZA_DATABASE_URL", "sqlite+aiosqlite:////tmp/run_live.db")
os.environ.setdefault("MIRZA_SESSION_SECRET", "run-secret-1")


async def main() -> None:
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    import mirza.plugins as plugins
    plugins.load_builtin_plugins()

    # 0. fresh migrated DB
    dbfile = "/tmp/run_live.db"
    if os.path.exists(dbfile):
        os.remove(dbfile)
    subprocess = __import__("subprocess")
    subprocess.run([str(ROOT / ".venv/bin/alembic"), "upgrade", "head"],
                   cwd=str(ROOT), check=True, capture_output=True,
                   env=dict(os.environ))
    from mirza.config import get_settings
    get_settings.cache_clear()
    from mirza.db import dispose_engine, get_sessionmaker

    # 1. fake Marzban panel (records calls)
    calls: list[tuple[str, str]] = []

    async def token(request: web.Request) -> web.Response:
        return web.json_response({"access_token": "faketok"})

    async def create_user(request: web.Request) -> web.Response:
        calls.append(("POST", "/api/user"))
        body = await request.json()
        return web.json_response({
            "username": body.get("username"),
            "subscription_url": "/sub/abc123",
            "data_limit": body.get("data_limit"),
            "expire": body.get("expire"), "status": "active"})

    async def get_user(request: web.Request) -> web.Response:
        u = request.match_info["u"]
        calls.append(("GET", f"/api/user/{u}"))
        return web.json_response({
            "username": u, "subscription_url": "/sub/abc123",
            "data_limit": 1073741824, "used_traffic": 104857600,
            "expire": int(time.time()) + 86400 * 30, "status": "active"})

    async def put_user(request: web.Request) -> web.Response:
        calls.append(("PUT", f"/api/user/{request.match_info['u']}"))
        return web.json_response({"username": request.match_info["u"],
                                  "status": "active"})

    fake = web.Application()
    fake.router.add_post("/api/admin/token", token)
    fake.router.add_post("/api/user", create_user)
    fake.router.add_get("/api/user/{u}", get_user)
    fake.router.add_put("/api/user/{u}", put_user)

    fserver = TestServer(fake)
    await fserver.start_server()

    # 2. seed buyer + panel row pointing at the fake
    session = get_sessionmaker()()
    from mirza.models import Admin, MarzbanPanel, Product, User
    session.add(User(id="42", username="buyer", balance=500_000))
    session.add(Admin(id_admin="9", username="root"))
    session.add(MarzbanPanel(
        code_panel="c1", name_panel="main",
        url_panel=f"http://127.0.0.1:{fserver.port}",
        username_panel="admin", password_panel_encrypted="pw",
        panel_type="marzban"))
    session.add(Product(code_product="p1", name_product="1GB/30d",
                        price_product=90_000, volume_gb=1, service_days=30,
                        location="main"))
    await session.commit()

    # 3. BUY: create config through the real adapter over real HTTP
    from mirza.panels.service import PanelService
    async with PanelService(session) as panels:
        result = await panels.create_user(
            "main", "p1", "buyertest42", data_limit=1024 ** 3,
            expire_ts=int(time.time()) + 30 * 86400, user_id="42",
            tg_username="buyer")
    assert result.ok, result.error
    print("[OK] create_user      ->", result.subscription_url)
    print("     invoice          ->", result.invoice.id_invoice[:12],
          "| uuid:", result.invoice.uuid)

    # 4. STATUS query through the real adapter
    u = await panels.data_user("main", "buyertest42")
    print("[OK] data_user        ->",
          {"limit_GB": round((u.data_limit or 0) / 1024 ** 3),
           "used_MB": round((u.used_traffic or 0) / 1048576),
           "expires_in_d": round(((u.expire_at or 0) - time.time()) / 86400)})

    # 5. EXTEND (+15 days via real modify call)
    ok = await panels.extra_time("main", "buyertest42", 15)
    print("[OK] extra_time(+15d) ->", ok)

    # 6. WALLET pay for the invoice (ledger entry written)
    from mirza.payments.wallet import WalletService
    wallet = WalletService(session)
    change = await wallet.change("42", -90_000, "purchase",
                                 ref=result.invoice.id_invoice)
    print("[OK] wallet charge    ->", change.ok,
          "| balance:", f"{change.new_balance:,}")
    hist = await wallet.history("42")
    print("     ledger rows      ->", [(h.delta, h.reason) for h in hist])

    made = len(calls)
    print(f"\nfake panel saw {made} HTTP calls:", calls)
    assert made >= 3, "adapter never reached the wire"
    await fserver.close()
    run_migrate_down()
    await dispose_engine()


def run_migrate_down() -> None:
    subprocess = __import__("subprocess")
    subprocess.run([str(ROOT / ".venv/bin/alembic"), "downgrade", "base"],
                   cwd=str(ROOT), check=True, capture_output=True,
                   env=dict(os.environ))


if __name__ == "__main__":
    asyncio.run(main())
