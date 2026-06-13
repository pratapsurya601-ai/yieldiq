"""FIX-NET-MARGIN-UNIT — yfinance revenue/net_margin unit-integrity gate.

yfinance returns ``Total Revenue`` mis-scaled (typically ~1000x too
small) for a cohort of Indian micro-caps while ``Net Income`` arrives at
the correct magnitude — e.g. ESSARSHPNG FY2025 revenue=102.6M but
net_income=6.6B from the SAME income statement. ``_to_cr`` divides both
by 1e7 faithfully, so the inconsistency propagates and net_margin
(pat/revenue) explodes past ±100% (ESSARSHPNG 440,053%, SHYAMTEL
-56,884%, JINDALPHOT 45,645%).

The fix is a write-time plausibility gate in
``data_pipeline/sources/yfinance_supplement.py`` mirroring the
``compute_asset_turnover`` sanity gate (FIX-AUDIT5-P1-ASSET-TURNOVER):
when pat/revenue is implausible the revenue figure is the untrustworthy
one, so revenue + net_margin are dropped to None and the corrupt value
never reaches ratio_history / a fair value.
"""
from __future__ import annotations

import pytest

from data_pipeline.sources.yfinance_supplement import (
    NET_MARGIN_PLAUSIBLE_PCT,
    _net_margin_unit_ok,
)


# ───────────────────────── happy path ──────────────────────────────


@pytest.mark.parametrize("pat,revenue", [
    # Raw-rupee pairs from a consistent income statement (pre _to_cr):
    (1_500_000_000, 10_000_000_000),   # 15% net margin
    (-500_000_000, 10_000_000_000),    # -5% (loss-making but plausible)
    (9_000_000_000, 10_000_000_000),   # 90% (high but a real holding co)
    (1, 1),                            # 100% exactly — at the edge, allowed
])
def test_plausible_pairs_pass(pat, revenue):
    assert _net_margin_unit_ok(pat, revenue) is True


def test_missing_inputs_are_not_gated():
    """Nothing to check → gate must not fire (returns True)."""
    assert _net_margin_unit_ok(None, 100) is True
    assert _net_margin_unit_ok(100, None) is True
    assert _net_margin_unit_ok(100, 0) is True
    assert _net_margin_unit_ok(100, -5) is True
    assert _net_margin_unit_ok(None, None) is True


# ───────────────────── unit-mismatch guard ─────────────────────────


def test_essarshpng_prod_repro_trips_gate():
    """ESSARSHPNG FY2025 raw shape: revenue=102.6M, net_income=6.6008B
    from the SAME statement → implied net_margin ~6,433% — must trip."""
    assert _net_margin_unit_ok(6_600_800_000, 102_600_000) is False


def test_revenue_1000x_too_small_trips_gate():
    """The dominant signature: revenue ~1000x too small vs a correctly
    scaled pat. 660 Cr pat / 0.15 Cr revenue ≈ 440,053% net margin."""
    # In raw rupees: pat=6.6008e9, revenue=1.5e6 → 440,053%
    assert _net_margin_unit_ok(6_600_800_000, 1_500_000) is False


def test_negative_blowup_trips_gate():
    """SHYAMTEL -56,884% shape: large-magnitude negative margin trips."""
    assert _net_margin_unit_ok(-3_640_600, 6_400) is False


@pytest.mark.parametrize("pct_over", [1.01, 2.0, 100.0, 1000.0])
def test_just_outside_band_trips(pct_over):
    """Any |net_margin| beyond the plausible band trips, scale-free."""
    revenue = 1_000_000.0
    pat = revenue * (NET_MARGIN_PLAUSIBLE_PCT / 100.0) * pct_over
    assert _net_margin_unit_ok(pat, revenue) is False


def test_just_inside_band_passes():
    revenue = 1_000_000.0
    pat = revenue * (NET_MARGIN_PLAUSIBLE_PCT / 100.0) * 0.99
    assert _net_margin_unit_ok(pat, revenue) is True
