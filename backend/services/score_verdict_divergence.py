"""Score-vs-verdict divergence reconciler (ROOT CAUSE #6, 2026-06-10).

Problem
-------
The analysis page surfaces two trust signals that answer different
questions:

  * **YIQ Score / Grade** (`quality.yieldiq_score`, `quality.grade`)
    is a 0-100 *business-quality* composite — Piotroski + Moat +
    Revenue growth + a small MoS slice + analyst sentiment.
    Question: "Is this a quality business to own?"

  * **Verdict** (`valuation.verdict` + composite-IV-driven MoS)
    is a *price-vs-intrinsic-value* judgment derived from the
    composite intrinsic value vs the live quote.
    Question: "Is the price below intrinsic value right now?"

These can legitimately point opposite directions:

  - HDFCBANK 2026-06: YIQ 40 (Grade C) — post-merger ROE 8.8%
    (vs 16% historical) pulls Piotroski + the quality blend down;
    bull-side verdict surfaces "Undervalued" at 90% confidence
    because composite IV ~ Rs.1,147 vs price Rs.746.

  - A premium compounder (Nestle India, Asian Paints) often shows
    YIQ 75+ (Grade A) with a "Fairly Valued" or "Overvalued" verdict.

Both readings are technically correct. The page presents them
without explaining they measure different things, which confuses
users into reading the divergence as a contradiction.

Architectural fix
-----------------
Do NOT change either formula. This module emits an additive
top-level payload field:

    score_verdict_divergence = {
        "score_percentile": int,        # 0-100 YIQ score
        "verdict_signal":   str,        # "undervalued" | "overvalued" |
                                        # "fairly_valued" | "data_limited"
                                        # | "under_review" | "avoid"
        "diverges":         bool,       # True iff the two signals
                                        # disagree by a meaningful gap
        "explanation":      str,        # ~40-word descriptive copy
                                        # SEBI-clean — no advisory verbs
    }

The frontend renders an explainer caption only when ``diverges`` is
True. When the signals align, the field is still emitted (so admins
can audit the input) but the UI self-hides the caption.

Divergence rule
---------------
"Diverges" is True when EITHER:

  * Quality reads weak (score <= QUALITY_WEAK_THRESHOLD, default 50)
    AND verdict is bullish ("undervalued"), OR
  * Quality reads (score >= QUALITY_STRONG_THRESHOLD, default 70)
    AND verdict is bearish ("overvalued").

The 25-percentile-point gap matches the brief's guidance. We
deliberately do NOT fire on "fairly_valued" / "data_limited" /
"under_review" / "avoid" verdicts — those are non-directional and
the caption would be a non-sequitur.

Field-additive: legacy cached payloads stay valid (the wrapper falls
through cleanly when fields are missing). No CACHE_VERSION bump —
manifest entry ``v_score_verdict_divergence_caption_2026_06_10``
records the additive surface for the invalidation manifest.

SEBI lens
---------
Every copy string is descriptive. No imperative verbs ("buy" /
"sell" / "hold" / "should" / "recommend"), no value-judgement
adjectives ("attractive" / "expensive" / "cheap" / "strong" /
"weak" / "poor"). The explanation cites the two specific numbers
(score percentile + verdict tier) and names the two questions the
signals answer. The frontend caption layer adds its own copy
guard. See ``scripts/check_sebi_words.py`` for the full banlist.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

_log = logging.getLogger("yieldiq.score_verdict_divergence")


# Thresholds — kept module-level so tests can pin them and the
# rule is auditable without reading prose.
QUALITY_WEAK_THRESHOLD: int = 50
QUALITY_STRONG_THRESHOLD: int = 70

# Verdict literals that carry a directional reading. Anything else
# is treated as non-directional and never triggers the caption.
_BULL_VERDICTS: frozenset[str] = frozenset({
    "undervalued",
    "notably_undervalued",
})
_BEAR_VERDICTS: frozenset[str] = frozenset({
    "overvalued",
    "notably_overvalued",
})
_NON_DIRECTIONAL: frozenset[str] = frozenset({
    "fairly_valued",
    "data_limited",
    "under_review",
    "unavailable",
    "avoid",
})


def _normalize_verdict(verdict: Any) -> Optional[str]:
    """Lowercase + dedupe whitespace variants like "Under Review"."""
    if not isinstance(verdict, str) or not verdict.strip():
        return None
    return verdict.strip().lower().replace(" ", "_")


def _clamp_score(value: Any) -> Optional[int]:
    """Coerce a YIQ score to ``int`` in [0, 100], or None on bad input."""
    try:
        s = int(value)
    except (TypeError, ValueError):
        return None
    if s < 0 or s > 100:
        return None
    return s


def _bull_explanation(score: int, verdict: str) -> str:
    """Copy when score is weak AND verdict is bullish.

    Plain English: "the business quality blend reads {score} of 100
    while the price-vs-intrinsic-value verdict reads
    {verdict_human}. Quality and Valuation measure different things;
    they can point in different directions."
    """
    verdict_human = "Undervalued" if "notably" not in verdict else "Notably Undervalued"
    return (
        f"Quality blend reads {score} of 100. Valuation verdict reads "
        f"{verdict_human}. The two answer different questions: business "
        f"quality (ROE, moat, margins, growth) versus price vs intrinsic "
        f"value today. Both readings are informational."
    )


def _bear_explanation(score: int, verdict: str) -> str:
    """Copy when score is high AND verdict is bearish."""
    verdict_human = "Overvalued" if "notably" not in verdict else "Notably Overvalued"
    return (
        f"Quality blend reads {score} of 100. Valuation verdict reads "
        f"{verdict_human}. The two answer different questions: business "
        f"quality (ROE, moat, margins, growth) versus price vs intrinsic "
        f"value today. Both readings are informational."
    )


def _aligned_explanation(score: int, verdict: str) -> str:
    """Copy when score and verdict point the same way.

    Still emitted so admins can audit; the frontend caption self-hides
    when ``diverges`` is False.
    """
    return (
        f"Quality blend reads {score} of 100. Valuation verdict reads "
        f"{verdict.replace('_', ' ').title()}. Both signals point the "
        f"same way."
    )


def compute_score_verdict_divergence(
    yieldiq_score: Any,
    verdict: Any,
    *,
    weak_threshold: int = QUALITY_WEAK_THRESHOLD,
    strong_threshold: int = QUALITY_STRONG_THRESHOLD,
) -> Optional[dict[str, Any]]:
    """Build the score_verdict_divergence payload field.

    Parameters
    ----------
    yieldiq_score
        0-100 quality blend (``QualityOutput.yieldiq_score``).
    verdict
        Backend verdict literal (``ValuationOutput.verdict``) —
        e.g. "undervalued", "fairly_valued", "overvalued",
        "data_limited", "under_review", "unavailable", "avoid".

    Returns
    -------
    dict or None
        ``None`` when either input is unusable (missing / malformed).
        Otherwise a 4-key dict — see module docstring for the
        contract. ``diverges`` is True iff the gap rule fires.

    Notes
    -----
    Pure function. Never raises. Never reads from the DB or the
    network. Safe to call from the response-shaping hot path —
    a single-digit-microsecond cost per call.
    """
    score = _clamp_score(yieldiq_score)
    norm_verdict = _normalize_verdict(verdict)
    if score is None or norm_verdict is None:
        return None

    # Bull divergence: weak quality AND bullish verdict.
    if norm_verdict in _BULL_VERDICTS and score <= weak_threshold:
        return {
            "score_percentile": score,
            "verdict_signal": norm_verdict,
            "diverges": True,
            "explanation": _bull_explanation(score, norm_verdict),
        }
    # Bear divergence: high quality AND bearish verdict.
    if norm_verdict in _BEAR_VERDICTS and score >= strong_threshold:
        return {
            "score_percentile": score,
            "verdict_signal": norm_verdict,
            "diverges": True,
            "explanation": _bear_explanation(score, norm_verdict),
        }
    # Non-directional verdict — never fire the caption.
    if norm_verdict in _NON_DIRECTIONAL:
        return {
            "score_percentile": score,
            "verdict_signal": norm_verdict,
            "diverges": False,
            "explanation": _aligned_explanation(score, norm_verdict),
        }
    # Directional but not divergent — aligned signals.
    return {
        "score_percentile": score,
        "verdict_signal": norm_verdict,
        "diverges": False,
        "explanation": _aligned_explanation(score, norm_verdict),
    }


def divergence_from_payload(payload: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Read the score + verdict out of a dict payload and compute the field.

    Returns ``None`` when the payload shape is malformed. Defensive against
    the legacy and partial-fixture shapes the cache may still hold.
    """
    if not isinstance(payload, Mapping):
        return None
    quality = payload.get("quality") or {}
    valuation = payload.get("valuation") or {}
    if not isinstance(quality, Mapping) or not isinstance(valuation, Mapping):
        return None
    return compute_score_verdict_divergence(
        quality.get("yieldiq_score"),
        valuation.get("verdict"),
    )
