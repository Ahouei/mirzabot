"""Stars conversion math + offline fallback (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mirza.payments.stars import stars_for


def test_stars_conversion_matches_legacy_formula():
    # legacy: starAmount = usd * 0.016; stars = toman / starAmount
    for usd_rate in (50_000, 60_000, 74_300):
        toman = 100_000
        expected = int(toman / (usd_rate * 0.016))
        assert stars_for(toman, usd_rate) == expected


def test_stars_minimum_is_one():
    assert stars_for(1, 100_000) >= 1
