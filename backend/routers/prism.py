# backend/routers/prism.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Prism — consolidated analysis-page payload endpoint.
#
# GET  /api/v1/prism/{ticker}           — single-ticker prism (public)
# GET  /api/v1/prism/compare?t1=&t2=    — two-ticker overlay (public)
#
# Warm path target: <150ms. Cold path: <800ms. Never 500s — the
# service layer returns a populated baseline on any internal error.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services import prism_service

logger = logging.getLogger("yieldiq.prism.router")

router = APIRouter(prefix="/api/v1/prism", tags=["prism"])


@router.get("/compare")
async def compare_prism(
    t1: str = Query(..., min_length=1, max_length=32),
    t2: str = Query(..., min_length=1, max_length=32),
):
    """Return Prism payloads for two tickers plus per-axis delta overlay.
    Public, cached 1h per side via the underlying service."""
    try:
        return prism_service.compare_prisms(t1, t2)
    except Exception as exc:
        logger.warning("prism compare failed: %s", exc)
        # Return a shape-stable object instead of 500ing.
        return {
            "stock1": prism_service.get_prism(t1),
            "stock2": prism_service.get_prism(t2),
            "overlap": {
                "per_axis_delta": {
                    k: 0.0 for k in
                    ("value", "quality", "growth", "moat", "safety", "pulse")
                },
                "overall_delta": 0.0,
                "score_delta": 0.0,
                "mos_delta": 0.0,
            },
            "error": "compare_error",
            "data_limited": True,
            "disclaimer": prism_service.DISCLAIMER,
        }


@router.get("/{ticker}")
async def get_prism(ticker: str):
    """Return the consolidated Prism payload for a ticker. Public, no auth,
    cached 1 hour. Always returns HTTP 200 — missing data surfaces as
    `data_limited: true` in the payload."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker is required")
    return prism_service.get_prism(ticker)
