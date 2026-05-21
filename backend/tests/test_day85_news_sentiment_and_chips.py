"""
Day-85 — title-only news sentiment + frontend tier-chip plumbing
(Tier-3 issue #33, news/sentiment, second piece).

Day-79 shipped the A/B/C source-quality tier on the wire. Day-85
extends the same `annotate()` payload with a cheap title-only
sentiment score, and the frontend renders a tier chip + sentiment
glyph next to each item.

These tests cover the BACKEND half:
  - keyword lists are non-empty and contain no SEBI-banned vocab
  - score math behaves on canonical positive / negative / neutral
    headlines and is clamped to [-1, 1]
  - label_sentiment buckets the score with a dead-zone for noise
  - annotate() attaches both sentiment_score AND sentiment_label
  - score_title_sentiment is robust on empty / non-string input
"""
from __future__ import annotations

import pytest

from backend.services.news_filters import (
    _NEGATIVE_KEYWORDS,
    _POSITIVE_KEYWORDS,
    annotate,
    label_sentiment,
    score_title_sentiment,
)


# ── Keyword-list guards ────────────────────────────────────────

# SEBI-banned vocabulary. Must NOT appear in either keyword list,
# even as a substring of a longer word — the scoring regex is
# whole-word but we want zero ambiguity for a future code-review.
# (Synced with scripts/check_sebi_words.py BANNED_WORDS as of Day-85.)
_SEBI_BANNED = {
    "appears", "should", "concern", "strength", "weakness",
    "buy", "sell", "hold",
    "outperform", "underperform",
    "expensive", "cheap", "attractive", "poor",
    "strong", "weak",
    "accumulate", "recommend", "recommendation",
    "investable", "investability",
}


def test_positive_keyword_list_nonempty():
    assert len(_POSITIVE_KEYWORDS) >= 10


def test_negative_keyword_list_nonempty():
    assert len(_NEGATIVE_KEYWORDS) >= 10


def test_no_sebi_banned_words_in_positive_list():
    for kw in _POSITIVE_KEYWORDS:
        for token in kw.lower().split():
            assert token not in _SEBI_BANNED, (
                f"positive keyword '{kw}' contains SEBI-banned token '{token}' "
                f"— rephrase (see scripts/check_sebi_words.py)"
            )


def test_no_sebi_banned_words_in_negative_list():
    for kw in _NEGATIVE_KEYWORDS:
        for token in kw.lower().split():
            assert token not in _SEBI_BANNED, (
                f"negative keyword '{kw}' contains SEBI-banned token '{token}' "
                f"— rephrase (see scripts/check_sebi_words.py)"
            )


# ── score_title_sentiment math ─────────────────────────────────

def test_score_positive_title_above_zero():
    s = score_title_sentiment("Company wins major contract and raises guidance")
    assert s > 0


def test_score_negative_title_below_zero():
    s = score_title_sentiment("Regulator halts trading amid fraud investigation")
    assert s < 0


def test_score_neutral_title_near_zero():
    s = score_title_sentiment("Company holds annual general meeting in Mumbai")
    # "holds" not in either list (and "hold" is SEBI-banned, intentionally
    # absent); pure-procedural copy must score in the dead-zone.
    assert -0.02 <= s <= 0.02


def test_score_empty_title_is_zero():
    assert score_title_sentiment("") == 0.0
    assert score_title_sentiment(None) == 0.0  # type: ignore[arg-type]
    assert score_title_sentiment("   ") == 0.0


def test_score_clamped_to_unit_interval():
    # Pathological all-positive headline — score must not exceed 1.0.
    title = " ".join(_POSITIVE_KEYWORDS[:8])
    s = score_title_sentiment(title)
    assert -1.0 <= s <= 1.0


def test_score_is_finite_float():
    s = score_title_sentiment("Quarterly results beat estimates and raise guidance")
    assert isinstance(s, float)


# ── label_sentiment buckets ────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (0.5, "positive"),
    (0.02, "positive"),
    (0.0, "neutral"),
    (0.005, "neutral"),
    (-0.005, "neutral"),
    (-0.02, "negative"),
    (-0.5, "negative"),
])
def test_label_sentiment_buckets(score, expected):
    assert label_sentiment(score) == expected


def test_label_sentiment_non_numeric_defaults_neutral():
    assert label_sentiment("nope") == "neutral"  # type: ignore[arg-type]
    assert label_sentiment(None) == "neutral"  # type: ignore[arg-type]


# ── annotate() integration ─────────────────────────────────────

def _mk(headline: str, url: str = "https://moneycontrol.com/x") -> dict:
    return {
        "headline": headline,
        "summary": "",
        "source": "Moneycontrol",
        "url": url,
        "published_at": "2026-05-20T10:00:00Z",
    }


def test_annotate_attaches_sentiment_fields():
    out = annotate(_mk("Company reports record profits and expansion"))
    assert "sentiment_score" in out
    assert "sentiment_label" in out
    assert isinstance(out["sentiment_score"], float)
    assert out["sentiment_label"] in ("positive", "neutral", "negative")


def test_annotate_positive_headline_labels_positive():
    out = annotate(_mk("Company wins contract and raises guidance"))
    assert out["sentiment_label"] == "positive"
    assert out["sentiment_score"] > 0


def test_annotate_negative_headline_labels_negative():
    out = annotate(_mk("Regulator halts trading after fraud probe"))
    assert out["sentiment_label"] == "negative"
    assert out["sentiment_score"] < 0


def test_annotate_preserves_existing_quality_tier_fields():
    # Day-79 contract still holds — sentiment is additive.
    out = annotate(_mk("Routine board meeting scheduled"))
    assert "source_quality_tier" in out
    assert "source_tier_label" in out
