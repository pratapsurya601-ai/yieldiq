# backend/routers/backtest_accuracy.py
# ═══════════════════════════════════════════════════════════════
# Public verdict→forward-return backtest accuracy endpoint.
#
# The accuracy measurement loop made servable: a single read-only route
# that returns the parity scorecard — per-verdict-band forward returns,
# direction hit-rates, and the MoS-decile → forward-return calibration
# curve — at multiple horizons, overall and per sector.
#
# Cached 24h at the router layer (same cache_service used by
# /public/calibration). The underlying tables refresh nightly, so a day
# of staleness is invisible and we avoid read amplification on an
# unauthenticated public surface.
#
# Mounted under /api/v1/public to match the public-surface convention.
#
# SEBI: every field is a factual metric (counts, returns, hit-rates).
# Band names are the SEBI-safe below/near/above_fair_value vocabulary —
# the legacy undervalued/overvalued tokens never reach the wire. No
# advisory verbs, no quality claims.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.backtest_accuracy_service import (
    FORWARD_HORIZONS_DAYS,
    compute_backtest_accuracy,
    to_dict,
)
from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.backtest_accuracy_router")

router = APIRouter(prefix="/api/v1/public", tags=["public", "backtest"])

# 24h — source tables refresh nightly (see calibration router rationale).
_CACHE_KEY = "public:backtest_accuracy:v1"
_CACHE_TTL_SECONDS = 86_400  # 24h

# Compute parameters kept here so the documented meta block matches the
# actual computation by construction.
_HORIZONS = FORWARD_HORIZONS_DAYS
_MIN_SECTOR_OBSERVATIONS = 15

_CACHE_HEADERS = {
    "Cache-Control": "public, s-maxage=86400, stale-while-revalidate=172800",
}


def _build_payload() -> dict:
    """Compose the backtest-accuracy response off the service.

    Defensive: any exception from the compute path is logged and turned
    into an empty-but-well-shaped payload so the public endpoint never
    500s for a transient DB hiccup. The empty shape is the legitimate
    empty state — the consumer renders an "accruing history" message
    rather than failing.
    """
    try:
        result = compute_backtest_accuracy(
            horizons=_HORIZONS,
            min_sector_observations=_MIN_SECTOR_OBSERVATIONS,
        )
    except Exception as exc:
        logger.warning(
            "backtest_accuracy: compute raised (%s) — returning empty", exc
        )
        from backend.services.backtest_accuracy_service import (
            BacktestAccuracyResult,
        )
        result = BacktestAccuracyResult()
    return to_dict(
        result,
        horizons=_HORIZONS,
        min_sector_observations=_MIN_SECTOR_OBSERVATIONS,
    )


@router.get("/backtest-accuracy")
async def get_backtest_accuracy():
    """Verdict→forward-return backtest accuracy scorecard.

    Returns ``{"horizons": [...], "sectors": [...], "meta": {...}}``.

    Each horizon reports, per verdict band, the mean/median forward
    return and the direction hit-rate, plus the MoS-decile → forward-
    return calibration curve. Low-observation buckets are flagged
    (``low_n``) so consumers never read a tiny-sample median as signal.

    An all-empty payload (every horizon at observation_count 0) is the
    legitimate empty state while clean forward history is still
    accruing.

    Cached 24h at the router layer.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={**_CACHE_HEADERS, "X-Cache": "HIT"},
        )

    payload = _build_payload()
    cache.set(_CACHE_KEY, payload, ttl=_CACHE_TTL_SECONDS)
    return JSONResponse(
        content=payload,
        headers={**_CACHE_HEADERS, "X-Cache": "MISS"},
    )
