# backend/services/eli15_thesis_service.py
# ═══════════════════════════════════════════════════════════════
# ELI15 thesis service — 3-bullet plain-English explainer of why
# the model produced its verdict for a given ticker.
#
# Composes a structured prompt from cached AnalysisResponse fields
# (price, fair value, scenarios, WACC, growth, moat, confidence,
# sector), calls Anthropic Claude via the existing helper pattern
# (mirrors ar_intel_service / concall_intel_service), then runs
# every returned bullet through the SEBI post-filter to scrub any
# banned vocabulary.
#
# The bullet-level filter mirrors the orchestration in
# backend/services/analysis/sebi_filter.py::enforce:
#   1. Call Claude once with the SEBI-strict system prompt.
#   2. If ANY bullet contains a banned word, retry once with a
#      stricter re-prompt that names the offending word.
#   3. If the retry still trips, fall back to a deterministic
#      template (composed from the same numbers — no LLM).
#
# Cached per (ticker, model_version, generated_date) in the
# eli15_thesis_cache table so duplicate same-day requests do not
# re-hit Claude. LLM cost matters at scale.
#
# CRITICAL: this prose is one of the loudest SEBI-risk surfaces in
# the app. The prompt explicitly bans advisory verbs AND the
# valuation labels ("undervalued"/"overvalued") that the backend
# sebi_filter still bans (the frontend sebi-lint loosened those to
# descriptive-only on 2026-05-17, but the backend post-filter is
# the contract this module honors). The router maps the verdict
# enum into a neutral display phrase before returning to clients.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger("yieldiq.eli15_thesis")

# Versioning — bump PROMPT_VERSION when the system prompt changes.
# The (ticker, model_version, prompt_version, generated_date)
# cache key keeps the previous day's bullets around for audit /
# rollback.
EXTRACTOR_VERSION = "eli15-thesis-v1-anthropic-2026-06-09"
PROMPT_VERSION = 1

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Banned vocabulary — re-exported from the analysis-package SEBI
# filter so this module has no compile-time dep on the package
# (the package __init__ imports screener.moat_engine, which is
# heavy for a simple text-filter import).
# Mirrors backend/services/analysis/sebi_filter.py::BANNED_WORDS.
SEBI_BANNED_WORDS: tuple[str, ...] = (
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
    "accumulate",
    "recommend",
    "recommendation",
    "investable",
    "investability",
)

import re as _re
_BANNED_RE = _re.compile(
    r"\b(" + "|".join(_re.escape(w) for w in SEBI_BANNED_WORDS) + r")\b",
    _re.IGNORECASE,
)


def _find_banned(text: str) -> Optional[str]:
    """Return the first banned token in ``text``, or None."""
    if not text:
        return None
    m = _BANNED_RE.search(text)
    return m.group(0) if m else None


# Long, stable system prompt — candidate for Anthropic prompt
# caching. Hand-tuned so it pushes the model towards observational
# language and away from advisory verbs.
_SYSTEM_PROMPT = (
    "You are explaining a DCF-based stock valuation to a retail "
    "investor in India. Your job is to generate EXACTLY 3 bullets "
    "explaining why the YieldIQ model produced the verdict you are "
    "given — in plain English, using only the numbers provided.\n\n"
    "HARD CONSTRAINTS (SEBI IA Regulations 2013 — non-negotiable):\n"
    "* OBSERVATIONAL language only. NEVER use advisory verbs.\n"
    "* You MUST NOT use any of these words, in any form:\n"
    "  buy, sell, hold, recommend, recommendation, accumulate,\n"
    "  outperform, underperform, should, appears, concern, strength,\n"
    "  weakness, expensive, cheap, undervalued, overvalued,\n"
    "  attractive, poor, strong, weak, investable, investability.\n"
    "* Describe what the model SEES; never tell the user what to do.\n"
    "  Bad:  \"HDFC Bank looks undervalued — buy now.\"\n"
    "  Good: \"HDFC Bank trades at a 53% discount to the model's\n"
    "         base-case fair value of Rs 1,146.\"\n"
    "* IMPORTANT — never cite the live price as a specific number in\n"
    "  the bullets. The live quote moves intraday; the bullet text is\n"
    "  cached per IST day. Instead, frame the gap as a discount or\n"
    "  premium percentage relative to fair value, which stays correct\n"
    "  even as the live quote ticks. Use \"discount to fair value\" when\n"
    "  the model verdict is below fair value, \"premium over fair value\"\n"
    "  when above, and \"in line with fair value\" when the gap is small.\n"
    "* Use the numbers from the context block VERBATIM. Do not invent\n"
    "  metrics that were not supplied.\n"
    "* 2-3 sentences per bullet. Each bullet ends with a period.\n"
    "* No \"in conclusion\" / \"overall\" / \"in summary\" — the\n"
    "  bullets stand on their own.\n"
    "* No markdown formatting inside bullets (no **bold**, no _italic_).\n\n"
    "OUTPUT FORMAT:\n"
    "* Return EXACTLY 3 lines, one bullet per line.\n"
    "* Each line MUST start with the bullet character followed by a\n"
    "  single space, then the bullet text. The bullet character is\n"
    "  the Unicode middot (•) — not a dash, not an asterisk.\n"
    "* No preamble before the first bullet, no closing line after\n"
    "  the third bullet.\n"
)


