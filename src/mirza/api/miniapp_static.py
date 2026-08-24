"""Static Mini App bundle server.

Serves the legacy React build (app/ directory from upstream) when present,
so the existing Telegram Mini App keeps working against the new backend.
Drop the upstream app/ folder into ./app (or set MIRZA_MINIAPP_DIR) to enable.
"""
from __future__ import annotations

import os
from pathlib import Path

from aiohttp import web

_TYPES = {
    ".html": "text/html", ".js": "application/javascript",
    ".css": "text/css", ".json": "application/json",
    ".woff": "font/woff", ".woff2": "font/woff2",
    ".png": "image/png", ".svg": "image/svg+xml",
}


def _root() -> Path:
    env = os.environ.get("MIRZA_MINIAPP_DIR")
    if env:
        return Path(env)
    return Path.cwd() / "app"


async def serve_miniapp(request: web.Request) -> web.StreamResponse:
    root = _root()
    if not root.is_dir():
        return web.Response(
            status=404, text="Mini App bundle not installed. "
            "Copy the upstream app/ directory here or set MIRZA_MINIAPP_DIR.")

    tail = request.match_info.get("tail", "")
    rel = (tail or "index.html").lstrip("/")
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())) or not target.is_file():
        # SPA fallback: serve index.html for unknown paths
        target = root / "index.html"
        if not target.is_file():
            return web.Response(status=404, text="not found")
    ctype = _TYPES.get(target.suffix.lower(), "application/octet-stream")
    return web.FileResponse(target, headers={"Content-Type": f"{ctype}; charset=utf-8"})
