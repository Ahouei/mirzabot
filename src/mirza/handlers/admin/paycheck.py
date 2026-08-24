"""/paycheck - admin command: verify configured payment gateways without
spending money. Pings each gateway's cheapest status/auth endpoint and
reports configured / reachable / missing-key state.
"""
from __future__ import annotations

import time

import aiohttp

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select as sa_select

from mirza.config import get_settings
from mirza.db import get_sessionmaker
from mirza.models import PaySetting

router = Router(name="paycheck")

REQUIRED_KEYS = {
    "zarinpal": ["zarinpal_merchant"],
    "aqayepardakht": ["aqayepardakht_pin"],
    "nowpayments": ["nowpayment_api"],
    "plisio": ["plisio_api"],
    "iranpay": ["apiiranpay", "iranpay_base"],
    "cubepay": ["apiternado"],
    "card2card": ["active_cards"],
}

# cheap no-spend endpoints per gateway (auth/status probes)
PROBES = {
    "nowpayments": ("GET", "https://api.nowpayments.io/v1/status"),
    "zarinpal": ("GET", "https://api.zarinpal.com/pg/v4/payment/validation.json"),
}


def _is_admin(tg_id: int) -> bool:
    return tg_id == get_settings().admin_number


class AdminGate:
    def __call__(self, event) -> bool:
        uid = getattr(getattr(event, "from_user", None), "id", None)
        return bool(uid and _is_admin(uid))


router.message.filter(AdminGate())


@router.message(F.text.regexp(r"^/paycheck$"))
async def paycheck(message: Message):
    session = get_sessionmaker()()
    kv: dict[str, str] = {}
    try:
        res = await session.execute(
            sa_select(PaySetting.name_pay, PaySetting.value_pay))
        for k, v in res.all():
            if v:
                kv[k] = v
    finally:
        await session.close()

    lines = ["🩺 **gateway health**"]
    all_ok = True
    for gw, keys in REQUIRED_KEYS.items():
        missing = [k for k in keys if not kv.get(k)]
        if missing:
            lines.append(f"⚪️ {gw}: not configured "
                         f"(missing {', '.join(missing)})")
            continue
        probe = PROBES.get(gw)
        if probe is None:
            lines.append(f"🟢 {gw}: configured")
            continue
        method, url = probe
        headers = {}
        if gw == "nowpayments":
            headers["x-api-key"] = kv["nowpayment_api"]
        t0 = time.monotonic()
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)) as s:
                async with s.request(method, url, headers=headers) as resp:
                    ms = int((time.monotonic() - t0) * 1000)
                    # 200/40x from the API itself means reachable + auth seen;
                    # only network errors/timeouts mean broken.
                    lines.append(f"🟢 {gw}: reachable ({resp.status}) {ms}ms")
        except Exception as e:
            all_ok = False
            lines.append(f"🔴 {gw}: unreachable — {type(e).__name__}")
    await message.answer("\n".join(lines))


def routers() -> list[Router]:
    return [router]
