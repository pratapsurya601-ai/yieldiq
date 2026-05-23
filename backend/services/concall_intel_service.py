# backend/services/concall_intel_service.py
# ===============================================================
# Concall INTELLIGENCE -- structured-signal extraction from earnings
# call transcripts using the Claude (Anthropic) API.
#
# This is DISTINCT from backend/services/concall_service.py which
# returns a free-text retail-investor TL;DR via Groq/Llama. Intel
# returns STRUCTURED, machine-queryable signals that downstream
# analytics (alerts, percentile cohorts, retrospective backtests)
# can consume.
#
# Phase 1 (this revision): live Anthropic wiring with prompt caching,
# JSON-leaf SEBI sanitizer, schema validation, per-row cost tracking,
# and a quality_flag on persisted rows (migration 059).
#
# Phase 0 (previous) was a scaffold raising NotImplementedError unless
# a mock client was injected. The legacy contract is preserved: any
# caller that passes its own `anthropic_client` (real or mock) still
# works; the only new behaviour is that when `anthropic_client` is
# None AND the ANTHROPIC_API_KEY env var is set, we now build a real
# client instead of raising.
# ===============================================================
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger("yieldiq.concall_intel")

EXTRACTOR_VERSION = "concall-intel-v1-anthropic-2026-05-23"

