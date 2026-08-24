"""Alireza/Sanaei single-inbound adapter - parity for alireza_single.php.

Cookie-based login (/login), clients managed per inbound via /panel/api/inbounds.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

from yarl import URL

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "alireza_single", meta={"protocols": "vmess,vless,trojan"})
class AlirezaSingleAdapter(PanelAdapter):
    name: ClassVar[str] = "alireza_single"

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
            raise RuntimeError(f"alireza login failed: {status} {body}")
        cookie = self.client._session.cookie_jar.filter_cookies(  # type: ignore[union-attr]
            URL(self.client.base_url)) if self.client._session else {}
        raw = "; ".join(f"{k}={v.value}" for k, v in cookie.items())
        self._cookie = (time.time(), raw)
        return raw

    async def _headers(self) -> dict[str, str]:
        return {"Cookie": await self._login(), "Content-Type": "application/json"}

    @staticmethod
    def _find_client(clients: list[dict], username: str) -> dict | None:
        for c in clients:
            email = c.get("email") or ""
            if email == username or email.startswith(f"{username}."):
                return c
        return None

    async def _inbound(self) -> dict:
        inbound_id = self.creds.get("inbound_id")
        status, body = await self.client.get(
            "/panel/api/inbounds/list", headers=await self._headers())
        inbounds = body.get("obj") or [] if isinstance(body, dict) else []
        if inbound_id:
            for ib in inbounds:
                if ib.get("id") == int(inbound_id):
                    return ib
        return inbounds[0] if inbounds else {}

    async def _settings_add(self, username: str, total: int, expire: int,
                            sub_id: str) -> dict:
        import json
        return json.dumps({
            "id": [f"{username}-uuid"],
            "flow": "",
            "email": username,
            "limitIp": 0,
            "totalGB": total,
            "expiryTime": expire,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
        })

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        inbound = await self._inbound()
        if not inbound:
            return PanelResult(ok=False, error="no inbound found")
        sub_id = username[:16]
        payload = {
            "id": inbound.get("id"),
            "settings": await self._settings_add(username, data_limit,
                                                 expire_ts * 1000, sub_id),
        }
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
        clients_raw = inbound.get("clientStats") or []
        settings = inbound.get("settings")
        if isinstance(settings, str):
            import json
            try:
                clients = json.loads(settings).get("clients", [])
            except Exception:
                clients = []
        else:
            clients = clients_raw
        c = self._find_client(clients + clients_raw, username)
        if not c:
            return PanelResult(ok=False, error="client not found")
        stat = next((s for s in clients_raw if s.get("email") == c.get("email")), {})
        return PanelResult(ok=True, user=PanelUser(
            username=c.get("email", username),
            data_limit=c.get("totalGB"),
            expire_at=(c.get("expiryTime") or 0) // 1000 or None,
            used_traffic=stat.get("total"),
            status="active" if stat.get("enable", True) else "disabled",
            raw=c))

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        client = got.raw
        client.update({k: v for k, v in config.items() if k in client})
        import json
        inbound = await self._inbound()
        payload = {"id": inbound.get("id"),
                   "clientId": client.get("id"),
                   "settings": json.dumps({"clients": [client]})}
        status, body = await self.client.post(
            "/panel/api/inbounds/updateClient", json=payload,
            headers=await self._headers())
        return PanelResult(ok=status < 400 and bool(body.get("success")),
                           error=None if status < 400 else str(body))

    async def remove_user(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok:
            return got
        inbound = await self._inbound()
        status, _ = await self.client.post(
            f"/panel/api/inbounds/{inbound.get('id')}/delClient/"
            f"{got.raw.get('id')}", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"subId": username[:12]})

    async def reset_usage(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        inbound = await self._inbound()
        status, _ = await self.client.post(
            f"/panel/api/inbounds/{inbound.get('id')}/client/{got.user.username}"
            "/resetIpsAndTraffic", headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"enable": enabled})

    async def system_stats(self) -> dict:
        status, body = await self.client.get("/server/status",
                                             headers=await self._headers())
        return body if status < 400 else {}

    async def close(self) -> None:
        await self.client.close()
