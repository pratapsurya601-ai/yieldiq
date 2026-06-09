# backend/routers/ai_explain.py
# ═══════════════════════════════════════════════════════════════
# Premium Feel R4 (2026-06-09) — AI Explain endpoint.
#
#   POST /api/v1/public/ai-explain  body: { ticker, preset_id }
#   GET  /api/v1/public/ai-explain/presets
#
# Powers the AIPromptPresetsPanel grid on the analysis page. The
# POST endpoint takes a ticker + preset id, reads the existing
# analyze() cache (no recompute, no engine touch), composes a
# SEBI-strict context, dispatches to Claude via the same wiring
# eli15_thesis uses, scrubs the answer through the SEBI banned-vocab
# filter, and returns the text.
#
# Tier-gating: re-uses the shared daily rate-limiter
# (backend/middleware/rate_limit.py). The free tier already has a
# 5/day cap across analysis endpoints; rather than introduce a
# parallel counter (which would be hard to reason about — two
# distinct caps would leak into screenshots and support tickets),
# we bill ai-explain against the same counter. Pro / Analyst /
# Starter are uncapped per the existing TIER_LIMITS table.
#
# Cache: 30s per (ticker, preset_id) so repeated clicks within a
# session are cheap. Reuses backend.services.cache_service.cache.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.middleware.rate_limit import rate_limiter, clamped_used
from backend.services.cache_service import cache
from backend.services.analysis_service import (
    AnalysisService,
    TickerNotFoundError,
)
from backend.services import ai_explain_service as svc

logger = logging.getLogger("yieldiq.ai_explain")

router = APIRouter(prefix="/api/v1/public", tags=["ai_explain"])

_analysis = AnalysisService()

# Hard timeout — a stuck Anthropic call must never starve a worker.
_LLM_TIMEOUT_S = 25.0

# 30s router cache — repeated clicks on the same card by the same
# user within a session must not double-bill the LLM.
_CACHE_TTL_S = 30

_IST = timezone(timedelta(hours=5, minutes=30))


# ── Request / response models ──────────────────────────────────

class AIExplainRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    preset_id: str = Field(..., min_length=1, max_length=32)


class AIExplainResponse(BaseModel):
    ticker: str
    preset_id: str
    title: str
    answer: str
    disclaimer: str
    generated_at: str
    model_version: str
    source: str
    cached: bool


# ── Cache helpers ──────────────────────────────────────────────

def _cache_key(ticker: str, preset_id: str) -> str:
    return f"ai-explain:{ticker.upper()}:{preset_id.lower()}"


def _to_dict(analysis) -> dict:
    """Coerce a Pydantic AnalysisResponse to a plain dict (Pydantic v1/v2)."""
    if hasattr(analysis, "model_dump"):
        try:
            return analysis.model_dump()
        except Exception:
            pass
    if hasattr(analysis, "dict"):
        try:
            return analysis.dict()
        except Exception:
            pass
    try:
        return dict(vars(analysis))
    except Exception:
        return {}


# ── Endpoints ──────────────────────────────────────────────────

@router.get("/ai-explain/presets")
async def list_presets() -> dict:
    """Return the three preset cards rendered on the analysis page.

    SEBI-safe card copy is hard-coded in
    ``ai_explain_service.PRESETS`` — single source of truth shared
    with the answer-generation path.
    """
    return {
        "presets": svc.list_preset_cards(),
        "disclaimer": svc.DISCLAIMER,
    }


@router.post("/ai-explain")
async def ai_explain(
    body: AIExplainRequest,
    user: dict = Depends(get_current_user),
) -> AIExplainResponse:
    """Generate (or return cached) AI explanation for a preset card."""
    ticker = (body.ticker or "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")

    preset = svc.get_preset(body.preset_id)
    if preset is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unknown_preset",
                "preset_id": body.preset_id,
                "known": [p.preset_id for p in svc.PRESETS],
            },
        )

    # ── Tier-gate ──────────────────────────────────────────────
    # Same daily counter as analyze(). Pro / Analyst / Starter are
    # effectively unlimited per the shared TIER_LIMITS table; free
    # tier shares its 5/day cap with the analysis endpoints.
    user_tier = (user.get("tier") or "free").lower()
    user_id = str(user.get("id") or user.get("user_id") or user.get("email") or "anon")

    # Cache check — never bills the counter for a cache hit (the
    # answer text is identical, the user already paid for it once).
    cached_value = cache.get(_cache_key(ticker, preset.preset_id))
    if cached_value is not None:
        payload = dict(cached_value)
        payload["cached"] = True
        return AIExplainResponse(**payload)

    # On a cache miss, bill the counter BEFORE the LLM hop. The
    # counter is atomic (Postgres UPSERT-with-guard), so an over-
    # limit free-tier user gets blocked before we burn an LLM call.
    allowed, used, limit = rate_limiter.check_and_increment(
        user_id=user_id, tier=user_tier,
    )
    if not allowed:
        # Mirror the analyze() 429 contract so the existing frontend
        # error handler can recognize and route to the upgrade path.
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily analysis limit reached",
                "used": clamped_used(used, limit),
                "limit": limit,
                "tier": user_tier,
            },
        )

    # ── Load the cached analyze() payload ─────────────────────
    try:
        analysis = await asyncio.to_thread(
            _analysis.get_full_analysis, ticker,
        )
    except TickerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Ticker not found", "ticker": ticker},
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "ai_explain: get_full_analysis failed for %s: %s",
            ticker, exc,
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "analysis_unavailable", "retry_after": 30},
        )

    payload = _to_dict(analysis)
    ctx = svc.build_context_from_analysis(payload, ticker, preset.preset_id)

    # Hard timeout on the LLM path; never block the response.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(svc.generate_explanation, ctx),
            timeout=_LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "ai_explain: Claude timeout for %s/%s after %.0fs",
            ticker, preset.preset_id, _LLM_TIMEOUT_S,
        )
        result = svc.AIExplainResult(
            answer=svc.deterministic_template_answer(ctx),
            source="template",
        )

    response_payload = {
        "ticker": ticker,
        "preset_id": preset.preset_id,
        "title": preset.title,
        "answer": result.answer,
        "disclaimer": svc.DISCLAIMER,
        "generated_at": datetime.now(tz=_IST).isoformat(timespec="seconds"),
        "model_version": result.model_version,
        "source": result.source,
        "cached": False,
    }

    # Persist into the 30s cache (best-effort).
    try:
        cache.set(
            _cache_key(ticker, preset.preset_id),
            response_payload,
            ttl=_CACHE_TTL_S,
        )
    except Exception as exc:
        logger.debug(
            "ai_explain: cache.set failed for %s/%s: %s",
            ticker, preset.preset_id, exc,
        )

    return AIExplainResponse(**response_payload)
