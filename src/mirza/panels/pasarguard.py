"""Pasarguard adapter.

Legacy treated Pasarguard as a Marzban-compatible dialect (admin.php aliased
type pasarguard -> marzban with version_panel=1). We keep it as a thin
configuration variant of the Marzban adapter registered under its own name so
operators see it in panel pickers.
"""
from __future__ import annotations

from typing import ClassVar

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.registry import register_plugin
from mirza.panels.marzban import MarzbanAdapter


@register_plugin("panel", "pasarguard", meta={"protocols": "vless,vmess,trojan,ss"})
class PasarguardAdapter(MarzbanAdapter):
    name: ClassVar[str] = "pasarguard"

    async def create_user(self, username: str, *, data_limit: int, expire_ts: int,
                          note: str = "", data_limit_reset: str = "no_reset",
                          product: dict | None = None) -> PanelResult:
        result = await super().create_user(username, data_limit=data_limit,
                                           expire_ts=expire_ts, note=note,
                                           data_limit_reset=data_limit_reset,
                                           product=product)
        if result.ok and result.user is not None:
            u: PanelUser = result.user
            if not u.links:
                u.links = [u.subscription_url or ""]
        return result
