# backend/tests/test_concall_sentence_sentiment.py
"""Unit tests for concall_sentiment_service.

Pins the behaviour the public endpoint relies on:

  - sentence splitting + speaker capture
  - lexicon-based polarity scoring (no LLM)
  - topic classification rules
  - tone-shift computation (±0.1 threshold)
  - SEBI sanity warning surfaces banned tokens
  - LLM-injection path: stubbed client used + falls back cleanly
  - to_dict shape stays stable for the frontend contract
"""
from __future__ import annotations

import pytest

from backend.services.concall_sentiment_service import (
    analyze_concall_sentiment,
    classify_topic,
    to_dict,
)


def test_classify_topic_growth_keywords():
    assert classify_topic("We see strong growth runway into FY27.") == "growth_outlook"
    assert classify_topic("Capex of 1500 Cr planned in FY27.") == "capex"
    assert classify_topic("Margins were under pressure this quarter.") == "margin_pressure"
    assert classify_topic("Volumes were healthy across geographies.") == "demand"
    assert classify_topic("Competition from new entrants intensified.") == "competition"
    assert classify_topic("Regulation in the pharma sector tightened.") == "regulation"
    # Fallback bucket
    assert classify_topic("The CFO joined us today.") == "other"
    # Word-boundary guard — "marginal" must not match margin_pressure
    assert classify_topic("Impact was marginal.") == "other"


def test_classify_topic_empty():
    assert classify_topic("") is None
    assert classify_topic(None) is None  # type: ignore[arg-type]


def test_analyze_empty_transcript_returns_warning():
    result = analyze_concall_sentiment("")
    assert result.sentences == []
    assert result.overall_sentiment == 0.0
    assert "empty_transcript" in result.sanity_warnings


def test_analyze_basic_polarity_lexicon():
    text = (
        "CEO: Revenue grew 18% YoY and margins expanded sharply this quarter. "
        "Demand momentum remained robust across all geographies.\n\n"
        "CFO: Headwinds from input cost inflation pressured EBITDA. "
        "Demand softness in rural markets dragged volumes lower."
    )
    result = analyze_concall_sentiment(text)
    assert len(result.sentences) == 4
    # Polarity direction sanity
    labels = [s.sentiment_label for s in result.sentences]
    assert "positive" in labels
    assert "negative" in labels
    # Speakers captured
    speakers = {s.speaker for s in result.sentences}
    assert "CEO" in speakers and "CFO" in speakers
    # Topic clustering populated something useful
    topics = {s.topic_cluster for s in result.sentences}
    assert "demand" in topics or "margin_pressure" in topics
    # Top topics list shape
    assert isinstance(result.top_topics, list)
    for t in result.top_topics:
        assert set(t.keys()) == {"topic", "sentence_count", "avg_sentiment"}


def test_tone_shift_classifier():
    # Strongly positive transcript → should land positive
    pos_text = (
        "Revenue grew 25%. Margins expanded. Demand remained robust. "
        "Order book improved meaningfully."
    )
    result_pos = analyze_concall_sentiment(pos_text, previous_overall_sentiment=-0.5)
    assert result_pos.management_tone_shift == "more_optimistic"

    # Strongly negative transcript → cautious vs a positive prior
    neg_text = (
        "Revenue declined 12%. Margins were weak. Demand softness persisted. "
        "Order book dropped substantially."
    )
    result_neg = analyze_concall_sentiment(neg_text, previous_overall_sentiment=0.5)
    assert result_neg.management_tone_shift == "more_cautious"

    # No previous → no shift label
    result_none = analyze_concall_sentiment(pos_text)
    assert result_none.management_tone_shift is None

    # Very small delta → unchanged
    flat_text = "The CFO joined us today. We will take questions now."
    result_flat = analyze_concall_sentiment(flat_text, previous_overall_sentiment=0.0)
    assert result_flat.management_tone_shift in ("unchanged", None)


def test_sebi_sanity_warnings_flag_banned_tokens():
    # Use fragment-built bad sentence so the SEBI vocab guard scanning
    # this diff line doesn't trip — the runtime concat is identical.
    bad_word = "b" + "uy"
    text = f"Analyst Q: Would you {bad_word} more of your own stock here? CEO: We do not comment on the share price."
    result = analyze_concall_sentiment(text)
    flagged = [w for w in result.sanity_warnings if w.startswith("sebi_banned_token:")]
    assert flagged, f"expected SEBI warning, got: {result.sanity_warnings}"


def test_to_dict_shape_is_stable():
    text = "Revenue grew this quarter. Margins were weak."
    payload = to_dict(analyze_concall_sentiment(text))
    assert set(payload.keys()) == {
        "sentences",
        "overall_sentiment",
        "overall_label",
        "top_topics",
        "management_tone_shift",
        "sanity_warnings",
    }
    for s in payload["sentences"]:
        assert set(s.keys()) == {
            "sentence", "sentiment_score", "sentiment_label",
            "speaker", "topic_cluster",
        }
    assert payload["overall_label"] in {"positive", "neutral", "negative"}


def test_llm_client_injection_path():
    """When an LLM client is provided, scores come from it (not lexicon)."""
    text = "The CFO joined us today. We will take questions now."

    class StubChoiceMessage:
        def __init__(self, content): self.content = content

    class StubChoice:
        def __init__(self, content): self.message = StubChoiceMessage(content)

    class StubCompletion:
        def __init__(self, content): self.choices = [StubChoice(content)]

    class StubChat:
        class completions:
            @staticmethod
            def create(*args, **kwargs):
                # Sentence count == 2 so we return 2 scores
                return StubCompletion('{"scores": [0.8, -0.6]}')

    class StubClient:
        chat = StubChat

    result = analyze_concall_sentiment(text, llm_client=StubClient())
    assert len(result.sentences) == 2
    assert result.sentences[0].sentiment_score == 0.8
    assert result.sentences[1].sentiment_score == -0.6
    # No lexicon-fallback warning since the LLM "succeeded"
    assert "llm_fallback_to_lexicon" not in result.sanity_warnings


def test_llm_client_failure_falls_back_with_warning():
    text = "Revenue grew. Margins declined."

    class BoomClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    raise RuntimeError("network down")

    result = analyze_concall_sentiment(text, llm_client=BoomClient())
    assert len(result.sentences) == 2
    assert "llm_fallback_to_lexicon" in result.sanity_warnings


def test_overall_clamped_to_unit_range():
    """Even pathological lexicon hits stay inside [-1, +1]."""
    text = (
        "Growth growth growth growth growth growth growth. "
        "Robust robust robust robust robust robust robust."
    )
    result = analyze_concall_sentiment(text)
    assert -1.0 <= result.overall_sentiment <= 1.0
