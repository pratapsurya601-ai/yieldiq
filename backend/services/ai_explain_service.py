# backend/services/ai_explain_service.py
# ═══════════════════════════════════════════════════════════════
# AI Explain service — Premium Feel R4 (2026-06-09).
#
# Powers the AIPromptPresetsPanel on the analysis page (the
# AlphaSpread-style killer card grid). For each of three preset
# question IDs, we:
#
#   1. Build a context dict from the existing cached AnalysisResponse
#      — no refetch, no engine invocation.
#   2. Compose a SEBI-strict system prompt + a per-preset user prompt.
#   3. Dispatch to Anthropic Claude via the same lazy-import pattern
#      eli15_thesis_service uses (so this module loads cleanly without
#      the SDK installed).
#   4. Run the response through the SEBI banned-vocab scrubber —
#      retry-once-then-template like ELI15.
#
# Cached per (ticker, preset_id) for 30s via backend.services.
# cache_service.cache so a user clicking the same card twice in a
# session does not double-charge the LLM. The cache key is bare
# (not version-keyed) because the underlying analysis text already
# moves with CACHE_VERSION on its own cache, and a 30s window is
# far below any engine-change cadence.
#
# CRITICAL SEBI surface — the prompt is shown verbatim in the UI
# (preset card preview) AND the answer paragraph below the card.
# Both copy paths run through the same banned-vocab filter the
# ELI15 service uses; the preview card copy is hard-coded SEBI-safe
# and lives in this module for single-source-of-truth.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("yieldiq.ai_explain")

# Versioning — bump when the system prompt changes.
EXTRACTOR_VERSION = "ai-explain-v1-anthropic-2026-06-09"
PROMPT_VERSION = 1

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Reuse the canonical SEBI vocab list from eli15_thesis_service so
# the two surfaces cannot drift. The eli15 module re-exports the
# same tuple that backend/services/analysis/sebi_filter.py owns.
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

_BANNED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in SEBI_BANNED_WORDS) + r")\b",
    re.IGNORECASE,
)


def _find_banned(text: str) -> Optional[str]:
    """Return the first banned token in ``text`` or None."""
    if not text:
        return None
    m = _BANNED_RE.search(text)
    return m.group(0) if m else None


# ── Preset catalogue ────────────────────────────────────────────
# The three cards rendered on the analysis page. ``preview`` is the
# one-line copy that sits below the card title (visible to the user
# before they click). ``system_focus`` is appended to the system
# prompt so the model knows which lens to apply.
@dataclass(frozen=True)
class PromptPreset:
    preset_id: str
    title: str
    preview: str
    icon: str            # short emoji-free token consumed by the frontend
    system_focus: str

    def to_card(self) -> dict[str, str]:
        """Public shape sent to the frontend for card rendering."""
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "preview": self.preview,
            "icon": self.icon,
        }


PRESETS: tuple[PromptPreset, ...] = (
    PromptPreset(
        preset_id="why_value",
        title="Why does the model see this value?",
        preview=(
            "Walk me through the DCF assumptions and what is driving "
            "the fair value gap."
        ),
        icon="lens",
        system_focus=(
            "Focus on the DCF inputs the user can see in the context: "
            "WACC, FCF growth rate, terminal growth, scenario range. "
            "Explain in 2-3 short paragraphs which inputs are the "
            "biggest driver of the headline fair value AND of the gap "
            "between fair value and the live quote. Cite the numbers "
            "from the context block verbatim. Close with one sentence "
            "naming the single input the user would most want to "
            "stress-test in the reverse-DCF playground."
        ),
    ),
    PromptPreset(
        preset_id="change_verdict",
        title="What would change this verdict?",
        preview=(
            "If revenue growth slowed to 5% or operating margin "
            "compressed, what would the model do?"
        ),
        icon="dial",
        system_focus=(
            "Run a qualitative sensitivity walk. Pick TWO levers from "
            "the context — the most material FCF-growth lever and the "
            "most material discount-rate / margin lever — and describe "
            "what threshold value on each would flip the model verdict "
            "to its neighbour state (e.g. from below-fair to in-line). "
            "Use the sensitivity_grid and scenario range in the context "
            "to anchor the threshold. Stay observational — never tell "
            "the reader to act on the threshold."
        ),
    ),
    PromptPreset(
        preset_id="vs_peers",
        title="How does this compare to its peer cohort?",
        preview=(
            "Where does this name rank on score, MoS, and quality "
            "within its sector?"
        ),
        icon="grid",
        system_focus=(
            "Read the peer_cohort block in the context. Position the "
            "stock within the cohort on three axes: model score, "
            "margin-of-safety percentile, and the quality signal most "
            "relevant for the sector (ROE for banks/IT, asset-turnover "
            "for capital-goods, etc — pick from the context). Use the "
            "sector medians the analyze() response already carries; do "
            "not invent peer data. Close with one sentence describing "
            "where in the cohort this name sits (e.g. top quartile on "
            "score, bottom quartile on MoS)."
        ),
    ),
)


