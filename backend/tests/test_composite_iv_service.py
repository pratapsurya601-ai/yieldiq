# backend/tests/test_composite_iv_service.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend/services/composite_iv_service.py.
#
# Originally T1.1 (2026-06-09): three-estimator weighted average of
# DCF + Multiples + Wall St analyst price target.
#
# Phase C (2026-06-10) extended the average with four standalone
# Phase-A engines: Three-stage DCF, DDM, EPV, Probability-weighted.
# Default weights re-balanced — see composite_iv_service.py docstring.
# The tests below cover both the legacy three-estimator paths (now
# returning slightly different values because of the re-balance) and
# the new 4-7 estimator paths.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.services.composite_iv_service import (
    CompositeIV,
    DEFAULT_WEIGHT_ANALYST,
    DEFAULT_WEIGHT_DCF,
    DEFAULT_WEIGHT_DDM,
    DEFAULT_WEIGHT_EPV,
    DEFAULT_WEIGHT_MULTIPLES,
    DEFAULT_WEIGHT_PROBABILITY_WEIGHTED,
    DEFAULT_WEIGHT_THREE_STAGE,
    EXTREME_DIVERGENCE_RATIO,
    composite_to_dict,
    compute_composite_iv,
)


def _close(a: float, b: float, tol: float = 0.05) -> bool:
    """Float comparison helper — composite is rounded to 2dp."""
    return abs(a - b) < tol


class TestThreeEstimatorPath:
    """All three legacy inputs present — pre-Phase-C dominant case.

    Phase C re-balanced weights (DCF 0.50 -> 0.35, Multiples 0.30 ->
    0.20, Analyst 0.20 -> 0.15). When ONLY the legacy three are
    provided the pro-rata renormalization yields DCF ≈ 0.50,
    Multiples ≈ 0.286, Analyst ≈ 0.214 (total 0.70 redistributed).
    """

    def test_all_three_inputs_weighted_with_new_phase_c_weights(self):
        # HDFCBANK-shaped fixture from the T1.1 spec, recomputed under
        # Phase C weights (only the three legacy inputs supplied):
        #   raw weights: DCF 0.35, Multiples 0.20, Analyst 0.15 = 0.70
        #   pro-rata:    DCF 0.500, Multiples 0.2857, Analyst 0.2143
        # Composite = 1129.28*0.500 + 872.33*0.2857 + 803.00*0.2143
        #           ≈ 564.64 + 249.24 + 172.07 = 985.95
        result = compute_composite_iv(
            dcf_fv=1129.28,
            multiples_fv=872.33,
            analyst_avg=803.00,
        )
        assert result.value is not None
        assert _close(result.value, 985.95, tol=0.5)
        assert result.method == "composite_dcf_multiples_analyst"
        # Components carry pro-rata weights (not raw defaults).
        legacy_total = (
            DEFAULT_WEIGHT_DCF + DEFAULT_WEIGHT_MULTIPLES + DEFAULT_WEIGHT_ANALYST
        )
        assert _close(
            result.components["dcf"].weight,
            DEFAULT_WEIGHT_DCF / legacy_total,
            tol=1e-3,
        )
        assert _close(
            result.components["multiples"].weight,
            DEFAULT_WEIGHT_MULTIPLES / legacy_total,
            tol=1e-3,
        )
        assert _close(
            result.components["analyst"].weight,
            DEFAULT_WEIGHT_ANALYST / legacy_total,
            tol=1e-3,
        )
        # All component values are preserved (only the composite is averaged).
        assert _close(result.components["dcf"].value, 1129.28, tol=0.01)
        assert _close(result.components["multiples"].value, 872.33, tol=0.01)
        assert _close(result.components["analyst"].value, 803.00, tol=0.01)

    def test_components_weights_sum_to_one(self):
        result = compute_composite_iv(
            dcf_fv=1000.0, multiples_fv=900.0, analyst_avg=950.0
        )
        total = sum(c.weight for c in result.components.values())
        assert _close(total, 1.0, tol=1e-6)


