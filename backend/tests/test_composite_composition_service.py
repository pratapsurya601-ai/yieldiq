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


class TestSectorSpecificRow:
    """P0 2026-06-11 — sector_specific FV emitted as 8th row above DCF."""

    def test_no_sector_specific_keeps_seven_rows(self):
        # Baseline — no sector-specific FV, panel stays at 7 rows.
        payload = {
            "valuation": {"fair_value": 1000.0},
            "multiples_based_fv": 1100.0,
        }
        result = build_composite_composition(payload, composite_components=None)
        assert len(result.estimators) == 7
        assert result.estimators_total == 7
        # No sector_specific key present.
        assert all(r.key != "sector_specific" for r in result.estimators)

    def test_sector_specific_appears_as_eighth_row(self):
        # Bank Residual Income — HDFCBANK-shaped: DCF skipped (FCF non-
        # positive), Multiples present via P/B fallback, sector engine
        # populates with Bank Residual Income.
        payload = {
            "valuation": {"fair_value": None, "current_price": 1900.0},
            "multiples_based_fv": 1180.0,
            "probability_weighted_fv": 1189.40,
            "sector_specific_fv": 1800.0,
            "sector_specific_label": "bank_residual_income",
            "dcf_reason": "base_year_fcf_non_positive",
            "ddm_reason": "payout_ratio 26% < 30%",
            "epv_reason": "banks use the financial-cohort path, not EPV",
        }
        result = build_composite_composition(payload, composite_components=None)
        # 7 canonical + 1 sector-specific.
        assert len(result.estimators) == 8
        assert result.estimators_total == 8
        # sector_specific row is the first one rendered.
        first = result.estimators[0]
        assert first.key == "sector_specific"
        assert first.applicable is True
        assert first.value == 1800.0
        # Label / description come from the per-sector map.
        assert "Bank Residual Income" in first.label
        # Available count includes the sector slot + multiples + prob-
        # weighted (DCF / DDM / EPV / Wall St / Three-stage / Analyst
        # are inapplicable for this fixture).
        assert result.estimators_available == 3

    def test_unknown_sector_label_falls_back_to_generic_copy(self):
        payload = {
            "valuation": {"fair_value": 1000.0},
            "sector_specific_fv": 1234.0,
            "sector_specific_label": "made_up_engine_2099",
        }
        result = build_composite_composition(payload, composite_components=None)
        first = result.estimators[0]
        assert first.key == "sector_specific"
        # Generic fallback label used.
        assert "Sector-specific" in first.label

    def test_sector_specific_weight_pulled_from_components_when_present(self):
        # When composite_components carries the sector slot, the panel
        # uses its effective weight verbatim.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "multiples_based_fv": 1180.0,
            "sector_specific_fv": 1800.0,
            "sector_specific_label": "bank_residual_income",
        }
        composite_components = {
            "components": {
                "sector_specific": {"value": 1800.0, "weight": 0.45},
                "dcf": {"value": 1141.82, "weight": 0.22},
                "multiples": {"value": 1180.0, "weight": 0.18},
            },
            "method": "sector_bank_residual_income_composite_3_method",
            "sector_specific_label": "bank_residual_income",
        }
        result = build_composite_composition(
            payload, composite_components=composite_components,
        )
        ss = next(r for r in result.estimators if r.key == "sector_specific")
        assert ss.weight_effective == pytest.approx(0.45, abs=0.001)


