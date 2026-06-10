# backend/tests/test_it_services_overlay_service.py
"""Unit tests for the IT services overlay (T3.6 Phase A)."""
from __future__ import annotations

import math

import pytest

from backend.services.it_services_overlay_service import (
    IT_TICKERS,
    ITServicesOverlayInputs,
    ITServicesOverlayResult,
    compute_concentration_discount,
    compute_growth_quality_premium,
    compute_it_overlay,
    compute_sbc_overlay_discount,
    is_it_overlay_applicable,
    to_dict,
)


# ──────────────────────────────────────────────────────────────────
# Headline ticker-shape scenarios from the brief
# ──────────────────────────────────────────────────────────────────
class TestHeadlineScenarios:
    def test_tcs_shape_small_premium(self) -> None:
        """TCS: top_5=12%, BFSI=35%, USD=55%, SBC=1.5%, rev>headcount → ~1.02x."""
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=4000.0,
            top_5_client_concentration_pct=12.0,
            bfsi_revenue_share_pct=34.0,  # just under the 35% diversified gate
            usd_revenue_share_pct=55.0,
            sbc_pct_of_fcf=1.5,
            headcount_growth_pct=2.0,
            revenue_growth_3y_cagr_pct=9.0,
            operating_margin_pct=25.0,
            tier="tier_1",
        ))
        assert result.adjusted_fv is not None
        # Tier-1 diversified (+2%) + growth quality (+3% from 7pp spread) = 1.02 * 1.03 = 1.0506.
        # SBC at norm = 1.0.
        ratio = result.adjusted_fv / result.base_dcf_fv
        assert 1.02 <= ratio <= 1.06
        assert result.sanity_warnings == []
        assert result.adjustments["tier"] == "tier_1"

    def test_wipro_shape_small_discount(self) -> None:
        """WIPRO: top_5=17%, weak margins, headcount growing fast → small discount."""
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=250.0,
            top_5_client_concentration_pct=17.0,
            bfsi_revenue_share_pct=36.0,  # just over the 35% diversified gate (no premium)
            usd_revenue_share_pct=55.0,
            sbc_pct_of_fcf=2.0,
            headcount_growth_pct=8.0,  # spread too narrow for premium
            revenue_growth_3y_cagr_pct=5.0,
            operating_margin_pct=16.0,  # margin compression → -3%
            tier="tier_1",
        ))
        assert result.adjusted_fv is not None
        ratio = result.adjusted_fv / result.base_dcf_fv
        # Concentration neutral (top_5<20 but BFSI>=35 so no premium); SBC neutral;
        # growth: spread=-3pp no premium, margin<18 → 0.97.
        assert 0.94 <= ratio <= 0.99

    def test_eclerx_specialist_concentration(self) -> None:
        """ECLERX-shape (specialist, concentrated): top_5=60% → -10% fires."""
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=2500.0,
            top_5_client_concentration_pct=60.0,
            bfsi_revenue_share_pct=45.0,
            usd_revenue_share_pct=70.0,
            sbc_pct_of_fcf=5.0,
            headcount_growth_pct=10.0,
            revenue_growth_3y_cagr_pct=12.0,
            operating_margin_pct=20.0,
            tier="specialist",
        ))
        assert result.adjusted_fv is not None
        ratio = result.adjusted_fv / result.base_dcf_fv
        # Concentration 0.90 (top_5>50) * 0.97 (BFSI+USD double exposure) = 0.873.
        # SBC at norm = 1.0; growth no premium (spread=2 below 5pp gate), margin healthy.
        assert ratio < 0.90
        assert result.adjustments["concentration_multiplier"] == pytest.approx(0.90 * 0.97)
        assert result.risk_summary in ("elevated", "high")

    def test_mphasis_bfsi_double_exposure(self) -> None:
        """MPHASIS-shape: BFSI=55%, USD=65% → -3% double-exposure fires."""
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=2800.0,
            top_5_client_concentration_pct=28.0,  # below 30% so no client-concentration penalty
            bfsi_revenue_share_pct=55.0,
            usd_revenue_share_pct=65.0,
            sbc_pct_of_fcf=3.0,
            headcount_growth_pct=4.0,
            revenue_growth_3y_cagr_pct=8.0,
            operating_margin_pct=20.0,
            tier="tier_2",
        ))
        assert result.adjusted_fv is not None
        assert result.adjustments["concentration_multiplier"] == pytest.approx(0.97)


