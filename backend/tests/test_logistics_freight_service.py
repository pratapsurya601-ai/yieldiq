# backend/tests/test_logistics_freight_service.py
# =====================================================================
# Tests for backend/services/logistics_freight_service.py (T3.15 Phase A).
#
# Coverage map (top-to-bottom — each test reads independently, no shared
# fixtures so a failure points at one concern):
#
#   compute_logistics_fv
#     - BLUEDART-shape (road express): 500k MT, Rs 15/kg, 14% margin,
#       70% utilization, 16x multiple -> per-share FV positive
#     - CONCOR-shape (container rail): 4M TEUs, Rs 30k/TEU, 22%
#       margin, container_rail multiple 15x -> moat-premium FV
#     - SCI-shape (container shipping): commoditized cycle, low
#       multiple 7x -> FV reflects no pricing power
#     - MAHLOG-shape (3PL): asset-light, premium 18x multiple
#     - GESHIP-shape (tanker shipping): commoditized 6x
#
#   classify_cost_pressure
#     - diesel > 25% -> "diesel_squeeze"
#     - driver > 14% -> "labor_pressure"
#     - both within band -> "normal"
#     - diesel takes precedence over labor when both fire
#
#   Defensive guards
#     - zero volume -> method "unavailable", FV None
#     - zero revenue/unit -> "unavailable"
#     - zero / negative margin -> "unavailable"
#     - zero multiple -> "unavailable"
#     - zero shares -> FV None with warning
#     - net debt > EV -> distress warning
#
#   Sanity warnings
#     - low utilization (<55%) fires breakeven warning
#     - high utilization (>90%) fires stretched warning
#     - low margin (<5%) fires trough warning
#     - high margin (>35%) fires peak warning
#     - multiple far from segment reference fires band warning
#
#   is_logistics_applicable
#     - every entry in LOGISTICS_TICKERS routes True
#     - GOFASHION explicitly False (apparel retail)
#     - HDFCBANK False (not logistics)
#     - sector hint "Logistics" -> True for unknown ticker
#     - None sector + unknown ticker -> False
#     - .NS suffix handled
#
#   to_dict
#     - shape contains all required keys + JSON-serialisable values
# =====================================================================
from __future__ import annotations

import json

import pytest

from backend.services.logistics_freight_service import (
    LOGISTICS_TICKERS,
    SEGMENT_MULTIPLES,
    LogisticsInputs,
    LogisticsResult,
    classify_cost_pressure,
    compute_logistics_fv,
    is_logistics_applicable,
    to_dict,
)


# -----------------------------------------------------------------
# compute_logistics_fv — segment-shape fixtures
# -----------------------------------------------------------------

def test_bluedart_road_express_shape_yields_positive_fv():
    """BLUEDART-shape inputs (road express premium courier).

    500k MT annual volume, Rs 15/kg revenue, 14% operating margin,
    70% fleet utilization, 16x road_express multiple. Reasonable
    net debt for a fleet operator (Rs 200 cr), 23.7 cr shares.
    Should produce a positive per-share FV and the
    operating_leverage_ratio should land at exactly 1.0 (70/70).
    """
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,         # 0.5 million MT = 500k MT
        revenue_per_unit_inr=15000.0,  # Rs 15/kg = Rs 15,000/MT
        operating_margin_pct=14.0,
        fleet_utilization_pct=70.0,
        diesel_cost_pct_of_revenue=22.0,
        driver_cost_pct_of_revenue=12.0,
        ev_ebitda_multiple=16.0,
        net_debt_inr_cr=200.0,
        shares_outstanding=23_700_000.0,  # 2.37 cr shares
        segment="road_express",
    )
    out = compute_logistics_fv(inputs)

    assert out.method == "logistics_freight_volume_yield"
    assert out.fair_value_per_share is not None
    assert out.fair_value_per_share > 0
    # Revenue = 0.5 * 15000 / 10 = 750 cr
    assert out.revenue_inr_cr == pytest.approx(750.0, rel=0.01)
    # EBITDA = 750 * 0.14 = 105 cr
    assert out.ebitda_inr_cr == pytest.approx(105.0, rel=0.01)
    # OpLev = 70/70 = 1.0
    assert out.operating_leverage_ratio == pytest.approx(1.0, abs=0.001)
    # Cost pressure: 22% diesel + 12% driver -> normal
    assert out.cost_pressure_label == "normal"
    # No sanity warnings expected — every input is within band
    assert out.sanity_warnings == []


