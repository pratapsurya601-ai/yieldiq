# backend/tests/test_epv_service.py
"""Tests for backend/services/epv_service.py — T2.2 Phase A.

Covers:
  * HUL-shaped (FMCG): stable EBIT margin ~21%, low capex → EPV computes
  * TCS-shaped (IT services): high margin (~28%), very low capex
  * TATAMOTORS-shaped (cyclical): negative-EBIT years → median fallback
  * Insufficient history (3 years) → None + applicability=False
  * Negative / out-of-band cost of capital → None
  * Zero shares outstanding → None
  * growth_value_gap: when dcf_fv=2000 and epv≈1400 → gap ≈ 600
  * is_epv_applicable: banks, insurers, REITs → False; FMCG → True
  * to_dict shape

Run: pytest backend/tests/test_epv_service.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════
# compute_normalized_ebit_margin
# ═══════════════════════════════════════════════════════════════
def test_normalized_margin_constant_history():
    """Constant 21% margin across 5 years → output 21%."""
    from backend.services.epv_service import compute_normalized_ebit_margin

    rev = [50000.0, 53000.0, 56000.0, 58000.0, 60000.0]
    ebit = [10500.0, 11130.0, 11760.0, 12180.0, 12600.0]  # all ~21%
    out = compute_normalized_ebit_margin(rev, ebit)
    assert out is not None
    assert out == pytest.approx(0.21, abs=0.005)


def test_normalized_margin_mixed_history():
    """Mixed margin across years → arithmetic mean."""
    from backend.services.epv_service import compute_normalized_ebit_margin

    rev = [100.0, 100.0, 100.0, 100.0, 100.0]
    ebit = [20.0, 22.0, 18.0, 24.0, 16.0]
    out = compute_normalized_ebit_margin(rev, ebit)
    assert out is not None
    assert out == pytest.approx(0.20, abs=0.001)


def test_normalized_margin_length_mismatch():
    """Mismatched lengths → None."""
    from backend.services.epv_service import compute_normalized_ebit_margin

    assert compute_normalized_ebit_margin([1.0, 2.0], [0.5]) is None


def test_normalized_margin_empty():
    from backend.services.epv_service import compute_normalized_ebit_margin

    assert compute_normalized_ebit_margin([], []) is None


def test_normalized_margin_too_few_valid_years():
    """Only 2 years with positive revenue → None."""
    from backend.services.epv_service import compute_normalized_ebit_margin

    rev = [0.0, 0.0, 0.0, 100.0, 200.0]
    ebit = [10.0, 10.0, 10.0, 20.0, 40.0]
    assert compute_normalized_ebit_margin(rev, ebit) is None


# ═══════════════════════════════════════════════════════════════
# compute_owner_earnings
# ═══════════════════════════════════════════════════════════════
def test_owner_earnings_textbook():
    """EBIT 1000, D&A 200, maint 150, dWC 50, t=0.25 → 750+200-150-50 = 750."""
    from backend.services.epv_service import compute_owner_earnings

    out = compute_owner_earnings(
        ebit=1000.0, da=200.0, maintenance_capex=150.0,
        wc_change=50.0, tax_rate=0.25,
    )
    # NOPAT = 1000 * 0.75 = 750; + 200 - 150 - 50 = 750
    assert out == pytest.approx(750.0, abs=0.001)


def test_owner_earnings_tax_clamped():
    """Tax 0.99 → clamps to 0.40 → NOPAT = 600 → owner = 600 + 200 - 150 - 50 = 600."""
    from backend.services.epv_service import compute_owner_earnings

    out = compute_owner_earnings(
        ebit=1000.0, da=200.0, maintenance_capex=150.0,
        wc_change=50.0, tax_rate=0.99,
    )
    assert out == pytest.approx(600.0, abs=0.001)


# ═══════════════════════════════════════════════════════════════
# compute_epv — happy paths
# ═══════════════════════════════════════════════════════════════
def test_compute_epv_hul_shaped():
    """HUL-shaped: stable ~21% EBIT margin, current rev 60000 Cr,
    capex 2000 Cr, D&A 1500 Cr, k=10.5%, t=25%, shares=2350M.

    Expect EPV per share roughly in a sane Cr-equivalent band.
    """
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[50000.0, 53000.0, 56000.0, 58000.0, 60000.0],
        ebit_history=[10500.0, 11130.0, 11760.0, 12180.0, 12600.0],
        da_history=[1200.0, 1300.0, 1350.0, 1400.0, 1500.0],
        capex_history=[1500.0, 1700.0, 1800.0, 1900.0, 2000.0],
        working_capital_history=[3000.0, 3200.0, 3300.0, 3400.0, 3500.0],
        current_revenue=60000.0,
        cost_of_capital=0.105,
        tax_rate=0.25,
        shares_outstanding=2350.0,  # in millions; units cancel via Cr
        maintenance_capex_fraction=0.6,
    )
    result = compute_epv(inputs)
    assert result.method == "epv_normalized"
    assert result.epv_per_share is not None
    assert result.epv_per_share > 0
    assert result.epv_aggregate is not None and result.epv_aggregate > 0
    assert result.components["normalized_margin"] == pytest.approx(0.21, abs=0.005)
    assert "history_years" in result.components
    assert result.components["history_years"] == 5
    assert result.components["has_negative_ebit_year"] is False
    # No DCF input → no gap
    assert result.growth_value_gap is None


def test_compute_epv_tcs_shaped_high_margin():
    """TCS-shaped: ~28% EBIT margin, very low capex, high D&A coverage."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[150000.0, 165000.0, 180000.0, 195000.0, 210000.0],
        ebit_history=[42000.0, 46200.0, 50400.0, 54600.0, 58800.0],  # all 28%
        da_history=[2200.0, 2400.0, 2600.0, 2800.0, 3000.0],
        capex_history=[2500.0, 2700.0, 2900.0, 3100.0, 3300.0],
        working_capital_history=[12000.0, 12500.0, 13000.0, 13500.0, 14000.0],
        current_revenue=210000.0,
        cost_of_capital=0.11,
        tax_rate=0.25,
        shares_outstanding=3600.0,
        maintenance_capex_fraction=0.5,  # services co — lower
    )
    result = compute_epv(inputs)
    assert result.method == "epv_normalized"
    assert result.epv_per_share is not None and result.epv_per_share > 0
    assert result.components["normalized_margin"] == pytest.approx(0.28, abs=0.005)
    # Owner earnings should be substantial relative to revenue at this margin
    assert result.components["owner_earnings"] > 0


