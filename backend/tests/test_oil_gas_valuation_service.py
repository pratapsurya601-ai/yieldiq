# backend/tests/test_oil_gas_valuation_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for backend/services/oil_gas_valuation_service.py (T3.7 Phase A).
#
# Coverage map (top-to-bottom — each test reads independently, no shared
# fixtures so a failure points at one concern):
#
#   compute_upstream_reserves_npv
#     - ONGC-shape: proved 5500 MMBOE, prod 250 MMBOE/yr, $70/bbl,
#       opex $25/bbl, royalty 20%, cess 20%, tax 25% → NPV in expected
#       large-E&P band
#     - probable reserves contribute at 50% probability weight
#     - reserves life sanity warnings fire at <5y and >30y boundaries
#     - non-positive reserves → npv=0 + warning
#     - terminal_residual non-negative for normal positive-spread inputs
#     - depletion compounds correctly (year-2 production < year-1)
#
#   compute_downstream_ev_ebitda
#     - IOC-shape: 80 MMT × $8 GRM × 95% util × 6.5x → mid-cycle EV
#     - GRM < 4 USD/bbl → stressed warning
#     - GRM > 15 USD/bbl → peak warning
#     - negative equity (debt > EV) → distress warning
#     - zero throughput → ev=0 + warning
#
#   compute_city_gas_value
#     - IGL-shape: CNG 4 + PNG 2.5 MMSCM/day, ₹6.5/scm, 14x → equity EV
#     - zero volume → ev=0 + warning
#     - net debt subtracts correctly
#
#   compute_integrated_sotp
#     - RELIANCE-shape: upstream + downstream + petrochem + retail
#       components with shares → per-share FV
#     - missing component (None) is skipped, not zero
#     - all-None → method="unavailable"
#     - zero shares → fv_per_share=None + warning
#     - negative equity (debt > SOTP) → distress warning
#
#   select_method_for_ticker
#     - every entry in OIL_GAS_TICKERS routes correctly
#     - .NS suffix handled
#     - unknown ticker → None
#
#   is_oil_gas_applicable
#     - ONGC → True (in registry)
#     - HDFCBANK → False (bank, not oil-gas)
#     - sector hint "Oil & Gas" → True for unknown ticker
#     - None sector + unknown ticker → False
#
#   to_dict
#     - shape contains all 5 required keys + JSON-serialisable values
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import json

import pytest

