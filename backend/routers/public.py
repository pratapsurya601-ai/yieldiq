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


# ═══════════════════════════════════════════════════════════════
# TASK 2 — Index dashboard endpoints
# ═══════════════════════════════════════════════════════════════

INDICES: dict[str, dict] = {
    "nifty50": {
        "name": "Nifty 50 Valuation Dashboard",
        "description": "All 50 Nifty 50 stocks ranked by DCF fair value",
        "tickers": [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
            "SBIN.NS", "ICICIBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
            "WIPRO.NS", "AXISBANK.NS", "KOTAKBANK.NS", "LT.NS", "SUNPHARMA.NS",
            "HCLTECH.NS", "NESTLEIND.NS", "ASIANPAINT.NS", "ULTRACEMCO.NS", "ADANIENT.NS",
            "ADANIPORTS.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "COALINDIA.NS",
            "BHARTIARTL.NS", "DIVISLAB.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS",
            "HINDUNILVR.NS", "TATASTEEL.NS", "TECHM.NS", "APOLLOHOSP.NS", "BRITANNIA.NS",
            "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "INDUSINDBK.NS", "GRASIM.NS", "JSWSTEEL.NS",
            "BPCL.NS", "HINDALCO.NS", "M&M.NS", "TRENT.NS", "BEL.NS",
            "SHRIRAMFIN.NS", "ETERNAL.NS", "HAL.NS", "DMART.NS", "TATACONSUM.NS",
        ],
    },
    "nifty-bank": {
        "name": "Nifty Bank Valuation Dashboard",
        "description": "All Nifty Bank stocks ranked by DCF fair value",
        "tickers": [
            "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS",
            "SBIN.NS", "INDUSINDBK.NS", "BANDHANBNK.NS", "FEDERALBNK.NS",
            "BAJFINANCE.NS", "BAJAJFINSV.NS", "CHOLAFIN.NS", "SHRIRAMFIN.NS",
        ],
    },
    "nifty-it": {
        "name": "Nifty IT Valuation Dashboard",
        "description": "All Nifty IT stocks ranked by DCF fair value",
        "tickers": [
            "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
            "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "LTTS.NS",
        ],
    },
}


@router.get("/index-dashboard/{index_id}")
async def get_index_dashboard(index_id: str):
    """
    Valuation data for all stocks in an index. No auth required.
    15-minute cache.
    """
    if index_id not in INDICES:
        raise HTTPException(status_code=404, detail=f"Index '{index_id}' not found")

    _cache_key = f"public:index:{index_id}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    config = INDICES[index_id]
    stocks = []

    for ticker in config["tickers"]:
        # Try analysis cache
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            v = analysis.valuation
            q = analysis.quality
            c = analysis.company
            stocks.append({
                "ticker": ticker,
                "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": c.company_name,
                "sector": c.sector,
                "current_price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "grade": q.grade,
                "moat": q.moat,
                "market_cap": c.market_cap,
            })

    # Sort by score descending
    stocks.sort(key=lambda x: x.get("score", 0), reverse=True)

    result = {
        "index_id": index_id,
        "index_name": config["name"],
        "description": config["description"],
        "total_stocks": len(config["tickers"]),
        "available_stocks": len(stocks),
        "stocks": stocks,
        "summary": {
            "undervalued": sum(1 for s in stocks if s["verdict"] == "undervalued"),
            "fairly_valued": sum(1 for s in stocks if s["verdict"] == "fairly_valued"),
            "overvalued": sum(1 for s in stocks if s["verdict"] in ("overvalued", "avoid")),
            "most_undervalued": max(stocks, key=lambda x: x["mos"]) if stocks else None,
            "most_overvalued": min(stocks, key=lambda x: x["mos"]) if stocks else None,
        },
    }

    cache.set(_cache_key, result, ttl=900)
    return result


# ═══════════════════════════════════════════════════════════════
# TASK 3 — Public compare endpoint
# ═══════════════════════════════════════════════════════════════

@router.get("/compare")
async def public_compare(
    ticker1: str = Query(...),
    ticker2: str = Query(...),
):
    """
    Public stock comparison. No auth required. 1-hour cache.
    """
    t1 = ticker1.upper().strip()
    t2 = ticker2.upper().strip()
    if not t1.endswith(".NS") and not t1.endswith(".BO"):
        t1 = f"{t1}.NS"
    if not t2.endswith(".NS") and not t2.endswith(".BO"):
        t2 = f"{t2}.NS"

    # Resolve aliases
    try:
        from backend.routers.analysis import TICKER_ALIASES
        t1 = TICKER_ALIASES.get(t1, t1)
        t2 = TICKER_ALIASES.get(t2, t2)
    except Exception:
        pass

    # Sorted key for consistent caching
    pair = tuple(sorted([t1, t2]))
    _cache_key = f"public:compare:{pair[0]}:{pair[1]}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    def _get_stock_data(ticker: str) -> dict | None:
        # Try cache first
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            v = analysis.valuation
            q = analysis.quality
            c = analysis.company
            return {
                "ticker": ticker,
                "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": c.company_name,
                "sector": c.sector,
                "price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "piotroski": q.piotroski_score,
                "moat": q.moat,
                "moat_score": q.moat_score,
                "wacc": round(v.wacc, 4),
                "fcf_growth": round(v.fcf_growth_rate, 4) if v.fcf_growth_rate else None,
                "confidence": v.confidence_score,
                "roe": round(q.roe, 2) if q.roe else None,
                "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            }
        # Try running analysis
        try:
            from backend.services import analysis_service as service
            result = service.get_full_analysis(ticker)
            v = result.valuation
            q = result.quality
            c = result.company
            return {
                "ticker": ticker,
                "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": c.company_name,
                "sector": c.sector,
                "price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "piotroski": q.piotroski_score,
                "moat": q.moat,
                "moat_score": q.moat_score,
                "wacc": round(v.wacc, 4),
                "fcf_growth": round(v.fcf_growth_rate, 4) if v.fcf_growth_rate else None,
                "confidence": v.confidence_score,
                "roe": round(q.roe, 2) if q.roe else None,
                "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            }
        except Exception:
            return None

    s1 = _get_stock_data(t1)
    s2 = _get_stock_data(t2)

    if not s1 or not s2:
        missing = t1 if not s1 else t2
        raise HTTPException(status_code=404, detail=f"Could not get data for {missing}")

    # Determine winners
    def _winner(key: str, higher_is_better: bool = True):
        v1, v2 = s1.get(key), s2.get(key)
        if v1 is None or v2 is None:
            return "tie"
        if higher_is_better:
            return "stock1" if v1 > v2 else "stock2" if v2 > v1 else "tie"
        return "stock1" if v1 < v2 else "stock2" if v2 < v1 else "tie"

    winner = {
        "score": _winner("score"),
        "value": _winner("mos"),
        "quality": _winner("piotroski"),
        "moat": _winner("moat_score"),
    }

    # Overall winner
    w1 = sum(1 for v in winner.values() if v == "stock1")
    w2 = sum(1 for v in winner.values() if v == "stock2")
    overall = "stock1" if w1 > w2 else "stock2" if w2 > w1 else "tie"

    result = {
        "stock1": s1,
        "stock2": s2,
        "winner": winner,
        "overall_winner": overall,
    }

    cache.set(_cache_key, result, ttl=3600)
    return result
