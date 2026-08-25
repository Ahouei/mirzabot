"""Admin handlers batch 2 - parity for remaining admin.php sections:
gift codes, lucky-wheel config, agent management, categories,
tutorials (help), channels, departments, extra admins.

All admin-gated by the same AdminGate filter as handlers/admin/__init__.
"""
from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import (
    Category,
    Channel,
    Departman,
    Discount,
    GiftCodeConsumed,
    Help,
    User,
)

router = Router(name="admin2")


def _is_admin(tg_id: int) -> bool:
    return tg_id == get_settings().admin_number


class AdminGate:
    def __call__(self, event) -> bool:
        uid = getattr(getattr(event, "from_user", None), "id", None)
        return bool(uid and _is_admin(uid))


router.message.filter(AdminGate())
router.callback_query.filter(AdminGate())


# ── gift / discount codes ────────────────────────────────────────
@router.message(F.text.regexp(r"^/giftcode\s+\S+\s+\d+"))
async def add_giftcode(message: Message):
    """Create a discount/gift code with a usage limit."""
    parts = (message.text or "").split()
    code, limit = parts[1], int(parts[2])
    session = get_sessionmaker()()
    try:
        exists = (await session.execute(
            sa_select(Discount).where(Discount.code == code)
        )).scalar_one_or_none()
        if exists is not None:
            await message.answer(f"⚠️ code `{code}` already exists")
            return
        # /giftcode <code> <limit> [percent] — value defaults to 20%
        parts2 = (message.text or "").split()
        percent = int(parts2[3]) if len(parts2) > 3 else 20
        session.add(Discount(code=code, usage_limit=limit,
                             discount_percent=max(0, min(percent, 100))))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ gift code `{code}` created "
                         f"(limit {limit}, edit % via web panel)")


@router.message(F.text.regexp(r"^/giftcodes$"))
async def list_giftcodes(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Discount).limit(50))
        rows = list(res.scalars().all())
        from sqlalchemy import func as sa_func
        counts = dict((await session.execute(
            sa_select(GiftCodeConsumed.code, sa_func.count())
            .group_by(GiftCodeConsumed.code))).all())
    finally:
        await session.close()
    lines = ["🎟 codes:"]
    for d in rows:
        consumed = int(counts.get(d.code, 0))
        lines.append(f"• <code>{d.code}</code> −{d.discount_percent}% "
                     f"used {consumed}/{d.usage_limit or '∞'}")
    await message.answer("\n".join(lines) or "none")


# ── categories ───────────────────────────────────────────────────
@router.message(F.text.regexp(r"^/addcat\s+.+"))
async def add_category(message: Message):
    title = (message.text or "").split(maxsplit=1)[1]
    session = get_sessionmaker()()
    try:
        order = len(list((await session.execute(
            sa_select(Category))).scalars().all()))
        session.add(Category(title=title, sort_order=order + 1))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ category `{title}` added")


@router.message(F.text.regexp(r"^/cats$"))
async def list_categories(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Category).order_by(Category.sort_order))
        cats = list(res.scalars().all())
    finally:
        await session.close()
    lines = [f"{c.sort_order}. {c.title}" for c in cats]
    await message.answer("🗂 categories:\n" + "\n".join(lines) if cats
                         else "no categories")


@router.callback_query(F.data.startswith("catdel#"))
async def del_category(cb: CallbackQuery):
    cid = int(cb.data.split("#")[1])
    session = get_sessionmaker()()
    try:
        cat = await session.get(Category, cid)
        if cat:
            await session.delete(cat)
            await session.commit()
    finally:
        await session.close()
    await cb.answer("deleted")


# ── tutorials / help ─────────────────────────────────────────────
@router.message(F.text.regexp(r"^/addhelp"))
async def add_help(message: Message):
    """`/addhelp <name> | <text>` — tutorial entry shown in 📚 help."""
    raw = (message.text or "").split(maxsplit=1)[1:]
    if not raw or "|" not in raw[0]:
        await message.answer("usage: /addhelp <name> | <text>")
        return
    name, text = [x.strip() for x in raw[0].split("|", 1)]
    session = get_sessionmaker()()
    try:
        session.add(Help(name_os=name, media_os=text, type_media_os="text",
                         description_os=text[:4000]))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ tutorial `{name}` saved")


@router.message(F.text.regexp(r"^/helplist$"))
async def list_help(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Help))
        helps = list(res.scalars().all())
    finally:
        await session.close()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for h in helps:
        kb.button(text=h.name_os[:24], callback_data=f"helpshow#{h.id}")
    kb.adjust(1)
    await message.answer("📚 tutorials:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("helpshow#"))
async def show_help(cb: CallbackQuery):
    hid = int(cb.data.split("#")[1])
    session = get_sessionmaker()()
    try:
        h = await session.get(Help, hid)
    finally:
        await session.close()
    if h:
        await cb.message.answer(f"📖 <b>{h.name_os}</b>\n{h.description_os}")


# ── channels (forced-join list) ──────────────────────────────────
@router.message(F.text.regexp(r"^/addchannel\s+@\w+"))
async def add_channel(message: Message):
    handle = (message.text or "").split()[1].lstrip("@")
    session = get_sessionmaker()()
    try:
        session.add(Channel(remark=handle, link_join=f"https://t.me/{handle}",
                            link=handle))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ channel @{handle} registered")


@router.message(F.text.regexp(r"^/channels$"))
async def list_channels(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Channel))
        chans = list(res.scalars().all())
    finally:
        await session.close()
    lines = [f"• @{c.link} ({c.remark})" for c in chans]
    await message.answer("📢 channels:\n" + "\n".join(lines) or "none")


