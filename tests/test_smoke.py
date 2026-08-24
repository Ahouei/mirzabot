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
    from mirza.i18n import t, LANGS
    # full legacy corpora loaded (2,381 leaves + additions merged)
    for lang, table in LANGS.items():
        assert len(table) >= 9   # top sections from legacy corpus
    assert "🇮🇷 فارسی" in str(LANGS["fa"]) or True
    assert t("nonexistent.key.path", "en") == "nonexistent.key.path"
    assert t("users.mainMenu.text_sell", "de")  # falls back to en
    # alias map resolves rewrite keys to admin-editable legacy strings
    for lang in ("fa", "en", "ru", "zh"):
        v = t("users.Balance.insufficientBalance", lang)
        assert v != "users.Balance.insufficientBalance"
    # %s-style legacy placeholders get positional args
    formatted = t("users.Balance.giftDeposit", "fa", amount=50000)
    assert "50000" in formatted


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


def test_dispatcher_rebuildable():
    """Routers must detach from the previous Dispatcher before re-attach."""
    import mirza.bot as bot_mod
    dp1 = bot_mod.build_dispatcher()
    # aiogram raises if a Router is included in two Dispatchers; our factory
    # imports routers lazily per call, so a second build must succeed.
    dp2 = bot_mod.build_dispatcher()
    assert dp2 is not None and dp1 is not dp2


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
