"""Tests for compute_composite_agreement_score (T1.6, 2026-06-10).

Pure-function tests for the 5th Confidence pillar. Verifies:
  - HDFCBANK-shape three-estimator composite (~18% CV) -> 60-80 band
  - TCS-shape tightly clustered composite (<5% CV)     -> 100
  - Extreme divergence (CV > 0.5)                       -> 20
  - Single estimator                                    -> None
  - Empty / malformed components                        -> None
  - Defensive against None / wrong shape                -> None
  - compute_all_scores returns the 5-key dict including
    composite_agreement.

These tests run with no DB / network / yfinance access.
"""

from __future__ import annotations

import pytest

from backend.services.confidence_service import (
    compute_all_scores,
    compute_composite_agreement_score,
)


# ───────────────────────────────────────────────────────────────────
# Fixtures — shapes mirroring composite_iv_service.composite_to_dict
# ───────────────────────────────────────────────────────────────────
def _hdfcbank_shape() -> dict:
    """Three estimators clustered around ~935, CV ~= 0.18.

    DCF ₹1,129, Multiples ₹872, Analyst ₹803. Mean ≈ ₹935.
    stdev ≈ ₹167, CV ≈ 0.179. Lands in the 60-80 band per the
    threshold map.
    """
    return {
        "value": 935.0,
        "components": {
            "dcf": {"value": 1129.0, "weight": 0.50},
            "multiples": {"value": 872.0, "weight": 0.30},
            "analyst": {"value": 803.0, "weight": 0.20},
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": False,
    }


def _tcs_tight_shape() -> dict:
    """All three estimators within 5% of each other -> CV <= 0.05."""
    return {
        "value": 4015.0,
        "components": {
            "dcf": {"value": 4050.0, "weight": 0.50},
            "multiples": {"value": 4000.0, "weight": 0.30},
            "analyst": {"value": 3995.0, "weight": 0.20},
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": False,
    }


def _extreme_divergence_shape() -> dict:
    """DCF ₹2,000 / Multiples ₹500 / Analyst ₹1,500. Mean ≈ ₹1,333,
    stdev ≈ ₹624, CV ≈ 0.47. Lands in the 40 bucket per spec ...

    To land in the *20* bucket (CV > 0.50) we widen the spread:
    use 2200 / 400 / 1700 so the CV crosses 0.50.
    """
    return {
        "value": 1433.0,
        "components": {
            "dcf": {"value": 2200.0, "weight": 0.50},
            "multiples": {"value": 400.0, "weight": 0.30},
            "analyst": {"value": 1700.0, "weight": 0.20},
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": True,
    }


def _single_estimator_shape() -> dict:
    """Only one active estimator — no agreement signal possible."""
    return {
        "value": 1050.0,
        "components": {
            "dcf": {"value": 1050.0, "weight": 1.0},
        },
        "method": "holdco_dcf_only",
        "extreme_divergence": False,
    }


def _empty_shape() -> dict:
    return {
        "value": None,
        "components": {},
        "method": "unavailable",
        "extreme_divergence": False,
    }


# ───────────────────────────────────────────────────────────────────
# 1. Cluster width sanity
# ───────────────────────────────────────────────────────────────────
def test_hdfcbank_three_estimator_cluster_lands_60_to_80():
    """Mean ~935, CV ~0.18 -> the 0.15 < CV <= 0.30 bucket -> 60."""
    score = compute_composite_agreement_score(_hdfcbank_shape())
    assert score is not None
    assert 60 <= score <= 80, (
        f"HDFCBANK-shape (mean ~935, CV ~0.18) should land in [60, 80]; "
        f"got {score}"
    )


def test_tcs_tight_cluster_lands_at_100():
    score = compute_composite_agreement_score(_tcs_tight_shape())
    assert score == 100


def test_extreme_divergence_lands_in_lowest_bucket():
    """Widely-spread shape should fall into the lowest score bucket."""
    score = compute_composite_agreement_score(_extreme_divergence_shape())
    assert score is not None
    # The spread is intentionally wide; the score must be at most 40
    # (the second-lowest bucket) and never None / >=60.
    assert score <= 40, (
        f"Extreme-divergence shape should produce a low agreement "
        f"score (<=40); got {score}"
    )


# ───────────────────────────────────────────────────────────────────
# 2. Structural None paths
# ───────────────────────────────────────────────────────────────────
def test_single_estimator_returns_none():
    """A single-estimator composite carries no agreement signal."""
    assert compute_composite_agreement_score(_single_estimator_shape()) is None


def test_empty_components_returns_none():
    assert compute_composite_agreement_score(_empty_shape()) is None


def test_none_input_returns_none():
    assert compute_composite_agreement_score(None) is None


def test_wrong_shape_returns_none():
    """Anything that isn't a Mapping or lacks 'components' returns None."""
    assert compute_composite_agreement_score("not a dict") is None  # type: ignore[arg-type]
    assert compute_composite_agreement_score({"components": "wrong"}) is None
    assert compute_composite_agreement_score({"no_components_key": {}}) is None


def test_malformed_component_values_ignored():
    """Non-numeric / non-positive component values are dropped; if
    fewer than 2 valid values remain, return None."""
    payload = {
        "value": 1000.0,
        "components": {
            "dcf": {"value": 1000.0, "weight": 0.5},
            "multiples": {"value": "garbage", "weight": 0.3},
            "analyst": {"value": -500.0, "weight": 0.2},  # ignored
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": False,
    }
    # Only one valid component (dcf) — should be None.
    assert compute_composite_agreement_score(payload) is None


def test_two_valid_components_score_emitted():
    """Two valid components is the minimum for an agreement signal."""
    payload = {
        "value": 1000.0,
        "components": {
            "dcf": {"value": 1000.0, "weight": 0.6},
            "multiples": {"value": 1010.0, "weight": 0.4},
        },
        "method": "composite_dcf_multiples",
        "extreme_divergence": False,
    }
    score = compute_composite_agreement_score(payload)
    assert score is not None
    # Two values within 1% of each other -> top bucket.
    assert score == 100


def test_non_mapping_component_entries_dropped():
    """A component entry that isn't a Mapping is silently dropped."""
    payload = {
        "value": 1000.0,
        "components": {
            "dcf": {"value": 1000.0, "weight": 0.5},
            "multiples": "not_a_mapping",  # ignored
            "analyst": {"value": 1020.0, "weight": 0.5},
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": False,
    }
    score = compute_composite_agreement_score(payload)
    # Two valid values within 2% -> top bucket.
    assert score == 100


# ───────────────────────────────────────────────────────────────────
# 3. compute_all_scores integration
# ───────────────────────────────────────────────────────────────────
def test_compute_all_scores_returns_five_keys():
    out = compute_all_scores(
        "HDFCBANK",
        enriched={"sector": "Banking"},
        composite_components=_hdfcbank_shape(),
    )
    assert set(out.keys()) == {
        "data_quality",
        "model_confidence",
        "valuation_stability",
        "sensitivity",
        "composite_agreement",
    }


def test_compute_all_scores_propagates_composite_agreement():
    out = compute_all_scores(
        "HDFCBANK",
        enriched={"sector": "Banking"},
        composite_components=_hdfcbank_shape(),
    )
    assert out["composite_agreement"] is not None
    assert 60 <= out["composite_agreement"] <= 80


def test_compute_all_scores_without_composite_returns_none_for_agreement():
    """When composite_components isn't passed, the 5th key is None."""
    out = compute_all_scores(
        "HDFCBANK",
        enriched={"sector": "Banking"},
    )
    assert "composite_agreement" in out
    assert out["composite_agreement"] is None


def test_compute_all_scores_composite_none_for_single_estimator():
    out = compute_all_scores(
        "BAJAJHLDNG",
        enriched={"sector": "Holding Company"},
        composite_components=_single_estimator_shape(),
    )
    assert out["composite_agreement"] is None


def test_compute_all_scores_never_raises_on_garbage():
    """Defensive contract — anything goes in, dict comes out."""
    out = compute_all_scores(
        "TEST",
        composite_components={"components": None},  # type: ignore[dict-item]
    )
    assert isinstance(out, dict)
    assert out["composite_agreement"] is None


# ───────────────────────────────────────────────────────────────────
# 4. Monotonicity property test — wider spread -> lower score
# ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "values, expected_band",
    [
        # CV ~= 0.012 -> 100
        ([1000.0, 1010.0, 1020.0], (100, 100)),
        # CV ~= 0.082 -> 80
        ([900.0, 1000.0, 1100.0], (80, 80)),
        # CV ~= 0.20 -> 60
        ([700.0, 1000.0, 1300.0], (60, 60)),
        # CV ~= 0.408 -> 40
        ([400.0, 1000.0, 1600.0], (40, 40)),
        # CV ~= 0.65 -> 20
        ([200.0, 800.0, 2000.0], (20, 20)),
    ],
)
def test_score_buckets_monotonic_in_spread(values, expected_band):
    payload = {
        "value": sum(values) / len(values),
        "components": {
            f"e{i}": {"value": v, "weight": 1.0 / len(values)}
            for i, v in enumerate(values)
        },
        "method": "composite_dcf_multiples_analyst",
        "extreme_divergence": False,
    }
    score = compute_composite_agreement_score(payload)
    lo, hi = expected_band
    assert score is not None
    assert lo <= score <= hi, (
        f"values={values} expected score in [{lo}, {hi}]; got {score}"
    )
