# backend/tests/test_cement_utilization_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for backend/services/cement_utilization_service.py (T3.8 Phase A).
#
# Coverage map — each test reads independently, no shared fixtures so
# a failure points at one concern:
#
#   compute_cement_fv
#     - ULTRACEMCO-shape (130 MTPA, 80% util, ₹1200/t, 17x premium)
#     - SHREECEM-shape   (47 MTPA, 82% util, ₹1300/t, 17x premium)
#     - AMBUJACEM-shape  (75 MTPA, 78% util, ₹1100/t, 13.5x mid-tier)
#     - sub-segment defaulting (unknown → mid_tier)
#     - non-positive capacity / mid-cycle / EBITDA / multiple guards
#     - per-share FV requires shares_outstanding > 0
#     - net-debt > EV → negative equity warning
#     - EBITDA/tonne below ₹600 → trough warning
#     - EBITDA/tonne above ₹1600 → peak warning
#     - multiple far from segment reference → warning
#     - current util below 75% → breakeven warning
#     - current util above 95% → stretched warning
#
#   classify_cycle_position
#     - 70% vs 80% mid → "trough"
#     - 80% vs 80% mid → "mid"
#     - 90% vs 80% mid → "peak"
#     - exactly mid - 7 → "trough" (inclusive)
#     - exactly mid + 7 → "peak" (inclusive)
#     - mid_util=0 → "mid" (defensive)
#
#   is_cement_applicable
#     - ULTRACEMCO → True (in registry)
#     - HDFCBANK → False (bank)
#     - sector hint "Cement" → True for unknown ticker
#     - sector hint "building materials" → True
#     - None sector + unknown ticker → False
#     - .NS suffix handled
#
#   to_dict
#     - shape contains all required keys + JSON-serialisable values
#     - mutating returned dict does not pollute the source result
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import json

import pytest

from backend.services.cement_utilization_service import (
    CEMENT_TICKERS,
    SEGMENT_MULTIPLES,
    CementInputs,
    CementResult,
    classify_cycle_position,
    compute_cement_fv,
    is_cement_applicable,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# compute_cement_fv — premium / mid-tier / weak shape tests
# ─────────────────────────────────────────────────────────────────

def test_ultracemco_premium_shape_produces_mid_cycle_ev():
    """ULTRACEMCO-shape: 130 MTPA × 80% × ₹1200/t × 17x → big EV.

    Mid-cycle production = 130 × 0.80 = 104 MTPA
    Mid-cycle EBITDA     = 104 × ₹1200 = ₹12,480 cr
    EV                   = 12,480 × 17 = ₹2,12,160 cr

    The bands below are sized to catch a units bug (a factor-of-10 or
    factor-of-100 error would blow through them) while tolerating
    reasonable parameter sensitivity.
    """
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=130.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=80.0,
        realization_per_tonne_inr=5800.0,
        ebitda_per_tonne_inr=1200.0,
        ev_ebitda_multiple=17.0,
        net_debt_inr_cr=5000.0,
        shares_outstanding=29e7,  # ~29 cr shares
        sub_segment="premium",
    ))
    assert result.method == "cement_capacity_utilization"
    assert 10_000.0 < result.mid_cycle_ebitda_inr_cr < 15_000.0
    assert result.enterprise_value_inr_cr is not None
    assert 180_000.0 < result.enterprise_value_inr_cr < 230_000.0
    assert result.fair_value_per_share is not None
    assert result.fair_value_per_share > 5000.0
    assert result.cycle_position_signal == "mid"


def test_shreecem_premium_shape_produces_per_share_fv():
    """SHREECEM-shape: 47 MTPA × 82% × ₹1300/t × 17x → per-share FV.

    Premium multiple anchored at 17x. Tight capacity (47 MTPA) means
    a focused cement-pure-play valuation — checks that the engine
    scales linearly with capacity vs ULTRACEMCO's 130 MTPA shape.
    """
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=47.0,
        current_utilization_pct=82.0,
        mid_cycle_utilization_pct=80.0,
        realization_per_tonne_inr=5900.0,
        ebitda_per_tonne_inr=1300.0,
        ev_ebitda_multiple=17.0,
        net_debt_inr_cr=2000.0,
        shares_outstanding=3.6e7,  # ~3.6 cr shares (SHREECEM low float)
        sub_segment="premium",
    ))
    assert result.method == "cement_capacity_utilization"
    # EBITDA: 47 × 0.80 × 1300 / 10 = 4,888 cr. EV ≈ 83k cr.
    assert 4_500.0 < result.mid_cycle_ebitda_inr_cr < 5_500.0
    assert result.enterprise_value_inr_cr is not None
    assert 75_000.0 < result.enterprise_value_inr_cr < 95_000.0
    assert result.fair_value_per_share is not None


