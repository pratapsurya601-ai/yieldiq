# backend/tests/test_pharma_pipeline_service.py
#
# Covers the standalone pharma-pipeline rNPV engine in
# backend/services/pharma_pipeline_service.py.
#
# Surface:
#   1. value_single_asset — POA scaling by phase, biosimilar
#      penetration / exclusivity, discount-rate sensitivity.
#   2. value_pipeline — multi-asset sum, top-3 drivers,
#      contribution_pct distribution, sensitivity shocks.
#   3. is_pharma_pipeline_meaningful — sector + curated-data gating.
#   4. Seed JSON loader — SUNPHARMA / DRREDDY / BIOCON round-trip.
#   5. to_dict shape — JSON-safe surface.
#
# Run: pytest backend/tests/test_pharma_pipeline_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────────
# Imports under test
# ─────────────────────────────────────────────────────────────────
from backend.services.pharma_pipeline_service import (  # noqa: E402
    PipelineAsset,
    PipelineAssetValuation,
    PipelineValuationResult,
    POA_BY_PHASE,
    has_curated_pipeline_data,
    is_pharma_pipeline_meaningful,
    load_curated_assets,
    to_dict,
    value_pipeline,
    value_single_asset,
)


# ─────────────────────────────────────────────────────────────────
# Reference asset — canonical Phase 3 oncology used across cases.
# ─────────────────────────────────────────────────────────────────


def _reference_phase3_asset(**overrides) -> PipelineAsset:
    base = dict(
        name="Reference oncology asset",
        phase="phase_3",
        indication="oncology",
        target_market_size_usd=4.5e9,
        expected_peak_share_pct=12.0,
        expected_margin_pct=35.0,
        expected_launch_year_offset=3,
        exclusivity_years=11,
    )
    base.update(overrides)
    return PipelineAsset(**base)


# ─────────────────────────────────────────────────────────────────
# value_single_asset — POA scaling
# ─────────────────────────────────────────────────────────────────


def test_phase3_oncology_rnpv_magnitude_is_reasonable():
    """Phase 3 oncology asset with TAM $4.5B, 12% peak share, 35%
    margin, launch in 3y, 11y exclusivity, 13% discount.

    The asset's risk-unadjusted PV is on the order of $500-700M; at
    POA = 0.55 the rNPV settles in the $250-450M range. In INR Cr at
    USD/INR = 83 that is ~₹2,000-3,800 Cr.

    Lock in a band rather than a point so future tweaks to the
    penetration curve don't have to re-write the assertion. The
    purpose is to catch order-of-magnitude regressions, not to pin
    the engine to today's math byte-for-byte.
    """
    a = _reference_phase3_asset()
    v = value_single_asset(a, discount_rate=0.13, usd_to_inr=83.0)
    assert isinstance(v, PipelineAssetValuation)
    assert v.poa_applied == pytest.approx(POA_BY_PHASE["phase_3"], abs=1e-9)
    assert 250e6 <= v.rnpv_usd <= 450e6
    assert 2000 <= v.rnpv_inr_cr <= 3800
    # Peak revenue = TAM × peak share, irrespective of POA.
    assert v.peak_revenue_usd == pytest.approx(4.5e9 * 0.12, abs=1.0)


def test_preclinical_value_drops_dramatically_vs_phase3():
    """Same inputs except phase=preclinical — POA falls from 0.55 to
    0.08, so rNPV should drop by roughly that ratio (≈14% of the
    Phase 3 value).

    rNPV is linear in POA, so the ratio of preclinical/phase3
    rNPV equals 0.08/0.55 ≈ 0.145 exactly. Loose bounds tolerate
    any future small rounding tweak.
    """
    phase3 = _reference_phase3_asset()
    preclinical = _reference_phase3_asset(phase="preclinical")

    v3 = value_single_asset(phase3, discount_rate=0.13)
    vp = value_single_asset(preclinical, discount_rate=0.13)

    expected_ratio = POA_BY_PHASE["preclinical"] / POA_BY_PHASE["phase_3"]
    assert vp.rnpv_inr_cr / v3.rnpv_inr_cr == pytest.approx(expected_ratio, abs=0.005)


def test_filed_asset_has_near_term_high_value():
    """Filed assets get POA = 0.87 and launch close to today — the
    rNPV should beat the equivalent Phase 3 asset (POA 0.55, launch
    pushed further out).
    """
    filed = _reference_phase3_asset(phase="filed", expected_launch_year_offset=1)
    phase3 = _reference_phase3_asset()
    vf = value_single_asset(filed)
    v3 = value_single_asset(phase3)
    assert vf.rnpv_inr_cr > v3.rnpv_inr_cr
    assert vf.poa_applied == pytest.approx(POA_BY_PHASE["filed"], abs=1e-9)


