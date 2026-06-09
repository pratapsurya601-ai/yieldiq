# backend/routers/market.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.models.responses import MarketPulseResponse, SectorOverviewItem
from backend.services.data_service import DataService
from backend.services.cache_service import cache
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/market", tags=["market"])
data_service = DataService()
log = logging.getLogger("yieldiq.market")

# IST tzinfo for the as_of timestamp and the stale-data threshold check.
# Using a fixed offset is fine: India never observes DST and the offset
# has been stable since 1947.
_IST = timezone(timedelta(hours=5, minutes=30))


def _pipeline_session():
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


@router.get("/pulse", response_model=MarketPulseResponse)
async def get_market_pulse(
    user: dict = Depends(get_current_user),
    include_macro: bool = Query(default=False),
):
    """
    Market indices + fear/greed.

    Pass ``?include_macro=true`` to additionally fetch FII/DII
    flows, FX, commodities and the risk-free rate. Macro fields
    are optional and default to ``null`` — clients unaware of
    them continue to work.
    """
    # Tier-0 RAW dict cache. Data is identical for all users
    # (market indices, not user-specific) so a single shared cache
    # entry is safe. Auth is still enforced — the cache check
    # runs AFTER get_current_user via Depends.
    _raw_key = f"market:pulse:raw:{int(bool(include_macro))}"
    try:
        _raw = cache.get(_raw_key)
    except Exception:
        _raw = None
    if _raw is not None:
        return JSONResponse(
            content=_raw,
            headers={
                "X-Cache": "HIT-MEM-RAW",
                # Auth-gated endpoint — use private so Vercel's
                # shared edge cache does not cache responses
                # across authenticated users. 60s max-age still
                # lets the browser avoid repeat calls during
                # page navigation.
                "Cache-Control": "private, max-age=60",
            },
        )

    base = data_service.get_market_pulse()

    if not include_macro:
        try:
            _dump = base.model_dump(mode="json") if hasattr(base, "model_dump") else base
            cache.set(_raw_key, _dump, ttl=60)
        except Exception:
            pass
        return base

    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        db = _pipeline_session()
        try:
            snapshot = svc.get_snapshot(cache, db)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

        base_dict = base.model_dump()
        allowed = set(MarketPulseResponse.model_fields.keys())
        for k, v in (snapshot or {}).items():
            if k in allowed:
                base_dict[k] = v
        # Attach AI summary if already cached (24h) — avoid
        # blocking the /pulse call on a live LLM roundtrip.
        cached_summary = cache.get("macro:ai_summary")
        if cached_summary:
            base_dict["ai_summary"] = cached_summary

        # ── INR-conversion for Gold/Silver tile display (2026-06-09) ─
        # MarketsStrip shows commodities as ₹X/10g for the Indian
        # retail audience. Gold/silver come in USD/troy-ounce; one
        # troy ounce is 31.1035 grams. Render value = USD price ×
        # USD/INR × (10 / 31.1035). Skip silently when either input
        # is missing — the tile then degrades to USD or to "—".
        try:
            _usd_inr = base_dict.get("usd_inr")
            if _usd_inr:
                _gold_usd = base_dict.get("gold_usd")
                if _gold_usd:
                    base_dict["gold_inr_per_10g"] = round(
                        float(_gold_usd) * float(_usd_inr) * (10.0 / 31.1035), 0
                    )
                _silver_usd = base_dict.get("silver_usd")
                if _silver_usd:
                    base_dict["silver_inr_per_10g"] = round(
                        float(_silver_usd) * float(_usd_inr) * (10.0 / 31.1035), 0
                    )
        except (TypeError, ValueError) as _conv_exc:
            log.debug("commodity INR-conv skipped: %s", _conv_exc)

        out = MarketPulseResponse(**base_dict)
        try:
            cache.set(_raw_key, out.model_dump(mode="json"), ttl=60)
        except Exception:
            pass
        return out
    except Exception as exc:
        log.debug("Macro merge failed: %s", exc)
        return base


@router.get("/macro-summary")
async def get_macro_summary(user: dict = Depends(get_current_user)):
    """
    AI-generated 2-sentence market commentary. Cached 24 hours.
    Separate from ``/pulse`` so the main market strip never waits
    on an LLM roundtrip.
    """
    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        snapshot = cache.get("macro:snapshot") or {}
        summary = svc.get_ai_summary(snapshot, cache)
        return {"summary": summary}
    except Exception as exc:
        log.debug("macro-summary failed: %s", exc)
        return {"summary": None}


@router.get("/sectors", response_model=list[SectorOverviewItem])
async def get_sector_overview(user: dict = Depends(get_current_user)):
    """Sector valuation summary."""
    return data_service.get_sector_overview()


# ── Today's Movers (2026-06-09) ────────────────────────────────
# Daily-engagement widget for /home — top N gainers + losers from the
# selected cohort (default NIFTY 500). Powered by the most-recent two
# trading days in `daily_prices`. NEUTRAL framing: this is a market-data
# surface, not a recommendation engine. The router copy never uses
# "buy"/"sell"/"pick" verbs — only "% change".

