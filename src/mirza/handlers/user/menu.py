"""Main menu handler - parity for index.php start/menu + language switch."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.i18n import t
from mirza.models import Setting, User

router = Router(name="menu")


def _main_keyboard(lang: str):
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    from mirza.i18n import t as _t
    labels = _t("users.mainMenu", lang)
    if not isinstance(labels, dict):
        labels = {}
    kb = ReplyKeyboardBuilder()
    texts = [
        labels.get("text_sell"), labels.get("text_extend"),
        labels.get("text_usertest"), labels.get("text_wheel_luck"),
        labels.get("text_Purchased_services"), labels.get("accountwallet"),
        labels.get("text_affiliates"), labels.get("text_Tariff_list"),
        labels.get("text_support"), labels.get("text_help"),
    ]
    for txt in texts:
        if txt:
            kb.button(text=txt)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject | None = None,
                db_user: User | None = None, t=None):  # noqa: A002
    # deep-link referral: /start ref_<id>
    if command and command.args and command.args.startswith("ref_") and db_user:
        ref = command.args[4:]
        if ref.isdigit() and ref != str(db_user.id) and not db_user.referrer_id:
            session = get_sessionmaker()()
            try:
                res = await session.execute(
                    sa_select(User).where(User.id == ref))
                if res.scalar_one_or_none():
                    db_user.referrer_id = ref
                    await session.commit()
            finally:
                await session.close()
    lang = getattr(db_user, "lang", "fa") or "fa"
    await message.answer("👋 " + str(t("users.mainMenu.text_sell")),
                         reply_markup=_main_keyboard(lang))


@router.message(F.text.regexp(r"(?i)(📚|help|راهنما|Помощь|帮助)"))
async def help_menu(message: Message, t=None):  # noqa: A002
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Setting.value).where(Setting.key == "help_text"))
        text = res.scalar_one_or_none()
    finally:
        await session.close()
    await message.answer(text or str(t("users.mainMenu.text_help")))


@router.callback_query(F.data == "confirmchannel")
async def confirm_channel(cb: CallbackQuery, db_user: User | None = None,
                          bot=None):
    ok = True
    try:
        from sqlalchemy import select as _s
        session = get_sessionmaker()()
        res = await session.execute(
            _s(Setting.value).where(Setting.key == "channel_lock"))
        lock = res.scalar_one_or_none()
        await session.close()
        if lock and bot:
            member = await bot.get_chat_member(str(lock).lstrip("@"),
                                               int(cb.from_user.id))
            ok = member.status not in ("left", "kicked")
    except Exception:
        ok = True
    if ok and db_user:
        db_user.join_channel_ok = True
        session = get_sessionmaker()()
        await session.merge(db_user)
        await session.commit()
        await session.close()
        await cb.answer("✅", show_alert=True)
    else:
        await cb.answer("❌", show_alert=True)


@router.message(F.text.regexp(r"^/lang\s*(fa|en|ru|zh)?"))
async def set_lang(message: Message, db_user: User | None = None):
    if not db_user:
        return
    arg = (message.text or "").split()[-1]
    if arg in ("fa", "en", "ru", "zh"):
        db_user.lang = arg
        session = get_sessionmaker()()
        await session.merge(db_user)
        await session.commit()
        await session.close()
        await message.answer(f"🌐 {arg}",
                             reply_markup=_main_keyboard(arg))
