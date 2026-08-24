"""Admin handlers - parity for admin.php (10.9k lines) core command surface.

Sections: stats, users, panels CRUD, products, categories, payments,
broadcast, settings toggles, agent management, backup trigger, gift codes.
Router is admin-gated by middleware below.
"""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func as sa_func
from sqlalchemy import select as sa_select

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import Invoice, MarzbanPanel, PaymentReport, Product, User

router = Router(name="admin")


def _is_admin(tg_id: int) -> bool:
    return tg_id == get_settings().admin_number


class AdminGate:
    """Simple filter: only primary admin passes."""

    def __call__(self, event) -> bool:
        uid = getattr(getattr(event, "from_user", None), "id", None)
        return bool(uid and _is_admin(uid))


router.message.filter(AdminGate())
router.callback_query.filter(AdminGate())


# ── stats ────────────────────────────────────────────────────────
@router.message(F.text.regexp(r"(?i)(/stats|📊)"))
async def stats(message: Message):
    session = get_sessionmaker()()
    try:
        users_n = (await session.execute(
            sa_select(sa_func.count()).select_from(User))).scalar() or 0
        invoices_n = (await session.execute(
            sa_select(sa_func.count()).select_from(Invoice))).scalar() or 0
        paid = (await session.execute(
            sa_select(sa_func.coalesce(sa_func.sum(PaymentReport.price), 0))
            .where(PaymentReport.payment_status == "paid"))).scalar() or 0
        panels_n = (await session.execute(
            sa_select(sa_func.count()).select_from(MarzbanPanel))).scalar() or 0
    finally:
        await session.close()
    await message.answer(
        f"📊 <b>stats</b>\n"
        f"users: {users_n}\nservices: {invoices_n}\n"
        f"revenue: {paid:,}\npanels: {panels_n}")


# ── panel management ─────────────────────────────────────────────
@router.message(F.text.regexp(r"^/addpanel"))
async def add_panel(message: Message):
    # /addpanel name|type|url|user|pass [inbound_id]
    try:
        parts = (message.text or "").split(maxsplit=1)[1].split("|")
        name, ptype, url, puser, ppass = parts[:5]
        inbound = int(parts[5]) if len(parts) > 5 else None
    except (IndexError, ValueError):
        await message.answer("usage: /addpanel name|type|url|user|pass "
                             "[inbound_id]\ntypes: " + ", ".join(_panel_types()))
        return
    from mirza.panels.service import _decrypt_secret  # noqa: F401
    session = get_sessionmaker()()
    try:
        enc = _encrypt_secret(ppass)
        session.add(MarzbanPanel(
            code_panel=f"{name}-{int(time.time())}",
            name_panel=name, url_panel=url.rstrip("/"),
            username_panel=puser, password_panel_encrypted=enc,
            panel_type=ptype if ptype in _panel_types() else "marzban",
            inbound_id=inbound))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ panel `{name}` added ({ptype})")


@router.message(F.text.regexp(r"^/panels$"))
async def list_panels(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(MarzbanPanel))
        rows = list(res.scalars().all())
    finally:
        await session.close()
    lines = ["🔌 panels:"]
    for p in rows:
        lines.append(f"• <b>{p.name_panel}</b> [{p.panel_type}] "
                     f"{'✅' if p.status else '⛔️'} {p.url_panel}")
    await message.answer("\n".join(lines) or "none")


@router.callback_query(F.data.startswith("paneltoggle#"))
async def toggle_panel(cb: CallbackQuery):
    name = cb.data.split("#", 1)[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(MarzbanPanel).where(MarzbanPanel.name_panel == name))
        panel = res.scalar_one_or_none()
        if panel:
            panel.status = not panel.status
            await session.commit()
    finally:
        await session.close()
    await cb.answer("toggled ✅")


# ── products ─────────────────────────────────────────────────────
@router.message(F.text.regexp(r"^/addproduct"))
async def add_product(message: Message):
    # /addproduct code|name|price|volume_gb|days|location
    try:
        code, name, price, vol, days, loc = \
            (message.text or "").split(maxsplit=1)[1].split("|")
    except (IndexError, ValueError):
        await message.answer("usage: /addproduct code|name|price|volume_gb|"
                             "days|location(/all)")
        return
    session = get_sessionmaker()()
    try:
        session.add(Product(code_product=code, name_product=name,
                            price_product=int(price), volume_gb=int(vol),
                            service_days=int(days), location=loc))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ product `{code}` added")


@router.message(F.text.regexp(r"^/products$"))
async def list_products(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Product))
        rows = list(res.scalars().all())
    finally:
        await session.close()
    lines = ["📦 products:"]
    for p in rows:
        lines.append(f"• <code>{p.code_product}</code> {p.name_product} — "
                     f"{p.price_product:,} | {p.volume_gb}GB/{p.service_days}d "
                     f"@ {p.location}")
    await message.answer("\n".join(lines) or "none")


