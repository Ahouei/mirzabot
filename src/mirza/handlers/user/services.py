"""My services / extend / extra volume / extra time / change location.

Parity for text_Purchased_services, extend, extravolume, extratime, changeloc.
"""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Invoice, MarzbanPanel, Product, ServiceOther
from mirza.i18n import t as _t
from mirza.panels.service import PanelService

router = Router(name="services")
_PENDING: dict[str, dict] = {}


async def _user_invoices(user_id: str) -> list[Invoice]:
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.user_id == user_id,
                                     Invoice.status != "test"))
        return list(res.scalars().all())
    finally:
        await session.close()


@router.message(F.text.regexp(r"(?i)(🛍|سرویس|My services)"))
async def my_services(message: Message, db_user=None):
    invoices = await _user_invoices(str(db_user.id))
    if not invoices:
        await message.answer("no services yet")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for inv in invoices[:30]:
        label = f"{inv.product_name or inv.uuid} ({inv.status})"
        kb.button(text=label, callback_data=f"svc#{inv.id_invoice}")
    kb.adjust(1)
    await message.answer("🗂 your services", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("svc#"))
async def service_detail(cb: CallbackQuery, db_user=None):
    iid = cb.data.split("#", 1)[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == iid))
        inv = res.scalar_one_or_none()
    finally:
        await session.close()
    if inv is None:
        await cb.answer("not found", show_alert=True)
        return
    from mirza.i18n import t
    lang = getattr(db_user, "lang", "fa") or "fa"
    from mirza.panels.service import PanelService
    async with PanelService() as panels:
        u = await panels.data_user(inv.service_location, inv.uuid or "")
    lines = [f"🧾 <b>{inv.id_invoice}</b>",
             f"product: {inv.product_name}", f"status: {inv.status}"]
    if u:
        used_gb = round((u.used_traffic or 0) / 1024 ** 3, 2)
        total_gb = round((u.data_limit or 0) / 1024 ** 3, 2)
        exp = time.strftime("%Y-%m-%d", time.localtime(u.expire_at)) \
            if u.expire_at else "-"
        lines += [f"volume: {used_gb}/{total_gb} GB", f"expires: {exp}",
                  t("users.services.config", lang) if u.subscription_url else ""]
        if u.subscription_url:
            lines.append(u.subscription_url)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 extend", callback_data=f"ext#{iid}")
    kb.button(text="➕ extra volume", callback_data=f"exv#{iid}")
    kb.button(text="⏳ extra time", callback_data=f"extime#{iid}")
    kb.button(text=_t("users.services.changeloc",
                      getattr(db_user, "lang", "fa") or "fa")
              if _t("users.services.changeloc", "en")
              != "users.services.changeloc" else "📍 change location",
              callback_data=f"chloc#{iid}")
    kb.button(text="♻️ revoke sub link", callback_data=f"revoke#{iid}")
    kb.adjust(2)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("revoke#"))
async def revoke(cb: CallbackQuery, db_user=None):
    iid = cb.data.split("#", 1)[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == iid))
        inv = res.scalar_one_or_none()
    finally:
        await session.close()
    if inv is None:
        await cb.answer("❌")
        return
    from mirza.panels.service import PanelService
    async with PanelService() as panels:
        u = await panels.revoke_sub(inv.service_location, inv.uuid or "")
    if u and u.subscription_url:
        await cb.message.answer(f"♻️ new link:\n{u.subscription_url}")
        await cb.answer("✅")
    else:
        await cb.answer("failed", show_alert=True)


@router.callback_query(F.data.startswith("ext#"))
async def extend_prompt(cb: CallbackQuery, db_user=None):
    iid = cb.data.split("#", 1)[1]
    _PENDING[str(db_user.id)] = {"await": "extend_days",
                                 "invoice": iid}
    await cb.message.answer("🔄 send days to add (0 = product default):")


@router.callback_query(F.data.startswith("exv#"))
async def extra_volume_prompt(cb: CallbackQuery, db_user=None):
    iid = cb.data.split("#", 1)[1]
    _PENDING[str(db_user.id)] = {"await": "extra_volume", "invoice": iid}
    await cb.message.answer("➕ send GB amount:")