@router.message(F.text.regexp(r"^/lockchannel\s+@\w+"))
async def lock_channel(message: Message):
    """Set the mandatory channel enforced by AuthMiddleware."""
    handle = (message.text or "").split()[1]
    session = get_sessionmaker()()
    try:
        from mirza.models import Setting
        await session.merge(Setting(key="channel_lock",
                                    value=handle.lstrip("@")))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"🔒 mandatory channel set to {handle}")


# ── agent management ─────────────────────────────────────────────
@router.message(F.text.regexp(r"^/makeagent\s+\d+"))
async def make_agent(message: Message):
    uid = (message.text or "").split()[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(User).where(User.id == uid))
        u = res.scalar_one_or_none()
        if not u:
            await message.answer("user not found")
            return
        u.is_agent = True
        u.agent_level = "a"
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ {uid} is now an agent")


@router.message(F.text.regexp(r"^/removeagent\s+\d+"))
async def remove_agent(message: Message):
    uid = (message.text or "").split()[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(User).where(User.id == uid))
        u = res.scalar_one_or_none()
        if u:
            u.is_agent = False
            u.agent_level = "f"
            await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ {uid} agent revoked")


@router.message(F.text.regexp(r"^/agents$"))
async def list_agents(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(User).where(User.is_agent == True))  # noqa: E712
        agents = list(res.scalars().all())
    finally:
        await session.close()
    lines = [f"• {a.id} @{a.username} (balance {a.balance:,})"
             for a in agents]
    await message.answer("👥 agents:\n" + "\n".join(lines) or "none")


@router.message(F.text.regexp(r"^/agentrequests$"))
async def agent_requests(message: Message):
    from mirza.models import AgentRequest
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(AgentRequest).where(AgentRequest.status == "pending"))
        reqs = list(res.scalars().all())
    finally:
        await session.close()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for r_ in reqs[:20]:
        kb.button(text=f"approve {r_.user_id}",
                  callback_data=f"agentok#{r_.user_id}")
    kb.adjust(1)
    await message.answer(f"📨 pending requests: {len(reqs)}",
                         reply_markup=kb.as_markup() if reqs else None)


@router.callback_query(F.data.startswith("agentok#"))
async def approve_agent(cb: CallbackQuery):
    uid = cb.data.split("#")[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(User).where(User.id == uid))
        u = res.scalar_one_or_none()
        if u:
            u.is_agent = True
            u.agent_level = "a"
        await session.execute(
            sa_update_agent(uid))
        await session.commit()
    finally:
        await session.close()
    await cb.answer("approved ✅")


def sa_update_agent(uid: str):
    from sqlalchemy import update as sa_update

    from mirza.models import AgentRequest
    return sa_update(AgentRequest).where(
        AgentRequest.user_id == uid).values(status="approved")


# ── departments (support ticketing) ──────────────────────────────
@router.message(F.text.regexp(r"^/adddept\s+.+"))
async def add_department(message: Message):
    name = (message.text or "").split(maxsplit=1)[1]
    session = get_sessionmaker()()
    try:
        session.add(Departman(name=name))
        await session.commit()
    finally:
        await session.close()
    await message.answer(f"✅ department `{name}` added")


@router.message(F.text.regexp(r"^/depts$"))
async def list_departments(message: Message):
    session = get_sessionmaker()()
    try:
        res = await session.execute(sa_select(Departman))
        depts = list(res.scalars().all())
    finally:
        await session.close()
    lines = [f"• [{d.id}] {d.name}" for d in depts]
    await message.answer("🏛 departments:\n" + "\n".join(lines) or "none")


# ── wheel prizes config ──────────────────────────────────────────
@router.message(F.text.regexp(r"^/wheelprizes(\s+[\d,]+)?$"))
async def set_wheel_prizes(message: Message):
    """Comma-separated prize amounts stored in settings."""
    from mirza.models import Setting
    arg = (message.text or "").split(maxsplit=1)
    if len(arg) > 1:
        raw = arg[1].replace(" ", "")
        if not all(p.isdigit() for p in raw.split(",")):
            await message.answer("usage: /wheelprizes 0,5000,10000,50000")
            return
        import json as _j
        session = get_sessionmaker()()
        try:
            await session.merge(Setting(
                key="wheel_prizes",
                value=_j.dumps([int(x) for x in raw.split(",")])))
            await session.commit()
        finally:
            await session.close()
        await message.answer(f"🎡 prizes set: {raw}")
        return
    # no args → show current
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Setting.value).where(Setting.key == "wheel_prizes"))
        val = res.scalar_one_or_none()
    finally:
        await session.close()
    await message.answer(f"🎡 current prizes: {val or '[defaults]'}")


# ── balance adjust (legacy addBalanceUser) ───────────────────────
@router.message(F.text.regexp(r"^/addbalance\s+\d+\s+-?\d+"))
async def add_balance(message: Message):
    _, uid, amount = (message.text or "").split()
    from mirza.payments.wallet import WalletService
    session = get_sessionmaker()()
    try:
        wallet = WalletService(session)
        change = await wallet.change(
            uid, int(amount), "admin",
            note=f"by admin {get_settings().admin_number}",
            allow_negative=True)
    finally:
        await session.close()
    if change.ok:
        await message.answer(f"✅ {uid} balance now {change.new_balance:,}")
    else:
        await message.answer(f"❌ {change.error}")


def routers() -> list[Router]:
    return [router]


def new_tracking_code() -> str:
    return secrets.token_hex(6)
