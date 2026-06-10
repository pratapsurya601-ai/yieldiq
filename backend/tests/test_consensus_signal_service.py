# backend/tests/test_consensus_signal_service.py
"""
Tests for backend/services/consensus_signal_service.py

Covers:
  * happy-path direction counting (above / below / near + ties)
  * level classification thresholds
  * tolerance band edge cases
  * CV computation (magnitude clustering)
  * defensive: None / non-finite / negative inputs
  * headline + to_dict + estimator_breakdown projections
  * SEBI vocab posture on every produced string
"""
from __future__ import annotations

import math
import re

import pytest

from backend.services.consensus_signal_service import (
    ConsensusSignal,
    build_estimator_breakdown,
    build_headline,
    classify_consensus_level,
    compute_consensus_signal,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# SEBI vocab guard — fragment-built per CLAUDE.md rule #5
# ─────────────────────────────────────────────────────────────────
# Each token is a string-concatenation of two halves so the SEBI diff-only
# linter doesn't flag this file's added lines as banned literals while the
# runtime assertion stays meaningful.
_BANNED_TOKENS = [
    "b" + "uy",
    "se" + "ll",
    "ho" + "ld",
    "recom" + "mend",
    "sho" + "uld",
    "che" + "ap",
    "expen" + "sive",
    "undervalu" + "ed",
    "overvalu" + "ed",
    "stro" + "ng " + "b" + "uy",
]


def _assert_sebi_clean(s: str) -> None:
    """Every string emitted by the service must be free of banned vocab."""
    assert isinstance(s, str)
    lowered = s.lower()
    for token in _BANNED_TOKENS:
        assert token not in lowered, f"SEBI banned token {token!r} in: {s!r}"


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────
@pytest.fixture
def seven_estimator_above():
    """6 of 7 estimators above price (very_high above)."""
    price = 1000.0
    values = {
        "dcf": 1129,
        "multiples": 1200,
        "analyst": 1150,
        "three_stage": 1080,
        "ddm": 1095,
        "epv": 1075,
        "probability_weighted": 850,  # this one points below
    }
    return values, price


@pytest.fixture
def seven_estimator_below():
    """5 of 7 estimators below price."""
    price = 1000.0
    values = {
        "dcf": 800,
        "multiples": 700,
        "analyst": 850,
        "three_stage": 1020,  # near
        "ddm": 600,
        "epv": 750,
        "probability_weighted": 1200,  # above
    }
    return values, price


@pytest.fixture
def seven_estimator_near():
    """All 7 estimators cluster within ±5% of price."""
    price = 1000.0
    values = {
        "dcf": 990,
        "multiples": 1010,
        "analyst": 1005,
        "three_stage": 995,
        "ddm": 1020,
        "epv": 970,
        "probability_weighted": 1030,
    }
    return values, price


# ─────────────────────────────────────────────────────────────────
# classify_consensus_level
# ─────────────────────────────────────────────────────────────────
class TestClassifyConsensusLevel:
    def test_seven_of_seven_is_very_high(self):
        assert classify_consensus_level(7, 7) == "very_high"

    def test_six_of_seven_is_very_high(self):
        # 6/7 = 0.857 -> very_high (>= 0.85)
        assert classify_consensus_level(6, 7) == "very_high"

    def test_five_of_seven_is_high(self):
        # 5/7 = 0.714 -> high (>= 0.70)
        assert classify_consensus_level(5, 7) == "high"

    def test_four_of_seven_is_moderate(self):
        # 4/7 = 0.571 -> moderate
        assert classify_consensus_level(4, 7) == "moderate"

    def test_three_of_seven_is_low(self):
        # 3/7 = 0.428 -> low
        assert classify_consensus_level(3, 7) == "low"

    def test_two_of_seven_is_dispersed(self):
        # 2/7 = 0.285 -> dispersed
        assert classify_consensus_level(2, 7) == "dispersed"

    def test_singleton_is_dispersed(self):
        assert classify_consensus_level(1, 1) == "dispersed"

    def test_zero_estimators_is_dispersed(self):
        assert classify_consensus_level(0, 0) == "dispersed"

    def test_zero_agreement_is_dispersed(self):
        assert classify_consensus_level(0, 5) == "dispersed"

    def test_count_clamped_to_total(self):
        # Defensive: caller bug shouldn't crash.
        assert classify_consensus_level(99, 7) == "very_high"

    def test_negative_total_is_dispersed(self):
        assert classify_consensus_level(0, -1) == "dispersed"

    def test_five_of_five_is_very_high(self):
        # All agreement on smaller universe still classes very_high.
        assert classify_consensus_level(5, 5) == "very_high"


# ─────────────────────────────────────────────────────────────────
# compute_consensus_signal — direction agreement
# ─────────────────────────────────────────────────────────────────
class TestComputeConsensusSignalDirection:
    def test_six_of_seven_above_price(self, seven_estimator_above):
        values, price = seven_estimator_above
        sig = compute_consensus_signal(values, price)
        assert sig.total_estimators == 7
        assert sig.direction_agreement_count == 6
        assert sig.consensus_direction == "above_price"
        assert sig.consensus_level == "very_high"
        assert sig.direction_agreement_pct == pytest.approx(85.7, abs=0.1)

    def test_below_price_majority(self, seven_estimator_below):
        values, price = seven_estimator_below
        sig = compute_consensus_signal(values, price)
        assert sig.consensus_direction == "below_price"
        assert sig.direction_agreement_count >= 4

    def test_all_near_price(self, seven_estimator_near):
        values, price = seven_estimator_near
        sig = compute_consensus_signal(values, price)
        assert sig.consensus_direction == "near_price"
        assert sig.direction_agreement_count == 7
        assert sig.consensus_level == "very_high"

    def test_split_when_above_and_below_tie(self):
        # 3 above, 3 below, 0 near at exactly the band edges.
        price = 100.0
        values = {
            "dcf": 130,
            "multiples": 120,
            "analyst": 115,
            "three_stage": 70,
            "ddm": 80,
            "epv": 85,
        }
        sig = compute_consensus_signal(values, price, tolerance_pct=5.0)
        assert sig.consensus_direction == "split"
        assert sig.consensus_level == "dispersed"

    def test_single_estimator_is_dispersed(self):
        price = 100.0
        sig = compute_consensus_signal({"dcf": 150}, price)
        assert sig.total_estimators == 1
        assert sig.consensus_level == "dispersed"


# ─────────────────────────────────────────────────────────────────
# compute_consensus_signal — defensive inputs
# ─────────────────────────────────────────────────────────────────
class TestComputeConsensusSignalDefensive:
    def test_zero_price_returns_dispersed(self):
        sig = compute_consensus_signal({"dcf": 100, "multiples": 120}, 0.0)
        assert sig.total_estimators == 0
        assert sig.consensus_level == "dispersed"
        assert sig.consensus_direction is None
        assert any("price" in w.lower() for w in sig.sanity_warnings)

    def test_negative_price_returns_dispersed(self):
        sig = compute_consensus_signal({"dcf": 100}, -50.0)
        assert sig.total_estimators == 0
        assert sig.consensus_direction is None

    def test_nan_price_returns_dispersed(self):
        sig = compute_consensus_signal({"dcf": 100}, float("nan"))
        assert sig.total_estimators == 0

    def test_inf_price_returns_dispersed(self):
        sig = compute_consensus_signal({"dcf": 100}, float("inf"))
        assert sig.total_estimators == 0

    def test_none_price_returns_dispersed(self):
        sig = compute_consensus_signal({"dcf": 100}, None)  # type: ignore[arg-type]
        assert sig.total_estimators == 0

    def test_empty_estimator_dict(self):
        sig = compute_consensus_signal({}, 100.0)
        assert sig.total_estimators == 0
        assert sig.consensus_level == "dispersed"

    def test_estimator_dict_non_dict(self):
        sig = compute_consensus_signal(None, 100.0)  # type: ignore[arg-type]
        assert sig.total_estimators == 0
        assert sig.consensus_level == "dispersed"

    def test_filters_none_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": 110, "multiples": None, "analyst": 105},
            price := 100.0,
        )
        assert sig.total_estimators == 2

    def test_filters_negative_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": -50, "multiples": 110, "analyst": 105},
            100.0,
        )
        assert sig.total_estimators == 2

    def test_filters_zero_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": 0, "multiples": 110, "analyst": 105},
            100.0,
        )
        assert sig.total_estimators == 2

    def test_filters_nan_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": float("nan"), "multiples": 110},
            100.0,
        )
        assert sig.total_estimators == 1

    def test_filters_inf_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": float("inf"), "multiples": 110},
            100.0,
        )
        assert sig.total_estimators == 1

    def test_filters_non_numeric_estimators(self):
        sig = compute_consensus_signal(
            {"dcf": "bad", "multiples": 110},  # type: ignore[dict-item]
            100.0,
        )
        assert sig.total_estimators == 1

    def test_two_estimator_warning_present(self):
        sig = compute_consensus_signal(
            {"dcf": 105, "multiples": 108}, 100.0
        )
        assert sig.total_estimators == 2
        assert any("Only 2" in w for w in sig.sanity_warnings)
        assert any("low confidence" in w for w in sig.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# tolerance band
# ─────────────────────────────────────────────────────────────────
class TestToleranceBand:
    def test_exactly_at_upper_edge_is_above(self):
        # value == price * 1.05 -> falls into above bucket (>=).
        sig = compute_consensus_signal(
            {"dcf": 105.0, "multiples": 105.0}, 100.0, tolerance_pct=5.0
        )
        assert sig.consensus_direction == "above_price"

    def test_exactly_at_lower_edge_is_below(self):
        sig = compute_consensus_signal(
            {"dcf": 95.0, "multiples": 95.0}, 100.0, tolerance_pct=5.0
        )
        assert sig.consensus_direction == "below_price"

    def test_just_inside_band_is_near(self):
        sig = compute_consensus_signal(
            {"dcf": 104.99, "multiples": 95.01}, 100.0, tolerance_pct=5.0
        )
        assert sig.consensus_direction == "near_price"

    def test_zero_tolerance_treats_everything_directional(self):
        sig = compute_consensus_signal(
            {"dcf": 100.01, "multiples": 99.99}, 100.0, tolerance_pct=0.0
        )
        # 100.01 > 100 -> above; 99.99 < 100 -> below; tie -> split.
        assert sig.consensus_direction == "split"

    def test_huge_tolerance_clamped_to_50(self):
        # tolerance of 500% is clamped to 50%; values at ±40% should be near.
        sig = compute_consensus_signal(
            {"dcf": 140, "multiples": 60}, 100.0, tolerance_pct=500.0
        )
        assert sig.consensus_direction == "near_price"
        assert sig.consensus_level == "very_high"

    def test_negative_tolerance_treated_as_zero(self):
        sig = compute_consensus_signal(
            {"dcf": 100.01}, 100.0, tolerance_pct=-5.0
        )
        # tol clamped to 0 -> 100.01 > 100 -> above.
        assert sig.consensus_direction == "above_price"

    def test_non_numeric_tolerance_defaults_to_five(self):
        sig = compute_consensus_signal(
            {"dcf": 104, "multiples": 102}, 100.0,
            tolerance_pct="bad",  # type: ignore[arg-type]
        )
        # Both inside the default ±5% band.
        assert sig.consensus_direction == "near_price"


# ─────────────────────────────────────────────────────────────────
# magnitude clustering — CV
# ─────────────────────────────────────────────────────────────────
class TestMagnitudeClustering:
    def test_cv_present_for_two_or_more(self, seven_estimator_above):
        values, price = seven_estimator_above
        sig = compute_consensus_signal(values, price)
        assert sig.magnitude_clustering_cv is not None
        assert sig.magnitude_clustering_cv >= 0.0

    def test_cv_none_for_singleton(self):
        sig = compute_consensus_signal({"dcf": 100}, 100.0)
        assert sig.magnitude_clustering_cv is None

    def test_tight_cluster_has_low_cv(self, seven_estimator_near):
        values, price = seven_estimator_near
        sig = compute_consensus_signal(values, price)
        # All values within ±3% of mean -> CV well below 0.05.
        assert sig.magnitude_clustering_cv is not None
        assert sig.magnitude_clustering_cv < 0.05

    def test_wide_dispersion_warning(self):
        # CV > 0.50 -> warning surfaced.
        sig = compute_consensus_signal(
            {"a": 10, "b": 100, "c": 200, "d": 300}, 150.0
        )
        assert sig.magnitude_clustering_cv is not None
        assert sig.magnitude_clustering_cv > 0.50
        assert any("vary widely" in w for w in sig.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# build_headline + to_dict
# ─────────────────────────────────────────────────────────────────
class TestHeadline:
    def test_above_price_grammar(self):
        assert build_headline("very_high", "above_price", 6, 7) == (
            "6 of 7 estimators agree: above current price"
        )

    def test_below_price_grammar(self):
        assert build_headline("high", "below_price", 5, 7) == (
            "5 of 7 estimators agree: below current price"
        )

    def test_near_price_grammar(self):
        assert build_headline("very_high", "near_price", 7, 7) == (
            "7 of 7 estimators agree: near current price"
        )

    def test_split_grammar(self):
        s = build_headline("dispersed", "split", 3, 7)
        assert "split" in s
        assert "3 of 7" in s

    def test_zero_total_grammar(self):
        s = build_headline("dispersed", None, 0, 0)
        assert "No estimators" in s

    def test_singular_estimator_word(self):
        s = build_headline("dispersed", "above_price", 1, 1)
        assert "1 of 1 estimator agree" in s


class TestToDict:
    def test_none_input_returns_stable_shape(self):
        d = to_dict(None)  # type: ignore[arg-type]
        for key in (
            "direction_agreement_count",
            "total_estimators",
            "direction_agreement_pct",
            "magnitude_clustering_cv",
            "consensus_level",
            "consensus_direction",
            "headline",
            "sanity_warnings",
            "estimator_breakdown",
        ):
            assert key in d

    def test_signal_round_trip(self, seven_estimator_above):
        values, price = seven_estimator_above
        sig = compute_consensus_signal(values, price)
        d = to_dict(sig)
        assert d["direction_agreement_count"] == sig.direction_agreement_count
        assert d["consensus_level"] == sig.consensus_level
        assert d["consensus_direction"] == sig.consensus_direction
        assert d["headline"] == sig.headline
        assert isinstance(d["sanity_warnings"], list)
        # estimator_breakdown is filled by build_estimator_breakdown
        # separately; to_dict alone leaves it empty.
        assert d["estimator_breakdown"] == []


class TestEstimatorBreakdown:
    def test_breakdown_matches_signal(self, seven_estimator_above):
        values, price = seven_estimator_above
        breakdown = build_estimator_breakdown(values, price)
        assert len(breakdown) == 7
        # Each item has the required keys.
        for item in breakdown:
            assert set(item.keys()) == {"name", "slot", "value", "direction"}
            assert item["direction"] in {
                "above_price", "below_price", "near_price"
            }
        # 6 above, 1 below — matches the signal.
        above_count = sum(1 for x in breakdown if x["direction"] == "above_price")
        assert above_count == 6

    def test_breakdown_filters_none(self):
        breakdown = build_estimator_breakdown(
            {"dcf": 110, "multiples": None, "analyst": 105}, 100.0
        )
        assert len(breakdown) == 2

    def test_breakdown_empty_on_zero_price(self):
        breakdown = build_estimator_breakdown({"dcf": 110}, 0.0)
        assert breakdown == []

    def test_breakdown_uses_friendly_labels(self):
        breakdown = build_estimator_breakdown(
            {"dcf": 110, "analyst": 105, "probability_weighted": 108},
            100.0,
        )
        labels = {x["name"] for x in breakdown}
        assert "DCF" in labels
        assert "Wall Street" in labels
        assert "Probability-weighted" in labels


# ─────────────────────────────────────────────────────────────────
# SEBI vocab guard on every produced string
# ─────────────────────────────────────────────────────────────────
class TestSebiVocab:
    def test_headlines_clean(self):
        for direction in (
            "above_price", "below_price", "near_price", "split", None,
        ):
            for level in (
                "very_high", "high", "moderate", "low", "dispersed"
            ):
                _assert_sebi_clean(build_headline(level, direction, 4, 7))
                _assert_sebi_clean(build_headline(level, direction, 0, 0))

    def test_full_signal_strings_clean(self, seven_estimator_above):
        values, price = seven_estimator_above
        sig = compute_consensus_signal(values, price)
        _assert_sebi_clean(sig.headline)
        for w in sig.sanity_warnings:
            _assert_sebi_clean(w)

    def test_warnings_clean_on_split(self):
        sig = compute_consensus_signal(
            {"dcf": 200, "multiples": 50}, 100.0
        )
        for w in sig.sanity_warnings:
            _assert_sebi_clean(w)


# ─────────────────────────────────────────────────────────────────
# end-to-end: round-trip on realistic 7-estimator payloads
# ─────────────────────────────────────────────────────────────────
class TestEndToEnd:
    def test_realistic_above_payload_headline_count_matches(
        self, seven_estimator_above
    ):
        values, price = seven_estimator_above
        sig = compute_consensus_signal(values, price)
        m = re.match(r"(\d+) of (\d+) estimators? agree", sig.headline)
        assert m is not None
        assert int(m.group(1)) == sig.direction_agreement_count
        assert int(m.group(2)) == sig.total_estimators

    def test_idempotent(self, seven_estimator_above):
        values, price = seven_estimator_above
        a = compute_consensus_signal(values, price)
        b = compute_consensus_signal(values, price)
        assert a == b

    def test_does_not_raise_on_pathological_inputs(self):
        # Defensive smoke: any mix of bad inputs returns a well-formed signal.
        for price in (0, -1, float("nan"), float("inf"), None):
            for values in (
                {},
                {"x": None},
                {"x": float("nan")},
                {"a": 1, "b": 2, "c": float("inf")},
            ):
                sig = compute_consensus_signal(values, price)  # type: ignore[arg-type]
                assert isinstance(sig, ConsensusSignal)
                _assert_sebi_clean(sig.headline)
