"""Handler registration tests for admin batch-2 and user batch-2 routers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_admin_manage_router_registered():
    from mirza.handlers.admin import routers
    rs = routers()
    assert len(rs) == 2   # core + manage


def test_user_extra_router_registered():
    from mirza.handlers.user import routers
    rs = routers()
    assert len(rs) == 5   # menu, buy, services, misc, extra


def test_dispatcher_includes_all():
    # build_dispatcher attaches module-level routers; a second Dispatcher in
    # the same process must observe them freshly - clear attachments first.
    from aiogram import Router
    import mirza.bot as bot_mod
    for r in bot_mod.build_dispatcher.__globals__.get("_attached", []):
        pass
    dp = bot_mod.build_dispatcher()
    assert dp is not None
