# backend/services/analysis/sebi_filter.py
# ═══════════════════════════════════════════════════════════════
# SEBI IA Regulations 2013 post-filter for LLM-generated summaries.
#
# YieldIQ is NOT a SEBI-registered Investment Advisor. Any language
# that crosses from factual description into advisory/opinion is
# treated as investment advice and is prohibited. This module is
# the single source of truth for:
#
#   1. Banned-word vocabulary (word-boundary, case-insensitive)
#   2. Prompt preamble injected into every LLM call producing text
#      for a retail investor (AI summary, narrative).
#   3. Retry-once-then-fallback orchestration. Callers pass in an
#      LLM-calling closure and a fallback context; this module
#      handles post-filter + retry + deterministic template
#      assembly + the mandatory "Not investment advice" prefix.
#
# Touched by PR-B of the SEBI compliance hardening effort.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import re
from typing import Any, Callable, Optional


# Mandatory prefix prepended to every summary the LLM is allowed to
# produce AND to the deterministic fallback. Not a separate field on
# the response model — part of the summary string itself, by design.
SEBI_PREFIX = "Model-generated description of metrics. Not investment advice."

# System preamble injected at the head of every prompt.
SEBI_SYSTEM_PREAMBLE = (
    "You are generating a factual description of financial metrics. "
    "Do not use subjective language, do not give opinions, do not "
    "recommend actions. Stick to numeric descriptions of the data "
    "provided."
)

# Banned words — SEBI-sensitive vocabulary. Matched case-insensitively
# on word boundaries. Kept in one place so the test suite and the
# runtime filter agree exactly.
BANNED_WORDS: tuple[str, ...] = (
    "appears",
    "should",
    "concern",
    "strength",
    "weakness",
    "buy",
    "sell",
    "hold",
    "outperform",
    "underperform",
    "expensive",
    "cheap",
    "undervalued",
    "overvalued",
    "attractive",
    "poor",
    "strong",
    "weak",
    # Advisory verbs we were already filtering pre-PR; keep them.
    "accumulate",
    "recommend",
    "recommendation",
    # Added 2026-04-25 after a UI string slipped through ("how investable
    # is this business today" appeared in a tooltip on /analysis/{ticker}).
    # The word reads as a directional verdict (i.e. should-you-invest), so
    # it crosses from descriptive into advisory and triggers SEBI IA scope.
    "investable",
    "investability",
)

_BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b",
    re.IGNORECASE,
)


def find_banned(text: str) -> Optional[str]:
    """Return the first banned token found in ``text``, or None."""
    if not text:
        return None
    m = _BANNED_RE.search(text)
    return m.group(0) if m else None


def strip_existing_prefix(text: str) -> str:
    """If the LLM echoed the mandatory prefix, strip it so we only
    add it exactly once downstream."""
    s = (text or "").lstrip()
    if s.startswith(SEBI_PREFIX):
        s = s[len(SEBI_PREFIX):].lstrip()
    return s


def with_prefix(body: str) -> str:
    """Prepend the mandatory prefix to ``body`` as the FIRST sentence
    of the summary (not a separate field)."""
    body = strip_existing_prefix(body).strip()
    if not body:
        return SEBI_PREFIX
    return f"{SEBI_PREFIX} {body}"


def _fmt_num(val: Any, dp: int = 2) -> str:
    if val is None:
        return "n/a"
    try:
        return f"{float(val):.{dp}f}"
    except Exception:
        return "n/a"


def _fmt_pct(val: Any, dp: int = 1) -> str:
    if val is None:
        return "n/a"
    try:
        return f"{float(val):.{dp}f}%"
    except Exception:
        return "n/a"


def _fmt_cagr_pct(val: Any, dp: int = 1) -> str:
    """CAGR comes in as decimal (0.058 = 5.8%). Mirror the same
    guard used in narrative.py — treat |val| >= 1.5 as already in
    percent form."""
    if val is None:
        return "n/a"
    try:
        v = float(val)
        if abs(v) >= 1.5:
            return f"{v:.{dp}f}%"
        return f"{v * 100:.{dp}f}%"
    except Exception:
        return "n/a"


def deterministic_template(ctx: dict) -> str:
    """Deterministic, always-SEBI-safe fallback.

    Constructed so it CANNOT contain any banned word by construction —
    pure numeric description. ``ctx`` keys:
      - company_name, ticker, current_price, fair_value, mos_pct,
        piotroski, moat, rev_cagr_3y, roe
    """
    company_name = ctx.get("company_name") or ctx.get("ticker") or ""
    ticker = ctx.get("ticker") or ""
    body = (
        f"{company_name} ({ticker}) trades at "
        f"{_fmt_num(ctx.get('current_price'))} vs a model fair value of "
        f"{_fmt_num(ctx.get('fair_value'))}, a gap of "
        f"{_fmt_pct(ctx.get('mos_pct'))}. "
        f"Piotroski F-score: "
        f"{ctx.get('piotroski') if ctx.get('piotroski') is not None else 'n/a'}/9. "
        f"Moat label: {ctx.get('moat') or 'unrated'}. "
        f"Revenue CAGR (3y): {_fmt_cagr_pct(ctx.get('rev_cagr_3y'))}. "
        f"Return on equity: {_fmt_pct(ctx.get('roe'))}."
    )
    # Defensive: the template is hand-constructed to be banned-free,
    # but if an upstream label ever leaks (e.g. a custom moat label
    # literally spelled "strong"), strip it to "unrated" rather than
    # emit a banned word. Belt-and-braces.
    while True:
        hit = find_banned(body)
        if not hit:
            break
        body = re.sub(
            r"\b" + re.escape(hit) + r"\b",
            "unrated",
            body,
            flags=re.IGNORECASE,
        )
    return with_prefix(body)


def enforce(
    call_llm: Callable[[Optional[str]], str],
    fallback_ctx: dict,
    *,
    logger: Optional[Any] = None,
    ticker: str = "",
) -> str:
    """Run the LLM, post-filter, retry once, fall back to the template.

    ``call_llm(retry_hint)`` is invoked up to twice:
      - first with ``retry_hint=None``
      - if the first output contains a banned word, a second time
        with ``retry_hint="<banned_word>"`` so the caller can append
        a stricter re-prompt.

    Returns a SEBI-safe string that is guaranteed to:
      - start with SEBI_PREFIX
      - contain no banned word (word-boundary, case-insensitive)
    """
    def _log_info(msg: str) -> None:
        if logger is not None:
            try:
                logger.info(msg)
            except Exception:
                pass

    try:
        first = call_llm(None) or ""
    except Exception as exc:
        _log_info(f"[{ticker}] sebi_filter: first LLM call raised {exc!r}")
        first = ""

    first = strip_existing_prefix(first).strip()
    hit = find_banned(first)
    if first and not hit:
        return with_prefix(first)

    # Retry once with a stricter re-prompt.
    _log_info(
        f"[{ticker}] sebi_filter: retry after banned={hit!r} "
        f"in first output"
    )
    try:
        second = call_llm(hit or "subjective language") or ""
    except Exception as exc:
        _log_info(f"[{ticker}] sebi_filter: retry LLM call raised {exc!r}")
        second = ""

    second = strip_existing_prefix(second).strip()
    hit2 = find_banned(second)
    if second and not hit2:
        return with_prefix(second)

    _log_info(
        f"[{ticker}] sebi_filter: falling back to deterministic "
        f"template (retry banned={hit2!r})"
    )
    return deterministic_template(fallback_ctx)