# ═══════════════════════════════════════════════════════════════
# compute_epv — cyclical with negative-EBIT trough year
# ═══════════════════════════════════════════════════════════════
def test_compute_epv_tatamotors_shaped_with_trough():
    """Cyclical with one negative-EBIT year → median fallback + warning."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        # 5 years where year 2 is a trough (EBIT negative)
        revenue_history=[280000.0, 250000.0, 300000.0, 330000.0, 350000.0],
        ebit_history=[18000.0, -8000.0, 16000.0, 24000.0, 30000.0],
        da_history=[12000.0, 13000.0, 14000.0, 15000.0, 16000.0],
        capex_history=[20000.0, 18000.0, 21000.0, 23000.0, 25000.0],
        working_capital_history=[8000.0, 9000.0, 7000.0, 6000.0, 6500.0],
        current_revenue=350000.0,
        cost_of_capital=0.12,
        tax_rate=0.25,
        shares_outstanding=3700.0,
        maintenance_capex_fraction=0.7,  # cyclical industrial — higher
    )
    result = compute_epv(inputs)
    assert result.method == "epv_minimum_owner_earnings"
    assert result.components["has_negative_ebit_year"] is True
    # The warning text mentions median; assertion is on path, not content
    assert any("median" in w.lower() for w in result.sanity_warnings)
    # Should still produce a number (the median margin is positive)
    assert result.epv_per_share is not None


# ═══════════════════════════════════════════════════════════════
# compute_epv — defensive paths
# ═══════════════════════════════════════════════════════════════
def test_compute_epv_insufficient_history():
    """3 years of history → unavailable."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[100.0, 110.0, 120.0],
        ebit_history=[20.0, 22.0, 24.0],
        da_history=[5.0, 5.0, 5.0],
        capex_history=[6.0, 6.0, 6.0],
        working_capital_history=[10.0, 11.0, 12.0],
        current_revenue=120.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=100.0,
    )
    result = compute_epv(inputs)
    assert result.method == "unavailable"
    assert result.epv_per_share is None
    assert result.epv_aggregate is None
    assert result.components.get("reason") == "insufficient_history"