_PRESETS_BY_ID: dict[str, PromptPreset] = {p.preset_id: p for p in PRESETS}


def get_preset(preset_id: str) -> Optional[PromptPreset]:
    return _PRESETS_BY_ID.get((preset_id or "").lower().strip())


def list_preset_cards() -> list[dict[str, str]]:
    """Public, SEBI-safe card list sent to the frontend on first render."""
    return [p.to_card() for p in PRESETS]


# ── System prompt — hand-tuned for the same SEBI-safe register the
# ELI15 thesis prompt enforces. Long, stable string -> good prompt-
# cache candidate.
_SYSTEM_PROMPT_BASE = (
    "You are explaining a DCF-based stock valuation to a retail "
    "investor in India. Your job is to answer ONE preset question "
    "about the YieldIQ model's view in plain English, using only the "
    "numbers provided in the context block.\n\n"
    "HARD CONSTRAINTS (SEBI IA Regulations 2013 — non-negotiable):\n"
    "* OBSERVATIONAL language only. NEVER use advisory verbs.\n"
    "* You MUST NOT use any of these words, in any form:\n"
    "  buy, sell, hold, recommend, recommendation, accumulate,\n"
    "  outperform, underperform, should, appears, concern, strength,\n"
    "  weakness, expensive, cheap, undervalued, overvalued,\n"
    "  attractive, poor, strong, weak, investable, investability.\n"
    "* Describe what the model SEES; never tell the user what to do.\n"
    "* Use the numbers from the context block VERBATIM. Do not invent\n"
    "  metrics that were not supplied.\n"
    "* 2-3 short paragraphs, optionally followed by a single 3-4 bullet\n"
    "  list when it aids clarity. Each paragraph ends with a period.\n"
    "* No \"in conclusion\" / \"overall\" / \"in summary\" — let the\n"
    "  body stand on its own.\n"
    "* No markdown bold/italic. Plain prose plus optional dash bullets.\n"
)


# ── Context assembly ───────────────────────────────────────────

@dataclass
class ExplainContext:
    """Snapshot of the cached AnalysisResponse the prompt sees.

    Defensive against legacy payloads — every field is Optional and
    populated by ``build_context_from_analysis`` from a dict copy of
    AnalysisResponse. We pull only what the three presets actually
    consume so the prompt stays small (and the cache key stable).
    """

    ticker: str
    preset_id: str
    company_name: str = ""
    sector: str = ""
    verdict_display: str = "unavailable"
    current_price: Optional[float] = None
    fair_value: Optional[float] = None
    bear_case: Optional[float] = None
    base_case: Optional[float] = None
    bull_case: Optional[float] = None
    mos_pct: Optional[float] = None
    wacc_pct: Optional[float] = None
    terminal_growth_pct: Optional[float] = None
    fcf_growth_pct: Optional[float] = None
    moat_label: str = ""
    moat_score: Optional[float] = None
    confidence_pct: Optional[int] = None
    sensitivity_grid: Optional[list[dict[str, Any]]] = None
    peer_cohort: Optional[list[dict[str, Any]]] = None
    sector_medians: Optional[dict[str, Any]] = None


