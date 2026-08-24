"""Marzban adapter - parity for Marzban.php (462 lines).

Endpoints: /api/admin/token, /api/sub, user CRUD, nodes, system stats.
Token cached 1h like legacy token_panel().
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin

TOKEN_TTL = 3500  # legacy: <=3600s reuse


@register_plugin("panel", "marzban", meta={"protocols": "vless,vmess,trojan,ss"})
class MarzbanAdapter(PanelAdapter):
    name: ClassVar[str] = "marzban"

    def __init__(self, creds: dict[str, Any]):
        # accept both the service-layer key (password_panel_encrypted, already
        # decrypted by PanelService) and raw password_panel from monitors
        creds = dict(creds)
        creds.setdefault("password_panel",
                         creds.pop("password_panel_encrypted", ""))
        super().__init__(creds)
        self.client = Client(creds["url_panel"])

    async def _token(self) -> dict:
        async def fetch() -> dict:
            status, body = await self.client.post(
                "/api/admin/token",
                data={"username": self.creds["username_panel"],
                      "password": self.creds["password_panel"]},
            )
            if status >= 400 or not isinstance(body, dict) or "access_token" not in body:
                raise RuntimeError(f"marzban auth failed: {status} {body}")
            return body
        tok = await self.client.cached_token("admin", TOKEN_TTL, fetch)
        return tok

    async def _headers(self) -> dict[str, str]:
        tok = await self._token()
        return {"Authorization": f"Bearer {tok['access_token']}",
                "Content-Type": "application/json"}

    @staticmethod
    def _normalize(body: dict, base_url: str) -> PanelUser:
        sub = body.get("subscription_url") or ""
        if sub and not sub.startswith("http"):
            sub = f"{base_url}/{sub.lstrip('/')}"
        return PanelUser(
            username=body.get("username", ""),
            subscription_url=sub,
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
        payload: dict[str, Any] = {
            "username": username,
            "data_limit": data_limit,
            "expire": expire_ts,
            "note": note,
            "data_limit_reset_strategy": data_limit_reset,
        }
        if product:
            if product.get("inbounds"):
                payload["inbounds"] = product["inbounds"]
            if product.get("proxies"):
                payload["proxies"] = product["proxies"]
        status, body = await self.client.post(
            "/api/user", json=payload, headers=await self._headers())
        if status >= 400:
            detail = body.get("detail") if isinstance(body, dict) else body
            return PanelResult(ok=False, error=str(detail or status), raw=body)
        user = self._normalize(body, self.creds["url_panel"])
        # legacy version_panel==1 decodes base64 sub into links
        if user.links == [] and user.subscription_url:
            import base64
            try:
                status2, raw_sub = await self.client.get(user.subscription_url)
                decoded = base64.b64decode(raw_sub).decode() if isinstance(raw_sub, str) else ""
                user.links = [l for l in decoded.splitlines() if l.strip()] or [raw_sub or ""]
            except Exception:
                pass
        return PanelResult(ok=True, user=user, raw=body)

    async def get_user(self, username: str) -> PanelResult:
        status, body = await self.client.get(
            f"/api/user/{username}", headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status), raw=body)
        return PanelResult(ok=True,
                           user=self._normalize(body, self.creds["url_panel"]), raw=body)

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        status, body = await self.client.put(
            f"/api/user/{username}", json=config, headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status), raw=body)
        return PanelResult(ok=True,
                           user=self._normalize(body, self.creds["url_panel"]), raw=body)

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self.client.delete(
            f"/api/user/{username}", headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(status))

    async def revoke_sub(self, username: str) -> PanelResult:
        status, body = await self.client.post(
            f"/api/user/{username}/revoke_sub", headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        return PanelResult(ok=True,
                           user=self._normalize(body, self.creds["url_panel"]))

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self.client.post(
            f"/api/user/{username}/reset", headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(status))

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"status": "active" if enabled else "disabled"})

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/api/system", headers=await self._headers())
        return body if status < 400 else {}

    # ── extras carried over from legacy (nodes/uptime cron uses these) ──
    async def list_nodes(self) -> list[dict]:
        status, body = await self.client.get("/api/nodes", headers=await self._headers())
        return body if status < 400 and isinstance(body, list) else []

    async def reconnect_node(self, node_id: int) -> bool:
        status, _ = await self.client.post(
            f"/api/node/{node_id}/reconnect", headers=await self._headers())
        return status < 400

    async def close(self) -> None:
        await self.client.close()
