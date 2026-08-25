"""Mini App API - exact action contract of legacy api/miniapp.php.

Actions (from the PHP match block): invoices, service, user_info,
countries, categories, time_ranges, services, custom_price, purchase.
Auth: per-user session token (user.token), same as legacy.
"""
from __future__ import annotations

import json
import secrets
import time

from aiohttp import web
from sqlalchemy import select as sa_select

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import Category, Invoice, MarzbanPanel, Product, User
from mirza.panels.service import PanelService


def _json(data, status: int = 200) -> web.Response:
    return web.json_response({"status": status < 400, "msg": "", **data}
                             if isinstance(data, dict) else data,
                             status=status)


async def _auth_user(request: web.Request) -> User | None:
    """Session token decides identity — never client-supplied user_id."""
    token = ""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.rel_url.query.get("token", "")
    if request.method == "POST":
        body = await request.json()
        if isinstance(body, dict):
            token = token or str(body.get("token", ""))
            request["body"] = body
    if not token:
        return None
    session = get_sessionmaker()()
    try:
        try:
            res = await session.execute(
                sa_select(User).where(User.token == token))
            return res.scalar_one_or_none()
        except Exception:
            # DB not migrated: no valid sessions can exist
            return None
    finally:
        await session.close()


# ── actions ──────────────────────────────────────────────────────
async def mini_invoices(user: User, data: dict) -> web.Response:
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.user_id == user.id)
            .order_by(Invoice.id_invoice.desc()))
        rows = [{
            "id_invoice": i.id_invoice,
            "username_service": i.uuid,
            "name_product": i.product_name,
            "price_product": i.price_product,
            "Service_location": i.service_location,
            "Status": i.status,
            "time_sell": i.time_sell,
        } for i in res.scalars()]
        return _json({"invoices": rows})
    finally:
        await session.close()


async def mini_service(user: User, data: dict) -> web.Response:
    iid = str(data.get("id_invoice") or data.get("username") or "")
    session = get_sessionmaker()()
    try:
        inv = (await session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == iid))).scalar_one_or_none()
    finally:
        await session.close()
    if inv is None or inv.user_id != user.id:
        return _json({"msg": "not found"}, 404)
    async with PanelService() as panels:
        u = await panels.data_user(inv.service_location, inv.uuid or "")
    payload = {
        "id_invoice": inv.id_invoice,
        "uuid": inv.uuid,
        "status_panel": inv.status,
        "expire": u.expire_at if u else None,
        "data_limit": u.data_limit if u else None,
        "used_traffic": u.used_traffic if u else None,
        "subscription_url": u.subscription_url if u else None,
        "links": u.links if u else [],
    }
    return _json(payload)


async def mini_user_info(user: User, _data: dict) -> web.Response:
    return _json({"user_info": {
        "id": user.id, "username": user.username,
        "Balance": user.balance, "lang": user.lang,
        "affiliatescount": user.affiliates_count,
        "score": user.score}})


async def mini_countries(_user: User, _data: dict) -> web.Response:
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(MarzbanPanel).where(MarzbanPanel.status == True))  # noqa: E712
        rows = [{"country_id": p.code_panel, "name": p.name_panel}
                for p in res.scalars()]
        return _json({"countries": rows})
    finally:
        await session.close()


async def mini_categories(_user: User, _data: dict) -> web.Response:
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Category).order_by(Category.sort_order))
        rows = [{"category_id": c.id, "title": c.title} for c in res.scalars()]
        return _json({"categories": rows})
    finally:
        await session.close()


async def mini_time_ranges(_user: User, data: dict) -> web.Response:
    """Distinct durations available for a location/volume (legacy shape)."""
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Product))
        ranges = sorted({p.service_days for p in res.scalars()})
        return _json({"time_ranges": [{"day": d} for d in ranges]})
    finally:
        await session.close()


