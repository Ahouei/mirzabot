"""REST API - parity for api/*.php (miniapp backend, users, products,
payments, panels, settings, verify, discount, invoice, keyboard, log, statbot).

Auth: Token header (bot token or hash.txt token) or admin session cookie -
same contract as legacy api/utils.php.
"""
from __future__ import annotations

import hmac
import secrets
import time
from pathlib import Path

from aiohttp import web
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import (
    Category,
    Discount,
    Invoice,
    MarzbanPanel,
    PaymentReport,
    Product,
    Setting,
    User,
)


def _json(data, status: int = 200) -> web.Response:
    return web.json_response({"status": status < 400, "msg": "", **data}
                             if isinstance(data, dict) else data,
                             status=status)


async def _tokens() -> list[str]:
    toks = []
    if get_settings().api_key:
        toks.append(get_settings().api_key)
    f = Path(get_settings().api_tokens_file)
    if f.is_file():
        val = f.read_text().strip()
        if val:
            toks.append(val)
    return toks


def auth(fn):
    """requireApiTokenOrAdminSession parity."""

    async def wrapper(request: web.Request) -> web.Response:
        provided = request.headers.get("Token", "").strip()
        valid = False
        if provided:
            for tok in await _tokens():
                if hmac.compare_digest(tok, provided):
                    valid = True
                    break
        if not valid:
            session_id = request.cookies.get("mirza_session")
            valid = bool(session_id and session_id in _SESSIONS)
        if not valid:
            return _json({"msg": "token invalid"}, 403)
        return await fn(request)

    return wrapper


# ── mini-app user-token flow (api/miniapp.php) ───────────────────
@auth
async def miniapp(request: web.Request) -> web.Response:
    """actions=services|balance|buy|token — session token decides identity."""
    q = dict(request.rel_url.query)
    action = q.get("actions", "me")
    session = get_sessionmaker()()
    try:
        token = q.get("token", "")
        if action == "token":
            # exchange telegram id + bot payload for a session token
            uid = str(q.get("user_id", ""))
            row = await session.get(User, uid)
            if row is None:
                return _json({"msg": "user not found"}, 404)
            if not row.token:
                row.token = secrets.token_hex(16)
                await session.commit()
            return _json({"token": row.token})
        res = await session.execute(
            sa_select(User).where(User.token == token))
        user = res.scalar_one_or_none()
        if user is None:
            return _json({"msg": "Token invalid"}, 403)
        if action == "me":
            return _json({"user": {"id": user.id, "username": user.username,
                                   "balance": user.balance,
                                   "lang": user.lang}})
        if action == "services":
            res = await session.execute(
                sa_select(Invoice).where(Invoice.user_id == user.id))
            invs = [{"id": i.id_invoice, "product": i.product_name,
                     "status": i.status} for i in res.scalars()]
            return _json({"services": invs})
        if action == "products":
            res = await session.execute(sa_select(Product))
            prods = [{"code": p.code_product, "name": p.name_product,
                      "price": p.price_product, "volume": p.volume_gb,
                      "days": p.service_days} for p in res.scalars()]
            return _json({"products": prods})
        if action == "categories":
            res = await session.execute(sa_select(Category))
            cats = [{"id": c.id, "title": c.title} for c in res.scalars()]
            return _json({"categories": cats})
        if action == "payments":
            res = await session.execute(
                sa_select(PaymentReport).where(PaymentReport.user_id == user.id))
            pays = [{"order": o.order_id, "price": o.price,
                     "status": o.payment_status} for o in res.scalars()]
            return _json({"payments": pays})
        return _json({"msg": "unknown action"}, 400)
    finally:
        await session.close()