# ── Verdict mapping ────────────────────────────────────────────
# The Pydantic enum uses {"undervalued", "fairly_valued",
# "overvalued", "avoid", "data_limited", "unavailable"} as wire
# tokens. The backend SEBI filter still bans the literal words
# "undervalued"/"overvalued" inside LLM-generated PROSE; the
# response field carries a neutral, observational label suitable
# for direct display.
_VERDICT_DISPLAY: dict[str, str] = {
    "undervalued": "below model fair value",
    "fairly_valued": "in line with model fair value",
    "overvalued": "above model fair value",
    "avoid": "model declined to value",
    "data_limited": "insufficient data",
    "unavailable": "unavailable",
}


def display_verdict(wire_verdict: str) -> str:
    """Map wire-format verdict to a SEBI-safe display phrase."""
    return _VERDICT_DISPLAY.get(
        (wire_verdict or "").lower(), "unavailable"
    )


# ── Context assembly ───────────────────────────────────────────

@dataclass
class ThesisContext:
    """Numbers the LLM prompt is composed from.

    Sourced from a cached AnalysisResponse. All fields are
    Optional — callers can build the context defensively from a
    payload that may have missing scenarios or confidence sub-
    scores (legacy cached rows).
    """
    ticker: str
    company_name: str = ""
    sector: str = ""
    verdict: str = "unavailable"       # wire-format enum
    verdict_display: str = "unavailable"  # SEBI-safe display label
    current_price: Optional[float] = None
    fair_value: Optional[float] = None
    bear_case: Optional[float] = None
    base_case: Optional[float] = None
    bull_case: Optional[float] = None
    mos_pct: Optional[float] = None
    wacc_pct: Optional[float] = None
    terminal_growth_pct: Optional[float] = None
    fcf_growth_pct: Optional[float] = None
    implied_growth_pct: Optional[float] = None  # market-implied; optional
    moat_label: str = ""
    moat_score: Optional[float] = None
    confidence_pct: Optional[int] = None
    top_confidence_driver: str = ""


