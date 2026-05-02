# backend/services/prism_narration_service.py
# ═══════════════════════════════════════════════════════════════
# Phase 2 of "The YieldIQ Prism" — Groq-backed auto-narration.
#
# Generates a ~45-second guided tour of a ticker's Prism:
#   • 2-sentence intro
#   • 6 x 1-sentence per-pillar descriptions (value/quality/growth/
#     moat/safety/pulse) referencing the actual hex scores + one
#     concrete metric from the hex.why field
#   • 1-sentence outro anchored to the MoS / verdict
#
# Constraints (hard):
#   - Groq-only (llama-3.3-70b-versatile). No Gemini, no OpenAI.
#   - SEBI-safe: prompt forbids buy/sell/hold/recommend; we also
#     post-filter the output and fall back to a templated narration
#     if any forbidden word slips through.
#   - Cache: 24hr TTL via the existing in-memory `cache_service`.
#     Key: prism-narration:{TICKER_UPPER}. Prevents Groq spam.
#   - Never raises. If Groq is unreachable or the key is missing,
#     we return a templated narration composed from pure string
#     interpolation of the hex payload.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from backend.services import prism_service
from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.prism.narration")

_CACHE_TTL = 24 * 3600  # 24 hours
_CACHE_PREFIX = "prism-narration:"

# Ordered identically to the frontend's PRISM_PILLAR_ORDER so the
# Prism highlight sequence flows from "stable → volatile".
_PILLAR_ORDER = ("pulse", "quality", "moat", "safety", "growth", "value")

# Each pillar holds ~6.5 sec on screen; 6 pillars = 39s + 4s intro +
# 4s outro ≈ 45s total audible tour (future TTS target).
_PILLAR_MS = 6500
_INTRO_MS = 4000
_OUTRO_MS = 4000

# SEBI post-filter: if any of these substrings appear (case-insensitive)
# in any generated prose field, we reject the Groq output wholesale and
# fall back to the templated narration. Defense-in-depth on top of
# prompt-level instructions.
_FORBIDDEN = re.compile(
    r"\b(buy|sell|hold|accumulate|recommend|recommendation|"
    r"target\s+price|price\s+target|should\s+(buy|sell|hold))\b",
    re.IGNORECASE,
)

DISCLAIMER = "Model estimate. Not investment advice."


# ── Public API ─────────────────────────────────────────────────
def get_or_generate_narration(ticker: str) -> dict:
    """Return a narration payload for `ticker`. Cached 24h. Never raises."""
    norm = (ticker or "").strip().upper()
    if not norm:
        return _templated_narration(prism_service.get_prism(ticker or ""))

    key = f"{_CACHE_PREFIX}{norm}"
    try:
        hit = cache.get(key)
    except Exception:
        hit = None
    if hit is not None:
        out = dict(hit)
        out["cached"] = True
        return out

    prism = prism_service.get_prism(norm)

    # Try Groq; fall back to template on any failure.
    try:
        nar = _groq_narration(prism)
    except Exception as exc:
        logger.warning("prism-narration: groq path raised for %s: %s", norm, exc)
        nar = None

    if not nar or not _passes_sebi_filter(nar):
        if nar is not None:
            logger.info("prism-narration: SEBI filter rejected Groq output for %s", norm)
        nar = _templated_narration(prism)

    nar["cached"] = False
    try:
        cache.set(key, nar, ttl=_CACHE_TTL)
    except Exception:
        pass
    return nar


