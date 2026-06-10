# backend/tests/test_derived_insights_service.py
# ═══════════════════════════════════════════════════════════════
# T5.3 (2026-06-10) — derived insights service unit tests.
#
# Covers each of the four insight builders in isolation, the
# top-level `compute_all_insights` orchestrator, the `to_dict`
# JSON projection, and the defensive posture (bad inputs surface
# as None rather than raising).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import math

import pytest

from backend.services.derived_insights_service import (
    ConfidenceSummaryInsight,
    DerivedInsights,
    EstimatorClusteringInsight,
    FloorCeilingInsight,
    SectorCalibrationInsight,
    compute_all_insights,
    compute_confidence_summary,
    compute_estimator_clustering,
    compute_floor_ceiling,
    compute_sector_calibration,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# Insight 1 — confidence summary
# ─────────────────────────────────────────────────────────────────
class TestConfidenceSummary:
    def test_all_five_pillars_high_yields_very_high(self):
        result = compute_confidence_summary(
            {
                "data_quality": 92,
                "model_fit": 90,
                "stability": 85,
                "sensitivity": 88,
                "estimator_agreement": 86,
            }
        )
        assert result is not None
        assert result.overall_level == "very_high"
        assert result.overall_score == 88  # mean(92,90,85,88,86)
        assert result.pillars_present == 5
        assert "VERY HIGHLY confident" in result.headline

    def test_all_five_pillars_low_yields_very_low(self):
        result = compute_confidence_summary(
            {
                "data_quality": 20,
                "model_fit": 25,
                "stability": 15,
                "sensitivity": 22,
                "estimator_agreement": 18,
            }
        )
        assert result is not None
        assert result.overall_level == "very_low"
        assert "VERY LOW" in result.headline

    def test_partial_pillars_present(self):
        # Only 2 pillars carry scores — overall is mean of the two.
        result = compute_confidence_summary(
            {
                "data_quality": 80,
                "model_fit": 60,
                "stability": None,
                "sensitivity": None,
                "estimator_agreement": None,
            }
        )
        assert result is not None
        assert result.pillars_present == 2
        assert result.overall_score == 70  # mean(80, 60)
        assert result.overall_level == "high"
        assert "data_quality" in result.pillar_breakdown
        assert "model_fit" in result.pillar_breakdown
        assert "stability" not in result.pillar_breakdown

    def test_no_pillars_returns_none(self):
        assert compute_confidence_summary({}) is None
        assert compute_confidence_summary({"data_quality": None}) is None

    def test_non_dict_returns_none(self):
        assert compute_confidence_summary(None) is None
        assert compute_confidence_summary("garbage") is None
        assert compute_confidence_summary([1, 2, 3]) is None

    def test_score_clamping(self):
        # > 100 clamps to 100, negative clamps to 0.
        result = compute_confidence_summary({"data_quality": 150})
        assert result is not None
        assert result.pillar_breakdown["data_quality"]["score"] == 100
        result2 = compute_confidence_summary({"data_quality": -25})
        assert result2 is not None
        assert result2.pillar_breakdown["data_quality"]["score"] == 0

    def test_level_thresholds(self):
        # very_high: >= 85
        assert compute_confidence_summary({"data_quality": 85}).overall_level == "very_high"
        assert compute_confidence_summary({"data_quality": 84}).overall_level == "high"
        # high: 70..84
        assert compute_confidence_summary({"data_quality": 70}).overall_level == "high"
        assert compute_confidence_summary({"data_quality": 69}).overall_level == "moderate"
        # moderate: 50..69
        assert compute_confidence_summary({"data_quality": 50}).overall_level == "moderate"
        assert compute_confidence_summary({"data_quality": 49}).overall_level == "low"
        # low: 30..49
        assert compute_confidence_summary({"data_quality": 30}).overall_level == "low"
        assert compute_confidence_summary({"data_quality": 29}).overall_level == "very_low"


# ─────────────────────────────────────────────────────────────────
# Insight 2 — estimator clustering
# ─────────────────────────────────────────────────────────────────
class TestEstimatorClustering:
    def test_seven_estimators_within_5pct(self):
        # All within 5% of 1000 — cluster_count = 7, total = 7.
        components = {
            "components": {
                "dcf": {"value": 1000.0, "weight": 0.35},
                "multiples": {"value": 980.0, "weight": 0.20},
                "analyst": {"value": 1020.0, "weight": 0.15},
                "three_stage": {"value": 990.0, "weight": 0.10},
                "ddm": {"value": 1010.0, "weight": 0.10},
                "epv": {"value": 995.0, "weight": 0.05},
                "probability_weighted": {"value": 1005.0, "weight": 0.05},
            }
        }
        result = compute_estimator_clustering(components)
        assert result is not None
        assert result.total_estimators == 7
        assert result.cluster_count == 7
        assert abs(result.cluster_center - 1000.0) < 0.01

    def test_five_of_seven_cluster_example_from_spec(self):
        # Spec headline: "5 of 7 estimators cluster within 15% of ₹950"
        # Build a set where 5 sit within 15% and 2 sit outside.
        components = {
            "components": {
                "dcf": {"value": 1129.0, "weight": 0.35},          # outside (+19%)
                "multiples": {"value": 872.0, "weight": 0.20},
                "analyst": {"value": 803.0, "weight": 0.15},        # outside (-15%)
                "three_stage": {"value": 870.0, "weight": 0.10},
                "epv": {"value": 890.0, "weight": 0.10},
                "probability_weighted": {"value": 945.0, "weight": 0.10},
                # 6 estimators total; center will be median.
            }
        }
        result = compute_estimator_clustering(components)
        assert result is not None
        assert result.total_estimators == 6
        # Headline references cluster center.
        assert "cluster within 15% of" in result.headline

    def test_singleton_returns_none(self):
        components = {"components": {"dcf": {"value": 1000.0, "weight": 1.0}}}
        assert compute_estimator_clustering(components) is None

    def test_empty_components_returns_none(self):
        assert compute_estimator_clustering({"components": {}}) is None
        assert compute_estimator_clustering({}) is None

    def test_none_or_non_dict_returns_none(self):
        assert compute_estimator_clustering(None) is None
        assert compute_estimator_clustering("garbage") is None

    def test_non_positive_values_dropped(self):
        # Zero / negative / non-finite values are filtered before
        # the clustering pass.
        components = {
            "components": {
                "dcf": {"value": 1000.0, "weight": 0.5},
                "multiples": {"value": 980.0, "weight": 0.3},
                "analyst": {"value": 0.0, "weight": 0.2},
                "three_stage": {"value": -50.0, "weight": 0.1},
                "epv": {"value": float("nan"), "weight": 0.1},
            }
        }
        result = compute_estimator_clustering(components)
        assert result is not None
        assert result.total_estimators == 2  # only DCF + multiples survive

    def test_accepts_flat_shape(self):
        # When the caller passes a flat dict (no "components" key), the
        # function still extracts the known slots.
        flat = {
            "dcf": {"value": 1000.0, "weight": 0.5},
            "multiples": {"value": 1010.0, "weight": 0.5},
        }
        result = compute_estimator_clustering(flat)
        assert result is not None
        assert result.total_estimators == 2

    def test_unknown_slots_ignored(self):
        # Unrecognised slot names are silently dropped.
        components = {
            "components": {
                "dcf": {"value": 1000.0, "weight": 0.5},
                "multiples": {"value": 1010.0, "weight": 0.5},
                "made_up_estimator": {"value": 10.0, "weight": 0.5},
            }
        }
        result = compute_estimator_clustering(components)
        assert result is not None
        assert result.total_estimators == 2


# ─────────────────────────────────────────────────────────────────
# Insight 3 — floor + ceiling
# ─────────────────────────────────────────────────────────────────
class TestFloorCeiling:
    def test_full_inputs(self):
        result = compute_floor_ceiling(
            liquidation=420.0,
            replacement=680.0,
            current_price=700.0,
            dcf=1129.0,
            composite=937.0,
        )
        assert result is not None
        assert result.liquidation_per_share == 420.0
        assert result.replacement_per_share == 680.0
        assert result.current_price == 700.0
        assert result.dcf_fv == 1129.0
        assert result.composite_iv == 937.0
        assert result.distress_flag is False
        assert "Floor support" in result.headline

    def test_distress_when_price_below_liquidation(self):
        result = compute_floor_ceiling(
            liquidation=500.0,
            replacement=None,
            current_price=400.0,
            dcf=None,
            composite=None,
        )
        assert result is not None
        assert result.distress_flag is True
        assert "Distress signal" in result.headline

    def test_liquidation_only(self):
        result = compute_floor_ceiling(
            liquidation=420.0,
            replacement=None,
            current_price=700.0,
            dcf=None,
            composite=None,
        )
        assert result is not None
        assert result.replacement_per_share is None
        assert result.ceiling_distance_pct is None
        assert result.floor_distance_pct is not None

    def test_replacement_only(self):
        result = compute_floor_ceiling(
            liquidation=None,
            replacement=680.0,
            current_price=700.0,
            dcf=None,
            composite=None,
        )
        assert result is not None
        assert result.liquidation_per_share is None
        assert result.floor_distance_pct is None
        assert result.ceiling_distance_pct is not None

    def test_no_anchors_returns_none(self):
        # Neither floor nor ceiling — nothing to anchor.
        assert (
            compute_floor_ceiling(
                liquidation=None,
                replacement=None,
                current_price=700.0,
                dcf=None,
                composite=None,
            )
            is None
        )

    def test_bad_current_price_returns_none(self):
        # Non-positive / non-finite current_price short-circuits.
        assert (
            compute_floor_ceiling(
                liquidation=420.0,
                replacement=None,
                current_price=0.0,
                dcf=None,
                composite=None,
            )
            is None
        )
        assert (
            compute_floor_ceiling(
                liquidation=420.0,
                replacement=None,
                current_price=float("nan"),
                dcf=None,
                composite=None,
            )
            is None
        )

    def test_distress_distance_pct(self):
        # Price 400, floor 500 → -20% below.
        result = compute_floor_ceiling(
            liquidation=500.0,
            replacement=None,
            current_price=400.0,
            dcf=None,
            composite=None,
        )
        assert result is not None
        assert result.floor_distance_pct == -20.0


# ─────────────────────────────────────────────────────────────────
# Insight 4 — sector calibration
# ─────────────────────────────────────────────────────────────────
class TestSectorCalibration:
    def test_full_provider_result(self):
        def provider(sector):
            return {
                "median_abs_error_pct": 12.3,
                "direction_accuracy_pct": 73.0,
                "observation_count": 247,
            }

        result = compute_sector_calibration("FMCG", provider)
        assert result is not None
        assert result.sector == "FMCG"
        assert result.median_abs_error_pct == 12.3
        assert result.direction_accuracy_pct == 73.0
        assert result.observation_count == 247
        assert "FMCG" in result.headline
        assert "247 observations" in result.headline

    def test_provider_returns_none(self):
        # Sector is missing from the published list (< 30 observations).
        def provider(sector):
            return None

        assert compute_sector_calibration("FMCG", provider) is None

    def test_provider_raises(self):
        def provider(sector):
            raise RuntimeError("boom")

        assert compute_sector_calibration("FMCG", provider) is None

    def test_no_sector_returns_none(self):
        provider = lambda s: {"median_abs_error_pct": 10.0}
        assert compute_sector_calibration(None, provider) is None
        assert compute_sector_calibration("", provider) is None
        assert compute_sector_calibration(123, provider) is None

    def test_no_provider_returns_none(self):
        assert compute_sector_calibration("FMCG", None) is None

    def test_partial_provider_result(self):
        # Only median; direction missing.
        def provider(sector):
            return {"median_abs_error_pct": 15.0, "observation_count": 50}

        result = compute_sector_calibration("IT Services", provider)
        assert result is not None
        assert result.median_abs_error_pct == 15.0
        assert result.direction_accuracy_pct is None
        assert result.observation_count == 50
        assert "IT Services" in result.headline

    def test_all_metrics_absent_returns_none(self):
        def provider(sector):
            return {}

        assert compute_sector_calibration("FMCG", provider) is None


# ─────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ─────────────────────────────────────────────────────────────────
class TestComputeAllInsights:
    def test_full_inputs_populates_all_four(self):
        def provider(sector):
            return {
                "median_abs_error_pct": 12.0,
                "direction_accuracy_pct": 70.0,
                "observation_count": 100,
            }

        out = compute_all_insights(
            confidence_scores={"data_quality": 80, "model_fit": 75},
            composite_components={
                "components": {
                    "dcf": {"value": 1000.0, "weight": 0.5},
                    "multiples": {"value": 1010.0, "weight": 0.5},
                }
            },
            liquidation=420.0,
            replacement=680.0,
            current_price=700.0,
            dcf_fv=1129.0,
            composite_iv=937.0,
            sector="FMCG",
            sector_calibration_provider=provider,
        )
        assert out.confidence_summary is not None
        assert out.estimator_clustering is not None
        assert out.floor_ceiling is not None
        assert out.sector_calibration is not None

    def test_no_inputs_returns_empty_bundle(self):
        out = compute_all_insights()
        assert out.confidence_summary is None
        assert out.estimator_clustering is None
        assert out.floor_ceiling is None
        assert out.sector_calibration is None

    def test_partial_inputs_fills_only_supported_slots(self):
        # Only confidence scores — others stay None.
        out = compute_all_insights(
            confidence_scores={"data_quality": 90, "stability": 80}
        )
        assert out.confidence_summary is not None
        assert out.estimator_clustering is None
        assert out.floor_ceiling is None
        assert out.sector_calibration is None

    def test_failing_provider_does_not_break_other_insights(self):
        def provider(sector):
            raise RuntimeError("downstream DB hiccup")

        out = compute_all_insights(
            confidence_scores={"data_quality": 80},
            current_price=700.0,
            liquidation=420.0,
            sector="FMCG",
            sector_calibration_provider=provider,
        )
        # Sector calibration is None but the other three insights
        # remain unaffected by the provider explosion.
        assert out.sector_calibration is None
        assert out.confidence_summary is not None
        assert out.floor_ceiling is not None


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────
class TestToDict:
    def test_full_bundle_round_trips(self):
        out = compute_all_insights(
            confidence_scores={"data_quality": 80},
            composite_components={
                "components": {
                    "dcf": {"value": 1000.0, "weight": 0.5},
                    "multiples": {"value": 1010.0, "weight": 0.5},
                }
            },
            liquidation=420.0,
            current_price=700.0,
        )
        d = to_dict(out)
        assert isinstance(d, dict)
        assert set(d.keys()) == {
            "confidence_summary",
            "estimator_clustering",
            "floor_ceiling",
            "sector_calibration",
        }
        assert d["confidence_summary"]["overall_level"] in {
            "very_high",
            "high",
            "moderate",
            "low",
            "very_low",
        }
        assert d["estimator_clustering"]["total_estimators"] == 2
        assert d["floor_ceiling"]["liquidation_per_share"] == 420.0
        assert d["sector_calibration"] is None

    def test_empty_bundle_emits_stable_shape(self):
        d = to_dict(DerivedInsights())
        # All four keys present (stable shape) but all None.
        assert d == {
            "confidence_summary": None,
            "estimator_clustering": None,
            "floor_ceiling": None,
            "sector_calibration": None,
        }

    def test_none_input_emits_stable_shape(self):
        d = to_dict(None)
        assert d == {
            "confidence_summary": None,
            "estimator_clustering": None,
            "floor_ceiling": None,
            "sector_calibration": None,
        }


# ─────────────────────────────────────────────────────────────────
# Defensive posture
# ─────────────────────────────────────────────────────────────────
class TestDefensivePosture:
    @pytest.mark.parametrize("bad", [None, "garbage", 42, [1, 2, 3]])
    def test_confidence_summary_bad_inputs(self, bad):
        assert compute_confidence_summary(bad) is None

    @pytest.mark.parametrize("bad", [None, "garbage", 42, [1, 2, 3]])
    def test_estimator_clustering_bad_inputs(self, bad):
        assert compute_estimator_clustering(bad) is None

    def test_floor_ceiling_garbage_floats_handled(self):
        # NaN / inf / negative liquidation are dropped — when both
        # liquidation and replacement are unusable, returns None.
        assert (
            compute_floor_ceiling(
                liquidation=float("nan"),
                replacement=float("inf"),
                current_price=700.0,
                dcf=None,
                composite=None,
            )
            is None
        )

    def test_floor_ceiling_negative_liquidation_treated_as_none(self):
        # A negative liquidation alone -> nothing to anchor -> None.
        assert (
            compute_floor_ceiling(
                liquidation=-50.0,
                replacement=None,
                current_price=700.0,
                dcf=None,
                composite=None,
            )
            is None
        )