def test_concor_container_rail_shape_uses_premium_multiple():
    """CONCOR-shape inputs (container rail moat).

    4 million TEU annual throughput, Rs 30,000/TEU realization, 22%
    operating margin (high — IR franchise economics), 75%
    utilization, 15x container_rail multiple. Container rail has
    near-zero diesel (electric traction) so cost_pressure should be
    "normal".
    """
    inputs = LogisticsInputs(
        annual_volume_mt=4.0,           # 4 million TEU
        revenue_per_unit_inr=30000.0,    # Rs 30k/TEU
        operating_margin_pct=22.0,
        fleet_utilization_pct=75.0,
        diesel_cost_pct_of_revenue=0.5,  # near-zero (electric)
        driver_cost_pct_of_revenue=8.0,
        ev_ebitda_multiple=15.0,
        net_debt_inr_cr=-2000.0,         # net cash (CONCOR is debt-free)
        shares_outstanding=609_000_000.0,  # 60.9 cr shares
        segment="container_rail",
    )
    out = compute_logistics_fv(inputs)

    assert out.method == "logistics_freight_volume_yield"
    assert out.fair_value_per_share is not None
    # Revenue = 4 * 30000 / 10 = 12000 cr
    assert out.revenue_inr_cr == pytest.approx(12_000.0, rel=0.01)
    # EBITDA = 12000 * 0.22 = 2640 cr
    assert out.ebitda_inr_cr == pytest.approx(2640.0, rel=0.01)
    # EV = 2640 * 15 = 39600 cr; equity = EV - (-2000) = 41600 cr
    # FV/share = 41600 * 1e7 / 60.9e7 = ~683
    assert out.fair_value_per_share > 600
    assert out.cost_pressure_label == "normal"
    assert out.operating_leverage_ratio > 1.0  # 75/70 = 1.07


def test_sci_container_shipping_shape_uses_low_multiple():
    """SCI-shape (container shipping commoditized).

    Container shipping has no pricing power — multiple 7x reflects
    cycle whipsaw. 1.5 million tonnes throughput at Rs 8,000/MT,
    8% margin (mid-cycle), 65% utilization.
    """
    inputs = LogisticsInputs(
        annual_volume_mt=1.5,
        revenue_per_unit_inr=8000.0,
        operating_margin_pct=8.0,
        fleet_utilization_pct=65.0,
        diesel_cost_pct_of_revenue=28.0,  # bunker oil heavy
        driver_cost_pct_of_revenue=6.0,
        ev_ebitda_multiple=7.0,
        net_debt_inr_cr=1500.0,
        shares_outstanding=465_000_000.0,
        segment="container_shipping",
    )
    out = compute_logistics_fv(inputs)

    assert out.method == "logistics_freight_volume_yield"
    # Revenue = 1.5 * 8000 / 10 = 1200 cr
    assert out.revenue_inr_cr == pytest.approx(1200.0, rel=0.01)
    # EBITDA = 1200 * 0.08 = 96 cr
    assert out.ebitda_inr_cr == pytest.approx(96.0, rel=0.01)
    # Diesel 28% > 25% -> squeeze
    assert out.cost_pressure_label == "diesel_squeeze"
    # Low multiple matches segment reference (7x vs 7x) -> no band warning
    # But diesel-squeeze warning will be present.
    assert any("diesel" in w.lower() for w in out.sanity_warnings)