# ── admin-side resources (api/users.php, product.php, panels.php...) ──
@auth
async def users(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    page = max(int(q.get("page", "1") or 1), 1)
    limit = min(max(int(q.get("limit", "10") or 10), 1), 100)
    search = q.get("q", "")
    session = get_sessionmaker()()
    try:
        stmt = sa_select(User)
        total_stmt = sa_select(sa_func.count()).select_from(User)
        if search:
            like = f"%{search}%"
            stmt = stmt.where((User.username.ilike(like)) | (User.id == search))
            total_stmt = total_stmt.where(
                (User.username.ilike(like)) | (User.id == search))
        total = (await session.execute(total_stmt)).scalar() or 0
        res = await session.execute(
            stmt.order_by(User.id.desc()).offset((page - 1) * limit).limit(limit))
        rows = [{"id": u.id, "username": u.username, "balance": u.balance,
                 "status": u.user_status, "agent": u.is_agent,
                 "lang": u.lang} for u in res.scalars()]
        return _json({"users": rows, "pagination": {
            "total_record": total,
            "total_pages": (total + limit - 1) // limit,
            "current": page}})
    finally:
        await session.close()


@auth
async def products(request: web.Request) -> web.Response:
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Product))
        rows = [{"code": p.code_product, "name": p.name_product,
                 "price": p.price_product, "volume_gb": p.volume_gb,
                 "days": p.service_days, "location": p.location,
                 "category": p.category_id} for p in res.scalars()]
        return _json({"products": rows})
    finally:
        await session.close()


@auth
async def panels(request: web.Request) -> web.Response:
    from mirza.registry import registry
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(MarzbanPanel))
        rows = [{"name": p.name_panel, "type": p.panel_type,
                 "url": p.url_panel, "status": bool(p.status)}
                for p in res.scalars()]
        return _json({"panels": rows,
                      "available_types": sorted(registry.names("panel"))})
    finally:
        await session.close()


@auth
async def payments(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    search = q.get("q", "")
    page = max(int(q.get("page", "1") or 1), 1)
    limit = min(max(int(q.get("limit", "10") or 10), 1), 100)
    session = get_sessionmaker()()
    try:
        stmt = sa_select(PaymentReport)
        if search:
            like = f"%{search}%"
            stmt = stmt.where((PaymentReport.order_id.ilike(like)) |
                              (PaymentReport.user_id.ilike(like)))
        total = (await session.execute(
            sa_select(sa_func.count())
            .select_from(PaymentReport))).scalar() or 0
        res = await session.execute(
            stmt.order_by(PaymentReport.id.desc())
            .offset((page - 1) * limit).limit(limit))
        rows = [{"order": o.order_id, "user": o.user_id, "price": o.price,
                 "method": o.payment_method, "status": o.payment_status,
                 "time": o.created_at} for o in res.scalars()]
        return _json({"payments": rows, "pagination": {
            "total_record": total, "current": page}})
    finally:
        await session.close()


@auth
async def settings_api(request: web.Request) -> web.Response:
    if request.method == "GET":
        session = get_sessionmaker()()
        try:
            res = await session.execute(sa_select(Setting))
            kv = {r.key: (r.value_json if r.value_json is not None else r.value)
                  for r in res.scalars()}
            return _json({"settings": kv})
        finally:
            await session.close()
    body = await request.json()
    session = get_sessionmaker()()
    try:
        for k, v in body.items():
            import json as _j
            row = Setting(key=k,
                          value=v if isinstance(v, str) else _j.dumps(v),
                          value_json=None if isinstance(v, str) else v)
            await session.merge(row)
        await session.commit()
        return _json({"msg": "ok"})
    finally:
        await session.close()


@auth
async def discounts(request: web.Request) -> web.Response:
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Discount))
        rows = [{"code": d.code, "percent": d.discount_percent,
                 "used": d.used_count, "limit": d.usage_limit}
                for d in res.scalars()]
        return _json({"discounts": rows})
    finally:
        await session.close()


@auth
async def statbot(request: web.Request) -> web.Response:
    session = get_sessionmaker()()
    try:
        users_n = (await session.execute(
            sa_select(sa_func.count()).select_from(User))).scalar() or 0
        sales = (await session.execute(
            sa_select(sa_func.count()).select_from(Invoice))).scalar() or 0
        revenue = (await session.execute(
            sa_select(sa_func.coalesce(sa_func.sum(PaymentReport.price), 0))
            .where(PaymentReport.payment_status == "paid"))).scalar() or 0
        return _json({"users": users_n, "sales": sales, "revenue": revenue})
    finally:
        await session.close()


@auth
async def invoices(request: web.Request) -> web.Response:
    q = dict(request.rel_url.query)
    session = get_sessionmaker()()
    try:
        stmt = sa_select(Invoice)
        if q.get("username"):
            stmt = stmt.where(Invoice.username == q["username"])
        res = await session.execute(stmt.limit(200))
        rows = [{"id": i.id_invoice, "user": i.user_id,
                 "location": i.service_location, "uuid": i.uuid,
                 "status": i.status} for i in res.scalars()]
        return _json({"invoices": rows})
    finally:
        await session.close()