# ──────────────────────────────────────────────────────────────────
# compute_concentration_discount — boundary cases
# ──────────────────────────────────────────────────────────────────
class TestConcentrationDiscount:
    def test_diversified_premium_fires(self) -> None:
        # top_5<20, bfsi<35 → +2%, no other adjustment.
        assert compute_concentration_discount(15.0, 30.0, 55.0) == pytest.approx(1.02)

    def test_at_20_pct_no_premium(self) -> None:
        # Boundary: top_5 < 20 strict — at 20 no premium.
        assert compute_concentration_discount(20.0, 30.0, 55.0) == pytest.approx(1.0)

    def test_at_30_pct_no_penalty(self) -> None:
        # Boundary: top_5 > 30 strict — at exactly 30 no penalty.
        assert compute_concentration_discount(30.0, 35.0, 55.0) == pytest.approx(1.0)

    def test_at_31_pct_penalty(self) -> None:
        # Just over 30 → -5% fires.
        assert compute_concentration_discount(31.0, 35.0, 55.0) == pytest.approx(0.95)

    def test_at_50_pct_no_existential(self) -> None:
        # Boundary: top_5 > 50 strict — at exactly 50 only -5% fires.
        assert compute_concentration_discount(50.0, 35.0, 55.0) == pytest.approx(0.95)

    def test_at_51_pct_existential(self) -> None:
        # Just over 50 → -10% supersedes -5%.
        assert compute_concentration_discount(51.0, 35.0, 55.0) == pytest.approx(0.90)

    def test_60_pct_with_double_exposure(self) -> None:
        # ECLERX shape: top_5=60% AND BFSI+USD double-exposure.
        result = compute_concentration_discount(60.0, 45.0, 65.0)
        assert result == pytest.approx(0.90 * 0.97)

    def test_floor_clamps_at_85(self) -> None:
        # No combination of rules should ever go below 0.85.
        result = compute_concentration_discount(99.0, 99.0, 99.0)
        assert result >= 0.85

    def test_ceil_clamps_at_105(self) -> None:
        result = compute_concentration_discount(0.0, 0.0, 0.0)
        assert result <= 1.05

    def test_non_finite_inputs_default_to_neutral(self) -> None:
        # NaN → neutral midpoint → 1.0 (no premium, no penalty).
        assert compute_concentration_discount(float("nan"), float("nan"), float("nan")) == pytest.approx(1.0)

    def test_none_inputs_default_to_neutral(self) -> None:
        assert compute_concentration_discount(None, None, None) == pytest.approx(1.0)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
# compute_sbc_overlay_discount — per-tier behavior
# ──────────────────────────────────────────────────────────────────
class TestSBCOverlayDiscount:
    def test_tier1_at_norm_no_discount(self) -> None:
        # Tier-1 norm=1.5%, gate=norm+2pp=3.5%. SBC=1.5% → no discount.
        assert compute_sbc_overlay_discount(1.5, "tier_1") == 1.0

    def test_tier1_below_gate_no_discount(self) -> None:
        # SBC=3% < 3.5% gate → no discount.
        assert compute_sbc_overlay_discount(3.0, "tier_1") == 1.0

    def test_tier1_just_over_gate_small_discount(self) -> None:
        # SBC=4% → excess=0.5pp → -0.75%.
        assert compute_sbc_overlay_discount(4.0, "tier_1") == pytest.approx(1.0 - 0.015 * 0.5)

    def test_tier1_heavy_sbc_floor(self) -> None:
        # SBC=50% → excess=46.5pp → would be very negative; floors at 0.92.
        assert compute_sbc_overlay_discount(50.0, "tier_1") == pytest.approx(0.92)

    def test_tier2_higher_tolerance(self) -> None:
        # Tier-2 norm=3.0%, gate=5.0%. SBC=4% → no discount (well below gate).
        assert compute_sbc_overlay_discount(4.0, "tier_2") == 1.0

    def test_specialist_highest_tolerance(self) -> None:
        # Specialist norm=5.0%, gate=7.0%. SBC=6% → no discount.
        assert compute_sbc_overlay_discount(6.0, "specialist") == 1.0
        # SBC=10% → excess=3pp → -4.5%.
        assert compute_sbc_overlay_discount(10.0, "specialist") == pytest.approx(1.0 - 0.015 * 3.0)

    def test_unknown_tier_neutral(self) -> None:
        assert compute_sbc_overlay_discount(50.0, "unknown_tier") == 1.0  # type: ignore[arg-type]

    def test_non_finite_sbc_neutral(self) -> None:
        assert compute_sbc_overlay_discount(float("nan"), "tier_1") == 1.0
        assert compute_sbc_overlay_discount(None, "tier_1") == 1.0  # type: ignore[arg-type]

    def test_negative_sbc_treated_as_zero(self) -> None:
        # Negative SBC (data error) → treated as 0 → no discount.
        assert compute_sbc_overlay_discount(-5.0, "tier_1") == 1.0