def build_context_from_analysis(payload: dict) -> ThesisContext:
    """Build a ThesisContext from a cached AnalysisResponse dict.

    ``payload`` is the dict-form of AnalysisResponse (either the
    Pydantic .model_dump() or a raw row from analysis_cache). Every
    field lookup is defensive — pre-PR cached rows may omit any
    given key.
    """
    ticker = payload.get("ticker", "")
    company = payload.get("company") or {}
    valuation = payload.get("valuation") or {}
    quality = payload.get("quality") or {}
    scenarios = payload.get("scenarios") or {}

    company_name = company.get("company_name") or ticker
    sector = company.get("sector") or ""

    wire_verdict = (valuation.get("verdict") or "unavailable").lower()

    # Scenarios block: prefer scenarios.{bear,base,bull}.iv when
    # present (matches the format honest_card_generator uses); fall
    # back to flat valuation.bear_case/base_case/bull_case (older
    # payloads sometimes have one and not the other).
    def _scenario(name: str) -> Optional[float]:
        block = scenarios.get(name) or {}
        iv = block.get("iv") if isinstance(block, dict) else None
        if iv is None:
            iv = valuation.get(f"{name}_case")
        try:
            return float(iv) if iv is not None else None
        except (TypeError, ValueError):
            return None

    bear = _scenario("bear")
    base = _scenario("base")
    bull = _scenario("bull")

    # Top confidence driver — narrate the highest sub-score so the
    # third bullet has a specific anchor (vs the generic
    # "Confidence is X%"). If sub-scores are all None, leave blank.
    sub_scores: dict[str, Optional[int]] = {
        "data quality": valuation.get("data_quality_score"),
        "model fit": valuation.get("model_confidence_score"),
        "valuation stability": valuation.get("valuation_stability_score"),
    }
    top_driver = ""
    top_val = -1
    for label, val in sub_scores.items():
        if val is None:
            continue
        try:
            iv = int(val)
        except (TypeError, ValueError):
            continue
        if iv > top_val:
            top_val = iv
            top_driver = label

    return ThesisContext(
        ticker=ticker,
        company_name=company_name,
        sector=sector,
        verdict=wire_verdict,
        verdict_display=display_verdict(wire_verdict),
        current_price=_safe_float(valuation.get("current_price")),
        fair_value=_safe_float(valuation.get("fair_value")),
        bear_case=bear,
        base_case=base,
        bull_case=bull,
        mos_pct=_safe_float(valuation.get("margin_of_safety")),
        wacc_pct=_safe_pct(valuation.get("wacc")),
        terminal_growth_pct=_safe_pct(valuation.get("terminal_growth")),
        fcf_growth_pct=_safe_pct(valuation.get("fcf_growth_rate")),
        implied_growth_pct=None,  # reserved for reverse-DCF wiring
        moat_label=quality.get("moat") or "",
        moat_score=_safe_float(quality.get("moat_score")),
        confidence_pct=_safe_int(valuation.get("confidence_score")),
        top_confidence_driver=top_driver,
    )


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_pct(v: Any) -> Optional[float]:
    """Treat anything < 1.5 as decimal (0.098 -> 9.8%); larger as
    already-percent."""
    f = _safe_float(v)
    if f is None:
        return None
    return f * 100.0 if abs(f) < 1.5 else f


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"Rs {v:,.0f}"


def _fmt_pct(v: Optional[float], dp: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{dp}f}%"


def render_user_prompt(ctx: ThesisContext, retry_hint: Optional[str] = None) -> str:
    """Render the per-call user message from the context.

    On retry (``retry_hint`` is the offending banned word from the
    first attempt), append a stricter re-prompt that names the
    banned word explicitly. Mirrors the enforce() pattern in
    backend/services/analysis/sebi_filter.py.
    """
    lines = [
        f"Stock: {ctx.company_name} ({ctx.ticker})",
        f"Verdict: {ctx.verdict_display} (Margin of Safety: {_fmt_pct(ctx.mos_pct)})",
        f"Current Price: {_fmt_money(ctx.current_price)}",
        (
            f"Fair Value Range: {_fmt_money(ctx.bear_case)} (bear) - "
            f"{_fmt_money(ctx.base_case)} (base) - "
            f"{_fmt_money(ctx.bull_case)} (bull)"
        ),
        (
            f"DCF Inputs: WACC {_fmt_pct(ctx.wacc_pct)}, Terminal Growth "
            f"{_fmt_pct(ctx.terminal_growth_pct)}, FCF Growth Rate "
            f"{_fmt_pct(ctx.fcf_growth_pct)}"
        ),
    ]
    if ctx.implied_growth_pct is not None:
        lines.append(
            f"Implied Market Growth: {_fmt_pct(ctx.implied_growth_pct)}"
        )
    if ctx.moat_label:
        moat_line = f"Moat: {ctx.moat_label}"
        if ctx.moat_score is not None:
            moat_line += f" (sub-score: {ctx.moat_score:.0f})"
        lines.append(moat_line)
    if ctx.confidence_pct is not None:
        conf_line = f"Confidence: {ctx.confidence_pct}%"
        if ctx.top_confidence_driver:
            conf_line += f" (top driver: {ctx.top_confidence_driver})"
        lines.append(conf_line)
    if ctx.sector:
        lines.append(f"Sector: {ctx.sector}")

    body = "\n".join(lines)
    body += (
        "\n\nOutput exactly 3 bullets, one per line, each starting "
        "with the middot character followed by a space."
    )
    if retry_hint:
        body += (
            f"\n\nIMPORTANT: your previous attempt contained the "
            f"banned word \"{retry_hint}\". Rewrite WITHOUT using "
            "that word or any other word from the banned list."
        )
    return body