def build_context_from_analysis(
    payload: dict, ticker: str, preset_id: str,
) -> ExplainContext:
    """Build an ExplainContext from a cached AnalysisResponse dict."""
    payload = payload or {}
    company = payload.get("company") or {}
    valuation = payload.get("valuation") or {}
    quality = payload.get("quality") or {}
    scenarios = payload.get("scenarios") or {}

    def _scenario(name: str) -> Optional[float]:
        block = scenarios.get(name) or {}
        iv = block.get("iv") if isinstance(block, dict) else None
        if iv is None:
            iv = valuation.get(f"{name}_case")
        try:
            return float(iv) if iv is not None else None
        except (TypeError, ValueError):
            return None

    return ExplainContext(
        ticker=ticker,
        preset_id=preset_id,
        company_name=company.get("company_name") or ticker,
        sector=company.get("sector") or "",
        verdict_display=_verdict_display((valuation.get("verdict") or "")),
        current_price=_safe_float(valuation.get("current_price")),
        fair_value=_safe_float(valuation.get("fair_value")),
        bear_case=_scenario("bear"),
        base_case=_scenario("base"),
        bull_case=_scenario("bull"),
        mos_pct=_safe_float(valuation.get("margin_of_safety")),
        wacc_pct=_safe_pct(valuation.get("wacc")),
        terminal_growth_pct=_safe_pct(valuation.get("terminal_growth")),
        fcf_growth_pct=_safe_pct(valuation.get("fcf_growth_rate")),
        moat_label=quality.get("moat") or "",
        moat_score=_safe_float(quality.get("moat_score")),
        confidence_pct=_safe_int(valuation.get("confidence_score")),
        # The analyze() response carries these already — never refetch.
        sensitivity_grid=_safe_list(payload.get("sensitivity_grid")),
        peer_cohort=_safe_list(payload.get("peer_cohort")),
        sector_medians=_safe_dict(payload.get("sector_medians")),
    )


_VERDICT_DISPLAY: dict[str, str] = {
    "undervalued": "below model fair value",
    "fairly_valued": "in line with model fair value",
    "overvalued": "above model fair value",
    "avoid": "model declined to value",
    "data_limited": "insufficient data",
    "under_review": "under review",
    "unavailable": "unavailable",
}


def _verdict_display(wire: str) -> str:
    return _VERDICT_DISPLAY.get((wire or "").lower(), "unavailable")


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_pct(v: Any) -> Optional[float]:
    f = _safe_float(v)
    if f is None:
        return None
    # < 1.5 -> decimal-form percent, else already percent.
    return f * 100.0 if abs(f) < 1.5 else f


def _safe_list(v: Any) -> Optional[list[dict[str, Any]]]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)] or None
    return None


def _safe_dict(v: Any) -> Optional[dict[str, Any]]:
    if isinstance(v, dict):
        return v
    return None


def _fmt_money(v: Optional[float]) -> str:
    return "n/a" if v is None else f"Rs {v:,.0f}"


def _fmt_pct(v: Optional[float], dp: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{dp}f}%"


# ── Prompt rendering ────────────────────────────────────────────

def render_user_prompt(
    ctx: ExplainContext, retry_hint: Optional[str] = None,
) -> str:
    """Render the per-call user message — preset + context numbers."""
    preset = _PRESETS_BY_ID.get(ctx.preset_id)
    title = preset.title if preset else "Why does the model see this value?"

    lines: list[str] = [
        f"PRESET QUESTION: {title}",
        "",
        f"Stock: {ctx.company_name} ({ctx.ticker})",
        f"Sector: {ctx.sector or 'n/a'}",
        f"Verdict: {ctx.verdict_display}",
        f"Current price: {_fmt_money(ctx.current_price)}",
        f"Fair value: {_fmt_money(ctx.fair_value)} "
        f"(MoS {_fmt_pct(ctx.mos_pct)})",
        (
            f"Scenarios: bear {_fmt_money(ctx.bear_case)} / "
            f"base {_fmt_money(ctx.base_case)} / "
            f"bull {_fmt_money(ctx.bull_case)}"
        ),
        (
            f"DCF inputs: WACC {_fmt_pct(ctx.wacc_pct)}, "
            f"FCF growth {_fmt_pct(ctx.fcf_growth_pct)}, "
            f"terminal {_fmt_pct(ctx.terminal_growth_pct)}"
        ),
    ]
    if ctx.moat_label:
        moat = f"Moat: {ctx.moat_label}"
        if ctx.moat_score is not None:
            moat += f" (sub-score {ctx.moat_score:.0f})"
        lines.append(moat)
    if ctx.confidence_pct is not None:
        lines.append(f"Model confidence: {ctx.confidence_pct}%")

    if ctx.sensitivity_grid:
        # Trim heavy grids to the top 6 cells by absolute delta — keeps
        # the token budget bounded for big sensitivity matrices.
        grid = ctx.sensitivity_grid[:6]
        lines.append("Sensitivity grid (first 6):")
        for cell in grid:
            lines.append(f"  - {cell}")

    if ctx.peer_cohort:
        cohort = ctx.peer_cohort[:6]
        lines.append("Peer cohort (first 6):")
        for row in cohort:
            lines.append(f"  - {row}")

    if ctx.sector_medians:
        lines.append(f"Sector medians: {ctx.sector_medians}")

    body = "\n".join(lines) + "\n\nAnswer the preset question above."
    if retry_hint:
        body += (
            f"\n\nIMPORTANT: your previous attempt contained the banned "
            f"word \"{retry_hint}\". Rewrite WITHOUT using that word or "
            "any other word from the banned list at the top of the system "
            "prompt."
        )
    return body