def test_compute_epv_negative_cost_of_capital():
    """Negative k → unavailable, no division-by-zero blowup."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[100.0] * 5,
        ebit_history=[20.0] * 5,
        da_history=[5.0] * 5,
        capex_history=[6.0] * 5,
        working_capital_history=[10.0] * 5,
        current_revenue=100.0,
        cost_of_capital=-0.05,
        tax_rate=0.25,
        shares_outstanding=100.0,
    )
    result = compute_epv(inputs)
    assert result.method == "unavailable"
    assert result.epv_per_share is None
    assert result.components.get("reason") == "cost_of_capital_out_of_range"


def test_compute_epv_zero_cost_of_capital():
    """k = 0 → unavailable."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[100.0] * 5,
        ebit_history=[20.0] * 5,
        da_history=[5.0] * 5,
        capex_history=[6.0] * 5,
        working_capital_history=[10.0] * 5,
        current_revenue=100.0,
        cost_of_capital=0.0,
        tax_rate=0.25,
        shares_outstanding=100.0,
    )
    result = compute_epv(inputs)
    assert result.method == "unavailable"


def test_compute_epv_zero_shares_outstanding():
    """Shares = 0 → unavailable."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[100.0] * 5,
        ebit_history=[20.0] * 5,
        da_history=[5.0] * 5,
        capex_history=[6.0] * 5,
        working_capital_history=[10.0] * 5,
        current_revenue=100.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=0.0,
    )
    result = compute_epv(inputs)
    assert result.method == "unavailable"
    assert result.components.get("reason") == "shares_outstanding_invalid"


def test_compute_epv_negative_current_revenue():
    """Bad current revenue → unavailable (caught by current_revenue gate)."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[100.0] * 5,
        ebit_history=[20.0] * 5,
        da_history=[5.0] * 5,
        capex_history=[6.0] * 5,
        working_capital_history=[10.0] * 5,
        current_revenue=-50.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=100.0,
    )
    result = compute_epv(inputs)
    assert result.method == "unavailable"


# ═══════════════════════════════════════════════════════════════
# growth_value_gap
# ═══════════════════════════════════════════════════════════════
def test_growth_value_gap_simple_arithmetic():
    """dcf_fv=2000, EPV≈1400 → gap ≈ 600."""
    from backend.services.epv_service import EPVInputs, compute_epv

    # Construct inputs that produce an EPV per share close to 1400.
    # Aggregate owner earnings / k / shares ≈ 1400.
    # Pick: owner_earnings = 1400 (1 share equivalent), k = 0.10,
    # shares = 1 → EPV per share = 14000.
    # We instead tune via revenue / margin to land near 1400.
    inputs = EPVInputs(
        revenue_history=[1000.0] * 5,
        ebit_history=[200.0] * 5,  # 20% margin
        da_history=[10.0] * 5,
        capex_history=[10.0] * 5,
        working_capital_history=[50.0] * 5,
        current_revenue=1000.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=1.0,
    )
    dcf_fv = 2000.0
    result = compute_epv(inputs, dcf_fv=dcf_fv)
    # Sanity: result.epv_per_share computed deterministically. gap = dcf_fv - epv.
    assert result.epv_per_share is not None
    assert result.growth_value_gap is not None
    assert result.growth_value_gap == pytest.approx(
        dcf_fv - result.epv_per_share, abs=0.001
    )


