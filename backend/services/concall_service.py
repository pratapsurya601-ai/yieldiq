# backend/services/concall_service.py
# ═══════════════════════════════════════════════════════════════
# Earnings call (concall) transcript analysis.
# User pastes transcript text → AI extracts structured insights.
#
# Output structure:
#   - executive_summary: 2-3 sentence TL;DR
#   - financial_highlights: revenue/margin/profit deltas with numbers
#   - forward_guidance: management's outlook with direct quotes
#   - strategic_priorities: top 3-5 themes
#   - q_and_a_themes: what analysts asked about
#   - concerns_raised: risks/challenges acknowledged
#   - sentiment: positive | neutral | cautious | negative
#
# Caching: by SHA256 hash of transcript text (24-hour TTL).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("yieldiq.concall")


def _transcript_hash(text: str) -> str:
    """SHA256 hash of normalized transcript text."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _build_prompt(ticker: str, quarter: str, transcript: str) -> str:
    """Build the AI prompt for transcript analysis."""
    # Truncate very long transcripts (LLM context limits)
    max_chars = 60000
    if len(transcript) > max_chars:
        # Keep first 60% (management commentary) + last 40% (Q&A)
        first_chunk = int(max_chars * 0.6)
        last_chunk = int(max_chars * 0.4)
        transcript = transcript[:first_chunk] + "\n\n[...transcript truncated...]\n\n" + transcript[-last_chunk:]

    return f"""You are a financial analyst summarizing an earnings call transcript for retail investors.

Stock: {ticker}
Quarter: {quarter or "Latest"}

Transcript:
{transcript}

---

Output a JSON object with this exact structure (no markdown, no commentary, just JSON):

{{
  "executive_summary": "2-3 sentence TL;DR of the entire call",
  "financial_highlights": [
    "Revenue grew X% YoY to Rs Y Cr",
    "EBITDA margin expanded to X%",
    "..."
  ],
  "forward_guidance": [
    {{"topic": "Revenue", "guidance": "Management expects 12-15% growth in FY26", "quote": "..."}},
    {{"topic": "Margins", "guidance": "...", "quote": "..."}}
  ],
  "strategic_priorities": [
    "Capacity expansion in X facility",
    "Geographic expansion into Y market",
    "..."
  ],
  "q_and_a_themes": [
    {{"theme": "Margin pressure from raw material costs", "summary": "Multiple analysts asked about input cost inflation. Management said pass-through is happening with a 1-quarter lag."}},
    {{"theme": "...", "summary": "..."}}
  ],
  "concerns_raised": [
    "Slowdown in rural demand",
    "Working capital cycle elongation",
    "..."
  ],
  "sentiment": "positive | neutral | cautious | negative",
  "sentiment_rationale": "1 sentence explaining why"
}}

Rules:
- Use plain English a retail investor understands
- Include real numbers from the transcript
- Quotes must be exact phrases from the transcript
- If a section has no content, return an empty array
- Do NOT recommend buying or selling
- Do NOT include any text outside the JSON object
"""


# Gemini removed 18-Apr-2026 — Groq is the sole LLM for concall
# analysis now. The _call_gemini function was removed along with
# google-genai dependency.


def _call_groq(prompt: str) -> Optional[str]:
    """Primary LLM path for concall analysis (Llama 3.3 70B via Groq)."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        comp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a financial analyst. Output only valid JSON, no markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        return (comp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"Groq concall analysis failed: {e}")
        return None


def _strip_markdown_fences(s: str) -> str:
    """Remove ```json ... ``` fences if present."""
    s = s.strip()
    if s.startswith("```"):
        # Find first newline and last fence
        lines = s.split("\n")
        # Drop first line (```json or ```) and last line (```)
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            return "\n".join(lines[1:-1])
        return "\n".join(lines[1:])
    return s