def _compute_today_movers(cohort: str, limit: int) -> dict:
    """Query the two most recent trading days and rank by % change.

    Returns the JSON dict the endpoint streams. Pure function so the
    cache layer in `get_today_movers` can dump it directly.
    """
    cohort_norm = (cohort or "nifty500").lower()
    # Only NIFTY 500 is wired for v1. Other cohorts fall back to the
    # NIFTY 500 universe rather than 500-erroring on the frontend; the
    # cohort param is forward-compat for nifty50 / nifty100.
    nifty_index = "NIFTY 500"
    if cohort_norm == "nifty50":
        nifty_index = "NIFTY 50"
    elif cohort_norm == "nifty100":
        nifty_index = "NIFTY 100"

    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception as exc:
        log.warning("today-movers: pipeline session import failed: %s", exc)
        return {"as_of": None, "gainers": [], "losers": [], "stale": True}

    if PipelineSession is None:
        return {"as_of": None, "gainers": [], "losers": [], "stale": True}

    sess = PipelineSession()
    try:
        # Pull the two most-recent distinct trade dates that intersect
        # the cohort. Selecting from the cohort-filtered subquery means
        # we ignore data-load lag on stocks outside the cohort.
        row = sess.execute(
            text(
                """
                SELECT DISTINCT dp.trade_date
                FROM daily_prices dp
                JOIN nse_sector_constituents nc
                  ON UPPER(nc.ticker) = UPPER(dp.ticker)
                WHERE nc.nifty_index = :idx
                ORDER BY dp.trade_date DESC
                LIMIT 2
                """
            ),
            {"idx": nifty_index},
        ).fetchall()
        if len(row) < 2:
            return {"as_of": None, "gainers": [], "losers": [], "stale": True}

        latest_date, prev_date = row[0][0], row[1][0]

        # Stale-data check: if the latest trading day is more than 24h
        # behind today's IST date during market hours, the bhavcopy
        # ingest is lagging and we surface an empty list with a hint.
        now_ist = datetime.now(_IST)
        age_days = (now_ist.date() - latest_date).days
        # Threshold: 4 calendar days handles weekends + 1 public
        # holiday tolerantly; beyond that the pipeline really is stale.
        is_stale = age_days > 4

        # Pull both days for every cohort ticker in a single query.
        # Pivoting via FILTER aggregates avoids two round-trips and any
        # python-side join. `s.is_active` filters delisted tickers.
        rows = sess.execute(
            text(
                """
                SELECT
                    dp.ticker,
                    s.company_name,
                    MAX(CASE WHEN dp.trade_date = :latest THEN dp.close_price END)  AS close_latest,
                    MAX(CASE WHEN dp.trade_date = :prev   THEN dp.close_price END)  AS close_prev
                FROM daily_prices dp
                JOIN nse_sector_constituents nc
                  ON UPPER(nc.ticker) = UPPER(dp.ticker)
                LEFT JOIN stocks s
                  ON UPPER(s.ticker) = UPPER(dp.ticker)
                WHERE nc.nifty_index = :idx
                  AND dp.trade_date IN (:latest, :prev)
                  AND COALESCE(s.is_active, TRUE) = TRUE
                GROUP BY dp.ticker, s.company_name
                """
            ),
            {"idx": nifty_index, "latest": latest_date, "prev": prev_date},
        ).fetchall()

        movers: list[dict] = []
        for tk, name, close_l, close_p in rows:
            # Drop tickers with a null day (suspended / fresh listing).
            # Drop non-positive prev_close (would explode the ratio).
            if close_l is None or close_p is None:
                continue
            try:
                cl, cp = float(close_l), float(close_p)
            except (TypeError, ValueError):
                continue
            if cp <= 0:
                continue
            change_pct = (cl - cp) / cp * 100
            # Clip clearly-broken data points (>50% single-day moves are
            # almost always corporate-action splits that the bhavcopy
            # adjustment lagged on). Surfacing them as #1 mover misleads.
            if abs(change_pct) > 50:
                continue
            movers.append(
                {
                    "ticker": (tk or "").replace(".NS", ""),
                    "company_name": name or tk or "",
                    "change_pct": round(change_pct, 2),
                    "close": round(cl, 2),
                    "prev_close": round(cp, 2),
                }
            )

        gainers = sorted(movers, key=lambda m: m["change_pct"], reverse=True)[:limit]
        losers = sorted(movers, key=lambda m: m["change_pct"])[:limit]

        as_of_iso = datetime.combine(latest_date, datetime.min.time()).replace(
            hour=15, minute=30, tzinfo=_IST
        ).isoformat()

        return {
            "as_of": as_of_iso,
            "gainers": gainers if not is_stale else [],
            "losers": losers if not is_stale else [],
            "stale": is_stale,
            "cohort": cohort_norm,
        }
    finally:
        try:
            sess.close()
        except Exception:
            pass


@router.get("/today-movers")
async def get_today_movers(
    user: dict = Depends(get_current_user),
    cohort: str = Query(default="nifty500"),
    limit: int = Query(default=5, ge=1, le=20),
):
    """Top gainers / losers from the cohort, computed off the two most-
    recent trading days in `daily_prices`.

    Cached 60s at the router level — this is the home-page hot path and
    the underlying data only refreshes once a day post-close. Cohort +
    limit are part of the cache key so distinct calls stay isolated.
    """
    cache_key = f"market:today_movers:{cohort.lower()}:{int(limit)}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={
                "X-Cache": "HIT-MEM-MOVERS",
                "Cache-Control": "private, max-age=60",
            },
        )

    payload = _compute_today_movers(cohort, limit)
    try:
        cache.set(cache_key, payload, ttl=60)
    except Exception:
        pass
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, max-age=60"},
    )
