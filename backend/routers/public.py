# backend/routers/public.py
# ═══════════════════════════════════════════════════════════════
# Public (no-auth) API endpoints for SEO pages, landing page,
# and shareable content. All endpoints cached aggressively.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import time as _time
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.public")

router = APIRouter(prefix="/api/v1/public", tags=["public"])


# ── Helpers ───────────────────────────────────────────────────

def _get_db_session():
    """Get a pipeline DB session (Aiven Postgres). Returns None on failure."""
    try:
        from backend.services.analysis_service import _get_pipeline_session
        return _get_pipeline_session()
    except Exception:
        return None


def _safe_close(session) -> None:
    if session:
        try:
            session.close()
        except Exception:
            pass


def _extract_analysis_summary(result) -> dict:
    """Extract a flat summary dict from a full AnalysisResponse object."""
    v = result.valuation
    q = result.quality
    c = result.company
    return {
        "ticker": result.ticker,
        "company_name": c.company_name,
        "sector": c.sector,
        "industry": getattr(c, "industry", ""),
        "exchange": getattr(c, "exchange", "NSE"),
        "currency": getattr(c, "currency", "INR"),
        "fair_value": round(v.fair_value, 2),
        "current_price": round(v.current_price, 2),
        "mos": round(v.margin_of_safety, 1),
        "verdict": v.verdict,
        "score": q.yieldiq_score,
        "grade": q.grade,
        "moat": q.moat,
        "piotroski": q.piotroski_score,
        "bear_case": round(v.bear_case, 2),
        "base_case": round(v.base_case, 2),
        "bull_case": round(v.bull_case, 2),
        "wacc": round(v.wacc, 4),
        "confidence": v.confidence_score,
        "roe": round(q.roe, 2) if q.roe else None,
        "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
        "market_cap": c.market_cap,
        "ai_summary_snippet": (
            result.ai_summary[:200] + "..." if result.ai_summary and len(result.ai_summary) > 200
            else result.ai_summary
        ),
        "last_updated": result.timestamp,
    }


# ═══════════════════════════════════════════════════════════════
# TASK 5 — Landing page endpoints
# ═══════════════════════════════════════════════════════════════

@router.get("/recent-activity")
async def get_recent_activity(limit: int = Query(default=10, le=20)):
    """
    Recent analyses from fair_value_history for the live activity feed.
    No auth required. 5-minute cache.
    """
    _cache_key = f"public:recent-activity:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    results = []
    db = _get_db_session()
    if db:
        try:
            from data_pipeline.models import FairValueHistory
            rows = (
                db.query(FairValueHistory)
                .order_by(FairValueHistory.date.desc(), FairValueHistory.id.desc())
                .limit(limit)
                .all()
            )
            for r in rows:
                display = r.ticker.replace(".NS", "").replace(".BO", "")
                verdict_text = (r.verdict or "").replace("_", " ")
                results.append({
                    "ticker": r.ticker,
                    "display_ticker": display,
                    "company_name": display,  # will be enriched below
                    "fair_value": r.fair_value,
                    "price": r.price,
                    "mos_pct": r.mos_pct,
                    "verdict": verdict_text,
                    "date": r.date.isoformat() if r.date else None,
                })
            # Enrich company names from analysis cache
            for item in results:
                cached_analysis = cache.get(f"analysis:{item['ticker']}")
                if cached_analysis and hasattr(cached_analysis, "company"):
                    item["company_name"] = cached_analysis.company.company_name
        except Exception as e:
            logger.warning(f"recent-activity DB query failed: {e}")
        finally:
            _safe_close(db)

    # Fallback: scan cache if DB unavailable
    if not results:
        for key in list(cache._store.keys()):
            if not key.startswith("analysis:"):
                continue
            val = cache.get(key)
            if val and hasattr(val, "valuation"):
                display = val.ticker.replace(".NS", "").replace(".BO", "")
                results.append({
                    "ticker": val.ticker,
                    "display_ticker": display,
                    "company_name": val.company.company_name,
                    "fair_value": round(val.valuation.fair_value, 2),
                    "price": round(val.valuation.current_price, 2),
                    "mos_pct": round(val.valuation.margin_of_safety, 1),
                    "verdict": val.valuation.verdict.replace("_", " "),
                    "date": val.timestamp[:10] if val.timestamp else None,
                })
            if len(results) >= limit:
                break

    cache.set(_cache_key, results, ttl=300)
    return results