@router.callback_query(F.data.startswith("extime#"))
async def extra_time_prompt(cb: CallbackQuery, db_user=None):
    _PENDING[str(db_user.id)] = {"await": "extra_time",
                                 "invoice": cb.data.split("#", 1)[1]}
    await cb.message.answer("⏳ send days:")


@router.callback_query(F.data.startswith("chloc#"))
async def change_loc_start(cb: CallbackQuery, db_user=None):
    iid = cb.data.split("#", 1)[1]
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == iid))
        inv = res.scalar_one_or_none()
        from sqlalchemy import select as _s
        from mirza.models import MarzbanPanel
        panels = list((await session.execute(
            _s(MarzbanPanel.name_panel, MarzbanPanel.price_change_loc)
            .where(MarzbanPanel.change_loc == True))).all())  # noqa: E712
    finally:
        await session.close()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    kb = InlineKeyboardBuilder()
    for name, price in panels:
        kb.button(text=f"{name} ({price:,})",
                  callback_data=f"chlocgo#{iid}#{name}")
    kb.adjust(1)
    await cb.message.answer("📍 pick new location", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("chlocgo#"))
async def change_loc_go(cb: CallbackQuery, db_user=None):
    _, iid, newloc = cb.data.split("#", 2)
    session = get_sessionmaker()()
    try:
        inv = await _get_invoice(session, iid)
        from mirza.payments.wallet import WalletService
        wallet = WalletService(session)
        balance = await wallet.get_balance(str(db_user.id))
        res = await session.execute(
            sa_select(MarzbanPanel.price_change_loc)
            .where(MarzbanPanel.name_panel == newloc))
        price = res.scalar_one_or_none() or 0
        if balance < price:
            await cb.answer("insufficient funds", show_alert=True)
            return
        old_loc = inv.service_location
        username = inv.uuid or ""
        async with PanelService(session) as panels:
            created = await panels.create_user(
                newloc, "", username,
                data_limit=int(float(inv.volume or 0)),
                expire_ts=_expire(inv),
                user_id=str(db_user.id), kind="changeloc")
            if not created.ok:
                await cb.message.answer(f"❌ {created.error}")
                return
            await panels.remove_user(old_loc, username)
        chg = await wallet.change(str(db_user.id), -price, "changeloc",
                                  ref=iid)
        if not chg.ok:
            await cb.answer(chg.error, show_alert=True)
            return
        inv.service_location = newloc
        await session.commit()
    finally:
        await session.close()
    await cb.answer("✅ migrated")


# numeric input for extra volume/time/extend (FSM-light via _PENDING)


@router.message(F.text.regexp(r"^\d+$"))
async def numeric_input(message: Message, db_user=None):
    info = _PENDING.get(str(db_user.id)) or {}
    mode = info.pop("await", None)
    if not mode:
        return
    amount = int(message.text or "0")
    iid = info.get("invoice", "")
    session = get_sessionmaker()()
    try:
        inv = await _get_invoice(session, iid)
        async with PanelService(session) as panels:
            ok = False
            if mode == "extra_volume":
                ok = await panels.extra_volume(inv.service_location,
                                               inv.uuid or "", amount)
            elif mode == "extra_time":
                ok = await panels.extra_time(inv.service_location,
                                             inv.uuid or "", amount)
            elif mode == "extend_days":
                product_code = (inv.user_info or {}).get("product", "")
                result = await panels.extend(
                    "both", inv.service_location, inv.uuid or "",
                    product_code, extra_days=amount or 0, extra_gb=0)
                ok = result.ok
        if ok:
            row = ServiceOther(invoice_id=iid,
                               kind=mode.replace("_days", ""),
                               amount=amount, price=0,
                               created_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            session.add(row)
            await session.commit()
            await message.answer("✅ done")
        else:
            await message.answer("❌ panel error")
    finally:
        await session.close()


async def _get_invoice(session, iid: str) -> Invoice:
    res = await session.execute(
        sa_select(Invoice).where(Invoice.id_invoice == iid))
    return res.scalar_one()


def _expire(inv: Invoice) -> int:
    try:
        days = int(float((inv.service_time or "30").replace("D", "")))
    except ValueError:
        days = 30
    return int(time.time()) + days * 86400
