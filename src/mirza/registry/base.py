"""Plugin-first registry, keyed (kind, name, revision).

Every swappable subsystem (panel adapters, payment gateways, scheduler jobs,
feature addons) registers here. Core code resolves implementations only through
the registry - adding a backend never touches core code.

Revision semantics: bumping the revision replaces the previous implementation
at import time; the registry keeps the newest and records history.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginKey:
    kind: str          # "panel" | "payment" | "job" | "addon" | ...
    name: str
    revision: int = 1


@dataclass
class PluginEntry:
    key: PluginKey
    factory: Callable[[], Any]
    meta: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class Registry:
    _instance: ClassVar["Registry | None"] = None

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], PluginEntry] = {}
        self._history: dict[tuple[str, str], list[int]] = {}

    @classmethod
    def instance(cls) -> "Registry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── registration ────────────────────────────────────────────
    def register(self, kind: str, name: str, revision: int = 1,
                 meta: dict[str, Any] | None = None) -> Callable[[type], type]:
        def deco(cls_or_fn):
            key = (kind, name)
            existing = self._plugins.get(key)
            if existing and existing.key.revision >= revision:
                log.debug("registry: keeping rev %s of %s/%s (new %s ignored)",
                          existing.key.revision, kind, name, revision)
                return cls_or_fn
            if existing:
                self._history.setdefault(key, []).append(existing.key.revision)
            self._plugins[key] = PluginEntry(
                key=PluginKey(kind=kind, name=name, revision=revision),
                factory=cls_or_fn,
                meta=meta or {},
            )
            return cls_or_fn
        return deco

    # ── resolution ──────────────────────────────────────────────
    def get(self, kind: str, name: str):
        entry = self._plugins.get((kind, name))
        if entry is None or not entry.enabled:
            raise KeyError(f"plugin not found: {kind}/{name}")
        return entry.factory()

    def has(self, kind: str, name: str) -> bool:
        entry = self._plugins.get((kind, name))
        return bool(entry and entry.enabled)

    def list(self, kind: str) -> list[PluginEntry]:
        return [e for (k, _), e in sorted(self._plugins.items()) if k == kind]

    def names(self, kind: str) -> list[str]:
        return [e.key.name for e in self.list(kind)]

    def set_enabled(self, kind: str, name: str, enabled: bool) -> None:
        entry = self._plugins.get((kind, name))
        if entry:
            entry.enabled = enabled


registry = Registry.instance()


def register_plugin(kind: str, name: str | None = None, revision: int = 1,
                    meta: dict[str, Any] | None = None):
    """Decorator sugar: infers the name from the class when omitted."""
    def deco(cls):
        return registry.register(kind, name or cls.__name__.lower(), revision, meta)(cls)
    return deco