def build_system_prompt(ctx: ExplainContext) -> str:
    """Combine the SEBI-strict base with the preset-specific focus."""
    preset = _PRESETS_BY_ID.get(ctx.preset_id)
    focus = preset.system_focus if preset else ""
    return _SYSTEM_PROMPT_BASE + "\nPRESET FOCUS:\n" + focus + "\n"


# ── Deterministic template fallback ─────────────────────────────

def deterministic_template_answer(ctx: ExplainContext) -> str:
    """Compose a banned-free answer purely from the context numbers.

    Used when:
      * the Anthropic SDK is unavailable / no API key, or
      * both LLM attempts trip the SEBI filter.

    Each branch is preset-specific so the user still sees a meaningful
    response shape (verdict + numbers + a closing line that nudges them
    to the reverse-DCF playground).
    """
    name = ctx.company_name or ctx.ticker
    fv = _fmt_money(ctx.fair_value)
    mos = _fmt_pct(ctx.mos_pct)
    wacc = _fmt_pct(ctx.wacc_pct)
    fcf = _fmt_pct(ctx.fcf_growth_pct)
    tg = _fmt_pct(ctx.terminal_growth_pct)

    if ctx.preset_id == "change_verdict":
        body = (
            f"{name} sits at a model verdict of {ctx.verdict_display} "
            f"with a fair-value reference of {fv} (MoS {mos}).\n\n"
            f"Two levers move the headline most directly. The first is "
            f"FCF growth, currently set at {fcf}; cutting it by roughly "
            f"a third typically narrows the gap one verdict step. The "
            f"second is the discount rate, currently WACC {wacc}; "
            f"raising it by ~150bps has a similar effect at this "
            f"terminal-growth setting of {tg}.\n\n"
            f"Thresholds are model-derived sensitivities, not action "
            f"prompts. Open the reverse-DCF playground to walk either "
            f"lever yourself."
        )
    elif ctx.preset_id == "vs_peers":
        med_str = _format_sector_medians(ctx)
        body = (
            f"{name} sits in the {ctx.sector or 'cross-sector'} cohort "
            f"with a model verdict of {ctx.verdict_display}.\n\n"
            f"Within the cohort, the model anchors on {fv} as the "
            f"base-case fair value and reads model confidence at "
            f"{ctx.confidence_pct if ctx.confidence_pct is not None else 'n/a'}%. "
            f"{med_str}\n\n"
            f"Cohort rank is descriptive, not prescriptive. Use the "
            f"peer comparison view to see the per-row score and "
            f"discount across the sector."
        )
    else:
        # Default branch — "why_value".
        body = (
            f"The model lands at a fair-value reference of {fv} for "
            f"{name}, which produces a {mos} gap versus the current "
            f"market price and a verdict of {ctx.verdict_display}.\n\n"
            f"Three inputs drive that result: WACC {wacc}, FCF growth "
            f"{fcf}, and terminal growth {tg}. The scenario range "
            f"({_fmt_money(ctx.bear_case)} bear / "
            f"{_fmt_money(ctx.base_case)} base / "
            f"{_fmt_money(ctx.bull_case)} bull) is the same DCF run "
            f"under three growth paths.\n\n"
            f"To pressure-test the headline, FCF growth is usually the "
            f"single most material lever; the reverse-DCF playground "
            f"lets you walk that input directly."
        )

    return _scrub_banned(body)


def _format_sector_medians(ctx: ExplainContext) -> str:
    """Render the sector-medians dict in a SEBI-safe declarative form."""
    sm = ctx.sector_medians or {}
    if not sm:
        return ""
    bits: list[str] = []
    for key, val in sm.items():
        if val is None:
            continue
        try:
            if isinstance(val, (int, float)):
                bits.append(f"{key} {float(val):.2f}")
            else:
                bits.append(f"{key} {val}")
        except Exception:
            continue
    if not bits:
        return ""
    return "Sector medians: " + ", ".join(bits[:4]) + "."


