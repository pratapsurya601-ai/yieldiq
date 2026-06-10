"""Tests for backend.services.score_verdict_divergence (ROOT CAUSE #6, 2026-06-10).

Pure-function tests — no DB / network. Covers:

  * HDFCBANK-shape: score 40 + verdict "undervalued" -> diverges True (bull)
  * Premium compounder shape: score 80 + verdict "overvalued" -> diverges True (bear)
  * Aligned bull: score 75 + verdict "undervalued" -> diverges False
  * Aligned bear: score 30 + verdict "overvalued" -> diverges False
  * Non-directional verdicts (data_limited, fairly_valued, under_review,
    unavailable, avoid) never trigger the caption.
  * Malformed inputs (None, NaN, out-of-range) return None.
  * Score percentile bookends (0, 100) round-trip cleanly.
  * SEBI vocab guard: every emitted explanation is clean of the banned
    advisory verbs scanned by scripts/check_sebi_words.py.
"""

from __future__ import annotations

import pytest

from backend.services.score_verdict_divergence import (
    QUALITY_STRONG_THRESHOLD,
    QUALITY_WEAK_THRESHOLD,
    compute_score_verdict_divergence,
    divergence_from_payload,
)


# ── SEBI vocab guard (Pattern B per CLAUDE.md rule #5) ──────────────
# Banned-token list built from fragments so this file passes
# scripts/check_sebi_words.py --diff-only at commit time.
_BANNED_FRAGMENTS = [
    "b" + "uy",
    "se" + "ll",
    "ho" + "ld",
    "re" + "commend",
    "recom" + "mendation",
    "sho" + "uld",
    "che" + "ap",
    "expen" + "sive",
    "out" + "perform",
    "under" + "perform",
    "att" + "ractive",
    "stren" + "gth",
    "weak" + "ness",
    "appe" + "ars",
    "stro" + "ng",
    "we" + "ak",
    "po" + "or",
    "accumu" + "late",
    "investa" + "ble",
    "investabil" + "ity",
    "con" + "cern",
]


def _assert_sebi_clean(text: str) -> None:
    lowered = text.lower()
    for fragment in _BANNED_FRAGMENTS:
        assert fragment not in lowered, (
            f"SEBI vocab guard: explanation contains banned fragment {fragment!r}: {text!r}"
        )


# ── Divergence-detection core ──────────────────────────────────────


def test_hdfcbank_shape_bull_divergence():
    """Score 40 (weak quality) + verdict 'undervalued' -> divergence True.

    Mirrors the prod HDFCBANK 2026-06 reading documented in the ROOT
    CAUSE #6 brief: post-merger ROE 8.8% (vs 16% historical) drags
    quality, while composite IV ~Rs.1,147 vs price Rs.746 lifts the
    valuation verdict to undervalued at 90% confidence.
    """
    result = compute_score_verdict_divergence(40, "undervalued")
    assert result is not None
    assert result["score_percentile"] == 40
    assert result["verdict_signal"] == "undervalued"
    assert result["diverges"] is True
    assert "40 of 100" in result["explanation"]
    assert "Undervalued" in result["explanation"]
    _assert_sebi_clean(result["explanation"])


def test_premium_compounder_shape_bear_divergence():
    """Score 80 (high quality) + verdict 'overvalued' -> divergence True.

    Mirrors a Nestle / Asian Paints / Titan shape — solid Piotroski +
    wide moat -> 80+ quality blend, while composite IV sits below the
    market price -> overvalued verdict.
    """
    result = compute_score_verdict_divergence(80, "overvalued")
    assert result is not None
    assert result["score_percentile"] == 80
    assert result["verdict_signal"] == "overvalued"
    assert result["diverges"] is True
    assert "80 of 100" in result["explanation"]
    assert "Overvalued" in result["explanation"]
    _assert_sebi_clean(result["explanation"])


def test_notably_undervalued_at_low_score_diverges():
    """Same rule applies to the deeper 'notably_undervalued' tier."""
    result = compute_score_verdict_divergence(35, "notably_undervalued")
    assert result is not None
    assert result["diverges"] is True
    assert result["verdict_signal"] == "notably_undervalued"
    assert "Notably Undervalued" in result["explanation"]
    _assert_sebi_clean(result["explanation"])


def test_notably_overvalued_at_high_score_diverges():
    """Same rule applies to the deeper 'notably_overvalued' tier."""
    result = compute_score_verdict_divergence(75, "notably_overvalued")
    assert result is not None
    assert result["diverges"] is True
    assert result["verdict_signal"] == "notably_overvalued"
    assert "Notably Overvalued" in result["explanation"]
    _assert_sebi_clean(result["explanation"])


# ── Aligned signals — caption must self-hide ───────────────────────


def test_aligned_bull_no_divergence():
    """Score 75 + verdict 'undervalued' -> diverges False (aligned)."""
    result = compute_score_verdict_divergence(75, "undervalued")
    assert result is not None
    assert result["diverges"] is False
    assert result["score_percentile"] == 75
    _assert_sebi_clean(result["explanation"])


