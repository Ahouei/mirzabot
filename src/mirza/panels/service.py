"""Panel service layer - parity for panels.php ManagePanel class (2554 lines).

Single facade the handlers call. Resolves adapters via the registry, persists
invoices, normalizes errors, handles username generation and extend methods.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from mirza.contracts import PanelAdapter, PanelResult, PanelUser
from mirza.db import get_sessionmaker
from mirza.models import Invoice, MarzbanPanel, Product


@dataclass
class ProvisionResult:
    ok: bool
    invoice: Invoice | None = None
    links: list[str] | None = None
    subscription_url: str | None = None
    error: str | None = None


class PanelService:
    """Replaces ManagePanel: createUser/DataUser/extend/RemoveUser/..."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "PanelService":
        if self._session is None:
            self._session = get_sessionmaker()()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    # ── adapter resolution ────────────────────────────────────────
    @staticmethod
    def _adapter_for(panel: MarzbanPanel) -> PanelAdapter:
        from mirza.registry import registry
        creds = {
            "url_panel": panel.url_panel,
            "username_panel": panel.username_panel,
            # decrypt at use-site; stored encrypted at rest (improvement)
            "password_panel": _decrypt_secret(panel.password_panel_encrypted),
            "secret_code": panel.secret_code,
            "inbound_id": panel.inbound_id,
        }
        return registry.get("panel", panel.panel_type)(creds)

    # ── helpers ───────────────────────────────────────────────────
    @staticmethod
    def generate_username(method: str = "random", length: int = 8,
                          prefix: str = "") -> str:
        alphabet = string.ascii_lowercase + string.digits
        if method == "number":
            return "".join(secrets.choice(string.digits) for _ in range(length))
        return prefix + "".join(secrets.choice(alphabet) for _ in range(length))

    async def get_panel(self, name: str) -> MarzbanPanel | None:
        assert self._session is not None
        res = await self._session.execute(
            sa_select(MarzbanPanel).where(MarzbanPanel.name_panel == name))
        return res.scalar_one_or_none()

    async def get_product(self, code: str) -> Product | None:
        assert self._session is not None
        res = await self._session.execute(
            sa_select(Product).where(Product.code_product == code))
        return res.scalar_one_or_none()

    # ── core operations (parity set) ─────────────────────────────
    async def create_user(self, panel_name: str, product_code: str,
                          username: str, *, data_limit: int, expire_ts: int,
                          user_id: str = "", tg_username: str = "",
                          kind: str = "buy") -> ProvisionResult:
        panel = await self.get_panel(panel_name)
        if panel is None or not panel.status:
            return ProvisionResult(ok=False, error="Panel Not Found")
        product = await self.get_product(product_code)
        adapter = self._adapter_for(panel)
        try:
            result: PanelResult = await adapter.create_user(
                username,
                data_limit=data_limit,
                expire_ts=expire_ts,
                note=f"{user_id} | {tg_username} | {kind}",
                data_limit_reset=product.data_limit_reset if product else "no_reset",
                product={
                    "inbounds": product.inbounds if product else None,
                    "proxies": product.proxies if product else None,
                },
            )
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()
        if not result.ok or result.user is None:
            return ProvisionResult(ok=False, error=result.error or "unknown")
        invoice_id = secrets.token_hex(12)
        sub_url = result.user.subscription_url
        if panel.subvip:
            domain = _domain()
            sub_url = f"https://{domain}/sub/{invoice_id}"
        inv = Invoice(
            id_invoice=invoice_id,
            user_id=user_id or None,
            username=tg_username or username,
            service_location=panel_name,
            product_name=result.user.username,
            volume=str(data_limit),
            service_time=str(expire_ts),
            uuid=username,
            user_info={"tg_username": tg_username, "kind": kind},
            status="enable",
        )
        assert self._session is not None
        self._session.add(inv)
        await self._session.commit()
        return ProvisionResult(ok=True, invoice=inv,
                               links=result.user.links or [],
                               subscription_url=sub_url)

    async def data_user(self, panel_name: str, username: str) -> PanelUser | None:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return None
        adapter = self._adapter_for(panel)
        try:
            r = await adapter.get_user(username)
            return r.user if r.ok else None
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def modify_user(self, panel_name: str, username: str,
                          config: dict) -> bool:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return False
        adapter = self._adapter_for(panel)
        try:
            return (await adapter.modify_user(username, config)).ok
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def remove_user(self, panel_name: str, username: str) -> bool:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return False
        adapter = self._adapter_for(panel)
        try:
            return (await adapter.remove_user(username)).ok
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def revoke_sub(self, panel_name: str, username: str) -> PanelUser | None:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return None
        adapter = self._adapter_for(panel)
        try:
            r = await adapter.revoke_sub(username)
            return r.user if r.ok else None
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def reset_usage(self, panel_name: str, username: str) -> bool:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return False
        adapter = self._adapter_for(panel)
        try:
            return (await adapter.reset_usage(username)).ok
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def change_status(self, panel_name: str, username: str,
                            enabled: bool) -> bool:
        panel = await self.get_panel(panel_name)
        if panel is None:
            return False
        adapter = self._adapter_for(panel)
        try:
            return (await adapter.set_enabled(username, enabled)).ok
        finally:
            if hasattr(adapter, "close"):
                await adapter.close()

    async def extend(self, method: str, panel_name: str, username: str,
                     product_code: str, extra_days: int = 0,
                     extra_gb: int = 0) -> ProvisionResult:
        """Legacy extend(): add time/volume on top of remaining config."""
        current = await self.data_user(panel_name, username)
        if current is None:
            return ProvisionResult(ok=False, error="user not found on panel")
        product = await self.get_product(product_code)
        now_ts = _now()
        base_expire = max(current.expire_at or 0, now_ts)
        new_expire = base_expire + (extra_days or (product.service_days if product else 30)) * 86400
        if method in ("volume", "both"):
            base_vol = current.data_limit or 0
            used = current.used_traffic or 0
            new_limit = base_vol - used + (extra_gb or (product.volume_gb if product else 0)) * (1024 ** 3)
        else:
            new_limit = current.data_limit or 0
        ok = await self.modify_user(panel_name, username, {
            "data_limit": new_limit, "expire": new_expire})
        if not ok:
            return ProvisionResult(ok=False, error="panel modify failed")
        return ProvisionResult(ok=True)

    async def extra_volume(self, panel_name: str, username: str,
                           gb: int) -> bool:
        current = await self.data_user(panel_name, username)
        if current is None:
            return False
        new_limit = (current.data_limit or 0) + gb * (1024 ** 3)
        return await self.modify_user(panel_name, username,
                                      {"data_limit": new_limit})

    async def extra_time(self, panel_name: str, username: str,
                         days: int) -> bool:
        current = await self.data_user(panel_name, username)
        if current is None:
            return False
        base = max(current.expire_at or 0, _now())
        return await self.modify_user(panel_name, username,
                                      {"expire": base + days * 86400})

    async def change_location(self, old_panel: str, new_panel: str,
                              username: str, product_code: str,
                              user_id: str = "") -> ProvisionResult:
        """Legacy changeloc: create on new panel, remove from old."""
        created = await self.create_user(
            new_panel, product_code, username, data_limit=0, expire_ts=_now(),
            user_id=user_id, kind="changeloc")
        if not created.ok:
            return created
        await self.remove_user(old_panel, username)
        return created


# ── module-level helpers ─────────────────────────────────────────
def _now() -> int:
    import time
    return int(time.time())


def _domain() -> str:
    from mirza.config import get_settings
    return get_settings().domain_hosts


def _decrypt_secret(stored: str) -> str:
    """Fernet-encrypted at rest; falls back to legacy plaintext during import."""
    if not stored:
        return ""
    from mirza.config import get_settings
    key_source = get_settings().session_secret.encode()
    try:
        import base64
        import hashlib
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(key_source).digest())
        return Fernet(key).decrypt(stored.encode()).decode()
    except Exception:
        return stored
