# backend/routers/valuation_history.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History router (Agent B / contract-first).
#
# Two endpoints live here:
#
#   1. GET /api/valuation-history/{ticker}                  (Phase 1)
#      Raw FV-history points + material-move annotations.
#      Stub today — Agent A wires the data layer in a follow-up.
#
#   2. GET /api/v1/public/valuation-history/{ticker}        (R3)
#      Read-only aggregate over fair_value_history producing a
#      calibration series + descriptive hypothetical statistics.
#      No engine output changes — purely additive on top of the
#      existing table.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from backend.models.fair_value_history import (
    FairValueHistoryResponse,
    ValuationHistoryResponse,
)
from backend.services.cache_service import cache
from data_pipeline.db import get_db

logger = logging.getLogger("yieldiq.valuation_history")


router = APIRouter(prefix="/api/valuation-history", tags=["valuation-history"])
# Separate router for the public, /api/v1-prefixed aggregate endpoint
# so it lives in the same module without colliding with the legacy
# stub's prefix. main.py includes both.
public_router = APIRouter(
    prefix="/api/v1/public/valuation-history",
    tags=["valuation-history", "public"],
)


@router.get("/{ticker}", response_model=FairValueHistoryResponse)
async def get_valuation_history(
    ticker: str = Path(..., min_length=1, max_length=32),
) -> FairValueHistoryResponse:
    """Return historical fair value points + material-move annotations.

    Production-faithful only: every point is the FV a user would have
    seen on that date. Empty series returns points_count=0 with an empty
    points list — the UI handles this with 'Fair value history starts
    <date>' copy.
    """
    # AGENT A WIRES THE QUERY HERE — see Phase 1 Agent A scope.
    # This stub returns empty so the route is reachable, tests can hit
    # it, and frontend can mock against the real shape.
    return FairValueHistoryResponse(
        ticker=ticker.upper(),
        points=[],
        annotations=[],
        starts_at=None,
        points_count=0,
        is_sparse=True,
    )


# ─────────────────────────────────────────────────────────────────
# Premium Feel R3 — valuation-history aggregate endpoint
# ─────────────────────────────────────────────────────────────────


# 1h TTL. The chart redraws on calendar-day boundaries; aggressive
# caching keeps Aiven/Neon free-tier read-load flat under the home
# page's hot tickers.
_VAL_HISTORY_TTL = 3600


@public_router.get("/{ticker}", response_model=ValuationHistoryResponse)
async def get_valuation_history_backtest(
    ticker: str = Path(..., min_length=1, max_length=32),
    db: Session = Depends(get_db),
) -> ValuationHistoryResponse:
    """Return the calibration series + descriptive hypothetical stats.

    Read-only aggregate over fair_value_history. No engine output is
    recomputed or modified — this endpoint cannot move canary-diff
    because no returned valuation field changes.

    Response shape: ValuationHistoryResponse. When fewer than 12
    observations are on record, `stats` is None and `caveats` carries
    the deficit reason. The frontend renders an empty state in that
    branch.
    """
    ticker_norm = ticker.strip().upper()
    cache_key = f"public:valuation-history:{ticker_norm}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from backend.services.analysis.valuation_history_service import (
            compute_valuation_history,
        )

        payload = compute_valuation_history(db, ticker_norm)
    except Exception as exc:
        logger.exception(
            "valuation-history aggregate failed for %s: %s: %s",
            ticker_norm, type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Valuation history unavailable",
        )

    model = ValuationHistoryResponse(**payload)
    cache.set(cache_key, model, ttl=_VAL_HISTORY_TTL)
    return model
