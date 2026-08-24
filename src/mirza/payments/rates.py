"""Crypto/FX rate service - parity for function.php rate_arze().

USD/Toman: legacy scraped bon-bast.com (regex on first <span>digits</span>).
That host now 403s non-browser clients, so fetch order is:
  1. setting 'usd_rate' (admin-set override)
  2. TGJU open API (cdn.jsdelivr.net/gh/tgju) free USD chart
  3. bon-bast scrape (legacy path, kept for when it works again)
TRX priced from diaadata.org. Cached in-process with TTL (improvement;
legacy fetched per call).

Note: the legacy Stars path reads a 'Ton' rate that rate_arze() never
returned - a dead reference upstream. Stars here uses USD only.
"""
from __future__ import annotations

import json as _json
import re
import time

import aiohttp

_TRON_ASSET = ("https://api.diadata.org/v1/assetQuotation/Tron/"
               "0x0000000000000000000000000000000000000000")
_BONBAST = "https://www.bon-bast.com/"
_TGJU = ("https://cdn.jsdelivr.net/gh/majidip2009/tgju@main/"
         "data/ref-data/price_dollar_rl.json")

_cache: dict[str, tuple[float, dict[str, int] | None]] = {}
_TTL = 300  # seconds


async def _fetch(url: str, timeout: float = 8.0,
                 headers: dict[str, str] | None = None) -> str | None:
    try:
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers=headers) as s:
            async with s.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except Exception:
        return None


async def _usd_toman() -> int:
    # 1) admin override
    from mirza.models import Setting
    from sqlalchemy import select as sa_select
    from mirza.db import get_sessionmaker
    raw: str | None = None
    try:
        session = get_sessionmaker()()
        try:
            res = await session.execute(
                sa_select(Setting.value).where(Setting.key == "usd_rate"))
            raw = res.scalar_one_or_none()
        finally:
            await session.close()
    except Exception:
        raw = None   # DB not migrated yet - fall through to public sources
    if raw:
        try:
            return int(float(raw))
        except ValueError:
            pass
    # 2) TGJU mirror (price in rial -> /10 toman)
    body = await _fetch(_TGJU)
    if body:
        try:
            data = _json.loads(body)
            price_rial = int(str(data.get("p", data.get("Price", 0))
                                 ).replace(",", "") or 0)
            if price_rial > 0:
                return max(price_rial // 10, 1)
        except (ValueError, TypeError):
            pass
    # 3) legacy bon-bast scrape (browser UA; kept for parity)
    html = await _fetch(_BONBAST, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html"})
    if html:
        m = re.search(r"<span>\s*([\d,]+)\s*</span>", html)
        if m:
            return int(m.group(1).replace(",", ""))
    return 0


async def rate_arze(force: bool = False) -> dict[str, int] | None:
    """Returns {'USD': toman, 'TRX': toman} or None when USD unavailable
    (same contract as legacy: callers must handle null)."""
    hit = _cache.get("rates")
    if not force and hit and (time.time() - hit[0]) < _TTL and hit[1]:
        return hit[1]

    usd = await _usd_toman()
    if usd == 0:
        return None   # legacy parity: fail loud, no fallback guess

    trx_usd = 0.0
    body = await _fetch(_TRON_ASSET)
    if body:
        try:
            trx_usd = float((_json.loads(body) or {}).get("Price") or 0)
        except ValueError:
            trx_usd = 0.0
    rates = {"USD": usd, "TRX": int(trx_usd * usd)}
    _cache["rates"] = (time.time(), rates)
    return rates


def cached_rates() -> dict[str, int] | None:
    hit = _cache.get("rates")
    return hit[1] if hit else None