def analyze_transcript(transcript: str, ticker: str = "", quarter: str = "") -> dict:
    """
    Analyze an earnings call transcript and return structured insights.
    Uses cache to avoid re-analyzing same transcript.
    """
    if not transcript or len(transcript.strip()) < 200:
        return {"error": "Transcript too short. Paste the full call transcript (min 200 chars)."}

    if len(transcript) > 200000:
        return {"error": "Transcript too long (>200K chars). Trim to the most relevant sections."}

    # Cache by transcript hash
    th = _transcript_hash(transcript)
    cache_key = f"concall:{th}"
    try:
        from backend.services.cache_service import cache as _c
        cached = _c.get(cache_key)
        if cached:
            return {**cached, "cached": True, "transcript_hash": th}
    except Exception:
        pass

    prompt = _build_prompt(ticker.upper(), quarter, transcript)

    # Groq is the sole LLM path now (Gemini removed).
    raw = _call_groq(prompt)
    if not raw:
        return {"error": "AI analysis unavailable. Set GROQ_API_KEY."}

    raw_clean = _strip_markdown_fences(raw)

    try:
        parsed = json.loads(raw_clean)
    except json.JSONDecodeError as e:
        logger.warning(f"Concall JSON parse failed: {e}. Raw: {raw_clean[:500]}")
        # Try to extract JSON object from the response
        try:
            start = raw_clean.find("{")
            end = raw_clean.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(raw_clean[start:end + 1])
            else:
                return {"error": "AI returned invalid JSON. Try again or use a shorter transcript."}
        except Exception:
            return {"error": "AI returned invalid JSON. Try again."}

    # Validate / set defaults
    result = {
        "executive_summary": parsed.get("executive_summary", "") or "",
        "financial_highlights": parsed.get("financial_highlights", []) or [],
        "forward_guidance": parsed.get("forward_guidance", []) or [],
        "strategic_priorities": parsed.get("strategic_priorities", []) or [],
        "q_and_a_themes": parsed.get("q_and_a_themes", []) or [],
        "concerns_raised": parsed.get("concerns_raised", []) or [],
        "sentiment": parsed.get("sentiment", "neutral") or "neutral",
        "sentiment_rationale": parsed.get("sentiment_rationale", "") or "",
        "ticker": ticker.upper(),
        "quarter": quarter,
        "transcript_hash": th,
        "transcript_chars": len(transcript),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }

    # Cache for 24 hours
    try:
        from backend.services.cache_service import cache as _c
        _c.set(cache_key, result, ttl=86400)
    except Exception:
        pass

    return result