@router.get("/demo-cards")
async def get_demo_cards():
    """
    Return up to 4 cached analyses for the hero rotating demo card.
    No auth required. 2-minute cache.
    """
    _cache_key = "public:demo-cards"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    # Preferred tickers for the demo card rotation
    preferred = ["ITC.NS", "RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]
    cards = []

    for ticker in preferred:
        val = cache.get(f"analysis:{ticker}")
        if val and hasattr(val, "valuation"):
            v = val.valuation
            q = val.quality
            cards.append({
                "ticker": val.ticker,
                "display_ticker": ticker.replace(".NS", ""),
                "company_name": val.company.company_name,
                "sector": val.company.sector,
                "current_price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "grade": q.grade,
                "moat": q.moat,
                "bear_case": round(v.bear_case, 2),
                "base_case": round(v.base_case, 2),
                "bull_case": round(v.bull_case, 2),
            })
        if len(cards) >= 4:
            break

    cache.set(_cache_key, cards, ttl=120)
    return cards


# ═══════════════════════════════════════════════════════════════
# TASK 1 — Stock SEO page endpoints
# ═══════════════════════════════════════════════════════════════

@router.get("/stock-summary/{ticker}")
async def get_stock_summary(ticker: str):
    """
    Public stock summary for SEO pages. No auth required.
    1-hour cache. Checks analysis cache first, then runs analysis.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases
    try:
        from backend.routers.analysis import TICKER_ALIASES
        ticker = TICKER_ALIASES.get(ticker, ticker)
    except Exception:
        pass

    _cache_key = f"public:stock-summary:{ticker}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    # Try in-memory analysis cache first
    analysis_cached = cache.get(f"analysis:{ticker}")
    if analysis_cached and hasattr(analysis_cached, "valuation"):
        summary = _extract_analysis_summary(analysis_cached)
        cache.set(_cache_key, summary, ttl=3600)
        return summary

    # Run analysis if not cached
    try:
        from backend.services import analysis_service as service
        result = service.get_full_analysis(ticker)
        summary = _extract_analysis_summary(result)
        cache.set(_cache_key, summary, ttl=3600)
        return summary
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "no data" in err_str:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
        logger.warning(f"stock-summary failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Analysis unavailable")


@router.get("/all-tickers")
async def get_all_tickers():
    """
    All tickers with last update date — for sitemap generation.
    No auth required. 24-hour cache.
    """
    _cache_key = "public:all-tickers"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    tickers = []

    # Source 1: fair_value_history table
    db = _get_db_session()
    if db:
        try:
            from sqlalchemy import func
            from data_pipeline.models import FairValueHistory
            rows = (
                db.query(
                    FairValueHistory.ticker,
                    func.max(FairValueHistory.date).label("last_updated"),
                )
                .group_by(FairValueHistory.ticker)
                .all()
            )
            for r in rows:
                display = r.ticker.replace(".NS", "").replace(".BO", "")
                tickers.append({
                    "ticker": display,
                    "full_ticker": r.ticker,
                    "last_updated": r.last_updated.isoformat() if r.last_updated else None,
                })
        except Exception as e:
            logger.warning(f"all-tickers DB query failed: {e}")
        finally:
            _safe_close(db)

    # Source 2: analysis cache fallback
    if not tickers:
        seen = set()
        for key in list(cache._store.keys()):
            if key.startswith("analysis:") and ".NS" in key:
                t = key.replace("analysis:", "")
                if t not in seen:
                    seen.add(t)
                    display = t.replace(".NS", "").replace(".BO", "")
                    tickers.append({
                        "ticker": display,
                        "full_ticker": t,
                        "last_updated": None,
                    })

    cache.set(_cache_key, tickers, ttl=86400)
    return tickers