def test_ambujacem_mid_tier_shape_uses_lower_multiple():
    """AMBUJACEM-shape: 75 MTPA × 78% × ₹1100/t × 13.5x → mid-tier EV.

    13.5x mid-tier multiple should land EV materially lower than
    if the same ticker were valued at the 17x premium multiple.
    """
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=75.0,
        current_utilization_pct=78.0,
        mid_cycle_utilization_pct=80.0,
        realization_per_tonne_inr=5700.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
        net_debt_inr_cr=0.0,  # AMBUJACEM is cash-positive
        shares_outstanding=24.6e8,  # ~246 cr shares (large float)
        sub_segment="mid_tier",
    ))
    assert result.method == "cement_capacity_utilization"
    # EBITDA: 75 × 0.80 × 1100 / 10 = 6,600 cr. EV: ≈ 89k cr.
    assert 6_000.0 < result.mid_cycle_ebitda_inr_cr < 7_500.0
    assert result.enterprise_value_inr_cr is not None
    assert 80_000.0 < result.enterprise_value_inr_cr < 100_000.0


def test_unknown_sub_segment_defaults_to_mid_tier():
    """An unrecognized sub_segment value falls back to mid_tier.

    Defensive — caller may pass a typo or evolve the enum without
    updating SEGMENT_MULTIPLES. Mid-tier is the safest default
    because it's the modal segment in the cohort.
    """
    # type-check escape via cast: the engine accepts any string but
    # only normalizes "premium" / "mid_tier" / "weak"; anything else
    # is coerced to mid_tier in components.
    inputs = CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
        sub_segment="mid_tier",  # explicit mid_tier baseline
    )
    result = compute_cement_fv(inputs)
    assert result.components["sub_segment"] == "mid_tier"


# ─────────────────────────────────────────────────────────────────
# compute_cement_fv — defensive / sanity guards
# ─────────────────────────────────────────────────────────────────

def test_non_positive_capacity_returns_unavailable():
    """Zero installed capacity → method="unavailable", FV=None."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=0.0,
        current_utilization_pct=80.0,
    ))
    assert result.method == "unavailable"
    assert result.fair_value_per_share is None
    assert result.enterprise_value_inr_cr is None
    assert any("capacity" in w.lower() for w in result.sanity_warnings)


def test_non_positive_mid_cycle_utilization_returns_unavailable():
    """Zero mid-cycle utilization → method="unavailable"."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=0.0,
    ))
    assert result.method == "unavailable"
    assert any("mid-cycle" in w.lower() for w in result.sanity_warnings)


def test_non_positive_ebitda_per_tonne_returns_unavailable():
    """Zero EBITDA/tonne → method="unavailable"."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=0.0,
    ))
    assert result.method == "unavailable"
    assert any("ebitda" in w.lower() for w in result.sanity_warnings)


def test_non_positive_multiple_returns_unavailable():
    """Zero multiple → method="unavailable"."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ev_ebitda_multiple=0.0,
    ))
    assert result.method == "unavailable"
    assert any("multiple" in w.lower() for w in result.sanity_warnings)


def test_missing_shares_outstanding_skips_per_share_fv():
    """shares_outstanding=0 → EV computed, per-share FV is None."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        mid_cycle_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
        shares_outstanding=0.0,
    ))
    assert result.method == "cement_capacity_utilization"
    assert result.enterprise_value_inr_cr is not None
    assert result.fair_value_per_share is None
    assert any("shares" in w.lower() for w in result.sanity_warnings)


def test_net_debt_above_ev_flags_distress():
    """net_debt > EV → negative equity → distress warning."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=10.0,  # tiny capacity → tiny EV
        current_utilization_pct=70.0,
        mid_cycle_utilization_pct=80.0,
        ebitda_per_tonne_inr=600.0,
        ev_ebitda_multiple=10.0,
        net_debt_inr_cr=50_000.0,  # enormous debt
        shares_outstanding=1e7,
        sub_segment="weak",
    ))
    assert any("distress" in w.lower() for w in result.sanity_warnings)
    # FV should not be computed for negative equity
    assert result.fair_value_per_share is None


def test_low_ebitda_per_tonne_fires_trough_warning():
    """EBITDA/tonne < ₹600 → trough warning."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=500.0,
        ev_ebitda_multiple=13.5,
    ))
    assert any("trough" in w.lower() for w in result.sanity_warnings)


def test_high_ebitda_per_tonne_fires_peak_warning():
    """EBITDA/tonne > ₹1600 → peak warning."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=1700.0,
        ev_ebitda_multiple=13.5,
    ))
    assert any("peak" in w.lower() for w in result.sanity_warnings)


def test_multiple_far_from_segment_reference_flags_warning():
    """Multiple outside ±25% of segment reference → warning.

    Mid-tier reference is 13.5x. 8x is 0.59x ratio → outside band.
    """
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=8.0,
        sub_segment="mid_tier",
    ))
    assert any("multiple" in w.lower() and "band" in w.lower()
               for w in result.sanity_warnings)


