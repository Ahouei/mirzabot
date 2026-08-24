"""IBSng ISP billing adapter - parity for ibsng.php + ibsng/Modules/IBSng.php.

XML-RPC style POST to /IBSng/admin/ with form-encoded method calls.
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "ibsng", meta={"protocols": "pppoe,internet-billing"})
class IBSngAdapter(PanelAdapter):
    name: ClassVar[str] = "ibsng"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.client = Client(creds["url_panel"])

    async def _call(self, method: str, extra: dict[str, str]) -> tuple[int, Any]:
        form: dict[str, str] = {
            "auth_name": self.creds["username_panel"],
            "auth_pass": self.creds["password_panel"],
            "x": str(extra),
        }
        status, body = await self.client.post(f"/IBSng/admin/{method}", data=form)
        return status, body

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        group = (product or {}).get("ibsng_group", "default")
        gb = data_limit // (1024 ** 3)
        status, body = await self._call("user/add", {
            "normal_username": username,
            "normal_password": username[:8],
            "group_name": group,
            "credit_amount_gb": str(gb),
            "comment": note,
        })
        if status >= 400:
            return PanelResult(ok=False, error=str(body))
        return PanelResult(ok=True, user=PanelUser(username=username,
                                                   data_limit=data_limit,
                                                   expire_at=expire_ts))

    async def get_user(self, username: str) -> PanelResult:
        status, body = await self._call("user/search", {"query": username})
        rows = body if isinstance(body, list) else []
        if status >= 400 or not rows:
            return PanelResult(ok=False, error="not found")
        row = rows[0]
        return PanelResult(ok=True, user=PanelUser(
            username=username,
            used_traffic=row.get("used_credit"),
            data_limit=row.get("credit"),
            expire_at=int(row.get("expire_date") or 0) or None,
            status="active" if not row.get("is_locked") else "disabled",
            raw=row))

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        status, body = await self._call("user/edit", {"user_id": username,
                                                      **config})
        return PanelResult(ok=status < 400, error=None if status < 400 else str(body))

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self._call("user/delete", {"user_id": username})
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"normal_password": username[:8] + "n"})

    async def reset_usage(self, username: str) -> PanelResult:
        return await self.modify_user(username, {"reset_credit": "1"})

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        return await self.modify_user(
            username, {"attr_lock_user_by": "" if enabled else "admin"})

    async def system_stats(self) -> dict:
        return {}

    async def close(self) -> None:
        await self.client.close()