# ── Bullet parsing ─────────────────────────────────────────────

def parse_bullets(raw: str) -> list[str]:
    """Split the model output into bullet strings.

    The system prompt asks for the Unicode middot, but be lenient:
    accept the leading character "*", "-", or "•" as a bullet
    marker. Strip leading/trailing whitespace and empty lines.
    Returns at most 3 bullets; truncates the model if it overflows.
    """
    bullets: list[str] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # Strip bullet markers.
        for marker in ("•", "*", "-", "–"):
            if s.startswith(marker):
                s = s[len(marker):].lstrip()
                break
        # Sometimes Claude returns "1." / "2." prefixes.
        if len(s) >= 2 and s[0].isdigit() and s[1] in (".", ")"):
            s = s[2:].lstrip()
        if s:
            bullets.append(s)
        if len(bullets) >= 3:
            break
    return bullets


# ── Deterministic template fallback ────────────────────────────

def deterministic_template_bullets(ctx: ThesisContext) -> list[str]:
    """Construct 3 SEBI-safe bullets purely from the context.

    Used when:
      * the LLM call fails (network / quota / SDK missing), or
      * both attempts trip the SEBI filter.

    Constructed so the output CANNOT contain a banned word by
    construction — pure numeric description. As a belt-and-braces
    defense, any banned token that leaks through an upstream label
    is substituted with a neutral synonym at the end.

    Bug 7 (P2, 2026-06-09) — bullet 1 used to embed the live current
    price as a specific number ("trades at Rs 735") alongside the
    model fair value. The bullet text is cached per IST day; the live
    quote ticks intraday. The two diverge within minutes, which made
    the hero (live quote) contradict the WHY narrative (cached price)
    every single page render after market open.

    Fix: drop the absolute price from the narrative. Reframe as a
    discount / premium percentage which is invariant to intraday
    quote movement so long as the FAIR value (the cached number) is
    unchanged. The percentage carries the same meaning users care
    about — "how far is the price from where the model thinks it
    belongs" — without forging a specific quote that goes stale.
    """
    name = ctx.company_name or ctx.ticker

    # Bullet 1: discount / premium framing keyed off the wire verdict.
    fv_str = _fmt_money(ctx.fair_value)
    gap_str = _fmt_pct(abs(ctx.mos_pct)) if ctx.mos_pct is not None else "n/a"
    verdict_lc = (ctx.verdict or "").lower()
    if ctx.fair_value is None or ctx.mos_pct is None:
        # Edge case: the model couldn't produce a fair value or MoS.
        # Fall back to a verdict-only sentence; never invent numbers.
        b1 = (
            f"{name} sits at a model verdict of "
            f"{ctx.verdict_display}; the fair value gap is unavailable."
        )
    elif verdict_lc == "undervalued":
        b1 = (
            f"{name} trades at a {gap_str} discount to the model's "
            f"fair value of {fv_str} — the verdict is {ctx.verdict_display}."
        )
    elif verdict_lc == "overvalued":
        b1 = (
            f"{name} trades at a {gap_str} premium over the model's "
            f"fair value of {fv_str} — the verdict is {ctx.verdict_display}."
        )
    elif verdict_lc == "fairly_valued":
        b1 = (
            f"{name} trades in line with the model's fair value "
            f"of {fv_str} (gap {gap_str}) — the verdict is "
            f"{ctx.verdict_display}."
        )
    else:
        # avoid / data_limited / unavailable — describe the verdict
        # state without a directional framing.
        b1 = (
            f"{name} carries a model verdict of {ctx.verdict_display}; "
            f"the model fair value reference is {fv_str}."
        )

    # Bullet 2: DCF inputs and scenario range.
    parts2: list[str] = []
    if ctx.wacc_pct is not None or ctx.fcf_growth_pct is not None:
        parts2.append(
            f"The DCF uses WACC {_fmt_pct(ctx.wacc_pct)} and FCF growth "
            f"{_fmt_pct(ctx.fcf_growth_pct)}"
        )
        if ctx.terminal_growth_pct is not None:
            parts2[-1] += (
                f", with terminal growth at {_fmt_pct(ctx.terminal_growth_pct)}"
            )
        parts2[-1] += "."
    if ctx.bear_case is not None and ctx.bull_case is not None:
        parts2.append(
            f"The scenario range spans {_fmt_money(ctx.bear_case)} (bear) "
            f"to {_fmt_money(ctx.bull_case)} (bull)."
        )
    if not parts2:
        parts2.append(
            "Detailed DCF inputs are unavailable for this ticker."
        )
    b2 = " ".join(parts2)

    # Bullet 3: moat + confidence.
    parts3: list[str] = []
    if ctx.moat_label:
        parts3.append(f"Moat label: {ctx.moat_label}.")
    if ctx.confidence_pct is not None:
        cline = f"Confidence sits at {ctx.confidence_pct}%"
        if ctx.top_confidence_driver:
            cline += f", with {ctx.top_confidence_driver} as the top driver"
        cline += "."
        parts3.append(cline)
    if ctx.sector:
        parts3.append(f"Sector classification: {ctx.sector}.")
    if not parts3:
        parts3.append(
            "Quality and confidence sub-scores are unavailable."
        )
    b3 = " ".join(parts3)

    bullets = [b1, b2, b3]

    # Defensive scrub: replace any leaked banned token with a
    # neutral synonym so the template is banned-free by construction.
    cleaned: list[str] = []
    for b in bullets:
        out = b
        while True:
            hit = _find_banned(out)
            if not hit:
                break
            out = _re.sub(
                r"\b" + _re.escape(hit) + r"\b",
                "rated",
                out,
                flags=_re.IGNORECASE,
            )
        cleaned.append(out)
    return cleaned