# ── Groq path ──────────────────────────────────────────────────
def _groq_narration(prism: dict) -> Optional[dict]:
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key:
        logger.info("prism-narration: no GROQ_API_KEY; using template")
        return None

    axes = _dig(prism, "hex", "axes") or {}
    pillar_rows: list[dict] = []
    for key in _PILLAR_ORDER:
        node = axes.get(key) or {}
        pillar_rows.append({
            "key": key,
            "score": _safe_float(node.get("score")),
            "why": str(node.get("why") or "").strip()[:220],
        })

    company = prism.get("company_name") or prism.get("ticker")
    overall = _safe_float(prism.get("yieldiq_score_100") or
                          (_dig(prism, "hex", "overall") or 0) * 10)
    # P0 null-pillar gate: never default to "fair" / "Fair value
    # region" here — that masked the upstream null-pillar bug for
    # tickers like /prism/HEALTHCARE and /prism/SHAQUAK. When the
    # prism payload genuinely has no verdict, narrate it as
    # "Under Review" so downstream copy stays honest.
    verdict_band = prism.get("verdict_band") or "data_limited"
    verdict_label = prism.get("verdict_label") or "Under Review"
    mos = prism.get("mos_pct")
    price = prism.get("price")
    fv = prism.get("fair_value")

    system = (
        "You write 1-sentence factual descriptions of stock fundamentals. "
        "You NEVER recommend buy, sell, hold, accumulate, or target prices. "
        "Use simple English. Be specific — reference numbers you are given. "
        "Return JSON only, no prose around it."
    )

    user_payload = {
        "company_name": company,
        "ticker": prism.get("ticker"),
        "overall_score_100": overall,
        "verdict_band": verdict_band,
        "verdict_label": verdict_label,
        "current_price": price,
        "fair_value": fv,
        "mos_pct": mos,
        "pillars": pillar_rows,
    }

    user = (
        "Generate a 45-second guided narration of this stock's YieldIQ Prism. "
        "Return ONLY a JSON object with this exact shape:\n"
        "{\n"
        '  "intro": "<2 sentences, 30-45 words total, sets the company context '
        'and headline verdict. Factual only.>",\n'
        '  "pillars": [\n'
        '    {"key": "pulse",   "prose": "<1 sentence, 15-25 words, references the score '
        'AND one concrete metric from the why field>"},\n'
        '    {"key": "quality", "prose": "..."},\n'
        '    {"key": "moat",    "prose": "..."},\n'
        '    {"key": "safety",  "prose": "..."},\n'
        '    {"key": "growth",  "prose": "..."},\n'
        '    {"key": "value",   "prose": "..."}\n'
        "  ],\n"
        '  "outro": "<1 sentence, 18-28 words, anchored to the margin of safety '
        'and verdict label. Never says buy/sell/hold.>"\n'
        "}\n\n"
        "RULES:\n"
        "- NEVER use the words: buy, sell, hold, accumulate, recommend, "
        "target price.\n"
        "- Pillar order must match exactly: pulse, quality, moat, safety, growth, value.\n"
        "- Each pillar sentence must cite its numeric score.\n"
        "- No markdown, no headers, no bullets. Plain sentences only.\n\n"
        f"DATA:\n{json.dumps(user_payload, default=str)}"
    )

    t0 = time.perf_counter()
    try:
        from groq import Groq  # lazy import; keeps cold-start light
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=700,
            temperature=0.35,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("prism-narration: Groq call failed: %s", exc)
        return None

    latency_ms = (time.perf_counter() - t0) * 1000.0
    logger.info("prism-narration: Groq ok (%.0fms) for %s",
                latency_ms, prism.get("ticker"))

    try:
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("prism-narration: JSON parse failed: %s", exc)
        return None

    intro = str(parsed.get("intro") or "").strip()
    outro = str(parsed.get("outro") or "").strip()
    pillars_in = parsed.get("pillars") or []
    if not intro or not outro or not isinstance(pillars_in, list):
        return None

    # Reshape pillars into our canonical order, tolerating missing rows.
    by_key = {}
    for item in pillars_in:
        if isinstance(item, dict) and item.get("key") in _PILLAR_ORDER:
            by_key[item["key"]] = str(item.get("prose") or "").strip()

    pillars_out = []
    for key in _PILLAR_ORDER:
        prose = by_key.get(key) or ""
        if not prose:
            # A missing sentence triggers template fallback outright —
            # a partial narration would look broken.
            return None
        pillars_out.append({
            "key": key,
            "prose": prose,
            "duration_ms": _PILLAR_MS,
        })

    total = _INTRO_MS + (_PILLAR_MS * len(pillars_out)) + _OUTRO_MS

    return {
        "ticker": prism.get("ticker"),
        "intro": intro,
        "pillars": pillars_out,
        "outro": outro,
        "total_duration_ms": total,
        "intro_duration_ms": _INTRO_MS,
        "outro_duration_ms": _OUTRO_MS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "groq:llama-3.3-70b-versatile",
        "disclaimer": DISCLAIMER,
    }


# ── SEBI post-filter ───────────────────────────────────────────
def _passes_sebi_filter(nar: dict) -> bool:
    fields = [nar.get("intro") or "", nar.get("outro") or ""]
    for p in nar.get("pillars") or []:
        fields.append((p or {}).get("prose") or "")
    for txt in fields:
        if _FORBIDDEN.search(txt or ""):
            return False
    return True


