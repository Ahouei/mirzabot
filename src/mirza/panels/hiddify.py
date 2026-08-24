"""Hiddify adapter - parity for hiddify.php (91 lines).

Bearer dashboard auth (/api/v2/dashboard/...), users CRUD under
/admin/user/, subscription links from user detail.
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "hiddify", meta={"protocols": "vless,vmess,trojan"})
class HiddifyAdapter(PanelAdapter):
    name: ClassVar[str] = "hiddify"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])
        self.secret = creds.get("secret_code") or creds.get("password_panel", "")
        self._root_profile = str(creds.get("root_profile", "") or "")

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}",
                "Content-Type": "application/json"}

    def _base_api(self) -> str:
        secret_path = getattr(self, "_root_profile", "") or ""
        return f"/{secret_path}api/v2" if secret_path else "/api/v2"

    @staticmethod
    def _normalize(u: dict) -> PanelUser:
        return PanelUser(
            username=u.get("uuid") or u.get("name", ""),
            subscription_url=u.get("subscription_url"),
            data_limit=u.get("usage_limit"),
            expire_at=int(u.get("expire") or 0) or None,
            used_traffic=(u.get("current_usage_GB") or 0),
            status=u.get("mode", "active").lower(),
            raw=u,
        )

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        import uuid as _uuid
        uid = str(_uuid.uuid4())
        payload = {
            "uuid": uid,
            "name": username,
            "comment": note,
            "usage_limit": data_limit,
            "expire": expire_ts,
            "mode": "no_reset" if data_limit_reset == "no_reset" else "reset_ugb",
        }
        status, body = await self.client.post(
            f"{self._base_api()}/admin/user/", json=payload,
            headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status), raw=body)
        base = self.creds["url_panel"].rstrip("/")
        sub = f"{base}/{self._root_profile}{uid}/subscription/"
        return PanelResult(ok=True, user=self._normalize({**payload,
                                                         "subscription_url": sub}),
                           raw=body)

    async def get_user(self, username: str) -> PanelResult:
        # hiddify keys users by uuid; core passes the stored uuid
        status, body = await self.client.get(
            f"{self._base_api()}/admin/user/{username}/",
            headers=await self._headers())
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        return PanelResult(ok=True, user=self._normalize(body), raw=body)

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        current = await self.get_user(username)
        merged = {**(current.raw if current.ok else {}), **config}
        status, body = await self.client.put(
            f"{self._base_api()}/admin/user/{username}/", json=merged,
            headers=await self._headers())
        return PanelResult(ok=status < 400, error=None if status < 400 else str(status))

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self.client.delete(
            f"{self._base_api()}/admin/user/{username}/",
            headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        import uuid as _uuid
        return await self.modify_user(username, {"uuid": str(_uuid.uuid4())})

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self.client.delete(
            f"{self._base_api()}/admin/user/{username}/usage/",
            headers=await self._headers())
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(username, {
            "mode": "active" if enabled else "deactivate"})

    async def system_stats(self) -> dict:
        status, body = await self.client.get(
            f"{self._base_api()}/dashboard/status/",
            headers=await self._headers())
        return body if status < 400 else {}

    async def server_status(self) -> dict:
        """Legacy serverstatus()."""
        return await self.system_stats()

    async def close(self) -> None:
        await self.client.close()
