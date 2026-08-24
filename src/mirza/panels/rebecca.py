"""Rebecca adapter - parity for Rebecca.php (114 lines). Bearer-token API."""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "rebecca", meta={"protocols": "vless,vmess,trojan"})
class RebeccaAdapter(PanelAdapter):
    name: ClassVar[str] = "rebecca"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])

    async def _headers(self) -> dict[str, str]:
        # legacy stores the bearer token directly in password_panel
        return {"Authorization": f"Bearer {self.creds['password_panel']}",
                "Content-Type": "application/json"}

    @staticmethod
    def _normalize(body: dict) -> PanelUser:
        return PanelUser(
            username=body.get("username", ""),
            subscription_url=body.get("subscription_url"),
            links=list(body.get("links") or []),
            data_limit=body.get("data_limit"),
            expire_at=body.get("expire"),
            used_traffic=body.get("used_traffic"),
            status=body.get("status", "active"),
            raw=body,
        )

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        payload = {"username": username, "data_limit": data_limit,
                   "expire": expire_ts, "note": note}
        if product and product.get("inbounds"):
            payload["inbounds"] = product["inbounds"]
        status, body = await self.client.post("/api/v1/users", json=payload,
                                              headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status), raw=body)
        return PanelResult(ok=True, user=self._normalize(body), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        status, body = await self.client.get(f"/api/v1/users/{username}",
                                             headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        return PanelResult(ok=True, user=self._normalize(body), raw=body)

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        status, body = await self.client.put(f"/api/v1/users/{username}",
                                             json=config,
                                             headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(status),
                           raw=body)

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self.client.delete(f"/api/v1/users/{username}",
                                             headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        status, body = await self.client.post(
            f"/api/v1/users/{username}/revoke", headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        return PanelResult(ok=True, user=self._normalize(body))

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self.client.post(
            f"/api/v1/users/{username}/reset", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(
            username, {"status": "active" if enabled else "disabled"})

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/api/v1/system",
                                             headers=await self._headers())
        return body if status < 400 and isinstance(body, dict) else {}

    async def close(self) -> None:
        await self.client.close()