# ── Anthropic client + main entry point ────────────────────────

def _build_anthropic_client() -> Optional[Any]:
    """Build a real anthropic.Anthropic client when ANTHROPIC_API_KEY
    is set, else return None.

    Importing the SDK inside the function so the module loads cleanly
    in environments that don't have anthropic installed yet.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as exc:
        logger.warning("anthropic client init failed: %s", exc)
        return None


def _call_claude(
    client: Any,
    ctx: ThesisContext,
    model: str,
    retry_hint: Optional[str] = None,
) -> str:
    """Run one Claude call for the thesis prompt; return raw text."""
    user_prompt = render_user_prompt(ctx, retry_hint=retry_hint)
    response = client.messages.create(
        model=model,
        max_tokens=900,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )
    try:
        return response.content[0].text or ""
    except (AttributeError, IndexError):
        return ""


@dataclass
class ELI15ThesisResult:
    """Return shape of generate_thesis.

    ``bullets`` is always a list of exactly 3 SEBI-safe strings.
    ``source`` documents which path produced the bullets:
      * "llm_first"     — first Claude call passed the filter
      * "llm_retry"     — retry passed the filter
      * "template"      — both attempts tripped, used the template
      * "template_no_llm" — no Claude client available
    """
    bullets: list[str]
    source: str = "template_no_llm"
    model_version: str = EXTRACTOR_VERSION
    prompt_version: int = PROMPT_VERSION
    sanitizer_hits: list[str] = field(default_factory=list)


def generate_thesis(
    ctx: ThesisContext,
    *,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
    call_llm: Optional[Callable[[Optional[str]], str]] = None,
) -> ELI15ThesisResult:
    """Generate the 3-bullet thesis for ``ctx``.

    Behaviour:
      * If ``call_llm`` is supplied (test injection or stub), use it
        as the per-attempt closure. Otherwise build a real Anthropic
        client when ANTHROPIC_API_KEY is set.
      * If no client is available AND no ``call_llm`` was supplied,
        return the deterministic template immediately.
      * Otherwise: one call -> parse 3 bullets -> SEBI scan; if
        clean, return. If dirty, retry once with the banned word as
        a hint; if still dirty, fall back to template.
    """
    # Compose the per-attempt LLM closure.
    if call_llm is None:
        if anthropic_client is None:
            anthropic_client = _build_anthropic_client()
        if anthropic_client is None:
            return ELI15ThesisResult(
                bullets=deterministic_template_bullets(ctx),
                source="template_no_llm",
            )

        def call_llm(hint: Optional[str]) -> str:
            try:
                return _call_claude(
                    anthropic_client, ctx, model, retry_hint=hint
                )
            except Exception as exc:
                logger.warning(
                    "eli15_thesis: Claude call failed for %s: %s",
                    ctx.ticker, exc,
                )
                return ""

    # First attempt.
    raw_first = call_llm(None) or ""
    bullets_first = parse_bullets(raw_first)
    hits_first = _scan_bullets(bullets_first)

    if bullets_first and len(bullets_first) == 3 and not hits_first:
        return ELI15ThesisResult(
            bullets=bullets_first,
            source="llm_first",
            sanitizer_hits=[],
        )

    # Retry once with the first banned word as a hint.
    retry_hint = (
        hits_first[0].split(": ", 1)[1] if hits_first else "subjective language"
    )
    logger.info(
        "eli15_thesis: retry for %s after banned=%r / bullet_count=%d",
        ctx.ticker, retry_hint, len(bullets_first),
    )
    raw_retry = call_llm(retry_hint) or ""
    bullets_retry = parse_bullets(raw_retry)
    hits_retry = _scan_bullets(bullets_retry)

    if bullets_retry and len(bullets_retry) == 3 and not hits_retry:
        return ELI15ThesisResult(
            bullets=bullets_retry,
            source="llm_retry",
            sanitizer_hits=hits_first,
        )

    # Fall back to the deterministic template.
    logger.info(
        "eli15_thesis: template fallback for %s "
        "(first_hits=%s, retry_hits=%s)",
        ctx.ticker, hits_first[:3], hits_retry[:3],
    )
    return ELI15ThesisResult(
        bullets=deterministic_template_bullets(ctx),
        source="template",
        sanitizer_hits=hits_first + hits_retry,
    )


def _scan_bullets(bullets: list[str]) -> list[str]:
    """Walk every bullet and return "bullet[i]: <word>" findings."""
    findings: list[str] = []
    for i, b in enumerate(bullets):
        hit = _find_banned(b)
        if hit:
            findings.append(f"bullet[{i}]: {hit.lower()}")
    return findings


# ── Disclaimer ─────────────────────────────────────────────────

def build_disclaimer(generated_on: date) -> str:
    """Build the inline disclaimer string that every response carries.

    Format: "Generated YYYY-MM-DD. Not advice; for educational use.
    Adjust your own assumptions on the Reverse-DCF Playground."
    """
    return (
        f"Generated {generated_on.isoformat()}. Not advice; for "
        "educational use. Adjust your own assumptions on the "
        "Reverse-DCF Playground."
    )


# ── DB cache: read / write ─────────────────────────────────────
# Keyed by (ticker, model_version, prompt_version, generated_date).
# Day-granularity TTL is enough — the underlying analysis changes
# on the order of hours/days, and Claude cost matters at scale.

# Asia/Kolkata offset for generated_date stamping. Hardcoded
# because the project is single-market (India) and we want the
# day key to roll over at midnight IST, not UTC.
_IST_OFFSET = timedelta(hours=5, minutes=30)


def today_ist() -> date:
    """Return today's calendar date in Asia/Kolkata."""
    return (datetime.now(timezone.utc) + _IST_OFFSET).date()


