# backend/tests/test_steel_cost_curve_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for backend/services/steel_cost_curve_service.py (T3.9 Phase A).
#
# Coverage map (each test reads independently — no shared fixtures so a
# failure points at one concern):
#
#   compute_cost_curve_premium
#     - 70%+ integration → +1.0x
#     - 40-69% integration → +0.5x
#     - <40% integration → 0.0x
#     - negative / NaN clamps to 0.0
#
#   compute_steel_fv
#     - TATASTEEL-shape: 28 MTPA, 80% util, 60% integration, q2 →
#       through-cycle EBITDA ~₹12k/t, mid-cycle EBITDA, per-share FV
#     - JSWSTEEL-shape: 30 MTPA, q1 cost → q1 multiple 7.5 applied
#     - SAIL-shape: q3 cost → q3 multiple 5.0 applied
#     - integration premium tiers reflected in effective multiple
#     - cycle position: current util >> mid → cycle-peak warning
#     - cycle position: current util << mid → cycle-trough warning
#     - net debt subtracts from EV correctly
#     - negative through-cycle EBITDA → method="unavailable" + warning
#     - zero capacity → method="unavailable" + warning
#     - zero mid-cycle utilization → method="unavailable" + warning
#     - zero shares → method computed, fv_per_share=None, warning
#     - unknown quartile → defaults to q2 with warning
#     - negative equity (net debt > EV) → distress warning
#     - >35% through-cycle EBITDA margin → peak warning
#
#   is_steel_applicable
#     - every entry in STEEL_TICKERS → True
#     - .NS suffix handled
#     - "Metals & Mining" sector hint → True for unknown ticker
#     - "Aluminium" sector hint → True (HINDALCO / VEDL framework)
#     - HDFCBANK → False (bank, not steel)
#     - None sector + unknown ticker → False
#
#   to_dict
#     - shape contains all required keys + JSON-serialisable values
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import math

import pytest

from backend.services.steel_cost_curve_service import (
    QUARTILE_MULTIPLES,
    STEEL_TICKERS,
    SteelInputs,
    SteelResult,
    compute_cost_curve_premium,
    compute_steel_fv,
    is_steel_applicable,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# compute_cost_curve_premium
# ─────────────────────────────────────────────────────────────────

def test_integration_premium_high_tier_70_pct_adds_one_x():
    """≥70% integration adds +1.0x to the EV/EBITDA multiple."""
    assert compute_cost_curve_premium(70.0) == 1.0
    assert compute_cost_curve_premium(85.0) == 1.0
    assert compute_cost_curve_premium(100.0) == 1.0


def test_integration_premium_mid_tier_40_to_70_adds_half_x():
    """40%-69% integration adds +0.5x."""
    assert compute_cost_curve_premium(40.0) == 0.5
    assert compute_cost_curve_premium(50.0) == 0.5
    assert compute_cost_curve_premium(69.9) == 0.5


def test_integration_premium_low_tier_below_40_adds_none():
    """<40% integration adds 0.0x (no premium)."""
    assert compute_cost_curve_premium(0.0) == 0.0
    assert compute_cost_curve_premium(20.0) == 0.0
    assert compute_cost_curve_premium(39.9) == 0.0


def test_integration_premium_negative_or_nan_clamps_to_zero():
    """Negative / non-finite values clamp to 0.0."""
    assert compute_cost_curve_premium(-10.0) == 0.0
    assert compute_cost_curve_premium(float("nan")) == 0.0
    assert compute_cost_curve_premium(float("inf")) == 0.0
    assert compute_cost_curve_premium(None) == 0.0  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# compute_steel_fv — TATASTEEL shape
# ─────────────────────────────────────────────────────────────────

def test_tatasteel_shape_through_cycle_ebitda_and_mid_cycle():
    """TATASTEEL-shape inputs produce sensible through-cycle EBITDA.

    28 MTPA capacity, current util 80%, mid-cycle util 82%, realization
    ₹60k/t, cost ₹48k/t → through-cycle EBITDA = ₹12k/t.

    Mid-cycle EBITDA = 28 × 0.82 × 12000 / 10 = 27,552 INR cr.
    Q2 multiple 6.5 + integration premium (60% → +0.5) → 7.0x effective.
    EV = 27,552 × 7.0 = 192,864 INR cr.
    """
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=28.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=82.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=60.0,
        net_debt_inr_cr=80000.0,
        shares_outstanding=1_220_000_000.0,  # ~122 cr shares
    )
    out = compute_steel_fv(inputs)

    assert out.method == "cost_curve_ev_ebitda"
    assert out.through_cycle_ebitda_per_tonne == pytest.approx(12000.0, abs=1.0)
    # Mid-cycle EBITDA: 28 * 0.82 * 12000 / 10 = 27552 INR cr.
    assert out.mid_cycle_ebitda_inr_cr == pytest.approx(27552.0, abs=1.0)
    # Integration premium for 60% should be 0.5.
    assert out.integration_premium_pct == 0.5
    # Effective multiple = 6.5 (q2) + 0.5 (integration) = 7.0.
    assert out.components["effective_multiple"] == pytest.approx(7.0, abs=0.01)
    # EV = 27552 * 7.0 = 192864 INR cr.
    assert out.components["ev_inr_cr"] == pytest.approx(192864.0, abs=10.0)
    # Equity = EV - net_debt = 192864 - 80000 = 112864 INR cr.
    assert out.components["equity_inr_cr"] == pytest.approx(112864.0, abs=10.0)
    # Per share = 112864 * 1e7 / 1.22e9 ≈ ₹925.
    assert out.fair_value_per_share is not None
    assert 800 < out.fair_value_per_share < 1100