def test_discovery_asset_is_low_value():
    """Discovery POA = 0.03 — rNPV should be tiny relative to a
    Phase 3 asset with the same downstream economics.
    """
    discovery = _reference_phase3_asset(phase="discovery", expected_launch_year_offset=8)
    v = value_single_asset(discovery)
    assert v.poa_applied == pytest.approx(POA_BY_PHASE["discovery"], abs=1e-9)
    # Discovery rNPV must be at least 10x smaller than a Phase 3 asset
    # with the same launch offset (POA ratio alone is ~18x).
    phase3 = _reference_phase3_asset(expected_launch_year_offset=8)
    v_p3 = value_single_asset(phase3)
    assert v.rnpv_inr_cr * 10 < v_p3.rnpv_inr_cr


def test_zero_tam_yields_zero_rnpv():
    a = _reference_phase3_asset(target_market_size_usd=0.0)
    v = value_single_asset(a)
    assert v.rnpv_usd == 0.0
    assert v.rnpv_inr_cr == 0.0


def test_custom_poa_override_replaces_phase_default():
    """A custom override pins the POA regardless of phase."""
    a = _reference_phase3_asset(custom_poa_override=0.20)
    v = value_single_asset(a)
    assert v.poa_applied == pytest.approx(0.20, abs=1e-9)


def test_poa_override_clamped_to_unit_interval():
    """POA > 1.0 must clamp to 1.0; POA < 0.0 to 0.0."""
    too_high = _reference_phase3_asset(custom_poa_override=1.5)
    too_low = _reference_phase3_asset(custom_poa_override=-0.2)
    assert value_single_asset(too_high).poa_applied == 1.0
    assert value_single_asset(too_low).poa_applied == 0.0


# ─────────────────────────────────────────────────────────────────
# Biosimilar economics
# ─────────────────────────────────────────────────────────────────


def test_biosimilar_short_exclusivity_lowers_value_vs_nce():
    """A biosimilar with the same TAM / share / margin as an NCE
    will have a shorter exclusivity (5-7y vs 10-12y), so the rNPV is
    materially lower even before the faster-but-still-bounded ramp
    helps.
    """
    nce = _reference_phase3_asset(exclusivity_years=11, is_biosimilar=False)
    bio = _reference_phase3_asset(exclusivity_years=6, is_biosimilar=True)
    vn = value_single_asset(nce)
    vb = value_single_asset(bio)
    assert vb.rnpv_inr_cr < vn.rnpv_inr_cr


def test_biosimilar_with_matching_exclusivity_higher_than_nce_during_ramp():
    """When the exclusivity windows match, the biosimilar's faster
    early-ramp curve makes the early years (the discount-rate-
    privileged ones) more valuable — total rNPV should be greater
    than the equivalent NCE.

    This regression-guards the penetration-curve choice for
    biosimilars: if a refactor ever flips the bio curve to slower-
    than-NCE, this test catches it.
    """
    nce = _reference_phase3_asset(exclusivity_years=6, is_biosimilar=False)
    bio = _reference_phase3_asset(exclusivity_years=6, is_biosimilar=True)
    vn = value_single_asset(nce)
    vb = value_single_asset(bio)
    assert vb.rnpv_inr_cr > vn.rnpv_inr_cr


# ─────────────────────────────────────────────────────────────────
# Discount-rate sensitivity
# ─────────────────────────────────────────────────────────────────


def test_discount_rate_clamped_to_band():
    """A discount rate of 50% (out of band) must be clamped to the
    18% ceiling; -5% to the 10% floor.

    The clamp lets the caller pass any number without blowing up the
    rNPV; we still want correct math at the boundary.
    """
    a = _reference_phase3_asset()
    high = value_single_asset(a, discount_rate=0.50)
    at_ceiling = value_single_asset(a, discount_rate=0.18)
    low = value_single_asset(a, discount_rate=-0.05)
    at_floor = value_single_asset(a, discount_rate=0.10)
    assert high.rnpv_inr_cr == at_ceiling.rnpv_inr_cr
    assert low.rnpv_inr_cr == at_floor.rnpv_inr_cr


# ─────────────────────────────────────────────────────────────────
# value_pipeline — multi-asset aggregation
# ─────────────────────────────────────────────────────────────────


def test_value_pipeline_total_sums_per_asset_rnpv():
    """Multi-asset total must equal Σ(single-asset rNPV)."""
    assets = [
        _reference_phase3_asset(name="A"),
        _reference_phase3_asset(name="B", phase="filed", expected_launch_year_offset=1),
        _reference_phase3_asset(name="C", phase="preclinical"),
    ]
    individual = [value_single_asset(a).rnpv_inr_cr for a in assets]
    result = value_pipeline(assets)
    assert result.total_pipeline_rnpv_inr_cr == pytest.approx(sum(individual), abs=0.05)
    assert result.method == "rnpv_per_asset"


