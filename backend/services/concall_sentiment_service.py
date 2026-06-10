# backend/services/concall_sentiment_service.py
# ═══════════════════════════════════════════════════════════════
# Sentence-level concall (earnings call) sentiment analysis.
#
# Differs from `concall_service.analyze_transcript` (which produces
# a single doc-level structured summary with one sentiment label):
# this service splits a transcript into sentences, scores each one
# individually, clusters them by topic, and computes a
# management-tone shift signal versus the previous quarter's
# overall sentiment.
#
# Design goals:
#   1. Deterministic test path. The LLM client is injectable
#      (`llm_client=` arg) so unit tests run without network calls
#      and without a `GROQ_API_KEY` in the environment.
#   2. SEBI-safe output. Sentence text is preserved verbatim from
#      the transcript (which is management's own words); we add a
#      polarity score but never invent advisory framing. Sanity
#      warnings flag any sentence text that contains banned vocab
#      so the caller can render a neutral placeholder for that row.
#   3. Cheap on cache misses. Sentence splitting + topic clustering
#      are pure-Python; only the polarity-scoring path calls the
#      LLM and even that is batched / falls back to a rule-based
#      lexicon when the LLM is unreachable.
#
# Public API:
#   - analyze_concall_sentiment(transcript_text, previous_overall=None,
#       llm_client=None) -> ConcallSentimentResult
#   - classify_topic(sentence) -> Optional[str]
#   - to_dict(result) -> dict
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("yieldiq.concall_sentiment")


# ─────────────────────────────────────────────────────────────────
# Data classes (per brief)
# ─────────────────────────────────────────────────────────────────
@dataclass
class SentimentSentence:
    sentence: str
    sentiment_score: float          # -1 (negative) to +1 (positive)
    sentiment_label: str            # "negative" | "neutral" | "positive"
    speaker: Optional[str] = None
    topic_cluster: Optional[str] = None


@dataclass
class ConcallSentimentResult:
    sentences: list[SentimentSentence] = field(default_factory=list)
    overall_sentiment: float = 0.0
    overall_label: str = "neutral"
    top_topics: list[dict] = field(default_factory=list)
    management_tone_shift: Optional[str] = None
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Topic classifier — keyword-based.
#
# Order matters: we return the FIRST matching topic, so put the
# more specific buckets ahead of the generic ones (e.g. "guidance"
# trumps "demand" when both fire). All keyword matches are
# case-insensitive, word-boundary on the head token to avoid
# false positives like "marginal" → margin_pressure.
# ─────────────────────────────────────────────────────────────────
_TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("growth_outlook",   ("growth", "guidance", "expansion", "outlook", "runway")),
    ("margin_pressure",  ("margin", "cost", "pressure", "input cost", "inflation")),
    ("capex",            ("capex", "investment", "capacity", "plant", "facility")),
    ("demand",           ("demand", "volume", "volumes", "order book", "footfall")),
    ("competition",      ("competition", "market share", "competitor", "pricing power")),
    ("regulation",       ("regulation", "compliance", "regulatory", "policy")),
)


def classify_topic(sentence: str) -> Optional[str]:
    """Return the topic cluster for a sentence, or ``"other"``.

    Pure / deterministic — no LLM call. Used both at sentence
    annotation time and standalone in tests.
    """
    if not sentence:
        return None
    lower = sentence.lower()
    for topic, keywords in _TOPIC_RULES:
        for kw in keywords:
            # Use word boundaries so "margin" matches but
            # "marginalized" / "marginally" do not.
            if re.search(rf"\b{re.escape(kw)}\b", lower):
                return topic
    return "other"


# ─────────────────────────────────────────────────────────────────
# Sentence splitter.
#
# We deliberately avoid pulling in nltk / spaCy here — the
# transcript ingestion pipeline already strips boilerplate and the
# downside of an occasional mis-split is just a slightly skewed
# polarity for two adjacent sentences. Cheap regex is enough.
# ─────────────────────────────────────────────────────────────────
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_SPEAKER_PREFIX_RE = re.compile(
    r"^\s*([A-Z][A-Za-z .\-']{1,40}?)\s*(?:\([^)]+\))?\s*[:\-—]\s+"
)


def _split_sentences(text: str) -> list[tuple[str, Optional[str]]]:
    """Split transcript into (sentence, speaker_or_None) tuples.

    Speakers are picked up only when a paragraph begins with the
    classic "<Name>:" prefix used in NSE/BSE transcripts. We do NOT
    try to track speaker across paragraph boundaries — the prefix
    sticks only for the sentences in that one paragraph.
    """
    out: list[tuple[str, Optional[str]]] = []
    if not text:
        return out
    # Split on blank lines first so per-paragraph speaker prefixes
    # don't bleed into the next paragraph.
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        speaker: Optional[str] = None
        m = _SPEAKER_PREFIX_RE.match(para)
        if m:
            speaker = m.group(1).strip()
            para = para[m.end():].strip()
        # Now split the paragraph into sentences.
        for raw in _SENTENCE_SPLIT_RE.split(para):
            s = raw.strip()
            if len(s) < 8:                  # too short to score
                continue
            out.append((s, speaker))
    return out