from backend.services.oil_gas_valuation_service import (
    OIL_GAS_TICKERS,
    CityGasInputs,
    DownstreamRefiningInputs,
    OilGasValuationResult,
    UpstreamReserveInputs,
    compute_city_gas_value,
    compute_downstream_ev_ebitda,
    compute_integrated_sotp,
    compute_upstream_reserves_npv,
    is_oil_gas_applicable,
    select_method_for_ticker,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# compute_upstream_reserves_npv
# ─────────────────────────────────────────────────────────────────

def test_upstream_ongc_shape_npv_in_major_eup_band():
    """ONGC-shape inputs produce an NPV in the major-E&P band.

    With 5500 MMBOE proved reserves, 250 MMBOE/yr production, $70/bbl
    realized price, $25 opex, 20% royalty + 20% cess + 25% income tax,
    12% discount and a 15-year horizon plus terminal residual, the
    NPV lands in the major-E&P band (≥ ₹1.5 lakh crore — i.e. ₹150k
    crore). The exact figure depends on the depletion curve modeling
    (5%/yr exponential decline) and the terminal-residual treatment.
    """
    inputs = UpstreamReserveInputs(
        proved_reserves_mmboe=5500.0,
        probable_reserves_mmboe=0.0,
        annual_production_mmboe=250.0,
        realized_price_usd_per_boe=70.0,
        operating_cost_usd_per_boe=25.0,
        royalty_pct=20.0,
        cess_pct=20.0,
        income_tax_pct=25.0,
        discount_rate=0.12,
        usd_to_inr=83.0,
    )
    out = compute_upstream_reserves_npv(inputs)

    # NPV should be in the major-E&P band — at least ₹1.5 lakh cr,
    # and not absurdly above ₹10 lakh cr.
    assert out["npv_inr_cr"] >= 150_000, (
        f"NPV {out['npv_inr_cr']:,.0f} below major-E&P floor"
    )
    assert out["npv_inr_cr"] <= 1_000_000, (
        f"NPV {out['npv_inr_cr']:,.0f} above plausibility cap"
    )
    # Net cash flow per BOE: 70 - 25 - 14 (20% royalty) - 14 (20% cess)
    # = 17 pre-tax; 17 * 0.75 = 12.75 USD/BOE.
    assert out["net_cf_per_boe_usd"] == pytest.approx(12.75, abs=0.01)
    # Reserves life: 5500 / 250 = 22 years.
    assert out["reserves_life_years"] == pytest.approx(22.0, abs=0.01)
    # No sanity warnings (life is within the 5-30y band).
    assert out["sanity_warnings"] == []


def test_upstream_probable_reserves_weighted_at_fifty_pct():
    """Probable reserves contribute at 50% probability weight."""
    proved_only = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=5000.0,
            probable_reserves_mmboe=0.0,
            annual_production_mmboe=250.0,
        )
    )
    with_probable = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=5000.0,
            probable_reserves_mmboe=2000.0,  # → +1000 risked
            annual_production_mmboe=250.0,
        )
    )
    # Risked reserves: 5000 vs 5000 + 0.5*2000 = 6000.
    assert proved_only["risked_reserves_mmboe"] == pytest.approx(5000.0)
    assert with_probable["risked_reserves_mmboe"] == pytest.approx(6000.0)
    # More reserves → more NPV (longer life + larger terminal).
    assert with_probable["npv_inr_cr"] > proved_only["npv_inr_cr"]


def test_upstream_reserves_life_warning_near_term_depletion():
    """Reserves life < 5y fires the near-term depletion warning."""
    out = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=600.0,        # life ≈ 2.4y
            probable_reserves_mmboe=0.0,
            annual_production_mmboe=250.0,
        )
    )
    assert any(
        "near-term depletion" in w for w in out["sanity_warnings"]
    ), out["sanity_warnings"]


def test_upstream_reserves_life_warning_ultra_long_tail():
    """Reserves life > 30y fires the ultra-long-tail warning."""
    out = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=15000.0,      # life = 60y
            probable_reserves_mmboe=0.0,
            annual_production_mmboe=250.0,
        )
    )
    assert any(
        "ultra-long tail" in w for w in out["sanity_warnings"]
    ), out["sanity_warnings"]


def test_upstream_non_positive_reserves_short_circuits():
    """Zero reserves → npv=0 with a sanity warning, no crash."""
    out = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=0.0,
            probable_reserves_mmboe=0.0,
            annual_production_mmboe=250.0,
        )
    )
    assert out["npv_inr_cr"] == 0.0
    assert out["year_by_year_cashflows"] == []
    assert any(
        "non-positive reserves" in w for w in out["sanity_warnings"]
    )


def test_upstream_depletion_compounds_year_over_year():
    """Year-2 production should be < year-1 due to 5%/yr decline."""
    out = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=5500.0,
            annual_production_mmboe=250.0,
        ),
        horizon_years=5,
        depletion_per_year=0.05,
    )
    cashflows = out["year_by_year_cashflows"]
    assert len(cashflows) == 5
    # Production declines monotonically.
    productions = [cf[1] for cf in cashflows]
    assert productions[0] > productions[1] > productions[2] > productions[3]


def test_upstream_terminal_residual_nonneg_for_normal_inputs():
    """Terminal residual is non-negative for any positive-spread input."""
    out = compute_upstream_reserves_npv(
        UpstreamReserveInputs(
            proved_reserves_mmboe=5500.0,
            annual_production_mmboe=250.0,
        )
    )
    assert out["terminal_residual"] >= 0.0


