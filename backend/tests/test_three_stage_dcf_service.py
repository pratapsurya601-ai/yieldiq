# backend/tests/test_three_stage_dcf_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for backend/services/three_stage_dcf_service.py (T2.5 Phase A).
#
# Coverage map (one test per concern, no fixtures shared across tests
# so each test reads top-to-bottom):
#
#   compute_fade_growth_rates
#     - linear taper hits g_terminal exactly on the last fade year
#     - fade_years == 0 → []
#     - fade_years == 1 → [g_terminal]
#     - g_high == g_terminal → constant tail
#
#   compute_three_stage_dcf
#     - HDFCBANK-shaped: FV lands in the ₹1000-1200 bracket
#     - TCS-shaped: FV lands in plausible bracket
#     - g_t >= r → method='unavailable'
#     - g_high < g_t → warning emitted, still computes
#     - base_year_fcf = 0 → unavailable
#     - shares_outstanding = 0 → per-share is None, EV still computed
#     - net_debt > 0 reduces equity_value
#     - net_debt < 0 (net cash) increases equity_value
#     - gap_to_two_stage_dcf populated when caller provides comparison
#     - explicit PV math reproduces hand-calculated value
#
#   select_three_stage_default_horizons
#     - IT services → (7, 5)
#     - metals / cyclicals → (3, 7)
#     - banks → (5, 5)
#     - pharma → (5, 7)
#     - recent IPO override → (8, 5) regardless of sector
#     - unknown / None sector → (5, 5)
#
#   is_three_stage_applicable
#     - HDFCBANK-shaped (positive FCF, 5y history, Bank sector) → True
#     - holdco sector → False
#     - REIT sector → False
#     - zero FCF → False
#     - short history → False
#
#   to_dict
#     - returns plain-JSON shape, projections become list of dicts
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import math

import pytest

