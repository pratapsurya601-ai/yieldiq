# backend/tests/test_utilities_maintenance_capex_service.py
#
# Tests for the standalone utilities maintenance-capex intensity
# overlay shipped in T3.12 Phase A. Phase B will wire the overlay
# into the analysis route; this test surface covers ONLY the pure
# math + applicability gate so the Phase A PR can ship without
# touching any caller.
#
# Coverage:
#   1. POWERGRID-shaped transmission baseline — ratio ~1.1x norm → "normal"
#   2. NTPC-shaped thermal with larger growth capex (explicit split)
#   3. TATAPOWER-shaped distribution renewables mix — heavy band
#   4. NHPC-shaped renewable — low maintenance vs low norm → normal
#   5. Underspending warning case (deferred maintenance risk)
#   6. Extreme intensity warning case (asset stress signal)
#   7. classify_maintenance_intensity standalone — band boundaries
#   8. Defensive: D&A zero, fraction out of range, growth > total
#   9. Defensive: explicit growth_capex producing negative maintenance
#  10. Asset-base age + underspending compounding warning
#  11. is_utilities_maint_applicable — universe + reject paths
#  12. to_dict shape — JSON-safe
#
# Run: pytest backend/tests/test_utilities_maintenance_capex_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── POWERGRID-shaped transmission baseline ───────────────────────
def test_powergrid_shaped_transmission_normal():
    """POWERGRID: transmission, D&A ₹8,000 Cr, total capex ₹11,000 Cr
    with default 0.65 maintenance fraction → maint ₹7,150 Cr → ratio
    7150/8000 = 0.894x; segment norm 1.1x → rel = 0.81 (just inside
    'normal' band [0.8, 1.2]).

    Owner earnings = reported_fcf − (maint − D&A)
                   = 6000 − (7150 − 8000) = 6850 (D&A exceeds maint
                   slightly, so owner earnings exceed reported FCF —
                   POWERGRID is currently UNDER-spending vs the
                   accounting depreciation).
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=6000.0,
        da_inr_cr=8000.0,
        total_capex_inr_cr=11000.0,
        maintenance_capex_fraction=0.65,
        sub_segment="transmission",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_capex_estimated == pytest.approx(7150.0, abs=1.0)
    assert out.maintenance_intensity_pct == pytest.approx(89.375, abs=0.5)
    assert out.intensity_label == "normal"
    assert out.owner_earnings_inr_cr == pytest.approx(6850.0, abs=1.0)
    assert out.segment_norm_ratio == pytest.approx(1.1, abs=0.001)
    # Ratio vs norm = 0.894 / 1.1 ≈ 0.81
    assert out.ratio_vs_norm == pytest.approx(0.813, abs=0.01)


# ── NTPC-shaped thermal with explicit growth capex ──────────────
def test_ntpc_shaped_thermal_explicit_growth_split():
    """NTPC: thermal generation, big capex cycle with disclosed
    growth split. D&A ₹14,000 Cr, total capex ₹22,000 Cr, of which
    ₹10,000 Cr is growth → maintenance = 22000 − 10000 = ₹12,000 Cr.

    Ratio 12000/14000 = 0.857x; segment norm 0.9x → rel = 0.952
    (squarely 'normal'). Owner earnings = reported_fcf − (12000 −
    14000) = reported + 2000 (D&A > maint → owner earnings exceed
    reported FCF in this snapshot).
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=8000.0,
        da_inr_cr=14000.0,
        total_capex_inr_cr=22000.0,
        growth_capex_inr_cr=10000.0,
        sub_segment="generation_thermal",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_capex_estimated == pytest.approx(12000.0, abs=1.0)
    assert out.maintenance_intensity_pct == pytest.approx(85.71, abs=0.5)
    assert out.intensity_label == "normal"
    # owner_earnings = 8000 − (12000 − 14000) = 10000
    assert out.owner_earnings_inr_cr == pytest.approx(10000.0, abs=1.0)