# ──────────────────────────────────────────────────────────────────
# compute_growth_quality_premium
# ──────────────────────────────────────────────────────────────────
class TestGrowthQualityPremium:
    def test_strong_leverage_premium(self) -> None:
        # rev=10%, head=3% → spread=7pp → +3%. Margin healthy.
        assert compute_growth_quality_premium(10.0, 22.0, 3.0) == pytest.approx(1.03)

    def test_extreme_leverage_premium(self) -> None:
        # rev=15%, head=2% → spread=13pp → +5%. Margin healthy.
        assert compute_growth_quality_premium(15.0, 22.0, 2.0) == pytest.approx(1.05)

    def test_no_leverage_neutral(self) -> None:
        # rev=10%, head=8% → spread=2pp (<5) → no premium. Margin healthy.
        assert compute_growth_quality_premium(10.0, 22.0, 8.0) == pytest.approx(1.0)

    def test_margin_compression(self) -> None:
        # Spread neutral, margin=17 → -3%.
        assert compute_growth_quality_premium(10.0, 17.0, 8.0) == pytest.approx(0.97)

    def test_severe_margin_compression(self) -> None:
        assert compute_growth_quality_premium(10.0, 14.0, 8.0) == pytest.approx(0.95)

    def test_revenue_decline_floors(self) -> None:
        # Negative revenue growth → floor at 0.95 regardless of other signals.
        assert compute_growth_quality_premium(-5.0, 25.0, 3.0) == pytest.approx(0.95)

    def test_premium_and_compression_stack(self) -> None:
        # Spread=7pp (+3%) AND margin=17 (-3%) → ~1.03 * 0.97 = 0.9991.
        result = compute_growth_quality_premium(10.0, 17.0, 3.0)
        assert result == pytest.approx(1.03 * 0.97)

    def test_ceil_clamps_at_105(self) -> None:
        # Extreme inputs should not exceed the ceiling.
        result = compute_growth_quality_premium(100.0, 50.0, 0.0)
        assert result <= 1.05

    def test_floor_clamps_at_95(self) -> None:
        result = compute_growth_quality_premium(0.5, 10.0, 0.0)
        assert result >= 0.95

    def test_non_finite_inputs_neutral(self) -> None:
        result = compute_growth_quality_premium(float("nan"), float("nan"), float("nan"))
        # All defaults: rev=10, margin=22, head=5 → spread=5pp → +3%.
        assert result == pytest.approx(1.03)


# ──────────────────────────────────────────────────────────────────
# compute_it_overlay — defensive paths
# ──────────────────────────────────────────────────────────────────
class TestComputeITOverlayDefensive:
    def test_none_base_fv_returns_none(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=None,  # type: ignore[arg-type]
            top_5_client_concentration_pct=15.0,
        ))
        assert result.adjusted_fv is None
        assert any("base_dcf_fv invalid" in w for w in result.sanity_warnings)

    def test_nan_base_fv_returns_none(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=float("nan"),
            top_5_client_concentration_pct=15.0,
        ))
        assert result.adjusted_fv is None

    def test_zero_base_fv_returns_none(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=0.0,
            top_5_client_concentration_pct=15.0,
        ))
        assert result.adjusted_fv is None

    def test_negative_base_fv_returns_none(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=-100.0,
            top_5_client_concentration_pct=15.0,
        ))
        assert result.adjusted_fv is None

    def test_unknown_tier_warns_and_defaults_to_tier1(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=15.0,
            tier="garbage",  # type: ignore[arg-type]
        ))
        assert result.adjusted_fv is not None
        assert result.adjustments["tier"] == "tier_1"
        assert any("tier=" in w for w in result.sanity_warnings)

    def test_out_of_band_inputs_warn_but_proceed(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=150.0,  # > 100
            bfsi_revenue_share_pct=-10.0,  # < 0
        ))
        assert result.adjusted_fv is not None
        assert len(result.sanity_warnings) >= 2

    def test_risk_summary_buckets(self) -> None:
        # Moderate: drift within ±3%.
        r1 = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=25.0,
            bfsi_revenue_share_pct=35.0,
            usd_revenue_share_pct=55.0,
            sbc_pct_of_fcf=1.5,
            headcount_growth_pct=8.0,
            revenue_growth_3y_cagr_pct=10.0,
            operating_margin_pct=22.0,
            tier="tier_1",
        ))
        assert r1.risk_summary == "moderate"

        # High: ECLERX shape.
        r2 = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=60.0,
            bfsi_revenue_share_pct=45.0,
            usd_revenue_share_pct=70.0,
            sbc_pct_of_fcf=15.0,
            headcount_growth_pct=10.0,
            revenue_growth_3y_cagr_pct=10.0,
            operating_margin_pct=14.0,
            tier="specialist",
        ))
        assert r2.risk_summary == "high"

    def test_compound_multiplier_in_adjustments(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=15.0,
        ))
        assert "compound_multiplier" in result.adjustments
        c = result.adjustments["concentration_multiplier"]
        s = result.adjustments["sbc_multiplier"]
        g = result.adjustments["growth_quality_multiplier"]
        assert result.adjustments["compound_multiplier"] == pytest.approx(c * s * g)