# ─────────────────────────────────────────────────────────────────
# compute_downstream_ev_ebitda
# ─────────────────────────────────────────────────────────────────

def test_downstream_ioc_shape_ev_mid_cycle():
    """IOC-shape inputs produce a mid-cycle refining EV."""
    out = compute_downstream_ev_ebitda(
        DownstreamRefiningInputs(
            refining_throughput_mmt=80.0,
            gross_refining_margin_usd_per_bbl=8.0,
            capacity_utilization_pct=95.0,
            ev_ebitda_multiple=6.5,
            net_debt_inr_cr=0.0,
            usd_to_inr=83.0,
        )
    )
    # EBITDA = 80 * 0.95 * 7.33 * 8 * 83 / 10 ≈ ₹37k cr
    # EV = 37k * 6.5 ≈ ₹240k cr
    assert out["ebitda_inr_cr"] == pytest.approx(36_990.0, rel=0.01)
    assert out["ev_inr_cr"] == pytest.approx(240_436.0, rel=0.01)
    assert out["equity_value_inr_cr"] == out["ev_inr_cr"]
    assert out["sanity_warnings"] == []


def test_downstream_stressed_grm_warning():
    """GRM < $4/bbl fires the stressed refining cycle warning."""
    out = compute_downstream_ev_ebitda(
        DownstreamRefiningInputs(
            refining_throughput_mmt=80.0,
            gross_refining_margin_usd_per_bbl=3.0,
        )
    )
    assert any(
        "stressed refining cycle" in w for w in out["sanity_warnings"]
    )


def test_downstream_peak_grm_warning():
    """GRM > $15/bbl fires the peak cycle warning."""
    out = compute_downstream_ev_ebitda(
        DownstreamRefiningInputs(
            refining_throughput_mmt=80.0,
            gross_refining_margin_usd_per_bbl=18.0,
        )
    )
    assert any(
        "peak cycle" in w for w in out["sanity_warnings"]
    )


def test_downstream_negative_equity_distress_warning():
    """Net debt > EV fires the distress warning."""
    out = compute_downstream_ev_ebitda(
        DownstreamRefiningInputs(
            refining_throughput_mmt=10.0,
            gross_refining_margin_usd_per_bbl=8.0,
            net_debt_inr_cr=100_000.0,         # huge debt swamps EV
        )
    )
    assert out["equity_value_inr_cr"] < 0
    assert any(
        "distress" in w for w in out["sanity_warnings"]
    )


def test_downstream_zero_throughput_short_circuits():
    """Zero throughput → ev=0 with a sanity warning."""
    out = compute_downstream_ev_ebitda(
        DownstreamRefiningInputs(
            refining_throughput_mmt=0.0,
        )
    )
    assert out["ev_inr_cr"] == 0.0
    assert any(
        "non-positive throughput" in w for w in out["sanity_warnings"]
    )


# ─────────────────────────────────────────────────────────────────
# compute_city_gas_value
# ─────────────────────────────────────────────────────────────────

def test_city_gas_igl_shape_value():
    """IGL-shape inputs produce the expected city-gas EV."""
    out = compute_city_gas_value(
        CityGasInputs(
            cng_volume_mmscm_per_day=4.0,
            png_volume_mmscm_per_day=2.5,
            ebitda_per_unit_inr_per_scm=6.5,
            ebitda_multiple=14.0,
            net_debt_inr_cr=0.0,
        )
    )
    # Annual EBITDA = (4 + 2.5) * 365 * 6.5 / 10 ≈ ₹1,542 cr
    # EV = 1,542 * 14 ≈ ₹21,591 cr
    assert out["annual_ebitda_inr_cr"] == pytest.approx(1_542.25, rel=0.01)
    assert out["ev_inr_cr"] == pytest.approx(21_591.5, rel=0.01)
    assert out["equity_value_inr_cr"] == out["ev_inr_cr"]
    assert out["total_volume_mmscm_per_day"] == 6.5