@auth
async def logs(request: web.Request) -> web.Response:
    session = get_sessionmaker()()
    try:
        from mirza.models import LogsApi
        res = await session.execute(
            sa_select(LogsApi).order_by(LogsApi.id.desc()).limit(50))
        rows = [{"route": l.route, "actor": l.actor_id,
                 "at": str(l.created_at)} for l in res.scalars()]
        return _json({"logs": rows})
    finally:
        await session.close()


@auth
async def verify_user(request: web.Request) -> web.Response:
    """Phone verification status update (api/verify.php)."""
    body = await request.json()
    uid = str(body.get("user_id", ""))
    phone = str(body.get("phone", ""))
    session = get_sessionmaker()()
    try:
        await session.execute(
            sa_update(User).where(User.id == uid)
            .values(phone_number=phone, verify_status="verified"))
        await session.commit()
        return _json({"msg": "verified"})
    finally:
        await session.close()


# ── app wiring ───────────────────────────────────────────────────
def make_app() -> web.Application:
    app = web.Application()
    r = web.Application()  # placeholder to keep linters calm
    del r
    # legacy miniapp action API + token exchange + static bundle
    from .miniapp import miniapp, token_exchange
    app.router.add_get("/api/miniapp", miniapp)
    app.router.add_post("/api/miniapp", miniapp)
    app.router.add_post("/api/miniapp/token", token_exchange)
    app.router.add_get("/api/users", users)
    app.router.add_get("/api/product", products)
    app.router.add_get("/api/panels", panels)
    app.router.add_get("/api/payment", payments)
    app.router.add_get("/api/settings", settings_api)
    app.router.add_post("/api/settings", settings_api)
    app.router.add_get("/api/discount", discounts)
    app.router.add_get("/api/statbot", statbot)
    app.router.add_get("/api/invoice", invoices)
    app.router.add_get("/api/log", logs)
    app.router.add_post("/api/verify", verify_user)

    # payment gateway callbacks (webhook replacements of pay/*.php)
    from .payhooks import (
        aqaye_callback,
        cubepay_callback,
        iranpay_callback,
        nowpayment_callback,
        plisio_callback,
        zarinpal_callback,
    )
    app.router.add_post("/pay/plisio/callback", plisio_callback)
    app.router.add_post("/pay/nowpayment/callback", nowpayment_callback)
    app.router.add_get("/pay/zarinpal/callback", zarinpal_callback)
    app.router.add_get("/pay/aqayepardakht/callback", aqaye_callback)
    app.router.add_get("/pay/iranpay/callback", iranpay_callback)
    # CubePay: POST from gateway (signed), GET browser redirect (HTML card)
    app.router.add_post("/pay/cubepay/callback", cubepay_callback)
    app.router.add_get("/pay/cubepay/callback", cubepay_callback)

    # subscription proxy (sub/index.php parity)
    from .subproxy import sub_handler
    app.router.add_get("/sub/{token}", sub_handler)

    # legacy miniapp bundle (React build) served from /app if present
    from .miniapp_static import serve_miniapp
    app.router.add_get("/app/", serve_miniapp)
    app.router.add_get("/app/{tail:.*}", serve_miniapp)

    # webhook endpoint (index.php parity, with secret check)
    from .webhook import webhook_handler
    app.router.add_post(get_settings().webhook_path, webhook_handler)

    # white-label child-bot webhook dispatcher
    from .whitelabel import whitelabel_webhook
    app.router.add_post("/wl/{bot_username}", whitelabel_webhook)

    # web panel (session-based dashboard)
    from ..routes.webpanel import make_web_app
    app.add_subapp("/panel/", make_web_app())

    return app


def run_server() -> None:
    web.run_app(make_app(), host="0.0.0.0", port=8080)


_SESSIONS: dict[str, float] = {}


def new_session(user: str) -> str:
    sid = secrets.token_hex(24)
    _SESSIONS[sid] = time.time()
    return sid


def session_valid(sid: str) -> bool:
    ts = _SESSIONS.get(sid)
    return bool(ts and time.time() - ts < 86400)


def drop_session(sid: str) -> None:
    _SESSIONS.pop(sid, None)