def test_aligned_bear_no_divergence():
    """Score 30 + verdict 'overvalued' -> diverges False (aligned)."""
    result = compute_score_verdict_divergence(30, "overvalued")
    assert result is not None
    assert result["diverges"] is False
    assert result["score_percentile"] == 30
    _assert_sebi_clean(result["explanation"])


@pytest.mark.parametrize(
    "verdict",
    ["fairly_valued", "data_limited", "under_review", "unavailable", "avoid"],
)
def test_non_directional_verdicts_never_diverge(verdict):
    """Non-directional verdicts always return diverges=False.

    The caption would be a non-sequitur on these — the verdict is not
    saying "above" or "below" intrinsic value, it is saying we cannot
    publish a directional reading at all.
    """
    # Cover both tails — weak and high quality.
    for score in (10, 40, 60, 90):
        result = compute_score_verdict_divergence(score, verdict)
        assert result is not None
        assert result["diverges"] is False, (
            f"score={score}, verdict={verdict} should not diverge"
        )
        _assert_sebi_clean(result["explanation"])


# ── Threshold boundary behaviour ────────────────────────────────────


def test_bull_boundary_exactly_at_weak_threshold():
    """Score == weak_threshold + bullish verdict -> divergence True (<=)."""
    result = compute_score_verdict_divergence(QUALITY_WEAK_THRESHOLD, "undervalued")
    assert result is not None
    assert result["diverges"] is True


def test_bull_boundary_one_above_weak_threshold():
    """Score == weak_threshold + 1 + bullish verdict -> aligned (no caption)."""
    result = compute_score_verdict_divergence(
        QUALITY_WEAK_THRESHOLD + 1, "undervalued"
    )
    assert result is not None
    assert result["diverges"] is False


def test_bear_boundary_exactly_at_strong_threshold():
    """Score == strong_threshold + bearish verdict -> divergence True (>=)."""
    result = compute_score_verdict_divergence(
        QUALITY_STRONG_THRESHOLD, "overvalued"
    )
    assert result is not None
    assert result["diverges"] is True


def test_bear_boundary_one_below_strong_threshold():
    """Score == strong_threshold - 1 + bearish verdict -> aligned (no caption)."""
    result = compute_score_verdict_divergence(
        QUALITY_STRONG_THRESHOLD - 1, "overvalued"
    )
    assert result is not None
    assert result["diverges"] is False


# ── Score percentile bookends + coercion ────────────────────────────


@pytest.mark.parametrize("score", [0, 25, 50, 75, 100])
def test_score_percentile_round_trip(score):
    result = compute_score_verdict_divergence(score, "fairly_valued")
    assert result is not None
    assert result["score_percentile"] == score


# ── Malformed-input guard ───────────────────────────────────────────


@pytest.mark.parametrize(
    "score,verdict",
    [
        (None, "undervalued"),
        (40, None),
        (None, None),
        ("not a number", "undervalued"),
        (40, ""),
        (40, "   "),
        (-5, "undervalued"),       # out of [0,100]
        (101, "undervalued"),      # out of [0,100]
        (float("nan"), "undervalued"),
    ],
)
def test_malformed_inputs_return_none(score, verdict):
    """Defensive: bad inputs degrade to None rather than raising."""
    result = compute_score_verdict_divergence(score, verdict)
    assert result is None


def test_verdict_case_insensitive_and_space_tolerant():
    """'Under Review' (frontend casing with space) normalises cleanly."""
    result = compute_score_verdict_divergence(40, "Under Review")
    assert result is not None
    assert result["verdict_signal"] == "under_review"
    assert result["diverges"] is False


# ── Wrapper that reads from a payload dict ─────────────────────────


def test_divergence_from_payload_hdfcbank_shape():
    payload = {
        "quality": {"yieldiq_score": 40, "grade": "C"},
        "valuation": {"verdict": "undervalued", "confidence_score": 90},
    }
    result = divergence_from_payload(payload)
    assert result is not None
    assert result["diverges"] is True
    assert result["score_percentile"] == 40
    assert result["verdict_signal"] == "undervalued"


def test_divergence_from_payload_aligned_premium():
    payload = {
        "quality": {"yieldiq_score": 85, "grade": "A"},
        "valuation": {"verdict": "fairly_valued", "confidence_score": 80},
    }
    result = divergence_from_payload(payload)
    assert result is not None
    assert result["diverges"] is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"quality": None, "valuation": None},
        {"quality": {}, "valuation": {}},
        {"quality": "not a dict", "valuation": {"verdict": "undervalued"}},
        {"quality": {"yieldiq_score": 40}},      # missing valuation
        {"valuation": {"verdict": "undervalued"}},  # missing quality
    ],
)
def test_divergence_from_payload_degrades_safely(payload):
    """Payload shape failures return None, never raise."""
    result = divergence_from_payload(payload)
    assert result is None