# ── TATAPOWER-shaped distribution → heavy intensity ─────────────
def test_tatapower_shaped_distribution_heavy():
    """TATAPOWER (distribution, smart-meter / renewables mix):
    D&A ₹3,000 Cr, total capex ₹8,000 Cr, default 0.65 fraction →
    maint ₹5,200 Cr → ratio 5200/3000 = 1.733x; segment norm 1.2x →
    rel = 1.44 (between 1.2 and 1.5 → 'heavy').
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=1500.0,
        da_inr_cr=3000.0,
        total_capex_inr_cr=8000.0,
        maintenance_capex_fraction=0.65,
        sub_segment="distribution",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_capex_estimated == pytest.approx(5200.0, abs=1.0)
    assert out.intensity_label == "heavy"
    assert out.ratio_vs_norm == pytest.approx(1.444, abs=0.01)
    # One of the warnings should reference "heavy"
    assert any("heavy" in w for w in out.sanity_warnings)


# ── NHPC-shaped renewable — low maint vs low norm → normal ──────
def test_nhpc_shaped_renewable_normal():
    """NHPC (hydro): D&A ₹1,800 Cr, total capex ₹2,500 Cr, default
    0.65 fraction → maint ₹1,625 Cr → ratio 1625/1800 = 0.903x;
    segment norm 0.7x → rel = 1.29 (between 1.2 and 1.5 → 'heavy').

    This catches the segment-relative point: a 0.9x absolute ratio
    that would be 'normal' for thermal becomes 'heavy' for
    renewable because the norm is lower. Phase B's badge logic
    needs to respect this — it's the whole point of segmenting.
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=1200.0,
        da_inr_cr=1800.0,
        total_capex_inr_cr=2500.0,
        sub_segment="generation_renewable",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_capex_estimated == pytest.approx(1625.0, abs=1.0)
    # Absolute ratio 0.903x, but rel 1.29 → heavy
    assert out.intensity_label == "heavy"
    assert out.segment_norm_ratio == pytest.approx(0.7, abs=0.001)