class TestRedistributionPaths:
    """Missing-estimator paths re-distribute weights pro-rata.

    Under Phase C weights the legacy two-estimator pairs renormalize
    against the new defaults (0.35 / 0.20 / 0.15).
    """

    def test_multiples_missing_dcf_and_analyst_share_pro_rata(self):
        # Defaults: DCF 0.35, Analyst 0.15 → totals 0.50.
        # Re-normalized: DCF 0.35/0.50 = 0.70, Analyst 0.15/0.50 = 0.30.
        result = compute_composite_iv(
            dcf_fv=1000.0, multiples_fv=None, analyst_avg=800.0
        )
        assert result.value is not None
        assert result.method == "composite_dcf_analyst"
        # Composite = 1000 * 0.70 + 800 * 0.30 = 700 + 240 = 940.
        assert _close(result.value, 940.0, tol=0.5)
        assert _close(result.components["dcf"].weight, 0.70, tol=1e-3)
        assert _close(result.components["analyst"].weight, 0.30, tol=1e-3)
        total = sum(c.weight for c in result.components.values())
        assert _close(total, 1.0, tol=1e-6)
        assert "multiples" not in result.components

    def test_analyst_missing_dcf_and_multiples_share_pro_rata(self):
        # Defaults: DCF 0.35, Multiples 0.20 → totals 0.55.
        # Re-normalized: DCF 0.35/0.55 ≈ 0.636, Multiples 0.20/0.55 ≈ 0.364.
        result = compute_composite_iv(
            dcf_fv=1000.0, multiples_fv=800.0, analyst_avg=None
        )
        assert result.value is not None
        assert result.method == "composite_dcf_multiples"
        # Composite ≈ 1000 * 0.636 + 800 * 0.364 ≈ 636 + 291 ≈ 927.27.
        assert _close(result.value, 927.27, tol=0.5)
        assert _close(
            result.components["dcf"].weight, 0.35 / 0.55, tol=1e-3
        )
        assert _close(
            result.components["multiples"].weight, 0.20 / 0.55, tol=1e-3
        )

    def test_dcf_missing_multiples_and_analyst_share_pro_rata(self):
        # Defaults: Multiples 0.20, Analyst 0.15 → totals 0.35.
        # Re-normalized: Multiples 0.20/0.35 ≈ 0.571, Analyst 0.15/0.35 ≈ 0.429.
        result = compute_composite_iv(
            dcf_fv=None, multiples_fv=800.0, analyst_avg=900.0
        )
        assert result.value is not None
        assert result.method == "composite_multiples_analyst"
        # Composite ≈ 800 * 0.571 + 900 * 0.429 ≈ 457.14 + 385.71 = 842.86.
        assert _close(result.value, 842.86, tol=0.5)


class TestSingleEstimatorPaths:
    """When only one estimator is present, weight = 1.0 and composite = it."""

    def test_only_dcf_returns_dcf_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=1129.28, multiples_fv=None, analyst_avg=None
        )
        assert result.value is not None
        assert _close(result.value, 1129.28, tol=0.01)
        assert result.method == "dcf_only"
        assert _close(result.components["dcf"].weight, 1.0, tol=1e-6)
        assert len(result.components) == 1

    def test_only_multiples_returns_multiples_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=None, multiples_fv=872.33, analyst_avg=None
        )
        assert result.value is not None
        assert _close(result.value, 872.33, tol=0.01)
        assert result.method == "multiples_only"
        assert _close(result.components["multiples"].weight, 1.0, tol=1e-6)

    def test_only_analyst_returns_analyst_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=None, multiples_fv=None, analyst_avg=803.0
        )
        assert result.value is not None
        assert _close(result.value, 803.0, tol=0.01)
        assert result.method == "analyst_only"
        assert _close(result.components["analyst"].weight, 1.0, tol=1e-6)

    def test_only_three_stage_returns_three_stage_with_weight_one(self):
        # New Phase C single-estimator path.
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=None,
            analyst_avg=None,
            three_stage_fv=706.0,
        )
        assert result.value is not None
        assert _close(result.value, 706.0, tol=0.01)
        assert result.method == "three_stage_only"
        assert _close(result.components["three_stage"].weight, 1.0, tol=1e-6)

    def test_only_ddm_returns_ddm_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=None,
            analyst_avg=None,
            ddm_fv=550.0,
        )
        assert result.value is not None
        assert _close(result.value, 550.0, tol=0.01)
        assert result.method == "ddm_only"

    def test_only_epv_returns_epv_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=None,
            analyst_avg=None,
            epv_fv=620.0,
        )
        assert result.value is not None
        assert _close(result.value, 620.0, tol=0.01)
        assert result.method == "epv_only"

    def test_only_prob_weighted_returns_with_weight_one(self):
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=None,
            analyst_avg=None,
            probability_weighted_fv=780.0,
        )
        assert result.value is not None
        assert _close(result.value, 780.0, tol=0.01)
        assert result.method == "probability_weighted_only"


