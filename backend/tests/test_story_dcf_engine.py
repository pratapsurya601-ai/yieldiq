"""Tests for backend.services.story_dcf_engine."""
from __future__ import annotations

import pytest

from backend.services.story_dcf_engine import (
    StoryParams,
    INDUSTRY_STORY_DEFAULTS,
    compute_story_dcf_fair_value,
    _revenue_path,
    _margin_path,
    _fcff_path,
    _terminal_value,
    _discount,
)


# ── Pure-function unit tests ─────────────────────────────────


def test_revenue_path_fade():
    """Revenue grows at fading rate from g0 to g_term over n years."""
    revs = _revenue_path(rev0=100, g0=0.30, g_term=0.05, n=5)
    assert len(revs) == 5
    # Year 1 ~ 100 × 1.30 = 130
    assert 125 < revs[0] < 135
    # Year 5 growth rate ~ 0.05 → revs[4] = revs[3] × 1.05
    assert revs[4] / revs[3] - 1 == pytest.approx(0.05, abs=0.02)
    # Monotonically increasing
    assert all(revs[i] < revs[i + 1] for i in range(len(revs) - 1))


def test_margin_path_linear_ramp_then_flat():
    """Margin ramps linearly from 0 → target over conv_yr, flat after."""
    margins = _margin_path(m_target=0.20, conv_yr=5, n=10)
    assert len(margins) == 10
    # Year 1 = 0.20 × 1/5 = 0.04
    assert margins[0] == pytest.approx(0.04, abs=0.001)
    # Year 5 = 0.20 × 5/5 = 0.20
    assert margins[4] == pytest.approx(0.20, abs=0.001)
    # Year 10 still 0.20 (flat after convergence)
    assert margins[9] == pytest.approx(0.20, abs=0.001)


def test_fcff_path_positive_at_target_margin():
    """FCFF should be positive once margin converges and growth slows."""
    revs = _revenue_path(rev0=1000, g0=0.20, g_term=0.05, n=10)
    margins = _margin_path(m_target=0.20, conv_yr=5, n=10)
    fcffs = _fcff_path(revs=revs, margins=margins, reinvest_rate=0.60, tax=0.25)
    assert len(fcffs) == 10
    # Later years should be positive (margin stabilised, growth slowed)
    assert fcffs[-1] > 0
    assert fcffs[-2] > 0


def test_terminal_value_refuses_near_zero_denominator():
    """wacc - g_term < 0.03 → None (model break)."""
    assert _terminal_value(fcff_n=100, g_term=0.05, wacc=0.06) is None
    assert _terminal_value(fcff_n=100, g_term=0.05, wacc=0.10) is not None


def test_terminal_value_refuses_negative_fcff():
    assert _terminal_value(fcff_n=-50, g_term=0.05, wacc=0.13) is None
    assert _terminal_value(fcff_n=0, g_term=0.05, wacc=0.13) is None


def test_discount_pv_decreases_with_wacc():
    cashflows = [100, 110, 120, 130, 140]
    pv_low = _discount(cashflows, tv=1000, wacc=0.10)
    pv_high = _discount(cashflows, tv=1000, wacc=0.15)
    assert pv_low > pv_high


# ── Industry-default sanity ──────────────────────────────────


def test_industry_defaults_all_have_required_fields():
    """Each industry default must produce a valid StoryParams."""
    for key, params in INDUSTRY_STORY_DEFAULTS.items():
        assert isinstance(params, StoryParams)
        assert 0.05 <= params.initial_growth <= 0.50, key
        assert 0.05 <= params.target_op_margin <= 0.50, key
        assert 0.03 <= params.terminal_growth <= 0.07, key
        assert 0.08 <= params.wacc <= 0.20, key
        assert params.wacc - params.terminal_growth >= 0.05, key


# ── Public API ────────────────────────────────────────────


def test_compute_returns_none_for_unsupported_sector():
    """Pharma / Auto / etc. don't get story-DCF — None."""
    result = compute_story_dcf_fair_value(
        ticker="SUNPHARMA.NS",
        sector="Pharma",
        financials={"revenue": 50000e7, "shares": 24e8, "current_price": 1800},
    )
    assert result is None


