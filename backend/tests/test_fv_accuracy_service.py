"""Tests for backend.services.fv_accuracy_service.

These are pure-function tests — no DB, no network. They lock the
contract that the /api/v1/public/accuracy endpoint depends on:

    - SEBI vocabulary mapping (undervalued -> below_fair_value, etc.)
    - directional hit-rate math
    - return-attribution mean/median per band
    - calibration-curve bucket boundaries

If the public dashboard ever shows a wrong number, the bug almost
certainly reproduces here first.
"""
from __future__ import annotations

import pytest

from backend.services.fv_accuracy_service import (
    ALL_BANDS,
    BAND_ABOVE,
    BAND_BELOW,
    BAND_NEAR,
    CALIBRATION_BUCKETS,
    compute_calibration_curve,
    compute_directional_accuracy,
    compute_return_attribution,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _row(verdict, price_then, price_now, mos_pct=None):
    return {
        "verdict": verdict,
        "price_then": price_then,
        "price_now": price_now,
        "mos_pct": mos_pct,
    }


# ═════════════════════════════════════════════════════════════════
# compute_directional_accuracy
# ═════════════════════════════════════════════════════════════════
class TestDirectionalAccuracy:
    def test_empty_rows_returns_nulls(self):
        out = compute_directional_accuracy([])
        assert out["total"] == 0
        assert out["directional_correct"] == 0
        assert out["hit_rate"] is None
        assert set(out["by_band"].keys()) == set(ALL_BANDS)
        for b in ALL_BANDS:
            assert out["by_band"][b]["hit_rate"] is None

    def test_undervalued_correct_when_return_above_5pct(self):
        # +20% return, undervalued -> correct
        rows = [_row("undervalued", 100.0, 120.0)]
        out = compute_directional_accuracy(rows)
        assert out["total"] == 1
        assert out["directional_correct"] == 1
        assert out["hit_rate"] == 1.0
        assert out["by_band"][BAND_BELOW]["correct"] == 1

    def test_undervalued_wrong_when_return_negative(self):
        rows = [_row("undervalued", 100.0, 80.0)]
        out = compute_directional_accuracy(rows)
        assert out["directional_correct"] == 0
        assert out["hit_rate"] == 0.0

    def test_overvalued_correct_when_return_below_neg5pct(self):
        rows = [_row("overvalued", 100.0, 90.0)]  # -10%
        out = compute_directional_accuracy(rows)
        assert out["directional_correct"] == 1
        assert out["by_band"][BAND_ABOVE]["correct"] == 1

    def test_fairly_valued_correct_when_return_in_band(self):
        rows = [_row("fairly_valued", 100.0, 105.0)]  # +5%
        out = compute_directional_accuracy(rows)
        assert out["directional_correct"] == 1
        assert out["by_band"][BAND_NEAR]["correct"] == 1

    def test_fairly_valued_wrong_when_return_outside_band(self):
        rows = [_row("fairly_valued", 100.0, 130.0)]  # +30%, outside ±10
        out = compute_directional_accuracy(rows)
        assert out["directional_correct"] == 0

    def test_mixed_population_aggregates_correctly(self):
        rows = [
            _row("undervalued", 100, 130),     # +30 correct
            _row("undervalued", 100, 95),      # -5  wrong
            _row("overvalued", 100, 70),       # -30 correct
            _row("overvalued", 100, 110),      # +10 wrong
            _row("fairly_valued", 100, 103),   # +3  correct
            _row("fairly_valued", 100, 140),   # +40 wrong
        ]
        out = compute_directional_accuracy(rows)
        assert out["total"] == 6
        assert out["directional_correct"] == 3
        assert out["hit_rate"] == 0.5
        assert out["by_band"][BAND_BELOW] == {"total": 2, "correct": 1, "hit_rate": 0.5}
        assert out["by_band"][BAND_ABOVE] == {"total": 2, "correct": 1, "hit_rate": 0.5}
        assert out["by_band"][BAND_NEAR] == {"total": 2, "correct": 1, "hit_rate": 0.5}

    def test_unknown_verdict_is_skipped(self):
        rows = [
            _row("garbage_value", 100, 200),
            _row(None, 100, 200),
            _row("undervalued", 100, 120),
        ]
        out = compute_directional_accuracy(rows)
        assert out["total"] == 1
        assert out["directional_correct"] == 1

    def test_invalid_prices_are_skipped(self):
        rows = [
            _row("undervalued", None, 120),
            _row("undervalued", 100, None),
            _row("undervalued", 0, 120),       # division by zero guard
            _row("undervalued", "abc", 120),   # non-numeric
            _row("undervalued", 100, 120),     # the only valid one
        ]
        out = compute_directional_accuracy(rows)
        assert out["total"] == 1
        assert out["directional_correct"] == 1


# ═════════════════════════════════════════════════════════════════
# compute_return_attribution
# ═════════════════════════════════════════════════════════════════
class TestReturnAttribution:
    def test_empty_rows(self):
        out = compute_return_attribution([])
        assert out["overall"]["count"] == 0
        assert out["overall"]["mean_return_pct"] is None
        assert out["monotonic"] is None
        for b in ALL_BANDS:
            assert out["by_band"][b]["count"] == 0

    def test_per_band_means_and_medians(self):
        rows = [
            _row("undervalued", 100, 120),   # +20
            _row("undervalued", 100, 140),   # +40
            _row("fairly_valued", 100, 105), # +5
            _row("fairly_valued", 100, 95),  # -5
            _row("overvalued", 100, 80),     # -20
        ]
        out = compute_return_attribution(rows)
        assert out["by_band"][BAND_BELOW]["count"] == 2
        assert out["by_band"][BAND_BELOW]["mean_return_pct"] == 30.0
        assert out["by_band"][BAND_BELOW]["median_return_pct"] == 30.0
        assert out["by_band"][BAND_NEAR]["mean_return_pct"] == 0.0
        assert out["by_band"][BAND_ABOVE]["mean_return_pct"] == -20.0
        assert out["overall"]["count"] == 5

    def test_monotonic_true_when_below_gt_near_gt_above(self):
        rows = [
            _row("undervalued", 100, 130),
            _row("fairly_valued", 100, 110),
            _row("overvalued", 100, 90),
        ]
        out = compute_return_attribution(rows)
        assert out["monotonic"] is True

    def test_monotonic_false_when_overvalued_outperforms(self):
        rows = [
            _row("undervalued", 100, 90),    # -10
            _row("fairly_valued", 100, 100), # 0
            _row("overvalued", 100, 130),    # +30 — bad model
        ]
        out = compute_return_attribution(rows)
        assert out["monotonic"] is False

    def test_monotonic_none_when_band_is_empty(self):
        rows = [
            _row("undervalued", 100, 130),
            _row("fairly_valued", 100, 110),
            # no overvalued rows
        ]
        out = compute_return_attribution(rows)
        assert out["monotonic"] is None


# ═════════════════════════════════════════════════════════════════
# compute_calibration_curve
# ═════════════════════════════════════════════════════════════════
class TestCalibrationCurve:
    def test_empty_rows_returns_all_zero_buckets(self):
        out = compute_calibration_curve([])
        assert len(out["buckets"]) == len(CALIBRATION_BUCKETS)
        for b in out["buckets"]:
            assert b["count"] == 0
            assert b["mean_return_pct"] is None
        assert out["monotonic"] is None

    def test_bucket_assignment(self):
        # Each row's mos_pct lands in a distinct bucket.
        rows = [
            _row("undervalued", 100, 80, mos_pct=-50),    # <=-40
            _row("undervalued", 100, 90, mos_pct=-30),    # -40..-20
            _row("fairly_valued", 100, 100, mos_pct=-10), # -20..0
            _row("fairly_valued", 100, 110, mos_pct=10),  # 0..+20
            _row("undervalued", 100, 130, mos_pct=30),    # +20..+40
            _row("undervalued", 100, 160, mos_pct=60),    # >=+40
        ]
        out = compute_calibration_curve(rows)
        for b in out["buckets"]:
            assert b["count"] == 1, f"bucket {b['label']} expected 1 row"

    def test_well_calibrated_model_is_monotonic(self):
        # MoS at T-12mo correlates linearly with realized return.
        rows = [
            _row("overvalued", 100, 70, mos_pct=-50),      # ret -30
            _row("overvalued", 100, 85, mos_pct=-30),      # ret -15
            _row("fairly_valued", 100, 95, mos_pct=-10),   # ret -5
            _row("fairly_valued", 100, 110, mos_pct=10),   # ret +10
            _row("undervalued", 100, 125, mos_pct=30),     # ret +25
            _row("undervalued", 100, 150, mos_pct=60),     # ret +50
        ]
        out = compute_calibration_curve(rows)
        assert out["monotonic"] is True

    def test_anti_calibrated_model_is_not_monotonic(self):
        # Higher MoS → lower realized return (model is inverted).
        rows = [
            _row("undervalued", 100, 50, mos_pct=60),
            _row("overvalued", 100, 200, mos_pct=-50),
        ]
        out = compute_calibration_curve(rows)
        assert out["monotonic"] is False

    def test_rows_without_mos_are_skipped(self):
        rows = [
            _row("undervalued", 100, 120, mos_pct=None),
            _row("undervalued", 100, 120, mos_pct="bogus"),
        ]
        out = compute_calibration_curve(rows)
        for b in out["buckets"]:
            assert b["count"] == 0

    def test_mean_within_bucket(self):
        rows = [
            _row("undervalued", 100, 120, mos_pct=10),  # ret +20
            _row("undervalued", 100, 110, mos_pct=15),  # ret +10
        ]
        out = compute_calibration_curve(rows)
        bucket_0_20 = next(b for b in out["buckets"] if b["label"] == "0% to +20%")
        assert bucket_0_20["count"] == 2
        assert bucket_0_20["mean_return_pct"] == 15.0
        assert bucket_0_20["median_return_pct"] == 15.0


# ═════════════════════════════════════════════════════════════════
# Vocabulary contract — guards against accidentally exposing the
# legacy "undervalued"/"overvalued" labels at the API boundary.
# ═════════════════════════════════════════════════════════════════
class TestSebiVocabulary:
    def test_no_legacy_terms_in_band_keys(self):
        for band in ALL_BANDS:
            assert "undervalued" not in band
            assert "overvalued" not in band
            assert band in (
                "below_fair_value",
                "near_fair_value",
                "above_fair_value",
            )

    def test_directional_output_uses_only_sebi_bands(self):
        rows = [
            _row("undervalued", 100, 120),
            _row("overvalued", 100, 80),
            _row("fairly_valued", 100, 100),
        ]
        out = compute_directional_accuracy(rows)
        for key in out["by_band"].keys():
            assert key in ALL_BANDS
            assert "undervalued" not in key
            assert "overvalued" not in key
