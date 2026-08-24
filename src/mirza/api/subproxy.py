"""Subscription proxy - parity for sub/index.php.

GET /sub/{invoice_token} -> live config links from the backend panel.
"""
from __future__ import annotations

import html

from aiohttp import web
from sqlalchemy import select as sa_select

from mirza.db import get_sessionmaker
from mirza.models import Invoice


async def sub_handler(request: web.Request) -> web.Response:
    token = html.escape(request.match_info.get("token", ""), quote=True)
    session = get_sessionmaker()()
    try:
        res = await session.execute(
            sa_select(Invoice).where(Invoice.id_invoice == token))
        inv = res.scalar_one_or_none()
    finally:
        await session.close()
    if inv is None:
        return web.Response(text="ERROR!", content_type="text/plain")
    from mirza.panels.service import PanelService
    async with PanelService() as panels:
        u = await panels.data_user(inv.service_location, inv.uuid or "")
    links = u.links if u and u.links else (
        [u.subscription_url] if u and u.subscription_url else [])
    body = "\r\n".join(links)
    return web.Response(text=body, content_type="text/plain",
                        charset="utf-8")
