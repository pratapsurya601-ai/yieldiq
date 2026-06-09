# backend/routers/eli15_thesis.py
# ═══════════════════════════════════════════════════════════════
# ELI15 thesis endpoint — 3-bullet plain-English explainer of why
# the YieldIQ model produced its verdict for a given ticker.
#
#   GET /api/v1/analysis/{ticker}/eli15-thesis
#
# Response shape:
#   {
#     "ticker": "HDFCBANK.NS",
#     "generated_at": "2026-06-09T07:30:00+05:30",
#     "model_version": "eli15-thesis-v1-anthropic-2026-06-09",
#     "verdict": "undervalued",        // wire-format enum
#     "verdict_display": "below model fair value",
#     "bullets": [...3 SEBI-safe strings...],
#     "disclaimer": "Generated 2026-06-09. Not advice; ..."
#   }
#
# Caching: looks up eli15_thesis_cache by (ticker, model, prompt,
# today_ist()); on cache hit returns the row directly. On miss,
# pulls a fresh AnalysisResponse, composes a ThesisContext, calls
# Claude with the SEBI-strict system prompt, runs every bullet
# through the SEBI filter, and persists the result. Cache miss is
# the only path that costs LLM tokens.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import get_current_user
from backend.services.analysis_service import (
    AnalysisService,
    TickerNotFoundError,
)
from backend.services import eli15_thesis_service as svc

logger = logging.getLogger("yieldiq.eli15_thesis")

router = APIRouter(prefix="/api/v1", tags=["analysis"])

# Single service instance (matches the analysis router convention).
_analysis = AnalysisService()


# Hard cap so a stuck Anthropic call cannot starve a Railway worker.
_LLM_TIMEOUT_S = 20.0

# Asia/Kolkata offset for the generated_at stamp.
_IST = timezone(timedelta(hours=5, minutes=30))


@router.get("/analysis/{ticker}/eli15-thesis")
async def get_eli15_thesis(
    ticker: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Return a 3-bullet plain-English thesis for ``ticker``.

    Cached per (ticker, model_version, prompt_version, day-IST).
    Returns the cached row on hit; computes + persists on miss.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")

    today = svc.today_ist()

    # ── Tier 1: cached row ──────────────────────────────────────
    cached = svc.get_cached_thesis(ticker, generated_on=today)
    if cached and cached.get("bullets"):
        return _build_response(
            ticker=ticker,
            bullets=cached["bullets"],
            verdict=cached.get("verdict") or "unavailable",
            verdict_display=(
                cached.get("verdict_display") or svc.display_verdict(
                    cached.get("verdict") or ""
                )
            ),
            model_version=cached.get("model_version") or svc.EXTRACTOR_VERSION,
            generated_on=today,
            cached=True,
        )

    # ── Tier 2: build a fresh thesis ────────────────────────────
    try:
        analysis = await asyncio.to_thread(
            _analysis.get_full_analysis, ticker
        )
    except TickerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Ticker not found", "ticker": ticker},
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("eli15_thesis: get_full_analysis failed for %s: %s",
                       ticker, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "analysis_unavailable", "retry_after": 30},
        )

    # Pydantic model -> dict for the context builder.
    payload = _to_dict(analysis)
    ctx = svc.build_context_from_analysis(payload)

    # Hard timeout on the LLM path so a stuck call cannot block.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(svc.generate_thesis, ctx),
            timeout=_LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "eli15_thesis: Claude call timed out for %s after %.0fs",
            ticker, _LLM_TIMEOUT_S,
        )
        # Falls back to the deterministic template — never blocks
        # the response on LLM availability.
        result = svc.ELI15ThesisResult(
            bullets=svc.deterministic_template_bullets(ctx),
            source="template",
        )

    # Persist the result (best-effort; never raises).
    await asyncio.to_thread(
        svc.save_cached_thesis, ticker, result, ctx, generated_on=today,
    )

    return _build_response(
        ticker=ticker,
        bullets=result.bullets,
        verdict=ctx.verdict,
        verdict_display=ctx.verdict_display,
        model_version=result.model_version,
        generated_on=today,
        cached=False,
    )


def _build_response(
    *,
    ticker: str,
    bullets: list[str],
    verdict: str,
    verdict_display: str,
    model_version: str,
    generated_on,
    cached: bool,
) -> dict:
    """Assemble the wire-format response dict."""
    return {
        "ticker": ticker,
        "generated_at": datetime.now(tz=_IST).isoformat(timespec="seconds"),
        "model_version": model_version,
        "verdict": verdict,
        "verdict_display": verdict_display,
        "bullets": bullets,
        "disclaimer": svc.build_disclaimer(generated_on),
        "cached": cached,
    }


def _to_dict(analysis) -> dict:
    """Coerce a Pydantic AnalysisResponse to a plain dict.

    Falls back to ``.dict()`` if ``.model_dump()`` is unavailable
    (legacy Pydantic v1 in some test envs); finally falls back to
    ``vars()`` if neither is present.
    """
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
