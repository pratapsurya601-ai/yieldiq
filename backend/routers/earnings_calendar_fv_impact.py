# backend/routers/earnings_calendar_fv_impact.py
# ═══════════════════════════════════════════════════════════════
# Forward earnings calendar + FV-impact preview endpoint.
#
# GET /api/v1/public/earnings-calendar-fv-impact/{ticker}
#   → Returns the next-earnings date, days-until, consensus EPS
#     (annual + derived per-quarter), historical surprise track
#     record, and the per-5%-beat FV sensitivity. Self-empties when
#     no event falls within the service's lookahead window.
#
# What this endpoint is NOT
#   - Not a recompute. The DCF on the analysis page is unchanged
#     after this call. The "FV impact per 5% beat" surface is a
#     HEURISTIC sensitivity calibrated to the same dampener and
#     sector multipliers as the post-print
#     earnings_impact_service, so the FORWARD preview and the
#     BACKWARD reading agree on a beat day.
#   - Not advice. We do not say position / hold / sell anywhere.
#   - Not a forecast of THIS quarter's print — we surface the
#     consensus estimate (a Finnhub-published number) and a
#     historical surprise track record (from prior quarterly
#     prints) and let the user form their own expectation.
#
# Caching: 1h via the shared in-memory cache. Forward-looking
# inputs (next-earnings date, consensus EPS) move slowly enough
# that a 1h TTL never feels stale; the analysis page hits this
# endpoint once per render so the in-memory cache absorbs the
# repeat hits cleanly.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.services.cache_service import cache
from backend.services.earnings_calendar_fv_impact_service import (
    compute_earnings_calendar_fv_impact,
    to_dict,
)

logger = logging.getLogger("yieldiq.earnings_calendar_fv_impact")

router = APIRouter(prefix="/api/v1", tags=["earnings-calendar-fv-impact"])

# 1h cache — consensus EPS + scheduled-date inputs change at a
# multi-day cadence. The TTL just stops the analysis page render
# from re-hammering the upstream Finnhub fetch on every page view.
_CACHE_TTL_SECONDS = 3600


def _empty_payload(ticker: str, reason: str) -> dict:
    """The panel renders nothing when impact is None — never 500
    the analysis page over a missing forward-earnings condition."""
    return {
        "ticker": ticker,
        "impact": None,
        "reason": reason,
        "is_heuristic": True,
    }


@router.get("/public/earnings-calendar-fv-impact/{ticker}")
async def get_earnings_calendar_fv_impact(ticker: str):
    """
    Forward earnings preview. Returns the next-scheduled-earnings
    date, the consensus EPS estimate, this ticker's historical
    surprise track record, and the sensitivity of FV to a 5%
    revenue surprise.

    Public read-only — no auth. The frontend panel sits ABOVE the
    fold on the analysis page for tickers with imminent earnings;
    gating it behind auth would push the waterfall and hurt
    perceived freshness on the days when it's most useful.

    The payload always carries `is_heuristic: true`. Consumers MUST
    label this surface as a heuristic preview, not a recompute.
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        raise HTTPException(status_code=400, detail="ticker required")

    cache_key = f"public:earnings-cal-fv-impact:v1:{raw}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        impact = compute_earnings_calendar_fv_impact(raw)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "earnings_calendar_fv_impact: compute crashed for %s (%s)",
            raw, str(exc)[:120],
        )
        return _empty_payload(raw, "compute_crashed")

    if impact is None:
        # Cache the "no upcoming event" answer too so we don't
        # re-query Finnhub for every page view of every ticker
        # without near-term earnings.
        empty = _empty_payload(raw, "no_upcoming_earnings")
        cache.set(cache_key, empty, ttl=_CACHE_TTL_SECONDS)
        return empty

    payload = {
        "ticker": raw,
        "impact": to_dict(impact),
        "is_heuristic": True,
        # Explicit disclaimer surfaced at the API boundary too —
        # API consumers must not present this as a fair-value
        # recompute or as a position-sizing signal.
        "disclaimer": (
            "Heuristic forward preview. Consensus EPS is published "
            "annually by Finnhub and divided by four for a "
            "per-quarter figure. Per-5%-beat sensitivity uses the "
            "same sector multiplier and dampener as the post-print "
            "earnings-impact panel. Not a fair-value recompute and "
            "not a forecast of this quarter's print."
        ),
    }
    cache.set(cache_key, payload, ttl=_CACHE_TTL_SECONDS)
    return payload