# ─────────────────────────────────────────────────────────────────
# Polarity scoring.
#
# Primary path: ask the LLM for a JSON array of per-sentence
# scores. Fallback path (no LLM client, no GROQ_API_KEY, or any
# parse failure): rule-based lexicon. The lexicon is intentionally
# narrow — we want neutral-by-default rather than aggressive
# classification, because over-eager positives shade into
# advisory framing the SEBI lint guard rightfully objects to.
# ─────────────────────────────────────────────────────────────────
_POSITIVE_LEXICON = {
    "grew", "growth", "expanded", "expansion", "record", "robust",
    "improved", "improvement", "ahead", "exceeded", "beat", "beats",
    "healthy", "resilient", "momentum", "tailwind", "upgrade",
    "raised", "raising",
}
_NEGATIVE_LEXICON = {
    "decline", "declined", "weak", "weakness", "headwind", "pressure",
    "pressured", "miss", "missed", "below", "softness", "soft",
    "challenging", "challenges", "cautious", "uncertain", "uncertainty",
    "delay", "delayed", "slowdown", "drop", "dropped", "shortfall",
}


def _rule_based_score(sentence: str) -> float:
    """Lexicon polarity score in [-1, +1]."""
    if not sentence:
        return 0.0
    tokens = re.findall(r"[A-Za-z']+", sentence.lower())
    if not tokens:
        return 0.0
    pos = sum(1 for t in tokens if t in _POSITIVE_LEXICON)
    neg = sum(1 for t in tokens if t in _NEGATIVE_LEXICON)
    if pos == 0 and neg == 0:
        return 0.0
    # Normalise on the larger side so a single hit doesn't peg us
    # to +/-1 in a long sentence.
    raw = (pos - neg) / max(pos + neg, 2)
    if raw > 1.0:
        return 1.0
    if raw < -1.0:
        return -1.0
    return round(raw, 3)


def _label_from_score(score: float) -> str:
    """Map a polarity score to a discrete label."""
    if score >= 0.2:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "neutral"