def test_growth_value_gap_dcf_below_epv_negative_gap():
    """When DCF < EPV (unusual — model under-pricing growth), gap is negative."""
    from backend.services.epv_service import EPVInputs, compute_epv

    inputs = EPVInputs(
        revenue_history=[1000.0] * 5,
        ebit_history=[200.0] * 5,
        da_history=[10.0] * 5,
        capex_history=[10.0] * 5,
        working_capital_history=[50.0] * 5,
        current_revenue=1000.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=1.0,
    )
    result = compute_epv(inputs, dcf_fv=10.0)
    assert result.growth_value_gap is not None
    assert result.growth_value_gap < 0


# ═══════════════════════════════════════════════════════════════
# is_epv_applicable
# ═══════════════════════════════════════════════════════════════
def test_is_applicable_fmcg_ok():
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="HUL", sector="FMCG", revenue_history_years=7,
        has_negative_earnings=False,
    )
    assert ok is True
    assert reason == "ok"


def test_is_applicable_hdfcbank_rejects_banks():
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="HDFCBANK", sector="Bank", revenue_history_years=10,
        has_negative_earnings=False,
    )
    assert ok is False
    assert "bank" in reason.lower()


def test_is_applicable_insurer_rejected():
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="HDFCLIFE", sector="Life Insurance", revenue_history_years=8,
        has_negative_earnings=False,
    )
    assert ok is False
    assert (
        "insurer" in reason.lower()
        or "appraisal" in reason.lower()
        or "embedded" in reason.lower()
    )


def test_is_applicable_reit_rejected():
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="EMBASSY", sector="REIT", revenue_history_years=6,
        has_negative_earnings=False,
    )
    assert ok is False


def test_is_applicable_regulated_utility_rejected():
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="NTPC", sector="Power Utility", revenue_history_years=10,
        has_negative_earnings=False,
    )
    assert ok is False


def test_is_applicable_jiofin_recent_ipo_rejected():
    """Recent IPO with < 5y of history → not applicable."""
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="JIOFIN", sector="Financial Services", revenue_history_years=2,
        has_negative_earnings=False,
    )
    assert ok is False
    assert "history" in reason.lower()


def test_is_applicable_loss_making_rejected():
    """Persistently loss-making → not applicable."""
    from backend.services.epv_service import is_epv_applicable

    ok, reason = is_epv_applicable(
        ticker="PAYTM", sector="Internet Platform", revenue_history_years=6,
        has_negative_earnings=True,
    )
    assert ok is False
    assert "loss" in reason.lower() or "earnings" in reason.lower()


# ═══════════════════════════════════════════════════════════════
# to_dict
# ═══════════════════════════════════════════════════════════════
def test_to_dict_shape_for_computed_result():
    """to_dict returns the documented shape with primitive types."""
    from backend.services.epv_service import EPVInputs, compute_epv, to_dict

    inputs = EPVInputs(
        revenue_history=[100.0] * 5,
        ebit_history=[20.0] * 5,
        da_history=[5.0] * 5,
        capex_history=[6.0] * 5,
        working_capital_history=[10.0] * 5,
        current_revenue=100.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=10.0,
    )
    result = compute_epv(inputs, dcf_fv=20.0)
    d = to_dict(result)
    # Documented keys all present
    for k in (
        "epv_per_share", "epv_aggregate", "components",
        "method", "sanity_warnings", "growth_value_gap",
    ):
        assert k in d
    assert isinstance(d["components"], dict)
    assert isinstance(d["sanity_warnings"], list)
    assert d["method"] == "epv_normalized"


def test_to_dict_shape_for_unavailable_result():
    """to_dict on an 'unavailable' result still carries the shape."""
    from backend.services.epv_service import EPVInputs, compute_epv, to_dict

    inputs = EPVInputs(
        revenue_history=[100.0, 100.0],   # too short
        ebit_history=[20.0, 20.0],
        da_history=[5.0, 5.0],
        capex_history=[6.0, 6.0],
        working_capital_history=[10.0, 10.0],
        current_revenue=100.0,
        cost_of_capital=0.10,
        tax_rate=0.25,
        shares_outstanding=10.0,
    )
    result = compute_epv(inputs)
    d = to_dict(result)
    assert d["method"] == "unavailable"
    assert d["epv_per_share"] is None
    assert d["epv_aggregate"] is None
    assert d["growth_value_gap"] is None
    assert "reason" in d["components"]