def get_cached_thesis(
    ticker: str,
    *,
    model_version: str = EXTRACTOR_VERSION,
    prompt_version: int = PROMPT_VERSION,
    generated_on: Optional[date] = None,
) -> Optional[dict]:
    """Read a cached thesis row by (ticker, model, prompt, date).

    Returns the row as a dict, or None on miss / DB unavailable.
    Best-effort — never raises; cache misses degrade open.
    """
    if generated_on is None:
        generated_on = today_ist()
    session = _open_session()
    if session is None:
        return None
    try:
        from sqlalchemy import text
        row = session.execute(text("""
            SELECT bullets, verdict, verdict_display, source,
                   sanitizer_hits, generated_at, model_version,
                   prompt_version
              FROM eli15_thesis_cache
             WHERE ticker = :t
               AND model_version = :mv
               AND prompt_version = :pv
               AND generated_date = :gd
             LIMIT 1
        """), {
            "t": ticker,
            "mv": model_version,
            "pv": prompt_version,
            "gd": generated_on,
        }).mappings().first()
        if row is None:
            return None
        # bullets stored as JSONB list.
        b = row["bullets"]
        if isinstance(b, str):
            try:
                b = json.loads(b)
            except json.JSONDecodeError:
                return None
        if not isinstance(b, list):
            return None
        hits = row.get("sanitizer_hits") or []
        if isinstance(hits, str):
            try:
                hits = json.loads(hits)
            except json.JSONDecodeError:
                hits = []
        return {
            "bullets": [str(x) for x in b][:3],
            "verdict": row.get("verdict") or "",
            "verdict_display": row.get("verdict_display") or "",
            "source": row.get("source") or "",
            "sanitizer_hits": hits,
            "generated_at": row.get("generated_at"),
            "model_version": row.get("model_version") or model_version,
            "prompt_version": row.get("prompt_version") or prompt_version,
        }
    except Exception as exc:
        logger.warning("get_cached_thesis failed for %s: %s", ticker, exc)
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass


