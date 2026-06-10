# backend/tests/test_composite_iv_phase_c.py
# ═══════════════════════════════════════════════════════════════
# Phase C (2026-06-10) — composite IV now folds in four Phase-A
# standalone engines: Three-stage DCF, DDM, EPV, Probability-weighted.
# Liquidation + Replacement stay OUT (floor / Q signals, not estimators).
#
# This file pins the new behaviour:
#   * All 7 estimators present → weighted average matches the documented
#     default-weight distribution.
#   * Partial sets (4/5/6 estimators) → pro-rata redistribution works.
#   * HDFCBANK-shaped fixture → composite drops from the pre-Phase-C
#     value as three-stage drags the average down.
#   * Method tag handling for the new N-method generic form.
#   * Bank branch + Phase-C estimator combinations.
#
# Tests in `test_composite_iv_service.py` cover the legacy three-
# estimator paths + the holdco / bank branches and the single-
# estimator paths for each new slot. The two files are intentionally
# disjoint: this file is the Phase-C-specific contract pin.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.services.composite_iv_service import (
    DEFAULT_WEIGHT_ANALYST,
    DEFAULT_WEIGHT_DCF,
    DEFAULT_WEIGHT_DDM,
    DEFAULT_WEIGHT_EPV,
    DEFAULT_WEIGHT_MULTIPLES,
    DEFAULT_WEIGHT_PROBABILITY_WEIGHTED,
    DEFAULT_WEIGHT_THREE_STAGE,
    compute_composite_iv,
)


def _close(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(a - b) < tol


# ═══════════════════════════════════════════════════════════════
# 1. Default-weight invariants
# ═══════════════════════════════════════════════════════════════
class TestWeightConstants:
    """Pin the documented default weights so a future tweak is intentional."""

    def test_dcf_weight_is_035(self):
        assert DEFAULT_WEIGHT_DCF == 0.35

    def test_multiples_weight_is_020(self):
        assert DEFAULT_WEIGHT_MULTIPLES == 0.20

    def test_analyst_weight_is_015(self):
        assert DEFAULT_WEIGHT_ANALYST == 0.15

    def test_three_stage_weight_is_015(self):
        assert DEFAULT_WEIGHT_THREE_STAGE == 0.15

    def test_ddm_weight_is_005(self):
        assert DEFAULT_WEIGHT_DDM == 0.05

    def test_epv_weight_is_005(self):
        assert DEFAULT_WEIGHT_EPV == 0.05

    def test_probability_weighted_weight_is_005(self):
        assert DEFAULT_WEIGHT_PROBABILITY_WEIGHTED == 0.05

    def test_all_seven_weights_sum_to_one(self):
        total = (
            DEFAULT_WEIGHT_DCF
            + DEFAULT_WEIGHT_MULTIPLES
            + DEFAULT_WEIGHT_ANALYST
            + DEFAULT_WEIGHT_THREE_STAGE
            + DEFAULT_WEIGHT_DDM
            + DEFAULT_WEIGHT_EPV
            + DEFAULT_WEIGHT_PROBABILITY_WEIGHTED
        )
        assert _close(total, 1.0, tol=1e-9)


# ═══════════════════════════════════════════════════════════════
# 2. All-seven-estimators path
# ═══════════════════════════════════════════════════════════════
class TestSevenEstimatorPath:
    """When every estimator is present, raw defaults apply unchanged."""

    def test_seven_estimators_method_tag_is_generic_n_method(self):
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
            probability_weighted_fv=920.0,
        )
        assert result.method == "composite_7_method"

    def test_seven_estimators_weighted_average_correct(self):
        # Use round numbers to make the arithmetic checkable by eye:
        # 1000*0.35 + 900*0.20 + 950*0.15 + 800*0.15 + 850*0.05 + 820*0.05 + 920*0.05
        # = 350 + 180 + 142.5 + 120 + 42.5 + 41 + 46 = 922
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
            probability_weighted_fv=920.0,
        )
        assert result.value is not None
        assert _close(result.value, 922.0, tol=0.2)

    def test_seven_estimators_weights_match_defaults(self):
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
            probability_weighted_fv=920.0,
        )
        # When all present, raw defaults apply (no pro-rata rescale).
        assert _close(
            result.components["dcf"].weight, DEFAULT_WEIGHT_DCF, tol=1e-6
        )
        assert _close(
            result.components["multiples"].weight, DEFAULT_WEIGHT_MULTIPLES, tol=1e-6
        )
        assert _close(
            result.components["analyst"].weight, DEFAULT_WEIGHT_ANALYST, tol=1e-6
        )
        assert _close(
            result.components["three_stage"].weight,
            DEFAULT_WEIGHT_THREE_STAGE,
            tol=1e-6,
        )
        assert _close(
            result.components["ddm"].weight, DEFAULT_WEIGHT_DDM, tol=1e-6
        )
        assert _close(
            result.components["epv"].weight, DEFAULT_WEIGHT_EPV, tol=1e-6
        )
        assert _close(
            result.components["probability_weighted"].weight,
            DEFAULT_WEIGHT_PROBABILITY_WEIGHTED,
            tol=1e-6,
        )

    def test_seven_estimators_components_dict_has_seven_entries(self):
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
            probability_weighted_fv=920.0,
        )
        assert len(result.components) == 7

    def test_seven_estimators_weights_sum_to_one(self):
        # Weights are stored rounded to 4dp on each CompositeIVComponent
        # so the sum may drift slightly from exactly 1.0; the internal
        # math uses full precision. tol=1e-3 covers any rounding drift.
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
            probability_weighted_fv=920.0,
        )
        total = sum(c.weight for c in result.components.values())
        assert _close(total, 1.0, tol=1e-3)


