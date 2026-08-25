"""Web admin panel - parity for panel/*.php (login, dashboard, users,
products, payments, settings) as aiohttp sub-app with session cookies.

Improvement: bcrypt password hashing + timing-safe compare + session
regeneration on login (legacy panel had the same ideas in PHP; kept).
"""
from __future__ import annotations

import html
import secrets
import time

from aiohttp import web
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Admin, Invoice, MarzbanPanel, PaymentReport, Product, User

_SESSIONS: dict[str, tuple[str, float]] = {}

STYLE = """
body{background:#161210;color:#e8ddd0;font-family:system-ui,sans-serif;margin:0}
a{color:#e08b5a}.wrap{max-width:1100px;margin:2rem auto;padding:0 1rem}
.card{background:#211a15;border:1px solid #3a2d22;border-radius:12px;padding:1.2rem;margin-bottom:1rem}
table{width:100%;border-collapse:collapse}th,td{padding:.5rem;border-bottom:1px solid #3a2d22;text-align:left}
th{color:#c9a}.btn{background:#e08b5a;color:#161210;border:0;padding:.5rem 1rem;border-radius:8px;cursor:pointer}
input{background:#161210;color:#e8ddd0;border:1px solid #3a2d22;padding:.5rem;border-radius:8px}
h1{color:#f0b27a}
"""


def _page(title: str, body: str) -> web.Response:
    return web.Response(text=f"""<!doctype html><html><head><meta charset=utf-8>
<title>{html.escape(title)}</title><style>{STYLE}</style></head>
<body><div class=wrap>{body}</div></body></html>""", content_type="text/html")


def require_auth(fn):
    from functools import wraps
    @wraps(fn)
    async def wrapper(request):
        sid = request.cookies.get("mirza_session", "")
        sess = _SESSIONS.get(sid)
        if not sess or time.time() - sess[1] > 86400:
            raise web.HTTPFound("/panel/login")
        _SESSIONS[sid] = (sess[0], time.time())
        request["admin_user"] = sess[0]
        return await fn(request)
    return wrapper


async def login_get(request):
    if request.cookies.get("mirza_session") in _SESSIONS:
        raise web.HTTPFound("/panel/")
    return _page("Mirza Panel", """
<h1>Mirza Admin</h1>
<form method=post class=card>
 <input name=username placeholder=username required>
 <input name=password type=password placeholder=password required>
 <button class=btn>login</button>
</form>""")


async def login_post(request):
    form = await request.post()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Admin).where(Admin.username == username))
        admin = res.scalar_one_or_none()
    finally:
        await session.close()
    stored = getattr(admin, "password_hash", "") or ""
    ok = False
    try:
        import bcrypt
        # dummy hash for timing parity when user missing
        target = stored or ("$2y$10$dummy.hash.for.timing.attack."
                            "prevention.xxxxxxxxxxxxxxxx")
        ok = bcrypt.checkpw(password.encode(), target.replace("$2y$", "$2b$").encode())
        ok = ok and bool(stored)
    except Exception:
        ok = False
    if not ok:
        return _page("Login", "<h1>Mirza</h1><p>wrong credentials</p>"
                     "<a href=/panel/login>retry</a>")
    sid = secrets.token_hex(24)
    _SESSIONS[sid] = (username, time.time())
    resp = web.HTTPFound("/panel/")
    resp.set_cookie("mirza_session", sid, httponly=True, samesite="Lax")
    return resp


async def logout(request):
    sid = request.cookies.get("mirza_session", "")
    _SESSIONS.pop(sid, None)
    resp = web.HTTPFound("/panel/login")
    resp.del_cookie("mirza_session")
    return resp


@require_auth
async def dashboard(request):
    user = request["admin_user"]
    session = get_sessionmaker()()
    try:
        users_n = (await session.execute(
            sa_select(sa_func.count()).select_from(User))).scalar() or 0
        inv_n = (await session.execute(
            sa_select(sa_func.count()).select_from(Invoice))).scalar() or 0
        rev = (await session.execute(
            sa_select(sa_func.coalesce(sa_func.sum(PaymentReport.price), 0))
            .where(PaymentReport.payment_status == "paid"))).scalar() or 0
        panels_n = (await session.execute(
            sa_select(sa_func.count()).select_from(MarzbanPanel))).scalar() or 0
        prod_n = (await session.execute(
            sa_select(sa_func.count()).select_from(Product))).scalar() or 0
    finally:
        await session.close()
    cards = [("Users", users_n), ("Services", inv_n), ("Revenue", f"{rev:,}"),
             ("Panels", panels_n), ("Products", prod_n)]
    body = f"<p>admin: {user} · <a href=/panel/logout>logout</a></p>"
    for label, val in cards:
        body += f"<div class=card><b>{label}</b><br>{val}</div>"
    body += ("<div class=card><a href='/panel/users'>users</a> · "
             "<a href='/panel/invoices'>invoices</a> · "
             "<a href='/panel/products'>products</a> · "
             "<a href='/panel/payments'>payments</a> · "
             "<a href='/panel/panels'>panels</a> · "
             "<a href='/panel/settings'>settings</a></div>")
    return _page("Dashboard", body)


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["<div class=card><table><tr>" +
           "".join(f"<th>{h}</th>" for h in headers) + "</tr>"]
    for row in rows[:100]:
        out.append("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>")
    out.append("</table></div>")
    return "".join(out)


