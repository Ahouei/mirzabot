"""HTTP client helpers shared by panel adapters and gateways.

Replaces legacy request.php CurlRequest with an aiohttp session wrapper:
- bearer / cookie / form auth
- token cache with TTL (mirrors Marzban 1h token reuse)
- timeouts from settings ($request_exec_timeout equivalent)
"""
from __future__ import annotations

import time
from typing import Any

import aiohttp


class HttpError(Exception):
    pass


class Client:
    def __init__(self, base_url: str, timeout_s: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: aiohttp.ClientSession | None = None
        self._token_cache: dict[str, tuple[float, Any]] = {}

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── core verbs ───────────────────────────────────────────────
    async def request(self, method: str, path: str, *, json: Any | None = None,
                      data: dict | list | None = None, headers: dict[str, str] | None = None,
                      cookies: dict[str, str] | None = None) -> tuple[int, Any]:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        sess = await self._sess()
        async with sess.request(method, url, json=json, data=data,
                                headers=headers, cookies=cookies) as resp:
            body = await resp.text()
            status = resp.status
        try:
            import orjson as _json
            parsed = _json.loads(body)
        except Exception:
            parsed = body
        return status, parsed

    async def get(self, path: str, **kw) -> tuple[int, Any]:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw) -> tuple[int, Any]:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw) -> tuple[int, Any]:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw) -> tuple[int, Any]:
        return await self.request("DELETE", path, **kw)

    async def patch(self, path: str, **kw) -> tuple[int, Any]:
        return await self.request("PATCH", path, **kw)

    # ── cached token login (Marzban-style /api/admin/token) ─────
    async def cached_token(self, key: str, ttl: float,
                           fetcher) -> Any:
        """fetcher: async () -> token payload dict. Cached in-process."""
        hit = self._token_cache.get(key)
        if hit and (time.time() - hit[0]) < ttl:
            return hit[1]
        payload = await fetcher()
        self._token_cache[key] = (time.time(), payload)
        return payload