def save_cached_thesis(
    ticker: str,
    result: ELI15ThesisResult,
    ctx: ThesisContext,
    *,
    generated_on: Optional[date] = None,
) -> bool:
    """UPSERT a thesis row keyed by (ticker, model, prompt, date).

    Best-effort — returns False on DB unavailable; never raises.
    """
    if generated_on is None:
        generated_on = today_ist()
    session = _open_session()
    if session is None:
        return False
    try:
        from sqlalchemy import text
        session.execute(text("""
            INSERT INTO eli15_thesis_cache (
                ticker, model_version, prompt_version, generated_date,
                bullets, verdict, verdict_display, source,
                sanitizer_hits, generated_at
            ) VALUES (
                :t, :mv, :pv, :gd,
                CAST(:b AS JSONB), :v, :vd, :src,
                CAST(:sh AS JSONB), NOW()
            )
            ON CONFLICT (ticker, model_version, prompt_version, generated_date)
            DO UPDATE SET
                bullets         = EXCLUDED.bullets,
                verdict         = EXCLUDED.verdict,
                verdict_display = EXCLUDED.verdict_display,
                source          = EXCLUDED.source,
                sanitizer_hits  = EXCLUDED.sanitizer_hits,
                generated_at    = NOW()
        """), {
            "t": ticker,
            "mv": result.model_version,
            "pv": result.prompt_version,
            "gd": generated_on,
            "b": json.dumps(result.bullets),
            "v": ctx.verdict,
            "vd": ctx.verdict_display,
            "src": result.source,
            "sh": json.dumps(result.sanitizer_hits or []),
        })
        session.commit()
        return True
    except Exception as exc:
        logger.warning("save_cached_thesis failed for %s: %s", ticker, exc)
        try:
            session.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            session.close()
        except Exception:
            pass


def _open_session():
    """Return an SQLAlchemy session or None when DB is unavailable.

    Defers the import so this module loads cleanly when neither
    the pipeline DB layer nor SQLAlchemy is on the path (unit tests
    monkeypatch get_cached_thesis / save_cached_thesis directly).
    """
    try:
        from backend.services.analysis.db import _get_pipeline_session
    except Exception as exc:
        logger.debug("eli15_thesis: db import failed (%s)", exc)
        return None
    return _get_pipeline_session()