async def mini_services(_user: User, data: dict) -> web.Response:
    """Product list filtered by country/category/time/volume."""
    session = get_sessionmaker()()
    try:
        q = sa_select(Product)
        loc = data.get("country_id") or data.get("id_panel")
        if loc and loc != "":
            q = q.where((Product.location == loc) |
                        (Product.location == "/all"))
        cat = data.get("category_id")
        if cat and str(cat) not in ("0", ""):
            q = q.where(Product.category_id == int(cat))
        days = data.get("time_days")
        if days and str(days) not in ("0", ""):
            q = q.where(Product.service_days <= int(days))
        vol = data.get("traffic_gb")
        if vol and str(vol) not in ("0", ""):
            q = q.where(Product.volume_gb <= int(vol))
        res = await session.execute(q)
        rows = [{
            "code_product": p.code_product,
            "name_product": p.name_product,
            "price_product": p.price_product,
            "Volume_constraint": f"{p.volume_gb} GB",
            "Service_time": f"{p.service_days} D",
            "Location": p.location,
        } for p in res.scalars()]
        return _json({"services": rows})
    finally:
        await session.close()


async def mini_custom_price(user: User, data: dict) -> web.Response:
    """Custom volume/time price quote from panel pricing columns."""
    panel_name = str(data.get("id_panel", ""))
    gb = int(float(data.get("volume_gb", 0) or 0))
    days = int(float(data.get("time_days", 0) or 0))
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(MarzbanPanel).where(
                MarzbanPanel.name_panel == panel_name))
        p = res.scalar_one_or_none()
    finally:
        await session.close()
    if p is None:
        return _json({"msg": "panel not found"}, 404)
    price = (p.price_custom_volume * max(gb - p.main_volume, 0)
             + p.price_custom_time * max(days - p.main_time, 0))
    return _json({"price": max(price, 0)})


async def mini_purchase(user: User, data: dict) -> web.Response:
    """Create invoice + Unpaid order; reply with pay options (wallet/gw)."""
    code = str(data.get("code_product", ""))
    method = str(data.get("method", "wallet"))
    session = get_sessionmaker()()
    try:
        prod = (await session.execute(
            sa_select(Product).where(Product.code_product == code))).scalar_one_or_none()
    finally:
        await session.close()
    if prod is None:
        return _json({"msg": "product not found"}, 404)

    # one_buy_status guard (legacy parity)
    if prod.one_buy_status:
        session2 = get_sessionmaker()()
        try:
            dupes = (await session2.execute(
                sa_select(Invoice).where(Invoice.user_id == user.id,
                                         Invoice.product_name == code)
            )).scalars().first()
        finally:
            await session2.close()
        if dupes is not None:
            return _json({"msg": "already purchased this plan"}, 409)

    order_token = secrets.token_hex(10)
    session3 = get_sessionmaker()()
    try:
        session3.add(Invoice(
            id_invoice=order_token, user_id=user.id,
            username=user.username,
            service_location=prod.location, product_name=code,
            price_product=str(prod.price_product),
            volume=str(prod.volume_gb), service_time=str(prod.service_days),
            time_sell=time.strftime("%Y-%m-%d %H:%M:%S"),
            status="pending"))
        await session3.commit()
    finally:
        await session3.close()

    from mirza.payments.service import PaymentService
    psession = get_sessionmaker()()
    try:
        order = await PaymentService(psession).create_order(
            user.id, int(prod.price_product), method, invoice_id=order_token)

        if method == "wallet":
            # inline settlement: charge, then provision immediately
            from mirza.panels.service import PanelService
            from mirza.payments.wallet import WalletService
            wallet = WalletService(psession)
            charge = await wallet.change(user.id, -int(prod.price_product),
                                         "purchase", ref=order.order_id)
            if not charge.ok:
                await psession.rollback()
                return _json({"msg": "insufficient balance"}, 402)
            async with PanelService(psession) as panels:
                result = await panels.create_user(
                    prod.location or "", code, "",
                    data_limit=int(float(prod.volume_gb) * 1024 ** 3),
                    expire_ts=int(time.time()) + int(prod.service_days) * 86400,
                    user_id=user.id, tg_username=user.username or "")
            if not result.ok:
                await wallet.change(user.id, int(prod.price_product),
                                    "refund", note=f"provision failed {code}")
                return _json({"msg": f"provision failed: {result.error}"}, 502)
            inv2 = (await psession.execute(
                sa_select(Invoice).where(Invoice.id_invoice == order_token)
            )).scalar_one()
            inv2.status = "enable"
            await psession.commit()
            return _json({
                "invoice": {"id_invoice": order_token,
                            "price": prod.price_product},
                "order": {"order_id": order.order_id, "method": method,
                          "status": "paid"},
                "config": {"subscription_url": result.subscription_url,
                           "links": result.links or []},
            })

        return _json({
            "invoice": {"id_invoice": order_token,
                        "price": prod.price_product},
            "order": {"order_id": order.order_id,
                      "method": method,
                      "status": "Unpaid"},
        })
    finally:
        await psession.close()


