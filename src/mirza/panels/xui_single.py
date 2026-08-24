"""3x-ui / x-ui single inbound adapter - parity for x-ui_single.php (150 lines).

Login via POST /login (cookie), clients per inbound, /panel/api/inbounds.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from yarl import URL

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "xui_single", meta={"protocols": "vmess,vless,trojan"})
class XUISingleAdapter(PanelAdapter):
    name: ClassVar[str] = "xui_single"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])
        self._cookie: tuple[float, str] | None = None

    async def _login(self) -> str:
        if self._cookie and (time.time() - self._cookie[0]) < 3000:
            return self._cookie[1]
        status, body = await self.client.post(
            "/login",
            data={"username": self.creds["username_panel"],
                  "password": self.creds["password_panel"]},
        )
        ok = isinstance(body, dict) and body.get("success")
        if status >= 400 or not ok:
            raise RuntimeError(f"x-ui login failed: {status} {body}")
        jar = self.client._session.cookie_jar if self.client._session else None
        cookie = jar.filter_cookies(URL(self.client.base_url)) if jar else {}
        raw = "; ".join(f"{k}={v.value}" for k, v in cookie.items())
        self._cookie = (time.time(), raw)
        return raw

    async def _headers(self) -> dict[str, str]:
        return {"Cookie": await self._login(), "Content-Type": "application/json"}

    async def _inbound(self) -> dict:
        status, body = await self.client.get(
            "/panel/api/inbounds/list", headers=await self._headers())
        inbounds = body.get("obj") or [] if isinstance(body, dict) else []
        inbound_id = self.creds.get("inbound_id")
        if inbound_id:
            for ib in inbounds:
                if ib.get("id") == int(inbound_id):
                    return ib
        return inbounds[0] if inbounds else {}

    @staticmethod
    def _clients(inbound: dict) -> list[dict]:
        import json
        try:
            return json.loads(inbound.get("settings") or "{}").get("clients", [])
        except Exception:
            return []

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        import json
        inbound = await self._inbound()
        if not inbound:
            return PanelResult(ok=False, error="no inbound found")
        sub_id = username[:16]
        client = {
            "id": f"{username}-uuid",
            "email": username,
            "totalGB": data_limit,
            "expiryTime": expire_ts * 1000,
            "enable": True,
            "subId": sub_id,
            "tgId": "",
            "limitIp": 0,
            "flow": "",
        }
        payload = {"id": inbound.get("id"),
                   "settings": json.dumps({"clients": [client]})}
        status, body = await self.client.post(
            "/panel/api/inbounds/addClient", json=payload,
            headers=await self._headers())
        if status >= 400 or not isinstance(body, dict) or not body.get("success"):
            return PanelResult(ok=False, error=str(body))
        base = self.creds["url_panel"].rstrip("/")
        sub = f"{base}/sub/{sub_id}"
        return PanelResult(ok=True, user=PanelUser(
            username=username, subscription_url=sub,
            data_limit=data_limit, expire_at=expire_ts), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        inbound = await self._inbound()
        c = next((c for c in self._clients(inbound)
                  if c.get("email") == username), None)
        if not c:
            return PanelResult(ok=False, error="client not found")
        stats = inbound.get("clientStats") or []
        stat = next((s for s in stats if s.get("email") == username), {})
        return PanelResult(ok=True, user=PanelUser(
            username=username,
            data_limit=c.get("totalGB"),
            expire_at=(c.get("expiryTime") or 0) // 1000 or None,
            used_traffic=stat.get("total"),
            status="active" if c.get("enable", True) else "disabled",
            raw=c))

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        client = got.raw
        client.update({k: v for k, v in config.items() if k in client})
        import json
        inbound = await self._inbound()
        payload = {"id": inbound.get("id"), "clientId": client.get("id"),
                   "settings": json.dumps({"clients": [client]})}
        status, body = await self.client.post(
            "/panel/api/inbounds/updateClient", json=payload,
            headers=await self._headers())
        return PanelResult(ok=status < 400 and bool(body.get("success")))

    async def remove_user(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        inbound = await self._inbound()
        status, _ = await self.client.post(
            f"/panel/api/inbounds/{inbound.get('id')}/delClient/"
            f"{got.raw.get('id')}", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"subId": username[:12]})

    async def reset_usage(self, username: str) -> PanelResult:
        inbound = await self._inbound()
        status, _ = await self.client.post(
            f"/panel/api/inbounds/{inbound.get('id')}/client/{username}"
            "/resetIpsAndTraffic", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"enable": enabled})

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/server/status",
                                             headers=await self._headers())
        return body if status < 400 else {}

    # legacy attach_service / used_data parity
    async def used_data(self, username: str) -> int | None:
        got = await self.get_user(username)
        return got.user.used_traffic if got.ok and got.user else None

    async def close(self) -> None:
        await self.client.close()