def test_value_pipeline_top_3_drivers_sorted_descending_by_contribution():
    """Top drivers must come out in descending contribution order."""
    assets = [
        _reference_phase3_asset(name="HighValueFiled", phase="filed"),
        _reference_phase3_asset(name="LowValueDiscovery", phase="discovery"),
        _reference_phase3_asset(name="MidValuePhase3"),
    ]
    result = value_pipeline(assets)
    # 'HighValueFiled' must lead the drivers list.
    assert result.top_3_drivers[0] == "HighValueFiled"
    # Each driver is unique.
    assert len(set(result.top_3_drivers)) == len(result.top_3_drivers)


def test_value_pipeline_contribution_pct_sums_to_100():
    """Per-asset contribution_pct values must sum to ~100% when the
    total is positive."""
    assets = [
        _reference_phase3_asset(name="A"),
        _reference_phase3_asset(name="B", phase="phase_2"),
    ]
    result = value_pipeline(assets)
    total_pct = sum((v.contribution_pct or 0.0) for v in result.asset_valuations)
    assert total_pct == pytest.approx(100.0, abs=0.05)


def test_empty_pipeline_returns_unavailable_method():
    """No assets → method='unavailable' + zero total."""
    result = value_pipeline([])
    assert result.method == "unavailable"
    assert result.total_pipeline_rnpv_inr_cr == 0.0
    assert result.asset_valuations == []
    assert result.top_3_drivers == []


# ─────────────────────────────────────────────────────────────────
# Sensitivity shocks
# ─────────────────────────────────────────────────────────────────


def test_sensitivity_poa_50_pct_shock_halves_total():
    """rNPV is linear in POA. A 50% POA cut on every asset should
    cut the total by exactly 50%."""
    assets = [_reference_phase3_asset(name="X")]
    result = value_pipeline(assets)
    shock = result.sensitivity["poa_minus_50_pct"]
    assert shock["delta_pct"] == pytest.approx(-50.0, abs=0.1)


def test_sensitivity_peak_share_minus_25_pct_drops_value():
    """A 25% peak-share cut must reduce the total — exact magnitude
    is order-of-magnitude tested rather than pinned because the
    ramp curve makes it not perfectly linear at the year-2 level."""
    assets = [_reference_phase3_asset(name="X")]
    result = value_pipeline(assets)
    shock = result.sensitivity["peak_share_minus_25_pct"]
    assert -30.0 <= shock["delta_pct"] <= -20.0


def test_sensitivity_discount_rate_plus_200_bps_drops_value():
    """+200 bps on the discount rate must drop the total."""
    assets = [_reference_phase3_asset(name="X")]
    result = value_pipeline(assets)
    shock = result.sensitivity["discount_rate_plus_200_bps"]
    assert shock["delta_pct"] < 0.0


# ─────────────────────────────────────────────────────────────────
# is_pharma_pipeline_meaningful — routing
# ─────────────────────────────────────────────────────────────────


def test_routing_pharma_ticker_with_curated_data_returns_true():
    ok, reason = is_pharma_pipeline_meaningful(
        "SUNPHARMA", sector="pharma", has_curated_pipeline_data=True,
    )
    assert ok is True
    assert "pharma" in reason.lower()


def test_routing_pharma_ticker_without_curated_data_returns_false():
    ok, reason = is_pharma_pipeline_meaningful(
        "SUNPHARMA", sector="pharma", has_curated_pipeline_data=False,
    )
    assert ok is False
    # Reason must point at the missing-data root cause.
    assert "no curated pipeline data" in reason.lower()


def test_routing_non_pharma_ticker_returns_false():
    ok, reason = is_pharma_pipeline_meaningful(
        "HDFCBANK", sector="banking", has_curated_pipeline_data=True,
    )
    assert ok is False
    assert "pharma cohort" in reason.lower()


def test_routing_handles_ticker_with_ns_suffix():
    """The matcher must strip .NS / .BO suffix before checking the
    pharma cohort."""
    ok, _ = is_pharma_pipeline_meaningful(
        "SUNPHARMA.NS", sector=None, has_curated_pipeline_data=True,
    )
    assert ok is True


def test_routing_empty_ticker_returns_false():
    ok, reason = is_pharma_pipeline_meaningful(
        "", sector="pharma", has_curated_pipeline_data=True,
    )
    assert ok is False
    assert "empty" in reason.lower()


# ─────────────────────────────────────────────────────────────────
# Seed JSON loader
# ─────────────────────────────────────────────────────────────────


