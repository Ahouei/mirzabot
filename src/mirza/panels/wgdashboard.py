"""WGDashboard (WireGuard) adapter - parity for WGDashboard.php (239 lines).

Session-based auth; peers CRUD under /api/wireguard/service/<if>/.
"""
from __future__ import annotations

import base64
import time
from typing import Any, ClassVar

from yarl import URL

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "wgdashboard", meta={"protocols": "wireguard"})
class WGDashboardAdapter(PanelAdapter):
    name: ClassVar[str] = "wgdashboard"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])
        self._cookie: tuple[float, str] | None = None
        self._interface = creds.get("inbound_id") or "wg0"

    async def _login(self) -> str:
        if self._cookie and (time.time() - self._cookie[0]) < 3000:
            return self._cookie[1]
        status, body = await self.client.post(
            "/api/authenticate",
            data={"username": self.creds["username_panel"],
                  "password": self.creds["password_panel"]},
        )
        if status >= 400:
            raise RuntimeError(f"wgdashboard login failed: {status}")
        jar = self.client._session.cookie_jar if self.client._session else None
        cookie = jar.filter_cookies(URL(self.client.base_url)) if jar else {}
        raw = "; ".join(f"{k}={v.value}" for k, v in cookie.items())
        self._cookie = (time.time(), raw)
        return raw

    async def _headers(self) -> dict[str, str]:
        return {"Cookie": await self._login(), "Content-Type": "application/json"}

    async def _peers(self) -> list[dict]:
        status, body = await self.client.get(
            f"/api/wireguard/service/getWireguardConfigurationInfo"
            f"?configurationName={self._interface}",
            headers=await self._headers())
        if status >= 400 or not isinstance(body, dict):
            return []
        return (body.get("data", {}).get("configuration", {}).get("Peers")) or []

    @staticmethod
    def _gen_keys() -> tuple[str, str]:
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import \
                X25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            priv = X25519PrivateKey.generate()
            priv_b = priv.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption())
            pub_b = priv.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            return (base64.b64encode(priv_b).decode(),
                    base64.b64encode(pub_b).decode())
        except Exception:
            import os
            return (base64.b64encode(os.urandom(32)).decode(),
                    base64.b64encode(os.urandom(32)).decode())

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        privkey, pubkey = self._gen_keys()
        allowed_ips = (product or {}).get("allowed_ips")
        payload = {
            "publicKey": pubkey,
            "privateKey": privkey,
            "allowedIp": allowed_ips,
            "name": username,
            "endpoint_allowed_ip": "0.0.0.0/0",
            "presharedKey": "",
            "enabled": True,
            "persistentKeepalive": 25,
        }
        status, body = await self.client.post(
            f"/api/wireguard/service/addPeer?name={self._interface}",
            json=payload, headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(body))
        conf_url = f"{self.creds['url_panel'].rstrip('/')}/download/{username}.conf"
        return PanelResult(ok=True, user=PanelUser(
            username=username, subscription_url=conf_url,
            data_limit=data_limit, expire_at=expire_ts), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        for p in await self._peers():
            if p.get("name") == username:
                return PanelResult(ok=True, user=PanelUser(
                    username=username,
                    data_limit=p.get("total_data_usage"),
                    used_traffic=p.get("total_receive"),
                    expire_at=int(p.get("expire_time") or 0) or None,
                    online=bool(p.get("status")),
                    raw=p))
        return PanelResult(ok=False, error="peer not found")

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        peer = got.raw
        peer.update(config)
        payload = {"id": username, **{k.replace("pub", "publicKey"): v for k, v in
                                      config.items()}}
        status, _ = await self.client.post(
            f"/api/wireguard/service/updatePeer?name={self._interface}",
            json=payload, headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def remove_user(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        status, _ = await self.client.post(
            f"/api/wireguard/service/deletePeer?name={self._interface}",
            json={"id": got.raw.get("id")}, headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        _, pub = self._gen_keys()
        return await self.modify_user(username, {"publicKey": pub})

    async def reset_usage(self, username: str) -> PanelResult:
        got = await self.get_user(username)
        if not got.ok or got.user is None:
            return got
        status, _ = await self.client.post(
            "/api/util/resetWireguardConfigurationDataUsage",
            json={"configurationName": self._interface,
                  "peers": [got.raw.get("id")]},
            headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {"enabled": enabled})

    async def system_stats(self) -> dict:
        status, body = await self.client.get(
            "/api/protocol/status", headers=await self._headers())
        return body if status < 400 and isinstance(body, dict) else {}

    async def close(self) -> None:
        await self.client.close()
