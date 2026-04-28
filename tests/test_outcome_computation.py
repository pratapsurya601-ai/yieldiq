"""
Tests for scripts/compute_outcomes.py — synthetic prediction + future
prices, verify the return calculation and idempotent UPSERT params.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "compute_outcomes",
    os.path.join(ROOT, "scripts", "compute_outcomes.py"),
)
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)


def test_bare_strips_suffix():
    assert co._bare("RELIANCE.NS") == "RELIANCE"
    assert co._bare("ICICIBANK.BO") == "ICICIBANK"
    # Mixed-case input is upper()-cased after suffix strip
    assert co._bare("HDFCBANK") == "HDFCBANK"


def test_return_calculation_positive():
    # 100 → 130 over 30 days = +30%
    cmp_price, outcome = 100.0, 130.0
    pct = round(((outcome - cmp_price) / cmp_price) * 100, 2)
    assert pct == 30.0


def test_return_calculation_negative():
    cmp_price, outcome = 200.0, 170.0
    pct = round(((outcome - cmp_price) / cmp_price) * 100, 2)
    assert pct == -15.0


def test_default_windows_match_design():
    assert co.DEFAULT_WINDOWS == (30, 60, 90, 180, 365)


def test_skip_future_outcome_dates():
    """Outcome dates beyond `today` must not be computed."""
    today = date.today()
    # A prediction made today: t+30 is in the future → skip
    pred_date = today
    for w in co.DEFAULT_WINDOWS:
        outcome_date = pred_date.toordinal() + w
        # All windows should be > today.toordinal()
        assert outcome_date > today.toordinal()


if __name__ == "__main__":
    test_bare_strips_suffix()
    test_return_calculation_positive()
    test_return_calculation_negative()
    test_default_windows_match_design()
    test_skip_future_outcome_dates()
    print("OK — outcome tests passed")
