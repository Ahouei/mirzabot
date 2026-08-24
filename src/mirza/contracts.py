"""Shared typed contracts every plugin kind must satisfy.

Contracts are structural (runtime_checkable) so plugins stay decoupled from
core imports and can be authored in addon packages too.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable


# ─────────────────────────────────────────────────────────────
# Panel adapter contract
# ─────────────────────────────────────────────────────────────
@dataclass
class PanelUser:
    """Normalized view of a user/config on any backend panel."""
    username: str
    subscription_url: str | None = None
    links: list[str] = field(default_factory=list)
    data_limit: int | None = None            # bytes
    expire_at: int | None = None             # unix ts
    used_traffic: int | None = None
    status: str = "active"                   # active|expired|limited|disabled
    online: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PanelResult:
    ok: bool
    user: PanelUser | None = None
    error: str | None = None
    raw: Any = None


class PanelAdapter(ABC):
    """One implementation per backend. Registered under kind='panel'.

    All methods are async. Credentials come from MarzbanPanel row; adapters
    never query the DB themselves - core passes a credentials mapping.
    """

    kind: ClassVar[str] = "panel"
    name: ClassVar[str] = "base"

    def __init__(self, creds: dict[str, Any]):
        self.creds = creds

    async def close(self) -> None:  # optional cleanup; adapters may override
        return None

    @abstractmethod
    async def create_user(self, username: str, *, data_limit: int,
                          expire_ts: int, note: str = "",
                          data_limit_reset: str = "no_reset",
                          product: dict[str, Any] | None = None) -> PanelResult: ...

    @abstractmethod
    async def get_user(self, username: str) -> PanelResult: ...

    @abstractmethod
    async def modify_user(self, username: str, config: dict[str, Any]) -> PanelResult: ...

    @abstractmethod
    async def remove_user(self, username: str) -> PanelResult: ...

    @abstractmethod
    async def revoke_sub(self, username: str) -> PanelResult: ...

    @abstractmethod
    async def reset_usage(self, username: str) -> PanelResult: ...

    @abstractmethod
    async def set_enabled(self, username: str, enabled: bool) -> PanelResult: ...

    @abstractmethod
    async def system_stats(self) -> dict[str, Any]: ...


# ─────────────────────────────────────────────────────────────
# Payment gateway contract
# ─────────────────────────────────────────────────────────────
@dataclass
class GatewayInit:
    redirect_url: str | None = None          # http(s) redirect gateways
    pay_text: str | None = None              # manual/crypto instructions
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(ABC):
    """Registered under kind='payment'. name must match marzban_panel-independent
    PaySetting keys convention: <gateway>_merchant etc."""

    kind: ClassVar[str] = "payment"
    name: ClassVar[str] = "base"

    def __init__(self, settings_kv: dict[str, str], callback_base: str):
        self.kv = settings_kv
        self.callback_base = callback_base

    @abstractmethod
    async def create_payment(self, order_id: str, amount: int,
                             description: str) -> GatewayInit: ...

    @abstractmethod
    async def verify_payment(self, request_body: bytes,
                             query: dict[str, str]) -> tuple[bool, str]:
        """Return (paid, order_id). Must be idempotent - caller claims the row."""


class CryptoPollingGateway(PaymentGateway):
    """Gateways without webhooks (plisio-style): scheduler polls verify()."""


# ─────────────────────────────────────────────────────────────
# Scheduler job contract
# ─────────────────────────────────────────────────────────────
class Job(ABC):
    """Registered under kind='job' with meta {'cron': '*/5 * * * *'}."""

    kind: ClassVar[str] = "job"
    name: ClassVar[str] = "base"

    @abstractmethod
    async def run(self, ctx: "JobContext") -> None: ...  # noqa: UP037


@runtime_checkable
class JobContext(Protocol):
    session_factory: Any
    bot: Any
    send_report: Any  # async callable(kind: str, text: str)
