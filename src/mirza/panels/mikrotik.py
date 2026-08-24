"""MikroTik RouterOS REST API adapter - parity for mikrotik.php (167 lines).

POST /rest/login then RouterOS v7 /rest interface (ppp secret / hotspot user).
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "mikrotik", meta={"protocols": "ppp,hotpspot,wg"})
class MikrotikAdapter(PanelAdapter):
    name: ClassVar[str] = "mikrotik"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])
        self._logged = False

    async def _ensure_login(self) -> None:
        if self._logged:
            return
        status, _ = await self.client.post(
            "/rest/login",
            json={"username": self.creds["username_panel"],
                  "password": self.creds["password_panel"]},
        )
        if status >= 400:
            raise RuntimeError(f"mikrotik login failed: {status}")
        self._logged = True

    async def _headers(self) -> dict[str, str]:
        await self._ensure_login()
        return {"Content-Type": "application/json"}

    def _kind(self) -> str:
        # inbound_id semantics: 1=ppp-secret, 2=hotspot-user
        return "ppp/secret" if str(self.creds.get("inbound_id", "1")) == "1" \
            else "ip/hotspot/user"

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        kind = self._kind()
        gb = max(data_limit // (1024 ** 3), 0)
        profile = product.get("mikrotik_profile", "default") if product else "default"
        payload = {"name": username, "password": username[:8],
                   "comment": note, "profile": profile}
        if gb:
            payload["limit-bytes-total"] = f"{gb}G" if kind.startswith("ppp") else gb * (1024 ** 3)
        status, body = await self.client.post(
            f"/rest/{kind}", json=payload, headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(body))
        return PanelResult(ok=True, user=PanelUser(username=username,
                                                   raw=body,
                                                   data_limit=data_limit,
                                                   expire_at=expire_ts))

    async def get_user(self, username: str) -> PanelResult:
        kind = self._kind()
        status, body = await self.client.get(
            f"/rest/{kind}?name={username}", headers=await self._headers())
        rows = body if isinstance(body, list) else []
        row = rows[0] if rows else None
        if status >= 400 or not row:
            return PanelResult(ok=False, error="not found")
        used: int | None = None
        try:
            s2, stats = await self.client.get(
                f"/rest/{kind}/{'ppp' if kind.startswith('ppp') else 'hotspot'}/"
                f"active?name={username}", headers=await self._headers())
            _ = s2, stats  # active session info optional
        except Exception:
            pass
        return PanelResult(ok=True, user=PanelUser(username=username, raw=row,
                                                   used_traffic=used))

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        rid = got.raw.get(".id")
        status, body = await self.client.patch(
            f"/rest/{'ppp/secret'}/{rid}" if self._kind().startswith("ppp")
            else f"/rest/ip/hotspot/user/{rid}",
            json=config, headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(body))

    async def remove_user(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        rid = got.raw.get(".id")
        kind = self._kind()
        status, _ = await self.client.delete(
            f"/rest/{kind}/{rid}", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"password": username[:8] + "r"})

    async def reset_usage(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"limit-bytes-total": "0"})

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"disabled": "no" if enabled else "yes"})

    async def system_stats(self) -> dict:
        status, body = await self.client.get(
            "/rest/system/resource", headers=await self._headers())
        return body if status < 400 and isinstance(body, dict) else {}

    async def close(self) -> None:
        await self.client.close()