# ── Underspending warning ───────────────────────────────────────
def test_underspending_warning_distribution():
    """Distribution norm 1.2x. Inputs producing absolute ratio 0.3x
    → rel 0.25 (< 0.8 → 'underspending'). Sanity warning should
    surface 'underspending' and 'deferred maintenance risk' tokens.
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=900.0,
        da_inr_cr=3000.0,
        total_capex_inr_cr=1400.0,
        maintenance_capex_fraction=0.65,
        sub_segment="distribution",
    )
    out = compute_maintenance_adjustment(inp)
    # maint = 1400 × 0.65 = 910 → 910/3000 = 0.303x absolute
    assert out.maintenance_capex_estimated == pytest.approx(910.0, abs=1.0)
    assert out.intensity_label == "underspending"
    joined = " ".join(out.sanity_warnings).lower()
    assert "underspending" in joined
    assert "deferred" in joined


# ── Extreme intensity warning ───────────────────────────────────
def test_extreme_intensity_warning_thermal():
    """Thermal norm 0.9x. Force maint/D&A = 2.0x absolute → rel 2.22
    (> 1.5 → 'extreme'). Warning surfaces 'extreme' and 'asset stress'.
    """
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=-500.0,
        da_inr_cr=5000.0,
        total_capex_inr_cr=20000.0,
        maintenance_capex_fraction=0.5,  # maint = 10000 → 2.0x D&A
        sub_segment="generation_thermal",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_capex_estimated == pytest.approx(10000.0, abs=1.0)
    assert out.intensity_label == "extreme"
    joined = " ".join(out.sanity_warnings).lower()
    assert "extreme" in joined
    assert "asset stress" in joined


# ── classify_maintenance_intensity band boundaries ──────────────
def test_classify_band_boundaries_thermal():
    """Thermal norm 0.9x:
      ratio 0 → 'underspending' (zero-or-negative special case)
      ratio 0.6 × 0.9 = 0.54 → rel 0.6 → underspending
      ratio 1.0 × 0.9 = 0.9  → rel 1.0 → normal
      ratio 1.3 × 0.9 = 1.17 → rel 1.3 → heavy
      ratio 1.6 × 0.9 = 1.44 → rel 1.6 → extreme
    """
    from backend.services.utilities_maintenance_capex_service import (
        classify_maintenance_intensity,
    )
    seg = "generation_thermal"
    assert classify_maintenance_intensity(0.0, seg) == "underspending"
    assert classify_maintenance_intensity(0.54, seg) == "underspending"
    assert classify_maintenance_intensity(0.9, seg) == "normal"
    assert classify_maintenance_intensity(1.17, seg) == "heavy"
    assert classify_maintenance_intensity(1.44, seg) == "extreme"


def test_classify_unknown_segment_uses_thermal_norm():
    """Unknown segment must not crash; falls back to thermal norm
    so the label is still produced."""
    from backend.services.utilities_maintenance_capex_service import (
        classify_maintenance_intensity,
    )
    assert classify_maintenance_intensity(0.9, "not_a_segment") == "normal"


# ── Defensive: D&A zero suppresses ratio ────────────────────────
def test_defensive_da_zero():
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=100.0,
        da_inr_cr=0.0,
        total_capex_inr_cr=500.0,
        sub_segment="transmission",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.maintenance_intensity_pct == 0.0
    assert out.intensity_label == "normal"
    assert any("D&A non-positive" in w for w in out.sanity_warnings)


# ── Defensive: fraction out of range clamped ────────────────────
def test_defensive_fraction_out_of_range_clamped():
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=1000.0,
        da_inr_cr=2000.0,
        total_capex_inr_cr=3000.0,
        maintenance_capex_fraction=1.5,  # invalid → clamped to 1.0
        sub_segment="transmission",
    )
    out = compute_maintenance_adjustment(inp)
    # Clamped to 1.0 → maint == total
    assert out.maintenance_capex_estimated == pytest.approx(3000.0, abs=1.0)
    assert any("out of [0,1]" in w for w in out.sanity_warnings)


# ── Defensive: growth > total falls back to fraction ────────────
def test_defensive_growth_greater_than_total():
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=1000.0,
        da_inr_cr=2000.0,
        total_capex_inr_cr=5000.0,
        growth_capex_inr_cr=7000.0,  # invalid — exceeds total
        maintenance_capex_fraction=0.65,
        sub_segment="generation_thermal",
    )
    out = compute_maintenance_adjustment(inp)
    # Falls back to fraction split → 5000 × 0.65 = 3250
    assert out.maintenance_capex_estimated == pytest.approx(3250.0, abs=1.0)
    assert any("falling back" in w for w in out.sanity_warnings)


# ── Asset-base age + underspending compounds risk ───────────────
def test_asset_age_with_underspending_compounds_warning():
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=500.0,
        da_inr_cr=3000.0,
        total_capex_inr_cr=1200.0,
        maintenance_capex_fraction=0.5,  # maint = 600 → 0.2x → underspending
        asset_base_age_years=30.0,
        sub_segment="distribution",
    )
    out = compute_maintenance_adjustment(inp)
    assert out.intensity_label == "underspending"
    joined = " ".join(out.sanity_warnings).lower()
    assert "asset_base_age" in joined
    assert "compounding" in joined


# ── Applicability gate ──────────────────────────────────────────
def test_applicability_gate_universe():
    from backend.services.utilities_maintenance_capex_service import (
        is_utilities_maint_applicable, UTILITIES_TICKERS,
    )
    for t in [
        "POWERGRID", "NTPC", "NHPC", "SJVN", "ADANIPOWER",
        "TATAPOWER", "TORNTPOWER", "JSWENERGY", "RELINFRA",
    ]:
        ok, reason = is_utilities_maint_applicable(t, "Utilities")
        assert ok is True, f"{t} should be applicable; got {reason}"
        assert t in UTILITIES_TICKERS


def test_applicability_gate_strips_exchange_suffix():
    from backend.services.utilities_maintenance_capex_service import (
        is_utilities_maint_applicable,
    )
    ok, _ = is_utilities_maint_applicable("POWERGRID.NS", None)
    assert ok is True
    ok, _ = is_utilities_maint_applicable("powergrid.bo", None)
    assert ok is True


def test_applicability_gate_rejects_non_utility():
    from backend.services.utilities_maintenance_capex_service import (
        is_utilities_maint_applicable,
    )
    ok, reason = is_utilities_maint_applicable("RELIANCE", "Energy")
    assert ok is False
    assert "not a utilities" in reason.lower()


def test_applicability_gate_sector_tag_soft_reject():
    """A utilities-tagged ticker NOT in the explicit list returns
    False with a soft signal so Phase B can choose to fire."""
    from backend.services.utilities_maintenance_capex_service import (
        is_utilities_maint_applicable,
    )
    ok, reason = is_utilities_maint_applicable("CESC", "Utilities")
    assert ok is False
    assert "not in UTILITIES_TICKERS" in reason


def test_applicability_gate_empty_ticker():
    from backend.services.utilities_maintenance_capex_service import (
        is_utilities_maint_applicable,
    )
    ok, reason = is_utilities_maint_applicable("", "Utilities")
    assert ok is False
    assert "empty" in reason.lower()


# ── to_dict shape ───────────────────────────────────────────────
def test_to_dict_shape_and_types():
    from backend.services.utilities_maintenance_capex_service import (
        UtilitiesMaintenanceInputs, compute_maintenance_adjustment, to_dict,
    )
    inp = UtilitiesMaintenanceInputs(
        reported_fcf_inr_cr=6000.0,
        da_inr_cr=8000.0,
        total_capex_inr_cr=11000.0,
        sub_segment="transmission",
    )
    d = to_dict(compute_maintenance_adjustment(inp))
    expected_keys = {
        "reported_fcf_inr_cr",
        "maintenance_capex_estimated_inr_cr",
        "owner_earnings_inr_cr",
        "maintenance_intensity_pct",
        "intensity_label",
        "sub_segment",
        "segment_norm_ratio",
        "ratio_vs_norm",
        "sanity_warnings",
    }
    assert expected_keys == set(d.keys())
    assert isinstance(d["sanity_warnings"], list)
    assert d["intensity_label"] in (
        "underspending", "normal", "heavy", "extreme",
    )
    assert d["sub_segment"] == "transmission"
    # All numeric fields plain floats — JSON-safe
    for k in (
        "reported_fcf_inr_cr",
        "maintenance_capex_estimated_inr_cr",
        "owner_earnings_inr_cr",
        "maintenance_intensity_pct",
        "segment_norm_ratio",
        "ratio_vs_norm",
    ):
        assert isinstance(d[k], (int, float)), f"{k} should be numeric"
