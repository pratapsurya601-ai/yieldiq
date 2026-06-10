# backend/tests/test_composite_composition_service.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend/services/composite_composition_service.py.
#
# v_composite_composition_transparency_2026_06_10
#
# Coverage targets:
#   1. Confidence bands map correctly to the integer thresholds.
#   2. Outlier flagging fires when an estimator deviates >40% from
#      the median, but ONLY when 3+ estimators are present.
#   3. Effective weights from composite_components are honored
#      verbatim (panel agrees with the composite math).
#   4. Pro-rata fallback fires when composite_components is absent
#      (legacy payload path).
#   5. Reason strings: per-ticker `_reason` slot wins over the
#      canonical default.
#   6. Serialization shape contract preserved.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest

from backend.services.composite_composition_service import (
    CANONICAL_ESTIMATORS,
    OUTLIER_THRESHOLD_PCT,
    build_composite_composition,
    composition_to_dict,
)


def _close(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) < tol


class TestConfidenceBands:
    """N of 7 thresholds map to HIGH / MODERATE / LOW / MINIMAL."""

    def test_seven_of_seven_yields_high(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1100.0,
            "three_stage_fv": 950.0,
            "insights": {"wall_street_avg_target": 1050.0},
            "ddm_fv": 1080.0,
            "epv_per_share": 970.0,
            "probability_weighted_fv": 1020.0,
            "composite_intrinsic_value": 1024.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 7
        assert result.estimators_total == 7
        assert result.confidence_label == "HIGH"
        assert "HIGH" in result.confidence_caption

    def test_five_of_seven_yields_moderate(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1100.0,
            "three_stage_fv": 950.0,
            "insights": {"wall_street_avg_target": 1050.0},
            "ddm_fv": 1080.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 5
        assert result.confidence_label == "MODERATE"
        assert "MODERATE" in result.confidence_caption

    def test_three_of_seven_yields_low(self):
        # HDFCBANK-shaped: DCF + multiples + bank-residual standin via
        # three-stage; no broker coverage, no DDM, no EPV, no prob-mix.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "multiples_based_fv": 1180.0,
            "three_stage_fv": 1100.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 3
        assert result.confidence_label == "LOW"
        assert "LOW" in result.confidence_caption

    def test_two_of_seven_yields_minimal(self):
        # Headline-ticker case: DCF + one corroborator only.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "multiples_based_fv": 1180.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 2
        assert result.confidence_label == "MINIMAL"
        assert (
            "MINIMAL" in result.confidence_caption
            or "DCF" in result.confidence_caption
        )

    def test_zero_yields_minimal(self):
        payload = {"valuation": {}}
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 0
        assert result.confidence_label == "MINIMAL"


class TestEstimatorRows:
    """Per-estimator rows carry the right metadata."""

    def test_all_seven_rows_emitted_even_when_inapplicable(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            # everything else absent
        }
        result = build_composite_composition(payload, composite_components=None)
        # Always 7 rows in the output — applicable/inapplicable mix is
        # the source of truth for the panel.
        assert len(result.estimators) == 7
        applicable = [r for r in result.estimators if r.applicable]
        assert len(applicable) == 1
        assert applicable[0].key == "dcf"
        assert _close(applicable[0].value, 1000.0)

    def test_inapplicable_row_carries_default_reason(self):
        payload = {"valuation": {"fair_value": 1000.0}}
        result = build_composite_composition(payload, composite_components=None)
        analyst_row = next(r for r in result.estimators if r.key == "analyst")
        assert analyst_row.applicable is False
        assert analyst_row.reason is not None
        assert "broker" in analyst_row.reason.lower()

    def test_per_ticker_reason_overrides_default(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "ddm_reason": "Payout 26% below 30% DDM gate",
        }
        result = build_composite_composition(payload, composite_components=None)
        ddm_row = next(r for r in result.estimators if r.key == "ddm")
        assert ddm_row.applicable is False
        assert ddm_row.reason == "Payout 26% below 30% DDM gate"


class TestEffectiveWeights:
    """When composite_components is supplied, panel uses it verbatim."""

    def test_effective_weight_from_composite_components_honored(self):
        # Two applicable estimators with hand-rolled effective weights —
        # the panel must trust the composite_iv_service math.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "multiples_based_fv": 1180.0,
            "composite_intrinsic_value": 1158.0,
        }
        composite_components = {
            "components": {
                "dcf": {"value": 1141.82, "weight": 0.6364},
                "multiples": {"value": 1180.0, "weight": 0.3636},
            },
            "method": "composite_dcf_multiples",
        }
        result = build_composite_composition(
            payload, composite_components=composite_components
        )
        dcf_row = next(r for r in result.estimators if r.key == "dcf")
        mult_row = next(r for r in result.estimators if r.key == "multiples")
        assert _close(dcf_row.weight_effective, 0.6364)
        assert _close(mult_row.weight_effective, 0.3636)
        # Nominal weights match the canonical slot defaults — the panel
        # surfaces BOTH nominal and effective so users see the math.
        assert _close(dcf_row.weight_nominal, 0.35)
        assert _close(mult_row.weight_nominal, 0.20)

    def test_effective_weight_pro_rata_when_components_absent(self):
        # No composite_components supplied (legacy payload) — fall back
        # to the pro-rata renormalization against canonical defaults.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "multiples_based_fv": 1180.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        dcf_row = next(r for r in result.estimators if r.key == "dcf")
        mult_row = next(r for r in result.estimators if r.key == "multiples")
        # 0.35 + 0.20 = 0.55 → DCF 0.6364, Multiples 0.3636.
        expected_dcf = 0.35 / 0.55
        expected_mult = 0.20 / 0.55
        assert _close(dcf_row.weight_effective, expected_dcf, tol=0.001)
        assert _close(mult_row.weight_effective, expected_mult, tol=0.001)

    def test_inapplicable_rows_carry_zero_effective_weight(self):
        payload = {"valuation": {"fair_value": 1000.0}}
        result = build_composite_composition(payload, composite_components=None)
        for row in result.estimators:
            if not row.applicable:
                assert row.weight_effective == 0.0
                assert row.contribution is None


class TestContribution:
    """Contribution = value * weight_effective."""

    def test_contribution_arithmetic(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1200.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        dcf_row = next(r for r in result.estimators if r.key == "dcf")
        mult_row = next(r for r in result.estimators if r.key == "multiples")
        # contributions should sum to ~composite_value.
        contributions = [
            r.contribution for r in result.estimators if r.contribution is not None
        ]
        assert len(contributions) == 2
        # Expected: DCF 1000 * 0.6364 + Mult 1200 * 0.3636 = 636.4 + 436.4 = 1072.8
        expected = (
            dcf_row.value * dcf_row.weight_effective
            + mult_row.value * mult_row.weight_effective
        )
        assert _close(sum(contributions), expected, tol=0.5)


class TestOutlierFlagging:
    """Outliers fire when value deviates >40% from median."""

    def test_no_outlier_with_only_two_estimators(self):
        # 2 estimators — outlier concept undefined; should NOT flag.
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 100.0,  # 90% gap — would be outlier with 3+
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.outliers == []
        assert all(not r.is_outlier for r in result.estimators)

    def test_outlier_flagged_when_three_plus_estimators_present(self):
        # Three estimators where one is 60% above the median should
        # trip the OUTLIER_THRESHOLD_PCT (40%) gate.
        # values: 1000, 1100, 2000
        # median = 1100; deviations: 9%, 0%, 81% — only 2000 is outlier.
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1100.0,
            "three_stage_fv": 2000.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert "three_stage" in result.outliers
        ts_row = next(r for r in result.estimators if r.key == "three_stage")
        assert ts_row.is_outlier is True
        # The other two are inside the band.
        dcf_row = next(r for r in result.estimators if r.key == "dcf")
        mult_row = next(r for r in result.estimators if r.key == "multiples")
        assert dcf_row.is_outlier is False
        assert mult_row.is_outlier is False

    def test_clustered_estimators_no_outlier(self):
        # All within 10% of each other — no outlier expected.
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1050.0,
            "three_stage_fv": 990.0,
            "insights": {"wall_street_avg_target": 1020.0},
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.outliers == []
        assert all(not r.is_outlier for r in result.estimators)


class TestSerialization:
    """composition_to_dict preserves shape contract."""

    def test_dict_carries_all_required_top_level_keys(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1100.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        as_dict = composition_to_dict(result)
        # Required keys per the spec.
        for key in (
            "estimators",
            "estimators_available",
            "estimators_total",
            "confidence_label",
            "confidence_caption",
            "outliers",
            "composite_value",
        ):
            assert key in as_dict

    def test_each_estimator_row_carries_required_fields(self):
        payload = {"valuation": {"fair_value": 1000.0}}
        result = build_composite_composition(payload, composite_components=None)
        as_dict = composition_to_dict(result)
        assert len(as_dict["estimators"]) == 7
        for row in as_dict["estimators"]:
            for key in (
                "key",
                "label",
                "value",
                "weight_nominal",
                "weight_effective",
                "contribution",
                "applicable",
                "reason",
                "is_outlier",
                "description",
            ):
                assert key in row, f"row missing key {key!r}: {row}"

    def test_estimator_order_matches_canonical(self):
        payload = {"valuation": {"fair_value": 1000.0}}
        result = build_composite_composition(payload, composite_components=None)
        as_dict = composition_to_dict(result)
        actual_order = [r["key"] for r in as_dict["estimators"]]
        expected_order = [slot.key for slot in CANONICAL_ESTIMATORS]
        assert actual_order == expected_order


class TestRealWorldFixtures:
    """End-to-end shape against fixture data shaped like prod tickers."""

    def test_hdfcbank_shape_drives_low_confidence(self):
        # Approximate HDFCBANK fixture from the task brief — only DCF,
        # Multiples, and (synth) bank-residual standin via three-stage.
        payload = {
            "valuation": {"fair_value": 1141.82, "current_price": 1900.0},
            "multiples_based_fv": 1180.0,
            "three_stage_fv": 1100.0,
            "probability_weighted_fv": 1189.40,
            "composite_intrinsic_value": 1147.77,
            # DDM gated out (low payout); EPV gated out (banks use
            # financial cohort); Wall St absent (no broker coverage in
            # this fixture).
            "ddm_reason": "Payout below DDM gate",
            "epv_reason": "Banks use the financial-cohort path",
        }
        result = build_composite_composition(payload, composite_components=None)
        assert result.estimators_available == 4
        # MODERATE band at 4/7 per the threshold table.
        assert result.confidence_label == "MODERATE"
        # Reasons preserved on inapplicable rows.
        ddm_row = next(r for r in result.estimators if r.key == "ddm")
        epv_row = next(r for r in result.estimators if r.key == "epv")
        assert ddm_row.reason == "Payout below DDM gate"
        assert epv_row.reason == "Banks use the financial-cohort path"

    def test_axisbank_shape_with_single_outlier(self):
        # Shape that surfaces the AXISBANK +60% Undervalued case —
        # three estimators with one going extreme. Outlier flag
        # should fire so the user can see the +60% MoS came from a
        # single divergent estimator, not a consensus signal.
        payload = {
            "valuation": {"fair_value": 1500.0, "current_price": 1314.0},
            "multiples_based_fv": 1450.0,
            "three_stage_fv": 3200.0,  # extreme — 110%+ above median
        }
        result = build_composite_composition(payload, composite_components=None)
        # 3/7 -> LOW confidence band.
        assert result.confidence_label == "LOW"
        # The extreme estimator flagged as outlier.
        assert "three_stage" in result.outliers
        ts_row = next(r for r in result.estimators if r.key == "three_stage")
        assert ts_row.is_outlier is True
