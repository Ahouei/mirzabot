"""S-UI adapter - parity for s_ui.php (300 lines).

Auth: /app/login (cookie). Clients under /apiv2/clients; CRUD via /apiv2/client.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from yarl import URL

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "sui", meta={"protocols": "vless,vmess,trojan"})
class SUIAdapter(PanelAdapter):
    name: ClassVar[str] = "sui"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])
        self._cookie: tuple[float, str] | None = None

    async def _login(self) -> str:
        if self._cookie and (time.time() - self._cookie[0]) < 3000:
            return self._cookie[1]
        status, body = await self.client.post(
            "/app/login",
            data={"user": self.creds["username_panel"],
                  "password": self.creds["password_panel"]},
        )
        if status >= 400:
            raise RuntimeError(f"s-ui login failed: {status}")
        jar = self.client._session.cookie_jar if self.client._session else None
        cookie = jar.filter_cookies(URL(self.client.base_url)) if jar else {}
        raw = "; ".join(f"{k}={v.value}" for k, v in cookie.items())
        self._cookie = (time.time(), raw)
        return raw

    async def _headers(self) -> dict[str, str]:
        return {"Cookie": await self._login(), "Content-Type": "application/json"}

    async def _clients(self) -> list[dict]:
        status, body = await self.client.get("/apiv2/clients",
                                             headers=await self._headers())
        if status >= 400:
            return []
        return body.get("obj", {}).get("clients", []) if isinstance(body, dict) else []

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        payload = [{
            "name": username,
            "enable": 1,
            "limits": {"total": data_limit, "expire": expire_ts * 1000},
            "config": product or {},
        }]
        status, body = await self.client.post(
            "/apiv2/client/create", json=payload, headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(body))
        base = self.creds["url_panel"].rstrip("/")
        return PanelResult(ok=True, user=PanelUser(
            username=username, subscription_url=f"{base}/sub/{username}",
            data_limit=data_limit, expire_at=expire_ts), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        for c in await self._clients():
            if c.get("name") == username:
                limits = c.get("limits") or {}
                return PanelResult(ok=True, user=PanelUser(
                    username=username,
                    data_limit=limits.get("total"),
                    expire_at=(limits.get("expire") or 0) // 1000 or None,
                    used_traffic=c.get("usage_total"),
                    status="active" if c.get("enable") else "disabled",
                    raw=c))
        return PanelResult(ok=False, error="not found")

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        client = got.raw
        client.update(config)
        status, _ = await self.client.post(
            "/apiv2/client/update", json=[client], headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def remove_user(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        status, _ = await self.client.post(
            "/apiv2/client/delete", json=[got.raw.get("id")],
            headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"name": username})

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self.client.post(
            "/apiv2/clients/reset_usage", json=[username],
            headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"enable": 1 if enabled else 0})

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/apiv2/server/status",
                                             headers=await self._headers())
        return body if status < 400 else {}

    async def close(self) -> None:
        await self.client.close()