ACTIONS = {
    "invoices": mini_invoices,
    "service": mini_service,
    "user_info": mini_user_info,
    "countries": mini_countries,
    "categories": mini_categories,
    "time_ranges": mini_time_ranges,
    "services": mini_services,
    "custom_price": mini_custom_price,
    "purchase": mini_purchase,
}


async def miniapp(request: web.Request) -> web.Response:
    user = await _auth_user(request)
    if user is None:
        return _json({"msg": "Token invalid"}, 403)
    data = request.get("body") or dict(request.rel_url.query)
    action = str(data.get("actions", data.get("action", "")))
    handler = ACTIONS.get(action)
    if handler is None:
        return _json({"msg": "Action Invalid"}, 400)
    if getattr(user, "user_status", "active") == "block":
        return _json({"msg": "blocked"}, 402)
    return await handler(user, data)


def verify_init_data(init_data: str, bot_token: str,
                     max_age_s: int = 86400) -> dict | None:
    """Validate Telegram WebApp initData per core.telegram.org spec.

    Returns the parsed user dict when valid, else None. Checks:
      1. HMAC-SHA256(secret_key, data_check_string) == hash
         secret_key = HMAC(bot_token, "WebAppData")
      2. auth_date freshness (replay window)
    """
    import hashlib
    import hmac as hmac_mod
    from urllib.parse import parse_qsl

    if not init_data or not bot_token:
        return None
    pairs = sorted(parse_qsl(init_data, keep_blank_values=True))
    given = dict(pairs).get("hash", "")
    if not given:
        return None
    # Telegram's data_check_string excludes the hash field itself
    data_check = "\n".join(f"{k}={v}" for k, v in pairs if k != "hash")
    secret = hmac_mod.new(b"WebAppData", bot_token.encode(),
                          hashlib.sha256).digest()
    calc = hmac_mod.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac_mod.compare_digest(calc, given):
        return None
    try:
        auth_date = int(dict(pairs).get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date and time.time() - auth_date > max_age_s:
        return None
    try:
        return json.loads(dict(pairs).get("user", "{}"))
    except Exception:
        return {}


async def token_exchange(request: web.Request) -> web.Response:
    """Issue/return the Mini App session token for a Telegram user.

    Identity comes from signed Telegram WebApp initData — a bare user_id is
    rejected so accounts cannot be hijacked by guessing numeric ids.
    """
    settings = get_settings()
    try:
        body = await request.json()
    except Exception:
        body = {}
    init_data = str(body.get("initData")
                    or request.rel_url.query.get("initData") or "")
    if not init_data:
        # dev convenience only when no bot token configured (nothing to forge)
        if settings.api_key:
            return _json({"msg": "initData required"}, 401)
        uid = str(body.get("user_id", "")
                  or request.rel_url.query.get("user_id", ""))
        if not uid.isdigit():
            return _json({"msg": "initData or user_id required"}, 400)
    else:
        tg_user = verify_init_data(init_data, settings.api_key)
        if not tg_user or not str(tg_user.get("id", "")).isdigit():
            return _json({"msg": "invalid initData"}, 401)
        uid = str(tg_user["id"])

    session = get_sessionmaker()()
    try:
        try:
            row = await session.get(User, uid)
            if row is None:
                row = User(id=uid, username=str(
                    body.get("username") or uid))
                session.add(row)
            if not row.token:
                row.token = secrets.token_hex(16)
            await session.commit()
        except Exception:
            await session.rollback()
            return _json({"msg": "database unavailable — run migrations"}, 503)
        return _json({"token": row.token})
    finally:
        await session.close()