# ── Templated fallback ─────────────────────────────────────────
_PILLAR_HUMAN: dict[str, str] = {
    "pulse": "Pulse",
    "quality": "Quality",
    "moat": "Moat",
    "safety": "Safety",
    "growth": "Growth",
    "value": "Value",
}


def _templated_narration(prism: dict) -> dict:
    """Deterministic narration built from the hex payload — no LLM.

    Used when Groq is unavailable, errors, or returns SEBI-unsafe text.
    Must be boring-but-correct: factual interpolation of scores and the
    existing hex.why sentences (which are already SEBI-scrubbed upstream).
    """
    ticker = prism.get("ticker") or ""
    company = prism.get("company_name") or ticker
    # P0 null-pillar gate: same fix as `_groq_narration` — no silent
    # "Fair value region" fallback. If the prism is unscored, say so.
    verdict_label = str(prism.get("verdict_label") or "Under Review")
    overall_100 = prism.get("yieldiq_score_100")
    overall_10 = None
    try:
        if overall_100 is not None:
            overall_10 = round(float(overall_100) / 10.0, 1)
        else:
            ov = _dig(prism, "hex", "overall")
            if ov is not None:
                overall_10 = round(float(ov), 1)
    except Exception:
        overall_10 = None

    mos = prism.get("mos_pct")
    price = prism.get("price")
    fv = prism.get("fair_value")

    # Intro
    # P0 null-pillar gate: when the verdict is "Under Review" the
    # composite score is suppressed upstream — narrate the dimmed
    # state honestly instead of pretending it sits in any region.
    if verdict_label == "Under Review":
        intro = (
            f"{company} is currently Under Review on the YieldIQ Prism — "
            f"too few of the six pillars have enough data to score "
            f"a confident composite. The lit pillars below show what we do know."
        )
    elif overall_10 is not None:
        intro = (
            f"{company} scores {overall_10} on the YieldIQ Prism, "
            f"sitting in the {verdict_label.lower()}. "
            f"Here is how the six pillars refract the underlying data."
        )
    else:
        intro = (
            f"{company} is mapped onto the YieldIQ Prism across six pillars. "
            f"The verdict reads: {verdict_label.lower()}."
        )

    # Pillars
    axes = _dig(prism, "hex", "axes") or {}
    pillars_out = []
    for key in _PILLAR_ORDER:
        node = axes.get(key) or {}
        score = _safe_float(node.get("score"))
        why = str(node.get("why") or "").strip()
        human = _PILLAR_HUMAN[key]
        if score is None:
            prose = f"{human} data is limited for {company}, so this lens is dimmed."
        elif why:
            prose = f"{human} scores {score:.1f} out of 10 — {_lowercase_first(why)}"
            if not prose.rstrip().endswith("."):
                prose = prose.rstrip() + "."
        else:
            prose = f"{human} scores {score:.1f} out of 10 on the underlying fundamentals."
        pillars_out.append({
            "key": key,
            "prose": prose,
            "duration_ms": _PILLAR_MS,
        })

    # Outro
    outro_bits: list[str] = []
    if overall_10 is not None:
        outro_bits.append(
            f"The Prism settles at {overall_10}, {verdict_label.lower()}."
        )
    else:
        outro_bits.append(f"The Prism reads: {verdict_label.lower()}.")

    if price is not None and fv is not None and mos is not None:
        try:
            direction = "above" if float(mos) < 0 else "below"
            gap = abs(float(mos))
            outro_bits.append(
                f"Price sits {gap:.0f}% {direction} the model estimate."
            )
        except Exception:
            pass

    outro = " ".join(outro_bits).strip() or (
        "The Prism reading is complete. See the pillars for details."
    )

    total = _INTRO_MS + (_PILLAR_MS * len(pillars_out)) + _OUTRO_MS

    return {
        "ticker": ticker,
        "intro": intro,
        "pillars": pillars_out,
        "outro": outro,
        "total_duration_ms": total,
        "intro_duration_ms": _INTRO_MS,
        "outro_duration_ms": _OUTRO_MS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "template",
        "disclaimer": DISCLAIMER,
    }


# ── helpers ────────────────────────────────────────────────────
def _dig(d: Any, *path, default=None):
    cur = d
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
    return cur if cur is not None else default


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _lowercase_first(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s[0].lower() + s[1:]


__all__ = ["get_or_generate_narration", "DISCLAIMER"]
