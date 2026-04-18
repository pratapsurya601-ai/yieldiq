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