class TestUnavailable:
    def test_all_inputs_none_returns_unavailable(self):
        result = compute_composite_iv(
            dcf_fv=None, multiples_fv=None, analyst_avg=None
        )
        assert result.value is None
        assert result.components == {}
        assert result.method == "unavailable"

    def test_all_inputs_zero_or_negative_returns_unavailable(self):
        # Zero and negative inputs are rejected (treated as None) per the
        # _coerce_pos_float posture mirrored from multiples_fv.py.
        result = compute_composite_iv(
            dcf_fv=0.0, multiples_fv=-100.0, analyst_avg=0.0
        )
        assert result.value is None
        assert result.method == "unavailable"

    def test_nan_inputs_rejected(self):
        result = compute_composite_iv(
            dcf_fv=float("nan"),
            multiples_fv=float("nan"),
            analyst_avg=float("nan"),
        )
        assert result.value is None
        assert result.method == "unavailable"

    def test_all_seven_zero_or_negative_returns_unavailable(self):
        # The new Phase-C slots are subject to the same gate.
        result = compute_composite_iv(
            dcf_fv=0.0,
            multiples_fv=-1.0,
            analyst_avg=0.0,
            three_stage_fv=0.0,
            ddm_fv=-5.0,
            epv_fv=0.0,
            probability_weighted_fv=0.0,
        )
        assert result.value is None
        assert result.method == "unavailable"


class TestHoldcoBranch:
    """Pure holdcos skip multiples + Phase-C extras; composite = DCF alone."""

    def test_holdco_kind_skips_multiples(self):
        # Even when multiples_fv is provided, the holdco branch ignores it.
        result = compute_composite_iv(
            dcf_fv=1500.0,
            multiples_fv=1200.0,
            analyst_avg=1800.0,
            stock_kind="holdco",
        )
        assert result.value is not None
        assert _close(result.value, 1500.0, tol=0.01)
        assert result.method == "holdco_dcf_only"
        assert len(result.components) == 1
        assert "dcf" in result.components
        assert "multiples" not in result.components
        assert "analyst" not in result.components

    def test_holdco_ticker_in_holding_companies_set_skips_multiples(self):
        # BAJAJHLDNG is in HOLDING_COMPANIES (constants.py). Even without
        # stock_kind tagged, the ticker fallback routes to the holdco branch.
        result = compute_composite_iv(
            dcf_fv=1500.0,
            multiples_fv=1200.0,
            analyst_avg=1800.0,
            ticker="BAJAJHLDNG.NS",
        )
        assert result.method == "holdco_dcf_only"
        assert "multiples" not in result.components

    def test_holdco_without_dcf_returns_unavailable(self):
        # A holdco with no DCF is genuinely unavailable — SOTP is the
        # right answer but ships under T1.4; until then we honestly
        # surface "no composite" rather than fake one off multiples.
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=1200.0,
            analyst_avg=1800.0,
            stock_kind="holdco",
        )
        assert result.value is None
        assert result.method == "unavailable"

    def test_holdco_ignores_phase_c_estimators_too(self):
        # Phase-C slots are also skipped on the holdco branch. The
        # standalone services' applicability gates already exclude
        # holdcos at the Phase-B inject layer; this is the belt-and-
        # braces backstop on the composite side.
        result = compute_composite_iv(
            dcf_fv=1500.0,
            multiples_fv=1200.0,
            analyst_avg=1800.0,
            three_stage_fv=1100.0,
            ddm_fv=900.0,
            epv_fv=1000.0,
            probability_weighted_fv=1400.0,
            stock_kind="holdco",
        )
        assert result.method == "holdco_dcf_only"
        assert len(result.components) == 1
        for k in ("three_stage", "ddm", "epv", "probability_weighted"):
            assert k not in result.components