def test_mahlog_3pl_asset_light_shape_premium_multiple():
    """MAHLOG-shape (3PL asset-light, premium multiple).

    18x reflects the customer-stickiness + software-margin layer
    that asset-light 3PL operators print. 1.2 million tonnes
    handled, Rs 22,000/MT, 11% margin (asset-light typically
    higher than gross road), 80% utilization.
    """
    inputs = LogisticsInputs(
        annual_volume_mt=1.2,
        revenue_per_unit_inr=22000.0,
        operating_margin_pct=11.0,
        fleet_utilization_pct=80.0,
        diesel_cost_pct_of_revenue=18.0,
        driver_cost_pct_of_revenue=10.0,
        ev_ebitda_multiple=18.0,
        net_debt_inr_cr=400.0,
        shares_outstanding=70_000_000.0,  # 7 cr shares
        segment="3pl_supply_chain",
    )
    out = compute_logistics_fv(inputs)

    assert out.method == "logistics_freight_volume_yield"
    assert out.fair_value_per_share is not None
    # OpLev = 80/70 ~ 1.143
    assert out.operating_leverage_ratio == pytest.approx(1.143, abs=0.01)
    assert out.cost_pressure_label == "normal"


def test_geship_tanker_shipping_shape_uses_lowest_multiple():
    """GESHIP-shape (tanker shipping, commoditized).

    Tanker shipping carries the lowest multiple (6x) — pure
    commodity exposure to crude / product tanker rates. 2 MT,
    Rs 6,500/MT, 12% margin (mid-cycle), 70% utilization.
    """
    inputs = LogisticsInputs(
        annual_volume_mt=2.0,
        revenue_per_unit_inr=6500.0,
        operating_margin_pct=12.0,
        fleet_utilization_pct=70.0,
        diesel_cost_pct_of_revenue=24.0,
        driver_cost_pct_of_revenue=7.0,
        ev_ebitda_multiple=6.0,
        net_debt_inr_cr=800.0,
        shares_outstanding=142_000_000.0,
        segment="tanker_shipping",
    )
    out = compute_logistics_fv(inputs)

    assert out.method == "logistics_freight_volume_yield"
    # Revenue = 2 * 6500 / 10 = 1300 cr
    assert out.revenue_inr_cr == pytest.approx(1300.0, rel=0.01)
    # EBITDA = 1300 * 0.12 = 156 cr
    assert out.ebitda_inr_cr == pytest.approx(156.0, rel=0.01)


# -----------------------------------------------------------------
# classify_cost_pressure
# -----------------------------------------------------------------

def test_classify_cost_pressure_diesel_squeeze_fires_above_25_pct():
    """Diesel > 25% of revenue -> 'diesel_squeeze' label."""
    assert classify_cost_pressure(26.0, 10.0) == "diesel_squeeze"
    assert classify_cost_pressure(25.5, 0.0) == "diesel_squeeze"


def test_classify_cost_pressure_labor_pressure_fires_above_14_pct():
    """Driver > 14% of revenue and diesel <=25% -> 'labor_pressure'."""
    assert classify_cost_pressure(20.0, 15.0) == "labor_pressure"
    assert classify_cost_pressure(0.0, 14.5) == "labor_pressure"


def test_classify_cost_pressure_normal_when_both_within_band():
    """Both lines within their analyst-watch thresholds -> 'normal'."""
    assert classify_cost_pressure(22.0, 12.0) == "normal"
    assert classify_cost_pressure(0.0, 0.0) == "normal"
    # Right at the boundary (not strictly above) -> still normal.
    assert classify_cost_pressure(25.0, 14.0) == "normal"


def test_classify_cost_pressure_diesel_takes_precedence_over_labor():
    """When BOTH lines breach, diesel-squeeze is reported first.

    Diesel is shorter-cycle (weeks to recover via fuel surcharges);
    labor is structural. Sell-side analysts flag the diesel chip
    first.
    """
    assert classify_cost_pressure(30.0, 20.0) == "diesel_squeeze"


# -----------------------------------------------------------------
# Defensive guards
# -----------------------------------------------------------------