# Anthropic model + pricing. Sonnet 4.7 is the default — strikes the
# right cost/quality balance for structured extraction. Update the
# pricing dict in one place when Anthropic changes rates.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
ANTHROPIC_PRICING_USD_PER_MTOKEN: dict[str, dict[str, float]] = {
    # Source: https://www.anthropic.com/pricing (as of 2026-05-23).
    "claude-sonnet-4-5":  {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-7":  {"input": 3.0,  "output": 15.0},
    "claude-opus-4-7":    {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5":   {"input": 1.0,  "output": 5.0},
}

# Banned vocabulary. Must stay in lock-step with
# backend/services/concall_service.py::_SEBI_BANNED_WORDS — we keep an
# independent copy here so this module has no compile-time dependency
# on the summary service. Mismatches would be a bug; the existing
# sebi-lint CI workflow flags new violations elsewhere in the tree.
SEBI_BANNED_WORDS: tuple[str, ...] = (
    "buy", "sell", "hold", "strong", "recommend", "accumulate",
    "should", "outperform", "underperform", "opportunity", "pick",
    "target", "rating", "downgrade", "upgrade",
)

ALLOWED_MANAGEMENT_TONES: frozenset[str] = frozenset({
    "bullish", "neutral", "cautious", "defensive",
})

# Long, stable system prompt -- candidate for Anthropic prompt caching.
# Keep this dict-of-blocks shape so we can pass it as
# `system=[...] cache_control={"type": "ephemeral"}` to the SDK.
_SYSTEM_PROMPT = (
    "You are an equity research analyst extracting STRUCTURED SIGNALS "
    "from an Indian earnings call transcript.\n\n"
    "You MUST respond with a single JSON object matching this schema:\n"
    "{\n"
    '  "fiscal_period":     "Q1FY26",                       // string Q?FY??\n'
    '  "concall_date":      "YYYY-MM-DD",                   // ISO date\n'
    '  "transcript_source": "nse_pdf",                      // provenance tag\n'
    '  "guidance_changes":  [\n'
    '    {"metric":"revenue_growth_fy26","previous":"12-15%","new":"14-16%",\n'
    '     "direction":"raised|lowered|reaffirmed","quote":"..."}\n'
    '  ],\n'
    '  "capex_commitments": [\n'
    '    {"amount_cr":1200,"horizon":"FY26-FY28","purpose":"...","quote":"..."}\n'
    '  ],\n'
    '  "margin_commentary": [\n'
    '    {"segment":"consumer","direction":"expansion|contraction|stable",\n'
    '     "drivers":["..."],"quote":"..."}\n'
    '  ],\n'
    '  "management_tone":   "bullish|neutral|cautious|defensive",\n'
    '  "key_quotes":        [\n'
    '    {"speaker":"CFO","topic":"working capital","quote":"..."}\n'
    '  ]\n'
    "}\n\n"
    "SEBI-COMPLIANCE RULES (HARD CONSTRAINTS):\n"
    "* You are NOT a SEBI-registered research analyst. You MUST NOT use any of:\n"
    "  buy, sell, hold, strong, recommend, accumulate, should, outperform,\n"
    "  underperform, opportunity, pick, target, rating, downgrade, upgrade.\n"
    "* Quote management VERBATIM. Do not paraphrase to add a directional bias.\n"
    "* `management_tone` is the ONLY field where you may use a qualitative\n"
    "  label — and it must be one of the four enum values above, nothing else.\n"
    "* Empty arrays are valid. Don't fabricate guidance/capex if none was\n"
    "  given on the call.\n\n"
    "OUTPUT FORMAT:\n"
    "* Return ONLY the JSON object. No markdown, no preamble, no closing line.\n"
    "* All amounts in INR Cr (crore = 10M). Convert if the speaker used Rs Mn.\n"
)


@dataclass
class ConcallIntelResult:
    """Return shape of extract_concall_signals (Phase 1 contract).

    `signals` matches the JSON schema in _SYSTEM_PROMPT; `quality_flag`
    is 'ok' when the SEBI walker found nothing or 'sebi_withheld' when
    a banned word was caught in `management_tone` / `key_quotes`. Cost
    fields are populated when the real Anthropic client was used; they
    default to zero when only a mock was injected.
    """
    signals: dict
    quality_flag: str = "ok"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    sanitizer_hits: list[str] = field(default_factory=list)


# ---------- pricing ---------------------------------------------------------

def compute_anthropic_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Return USD cost for an Anthropic call given the model + tokens.

    Pure function so tests can call it directly. Returns 0.0 for
    unknown models — caller decides whether to treat that as an error.
    """
    rates = ANTHROPIC_PRICING_USD_PER_MTOKEN.get(model)
    if not rates:
        return 0.0
    return round(
        (input_tokens / 1_000_000.0) * rates["input"]
        + (output_tokens / 1_000_000.0) * rates["output"],
        4,
    )


# ---------- sanitizer -------------------------------------------------------

def _iter_string_leaves(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    """Yield (json-path, string-value) for every string leaf in a JSON
    structure. Walks dicts and lists recursively; non-string scalars
    are skipped.
    """
    if isinstance(node, str):
        yield path or "$", node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _iter_string_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_string_leaves(v, f"{path}[{i}]")


# Restrict the SEBI check to free-text fields. Structured metadata
# fields like `direction`, `segment`, `metric` legitimately contain
# words like "raised" / "target" as schema tokens (e.g. "target" might
# appear in a metric name like "revenue_target_fy26"). The bans must
# only apply to LLM-generated free-text — quotes, drivers, purpose.
_SEBI_CHECK_FIELD_SUFFIXES = ("quote", "drivers", "purpose", "management_tone")


def _path_subject_to_sebi_check(path: str) -> bool:
    last = path.rsplit(".", 1)[-1]
    # drivers is a list of strings, so path looks like ...drivers[0]
    base = last.split("[", 1)[0]
    return base in _SEBI_CHECK_FIELD_SUFFIXES


def scan_for_banned_vocab(signals: dict) -> list[str]:
    """Return a list of "<path>: <banned_word>" findings, empty when clean.

    Only scans free-text fields (quotes, drivers, purpose,
    management_tone) — structured fields are exempt because the schema
    itself uses controlled vocabulary that overlaps with the ban list
    (e.g. "direction": "raised", "target" as part of a metric name).
    """
    findings: list[str] = []
    lowered_bans = [w.lower() for w in SEBI_BANNED_WORDS]
    for path, value in _iter_string_leaves(signals):
        if not _path_subject_to_sebi_check(path):
            continue
        lowered = value.lower()
        for word in lowered_bans:
            # Word-boundary check: substring search would false-positive
            # on "should" inside "shoulder". Build a simple boundary
            # check without regex for speed.
            idx = 0
            while True:
                pos = lowered.find(word, idx)
                if pos < 0:
                    break
                left_ok = pos == 0 or not lowered[pos - 1].isalpha()
                end = pos + len(word)
                right_ok = end == len(lowered) or not lowered[end].isalpha()
                if left_ok and right_ok:
                    findings.append(f"{path}: {word}")
                    break
                idx = pos + 1
    return findings


# ---------- schema validation -----------------------------------------------

_REQUIRED_KEYS = (
    "fiscal_period", "concall_date", "transcript_source",
    "guidance_changes", "capex_commitments", "margin_commentary",
    "management_tone", "key_quotes",
)


def validate_schema(signals: dict) -> None:
    """Raise ValueError if `signals` doesn't match the documented shape.

    Soft validation — checks structural keys, enum values, and that
    list-typed fields are actually lists. Does NOT enforce nested
    dict shapes (cap the strictness so a slightly malformed sub-record
    doesn't trigger sebi_withheld; downstream code handles missing
    sub-keys defensively).
    """
    missing = [k for k in _REQUIRED_KEYS if k not in signals]
    if missing:
        raise ValueError(f"signals missing required keys: {missing}")

    for k in ("guidance_changes", "capex_commitments",
              "margin_commentary", "key_quotes"):
        if not isinstance(signals[k], list):
            raise ValueError(f"signals.{k} must be a list")

    tone = signals.get("management_tone")
    if tone is not None and tone not in ALLOWED_MANAGEMENT_TONES:
        raise ValueError(
            f"management_tone must be one of {sorted(ALLOWED_MANAGEMENT_TONES)}, "
            f"got {tone!r}"
        )


# ---------- client factory --------------------------------------------------

def _build_anthropic_client() -> Optional[Any]:
    """Build a real anthropic.Anthropic client when ANTHROPIC_API_KEY
    is set, else return None.

    Importing the SDK inside the function so the module loads cleanly
    in environments that don't have anthropic installed yet (the SDK
    is now in requirements.txt but older virtualenvs may lag).
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


# ---------- main entry point ------------------------------------------------

def extract_concall_signals(
    ticker: str,
    transcript_text: str,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
) -> dict:
    """Phase-1 entry: extract structured concall signals.

    Returns the signals dict (legacy contract). For richer metadata
    (cost, quality_flag, sanitizer hits), call
    `extract_concall_signals_full` instead.
    """
    return extract_concall_signals_full(
        ticker, transcript_text,
        anthropic_client=anthropic_client, model=model,
    ).signals


def extract_concall_signals_full(
    ticker: str,
    transcript_text: str,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
) -> ConcallIntelResult:
    """Same as extract_concall_signals but returns the full result
    (cost, quality_flag, sanitizer hits).

    Behaviour:
      * If `anthropic_client` is None AND `ANTHROPIC_API_KEY` is set,
        we build a real client.
      * If `anthropic_client` is None AND no API key, raise
        NotImplementedError (the Phase-0 safety guard, preserved).
      * Calls `messages.create` with the SEBI-strict system prompt
        marked for prompt caching (saves ~90% on repeat-call input
        cost when the operator runs the batch script).
      * Parses the JSON response, validates the schema, walks all
        string leaves for banned vocabulary, and returns a result
        with quality_flag='sebi_withheld' if anything was caught.
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not transcript_text or len(transcript_text.strip()) < 200:
        raise ValueError(
            "transcript_text too short (<200 chars) -- pass a full "
            "transcript to extract meaningful signals."
        )

    if anthropic_client is None:
        anthropic_client = _build_anthropic_client()
    if anthropic_client is None:
        raise NotImplementedError(
            "concall_intel_service.extract_concall_signals: no anthropic "
            "client supplied and ANTHROPIC_API_KEY is unset. Set the env "
            "var or inject a client (real or mock) to use this path."
        )

    try:
        # Prompt cache the system prompt — the schema instructions
        # don't change across calls. The SDK's cache_control marker
        # cuts repeat-call input cost dramatically.
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Ticker: {ticker}\n\n"
                        f"Transcript:\n{transcript_text}\n\n"
                        "Respond with the JSON object only."
                    ),
                }
            ],
        )
    except Exception as exc:
        logger.warning("anthropic_client.messages.create failed: %s", exc)
        raise

    # Parse response text. Real SDK returns response.content[0].text;
    # mocks mirror that shape.
    try:
        raw_text = response.content[0].text
    except (AttributeError, IndexError) as exc:
        raise ValueError(f"unexpected anthropic response shape: {exc}") from exc

    # Pull usage. Real SDK returns response.usage.input_tokens /
    # .output_tokens; mocks usually omit it (defaults to 0).
    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    # Cache-read tokens are charged at a discount; we sum them with
    # regular input tokens for the in-the-clear cost report. A future
    # refinement could break this out. For now keep it simple.
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0
    in_tok_total = in_tok + cache_read

    try:
        signals = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM did not return valid JSON: {exc}") from exc

    if not isinstance(signals, dict):
        raise ValueError("LLM JSON root must be an object")

    signals.setdefault("extractor_version", EXTRACTOR_VERSION)

    # Hard schema validation. Re-raise as ValueError so the batch
    # script can count + skip schema failures.
    validate_schema(signals)

    # SEBI sanitizer over string leaves of the parsed JSON.
    hits = scan_for_banned_vocab(signals)
    quality = "ok"
    if hits:
        logger.warning(
            "concall_intel: SEBI banned vocab in %s output for %s: %s",
            model, ticker, hits[:5],
        )
        quality = "sebi_withheld"

    cost = compute_anthropic_cost_usd(model, in_tok_total, out_tok)

    return ConcallIntelResult(
        signals=signals,
        quality_flag=quality,
        input_tokens=in_tok_total,
        output_tokens=out_tok,
        cost_usd=cost,
        model=model,
        sanitizer_hits=hits,
    )


# -- DB persistence ----------------------------------------------

def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is
    unset or the connect fails -- callers must handle the None.
    Same pattern as backend/services/api_keys_service.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("concall_intel: psycopg2.connect failed (%s)", exc)
        return None


def save_signals(
    ticker: str,
    fiscal_period: str,
    signals: dict,
    *,
    quality_flag: str = "ok",
    transcript_id: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> bool:
    """UPSERT a concall_signals row.

    Phase-1 extends the Phase-0 signature with optional metadata that
    maps to the columns added by migration 059. The defaults preserve
    backwards-compatibility — any existing caller that passes only
    (ticker, fiscal_period, signals) gets the same behaviour as
    before, just with `quality_flag='ok'` persisted alongside.

    Returns True on success, False on DB unreachable / insert failure.
    Does NOT raise on DB errors — callers can decide whether to retry.
    """
    if not ticker or not fiscal_period:
        raise ValueError("ticker and fiscal_period are required")
    if not isinstance(signals, dict):
        raise ValueError("signals must be a dict")

    conn = _connect()
    if conn is None:
        logger.info(
            "save_signals: no DATABASE_URL -- skipping persist for %s %s",
            ticker, fiscal_period,
        )
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO concall_signals (
                        ticker, fiscal_period, concall_date,
                        transcript_source, guidance_changes,
                        capex_commitments, margin_commentary,
                        management_tone, key_quotes, extractor_version,
                        quality_flag, transcript_id,
                        ai_input_tokens, ai_output_tokens, ai_cost_usd
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (ticker, fiscal_period) DO UPDATE SET
                        concall_date      = EXCLUDED.concall_date,
                        transcript_source = EXCLUDED.transcript_source,
                        guidance_changes  = EXCLUDED.guidance_changes,
                        capex_commitments = EXCLUDED.capex_commitments,
                        margin_commentary = EXCLUDED.margin_commentary,
                        management_tone   = EXCLUDED.management_tone,
                        key_quotes        = EXCLUDED.key_quotes,
                        extracted_at      = now(),
                        extractor_version = EXCLUDED.extractor_version,
                        quality_flag      = EXCLUDED.quality_flag,
                        transcript_id     = EXCLUDED.transcript_id,
                        ai_input_tokens   = EXCLUDED.ai_input_tokens,
                        ai_output_tokens  = EXCLUDED.ai_output_tokens,
                        ai_cost_usd       = EXCLUDED.ai_cost_usd
                    """,
                    (
                        ticker,
                        fiscal_period,
                        signals.get("concall_date"),
                        signals.get("transcript_source"),
                        json.dumps(signals.get("guidance_changes") or []),
                        json.dumps(signals.get("capex_commitments") or []),
                        json.dumps(signals.get("margin_commentary") or []),
                        signals.get("management_tone"),
                        json.dumps(signals.get("key_quotes") or []),
                        signals.get("extractor_version", EXTRACTOR_VERSION),
                        quality_flag,
                        transcript_id,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("save_signals UPSERT failed: %s", exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
