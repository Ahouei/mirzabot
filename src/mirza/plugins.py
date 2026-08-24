"""Import all builtin plugins so registration side-effects run."""
from __future__ import annotations

IMPORTS = [
    "mirza.panels.marzban",
    "mirza.panels.marzneshin",
    "mirza.panels.alireza_single",
    "mirza.panels.xui_single",
    "mirza.panels.sui",
    "mirza.panels.hiddify",
    "mirza.panels.wgdashboard",
    "mirza.panels.mikrotik",
    "mirza.panels.ibsng",
    "mirza.panels.rebecca",
    "mirza.panels.pasarguard",
    "mirza.panels.mirza_agent",
    "mirza.payments.zarinpal",
    "mirza.payments.aqayepardakht",
    "mirza.payments.nowpayments",
    "mirza.payments.plisio",
    "mirza.payments.iranpay",
    "mirza.payments.card2card",
    "mirza.jobs.builtin",
]


def load_builtin_plugins() -> None:
    import importlib

    for mod in IMPORTS:
        try:
            importlib.import_module(mod)
        except Exception:  # pragma: no cover - addon optional deps
            import logging
            logging.getLogger(__name__).exception("failed loading plugin module %s", mod)
