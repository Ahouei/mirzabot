"""Smoke tests: registry, i18n, models, dispatcher wiring, API app."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_registry_plugins_load():
    import mirza.plugins as p
    from mirza.registry import registry
    p.load_builtin_plugins()
    assert set(registry.names("panel")) >= {
        "marzban", "marzneshin", "alireza_single", "xui_single", "sui",
        "hiddify", "wgdashboard", "mikrotik", "ibsng", "rebecca",
        "pasarguard", "mirza_agent"}
    assert {"zarinpal", "aqayepardakht", "nowpayments", "plisio",
            "iranpay", "iranpay2", "card2card"} <= set(
        registry.names("payment"))
    jobs = registry.names("job")
    assert len(jobs) >= 16


def test_i18n_fallbacks():
    from mirza.i18n import t
    assert t("users.Balance.insufficientBalance", "fa") != \
        "users.Balance.insufficientBalance"
    assert t("nonexistent.key.path", "en") == "nonexistent.key.path"
    assert t("users.mainMenu.text_sell", "de")  # falls back to en


def test_models_metadata_complete():
    from mirza.db import Base
    expected = {
        "user", "admin", "channels", "help", "setting", "marzban_panel",
        "product", "category", "invoice", "Payment_report", "Discount",
        "Giftcodeconsumed", "PaySetting", "DiscountSell", "affiliates",
        "shopSetting", "cancel_service", "service_other", "card_number",
        "Requestagent", "topicid", "manualsell", "wheel_list", "botsaz",
        "app", "logs_api", "reagent_report", "support_message",
        "departman", "balance_ledger"}
    have = set(Base.metadata.tables)
    missing = expected - have
    assert not missing, f"missing tables: {missing}"


def test_dispatcher_builds():
    import mirza.bot as bot_mod
    dp = bot_mod.build_dispatcher()
    assert dp is not None


def test_api_app_routes():
    from mirza.api import make_app
    app = make_app()
    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/api/miniapp" in paths
    assert "/sub/{token}" in paths
    assert "/webhook" in paths
    assert "/wl/{bot_username}" in paths
    assert any(p.startswith("/panel/") for p in paths)


def test_username_generation():
    from mirza.panels.service import PanelService
    u1 = PanelService.generate_username("random", 8)
    u2 = PanelService.generate_username("number", 6)
    assert len(u1) == 8 and len(u2) == 6 and u2.isdigit()


def test_marzban_normalize():
    from mirza.panels.marzban import MarzbanAdapter
    user = MarzbanAdapter._normalize(
        {"username": "u1", "subscription_url": "sub/abc",
         "data_limit": 100, "expire": 123}, "https://p.example")
    assert user.subscription_url == "https://p.example/sub/abc"
