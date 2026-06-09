# backend/routers/sparklines.py
"""Batch sparkline-series endpoint for the home-page polish surfaces.

Powers the 56×18 inline SVG charts that the WatchlistPanel,
PortfolioPanel, TodaysMovers rows and MarketsStrip tiles render next to
their headline numbers. The frontend batch-fetches one payload per
surface on mount; the data feeds the `<Sparkline values={...} />`
component directly.

Design notes:

* Single endpoint, batched by ticker list — issuing N per-ticker
  requests from the watchlist would flood the API gateway on every
  home-page paint. The cap (TICKER_CAP) is defensive; the home page
  itself never asks for more than ~20 tickers in any single panel.
* Server pulls `daily_prices.close_price` for the last N trading days
  (7 or 30), oldest-first to match the component's expected
  orientation. Suspended/dead tickers with no rows are silently
  omitted from the response — the frontend skips the sparkline cell
  rather than rendering a degenerate flat line.
* 60s router cache, keyed by sorted ticker tuple + period. The daily
  series only changes once per post-close bhavcopy refresh, but
  caching at 60s mirrors `/pulse` and `/today-movers` so a tab refresh
  during market hours doesn't re-hit the DB for the same panel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.middleware.auth import get_current_user
from backend.services.cache_service import cache

router = APIRouter(prefix="/api/v1", tags=["sparklines"])
log = logging.getLogger("yieldiq.sparklines")

# Cap per request — defends against an accidental loop in the frontend
# that would fan out a request with thousands of tickers. The home page
# itself never exceeds ~20 tickers per panel.
TICKER_CAP = 50

# Supported lookback windows. 7d is the home-page default; 30d is
# available for the (future) /watchlist detail view.
_PERIOD_DAYS: Dict[str, int] = {
    "7d": 7,
    "30d": 30,
}

_IST = timezone(timedelta(hours=5, minutes=30))


def _pipeline_session():
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:  # pragma: no cover — import path optional in tests
        pass
    return None


def _parse_tickers(raw: str) -> List[str]:
    """Comma-separated → uppercase-stripped list, de-duped, cap enforced."""
    if not raw:
        return []
    seen: set[str] = set()
    out: List[str] = []
    for tk in raw.split(","):
        # Lowercase markers like ".ns" get NFD-normalised by upstream
        # callers; we still upper-case defensively here so a stray
        # lowercase ticker in someone's watchlist doesn't slip past the
        # de-dupe set as a distinct entry.
        norm = tk.strip().upper()
        if not norm:
            continue
        # Strip suffixes the frontend may or may not include — the
        # daily_prices table uses bare-symbol .NS rows; we match both
        # paths by querying on the ticker as-given AND on the bare
        # ticker (see _fetch_sparklines below).
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _fetch_sparklines(tickers: List[str], days: int) -> Dict[str, List[float]]:
    """Fetch the last `days` trading-day closes for each ticker.

    Returns oldest→newest ordered lists, keyed by the ticker AS GIVEN by
    the caller (so the frontend can look the result up under the same
    string it asked for). Tickers with no rows are simply absent from
    the dict — the frontend renders no sparkline for them.
    """
    if not tickers:
        return {}

    sess = _pipeline_session()
    if sess is None:
        log.debug("sparklines: no pipeline session available")
        return {}

    try:
        # Build a list of (input_ticker, lookup_variants) so we can match
        # both "HDFCBANK" and "HDFCBANK.NS" forms in the daily_prices
        # table without forcing the frontend to know which suffix the
        # backend stores. The variants set is small (1-2 entries per
        # ticker) so we widen the IN clause cheaply.
        variants: set[str] = set()
        for tk in tickers:
            variants.add(tk)
            # Add the .NS variant if not already suffixed; the bhavcopy
            # ingest stores most NSE tickers WITH the .NS suffix.
            if "." not in tk:
                variants.add(f"{tk}.NS")
            else:
                # Add bare form too — some upstreams (Yahoo) store
                # without the suffix.
                bare = tk.split(".", 1)[0]
                variants.add(bare)

        rows = sess.execute(
            text(
                """
                SELECT
                    UPPER(ticker) AS ticker,
                    trade_date,
                    close_price
                FROM daily_prices
                WHERE UPPER(ticker) = ANY(:tickers)
                  AND close_price IS NOT NULL
                  AND close_price > 0
                  AND trade_date >= :since
                ORDER BY UPPER(ticker), trade_date
                """
            ),
            {
                "tickers": list(variants),
                # Look back at calendar days a bit beyond `days` so
                # weekends + holidays still leave the requested count
                # of TRADING days in the slice. We then trim to `days`
                # below — keeps the SQL trivial and the trim cheap.
                "since": datetime.now(_IST).date() - timedelta(days=days * 2 + 5),
            },
        ).fetchall()

        # Bucket rows by canonical ticker. Match both suffixed and bare
        # variants back to the input ticker — preserving the caller's
        # original casing/suffix in the output dict.
        per_ticker: Dict[str, List[tuple]] = {tk: [] for tk in tickers}
        # Reverse-index: every variant → input ticker that produced it.
        variant_to_input: Dict[str, str] = {}
        for tk in tickers:
            variant_to_input[tk] = tk
            if "." not in tk:
                variant_to_input[f"{tk}.NS"] = tk
            else:
                bare = tk.split(".", 1)[0]
                variant_to_input[bare] = tk

        for db_tk, trade_date, close_price in rows:
            input_tk = variant_to_input.get(db_tk)
            if input_tk is None:
                continue
            try:
                per_ticker[input_tk].append((trade_date, float(close_price)))
            except (TypeError, ValueError):
                continue

        # Take the last `days` trading days per ticker and emit closes
        # only. Tickers with fewer than 2 closes are skipped — the
        # Sparkline component renders null for length < 2 anyway, so
        # carrying single-point arrays would only add network bytes.
        out: Dict[str, List[float]] = {}
        for tk, pairs in per_ticker.items():
            if len(pairs) < 2:
                continue
            # Already sorted by trade_date asc thanks to the ORDER BY.
            tail = pairs[-days:]
            out[tk] = [p[1] for p in tail]
        return out
    finally:
        try:
            sess.close()
        except Exception:
            pass


@router.get("/sparklines")
async def get_sparklines(
    user: dict = Depends(get_current_user),
    tickers: str = Query(default="", description="Comma-separated tickers"),
    period: str = Query(default="7d", description="Lookback window (7d or 30d)"),
):
    """Return batch 7- or 30-day close-price series per ticker.

    Response shape:

        {
          "as_of": "2026-06-09T15:30:00+05:30",
          "period": "7d",
          "series": {
              "HDFCBANK": [747.05, 740.12, 738.65, ...],
              "RELIANCE": [1280.50, 1275.30, ...]
          }
        }

    Tickers with < 2 closes in the window are omitted (a single point
    is not a sparkline).
    """
    period_norm = period.lower()
    if period_norm not in _PERIOD_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"period must be one of {sorted(_PERIOD_DAYS.keys())}",
        )
    days = _PERIOD_DAYS[period_norm]

    parsed = _parse_tickers(tickers)
    if len(parsed) > TICKER_CAP:
        raise HTTPException(
            status_code=400,
            detail=f"tickers list exceeds cap of {TICKER_CAP}",
        )

    if not parsed:
        return {"as_of": None, "period": period_norm, "series": {}}

    # Stable cache key — order-independent so two callers asking for the
    # same set in different order hit the same entry.
    key = f"sparklines:{period_norm}:" + ",".join(sorted(parsed))
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={
                "X-Cache": "HIT-MEM-SPARK",
                # Private — auth-gated endpoint, no shared edge cache.
                "Cache-Control": "private, max-age=60",
            },
        )

    series = _fetch_sparklines(parsed, days)
    payload = {
        "as_of": datetime.now(_IST).isoformat(),
        "period": period_norm,
        "series": series,
    }
    try:
        cache.set(key, payload, ttl=60)
    except Exception:
        pass

    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, max-age=60"},
    )
