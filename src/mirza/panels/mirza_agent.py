"""Mirza Agent adapter - parity for mirza_agent.php (agent-network panels).

Actions-based JSON API: ?actions=list_panel, actions=user_create etc.,
bearer token in password_panel.
"""
from __future__ import annotations

from typing import Any, ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.panels.http import Client
from mirza.registry import register_plugin


@register_plugin("panel", "mirza_agent", meta={"kind": "agent-network"})
class MirzaAgentAdapter(PanelAdapter):
    name: ClassVar[str] = "mirza_agent"

    def __init__(self, creds: dict[str, Any]):
        super().__init__(creds)
        self.base = creds["url_panel"].split("?")[0]
        self.client = Client(self.base)

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.creds['password_panel']}",
                "Content-Type": "application/json"}

    async def _action(self, action: str, payload: dict | None = None) -> tuple[int, Any]:
        body = {"actions": action, **(payload or {})}
        sep = "&" if "?" in self.creds["url_panel"] else "?"
        url = f"{self.creds['url_panel']}{sep}actions={action}"
        return await self.client.request("POST", url, json=body,
                                         headers=await self._headers())

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        status, body = await self._action("user_create", {
            "username": username,
            "data_limit_gb": max(data_limit // (1024 ** 3), 1),
            "expire_days": max((expire_ts - _now()) // 86400, 0),
            "note": note,
        })
        if status >= 400:
            return PanelResult(ok=False, error=str(body))
        sub = (body or {}).get("subscription_url") if isinstance(body, dict) else None
        return PanelResult(ok=True, user=PanelUser(username=username,
                                                   subscription_url=sub,
                                                   data_limit=data_limit,
                                                   expire_at=expire_ts), raw=body)

    async def get_user(self, username: str) -> PanelResult:
        status, body = await self._action("user_get", {"username": username})
        if status >= 400:
            return PanelResult(ok=False, error=str(status))
        b = body if isinstance(body, dict) else {}
        return PanelResult(ok=True, user=PanelUser(
            username=username,
            subscription_url=b.get("subscription_url"),
            used_traffic=(b.get("used_gb") or 0) * (1024 ** 3),
            expire_at=b.get("expire"), raw=b))

    async def modify_user(self, username: str, config: dict) -> PanelResult:
        status, _ = await self._action("user_update", {"username": username,
                                                       **config})
        return PanelResult(ok=status < 400)

    async def remove_user(self, username: str) -> PanelResult:
        status, _ = await self._action("user_delete", {"username": username})
        return PanelResult(ok=status < 400)

    async def revoke_sub(self, username: str) -> PanelResult:
        status, _ = await self._action("user_revoke", {"username": username})
        return PanelResult(ok=status < 400)

    async def reset_usage(self, username: str) -> PanelResult:
        status, _ = await self._action("user_reset", {"username": username})
        return PanelResult(ok=status < 400)

    async def set_enabled(self, username: str, enabled: bool) -> PanelResult:
        status, _ = await self._action(
            "user_enable" if enabled else "user_disable", {"username": username})
        return PanelResult(ok=status < 400)

    async def system_stats(self) -> dict:
        status, body = await self._action("system_stats")
        return body if status < 400 and isinstance(body, dict) else {}

    async def list_agent_panels(self) -> list[dict]:
        """Legacy get_panel_list()."""
        status, body = await self._action("list_panel")
        return body if status < 400 and isinstance(body, list) else []

    async def close(self) -> None:
        await self.client.close()


def _now() -> int:
    import time
    return int(time.time())