# ── user management ──────────────────────────────────────────────
@router.message(F.text.regexp(r"^/finduser\s+\S+"))
async def find_user(message: Message):
    q = (message.text or "").split()[1]
    session = get_sessionmaker()()
    try:
        col = User.id if q.isdigit() else User.username
        res = await session.execute(sa_select(User).where(col == q))
        u = res.scalar_one_or_none()
        if not u:
            await message.answer("not found")
            return
        invs = (await session.execute(
            sa_select(sa_func.count()).select_from(Invoice)
            .where(Invoice.user_id == str(u.id)))).scalar() or 0
        await message.answer(
            f"👤 {u.id} @{u.username}\nbalance: {u.balance:,}\n"
            f"agent: {'yes' if u.is_agent else 'no'}\n"
            f"status: {u.user_status} | lang: {u.lang}\nservices: {invs}")
    finally:
        await session.close()


@router.message(F.text.regexp(r"^/block\s+\d+"))
async def block_user(message: Message):
    await _set_status(message, "block")


@router.message(F.text.regexp(r"^/unblock\s+\d+"))
async def unblock_user(message: Message):
    await _set_status(message, "active")


async def _set_status(message: Message, status: str):
    uid = (message.text or "").split()[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(User).where(User.id == uid))
        u = res.scalar_one_or_none()
        if u:
            u.user_status = status
            await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ {uid} → {status}")


# ── broadcast ────────────────────────────────────────────────────
@router.message(F.command("broadcast"))
async def broadcast_cmd(message: Message):
    _BROADCAST["await"] = True
    await message.answer("📣 send the message to broadcast "
                         "(HTML). /cancel to abort.")


_BROADCAST: dict[str, bool] = {}
_TOPUP_UNUSED: dict = {}


@router.message(F.command("cancel"))
async def cancel_cmd(message: Message):
    _BROADCAST.pop("await", None)
    await message.answer("cancelled")


@router.message(lambda m: _BROADCAST.get("await") is True)
async def broadcast_capture(message: Message):
    _BROADCAST.pop("await", None)
    session = get_sessionmaker()()
    try:
        from mirza.models import Setting
        row = Setting(key="broadcast_text", value=message.html_text)
        await session.merge(row)
        res = await session.execute(sa_select(User.id))
        targets = [r for (r,) in res.all()]
    finally:
        await session.close()
    for uid in targets:
        sess2 = get_sessionmaker()()
        try:
            u = await sess2.get(User, str(uid))
            if u:
                u.check_status = "sending"
        finally:
            await sess2.commit()
            await sess2.close()
    await message.answer(f"📣 queued for {len(targets)} users "
                         "(sendmessage job delivers at 30/min)")


# ── payments report ──────────────────────────────────────────────
@router.message(F.text.regexp(r"^/payments"))
async def payments_report(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(PaymentReport)
            .order_by(PaymentReport.id.desc()).limit(10))
        rows = list(res.scalars().all())
    finally:
        await session.close()
    lines = ["💳 recent payments:"]
    for o in rows:
        lines.append(f"• {o.order_id[:12]} {o.price:,} [{o.payment_method}] "
                     f"{o.payment_status}")
    await message.answer("\n".join(lines) or "none")


# ── manual sell ──────────────────────────────────────────────────
@router.message(F.text.regexp(r"^/sell\s+\S+\s+\S+"))
async def manual_sell(message: Message):
    _, uid, code = (message.text or "").split(maxsplit=2)
    from mirza.panels.service import PanelService
    session = get_sessionmaker()()
    try:
        async with PanelService(session) as panels:
            username = PanelService.generate_username("random", 8)
            result = await panels.create_user(
                await _default_panel_name(session), code, username,
                data_limit=0, expire_ts=int(time.time()) + 30 * 86400,
                user_id=uid, tg_username="", kind="manual")
    finally:
        await session.close()
    if result.ok:
        await message.answer(f"✅ sold\n{result.subscription_url or ''}")
    else:
        await message.answer(f"❌ {result.error}")


async def _default_panel_name(session) -> str:
    res = await session.execute(
        sa_select(MarzbanPanel.name_panel).limit(1))
    return res.scalar_one_or_none() or "main"


# ── helpers ──────────────────────────────────────────────────────
def _panel_types() -> list[str]:
    from mirza.registry import registry
    return sorted(registry.names("panel"))


def _encrypt_secret(raw: str) -> str:
    import base64
    import hashlib

    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(
        hashlib.sha256(get_settings().session_secret.encode()).digest())
    return Fernet(key).encrypt(raw.encode()).decode()


def routers() -> list[Router]:
    from .manage import router as manage_router
    from .paycheck import router as paycheck_router
    return [router, manage_router, paycheck_router]
