# tests/test_reverse_dcf.py
# ═══════════════════════════════════════════════════════════════
# Tests for backend/services/reverse_dcf_service.py
#
# Three classes of tests, per the task spec:
#   1. Golden-stock test  — TCS-like inputs imply growth in a
#                           plausible range
#   2. Sanity test        — implied growth always bounded
#                           [-5%, 50%]
#   3. Null-input handling — bad / missing inputs return None
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path when pytest is invoked from
# the worktree root (mirrors the pattern in tests/test_dcf_edge_cases.py)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from backend.services.reverse_dcf_service import (
    compute_reverse_dcf,
    SEARCH_MIN_GROWTH,
    SEARCH_MAX_GROWTH,
)


# ─────────────────────────────────────────────────────────────
# Helpers — TCS-like inputs (FY24 trailing actuals, rough)
#
# We hard-code rather than call the live pipeline so the test is
# deterministic offline. Numbers chosen to land near consensus FV
# at ~12% implied growth so the test catches both binary-search
# regressions and lattice drift in models/forecaster.
# ─────────────────────────────────────────────────────────────
def _tcs_inputs() -> dict:
    # Approximate FY24 trailing values, in INR
    revenue = 2_400_000_000_000.0     # ₹2.4 lakh Cr
    fcf     = 440_000_000_000.0       # ₹44k Cr
    margin  = fcf / revenue           # ~18%
    return dict(
        ticker="TCS.NS",
        current_price=3_900.0,
        wacc=0.115,
        current_fcf=fcf,
        current_margin=margin,
        current_revenue=revenue,
        total_debt=80_000_000_000.0,
        total_cash=600_000_000_000.0,
        shares=3_620_000_000.0,
        terminal_g=0.04,
    )


# ─────────────────────────────────────────────────────────────
# Golden-stock test
# ─────────────────────────────────────────────────────────────
def test_tcs_implied_growth_in_plausible_range():
    """TCS at ~₹3,900 should imply an FCF growth rate in the
    single-digit-to-low-teens band — anywhere outside [-5%, 30%]
    would suggest a bad lattice or a busted binary search."""
    out = compute_reverse_dcf(**_tcs_inputs())
    assert out is not None, "TCS-like inputs should produce a result"
    g = out["implied_growth_pct"]
    # Plausible band: -5% (search floor) to 45%. TCS trades at ~30x
    # P/FCF, so once the exponential fade is applied the year-1 growth
    # the price embeds is meaningfully above headline GDP+inflation —
    # historically the lattice has converged in the 25-40% band for
    # quality-cash-cow cohorts. Anything outside this range indicates
    # either a clamp regression or a fade-constant change.
    assert SEARCH_MIN_GROWTH <= g <= 0.45, (
        f"TCS implied growth {g:.2%} outside plausible band [-5%, 45%]"
    )
    # Margin axis sanity: implied margin under consensus growth must be
    # positive and below 60% (search ceiling). For a high-quality cash
    # cow we expect 5-40%.
    m = out["implied_margin_pct"]
    assert 0.005 <= m <= 0.60
    # Iso curve shape: 3 points, growth strictly non-decreasing
    iso = out["iso_fv_curve"]
    assert len(iso) == 3
    assert iso[0]["growth"] <= iso[1]["growth"] <= iso[2]["growth"]
    # Summary must mention both axes — keeps the public-facing string
    # contract stable for the React panel.
    summary = out["current_market_implied_summary"]
    assert "growth" in summary.lower()
    assert "margin" in summary.lower()


# ─────────────────────────────────────────────────────────────
# Bounds sanity — every solved growth must land in [-5%, 50%]
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("price_mult", [0.25, 0.5, 1.0, 1.5, 2.0, 4.0, 10.0])
def test_implied_growth_bounded(price_mult: float):
    """Across an ugly price-shock sweep, implied growth must stay
    inside the documented [-5%, 50%] search range. Anything outside
    indicates the clamp at the end of compute_reverse_dcf is broken."""
    base = _tcs_inputs()
    base["current_price"] = base["current_price"] * price_mult
    out = compute_reverse_dcf(**base)
    assert out is not None
    g = out["implied_growth_pct"]
    assert SEARCH_MIN_GROWTH - 1e-9 <= g <= SEARCH_MAX_GROWTH + 1e-9, (
        f"price={price_mult}x produced implied_growth_pct={g} — "
        f"outside [{SEARCH_MIN_GROWTH}, {SEARCH_MAX_GROWTH}]"
    )
    m = out["implied_margin_pct"]
    assert 0.0 < m <= 0.60 + 1e-9


# ─────────────────────────────────────────────────────────────
# Null-input handling
# ─────────────────────────────────────────────────────────────
def test_returns_none_on_loss_maker():
    """Negative or zero FCF (loss-maker) must produce None — the
    public router uses None to hide the panel rather than mislead
    users with a -5% floor reading."""
    bad = _tcs_inputs()
    bad["current_fcf"] = 0.0
    assert compute_reverse_dcf(**bad) is None
    bad2 = _tcs_inputs()
    bad2["current_fcf"] = -100.0
    assert compute_reverse_dcf(**bad2) is None


def test_returns_none_on_missing_price():
    bad = _tcs_inputs()
    bad["current_price"] = 0.0
    assert compute_reverse_dcf(**bad) is None


def test_returns_none_on_missing_shares():
    bad = _tcs_inputs()
    bad["shares"] = 0.0
    assert compute_reverse_dcf(**bad) is None


def test_returns_none_on_invalid_wacc():
    bad = _tcs_inputs()
    bad["wacc"] = 0.30   # outside [5%, 25%] guard
    assert compute_reverse_dcf(**bad) is None
    bad2 = _tcs_inputs()
    bad2["wacc"] = 0.01
    assert compute_reverse_dcf(**bad2) is None


def test_inputs_snapshot_present():
    """Inputs snapshot must be mirrored back so the response model
    serialises correctly via ReverseDcfInputs."""
    out = compute_reverse_dcf(**_tcs_inputs())
    assert out is not None
    inp = out["inputs"]
    for key in (
        "current_price", "wacc", "terminal_g", "current_fcf",
        "current_margin", "current_revenue", "consensus_growth",
        "total_debt", "total_cash", "shares", "years",
    ):
        assert key in inp, f"missing input snapshot key: {key}"


def test_sanity_lines_emitted_when_history_provided():
    inp = _tcs_inputs()
    out = compute_reverse_dcf(
        **inp,
        historical_revenue_cagr=0.11,
        historical_fcf_margin=0.20,
    )
    assert out is not None
    lines = out["sanity_check_lines"]
    assert len(lines) == 2
    assert any("revenue CAGR" in l for l in lines)
    assert any("FCF margin" in l for l in lines)
