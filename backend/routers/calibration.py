# backend/routers/calibration.py
# ═══════════════════════════════════════════════════════════════
# T1.2 — Public per-sector calibration accuracy endpoint.
#
# Single route. Cached 24h at the router layer (the same in-memory
# cache_service used by /public/coverage-stats and friends). The
# underlying stats are computed off fair_value_history + daily_prices
# which only refresh daily, so 24h staleness is invisible.
#
# Mounted under /api/v1/public so this matches the existing public-
# surface prefix convention.
#
# SEBI: every field in the response is a factual calibration metric
# (counts, error percentiles, direction-hit rate). No advisory
# vocabulary, no quality claims.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.backtest_publisher import (
    compute_sector_calibration,
    to_dict,
)
from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.calibration")

router = APIRouter(prefix="/api/v1/public", tags=["public", "calibration"])


# ─────────────────────────────────────────────────────────────────
# Cache wiring
# ─────────────────────────────────────────────────────────────────
# 24h matches the brief — the source tables refresh nightly, so a
# day of staleness is invisible to consumers and saves the daily
# read amplification on a public unauth surface.
_CACHE_KEY = "public:calibration:sectors:v1"
_CACHE_TTL_SECONDS = 86_400  # 24h

# Compute parameters. Kept here (not env-driven) so the public
# documentation in the response (`meta.lookback_days` etc.) matches
# the actual computation by construction.
_LOOKBACK_DAYS = 90
_MIN_OBSERVATIONS = 30


def _build_payload() -> dict:
    """Compose the calibration response off the publisher service.

    Defensive: any exception from the publisher path is logged and
    converted into an empty-shape payload so the public endpoint
    never 500s for a transient DB hiccup.
    """
    try:
        stats = compute_sector_calibration(
            min_observations=_MIN_OBSERVATIONS,
            lookback_days=_LOOKBACK_DAYS,
        )
    except Exception as exc:
        logger.warning(
            "calibration: compute_sector_calibration raised (%s) — "
            "returning empty",
            exc,
        )
        stats = []
    return to_dict(
        stats,
        lookback_days=_LOOKBACK_DAYS,
        min_observations=_MIN_OBSERVATIONS,
    )


@router.get("/calibration/sectors")
async def get_sector_calibration():
    """Per-sector calibration accuracy over the last 90 days.

    Returns ``{"sectors": [...], "meta": {...}}``. Sectors with fewer
    than 30 observations are excluded (insufficient signal). An empty
    ``sectors`` array is the legitimate empty state — the consumer
    page renders an "under construction" message rather than failing.

    Cached 24h at the router layer.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={
                "Cache-Control": (
                    "public, s-maxage=86400, stale-while-revalidate=172800"
                ),
                "X-Cache": "HIT",
            },
        )

    payload = _build_payload()
    cache.set(_CACHE_KEY, payload, ttl=_CACHE_TTL_SECONDS)
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": (
                "public, s-maxage=86400, stale-while-revalidate=172800"
            ),
            "X-Cache": "MISS",
        },
    )