# ─────────────────────────────────────────────────────────────────
# compute_steel_fv — JSWSTEEL shape (q1)
# ─────────────────────────────────────────────────────────────────

def test_jswsteel_shape_q1_multiple_is_seven_point_five():
    """JSWSTEEL-shape (q1) applies the Q1 multiple 7.5x."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=30.0,
        current_utilization_pct=85.0,
        mid_cycle_utilization_pct=82.0,
        realization_per_tonne_inr=62000.0,
        cost_per_tonne_inr=45000.0,
        cost_curve_quartile="q1",
        iron_ore_integration_pct=30.0,  # Below 40% → 0.0 premium
        net_debt_inr_cr=70000.0,
        shares_outstanding=2_440_000_000.0,
    )
    out = compute_steel_fv(inputs)

    assert out.method == "cost_curve_ev_ebitda"
    assert out.components["quartile_multiple"] == 7.5
    assert out.integration_premium_pct == 0.0
    assert out.components["effective_multiple"] == 7.5
    # Through-cycle EBITDA/t = 62000 - 45000 = 17000.
    assert out.through_cycle_ebitda_per_tonne == pytest.approx(17000.0, abs=1.0)
    # Mid-cycle EBITDA = 30 * 0.82 * 17000 / 10 = 41,820 INR cr.
    assert out.mid_cycle_ebitda_inr_cr == pytest.approx(41820.0, abs=5.0)


# ─────────────────────────────────────────────────────────────────
# compute_steel_fv — SAIL shape (q3)
# ─────────────────────────────────────────────────────────────────

def test_sail_shape_q3_multiple_is_five():
    """SAIL-shape (q3) applies the Q3 multiple 5.0x."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=20.0,
        current_utilization_pct=75.0,
        mid_cycle_utilization_pct=78.0,
        realization_per_tonne_inr=56000.0,
        cost_per_tonne_inr=49000.0,
        cost_curve_quartile="q3",
        iron_ore_integration_pct=80.0,  # High → +1.0 premium
        net_debt_inr_cr=35000.0,
        shares_outstanding=4_130_000_000.0,
    )
    out = compute_steel_fv(inputs)

    assert out.method == "cost_curve_ev_ebitda"
    assert out.components["quartile_multiple"] == 5.0
    assert out.integration_premium_pct == 1.0
    assert out.components["effective_multiple"] == 6.0


def test_quartile_multiples_ordered_q1_high_to_q4_low():
    """Cost-curve multiples decrease monotonically Q1→Q4.

    Q1 (lowest cost) earns through the cycle and gets the highest
    multiple. Q4 (highest cost) only earns in tight markets and gets
    the lowest.
    """
    assert QUARTILE_MULTIPLES["q1"] > QUARTILE_MULTIPLES["q2"]
    assert QUARTILE_MULTIPLES["q2"] > QUARTILE_MULTIPLES["q3"]
    assert QUARTILE_MULTIPLES["q3"] > QUARTILE_MULTIPLES["q4"]


# ─────────────────────────────────────────────────────────────────
# Cycle position observation
# ─────────────────────────────────────────────────────────────────

