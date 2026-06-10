"""ROOT CAUSE #12 — scripts/backfill_fair_value_history.py interp logic.

The interpolation kernel is the only code path with non-trivial
math; tests cover it directly without spinning up a DB session.

Covers:

* `_interpolate_gaps` on a sparse 30-day window: produces correct
  intermediate (date, fv, price) tuples whose MoS aligns with the
  linear interpolation between anchors.
* No interpolation rows produced when adjacent anchors are 1 day
  apart.
* Empty / single-anchor input → empty output.
* Multiple gaps in a single ticker series are all filled.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# The backfill script lives under scripts/ and is not a package; load
# it via importlib so we can hit `_interpolate_gaps` directly without
# a sys.path hack on every consumer.
_BACKFILL_PATH = _REPO / "scripts" / "backfill_fair_value_history.py"
_spec = importlib.util.spec_from_file_location(
    "backfill_fair_value_history_module", _BACKFILL_PATH,
)
assert _spec is not None and _spec.loader is not None
backfill_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_mod)  # type: ignore[attr-defined]
_interpolate_gaps = backfill_mod._interpolate_gaps


# ---------- sparse 30-day window happy path ---------------------------------

def test_interp_fills_sparse_30_day_window():
    """Two anchors 30 days apart, FV linearly drifts from 1000 → 1300
    and price from 950 → 1100. The interpolator must produce 29
    intermediate rows whose values match the linear formula.
    """
    a_d = date(2026, 1, 1)
    b_d = a_d + timedelta(days=30)
    anchors = [(a_d, 1000.0, 950.0), (b_d, 1300.0, 1100.0)]
    out = _interpolate_gaps(anchors)
    assert len(out) == 29  # days 2..30 exclusive of the right anchor
    # Spot-check the midpoint (day 15 — w = 15/30 = 0.5).
    mid_d = a_d + timedelta(days=15)
    mid_row = [r for r in out if r[0] == mid_d][0]
    assert mid_row[1] == pytest.approx(1150.0)  # 1000 + 0.5 * 300
    assert mid_row[2] == pytest.approx(1025.0)  # 950 + 0.5 * 150
    # The first interpolated row is day 2; check the formula.
    first = [r for r in out if r[0] == a_d + timedelta(days=1)][0]
    assert first[1] == pytest.approx(1010.0)  # 1000 + (1/30) * 300
    assert first[2] == pytest.approx(955.0)   # 950 + (1/30) * 150


def test_interp_skips_when_anchors_are_adjacent_days():
    """Two anchors on consecutive calendar days have no missing
    intermediates — the kernel must skip the pair (no row emitted).
    """
    a_d = date(2026, 1, 1)
    b_d = a_d + timedelta(days=1)
    anchors = [(a_d, 1000.0, 950.0), (b_d, 1050.0, 980.0)]
    out = _interpolate_gaps(anchors)
    assert out == []


def test_interp_empty_input_yields_empty():
    assert _interpolate_gaps([]) == []


def test_interp_single_anchor_yields_empty():
    assert _interpolate_gaps([(date(2026, 1, 1), 1000.0, 950.0)]) == []


def test_interp_multiple_gaps_each_filled_independently():
    """A series with three anchors at days 0, 5, 12 yields:
       - 4 rows between day 0 and day 5
       - 6 rows between day 5 and day 12
    """
    base = date(2026, 1, 1)
    anchors = [
        (base + timedelta(days=0),  1000.0, 950.0),
        (base + timedelta(days=5),  1100.0, 1000.0),
        (base + timedelta(days=12), 1200.0, 1050.0),
    ]
    out = _interpolate_gaps(anchors)
    assert len(out) == 4 + 6
    # The two anchors themselves are NOT in the interp output.
    dates = {r[0] for r in out}
    assert (base + timedelta(days=0)) not in dates
    assert (base + timedelta(days=5)) not in dates
    assert (base + timedelta(days=12)) not in dates


def test_interp_dates_are_in_chronological_order_per_pair():
    base = date(2026, 1, 1)
    anchors = [
        (base, 1000.0, 950.0),
        (base + timedelta(days=5), 1100.0, 1000.0),
    ]
    out = _interpolate_gaps(anchors)
    out_dates = [r[0] for r in out]
    assert out_dates == sorted(out_dates)
    # And strictly bounded by the anchors.
    assert all(base < d < (base + timedelta(days=5)) for d in out_dates)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