def save_user_concall(user_email: str, analysis: dict) -> bool:
    """Save concall analysis to user's library in Supabase."""
    if not user_email or not analysis:
        return False
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return False
        client.table("concall_analyses").upsert({
            "user_email": user_email,
            "ticker": analysis.get("ticker", ""),
            "quarter": analysis.get("quarter", ""),
            "transcript_hash": analysis.get("transcript_hash", ""),
            "summary": analysis.get("executive_summary", ""),
            "sentiment": analysis.get("sentiment", "neutral"),
            "data": analysis,  # full JSON
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_email,transcript_hash").execute()
        return True
    except Exception as e:
        logger.warning(f"save_user_concall failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Day-103a (refactored by Day-103d, 2026-05-22): ticker-level
# concall library.
#
# `list_concalls` backs the public endpoint
# GET /api/v1/public/concalls/{ticker}. It now reads from the
# CANONICAL `concall_transcripts` table (migration 010) — the
# `concalls` table the Day-103a agent created in migration 051 was
# a duplicate and is being dropped in migration 053.
#
# The canonical table has no `ai_summary` column. Period semantics
# are parsed out of the free-text `subject` field
# ("Q3 FY25 earnings call" → "Q3-FY25"). `ai_summary` is returned as
# None for now; a future PR will add a caching layer (either a new
# column or an out-of-band cache table) and call `summarise_concall`.
# The frontend already handles a missing `ai_summary` gracefully.
# ═══════════════════════════════════════════════════════════════

import re

_LIBRARY_SUMMARY_SYSTEM = (
    "You are a careful financial writer producing a neutral, factual "
    "5-bullet summary of an Indian-market earnings call for retail "
    "investors. Use plain English. Stick to what management actually "
    "said. Never use directional or advisory framing about the stock. "
    "You are SEBI-compliant: you do not recommend, rate, or rank "
    "securities, and you do not use vocabulary that implies a view on "
    "future share price."
)


# SEBI-safe vocabulary check. Any of these tokens appearing in the
# generated summary (case-insensitive, word-boundary) triggers a
# withhold-pending-review fallback. Kept narrow so we don't flag
# innocent uses (e.g. "strong" is banned, "stronger rupee" would also
# be flagged — that's the conservative tradeoff we want).
_SEBI_BANNED_WORDS = (
    "buy", "sell", "hold", "strong", "recommend", "accumulate",
    "should", "outperform", "underperform", "opportunity", "pick",
)

_SEBI_WITHHELD_MESSAGE = "(summary withheld pending review)"
_SUMMARY_UNAVAILABLE_MESSAGE = "(summary unavailable)"


def _contains_banned_vocab(text: str) -> Optional[str]:
    """Return the first banned word found in `text`, or None.

    Word-boundary, case-insensitive. We deliberately match substrings
    only at word boundaries so 'household' is NOT flagged for 'hold'.
    """
    if not text:
        return None
    import re as _re
    lower = text.lower()
    for w in _SEBI_BANNED_WORDS:
        if _re.search(rf"\b{_re.escape(w)}\b", lower):
            return w
    return None


def _library_summary_prompt(transcript_text: str) -> str:
    excerpt = transcript_text.strip()
    if len(excerpt) > 60000:
        first_chunk = int(60000 * 0.6)
        last_chunk = int(60000 * 0.4)
        excerpt = (
            excerpt[:first_chunk]
            + "\n\n[...transcript truncated...]\n\n"
            + excerpt[-last_chunk:]
        )
    return (
        "Summarise this earnings call into EXACTLY 5 short bullets. "
        "Each bullet is ONE short sentence, factual observation only, "
        "covering in order: (1) revenue / topline trajectory with "
        "numbers, (2) profit / margin trajectory with numbers, "
        "(3) segment or geography performance, (4) capex / capacity "
        "commitments mentioned, (5) management commentary on outlook "
        "(quote the language management used — do NOT characterise it "
        "as 'positive' or 'negative'; instead say 'management guided "
        "to X' or 'management flagged Y').\n\n"
        "BANNED WORDS (do not use under any circumstances): buy, sell, "
        "hold, strong, recommend, accumulate, should, outperform, "
        "underperform, opportunity, pick. Do not rate or rank the "
        "stock. Do not imply a view on future share price.\n\n"
        "Return only the 5 bullets, each prefixed with '- '. No "
        "preamble, no headings, no closing line.\n\n"
        f"Transcript:\n{excerpt}"
    )


def _groq_client():
    """Return a Groq client or None when the API key is missing."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception as exc:
        logger.warning(f"Groq client init failed: {exc}")
        return None


_LIBRARY_SUMMARY_MODEL = "llama-3.3-70b-versatile"


# Phase G-cost: per-million-token pricing for Groq-hosted models.
# Update these when Groq publishes new rates. Keys are model strings
# returned in the Groq response.
#
# Source: https://groq.com/pricing/ (as of 2026-05-23).
GROQ_PRICING_USD_PER_MTOKEN: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    # Defensive fallback for older / alias names.
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
}


def compute_groq_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Return USD cost for a Groq call given the model + token counts.

    Returns 0.0 when the model is unknown — caller decides whether to
    treat that as an error. Pure / no side effects so tests can call
    it directly.
    """
    rates = GROQ_PRICING_USD_PER_MTOKEN.get(model)
    if not rates:
        return 0.0
    return round(
        (input_tokens / 1_000_000.0) * rates["input"]
        + (output_tokens / 1_000_000.0) * rates["output"],
        4,
    )


# Return type for summarise_concall — keeps the public string-only
# contract backwards-compatible via the legacy `summarise_concall`
# wrapper while letting populate_concall_summary persist token usage.
@dataclass
class ConcallSummaryResult:
    summary: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


def summarise_concall_with_usage(transcript_text: str) -> ConcallSummaryResult:
    """Same as summarise_concall but also returns token + cost metadata.

    Used by populate_concall_summary (Phase G-cost) so we can persist
    per-row spend. The legacy `summarise_concall(...)` wrapper below
    keeps the string-only signature for any external callers.
    """
    empty = ConcallSummaryResult(summary="", model=_LIBRARY_SUMMARY_MODEL)
    if not transcript_text or len(transcript_text.strip()) < 200:
        return empty
    client = _groq_client()
    if client is None:
        return empty
    try:
        comp = client.chat.completions.create(
            model=_LIBRARY_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": _LIBRARY_SUMMARY_SYSTEM},
                {"role": "user", "content": _library_summary_prompt(transcript_text)},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        summary = (comp.choices[0].message.content or "").strip()
        # Groq follows the OpenAI shape: `usage.prompt_tokens` /
        # `usage.completion_tokens`. Be defensive — older client
        # versions might omit usage or use a dict instead of an object.
        usage = getattr(comp, "usage", None)
        if usage is None:
            in_tok = out_tok = 0
        else:
            in_tok = int(getattr(usage, "prompt_tokens", 0) or
                         (usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0))
            out_tok = int(getattr(usage, "completion_tokens", 0) or
                          (usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0))
    except Exception as exc:
        logger.warning(f"summarise_concall failed: {exc}")
        return empty

    banned = _contains_banned_vocab(summary)
    if banned is not None:
        logger.warning(
            "summarise_concall: SEBI-banned token '%s' in LLM output; "
            "withholding summary pending review",
            banned,
        )
        # We STILL paid for the call even though we're not surfacing
        # the text — record the spend honestly.
        return ConcallSummaryResult(
            summary=_SEBI_WITHHELD_MESSAGE,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_groq_cost_usd(_LIBRARY_SUMMARY_MODEL, in_tok, out_tok),
            model=_LIBRARY_SUMMARY_MODEL,
        )
    return ConcallSummaryResult(
        summary=summary,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=compute_groq_cost_usd(_LIBRARY_SUMMARY_MODEL, in_tok, out_tok),
        model=_LIBRARY_SUMMARY_MODEL,
    )


def summarise_concall(transcript_text: str) -> str:
    """Return a 5-bullet structured summary for a concall transcript.

    Pure function over the transcript text — does not touch the
    database. Day-104b wires this into `list_concalls` via the lazy
    populate path (`populate_concall_summary`).

    SEBI-safe: the prompt explicitly bans directional vocabulary, and
    the output is post-checked against `_SEBI_BANNED_WORDS`. If a
    banned word slips through, we return the
    `_SEBI_WITHHELD_MESSAGE` sentinel instead so we never surface
    advisory language to retail users.

    Returns an empty string when the LLM is unavailable so callers can
    fall back to the source link only.
    """
    # Thin wrapper around summarise_concall_with_usage; preserves the
    # legacy string-only contract for any external callers (tests,
    # scripts) that don't need cost tracking.
    return summarise_concall_with_usage(transcript_text).summary


def _normalise_library_ticker(ticker: str) -> str:
    """Normalise to the .NS-suffixed form stored in concall_transcripts."""
    t = (ticker or "").upper().strip()
    if not t:
        return ""
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


def _get_library_session():
    """Open a SQLAlchemy session for the concall_transcripts table.

    Uses the same pipeline-engine factory the financials/analysis
    services use so all reads share a connection pool.
    """
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


# Period extraction from the NSE free-text `subject` line.
#
# Real-world examples we want to canonicalise:
#   "Q3 FY25 earnings call"            → "Q3-FY25"
#   "Q3FY25 analyst meet"              → "Q3-FY25"
#   "Earnings call - Q1 FY2026"        → "Q1-FY26"
#   "Quarter ended 30 June 2024"       → "Q1-FY25"  (best effort)
#
# When no quarter+FY pattern matches, we fall back to a truncated
# version of the raw subject so the panel still has something to show.
_PERIOD_QFY_RE = re.compile(
    r"Q\s*([1-4])\s*FY\s*((?:20)?\d{2})",
    re.IGNORECASE,
)


def _parse_period_from_subject(subject: str) -> str:
    """Parse a canonical 'Q?-FY??' period from a free-text subject.

    Falls back to the truncated raw subject when no quarter/FY pattern
    is found — better to show *something* than to ship an empty cell.
    """
    s = (subject or "").strip()
    if not s:
        return ""
    m = _PERIOD_QFY_RE.search(s)
    if m:
        q = m.group(1)
        fy_raw = m.group(2)
        # Normalise '2026' / '26' → '26'
        fy = fy_raw[-2:]
        return f"Q{q}-FY{fy}"
    # No match — return a short label derived from the subject so the
    # panel renders meaningfully. Cap at 40 chars to keep the UI tidy.
    return s[:40]


# ─────────────────────────────────────────────────────────────────
# Day-104b: lazy AI-summary cache.
#
# Concurrency: cap Groq fan-out at 5 in-flight summaries process-wide
# so a hot-ticker burst doesn't blow rate limits or Groq cost spikes.
# We use a threading.Semaphore because populate_concall_summary is
# invoked from FastAPI BackgroundTasks (sync callables run in a worker
# thread).
# ─────────────────────────────────────────────────────────────────
import threading as _threading

_CONCALL_SUMMARY_CONCURRENCY = 5
_concall_summary_sem = _threading.Semaphore(_CONCALL_SUMMARY_CONCURRENCY)

# Max bytes we'll pull for a PDF before bailing. NSE concall PDFs are
# usually 200-800 KB; 5 MB is a safe ceiling.
_PDF_MAX_BYTES = 5 * 1024 * 1024
_PDF_FETCH_TIMEOUT_S = 30.0


def _fetch_pdf_bytes(url: str) -> Optional[bytes]:
    """Download a PDF with a hard size + timeout ceiling.

    Returns None on any failure (network, oversize, non-200). Caller
    is responsible for the structured-warning log path.
    """
    try:
        import httpx
        with httpx.Client(timeout=_PDF_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning(
                        "concall PDF fetch non-200 %s for %s",
                        resp.status_code, url,
                    )
                    return None
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _PDF_MAX_BYTES:
                        logger.warning(
                            "concall PDF exceeds %d bytes; aborting fetch of %s",
                            _PDF_MAX_BYTES, url,
                        )
                        return None
                return bytes(buf)
    except Exception as exc:
        logger.warning("concall PDF fetch failed for %s: %s", url, exc)
        return None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF via pypdf. Empty string on any failure."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(p for p in parts if p).strip()
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        return ""


def populate_concall_summary(concall_id: int) -> None:
    """Populate ai_summary for a single concall_transcripts row.

    Background task entry point. Idempotent and self-bounded:
      * Acquires the module-level semaphore so we never have more
        than _CONCALL_SUMMARY_CONCURRENCY Groq calls in flight.
      * If transcript_text is already cached, skip the PDF fetch.
      * On any failure, persists the `(summary unavailable)` sentinel
        so subsequent requests don't re-enter this code path.

    No-op (logged) when the DB session factory or the row is missing.
    """
    if not _concall_summary_sem.acquire(blocking=False):
        # Hit the in-flight ceiling — skip this round. The next
        # list_concalls call for the same ticker will retry; the
        # backlog drains naturally without a queue.
        logger.info(
            "populate_concall_summary: concurrency cap hit, skipping id=%s",
            concall_id,
        )
        return
    try:
        session = _get_library_session()
        if session is None:
            logger.warning("populate_concall_summary: no DB session, id=%s", concall_id)
            return
        try:
            from backend.models.concalls import ConcallTranscript
            row = session.get(ConcallTranscript, concall_id)
            if row is None:
                logger.warning("populate_concall_summary: row missing id=%s", concall_id)
                return
            if row.ai_summary:
                # Another worker beat us to it; nothing to do.
                return

            transcript_text = (row.transcript_text or "").strip()
            if not transcript_text:
                if not row.pdf_url:
                    # Nothing to summarise and nothing to fetch.
                    row.ai_summary = _SUMMARY_UNAVAILABLE_MESSAGE
                    row.ai_summary_generated_at = datetime.now(timezone.utc)
                    session.commit()
                    return
                pdf_bytes = _fetch_pdf_bytes(row.pdf_url)
                if not pdf_bytes:
                    row.ai_summary = _SUMMARY_UNAVAILABLE_MESSAGE
                    row.ai_summary_generated_at = datetime.now(timezone.utc)
                    session.commit()
                    return
                transcript_text = _extract_pdf_text(pdf_bytes)
                if not transcript_text or len(transcript_text) < 200:
                    row.ai_summary = _SUMMARY_UNAVAILABLE_MESSAGE
                    row.ai_summary_generated_at = datetime.now(timezone.utc)
                    session.commit()
                    return
                # Cache the extracted text so a future Groq retry doesn't
                # re-download + re-parse the PDF.
                row.transcript_text = transcript_text
                session.commit()

            result = summarise_concall_with_usage(transcript_text)
            if not result.summary:
                row.ai_summary = _SUMMARY_UNAVAILABLE_MESSAGE
            else:
                row.ai_summary = result.summary
                row.ai_summary_model = result.model or _LIBRARY_SUMMARY_MODEL
            row.ai_summary_generated_at = datetime.now(timezone.utc)
            # Phase G-cost: persist token + USD usage. NULL when the
            # call short-circuited (transcript too short, Groq down) —
            # consistent with "we didn't pay, don't record a cost".
            if result.input_tokens or result.output_tokens:
                row.ai_input_tokens = result.input_tokens
                row.ai_output_tokens = result.output_tokens
                row.ai_cost_usd = result.cost_usd
            session.commit()
        except Exception as exc:
            logger.warning(
                "populate_concall_summary failed for id=%s: %s",
                concall_id, exc,
            )
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            try:
                session.close()
            except Exception:
                pass
    finally:
        _concall_summary_sem.release()


def list_concalls(
    ticker: str,
    limit: int = 12,
    background_tasks=None,
) -> list[dict]:
    """Return the most recent concall filings for a ticker, newest first.

    Reads from the canonical `concall_transcripts` table (migration 010,
    extended by migration 055 with the AI-summary cache columns).

    Each row maps as:

        period              ← parsed from `subject` (e.g. "Q3-FY25")
        date                ← filing_date.isoformat() | ""
        source_url          ← pdf_url
        ai_summary          ← cached value | None (lazy populate)
        has_full_transcript ← pdf_url is not None

    Lazy AI-summary cache (Day-104b): for any row with `pdf_url` set
    and no cached summary, we enqueue a background task to fetch +
    summarise the PDF. The CURRENT request still returns
    `ai_summary: None` for those rows — subsequent requests within
    seconds will see the populated value once the worker finishes.

    `background_tasks` is the FastAPI `BackgroundTasks` instance from
    the calling endpoint. When None (e.g. from a script, or from the
    backfill CLI), we skip enqueuing.

    Returns [] on any DB or schema issue so the public endpoint stays
    200 with an empty library instead of 500-ing for one ticker.
    """
    full = _normalise_library_ticker(ticker)
    if not full:
        return []
    limit = max(1, min(int(limit or 12), 50))
    session = _get_library_session()
    if session is None:
        return []
    try:
        from backend.models.concalls import ConcallTranscript
        rows = (
            session.query(ConcallTranscript)
            .filter(ConcallTranscript.ticker == full)
            .order_by(
                ConcallTranscript.filing_date.desc(),
                ConcallTranscript.id.desc(),
            )
            .limit(limit)
            .all()
        )

        out: list[dict] = []
        for r in rows:
            cached_summary = (r.ai_summary or "").strip() or None
            # Schedule lazy populate for rows that have a source PDF
            # but no cached summary yet. We use background_tasks when
            # available; otherwise the row simply returns None and a
            # later request will trigger the populate.
            if (
                cached_summary is None
                and r.pdf_url
                and background_tasks is not None
            ):
                try:
                    background_tasks.add_task(populate_concall_summary, r.id)
                except Exception as exc:
                    logger.warning(
                        "failed to enqueue concall summary task id=%s: %s",
                        r.id, exc,
                    )
            out.append({
                "period": _parse_period_from_subject(r.subject or ""),
                "date": r.filing_date.isoformat() if r.filing_date else "",
                "source_url": r.pdf_url,
                "ai_summary": cached_summary,
                "has_full_transcript": bool(r.pdf_url),
            })
        return out
    except Exception as exc:
        logger.warning(f"list_concalls failed for {full}: {exc}")
        return []
    finally:
        try:
            session.close()
        except Exception:
            pass


def get_user_concalls(user_email: str, ticker: Optional[str] = None) -> list[dict]:
    """List user's saved concall analyses."""
    if not user_email:
        return []
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return []
        q = client.table("concall_analyses").select("*").eq("user_email", user_email)
        if ticker:
            q = q.eq("ticker", ticker.upper())
        result = q.order("saved_at", desc=True).limit(50).execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"get_user_concalls failed: {e}")
        return []
