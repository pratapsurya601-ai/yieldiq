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

import hashlib
import json
import logging
import os
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
# Day-103a: ticker-level concall library
#
# `list_concalls` and `summarise_concall` back the public endpoint
# GET /api/v1/public/concalls/{ticker}. They read/write the new
# `concalls` table (see migrations/051_concalls.sql) and lean on the
# same Groq client used elsewhere on the analysis page. Summaries
# are cached in the `ai_summary` column so repeat reads never call
# Groq again.
# ═══════════════════════════════════════════════════════════════

_LIBRARY_SUMMARY_SYSTEM = (
    "You are a careful financial writer producing a neutral, factual "
    "5-bullet summary of an Indian-market earnings call for retail "
    "investors. Use plain English. Stick to what management actually "
    "said. Never use directional or advisory framing about the stock."
)


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
        "Summarise this earnings call into exactly 5 short bullets. "
        "Cover: (1) revenue/topline commentary, (2) margin/profitability "
        "commentary, (3) segment or geography drivers, (4) outlook or "
        "guidance language used by management, (5) any risks or "
        "concerns explicitly acknowledged. Each bullet must be one "
        "sentence, factual, and avoid any directional framing about "
        "the share price.\n\nReturn only the 5 bullets, each prefixed "
        "with '- '. No preamble, no headings, no closing line.\n\n"
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


def summarise_concall(transcript_text: str) -> str:
    """Return a 5-bullet structured summary for a concall transcript.

    Pure function over the transcript text — does not touch the
    database. Callers persist the result into the `ai_summary` column
    (plus `ai_summary_generated_at` / `ai_summary_model`) so the work
    is never repeated.

    Returns an empty string when the LLM is unavailable so callers can
    fall back to the source link only.
    """
    if not transcript_text or len(transcript_text.strip()) < 200:
        return ""
    client = _groq_client()
    if client is None:
        return ""
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
        return (comp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning(f"summarise_concall failed: {exc}")
        return ""


def _normalise_library_ticker(ticker: str) -> str:
    """Normalise to the .NS-suffixed form stored in the concalls table."""
    t = (ticker or "").upper().strip()
    if not t:
        return ""
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


def _get_library_session():
    """Open a SQLAlchemy session for the concalls library table.

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


def list_concalls(ticker: str, limit: int = 12) -> list[dict]:
    """Return the most recent concalls for a ticker, newest first.

    Each row carries `period`, `date` (ISO YYYY-MM-DD or ""), `source_url`,
    `ai_summary`, and `has_full_transcript`. Returns [] on any DB or
    schema issue so the public endpoint stays 200 with an empty library
    instead of 500-ing for one ticker. Lazily back-fills a missing
    summary when the transcript text is on file and Groq is configured.
    """
    full = _normalise_library_ticker(ticker)
    if not full:
        return []
    limit = max(1, min(int(limit or 12), 50))
    session = _get_library_session()
    if session is None:
        return []
    try:
        from backend.models.concalls import Concall
        rows = (
            session.query(Concall)
            .filter(Concall.ticker == full)
            .order_by(Concall.concall_date.desc().nullslast(), Concall.id.desc())
            .limit(limit)
            .all()
        )

        out: list[dict] = []
        for r in rows:
            summary = r.ai_summary or ""
            # Lazy back-fill: if we have full transcript text but no
            # cached summary, generate + persist it once. We swallow
            # any persistence error so the read path never fails.
            if not summary and (r.transcript_text or "").strip():
                generated = summarise_concall(r.transcript_text or "")
                if generated:
                    r.ai_summary = generated
                    r.ai_summary_model = _LIBRARY_SUMMARY_MODEL
                    r.ai_summary_generated_at = datetime.now(timezone.utc)
                    try:
                        session.commit()
                    except Exception:
                        try:
                            session.rollback()
                        except Exception:
                            pass
                    summary = generated
            out.append({
                "period": r.period,
                "date": r.concall_date.isoformat() if r.concall_date else "",
                "source_url": r.source_url,
                "ai_summary": summary,
                "has_full_transcript": bool((r.transcript_text or "").strip()),
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