def test_zero_volume_returns_unavailable_with_no_fv():
    """Zero annual volume -> method 'unavailable', FV None."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.0,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "unavailable"
    assert out.fair_value_per_share is None
    assert out.cost_pressure_label == "unavailable"
    assert any("volume" in w.lower() for w in out.sanity_warnings)


def test_zero_revenue_per_unit_returns_unavailable():
    """Zero revenue/unit -> method 'unavailable'."""
    inputs = LogisticsInputs(
        annual_volume_mt=1.0,
        revenue_per_unit_inr=0.0,
        operating_margin_pct=14.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "unavailable"
    assert out.fair_value_per_share is None


def test_zero_margin_returns_unavailable():
    """Zero or negative operating margin -> method 'unavailable'."""
    inputs = LogisticsInputs(
        annual_volume_mt=1.0,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=0.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "unavailable"


def test_zero_multiple_returns_unavailable():
    """Zero EV/EBITDA multiple -> method 'unavailable'."""
    inputs = LogisticsInputs(
        annual_volume_mt=1.0,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
        ev_ebitda_multiple=0.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "unavailable"


def test_zero_shares_outstanding_yields_no_per_share_fv():
    """Zero shares -> FV/share None but method still computes."""
    inputs = LogisticsInputs(
        annual_volume_mt=1.0,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
        ev_ebitda_multiple=14.0,
        shares_outstanding=0.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "logistics_freight_volume_yield"
    assert out.fair_value_per_share is None
    assert any(
        "shares_outstanding" in w for w in out.sanity_warnings
    )
    # Revenue / EBITDA still populated for downstream consumers.
    assert out.revenue_inr_cr > 0


def test_net_debt_exceeds_ev_fires_distress_warning():
    """Net debt > enterprise value -> negative equity, distress warn."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.1,
        revenue_per_unit_inr=10000.0,
        operating_margin_pct=8.0,
        ev_ebitda_multiple=10.0,
        net_debt_inr_cr=200.0,   # blows past any EV from these tiny inputs
        shares_outstanding=10_000_000.0,
    )
    out = compute_logistics_fv(inputs)
    assert out.method == "logistics_freight_volume_yield"
    assert any("distress" in w.lower() for w in out.sanity_warnings)
    # FV per share suppressed because equity is negative.
    assert out.fair_value_per_share is None


# -----------------------------------------------------------------
# Sanity warnings
# -----------------------------------------------------------------

def test_low_utilization_fires_breakeven_warning():
    """Utilization < 55% fires the breakeven warning."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=10.0,
        fleet_utilization_pct=45.0,
        ev_ebitda_multiple=16.0,
    )
    out = compute_logistics_fv(inputs)
    assert any(
        "utilization" in w.lower() and "breakeven" in w.lower()
        for w in out.sanity_warnings
    )


def test_high_utilization_fires_stretched_warning():
    """Utilization > 90% fires the stretched warning."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
        fleet_utilization_pct=95.0,
        ev_ebitda_multiple=16.0,
    )
    out = compute_logistics_fv(inputs)
    assert any(
        "stretched" in w.lower() for w in out.sanity_warnings
    )


def test_low_margin_fires_trough_warning():
    """Margin < 5% fires the trough warning."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=3.0,
        ev_ebitda_multiple=16.0,
    )
    out = compute_logistics_fv(inputs)
    assert any("trough" in w.lower() for w in out.sanity_warnings)


def test_high_margin_fires_peak_warning():
    """Margin > 35% fires the peak warning."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=40.0,
        ev_ebitda_multiple=16.0,
    )
    out = compute_logistics_fv(inputs)
    assert any("peak" in w.lower() for w in out.sanity_warnings)


def test_multiple_far_from_segment_reference_fires_band_warning():
    """EV/EBITDA multiple outside +/-25% of segment ref fires warning."""
    # road_express ref = 16.0; 25x is far above.
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
        ev_ebitda_multiple=25.0,
        segment="road_express",
    )
    out = compute_logistics_fv(inputs)
    assert any(
        "outside" in w.lower() and "band" in w.lower()
        for w in out.sanity_warnings
    )


# -----------------------------------------------------------------
# is_logistics_applicable
# -----------------------------------------------------------------

@pytest.mark.parametrize("ticker", list(LOGISTICS_TICKERS.keys()))
def test_every_registered_logistics_ticker_routes_true(ticker):
    """Every bare ticker in the registry routes through this engine."""
    applicable, reason = is_logistics_applicable(ticker, None)
    assert applicable is True
    assert "LOGISTICS_TICKERS" in reason


def test_gofashion_explicitly_excluded_as_apparel_retail():
    """GOFASHION is apparel retail and must NOT route through here."""
    applicable, reason = is_logistics_applicable(
        "GOFASHION", "Apparel & Accessories"
    )
    assert applicable is False
    assert "apparel" in reason.lower() or "not logistics" in reason.lower()