def test_cycle_peak_warning_fires_when_current_util_runs_hot():
    """Current util ≥ mid + 8pp → cycle-peak warning."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=25.0,
        current_utilization_pct=92.0,  # well above mid 82
        mid_cycle_utilization_pct=82.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=50.0,
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert any("peak" in w for w in out.sanity_warnings)


def test_cycle_trough_warning_fires_when_current_util_runs_cold():
    """Current util ≤ mid - 10pp → cycle-trough warning."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=25.0,
        current_utilization_pct=68.0,  # well below mid 82
        mid_cycle_utilization_pct=82.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=50.0,
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert any("trough" in w for w in out.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# Defensive paths
# ─────────────────────────────────────────────────────────────────

def test_negative_through_cycle_ebitda_returns_unavailable():
    """Cost > realization → method='unavailable', no FV."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=15.0,
        current_utilization_pct=70.0,
        realization_per_tonne_inr=45000.0,
        cost_per_tonne_inr=50000.0,  # cost > realization
        cost_curve_quartile="q4",
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.method == "unavailable"
    assert out.fair_value_per_share is None
    assert any("loss-making" in w for w in out.sanity_warnings)


def test_zero_capacity_returns_unavailable():
    """Zero capacity → no FV, method='unavailable', warning fires."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=0.0,
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.method == "unavailable"
    assert out.fair_value_per_share is None
    assert any("capacity" in w for w in out.sanity_warnings)


def test_zero_mid_cycle_utilization_returns_unavailable():
    """Zero mid-cycle util → no FV."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=20.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=0.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.method == "unavailable"
    assert out.fair_value_per_share is None
    assert any("mid-cycle utilization" in w for w in out.sanity_warnings)


def test_zero_shares_outstanding_yields_no_per_share_fv():
    """Zero shares → engine still computes EV but per-share FV None."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=20.0,
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        net_debt_inr_cr=30000.0,
        shares_outstanding=0.0,
    )
    out = compute_steel_fv(inputs)
    assert out.method == "cost_curve_ev_ebitda"
    assert out.fair_value_per_share is None
    assert any("shares_outstanding" in w for w in out.sanity_warnings)
    # But mid-cycle EBITDA and EV should still be populated.
    assert out.mid_cycle_ebitda_inr_cr > 0
    assert out.components["ev_inr_cr"] > 0


def test_unknown_quartile_defaults_to_q2_with_warning():
    """Unrecognized quartile label → defaults to q2, warning."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=20.0,
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="qX",  # type: ignore[arg-type]
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.components["quartile_multiple"] == QUARTILE_MULTIPLES["q2"]
    assert any("quartile" in w for w in out.sanity_warnings)


def test_negative_equity_when_net_debt_exceeds_ev_fires_distress():
    """Net debt > EV → equity < 0 → distress warning."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=10.0,
        current_utilization_pct=70.0,
        realization_per_tonne_inr=55000.0,
        cost_per_tonne_inr=51000.0,  # thin spread → low EV
        cost_curve_quartile="q4",
        net_debt_inr_cr=500_000.0,  # absurd debt to force distress
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.components["equity_inr_cr"] < 0
    assert any("distress" in w for w in out.sanity_warnings)


def test_excess_through_cycle_ebitda_margin_fires_peak_warning():
    """Through-cycle EBITDA margin > 35% → peak-cycle warning.

    If cost figures are accidentally at cycle-trough levels, the
    apparent through-cycle margin balloons. Warning prompts the
    caller to verify cost inputs are mid-cycle.
    """
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=20.0,
        current_utilization_pct=82.0,
        realization_per_tonne_inr=80000.0,
        cost_per_tonne_inr=40000.0,  # margin = 40/80 = 50% way above 35
        cost_curve_quartile="q1",
        iron_ore_integration_pct=80.0,
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert any(
        "margin" in w and "35%" in w for w in out.sanity_warnings
    )