def test_compute_returns_none_for_missing_inputs():
    """Missing revenue / shares / price → None."""
    result = compute_story_dcf_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials={"current_price": 1000},  # no revenue, no shares
    )
    assert result is None


def test_paytm_shape_produces_finite_fv():
    """PAYTM-shape: ₹10,000 Cr revenue, 60 Cr shares, CMP ₹1000.
    Should produce a finite FV via the ecommerce/payments path."""
    result = compute_story_dcf_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials={
            "revenue": 10_000e7,    # ₹10,000 Cr TTM
            "shares": 60e7,         # 60 Cr shares
            "current_price": 1000.0,
            "net_debt": -8000e7,    # ₹-8,000 Cr (net cash)
        },
    )
    assert result is not None
    assert result["method"] == "story_dcf"
    # FV should be finite + non-zero
    assert result["fair_value"] > 0
    # Should land in a defensible band (200-3000 for PAYTM-shape)
    assert 200 <= result["fair_value"] <= 3000
    # Confidence capped at 50
    assert result["confidence_score"] <= 50
    # Meta block populated
    meta = result["_meta"]
    assert meta["initial_growth"] > 0
    assert meta["target_op_margin"] > 0
    assert meta["wacc"] > 0
    # TV should be a meaningful fraction of EV (story DCF is forward-heavy)
    assert 0.4 < meta["tv_pct_of_ev"] < 0.95


def test_fintech_broker_path_uses_different_industry_key():
    """A NUVAMA-shape ticker with sector 'Fintech' routes to
    fintech_broker industry."""
    result = compute_story_dcf_fair_value(
        ticker="NUVAMA.NS",
        sector="Fintech",
        financials={
            "revenue": 2000e7,
            "shares": 4e7,
            "current_price": 1500.0,
        },
    )
    assert result is not None
    assert result["_meta"]["industry"] == "fintech_broker"


def test_bear_bull_around_base():
    """Bear at -30%, bull at +45% — wider than peer-relative because
    story DCFs are more uncertain."""
    result = compute_story_dcf_fair_value(
        ticker="GROWW.NS",
        sector="Fintech",
        financials={
            "revenue": 3000e7,
            "shares": 5e7,
            "current_price": 200.0,
        },
    )
    assert result is not None
    assert result["bear_case"] < result["base_case"] < result["bull_case"]
    # Bear ≈ base × 0.70, Bull ≈ base × 1.45
    assert result["bear_case"] / result["base_case"] == pytest.approx(0.70, abs=0.02)
    assert result["bull_case"] / result["base_case"] == pytest.approx(1.45, abs=0.02)


def test_override_overlay_changes_params():
    """Explicit story_params should win over industry default.

    Uses a fictitious ticker NOT in the JSON overrides so the
    industry default is the comparison baseline. (Real tickers
    like MEESHO have their own override in config/story_dcf_
    overrides.json so won't roundtrip cleanly.)"""
    base = INDUSTRY_STORY_DEFAULTS["ecommerce"]
    override = StoryParams(
        initial_growth=base.initial_growth + 0.10,
        target_op_margin=base.target_op_margin,
        terminal_growth=base.terminal_growth,
        wacc=base.wacc,
        reinvestment_rate=base.reinvestment_rate,
    )
    fictitious_fin = {
        "revenue": 5000e7, "shares": 4e8, "current_price": 200,
    }
    result_default = compute_story_dcf_fair_value(
        ticker="TESTPLATFORM.NS",
        sector="Internet Platform",
        financials=fictitious_fin,
    )
    result_override = compute_story_dcf_fair_value(
        ticker="TESTPLATFORM.NS",
        sector="Internet Platform",
        financials=fictitious_fin,
        story_params=override,
    )
    assert result_default is not None, (
        "Default params should produce a FV for typical platform inputs"
    )
    assert result_override is not None
    # Higher initial growth → higher FV
    assert result_override["fair_value"] > result_default["fair_value"]
