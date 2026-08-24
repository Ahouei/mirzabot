"""Telegram webhook endpoint - parity for index.php entry with the secret
validation the PHP version was missing."""
from __future__ import annotations

import logging

from aiohttp import web

log = logging.getLogger(__name__)


async def webhook_handler(request: web.Request) -> web.Response:
    from mirza.config import get_settings
    settings = get_settings()
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.webhook_secret and secret != settings.webhook_secret:
        log.warning("webhook rejected: bad secret from %s",
                    request.remote)
        return web.Response(status=403)
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400)

    # main bot update; a misconfigured/empty token or downstream DB error
    # must not 500 the webhook (Telegram retries forever on non-2xx)
    from mirza.bot import process_update
    try:
        await process_update(settings.api_key, secret, payload)
    except Exception:
        log.exception("webhook update processing failed")
        return web.Response(text="OK")   # ack to stop retry storm
    return web.Response(text="OK")