def test_net_debt_subtracts_from_ev_to_equity():
    """Equity should equal EV - net_debt exactly."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=25.0,
        current_utilization_pct=82.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=10.0,  # below 40 → 0.0 premium
        net_debt_inr_cr=50000.0,
        shares_outstanding=1_000_000_000.0,
    )
    out = compute_steel_fv(inputs)
    assert out.components["equity_inr_cr"] == pytest.approx(
        out.components["ev_inr_cr"] - 50000.0, abs=0.5
    )


# ─────────────────────────────────────────────────────────────────
# is_steel_applicable
# ─────────────────────────────────────────────────────────────────

def test_is_applicable_routes_every_known_ticker():
    """Every entry in STEEL_TICKERS routes True."""
    for ticker in STEEL_TICKERS:
        ok, reason = is_steel_applicable(ticker, None)
        assert ok is True, f"{ticker} should route True, got reason={reason}"
        assert ticker in reason


def test_is_applicable_strips_ns_suffix():
    """``TATASTEEL.NS`` resolves the same as bare TATASTEEL."""
    ok, _ = is_steel_applicable("TATASTEEL.NS", None)
    assert ok is True


def test_is_applicable_matches_metals_mining_sector_hint():
    """Unknown ticker with 'Metals & Mining' sector → applicable."""
    ok, reason = is_steel_applicable("UNKNOWN", "Metals & Mining")
    assert ok is True
    assert "metals" in reason.lower()


def test_is_applicable_matches_aluminium_sector_hint():
    """HINDALCO / VEDL share the framework; aluminium hint routes True."""
    ok, _ = is_steel_applicable("UNKNOWNALU", "Aluminium")
    assert ok is True


def test_is_applicable_returns_false_for_bank_ticker():
    """HDFCBANK is a bank, not a steel producer."""
    ok, reason = is_steel_applicable("HDFCBANK", "Banks")
    assert ok is False
    assert "does not match" in reason


def test_is_applicable_returns_false_when_sector_missing_and_unknown_ticker():
    """No sector + ticker not in STEEL_TICKERS → False."""
    ok, reason = is_steel_applicable("UNKNOWN", None)
    assert ok is False
    assert "no sector hint" in reason


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────

def test_to_dict_shape_is_json_safe_and_has_all_keys():
    """to_dict output is JSON-serialisable + has all required keys."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=25.0,
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=50.0,
        net_debt_inr_cr=40000.0,
        shares_outstanding=1_000_000_000.0,
    )
    result = compute_steel_fv(inputs)
    d = to_dict(result)

    required_keys = {
        "fair_value_per_share",
        "through_cycle_ebitda_per_tonne",
        "mid_cycle_ebitda_inr_cr",
        "integration_premium_pct",
        "components",
        "method",
        "sanity_warnings",
    }
    assert required_keys.issubset(d.keys())

    # Roundtrip through json — proves shape is JSON-safe.
    serialized = json.dumps(d, default=str)
    assert isinstance(serialized, str)
    assert len(serialized) > 100


def test_to_dict_components_is_a_shallow_copy_not_a_reference():
    """Mutating the returned dict must not pollute the source result."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=25.0,
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        iron_ore_integration_pct=50.0,
        shares_outstanding=1_000_000_000.0,
    )
    result = compute_steel_fv(inputs)
    d = to_dict(result)
    d["components"]["injected"] = "should_not_leak_into_result"
    assert "injected" not in result.components


def test_to_dict_on_unavailable_result_still_well_formed():
    """Unavailable-method result still produces a well-formed dict."""
    inputs = SteelInputs(
        crude_steel_capacity_mtpa=0.0,  # forces unavailable
        current_utilization_pct=80.0,
        realization_per_tonne_inr=60000.0,
        cost_per_tonne_inr=48000.0,
        cost_curve_quartile="q2",
        shares_outstanding=1_000_000_000.0,
    )
    result = compute_steel_fv(inputs)
    d = to_dict(result)
    assert d["method"] == "unavailable"
    assert d["fair_value_per_share"] is None
    assert isinstance(d["components"], dict)
    assert isinstance(d["sanity_warnings"], list)
    assert len(d["sanity_warnings"]) >= 1


def test_dataclass_default_factory_isolates_components_across_instances():
    """Two independent SteelResult instances must not share components."""
    a = SteelResult(
        fair_value_per_share=None,
        through_cycle_ebitda_per_tonne=0.0,
        mid_cycle_ebitda_inr_cr=0.0,
        integration_premium_pct=0.0,
    )
    b = SteelResult(
        fair_value_per_share=None,
        through_cycle_ebitda_per_tonne=0.0,
        mid_cycle_ebitda_inr_cr=0.0,
        integration_premium_pct=0.0,
    )
    a.components["x"] = 1
    a.sanity_warnings.append("a warn")
    assert "x" not in b.components
    assert b.sanity_warnings == []