def test_seed_loader_returns_curated_assets_for_sunpharma():
    assets = load_curated_assets("SUNPHARMA")
    assert len(assets) >= 2  # Phase A seed carries 3 assets
    # Every asset must be a PipelineAsset and every phase must be a
    # recognised key in POA_BY_PHASE so the math fires correctly.
    for a in assets:
        assert isinstance(a, PipelineAsset)
        assert a.phase in POA_BY_PHASE
        assert a.target_market_size_usd > 0
        assert 0 < a.expected_peak_share_pct <= 100
        assert 0 < a.expected_margin_pct <= 100
        assert a.exclusivity_years > 0


def test_seed_loader_returns_empty_list_for_unknown_ticker():
    assert load_curated_assets("RANDOMNAME") == []
    assert load_curated_assets("") == []


def test_has_curated_pipeline_data_true_for_seed_tickers():
    assert has_curated_pipeline_data("SUNPHARMA") is True
    assert has_curated_pipeline_data("DRREDDY") is True
    assert has_curated_pipeline_data("BIOCON") is True


def test_has_curated_pipeline_data_false_for_non_seed_ticker():
    assert has_curated_pipeline_data("HDFCBANK") is False
    assert has_curated_pipeline_data("RELIANCE") is False


def test_seed_loader_strips_ns_suffix():
    """`.NS` suffix should not block a seed hit."""
    assert has_curated_pipeline_data("SUNPHARMA.NS") is True
    assert len(load_curated_assets("DRREDDY.BO")) > 0


# ─────────────────────────────────────────────────────────────────
# value_pipeline with real seed data (end-to-end smoke)
# ─────────────────────────────────────────────────────────────────


def test_sunpharma_seed_pipeline_produces_positive_total():
    assets = load_curated_assets("SUNPHARMA")
    result = value_pipeline(assets, discount_rate=0.13, usd_to_inr=83.0)
    assert result.method == "rnpv_per_asset"
    assert result.total_pipeline_rnpv_inr_cr > 0
    assert len(result.asset_valuations) == len(assets)
    assert len(result.top_3_drivers) >= 1


def test_drreddy_seed_pipeline_top_driver_is_largest_contributor():
    assets = load_curated_assets("DRREDDY")
    result = value_pipeline(assets)
    ranked = sorted(
        result.asset_valuations, key=lambda v: v.rnpv_inr_cr, reverse=True,
    )
    assert result.top_3_drivers[0] == ranked[0].asset.name


# ─────────────────────────────────────────────────────────────────
# to_dict — JSON-safe shape
# ─────────────────────────────────────────────────────────────────


def test_to_dict_has_expected_top_level_keys():
    assets = [_reference_phase3_asset(name="A")]
    result = value_pipeline(assets)
    d = to_dict(result)
    for key in (
        "method",
        "total_pipeline_rnpv_inr_cr",
        "top_3_drivers",
        "asset_valuations",
        "sensitivity",
        "sanity_warnings",
    ):
        assert key in d, f"Missing top-level key {key!r}"


def test_to_dict_asset_valuation_shape():
    assets = [_reference_phase3_asset(name="A")]
    d = to_dict(value_pipeline(assets))
    assert isinstance(d["asset_valuations"], list)
    assert len(d["asset_valuations"]) == 1
    av = d["asset_valuations"][0]
    for key in (
        "name", "phase", "indication", "is_biosimilar",
        "poa_applied", "peak_revenue_usd",
        "rnpv_usd", "rnpv_inr_cr", "contribution_pct",
    ):
        assert key in av, f"Missing per-asset key {key!r}"
    # Types must be JSON-friendly.
    assert isinstance(av["name"], str)
    assert isinstance(av["phase"], str)
    assert isinstance(av["is_biosimilar"], bool)
    assert isinstance(av["poa_applied"], float)
    assert isinstance(av["rnpv_inr_cr"], float)


def test_to_dict_is_json_serialisable():
    """Anything we return must survive a json.dumps round-trip."""
    import json
    assets = load_curated_assets("SUNPHARMA")
    d = to_dict(value_pipeline(assets))
    payload = json.dumps(d)  # raises TypeError if anything non-serialisable
    reloaded = json.loads(payload)
    assert reloaded["method"] == "rnpv_per_asset"
    assert reloaded["total_pipeline_rnpv_inr_cr"] > 0


# ─────────────────────────────────────────────────────────────────
# Sanity warnings
# ─────────────────────────────────────────────────────────────────


def test_sanity_warning_fires_for_aggressive_peak_share():
    """Peak share > 60% must generate a warning."""
    a = _reference_phase3_asset(expected_peak_share_pct=75.0)
    result = value_pipeline([a])
    assert any("aggressive" in w.lower() for w in result.sanity_warnings)


def test_sanity_warning_fires_for_biosimilar_with_overlong_exclusivity():
    a = _reference_phase3_asset(
        exclusivity_years=12, is_biosimilar=True,
    )
    result = value_pipeline([a])
    assert any("biosimilar exclusivity" in w.lower() for w in result.sanity_warnings)