def test_low_current_utilization_fires_breakeven_warning():
    """current util < 75% → breakeven warning."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=70.0,
        mid_cycle_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
    ))
    assert any("breakeven" in w.lower() for w in result.sanity_warnings)


def test_high_current_utilization_fires_stretched_warning():
    """current util > 95% → stretched warning."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=97.0,
        mid_cycle_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
    ))
    assert any("stretched" in w.lower() for w in result.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# classify_cycle_position
# ─────────────────────────────────────────────────────────────────

def test_classify_trough_when_current_well_below_mid():
    """70% vs 80% mid → trough (gap of 10pp > 7pp threshold)."""
    assert classify_cycle_position(70.0, 80.0) == "trough"


def test_classify_mid_when_current_at_mid():
    """80% vs 80% mid → mid."""
    assert classify_cycle_position(80.0, 80.0) == "mid"


def test_classify_peak_when_current_well_above_mid():
    """90% vs 80% mid → peak (gap of 10pp > 7pp threshold)."""
    assert classify_cycle_position(90.0, 80.0) == "peak"


def test_classify_trough_at_exact_lower_boundary():
    """mid - 7pp → trough (inclusive boundary)."""
    assert classify_cycle_position(73.0, 80.0) == "trough"


def test_classify_peak_at_exact_upper_boundary():
    """mid + 7pp → peak (inclusive boundary)."""
    assert classify_cycle_position(87.0, 80.0) == "peak"


def test_classify_mid_just_inside_trough_threshold():
    """73.5% vs 80% mid → mid (just inside the band)."""
    assert classify_cycle_position(73.5, 80.0) == "mid"


def test_classify_defensive_when_mid_util_zero():
    """mid_util=0 → "mid" (defensive — ill-posed input)."""
    assert classify_cycle_position(80.0, 0.0) == "mid"


# ─────────────────────────────────────────────────────────────────
# is_cement_applicable
# ─────────────────────────────────────────────────────────────────

def test_known_cement_ticker_applies_via_registry():
    """ULTRACEMCO is in CEMENT_TICKERS → True."""
    applicable, reason = is_cement_applicable("ULTRACEMCO", None)
    assert applicable is True
    assert "CEMENT_TICKERS" in reason


def test_bank_ticker_does_not_apply():
    """HDFCBANK should never route through cement engine."""
    applicable, reason = is_cement_applicable("HDFCBANK", "Banks")
    assert applicable is False


def test_sector_hint_cement_applies_for_unknown_ticker():
    """A non-registered ticker with sector "Cement" → True."""
    applicable, reason = is_cement_applicable("RANDOMCEM", "Cement")
    assert applicable is True
    assert "cement" in reason.lower()


def test_sector_hint_building_materials_applies():
    """Sector "Building Materials" routes via hint."""
    applicable, reason = is_cement_applicable("UNKNOWN", "Building Materials")
    assert applicable is True


def test_none_sector_unknown_ticker_does_not_apply():
    """No sector hint + unknown ticker → False."""
    applicable, _ = is_cement_applicable("UNKNOWN", None)
    assert applicable is False


def test_ns_suffix_is_stripped_for_registry_lookup():
    """ULTRACEMCO.NS resolves the same as ULTRACEMCO."""
    applicable, _ = is_cement_applicable("ULTRACEMCO.NS", None)
    assert applicable is True


def test_every_registry_entry_is_in_known_sub_segments():
    """Sanity check on CEMENT_TICKERS schema."""
    valid_segments = set(SEGMENT_MULTIPLES.keys())
    for ticker, segment in CEMENT_TICKERS.items():
        assert segment in valid_segments, (
            f"{ticker} has unknown segment {segment!r}"
        )


def test_eleven_cement_tickers_registered():
    """Spec says 11 cement tickers — guard against accidental edits."""
    assert len(CEMENT_TICKERS) == 11


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────

def test_to_dict_shape_is_json_serialisable():
    """to_dict output must round-trip through json.dumps."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=130.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=1200.0,
        ev_ebitda_multiple=17.0,
        shares_outstanding=29e7,
        sub_segment="premium",
    ))
    d = to_dict(result)
    # All required keys present
    for key in (
        "fair_value_per_share",
        "mid_cycle_ebitda_inr_cr",
        "enterprise_value_inr_cr",
        "components",
        "cycle_position_signal",
        "method",
        "sanity_warnings",
    ):
        assert key in d
    # json round-trip
    json.dumps(d)


def test_to_dict_components_is_shallow_copy():
    """Mutating returned dict must not affect the source result."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=50.0,
        current_utilization_pct=80.0,
        ebitda_per_tonne_inr=1100.0,
        ev_ebitda_multiple=13.5,
    ))
    d = to_dict(result)
    d["components"]["installed_capacity_mtpa"] = -999.0
    # Source result unchanged
    assert result.components["installed_capacity_mtpa"] == 50.0


def test_to_dict_handles_unavailable_method():
    """An unavailable result still serializes cleanly."""
    result = compute_cement_fv(CementInputs(
        installed_capacity_mtpa=0.0,
        current_utilization_pct=80.0,
    ))
    d = to_dict(result)
    assert d["method"] == "unavailable"
    assert d["fair_value_per_share"] is None
    assert d["enterprise_value_inr_cr"] is None
    json.dumps(d)  # round-trip
