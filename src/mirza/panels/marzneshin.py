"""Marzneshin adapter - parity for marzneshin.php (245 lines).

Auth: /api/admins/token (JWT). Users under /api/users, mutate via /api/users/{u}.
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin

TOKEN_TTL = 3500


@register_plugin("panel", "marzneshin", meta={"protocols": "vless,vmess,trojan"})
class MarzneshinAdapter(PanelAdapter):
    name: ClassVar[str] = "marzneshin"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])

    async def _headers(self) -> dict[str, str]:
        async def fetch() -> dict:
            status, body = await self.client.post(
                "/api/admins/token",
                data={"username": self.creds["username_panel"],
                      "password": self.creds["password_panel"]},
            )
            if status >= 400:
                raise RuntimeError(f"marzneshin auth failed: {status}")
            return body
        tok = await self.client.cached_token("admin", TOKEN_TTL, fetch)
        return {"Authorization": f"Bearer {tok.get('access_token', '')}",
                "Content-Type": "application/json"}

    @staticmethod
    def _normalize(body: dict, base_url: str) -> PanelUser:
        sub = body.get("subscription_url") or ""
        if sub and not sub.startswith("http"):
            sub = f"{base_url}{'' if base_url.endswith('/') else '/'}{sub.lstrip('/')}"
        u = body.get("user") or body
        return PanelUser(
            username=u.get("username", ""),
            subscription_url=sub,
            links=list(body.get("links") or []),
            data_limit=u.get("data_limit"),
            expire_at=u.get("expire_at") and int(u["expire_at"]) or None,
            used_traffic=u.get("used_traffic"),
            status="active" if not u.get("disabled") else "disabled",
            raw=body,
        )

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        payload: dict[str, Any] = {
            "username": username,
            "data_limit": data_limit,
            "expire_date": expire_ts * 1000 if expire_ts else 0,   # marzneshin: ms
            "note": note,
            "data_limit_reset_strategy": data_limit_reset.upper(),
        }
        if product and product.get("inbounds"):
            payload["inbounds"] = product["inbounds"]
        status, body = await self.client.post(
            "/api/users", json=payload, headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(body if isinstance(body, dict) else status))
        return PanelResult(ok=True, user=self._normalize(body, self.creds["url_panel"]), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        status, body = await self.client.get(
            f"/api/users/{username}", headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        return PanelResult(ok=True, user=self._normalize(body, self.creds["url_panel"]), raw=body)

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        current = await self.get_user(username)
        if not current.ok or current.user is None:
            return current
        merged: dict[str, Any] = dict(current.raw.get("user") or {})
        merged.update(config)
        status, body = await self.client.put(
            f"/api/users/{username}", json=merged, headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(status),
                           raw=body)

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self.client.delete(
            f"/api/users/{username}", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        # marzneshin rotates sub via user modify with new sub_revoked_at
        return await self.modify_user(username, {})

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self.client.post(
            f"/api/users/{username}/reset_usage", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        path = "enable" if enabled else "disable"
        status, _ = await self.client.post(
            f"/api/users/{username}/{path}", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/api/system", headers=await self._headers())
        return body if status < 400 else {}

    async def close(self) -> None:
        await self.client.close()