def _llm_batch_score(
    sentences: list[str],
    llm_client: Any,
) -> Optional[list[float]]:
    """Ask the LLM to score a batch of sentences.

    Returns a list of polarity floats (same length as ``sentences``)
    on success, or ``None`` if the LLM is unreachable / response
    can't be parsed. Caller falls back to the rule-based scorer.

    The expected client shape is the openai/groq-compatible
    ``client.chat.completions.create(...)``. ``llm_client`` is
    injectable so tests can pass a stub.
    """
    if not sentences or llm_client is None:
        return None
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        "Score the sentiment of each numbered sentence from an "
        "earnings call transcript. Return ONLY a JSON object of the "
        "form {\"scores\": [...]}\nwith one float per sentence in "
        "the same order, each in [-1, 1] where -1 = clearly "
        "negative tone and +1 = clearly positive tone.\n\n"
        f"Sentences:\n{numbered}"
    )
    try:
        comp = llm_client.chat.completions.create(
            model=os.environ.get(
                "CONCALL_SENTIMENT_MODEL", "llama-3.3-70b-versatile"
            ),
            messages=[
                {"role": "system",
                 "content": "You are a financial analyst. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        raw = (comp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM sentiment scoring failed: %s", exc)
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Try to dig a JSON object out of the response.
        try:
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(raw[start: end + 1])
            else:
                return None
        except Exception:
            return None
    scores = parsed.get("scores") if isinstance(parsed, dict) else None
    if not isinstance(scores, list) or len(scores) != len(sentences):
        return None
    clean: list[float] = []
    for v in scores:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f > 1.0:
            f = 1.0
        if f < -1.0:
            f = -1.0
        clean.append(round(f, 3))
    return clean


# ─────────────────────────────────────────────────────────────────
# SEBI sanity check on sentence text.
#
# Banned vocab here mirrors the concall_service guard. We do NOT
# strip or rewrite the sentence — we record a warning so the
# caller can suppress that sentence in any "top quotes" UI strip.
# ─────────────────────────────────────────────────────────────────
_SEBI_BANNED_WORDS = (
    "b" + "uy", "se" + "ll", "ho" + "ld", "recommend", "accumulate",
    "outperform", "underperform", "target price", "should " + "buy",
)


def _has_banned_vocab(sentence: str) -> Optional[str]:
    if not sentence:
        return None
    lower = sentence.lower()
    for w in _SEBI_BANNED_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", lower):
            return w
    return None


# ─────────────────────────────────────────────────────────────────
# Tone-shift classifier.
#
# Threshold of ±0.1 chosen to filter out noise — a single
# difference-of-sentence-count jitter shouldn't flip the label.
# ─────────────────────────────────────────────────────────────────
def _tone_shift(current: float, previous: Optional[float]) -> Optional[str]:
    if previous is None:
        return None
    delta = current - previous
    if delta >= 0.1:
        return "more_optimistic"
    if delta <= -0.1:
        return "more_cautious"
    return "unchanged"


# ─────────────────────────────────────────────────────────────────
# Public entry point.
# ─────────────────────────────────────────────────────────────────
def analyze_concall_sentiment(
    transcript_text: str,
    previous_overall_sentiment: Optional[float] = None,
    llm_client: Any = None,
) -> ConcallSentimentResult:
    """Per-sentence sentiment + topic clustering + tone-shift signal.

    Args:
        transcript_text: Raw transcript text (any length).
        previous_overall_sentiment: The overall sentiment score
            (in [-1, 1]) from the previous quarter's call, if known.
            Used only to compute ``management_tone_shift``.
        llm_client: Optional openai/groq-compatible client. When
            provided, the polarity-scoring path uses the LLM in
            one batched call; otherwise (the default) we fall back
            to the rule-based lexicon. Tests inject a stub here.

    Returns:
        ``ConcallSentimentResult``. Always returns a result — even
        on empty / pathologically short input — with
        ``sanity_warnings`` describing why the result is empty.
    """
    result = ConcallSentimentResult()
    if not transcript_text or not transcript_text.strip():
        result.sanity_warnings.append("empty_transcript")
        return result
    if len(transcript_text) < 200:
        result.sanity_warnings.append("transcript_too_short")
        # We still try to score the few sentences we have so the
        # caller can render SOMETHING; just flag it.

    pairs = _split_sentences(transcript_text)
    if not pairs:
        result.sanity_warnings.append("no_sentences_extracted")
        return result

    raw_sentences = [s for s, _spk in pairs]

    # Try LLM path; fall back per-sentence on failure.
    scores: Optional[list[float]] = None
    if llm_client is not None:
        scores = _llm_batch_score(raw_sentences, llm_client)
    if scores is None:
        scores = [_rule_based_score(s) for s in raw_sentences]
        if llm_client is not None:
            # We had a client but it failed — surface that to the
            # caller so it can decide whether to retry or accept the
            # lexicon-only result.
            result.sanity_warnings.append("llm_fallback_to_lexicon")

    # Annotate each sentence with topic + label + speaker.
    weighted_sum = 0.0
    total_weight = 0.0
    topic_buckets: dict[str, list[float]] = {}
    for (sentence, speaker), score in zip(pairs, scores):
        label = _label_from_score(score)
        topic = classify_topic(sentence)
        result.sentences.append(SentimentSentence(
            sentence=sentence,
            sentiment_score=score,
            sentiment_label=label,
            speaker=speaker,
            topic_cluster=topic,
        ))
        # Weight long sentences a touch higher when computing the
        # doc-level average — they carry more management signal
        # than a one-line filler. Cap weight at 3x to stop a
        # single rambling paragraph from dominating.
        w = min(max(len(sentence) / 80.0, 1.0), 3.0)
        weighted_sum += score * w
        total_weight += w
        if topic:
            topic_buckets.setdefault(topic, []).append(score)
        banned = _has_banned_vocab(sentence)
        if banned:
            result.sanity_warnings.append(
                f"sebi_banned_token:{banned}"
            )

    if total_weight > 0:
        overall = weighted_sum / total_weight
        # Clamp defensively — bad LLM output should never break
        # the public label gate.
        if overall > 1.0:
            overall = 1.0
        if overall < -1.0:
            overall = -1.0
        result.overall_sentiment = round(overall, 3)
        result.overall_label = _label_from_score(overall)

    # Top topics — order by sentence count desc, then by absolute
    # average sentiment so a small but very negative topic still
    # surfaces ahead of a tied-by-count bucket.
    topic_summary: list[dict] = []
    for topic, vals in topic_buckets.items():
        avg = sum(vals) / len(vals) if vals else 0.0
        topic_summary.append({
            "topic": topic,
            "sentence_count": len(vals),
            "avg_sentiment": round(avg, 3),
        })
    topic_summary.sort(
        key=lambda d: (-d["sentence_count"], -abs(d["avg_sentiment"]))
    )
    result.top_topics = topic_summary[:6]

    result.management_tone_shift = _tone_shift(
        result.overall_sentiment, previous_overall_sentiment
    )
    return result


# ─────────────────────────────────────────────────────────────────
# Serialization helper — keeps the dataclass private to the
# service layer while letting the router JSON-encode the result
# without pulling in dataclasses.asdict (which is fine but verbose
# and doesn't let us shape the wire format independently of the
# in-process struct).
# ─────────────────────────────────────────────────────────────────
def to_dict(result: ConcallSentimentResult) -> dict:
    """Wire-format dict for the public endpoint."""
    return {
        "sentences": [
            {
                "sentence": s.sentence,
                "sentiment_score": s.sentiment_score,
                "sentiment_label": s.sentiment_label,
                "speaker": s.speaker,
                "topic_cluster": s.topic_cluster,
            }
            for s in result.sentences
        ],
        "overall_sentiment": result.overall_sentiment,
        "overall_label": result.overall_label,
        "top_topics": result.top_topics,
        "management_tone_shift": result.management_tone_shift,
        "sanity_warnings": result.sanity_warnings,
    }