def _scrub_banned(text: str) -> str:
    """Replace any banned-word hit with a neutral synonym ("rated")."""
    out = text
    while True:
        hit = _find_banned(out)
        if not hit:
            return out
        out = re.sub(
            r"\b" + re.escape(hit) + r"\b",
            "rated",
            out,
            flags=re.IGNORECASE,
        )


# ── Anthropic dispatch ──────────────────────────────────────────

def _build_anthropic_client() -> Optional[Any]:
    """Return a real anthropic.Anthropic client when ANTHROPIC_API_KEY is
    set, else None. Imported lazily so this module loads without the SDK.
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
    ctx: ExplainContext,
    model: str,
    retry_hint: Optional[str] = None,
) -> str:
    """One Claude call. Returns raw text or empty string on failure."""
    system_prompt = build_system_prompt(ctx)
    user_prompt = render_user_prompt(ctx, retry_hint=retry_hint)
    response = client.messages.create(
        model=model,
        max_tokens=1200,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    )
    try:
        return response.content[0].text or ""
    except (AttributeError, IndexError):
        return ""


# ── Public API ──────────────────────────────────────────────────

@dataclass
class AIExplainResult:
    """Return shape of generate_explanation.

    ``answer`` is always a SEBI-safe string. ``source`` documents
    which path produced the answer:
      * "llm_first"       — first Claude call passed the filter
      * "llm_retry"       — retry passed the filter
      * "template"        — both attempts tripped, used the template
      * "template_no_llm" — no Claude client available
    """
    answer: str
    source: str = "template_no_llm"
    model_version: str = EXTRACTOR_VERSION
    prompt_version: int = PROMPT_VERSION
    sanitizer_hits: list[str] = field(default_factory=list)


def generate_explanation(
    ctx: ExplainContext,
    *,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
    call_llm: Optional[Callable[[Optional[str]], str]] = None,
) -> AIExplainResult:
    """Generate a SEBI-safe explanation for ``ctx``.

    Mirrors the orchestration in ``eli15_thesis_service.generate_thesis``:
      1. If no LLM closure / client is available, return the template.
      2. First call -> sanitize -> on miss, retry with hint.
      3. Both dirty -> deterministic template.
    """
    if call_llm is None:
        if anthropic_client is None:
            anthropic_client = _build_anthropic_client()
        if anthropic_client is None:
            return AIExplainResult(
                answer=deterministic_template_answer(ctx),
                source="template_no_llm",
            )

        def call_llm(hint: Optional[str]) -> str:
            try:
                return _call_claude(
                    anthropic_client, ctx, model, retry_hint=hint,
                )
            except Exception as exc:
                logger.warning(
                    "ai_explain: Claude call failed for %s/%s: %s",
                    ctx.ticker, ctx.preset_id, exc,
                )
                return ""

    raw_first = (call_llm(None) or "").strip()
    hit_first = _find_banned(raw_first) if raw_first else None
    if raw_first and not hit_first:
        return AIExplainResult(
            answer=raw_first, source="llm_first", sanitizer_hits=[],
        )

    retry_hint = hit_first or "subjective language"
    logger.info(
        "ai_explain: retry for %s/%s after banned=%r",
        ctx.ticker, ctx.preset_id, retry_hint,
    )
    raw_retry = (call_llm(retry_hint) or "").strip()
    hit_retry = _find_banned(raw_retry) if raw_retry else None
    if raw_retry and not hit_retry:
        return AIExplainResult(
            answer=raw_retry,
            source="llm_retry",
            sanitizer_hits=[retry_hint] if hit_first else [],
        )

    logger.info(
        "ai_explain: template fallback for %s/%s "
        "(first_hit=%r retry_hit=%r)",
        ctx.ticker, ctx.preset_id, hit_first, hit_retry,
    )
    hits: list[str] = []
    if hit_first:
        hits.append(hit_first)
    if hit_retry:
        hits.append(hit_retry)
    return AIExplainResult(
        answer=deterministic_template_answer(ctx),
        source="template",
        sanitizer_hits=hits,
    )


# ── Disclaimer ──────────────────────────────────────────────────

# Fixed disclaimer surfaced beneath every answer in the UI. Honest,
# SEBI-safe, scrubbed for banned vocab.
DISCLAIMER = (
    "AI-generated explanation, educational use only. Not investment "
    "advice. Numbers reflect the model's view, not a forecast."
)