def test_city_gas_zero_volume_short_circuits():
    """Zero volume → ev=0 + warning."""
    out = compute_city_gas_value(
        CityGasInputs(
            cng_volume_mmscm_per_day=0.0,
            png_volume_mmscm_per_day=0.0,
        )
    )
    assert out["ev_inr_cr"] == 0.0
    assert any(
        "non-positive volume" in w for w in out["sanity_warnings"]
    )


def test_city_gas_net_debt_subtracts():
    """Net debt subtracts from EV to yield equity value."""
    out = compute_city_gas_value(
        CityGasInputs(
            cng_volume_mmscm_per_day=4.0,
            png_volume_mmscm_per_day=2.5,
            ebitda_per_unit_inr_per_scm=6.5,
            ebitda_multiple=14.0,
            net_debt_inr_cr=2_000.0,
        )
    )
    assert out["equity_value_inr_cr"] == pytest.approx(
        out["ev_inr_cr"] - 2_000.0, rel=1e-6
    )


# ─────────────────────────────────────────────────────────────────
# compute_integrated_sotp
# ─────────────────────────────────────────────────────────────────

def test_integrated_sotp_reliance_shape():
    """RELIANCE-shape: upstream + downstream + petrochem + retail."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=50_000.0,
        downstream_value_inr_cr=400_000.0,
        petrochem_value_inr_cr=300_000.0,
        other_value_inr_cr=600_000.0,        # retail + telecom
        net_debt_inr_cr=200_000.0,
        shares_outstanding=676_94_15_000.0,  # ~676.94 cr shares
    )
    # Aggregate gross = 1,350,000 cr; equity = 1,150,000 cr
    assert result.aggregate_value_inr_cr == pytest.approx(
        1_150_000.0, rel=1e-6
    )
    assert result.method == "integrated_sotp"
    assert result.fair_value_per_share is not None
    # FV = 1,150,000 cr * 1e7 INR/cr / 676.94 cr shares ≈ ₹1,699 / share
    assert result.fair_value_per_share == pytest.approx(1_698.97, rel=0.01)
    # Components dict carries every input back.
    assert result.components["upstream"] == 50_000.0
    assert result.components["downstream"] == 400_000.0
    assert result.components["petrochem"] == 300_000.0
    assert result.components["other"] == 600_000.0
    assert result.components["net_debt"] == 200_000.0


def test_integrated_sotp_skips_missing_components():
    """Missing component (None) is skipped, not treated as zero."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=50_000.0,
        downstream_value_inr_cr=400_000.0,
        petrochem_value_inr_cr=None,
        other_value_inr_cr=None,
        net_debt_inr_cr=100_000.0,
        shares_outstanding=100_00_00_000.0,
    )
    # Aggregate = 450,000; equity = 350,000.
    assert result.aggregate_value_inr_cr == pytest.approx(
        350_000.0, rel=1e-6
    )
    assert result.components["petrochem"] is None
    assert result.components["other"] is None
    assert result.method == "integrated_sotp"


def test_integrated_sotp_all_none_unavailable():
    """All components None → method=unavailable."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=None,
        downstream_value_inr_cr=None,
    )
    assert result.method == "unavailable"
    assert result.fair_value_per_share is None
    assert result.aggregate_value_inr_cr is None
    assert any(
        "no segment values" in w for w in result.sanity_warnings
    )


def test_integrated_sotp_zero_shares_no_per_share():
    """Zero shares → fv_per_share=None + warning."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=100_000.0,
        downstream_value_inr_cr=100_000.0,
        shares_outstanding=0.0,
    )
    assert result.fair_value_per_share is None
    assert result.aggregate_value_inr_cr == pytest.approx(200_000.0)
    assert any(
        "shares_outstanding not supplied" in w for w in result.sanity_warnings
    )