# ═══════════════════════════════════════════════════════════════
# 3. HDFCBANK-shaped fixture (the canary stock)
# ═══════════════════════════════════════════════════════════════
class TestHDFCBANKLikeFixture:
    """HDFCBANK is the canary for the Phase-C composite shift.

    Real numbers from the brief:
      DCF (residual income) ≈ 1129.28
      Multiples             ≈ 872.33
      Analyst (Finnhub avg) ≈ 803.00
      Three-stage DCF       ≈ 706.00
      DDM                   ≈ N/A (insufficient streak / payout)
      EPV                   ≈ N/A (history not surfaced on payload)
      Prob-weighted         ≈ N/A (scenarios may not be both-side-positive)
    """

    def test_hdfcbank_with_three_stage_drops_composite_into_900s(self):
        # Four estimators (three legacy + three-stage). raw weights
        # 0.35 + 0.20 + 0.15 + 0.15 = 0.85 → pro-rata divides each by 0.85.
        # Composite = (1129.28*0.35 + 872.33*0.20 + 803*0.15 + 706*0.15) / 0.85
        #           = (395.25 + 174.47 + 120.45 + 105.90) / 0.85
        #           = 796.07 / 0.85 = 936.55
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
            three_stage_fv=706.00,
            stock_kind="bank",
            ticker="HDFCBANK.NS",
        )
        assert result.value is not None
        # Composite lands in the mid-900s. Pre-Phase-C composite was ~985.95
        # without three-stage — the new estimator drags it ~50 closer to the
        # AlphaSpread anchor.
        assert _close(result.value, 936.55, tol=1.0)
        # Bank + Phase-C estimator → generic bank N-method tag.
        assert result.method == "bank_composite_4_method"
        # All four estimator slots present, none zeroed.
        assert "dcf" in result.components
        assert "multiples" in result.components
        assert "analyst" in result.components
        assert "three_stage" in result.components
        # The three Phase-C slots that the data didn't support stay absent.
        assert "ddm" not in result.components
        assert "epv" not in result.components
        assert "probability_weighted" not in result.components

    def test_hdfcbank_composite_lower_than_dcf_only(self):
        # Sanity: every Phase-C estimator on this fixture is BELOW the DCF,
        # so the composite must come in below the DCF-only headline.
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
            three_stage_fv=706.00,
            stock_kind="bank",
            ticker="HDFCBANK.NS",
        )
        assert result.value is not None
        assert result.value < 1129.28

    def test_hdfcbank_composite_higher_than_alphaspread_target(self):
        # AlphaSpread published target ≈ 803 (matches the analyst slot here).
        # The composite still surfaces ABOVE that anchor — we haven't given
        # up the DCF signal entirely, just dampened it. The gap narrows
        # from 40% pre-T1.1 to ~17% post-Phase-C.
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
            three_stage_fv=706.00,
            stock_kind="bank",
            ticker="HDFCBANK.NS",
        )
        assert result.value is not None
        assert result.value > 803.0