class TestEPVBankCohortReasonOverlay:
    """P0 2026-06-11 — EPV 'insufficient history' rewritten on bank cohort."""

    def test_bank_payload_with_stale_history_reason_gets_rewritten(self):
        # Legacy cached payload — EPV inject ran the old gate order and
        # stamped "insufficient history (0 years; need at least 5)" on
        # a bank ticker. The composition panel rewrites the reason to
        # the bank-cohort framework copy.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "quality": {"is_bank": True},
            "epv_reason": "insufficient history (0 years; need at least 5)",
        }
        result = build_composite_composition(payload, composite_components=None)
        epv_row = next(r for r in result.estimators if r.key == "epv")
        assert epv_row.applicable is False
        assert epv_row.reason is not None
        assert "Residual Income" in epv_row.reason
        assert "insufficient history" not in epv_row.reason.lower()

    def test_bank_sector_string_match_when_is_bank_flag_absent(self):
        # Even older cached payload — no is_bank flag, only sector.
        payload = {
            "valuation": {"fair_value": 1141.82},
            "company": {"sector": "Banking"},
            "epv_reason": "insufficient_history",
        }
        result = build_composite_composition(payload, composite_components=None)
        epv_row = next(r for r in result.estimators if r.key == "epv")
        assert epv_row.applicable is False
        assert "Residual Income" in (epv_row.reason or "")

    def test_non_bank_keeps_history_reason_untouched(self):
        # A regular non-bank ticker that legitimately doesn't have
        # enough history (e.g. recent IPO) keeps the original reason.
        payload = {
            "valuation": {"fair_value": 1000.0},
            "company": {"sector": "Information Technology"},
            "epv_reason": "insufficient history (2 years; need at least 5)",
        }
        result = build_composite_composition(payload, composite_components=None)
        epv_row = next(r for r in result.estimators if r.key == "epv")
        assert epv_row.applicable is False
        assert "insufficient history" in (epv_row.reason or "").lower()
        assert "Residual Income" not in (epv_row.reason or "")


class TestHDFCBANKEndToEnd:
    """End-to-end HDFCBANK shape: 5 of 8 estimators populated."""

    def test_hdfcbank_post_phase_b_renders_eight_rows_minimum_four_applicable(self):
        # Approximate HDFCBANK shape after the Phase-B inject chain
        # populates sector_specific_fv. The composition panel now reads:
        #   - sector_specific (Bank Residual Income) ₹1,800 — applicable
        #   - DCF — skipped (base_year_fcf_non_positive)
        #   - Multiples ₹1,180 — applicable (P/B fallback)
        #   - Three-stage — skipped (base_year_fcf_non_positive)
        #   - Wall St — skipped (no broker coverage)
        #   - DDM — skipped (payout 26% < 30%)
        #   - EPV — skipped (banks use Residual Income, not EPV)
        #   - Probability-weighted ₹1,189.40 — applicable
        #
        # That's 3 applicable canonical + 1 sector_specific = 4 of 8.
        payload = {
            "valuation": {"fair_value": None, "current_price": 1900.0},
            "multiples_based_fv": 1180.0,
            "probability_weighted_fv": 1189.40,
            "sector_specific_fv": 1800.0,
            "sector_specific_label": "bank_residual_income",
            "quality": {"is_bank": True},
            "dcf_reason": "base_year_fcf_non_positive",
            "three_stage_reason": "base_year_fcf_non_positive",
            "ddm_reason": "payout_ratio 26% < 30%",
            "epv_reason": "insufficient history (0 years; need at least 5)",
        }
        result = build_composite_composition(payload, composite_components=None)
        # 8-row total — the canonical 7 plus the sector-specific Bank
        # Residual Income row.
        assert len(result.estimators) == 8
        assert result.estimators_total == 8
        # At least 3 estimators applicable (sector + multiples + prob-wt).
        assert result.estimators_available >= 3
        # The EPV reason is rewritten away from the stale "insufficient
        # history" toward the bank-cohort framework copy.
        epv_row = next(r for r in result.estimators if r.key == "epv")
        assert "Residual Income" in (epv_row.reason or "")
        # The sector-specific Bank Residual Income row carries the right
        # label so the user can see the engine name.
        ss_row = next(
            r for r in result.estimators if r.key == "sector_specific"
        )
        assert "Bank Residual Income" in ss_row.label
        assert ss_row.value == 1800.0