def test_unknown_ticker_with_logistics_sector_hint_routes_true():
    """Unknown ticker + a logistics-flavored sector string -> True."""
    applicable, reason = is_logistics_applicable(
        "SOMENEWCO", "Logistics & Transportation"
    )
    assert applicable is True
    assert "logistic" in reason.lower()


def test_unknown_ticker_with_freight_sector_hint_routes_true():
    """Sector hint 'freight' is one of the matched substrings."""
    applicable, reason = is_logistics_applicable(
        "SOMECO", "Freight Forwarding"
    )
    assert applicable is True


def test_hdfcbank_does_not_route_through_logistics_engine():
    """Bank ticker + bank sector -> not applicable."""
    applicable, reason = is_logistics_applicable(
        "HDFCBANK", "Private Sector Bank"
    )
    assert applicable is False


def test_unknown_ticker_no_sector_returns_false():
    """No registry hit + no sector hint -> not applicable."""
    applicable, reason = is_logistics_applicable("RANDOMCO", None)
    assert applicable is False


def test_ns_suffix_handled_for_registered_tickers():
    """.NS suffix should not break the registry match."""
    applicable, reason = is_logistics_applicable("BLUEDART.NS", None)
    assert applicable is True


# -----------------------------------------------------------------
# to_dict
# -----------------------------------------------------------------

def test_to_dict_emits_json_serialisable_payload_with_required_keys():
    """``to_dict`` produces a JSON-safe dict carrying every output."""
    inputs = LogisticsInputs(
        annual_volume_mt=0.5,
        revenue_per_unit_inr=15000.0,
        operating_margin_pct=14.0,
        ev_ebitda_multiple=16.0,
        shares_outstanding=23_700_000.0,
    )
    out = compute_logistics_fv(inputs)
    payload = to_dict(out)

    # Required keys present.
    required = {
        "fair_value_per_share",
        "revenue_inr_cr",
        "ebitda_inr_cr",
        "operating_leverage_ratio",
        "components",
        "cost_pressure_label",
        "method",
        "sanity_warnings",
    }
    assert required.issubset(set(payload.keys()))

    # JSON round-trip — fails if any non-primitive leaked in.
    serialized = json.dumps(payload)
    rehydrated = json.loads(serialized)
    assert rehydrated["method"] == "logistics_freight_volume_yield"
    assert isinstance(rehydrated["components"], dict)
    assert isinstance(rehydrated["sanity_warnings"], list)


def test_to_dict_components_is_shallow_copy_not_alias():
    """Mutating the returned dict must not poison the source result."""
    inputs = LogisticsInputs(
        annual_volume_mt=1.0,
        revenue_per_unit_inr=10000.0,
        operating_margin_pct=10.0,
    )
    out = compute_logistics_fv(inputs)
    payload = to_dict(out)
    payload["components"]["__sentinel__"] = "polluted"
    assert "__sentinel__" not in out.components


# -----------------------------------------------------------------
# Segment registry self-consistency
# -----------------------------------------------------------------

def test_every_registered_segment_has_a_multiple_anchor():
    """Every segment used by a ticker has an entry in SEGMENT_MULTIPLES."""
    for segment in LOGISTICS_TICKERS.values():
        assert segment in SEGMENT_MULTIPLES, (
            f"segment {segment} has no SEGMENT_MULTIPLES anchor"
        )


def test_concor_uses_container_rail_segment_premium():
    """CONCOR is the only container-rail ticker and must use that segment."""
    assert LOGISTICS_TICKERS["CONCOR"] == "container_rail"
    # Premium multiple anchor (15x) reflects moat.
    assert SEGMENT_MULTIPLES["container_rail"] >= 14.0


def test_shipping_segments_carry_lower_multiples_than_road():
    """Container/tanker shipping are commoditized — lower multiples."""
    assert (
        SEGMENT_MULTIPLES["container_shipping"]
        < SEGMENT_MULTIPLES["road_express"]
    )
    assert (
        SEGMENT_MULTIPLES["tanker_shipping"]
        < SEGMENT_MULTIPLES["road_express"]
    )