# ──────────────────────────────────────────────────────────────────
# is_it_overlay_applicable
# ──────────────────────────────────────────────────────────────────
class TestApplicability:
    def test_tcs_applicable(self) -> None:
        ok, reason = is_it_overlay_applicable("TCS", None)
        assert ok is True
        assert "TCS" in reason

    def test_tcs_ns_suffix_normalized(self) -> None:
        ok, _ = is_it_overlay_applicable("TCS.NS", None)
        assert ok is True

    def test_tcs_bo_suffix_normalized(self) -> None:
        ok, _ = is_it_overlay_applicable("TCS.BO", None)
        assert ok is True

    def test_infy_lowercase_applicable(self) -> None:
        ok, _ = is_it_overlay_applicable("infy", None)
        assert ok is True

    def test_hdfcbank_not_applicable(self) -> None:
        ok, _ = is_it_overlay_applicable("HDFCBANK", "Financial Services")
        assert ok is False

    def test_reliance_not_applicable(self) -> None:
        ok, _ = is_it_overlay_applicable("RELIANCE", "Energy")
        assert ok is False

    def test_sector_match_applicable(self) -> None:
        # Unknown ticker but IT sector → applicable.
        ok, _ = is_it_overlay_applicable("SOMEITCO", "Information Technology")
        assert ok is True

    def test_sector_match_it_services(self) -> None:
        ok, _ = is_it_overlay_applicable("SOMEITCO", "IT Services")
        assert ok is True

    def test_empty_ticker_not_applicable(self) -> None:
        ok, _ = is_it_overlay_applicable("", None)
        assert ok is False

    def test_none_ticker_not_applicable(self) -> None:
        ok, _ = is_it_overlay_applicable(None, None)  # type: ignore[arg-type]
        assert ok is False

    def test_universe_contents(self) -> None:
        # Brief-listed Tier-1 must all be present and tagged correctly.
        assert IT_TICKERS["TCS"] == "tier_1"
        assert IT_TICKERS["INFY"] == "tier_1"
        assert IT_TICKERS["HCLTECH"] == "tier_1"
        assert IT_TICKERS["WIPRO"] == "tier_1"
        assert IT_TICKERS["TECHM"] == "tier_1"
        assert IT_TICKERS["LTIM"] == "tier_1"
        # Tier-2
        assert IT_TICKERS["PERSISTENT"] == "tier_2"
        assert IT_TICKERS["MPHASIS"] == "tier_2"
        assert IT_TICKERS["COFORGE"] == "tier_2"
        # Specialists
        assert IT_TICKERS["ECLERX"] == "specialist"


# ──────────────────────────────────────────────────────────────────
# to_dict
# ──────────────────────────────────────────────────────────────────
class TestToDict:
    def test_shape(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=1000.0,
            top_5_client_concentration_pct=15.0,
        ))
        d = to_dict(result)
        assert set(d.keys()) == {
            "base_dcf_fv",
            "adjusted_fv",
            "adjustments",
            "risk_summary",
            "sanity_warnings",
            "method",
        }
        assert d["method"] == "it_services_overlay_phase_a"
        assert isinstance(d["adjustments"], dict)
        assert isinstance(d["sanity_warnings"], list)

    def test_handles_none_adjusted_fv(self) -> None:
        result = compute_it_overlay(ITServicesOverlayInputs(
            base_dcf_fv=None,  # type: ignore[arg-type]
            top_5_client_concentration_pct=15.0,
        ))
        d = to_dict(result)
        assert d["adjusted_fv"] is None
