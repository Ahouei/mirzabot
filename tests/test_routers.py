"""Handler registration tests for admin batch-2 and user batch-2 routers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_admin_manage_router_registered():
    from mirza.handlers.admin import routers
    rs = routers()
    assert len(rs) == 3   # core + manage + paycheck


def test_user_extra_router_registered():
    from mirza.handlers.user import routers
    rs = routers()
    assert len(rs) == 5   # menu, buy, services, misc, extra


def test_dispatcher_rebuildable():
    """Routers must detach from the previous Dispatcher before re-attach."""
    import mirza.bot as bot_mod
    dp1 = bot_mod.build_dispatcher()
    dp2 = bot_mod.build_dispatcher()
    assert dp2 is not None and dp1 is not dp2