def test_integrated_sotp_negative_equity_distress():
    """Net debt > aggregate → distress warning."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=10_000.0,
        downstream_value_inr_cr=10_000.0,
        net_debt_inr_cr=100_000.0,
        shares_outstanding=100_00_00_000.0,
    )
    assert result.aggregate_value_inr_cr < 0
    assert any(
        "distress" in w for w in result.sanity_warnings
    )
    # Per-share FV stays None when equity is negative.
    assert result.fair_value_per_share is None


# ─────────────────────────────────────────────────────────────────
# select_method_for_ticker
# ─────────────────────────────────────────────────────────────────

def test_select_method_for_every_registered_ticker():
    """Every entry in OIL_GAS_TICKERS routes correctly."""
    for ticker, expected_segment in OIL_GAS_TICKERS.items():
        assert select_method_for_ticker(ticker) == expected_segment, (
            f"{ticker} did not route to {expected_segment}"
        )


def test_select_method_handles_ns_suffix():
    """`.NS` suffix is stripped before lookup."""
    assert select_method_for_ticker("ONGC.NS") == "upstream"
    assert select_method_for_ticker("RELIANCE.NS") == "integrated"
    assert select_method_for_ticker("IGL.BO") == "city_gas"


def test_select_method_unknown_ticker_returns_none():
    """Unknown ticker → None."""
    assert select_method_for_ticker("HDFCBANK") is None
    assert select_method_for_ticker("TCS") is None
    assert select_method_for_ticker("") is None


# ─────────────────────────────────────────────────────────────────
# is_oil_gas_applicable
# ─────────────────────────────────────────────────────────────────

def test_is_applicable_ongc_true():
    """ONGC → True (in OIL_GAS_TICKERS)."""
    applicable, reason = is_oil_gas_applicable("ONGC", None)
    assert applicable is True
    assert "OIL_GAS_TICKERS" in reason


def test_is_applicable_hdfcbank_false():
    """HDFCBANK → False (not in registry, sector unrelated)."""
    applicable, reason = is_oil_gas_applicable(
        "HDFCBANK", "Banking and Financial Services"
    )
    assert applicable is False


def test_is_applicable_sector_hint_matches():
    """Sector hint 'Oil & Gas' → True for unknown ticker."""
    applicable, reason = is_oil_gas_applicable("UNKNOWNCO", "Oil & Gas")
    assert applicable is True
    assert "oil-gas hint" in reason

    # Other valid hints
    applicable_a, _ = is_oil_gas_applicable("X", "Petroleum products")
    assert applicable_a is True
    applicable_b, _ = is_oil_gas_applicable("Y", "City Gas Distribution")
    assert applicable_b is True


def test_is_applicable_no_sector_no_match_false():
    """None sector + unknown ticker → False."""
    applicable, reason = is_oil_gas_applicable("UNKNOWNCO", None)
    assert applicable is False
    assert "no sector hint" in reason


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────

def test_to_dict_contains_required_keys_and_serializable():
    """to_dict shape carries all 5 keys, fully JSON-serializable."""
    result = compute_integrated_sotp(
        upstream_value_inr_cr=50_000.0,
        downstream_value_inr_cr=400_000.0,
        net_debt_inr_cr=100_000.0,
        shares_outstanding=100_00_00_000.0,
    )
    payload = to_dict(result)
    expected_keys = {
        "fair_value_per_share",
        "aggregate_value_inr_cr",
        "components",
        "method",
        "sanity_warnings",
    }
    assert set(payload.keys()) == expected_keys
    # Round-trip through JSON to prove primitives only.
    json.dumps(payload)


def test_to_dict_shallow_copy_isolation():
    """Mutating the returned dict does not pollute the source result."""
    result = OilGasValuationResult(
        fair_value_per_share=100.0,
        aggregate_value_inr_cr=50_000.0,
        components={"upstream": 50_000.0},
        method="integrated_sotp",
        sanity_warnings=["warn-1"],
    )
    payload = to_dict(result)
    payload["components"]["upstream"] = 999.0
    payload["sanity_warnings"].append("new-warn")
    # Source unchanged.
    assert result.components["upstream"] == 50_000.0
    assert result.sanity_warnings == ["warn-1"]