@require_auth
async def users_page(request):
    q = request.rel_url.query.get("q", "")
    session = get_sessionmaker()()
    try:
        stmt = sa_select(User).order_by(User.id.desc()).limit(100)
        if q:
            stmt = stmt.where(User.username.ilike(f"%{q}%"))
        res = await session.execute(stmt)
        rows = [[u.id, html.escape(u.username), f"{u.balance:,}",
                 u.user_status, "agent" if u.is_agent else "-", u.lang]
                for u in res.scalars()]
    finally:
        await session.close()
    body = ("<form><input name=q placeholder='search username'>"
            "<button class=btn>search</button></form>" +
            _table(["id", "username", "balance", "status", "role", "lang"],
                   rows))
    return _page("Users", body)


@require_auth
async def products_page(request):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Product))
        rows = [[p.code_product, html.escape(p.name_product),
                 f"{p.price_product:,}", f"{p.volume_gb} GB",
                 f"{p.service_days} d", p.location] for p in res.scalars()]
    finally:
        await session.close()
    return _page("Products",
                 _table(["code", "name", "price", "volume", "duration",
                         "location"], rows))


@require_auth
async def payments_page(request):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(PaymentReport).order_by(PaymentReport.id.desc())
            .limit(100))
        rows = [[o.order_id, o.user_id, f"{o.price:,}", o.payment_method,
                 o.payment_status, o.created_at] for o in res.scalars()]
    finally:
        await session.close()
    return _page("Payments", _table(["order", "user", "amount", "method",
                                     "status", "time"], rows))


@require_auth
async def panels_page(request):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(MarzbanPanel))
        rows = [[p.name_panel, p.panel_type, p.url_panel,
                 "up" if p.status else "down"] for p in res.scalars()]
    finally:
        await session.close()
    return _page("Panels", _table(["name", "type", "url", "status"], rows))


@require_auth
async def invoices_page(request):
    from mirza.models import Invoice
    q = request.rel_url.query.get("q", "")
    status = request.rel_url.query.get("status", "")
    session = get_sessionmaker()()
    try:
        stmt = sa_select(Invoice).order_by(Invoice.id_invoice.desc()).limit(100)
        if q:
            stmt = stmt.where((Invoice.uuid == q) |
                              (Invoice.user_id == q) |
                              (Invoice.id_invoice == q))
        if status:
            stmt = stmt.where(Invoice.status == status)
        res = await session.execute(stmt)
        rows = [[i.id_invoice, i.user_id, i.service_location,
                 html.escape(i.product_name or ""), i.uuid,
                 f"{i.price_product}", i.status] for i in res.scalars()]
    finally:
        await session.close()
    filters = (
        '<form><input name=q placeholder="invoice/user/config">'
        '<input name=status placeholder="status">'
        '<button class=btn>filter</button></form>')
    return _page("Invoices", filters +
                 _table(["invoice", "user", "panel", "product", "config",
                         "price", "status"], rows))


SETTINGS_GROUPS = [
    ("shop", ["channel_lock", "default_panel", "support_id",
              "help_text", "broadcast_text"]),
]

# gateway keys belong to PaySetting (what payment services read),
# NOT the shop `setting` KV — writing them there silently no-ops.
PAY_KEYS = {"zarinpal_merchant", "aqayepardakht_pin", "nowpayment_api",
            "plisio_api", "iranpay_base", "apiternado", "feeternado",
            "feestatusternado", "chashbackstar"}


@require_auth
async def settings_page(request):
    if request.method == "POST":
        form = await request.post()
        session = get_sessionmaker()()
        try:
            for key in form.keys():
                val = str(form[key])
                import json as _j
                row: object
                if key in PAY_KEYS:
                    from mirza.models import PaySetting as _PayRow
                    row = _PayRow(name_pay=key, value_pay=val)
                else:
                    from mirza.models import Setting as _SettingModel
                    row = _SettingModel(key=key, value=val, value_json=None)
                    try:
                        parsed = _j.loads(val)
                        if isinstance(parsed, (dict, list)):
                            row.value_json = parsed  # type: ignore[attr-defined]
                    except Exception:
                        pass
                await session.merge(row)
            await session.commit()
        finally:
            await session.close()

    from mirza.models import PaySetting, Setting
    session = get_sessionmaker()()
    kv: dict[str, str] = {}
    try:
        res = await session.execute(sa_select(Setting))
        for r in res.scalars():
            kv[r.key] = r.value or ""
        res2 = await session.execute(
            sa_select(PaySetting.name_pay, PaySetting.value_pay))
        for k, v in res2.all():
            kv.setdefault(k, v or "")
    finally:
        await session.close()

    saved = request.rel_url.query.get("saved")
    body = ("<div class=card><b>✅ saved</b></div>" if saved else "") + """
<form method=post class=card>
"""
    for group, keys in SETTINGS_GROUPS:
        body += f"<h3>{group}</h3>"
        for k in keys:
            val = kv.get(k, "")
            body += (f"<div class=row style='display:flex;gap:8px;"
                     f"padding:4px 0'><span style='flex:1'>{html.escape(k)}"
                     f"</span><input name='{html.escape(k)}' "
                     f"value='{html.escape(val)}' style='flex:2'></div>")
    body += "<br><button class=btn>save</button></form>"
    return _page("Settings", body)


def make_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_get("/", dashboard)
    app.router.add_get("/users", users_page)
    app.router.add_get("/products", products_page)
    app.router.add_get("/payments", payments_page)
    app.router.add_get("/panels", panels_page)
    app.router.add_get("/invoices", invoices_page)
    app.router.add_get("/settings", settings_page)
    app.router.add_post("/settings", settings_page)
    return app