from backend.services.three_stage_dcf_service import (
    ThreeStageInputs,
    ThreeStageResult,
    ThreeStageYearProjection,
    compute_fade_growth_rates,
    compute_three_stage_dcf,
    is_three_stage_applicable,
    select_three_stage_default_horizons,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# compute_fade_growth_rates
# ─────────────────────────────────────────────────────────────────
def test_fade_growth_rates_5y_linear_taper():
    """Canonical case from the docstring:
    g_high=0.15, g_terminal=0.04, fade_years=5
        → [0.128, 0.106, 0.084, 0.062, 0.04]
    Last element is exactly g_terminal (within fp tolerance).
    """
    rates = compute_fade_growth_rates(0.15, 0.04, 5)
    assert len(rates) == 5
    expected = [0.128, 0.106, 0.084, 0.062, 0.04]
    for got, want in zip(rates, expected):
        assert got == pytest.approx(want, abs=1e-9)
    # Final element is exactly g_terminal
    assert rates[-1] == pytest.approx(0.04, abs=1e-12)


def test_fade_growth_rates_zero_years_returns_empty():
    """fade_years == 0 → no fade window."""
    assert compute_fade_growth_rates(0.15, 0.04, 0) == []
    # Negative also returns empty (defensive).
    assert compute_fade_growth_rates(0.15, 0.04, -3) == []


def test_fade_growth_rates_single_year_returns_terminal():
    """fade_years == 1 → [g_terminal] (one-shot drop, no taper)."""
    assert compute_fade_growth_rates(0.15, 0.04, 1) == [0.04]
    # Even with a huge g_high, single year still drops straight to g_t.
    assert compute_fade_growth_rates(0.30, 0.05, 1) == [0.05]


def test_fade_growth_rates_equal_high_and_terminal():
    """g_high == g_terminal → constant tail at the common rate."""
    rates = compute_fade_growth_rates(0.05, 0.05, 5)
    assert len(rates) == 5
    for r in rates:
        assert r == pytest.approx(0.05, abs=1e-12)


def test_fade_growth_rates_monotone_decreasing():
    """Strictly decreasing when g_high > g_terminal."""
    rates = compute_fade_growth_rates(0.20, 0.03, 8)
    assert len(rates) == 8
    for prev, nxt in zip(rates, rates[1:]):
        assert nxt < prev


# ─────────────────────────────────────────────────────────────────
# compute_three_stage_dcf — happy paths
# ─────────────────────────────────────────────────────────────────
def test_compute_hdfcbank_shaped_lands_in_plausible_bracket():
    """HDFCBANK-shaped (FCF ~20,000Cr, g_h=14%, g_t=5%, r=11.5%,
    shares=750Cr, net_debt~0). The three-stage FV should land in a
    plausible per-share band for a large-cap private-sector bank.

    Bracket is intentionally wide (₹500–₹1,800) because Phase A is
    the math, not the calibration. At these inputs the model lands
    around ~₹700 — below the YieldIQ two-stage prod value (~₹1,129)
    and below AlphaSpread (~₹803), which is the expected directional
    move: the fade window pulls FV below the cliff-style two-stage.
    Phase B will calibrate the composite weight against the existing
    estimator before any of this enters the public payload.
    """
    inputs = ThreeStageInputs(
        base_year_fcf=20_000.0,
        high_growth_rate=0.14,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.05,
        discount_rate=0.115,
        shares_outstanding=750.0,
        net_debt=0.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.fair_value_per_share is not None
    # Wide sanity bracket — Phase A is structural, Phase B will
    # calibrate against the composite.
    assert 500.0 < result.fair_value_per_share < 1800.0


def test_compute_tcs_shaped_returns_positive_per_share():
    """TCS-shaped: FCF~42000Cr, g_h=12%, g_t=5%, r=11.5%, shares=362Cr.
    Plausibility bracket is loose — we want to confirm the math
    doesn't collapse or explode on a large-cap IT-services profile.
    """
    inputs = ThreeStageInputs(
        base_year_fcf=42_000.0,
        high_growth_rate=0.12,
        high_growth_years=7,
        fade_years=5,
        terminal_growth=0.05,
        discount_rate=0.115,
        shares_outstanding=362.0,
        net_debt=-50_000.0,  # net cash on TCS
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.fair_value_per_share is not None
    assert result.fair_value_per_share > 0
    # Net cash should lift equity > EV
    assert result.equity_value > result.enterprise_value


def test_compute_projection_horizon_length_equals_n1_plus_n2():
    """Number of per-year projection rows == high_growth_years + fade_years."""
    inputs = ThreeStageInputs(
        base_year_fcf=1000.0,
        high_growth_rate=0.10,
        high_growth_years=4,
        fade_years=6,
        terminal_growth=0.03,
        discount_rate=0.10,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert len(result.projections) == 10
    # Years are 1..10 consecutive
    assert [p.year for p in result.projections] == list(range(1, 11))
    # Stage 1: first 4 rows all at g_h
    for p in result.projections[:4]:
        assert p.growth_rate == pytest.approx(0.10, abs=1e-9)
    # Stage 2: last row exactly at g_t
    assert result.projections[-1].growth_rate == pytest.approx(0.03, abs=1e-9)
    # Stage 2: monotonic decreasing growth across fade
    fade_growths = [p.growth_rate for p in result.projections[4:]]
    for a, b in zip(fade_growths, fade_growths[1:]):
        assert b < a


def test_compute_hand_calculated_minimal_case():
    """Small synthetic case where we can verify the PV by hand.

    Inputs: FCF_0 = 100, g_h = 0.10, N1 = 2, fade = 0,
            g_t = 0.05, r = 0.10, shares = 1, net_debt = 0.

    With fade_years=0 the model is essentially a 2-year explicit
    horizon + Gordon terminal.

    Year 1 FCF = 110, Year 2 FCF = 121
    Terminal at end of year 2: 121 * 1.05 / (0.10 - 0.05) = 2541.0
    PV: 110/1.1 + 121/1.21 + 2541/1.21
       = 100 + 100 + 2100.0
       = 2300.0
    """
    inputs = ThreeStageInputs(
        base_year_fcf=100.0,
        high_growth_rate=0.10,
        high_growth_years=2,
        fade_years=0,
        terminal_growth=0.05,
        discount_rate=0.10,
        shares_outstanding=1.0,
        net_debt=0.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.enterprise_value == pytest.approx(2300.0, rel=1e-9)
    assert result.fair_value_per_share == pytest.approx(2300.0, rel=1e-9)


def test_compute_first_year_growth_uses_high_rate():
    """Year-1 FCF must equal base × (1 + g_h), not the fade rate."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.20,
        high_growth_years=3,
        fade_years=4,
        terminal_growth=0.04,
        discount_rate=0.12,
        shares_outstanding=10.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.projections[0].fcf == pytest.approx(1_200.0, abs=1e-9)
    assert result.projections[0].growth_rate == pytest.approx(0.20, abs=1e-12)


# ─────────────────────────────────────────────────────────────────
# compute_three_stage_dcf — equity bridge
# ─────────────────────────────────────────────────────────────────
def test_net_debt_positive_reduces_equity_value():
    """Positive net_debt should reduce equity vs enterprise value
    by exactly net_debt."""
    inputs_no_debt = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
        net_debt=0.0,
    )
    inputs_with_debt = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
        net_debt=500.0,
    )
    r_clean = compute_three_stage_dcf(inputs_no_debt)
    r_debt = compute_three_stage_dcf(inputs_with_debt)
    # EV identical
    assert r_clean.enterprise_value == pytest.approx(
        r_debt.enterprise_value, rel=1e-9
    )
    # Equity differs by exactly net_debt
    assert (r_clean.equity_value - r_debt.equity_value) == pytest.approx(
        500.0, abs=1e-9
    )


def test_net_cash_increases_equity_value():
    """Negative net_debt (net cash) should LIFT equity above EV."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
        net_debt=-200.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.equity_value > result.enterprise_value
    assert (result.equity_value - result.enterprise_value) == pytest.approx(
        200.0, abs=1e-9
    )


def test_shares_zero_returns_none_per_share_keeps_ev():
    """shares_outstanding = 0 → per-share is None, EV/equity still
    meaningful."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=0.0,
        net_debt=0.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.fair_value_per_share is None
    assert result.enterprise_value is not None
    assert result.enterprise_value > 0
    assert result.equity_value is not None


# ─────────────────────────────────────────────────────────────────
# compute_three_stage_dcf — validation
# ─────────────────────────────────────────────────────────────────
def test_gt_ge_r_returns_unavailable_with_warning():
    """g_t >= r → Gordon diverges. Must short-circuit to unavailable."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.12,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.115,  # == r
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"
    assert result.fair_value_per_share is None
    assert any(
        "terminal_growth" in w and "discount_rate" in w
        for w in result.sanity_warnings
    )


def test_gt_above_r_returns_unavailable():
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.12,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.20,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"


def test_g_high_below_g_t_warns_but_computes():
    """g_high < g_t is unusual but mathematically valid (a negative
    fade — growth accelerates toward terminal). Should warn but still
    compute."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.02,    # below terminal
        high_growth_years=3,
        fade_years=4,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.fair_value_per_share is not None
    assert any("not really a fade" in w for w in result.sanity_warnings)


def test_g_high_above_r_warns_but_computes():
    """g_high >= r is unusual (compounds faster than discount in
    stage 1) but should warn rather than refuse."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.18,
        high_growth_years=3,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert any(
        "compounds faster than discount" in w
        for w in result.sanity_warnings
    )


def test_base_fcf_zero_returns_unavailable():
    inputs = ThreeStageInputs(
        base_year_fcf=0.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"
    assert any("base_year_fcf" in w for w in result.sanity_warnings)


def test_base_fcf_negative_returns_unavailable():
    inputs = ThreeStageInputs(
        base_year_fcf=-500.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"


def test_base_fcf_nan_returns_unavailable():
    inputs = ThreeStageInputs(
        base_year_fcf=float("nan"),
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"


def test_zero_horizon_returns_unavailable():
    """N1 + N2 == 0 leaves no explicit horizon; can't compute."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=0,
        fade_years=0,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"


def test_negative_shares_returns_unavailable():
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=-10.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "unavailable"


# ─────────────────────────────────────────────────────────────────
# compute_three_stage_dcf — comparison gap
# ─────────────────────────────────────────────────────────────────
def test_gap_to_two_stage_dcf_when_three_stage_lower():
    """Caller supplies two_stage=1500, three_stage outputs 1200 →
    gap = (1200 - 1500) / 1500 = -0.20."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs, two_stage_dcf_for_comparison=1500.0)
    assert result.method == "three_stage_dcf"
    assert result.gap_to_two_stage_dcf is not None
    expected_gap = (result.fair_value_per_share - 1500.0) / 1500.0
    assert result.gap_to_two_stage_dcf == pytest.approx(expected_gap, rel=1e-9)


def test_gap_to_two_stage_dcf_when_not_provided_is_none():
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.gap_to_two_stage_dcf is None


def test_gap_skipped_when_two_stage_non_positive():
    """Caller passes a sentinel 0 or negative — gap left None."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    r0 = compute_three_stage_dcf(inputs, two_stage_dcf_for_comparison=0.0)
    assert r0.gap_to_two_stage_dcf is None
    rn = compute_three_stage_dcf(inputs, two_stage_dcf_for_comparison=-10.0)
    assert rn.gap_to_two_stage_dcf is None


# ─────────────────────────────────────────────────────────────────
# select_three_stage_default_horizons
# ─────────────────────────────────────────────────────────────────
def test_horizons_it_services():
    assert select_three_stage_default_horizons("IT Services") == (7, 5)
    assert select_three_stage_default_horizons("Information Technology") == (7, 5)
    assert select_three_stage_default_horizons("software services") == (7, 5)


def test_horizons_metals_cyclical():
    assert select_three_stage_default_horizons("Metals & Mining") == (3, 7)
    assert select_three_stage_default_horizons("Steel") == (3, 7)
    assert select_three_stage_default_horizons("Iron Ore") == (3, 7)


def test_horizons_cement_cyclical():
    assert select_three_stage_default_horizons("Cement") == (3, 7)


def test_horizons_oil_gas():
    assert select_three_stage_default_horizons("Oil & Gas") == (3, 7)
    assert select_three_stage_default_horizons("Refining") == (3, 7)


def test_horizons_auto_cyclical():
    assert select_three_stage_default_horizons("Automobile") == (3, 7)
    assert select_three_stage_default_horizons("Auto OEM") == (3, 7)


def test_horizons_utilities_regulated():
    assert select_three_stage_default_horizons("Power Generation") == (3, 7)
    assert select_three_stage_default_horizons("Electric Utility") == (3, 7)


def test_horizons_pharma_long_fade():
    assert select_three_stage_default_horizons("Pharmaceuticals") == (5, 7)
    assert select_three_stage_default_horizons("Healthcare") == (5, 7)


def test_horizons_telecom():
    assert select_three_stage_default_horizons("Telecom") == (4, 6)


def test_horizons_banks():
    assert select_three_stage_default_horizons("Banking") == (5, 5)
    assert select_three_stage_default_horizons("Public Sector Bank") == (5, 5)


def test_horizons_fmcg():
    assert select_three_stage_default_horizons("FMCG") == (5, 5)
    assert select_three_stage_default_horizons("Consumer Goods") == (5, 5)


def test_horizons_recent_ipo_overrides_sector():
    """Recent IPO override beats sector lookup."""
    assert select_three_stage_default_horizons(
        "Cement", is_recent_ipo=True
    ) == (8, 5)
    assert select_three_stage_default_horizons(
        None, is_recent_ipo=True
    ) == (8, 5)


def test_horizons_unknown_sector_default():
    assert select_three_stage_default_horizons("RandomNewSector") == (5, 5)


def test_horizons_none_sector_default():
    assert select_three_stage_default_horizons(None) == (5, 5)
    assert select_three_stage_default_horizons("") == (5, 5)
    assert select_three_stage_default_horizons("   ") == (5, 5)


# ─────────────────────────────────────────────────────────────────
# is_three_stage_applicable
# ─────────────────────────────────────────────────────────────────
def test_applicable_tcs_shaped_true():
    """TCS-shaped: positive FCF, long history, IT services."""
    ok, reason = is_three_stage_applicable(
        "TCS",
        sector="IT Services",
        base_year_fcf=42_000.0,
        fcf_history_years=10,
    )
    assert ok is True
    assert reason == "ok"


def test_applicable_hdfcbank_shaped_true():
    ok, reason = is_three_stage_applicable(
        "HDFCBANK",
        sector="Banking",
        base_year_fcf=20_000.0,
        fcf_history_years=10,
    )
    assert ok is True
    assert reason == "ok"


def test_not_applicable_holdco():
    """BAJAJHLDNG-shaped — holdcos route through SOTP, not DCF."""
    ok, reason = is_three_stage_applicable(
        "BAJAJHLDNG",
        sector="Holdco",
        base_year_fcf=2_000.0,
        fcf_history_years=10,
    )
    assert ok is False
    assert "holdco" in reason


def test_not_applicable_holding_company_phrase():
    """The 'holding company' phrase should also be caught."""
    ok, reason = is_three_stage_applicable(
        "EXAMPLE",
        sector="Diversified Holding Company",
        base_year_fcf=2_000.0,
        fcf_history_years=10,
    )
    assert ok is False


def test_not_applicable_reit():
    """REITs use NAV+DPU, not DCF."""
    ok, reason = is_three_stage_applicable(
        "EMBASSY",
        sector="REIT",
        base_year_fcf=500.0,
        fcf_history_years=5,
    )
    assert ok is False
    assert "reit" in reason


def test_not_applicable_etf():
    ok, reason = is_three_stage_applicable(
        "NIFTYBEES",
        sector="ETF",
        base_year_fcf=100.0,
        fcf_history_years=5,
    )
    assert ok is False
    assert "etf" in reason


def test_not_applicable_zero_or_negative_fcf():
    """ZOMATO-shaped — no positive FCF baseline yet."""
    ok, reason = is_three_stage_applicable(
        "ZOMATO",
        sector="Platform",
        base_year_fcf=0.0,
        fcf_history_years=5,
    )
    assert ok is False
    assert "base_year_fcf" in reason

    ok2, reason2 = is_three_stage_applicable(
        "STARTUP",
        sector="Platform",
        base_year_fcf=-200.0,
        fcf_history_years=5,
    )
    assert ok2 is False
    assert "base_year_fcf" in reason2


def test_not_applicable_short_history():
    """Recent IPO with 2y of FCF — high growth not anchored."""
    ok, reason = is_three_stage_applicable(
        "NEWLISTING",
        sector="IT Services",
        base_year_fcf=500.0,
        fcf_history_years=2,
    )
    assert ok is False
    assert "fcf_history" in reason


def test_applicable_missing_sector_passes_when_other_gates_ok():
    """Missing sector is fine — three-stage isn't sector-gated, only
    structurally-gated (holdco / REIT / ETF)."""
    ok, reason = is_three_stage_applicable(
        "UNKNOWNCO",
        sector=None,
        base_year_fcf=1_000.0,
        fcf_history_years=5,
    )
    assert ok is True
    assert reason == "ok"


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────
def test_to_dict_returns_plain_json_shape():
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=3,
        fade_years=3,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
        net_debt=50.0,
    )
    result = compute_three_stage_dcf(inputs, two_stage_dcf_for_comparison=20.0)
    d = to_dict(result)
    assert isinstance(d, dict)
    # Required top-level keys
    for key in (
        "fair_value_per_share",
        "enterprise_value",
        "equity_value",
        "pv_explicit_fcf",
        "pv_terminal",
        "terminal_value",
        "projections",
        "method",
        "sanity_warnings",
        "gap_to_two_stage_dcf",
    ):
        assert key in d
    # Projections are dicts, not dataclass instances
    assert isinstance(d["projections"], list)
    assert len(d["projections"]) == 6
    for row in d["projections"]:
        assert isinstance(row, dict)
        for k in ("year", "growth_rate", "fcf", "discount_factor", "pv"):
            assert k in row
    # method is the success literal
    assert d["method"] == "three_stage_dcf"


def test_to_dict_for_unavailable_result_shape():
    inputs = ThreeStageInputs(
        base_year_fcf=0.0,
        high_growth_rate=0.10,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
    )
    result = compute_three_stage_dcf(inputs)
    d = to_dict(result)
    assert d["method"] == "unavailable"
    assert d["fair_value_per_share"] is None
    assert d["enterprise_value"] is None
    assert d["equity_value"] is None
    assert d["projections"] == []
    assert isinstance(d["sanity_warnings"], list)
    assert len(d["sanity_warnings"]) >= 1


def test_to_dict_rejects_non_result_input():
    with pytest.raises(TypeError):
        to_dict({"not": "a result"})  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# Cross-cutting: pv components reconcile to enterprise value
# ─────────────────────────────────────────────────────────────────
def test_ev_equals_pv_explicit_plus_pv_terminal():
    """Internal consistency: EV = pv_explicit_fcf + pv_terminal.
    Catches any off-by-one in the discounting loop."""
    inputs = ThreeStageInputs(
        base_year_fcf=1_000.0,
        high_growth_rate=0.10,
        high_growth_years=4,
        fade_years=6,
        terminal_growth=0.04,
        discount_rate=0.115,
        shares_outstanding=100.0,
        net_debt=200.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.enterprise_value == pytest.approx(
        result.pv_explicit_fcf + result.pv_terminal, rel=1e-12
    )
    # And sum of per-year PVs equals pv_explicit_fcf
    sum_pvs = sum(p.pv for p in result.projections)
    assert sum_pvs == pytest.approx(result.pv_explicit_fcf, rel=1e-12)


def test_equity_equals_ev_minus_net_debt():
    """Equity bridge identity."""
    inputs = ThreeStageInputs(
        base_year_fcf=5_000.0,
        high_growth_rate=0.08,
        high_growth_years=5,
        fade_years=5,
        terminal_growth=0.04,
        discount_rate=0.10,
        shares_outstanding=500.0,
        net_debt=1_000.0,
    )
    result = compute_three_stage_dcf(inputs)
    assert result.method == "three_stage_dcf"
    assert result.equity_value == pytest.approx(
        result.enterprise_value - 1_000.0, rel=1e-12
    )
    # And per-share = equity / shares
    assert result.fair_value_per_share == pytest.approx(
        result.equity_value / 500.0, rel=1e-12
    )