class TestBankBranch:
    """Bank branch tags the dcf slot as residual_income via the method tag."""

    def test_bank_kind_with_three_estimators_tags_method(self):
        # HDFCBANK-shaped (legacy 3 estimators only — no Phase-C extras):
        # the dcf_fv parameter here is actually the P/BV residual-income
        # FV the bank engine emitted. Composite math is unchanged; only
        # the method tag flips so the frontend can relabel the pill.
        result = compute_composite_iv(
            dcf_fv=900.0,
            multiples_fv=850.0,
            analyst_avg=803.0,
            stock_kind="bank",
        )
        assert result.value is not None
        # Legacy bank 3-way tag preserved when no Phase-C estimator present.
        assert result.method == "bank_composite_residual_multiples_analyst"
        # Composite under Phase-C weights (pro-rata DCF 0.50 / Mult 0.286 / Ana 0.214):
        # 900*0.500 + 850*0.2857 + 803*0.2143 ≈ 450 + 242.86 + 172.07 = 864.93
        assert _close(result.value, 864.93, tol=0.5)

    def test_bank_sector_tagging_via_string(self):
        result = compute_composite_iv(
            dcf_fv=900.0,
            multiples_fv=850.0,
            analyst_avg=None,
            sector="Banking",
        )
        # bank + 2 legacy estimators -> bank_composite_residual_multiples
        assert result.method == "bank_composite_residual_multiples"

    def test_bank_single_dcf_returns_residual_income_tag(self):
        result = compute_composite_iv(
            dcf_fv=900.0, multiples_fv=None, analyst_avg=None, stock_kind="bank"
        )
        assert result.method == "bank_residual_income"

    def test_bank_with_phase_c_estimator_uses_generic_n_method_tag(self):
        # Bank + any Phase-C estimator collapses to the generic
        # bank_composite_N_method tag (the frontend reads N + the
        # components dict for per-row labels).
        result = compute_composite_iv(
            dcf_fv=900.0,
            multiples_fv=850.0,
            analyst_avg=803.0,
            three_stage_fv=706.0,
            stock_kind="bank",
        )
        assert result.method == "bank_composite_4_method"


class TestExtremeDivergence:
    """Flag when the spread between max and min active estimator exceeds 2x."""

    def test_extreme_divergence_flagged_when_spread_exceeds_threshold(self):
        # max 2400 / min 1000 = 2.4 > 2.0 → flag fires.
        result = compute_composite_iv(
            dcf_fv=2400.0, multiples_fv=1000.0, analyst_avg=1200.0
        )
        assert result.value is not None  # composite still emitted.
        assert result.extreme_divergence is True

    def test_extreme_divergence_not_flagged_for_modest_spread(self):
        # max 1100 / min 900 ≈ 1.22 ≤ 2.0 → flag stays False.
        result = compute_composite_iv(
            dcf_fv=1100.0, multiples_fv=900.0, analyst_avg=1000.0
        )
        assert result.extreme_divergence is False

    def test_extreme_divergence_false_for_single_estimator(self):
        # Single estimator can't diverge with itself.
        result = compute_composite_iv(
            dcf_fv=1000.0, multiples_fv=None, analyst_avg=None
        )
        assert result.extreme_divergence is False

    def test_extreme_divergence_ratio_constant_is_two(self):
        # Pin the constant so future tuning is intentional.
        assert EXTREME_DIVERGENCE_RATIO == 2.0


class TestStringCoercion:
    """Numeric strings on the input slot still produce a composite."""

    def test_string_inputs_coerced(self):
        result = compute_composite_iv(
            dcf_fv="1129.28", multiples_fv="872.33", analyst_avg="803.00"
        )
        assert result.value is not None
        assert _close(result.value, 985.95, tol=0.5)

    def test_string_phase_c_inputs_coerced(self):
        result = compute_composite_iv(
            dcf_fv=None,
            multiples_fv=None,
            analyst_avg=None,
            three_stage_fv="706.00",
        )
        assert result.value is not None
        assert _close(result.value, 706.0, tol=0.01)


class TestRoundingAndShape:
    def test_serializes_via_composite_to_dict(self):
        result = compute_composite_iv(
            dcf_fv=1129.28, multiples_fv=872.33, analyst_avg=803.00
        )
        as_dict = composite_to_dict(result)
        assert isinstance(as_dict, dict)
        assert "value" in as_dict
        assert "components" in as_dict
        assert "method" in as_dict
        assert "extreme_divergence" in as_dict
        for key, comp in as_dict["components"].items():
            assert "value" in comp
            assert "weight" in comp