# ═══════════════════════════════════════════════════════════════
# 4. Partial Phase-C estimator sets (pro-rata redistribution)
# ═══════════════════════════════════════════════════════════════
class TestPartialPhaseCSets:
    """Subsets of estimators redistribute weights pro-rata; method tag
    reports the N count when any Phase-C estimator participates."""

    def test_six_estimators_one_missing_redistributes(self):
        # Drop probability_weighted. raw 0.35+0.20+0.15+0.15+0.05+0.05 = 0.95.
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
            epv_fv=820.0,
        )
        assert result.method == "composite_6_method"
        # Tolerance relaxed to 1e-3 — components are stored rounded to
        # 4dp so the sum may drift by ~5e-5 per term (here 6 * 5e-5 ≈
        # 3e-4). The underlying internal weights still sum to 1.0.
        total = sum(c.weight for c in result.components.values())
        assert _close(total, 1.0, tol=1e-3)
        assert len(result.components) == 6

    def test_five_estimators_dcf_three_stage_redistribution(self):
        # Three legacy + three-stage + ddm. raw 0.35+0.20+0.15+0.15+0.05 = 0.90.
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
            ddm_fv=850.0,
        )
        assert result.method == "composite_5_method"
        # DCF re-normalized weight = 0.35/0.90 ≈ 0.389.
        assert _close(result.components["dcf"].weight, 0.35 / 0.90, tol=1e-3)
        assert _close(
            result.components["three_stage"].weight, 0.15 / 0.90, tol=1e-3
        )

    def test_four_estimators_dcf_three_stage_only(self):
        # Just DCF + three-stage. raw 0.35 + 0.15 = 0.50 → DCF 0.70, TS 0.30.
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=None,
            analyst_avg=None,
            three_stage_fv=800.0,
        )
        # Only two estimators are present → it's a composite_2_method form.
        # But the legacy path doesn't have a 2-method analog for DCF+three_stage
        # (the legacy tags were only DCF+Multiples / DCF+Analyst /
        # Multiples+Analyst). Since three_stage is a Phase-C estimator, the
        # generic N-method form fires.
        assert result.method == "composite_2_method"
        # 1000*0.70 + 800*0.30 = 700 + 240 = 940
        assert _close(result.value, 940.0, tol=0.5)
        assert _close(result.components["dcf"].weight, 0.70, tol=1e-3)
        assert _close(result.components["three_stage"].weight, 0.30, tol=1e-3)

    def test_legacy_three_plus_three_stage_uses_generic_tag(self):
        # The 4-estimator HDFCBANK case but non-bank → composite_4_method.
        result = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            three_stage_fv=800.0,
        )
        assert result.method == "composite_4_method"

    def test_three_legacy_plus_ddm_alone(self):
        # Legacy three + DDM only. Sanity that the small-weight slot
        # changes the composite by a small amount (proportional to its weight).
        legacy = compute_composite_iv(
            dcf_fv=1000.0, multiples_fv=900.0, analyst_avg=950.0
        )
        with_ddm = compute_composite_iv(
            dcf_fv=1000.0,
            multiples_fv=900.0,
            analyst_avg=950.0,
            ddm_fv=600.0,
        )
        assert legacy.value is not None
        assert with_ddm.value is not None
        # DDM at 600 pulls below the legacy composite; the move is small
        # because DDM weight is just 0.05 / 0.75 ≈ 6.7% pro-rata.
        assert with_ddm.value < legacy.value
        assert with_ddm.method == "composite_4_method"


# ═══════════════════════════════════════════════════════════════
# 5. Backward compatibility — legacy-three-only callers
# ═══════════════════════════════════════════════════════════════
class TestBackwardCompatibility:
    """Callers passing only the original 3 positional args still get a
    composite — but the VALUE changes by ~1% from pre-Phase-C because
    the weights re-balanced. This is documented in the function's
    docstring; the test pins the new expected value."""

    def test_legacy_three_args_still_emit_composite_dcf_multiples_analyst(self):
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
        )
        assert result.method == "composite_dcf_multiples_analyst"

    def test_legacy_three_args_value_close_to_pre_phase_c(self):
        # Pre-Phase-C composite would have been 986.94 (weights 0.50/0.30/0.20).
        # Post-Phase-C with only three inputs: 985.95 (pro-rata of
        # 0.35/0.20/0.15 → 0.50/0.2857/0.2143). Drift ~0.1%.
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
        )
        assert result.value is not None
        # Within ~2 rupees of the legacy value (intentionally tight to
        # catch any future weight rebalance that silently moves the value
        # significantly on legacy-three callers).
        assert _close(result.value, 985.95, tol=0.5)
