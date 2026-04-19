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
from fastapi.responses import JSONResponse

from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.public")

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _cached_json(content, s_maxage: int, swr: int = 3600, extra_headers: dict | None = None):
    """Wrap content in a JSONResponse with Vercel-edge Cache-Control.

    `s-maxage` applies to shared caches only (Vercel edge, CDNs) so
    browsers still revalidate; `stale-while-revalidate` lets the
    edge serve stale for `swr` seconds while refreshing in the
    background. Both values are in seconds.

    `extra_headers` lets callers stamp observability headers (e.g.
    X-Source) without losing the Cache-Control contract.
    """
    headers = {
        "Cache-Control": f"public, s-maxage={s_maxage}, stale-while-revalidate={swr}",
    }
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(content=content, headers=headers)


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
    """Extract a flat summary dict from a full AnalysisResponse object.

    Single-Source-of-Truth contract (PR1):
        Every value MUST be a direct read from the AnalysisResponse the
        analysis pipeline produced. NO local computation, NO synthesised
        fallbacks. If the SEO frontend asks for a field that is not on
        AnalysisResponse, return None here and log — that field must be
        added to the canonical schema in a follow-up PR; we do NOT
        materialise it locally because that re-creates the very drift
        we just deleted.
    """
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
        # Phase 2.1 ratios — Optional; None renders as "—" on frontend.
        "roce": getattr(q, "roce", None),
        "debt_ebitda": getattr(q, "debt_ebitda", None),
        "interest_coverage": getattr(q, "interest_coverage", None),
        "current_ratio": getattr(q, "current_ratio", None),
        "asset_turnover": getattr(q, "asset_turnover", None),
        "revenue_cagr_3y": getattr(q, "revenue_cagr_3y", None),
        "revenue_cagr_5y": getattr(q, "revenue_cagr_5y", None),
        "ev_ebitda": (getattr(result, "insights", None) and getattr(result.insights, "ev_ebitda", None)),
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
        return _cached_json(cached, s_maxage=60, swr=300)

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
    # 1 min fresh at edge, 5 min stale-while-revalidate — list updates
    # every few minutes as new analyses stream in.
    return _cached_json(results, s_maxage=60, swr=300)


@router.get("/demo-cards")
async def get_demo_cards():
    """
    Return up to 4 cached analyses for the hero rotating demo card.
    No auth required. 2-minute cache.
    """
    _cache_key = "public:demo-cards"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=120, swr=600)

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
    return _cached_json(cards, s_maxage=120, swr=600)


# ═══════════════════════════════════════════════════════════════
# TASK 1 — Stock SEO page endpoints
# ═══════════════════════════════════════════════════════════════

@router.get("/stock-summary/{ticker}")
async def get_stock_summary(ticker: str):
    """
    Public stock summary for SEO pages. No auth required.

    Single-Source-of-Truth (PR1, 2026-04-19):
        Reads exclusively from `analysis_cache` (persisted v35 payload).
        NEVER recomputes locally — that path was the cause of the public/
        authed FV drift (HCLTECH, etc.). If the cache is empty for a
        ticker, we return a 503 "data under review" payload rather than
        synthesizing a different number than the authed endpoint.

        All fields the SEO page renders are sourced from the canonical
        AnalysisResponse schema. Any field the SEO page wants that is NOT
        in the cache schema must be added to AnalysisResponse — it cannot
        be back-doored here without re-introducing the drift bug.

    Cache: edge s-maxage=600, swr=3600. X-Source header for observability.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases (e.g. ZOMATO.NS → ETERNAL.NS)
    try:
        from backend.routers.analysis import TICKER_ALIASES
        ticker = TICKER_ALIASES.get(ticker, ticker)
    except Exception:
        pass

    _cache_key = f"public:stock-summary:{ticker}"
    _cached_summary = cache.get(_cache_key)
    if _cached_summary is not None:
        return _cached_json(
            _cached_summary,
            s_maxage=600,
            swr=3600,
            extra_headers={"X-Source": "analysis_cache_v35", "X-Cache": "HIT"},
        )

    # Resolve the canonical AnalysisResponse from the same place the
    # authed endpoint serves it. Tier 1 is the in-memory cache (warm
    # path); tier 2 is the persistent analysis_cache table (survives
    # Railway redeploys). Both are populated only by the analysis
    # service, never by this router.
    analysis_cached = cache.get(f"analysis:{ticker}")
    if analysis_cached is None or not hasattr(analysis_cached, "valuation"):
        try:
            from backend.services import analysis_cache_service
            from backend.models.responses import AnalysisResponse
            _db_payload = analysis_cache_service.get_cached(ticker)
            if _db_payload:
                analysis_cached = AnalysisResponse(**_db_payload)
                # Populate tier-1 so subsequent requests on this worker
                # skip the DB round-trip.
                cache.set(f"analysis:{ticker}", analysis_cached, ttl=86400)
        except Exception as _exc:
            logger.info(
                "stock-summary: analysis_cache tier-2 lookup failed for %s: %s",
                ticker, _exc,
            )

    # Cache miss on BOTH tiers → 503 under_review. We do NOT recompute
    # here. The warmer / nightly job is responsible for populating the
    # cache; serving a "different" FV from a freshly-computed analysis
    # would silently re-introduce the SoT drift bug PR1 closes.
    if analysis_cached is None or not hasattr(analysis_cached, "valuation"):
        logger.info("stock-summary cache miss for %s — returning under_review", ticker)
        return JSONResponse(
            status_code=503,
            content={
                "status": "under_review",
                "ticker": ticker,
                "message": "Analysis is being prepared for this ticker. Please check back shortly.",
                "last_validated_at": "",
                "reason": "cache_miss_no_recompute_on_public_path",
                "issue_count": 0,
            },
            headers={
                "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
                "X-Source": "analysis_cache_v35",
                "X-Cache": "MISS",
            },
        )

    # Quarantine gate — same as the authed endpoint. If validators flag
    # this payload, return the under_review structure WITHOUT caching it
    # under the clean key.
    from backend.services.validators import check_and_quarantine
    quarantine = check_and_quarantine(ticker, analysis_cached)
    if quarantine is not None:
        return quarantine

    summary = _extract_analysis_summary(analysis_cached)
    cache.set(_cache_key, summary, ttl=3600)
    return _cached_json(
        summary,
        s_maxage=600,
        swr=3600,
        extra_headers={"X-Source": "analysis_cache_v35", "X-Cache": "MISS"},
    )


@router.get("/all-tickers")
async def get_all_tickers():
    """
    All tickers with last update date — for sitemap generation + universe
    quality scans. Merges FairValueHistory (stocks users have analyzed)
    with NSE_UNIVERSE (the curated pipeline coverage list) so that new
    tickers appear in scans even before any user has analyzed them.
    No auth required. 24-hour cache.
    """
    _cache_key = "public:all-tickers"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=86400, swr=172800)

    tickers = []
    seen_symbols: set[str] = set()

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
                if display in seen_symbols:
                    continue
                seen_symbols.add(display)
                tickers.append({
                    "ticker": display,
                    "full_ticker": r.ticker,
                    "last_updated": r.last_updated.isoformat() if r.last_updated else None,
                })
        except Exception as e:
            logger.warning(f"all-tickers DB query failed: {e}")
        finally:
            _safe_close(db)

    # Source 2: analysis cache (additional coverage)
    for key in list(cache._store.keys()):
        if key.startswith("analysis:") and ".NS" in key:
            t = key.replace("analysis:", "")
            display = t.replace(".NS", "").replace(".BO", "")
            if display in seen_symbols:
                continue
            seen_symbols.add(display)
            tickers.append({
                "ticker": display,
                "full_ticker": t,
                "last_updated": None,
            })

    # Source 3: NSE_UNIVERSE (curated pipeline coverage — ~100 large-caps)
    # Ensures every tracked ticker appears in scans even if no user has
    # analyzed it yet. This is what the universe-scan workflow iterates.
    try:
        from data_pipeline.pipeline import NSE_UNIVERSE
        for t in NSE_UNIVERSE:
            display = t.replace(".NS", "").replace(".BO", "")
            if display in seen_symbols:
                continue
            seen_symbols.add(display)
            tickers.append({
                "ticker": display,
                "full_ticker": f"{display}.NS",
                "last_updated": None,
            })
    except Exception as e:
        logger.warning(f"all-tickers NSE_UNIVERSE merge failed: {e}")

    cache.set(_cache_key, tickers, ttl=86400)
    return _cached_json(tickers, s_maxage=86400, swr=172800)


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
        return _cached_json(cached, s_maxage=300, swr=3600)

    config = INDICES[index_id]
    stocks = []

    # ── Quality gate ────────────────────────────────────────────
    # Hide any stock whose USER-FACING fair_value / price ratio is
    # suspicious. This is the number on screen — if it's > 3x or
    # > 150% MoS, it's almost certainly a unit/conversion bug.
    # (e.g. HCLTECH showing FV ₹6,075 vs price ₹1,434, +268% MoS).
    # We deliberately do NOT check the raw DCF IV because that's
    # pre-blend/pre-cap and legitimately diverges for overvalued
    # quality names after the PE blend.
    def _is_suspicious(fv: float, price: float, mos: float) -> str | None:
        if price > 0 and fv > 0:
            ratio = fv / price
            if ratio > 3.0:
                return f"FV={ratio:.1f}x price"
            if ratio < 0.15:
                return f"FV={ratio:.2f}x price"
        if abs(mos) > 200:
            return f"MoS={mos:.0f}%"
        return None

    hidden: list[dict] = []

    for ticker in config["tickers"]:
        # Try analysis cache
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            v = analysis.valuation
            q = analysis.quality
            c = analysis.company

            _reason = _is_suspicious(
                float(v.fair_value or 0),
                float(v.current_price or 0),
                float(v.margin_of_safety or 0),
            )
            if _reason:
                hidden.append({
                    "ticker": ticker,
                    "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                    "reason": _reason,
                })
                continue

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
        "hidden_for_quality": hidden,
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
    return _cached_json(result, s_maxage=300, swr=3600)


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

    def _flatten(analysis) -> dict:
        v = analysis.valuation
        q = analysis.quality
        c = analysis.company
        ev_ebitda = None
        try:
            ev_ebitda = getattr(analysis, "insights", None) and getattr(analysis.insights, "ev_ebitda", None)
        except Exception:
            ev_ebitda = None
        return {
            "ticker": analysis.ticker,
            "display_ticker": analysis.ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": c.company_name,
            "sector": c.sector,
            "price": round(v.current_price, 2),
            "current_price": round(v.current_price, 2),
            "fair_value": round(v.fair_value, 2),
            "mos": round(v.margin_of_safety, 1),
            "verdict": v.verdict,
            "score": q.yieldiq_score,
            "grade": q.grade,
            "piotroski": q.piotroski_score,
            "moat": q.moat,
            "moat_score": q.moat_score,
            "wacc": round(v.wacc, 4),
            "fcf_growth": round(v.fcf_growth_rate, 4) if v.fcf_growth_rate else None,
            "confidence": v.confidence_score,
            "roe": round(q.roe, 2) if q.roe else None,
            "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
            "market_cap": c.market_cap,
        }

    def _get_stock_data(ticker: str) -> dict | None:
        from backend.services.validators import check_and_quarantine
        # Try cache first
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            if check_and_quarantine(ticker, analysis) is not None:
                return None
            return _flatten(analysis)
        # Try running analysis
        try:
            from backend.services.analysis_service import AnalysisService
            result = AnalysisService().get_full_analysis(ticker)
            if check_and_quarantine(ticker, result) is not None:
                return None
            return _flatten(result)
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
        "stock1_wins": w1,
        "stock2_wins": w2,
        "total_metrics": len(winner),
    }

    cache.set(_cache_key, result, ttl=3600)
    return result

# ---------------------------------------------------------------
# Earnings Calendar � public endpoint
# ---------------------------------------------------------------

@router.get("/earnings-calendar")
async def get_earnings_calendar(
    days: int = Query(default=14, le=60),
    limit: int = Query(default=100, le=500),
):
    """
    Upcoming earnings announcements from NSE event calendar.
    No auth required. 1-hour cache.
    """
    _cache_key = f"public:earnings:{days}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    events = []
    db = _get_db_session()
    if db:
        try:
            from data_pipeline.models import UpcomingEarnings, Stock
            cutoff = date.today() + timedelta(days=days)
            today = date.today()

            rows = (
                db.query(UpcomingEarnings, Stock)
                .outerjoin(Stock, UpcomingEarnings.ticker == Stock.ticker)
                .filter(UpcomingEarnings.event_date >= today)
                .filter(UpcomingEarnings.event_date <= cutoff)
                .order_by(UpcomingEarnings.event_date.asc())
                .limit(limit)
                .all()
            )

            for ue, stock in rows:
                display = ue.ticker.replace(".NS", "").replace(".BO", "")
                days_away = (ue.event_date - today).days
                events.append({
                    "ticker": ue.ticker,
                    "display_ticker": display,
                    "company_name": (stock.company_name if stock else display),
                    "sector": (stock.sector if stock else None),
                    "event_date": ue.event_date.isoformat(),
                    "event_type": ue.event_type or "Financial Results",
                    "purpose": ue.purpose or "",
                    "days_away": days_away,
                })
        except Exception as e:
            logger.warning(f"earnings-calendar query failed: {e}")
        finally:
            _safe_close(db)

    result = {
        "total": len(events),
        "window_days": days,
        "by_date": _group_earnings_by_date(events),
        "events": events,
    }
    cache.set(_cache_key, result, ttl=3600)
    return result


def _group_earnings_by_date(events: list) -> list:
    """Group events by date for calendar view."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for e in events:
        grouped[e["event_date"]].append(e)
    return [
        {"date": d, "count": len(items), "tickers": [e["display_ticker"] for e in items[:10]]}
        for d, items in sorted(grouped.items())
    ]

# ---------------------------------------------------------------
# Pre-built Screens � public landing pages (SEO)
# ---------------------------------------------------------------

SCREENS: dict[str, dict] = {
    "high-roce": {
        "name": "High ROCE Stocks",
        "description": "Indian stocks with ROCE > 20% � capital-efficient businesses",
        "h1": "High ROCE Stocks (ROCE > 20%)",
        "intro": "Companies generating 20%+ return on capital employed. High ROCE indicates efficient capital allocation and pricing power.",
        "filter": lambda s: (s.get("roce") or 0) >= 20,
        "sort_key": "roce",
        "sort_desc": True,
    },
    "low-pe-quality": {
        "name": "Low P/E Quality Stocks",
        "description": "P/E < 20 + Piotroski F-Score >= 7 � value with quality",
        "h1": "Low P/E Quality Stocks (P/E < 20, F-Score \u2265 7)",
        "intro": "Combines value (low P/E) with quality (high Piotroski F-Score). Filters out value traps by requiring strong fundamentals.",
        "filter": lambda s: ((s.get("pe_ratio") or 999) < 20) and ((s.get("piotroski") or 0) >= 7),
        "sort_key": "score",
        "sort_desc": True,
    },
    "debt-free": {
        "name": "Debt-Free Stocks",
        "description": "Indian stocks with Debt-to-Equity < 0.2 � minimal leverage risk",
        "h1": "Debt-Free Indian Stocks (D/E < 0.2)",
        "intro": "Companies with virtually no debt on the balance sheet. Lower financial risk during downturns and rising rate environments.",
        "filter": lambda s: (s.get("de_ratio") is not None) and (s.get("de_ratio") < 0.2),
        "sort_key": "score",
        "sort_desc": True,
    },
    "undervalued-quality": {
        "name": "Undervalued Quality Stocks",
        "description": "YieldIQ Score >= 70 + Margin of Safety >= 20% � high-quality undervalued",
        "h1": "Undervalued Quality Stocks (Score \u2265 70, MoS \u2265 20%)",
        "intro": "Stocks with strong YieldIQ quality scores trading at meaningful discounts to fair value.",
        "filter": lambda s: ((s.get("score") or 0) >= 70) and ((s.get("mos") or 0) >= 20),
        "sort_key": "mos",
        "sort_desc": True,
    },
    "wide-moat": {
        "name": "Wide Moat Stocks",
        "description": "Indian companies with sustainable competitive advantages",
        "h1": "Wide Moat Stocks (Indian Equities)",
        "intro": "Companies with durable competitive advantages \u2014 brand pricing power, network effects, switching costs, or scale economies.",
        "filter": lambda s: s.get("moat") == "Wide",
        "sort_key": "score",
        "sort_desc": True,
    },
    "high-piotroski": {
        "name": "High Piotroski F-Score Stocks",
        "description": "Indian stocks with Piotroski F-Score 8 or 9 � top financial strength",
        "h1": "High Piotroski F-Score Stocks (F-Score 8-9)",
        "intro": "Joseph Piotroski\'s 9-point fundamental quality score. Companies scoring 8-9 show consistent profitability, efficiency, and balance sheet strength.",
        "filter": lambda s: (s.get("piotroski") or 0) >= 8,
        "sort_key": "piotroski",
        "sort_desc": True,
    },
}


@router.get("/screens")
async def list_screens():
    """List all available pre-built screens."""
    return [
        {
            "slug": slug,
            "name": cfg["name"],
            "description": cfg["description"],
        }
        for slug, cfg in SCREENS.items()
    ]


@router.get("/screens/{slug}")
async def get_screen(slug: str, limit: int = Query(default=50, le=200)):
    """
    Run a pre-built screen against the analysis cache.
    No auth required. 30-min cache.
    """
    if slug not in SCREENS:
        raise HTTPException(status_code=404, detail=f"Screen \'{slug}\' not found")

    _cache_key = f"public:screen:{slug}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    cfg = SCREENS[slug]
    candidates = []

    # Scan analysis cache for matching tickers
    for key in list(cache._store.keys()):
        if not key.startswith("analysis:") or ".NS" not in key:
            continue
        val = cache.get(key)
        if not val or not hasattr(val, "valuation"):
            continue
        v = val.valuation
        q = val.quality
        c = val.company
        # Compute pe_ratio if possible
        pe_ratio = None
        try:
            if v.current_price and getattr(v, "eps_ttm", None):
                pe_ratio = v.current_price / v.eps_ttm
        except Exception:
            pass

        stock_data = {
            "ticker": val.ticker,
            "display_ticker": val.ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": c.company_name,
            "sector": c.sector,
            "current_price": round(v.current_price, 2),
            "fair_value": round(v.fair_value, 2),
            "mos": round(v.margin_of_safety, 1),
            "verdict": v.verdict,
            "score": q.yieldiq_score,
            "grade": q.grade,
            "moat": q.moat,
            "piotroski": q.piotroski_score,
            "roe": round(q.roe, 2) if q.roe else None,
            "roce": round(q.roce, 2) if getattr(q, "roce", None) else None,
            "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
            "market_cap": c.market_cap,
        }
        if cfg["filter"](stock_data):
            candidates.append(stock_data)

    # Sort
    candidates.sort(key=lambda x: x.get(cfg["sort_key"]) or 0, reverse=cfg["sort_desc"])
    candidates = candidates[:limit]

    result = {
        "slug": slug,
        "name": cfg["name"],
        "description": cfg["description"],
        "h1": cfg["h1"],
        "intro": cfg["intro"],
        "total": len(candidates),
        "stocks": candidates,
    }
    cache.set(_cache_key, result, ttl=1800)
    return result


# ═══════════════════════════════════════════════════════════════
# Risk stats — drawdown, volatility, beta, returns
# ═══════════════════════════════════════════════════════════════

@router.get("/dupont/{ticker}")
async def get_dupont_analysis(ticker: str, years: int = Query(default=5, ge=3, le=10)):
    """
    DuPont decomposition of ROE over the last N years.

    ROE = Net Margin x Asset Turnover x Equity Multiplier
        = (PAT / Revenue) x (Revenue / Assets) x (Assets / Equity)

    Returns historical decomposition so user can see which lever
    (profitability, efficiency, or leverage) drives the return.

    No auth. 24-hour cache.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:dupont:{clean}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    db = _get_db_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        from data_pipeline.models import Financials, Stock
        from datetime import date as _date

        cutoff = _date.today().replace(year=_date.today().year - years)
        rows = (
            db.query(Financials)
            .filter(Financials.ticker == clean)
            .filter(Financials.period_type == "annual")
            .filter(Financials.period_end >= cutoff)
            .order_by(Financials.period_end.desc())
            .limit(years)
            .all()
        )

        if not rows:
            raise HTTPException(status_code=404, detail=f"No financial history for {clean}")

        # Company info
        stock = db.query(Stock).filter(Stock.ticker == clean).first()
        company_name = stock.company_name if stock else clean

        decomposition = []
        for r in rows:
            revenue = r.revenue or 0
            pat = r.pat or 0
            total_assets = r.total_assets or 0
            total_equity = r.total_equity or 0

            if revenue > 0 and total_assets > 0 and total_equity > 0:
                net_margin = pat / revenue
                asset_turnover = revenue / total_assets
                equity_multiplier = total_assets / total_equity
                roe = net_margin * asset_turnover * equity_multiplier

                # Also compute ROA as a sanity check
                roa = pat / total_assets if total_assets > 0 else 0

                decomposition.append({
                    "period_end": r.period_end.isoformat(),
                    "fy": f"FY{r.period_end.year}" if r.period_end.month <= 3 else f"FY{r.period_end.year + 1}",
                    "revenue_cr": round(revenue / 1e7, 1),
                    "pat_cr": round(pat / 1e7, 1),
                    "total_assets_cr": round(total_assets / 1e7, 1),
                    "total_equity_cr": round(total_equity / 1e7, 1),
                    "net_margin_pct": round(net_margin * 100, 2),
                    "asset_turnover": round(asset_turnover, 2),
                    "equity_multiplier": round(equity_multiplier, 2),
                    "roe_pct": round(roe * 100, 2),
                    "roa_pct": round(roa * 100, 2),
                })

        if not decomposition:
            raise HTTPException(status_code=404, detail=f"Insufficient financial data for {clean}")

        # Sort chronologically for display (oldest first)
        decomposition.sort(key=lambda x: x["period_end"])

        # Compute trend commentary
        commentary = _dupont_commentary(decomposition)

        result = {
            "ticker": ticker,
            "display_ticker": clean,
            "company_name": company_name,
            "years": len(decomposition),
            "periods": decomposition,
            "latest": decomposition[-1] if decomposition else None,
            "commentary": commentary,
        }
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"dupont failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="DuPont analysis failed")
    finally:
        _safe_close(db)


def _dupont_commentary(periods: list[dict]) -> str:
    """Generate plain-English commentary on DuPont trends."""
    if len(periods) < 2:
        return ""

    latest = periods[-1]
    oldest = periods[0]

    margin_delta = latest["net_margin_pct"] - oldest["net_margin_pct"]
    turnover_delta = latest["asset_turnover"] - oldest["asset_turnover"]
    leverage_delta = latest["equity_multiplier"] - oldest["equity_multiplier"]
    roe_delta = latest["roe_pct"] - oldest["roe_pct"]

    parts: list[str] = []

    if roe_delta > 1:
        parts.append(f"ROE improved by {roe_delta:.1f} pp over {len(periods)} years.")
    elif roe_delta < -1:
        parts.append(f"ROE declined by {abs(roe_delta):.1f} pp over {len(periods)} years.")
    else:
        parts.append(f"ROE stable at ~{latest['roe_pct']:.0f}%.")

    # Dominant driver
    drivers = []
    if abs(margin_delta) > 1:
        dir_ = "improving" if margin_delta > 0 else "declining"
        drivers.append(f"net margin {dir_} ({oldest['net_margin_pct']:.1f}% \u2192 {latest['net_margin_pct']:.1f}%)")
    if abs(turnover_delta) > 0.1:
        dir_ = "improving" if turnover_delta > 0 else "declining"
        drivers.append(f"asset turnover {dir_} ({oldest['asset_turnover']:.2f}x \u2192 {latest['asset_turnover']:.2f}x)")
    if abs(leverage_delta) > 0.2:
        dir_ = "rising" if leverage_delta > 0 else "falling"
        drivers.append(f"leverage {dir_} ({oldest['equity_multiplier']:.2f}x \u2192 {latest['equity_multiplier']:.2f}x)")

    if drivers:
        parts.append("Driven by " + ", ".join(drivers) + ".")

    # High leverage warning
    if latest["equity_multiplier"] > 4:
        parts.append("High financial leverage (equity multiplier > 4x) amplifies returns but also risk.")

    return " ".join(parts)


@router.get("/news/{ticker}")
async def get_ticker_news(ticker: str, days: int = Query(default=14, ge=1, le=60)):
    """
    Combined news + BSE filings for a single ticker.
    No auth, 1-hour cache.
    Returns up to 30 items sorted by recency.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:news:{clean}:{days}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from backend.services.news_service import fetch_all_news_for_ticker, summarize_filings
        items = fetch_all_news_for_ticker(clean, days=days)
        ai_summary = summarize_filings(items, max_items=5) if items else None
        result = {
            "ticker": ticker,
            "display_ticker": clean,
            "count": len(items),
            "items": items[:30],
            "ai_summary": ai_summary,
        }
        cache.set(_cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"news fetch failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="News unavailable")


@router.get("/news")
async def get_news_feed(days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=50, le=100)):
    """
    Aggregated BSE corporate filings feed (latest across all stocks).
    No auth, 30-min cache.
    """
    _cache_key = f"public:news-feed:{days}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from backend.services.news_service import fetch_bse_filings
        items = fetch_bse_filings(ticker=None, days=days, limit=limit)
        result = {
            "count": len(items),
            "items": items,
        }
        cache.set(_cache_key, result, ttl=1800)
        return result
    except Exception as e:
        logger.warning(f"news feed failed: {e}")
        raise HTTPException(status_code=500, detail="News feed unavailable")


@router.get("/backtest/screen/{slug}")
async def backtest_screen_endpoint(
    slug: str,
    years: int = Query(default=3, ge=1, le=5),
    rebalance: str = Query(default="quarterly", pattern="^(monthly|quarterly|yearly)$"),
):
    """
    Backtest the CURRENT constituents of a pre-built screen.
    No auth, 24-hour cache.

    Answers: "The kinds of stocks this filter picks — how have
    they done over the last N years vs Nifty?"

    Note: NOT a true rolling backtest (which would re-run the filter
    at each historical date). Survivorship bias present — disclosed to user.
    """
    if slug not in SCREENS:
        raise HTTPException(status_code=404, detail=f"Screen '{slug}' not found")

    rebalance_days = {"monthly": 21, "quarterly": 63, "yearly": 252}[rebalance]

    _cache_key = f"public:backtest:{slug}:{years}:{rebalance}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    # Get current screen constituents
    screen_data = await get_screen(slug, limit=50)
    stocks = screen_data.get("stocks", [])
    if not stocks:
        raise HTTPException(status_code=503, detail="Screen has no current constituents (cache warming)")

    tickers = [s["ticker"] for s in stocks]

    try:
        from backend.services.backtest_service import backtest_tickers
        result = backtest_tickers(
            tickers=tickers,
            years=years,
            rebalance_days=rebalance_days,
            include_benchmark=True,
        )
        if result.get("error"):
            raise HTTPException(status_code=503, detail=result["error"])

        result["screen_slug"] = slug
        result["screen_name"] = SCREENS[slug]["name"]
        result["constituents"] = [
            {"ticker": s["ticker"], "display_ticker": s["display_ticker"], "company_name": s["company_name"]}
            for s in stocks[:20]
        ]
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"backtest failed for {slug}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Backtest computation failed")


@router.get("/technicals/{ticker}")
async def get_technicals_endpoint(ticker: str, days: int = Query(default=365, ge=60, le=730)):
    """
    Technical indicators (SMA, RSI, MACD, Bollinger) from Parquet history.

    Factual reference data, not buy/sell signals.
    No auth, 1-hour cache.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:technicals:{clean}:{days}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from data_pipeline.nse_prices.db_integration import get_technical_indicators
        result = get_technical_indicators(clean, days=days)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No price history for {clean}")
        result["ticker"] = ticker
        cache.set(_cache_key, result, ttl=3600)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"technicals failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="Technical indicators unavailable")


@router.get("/risk-stats/{ticker}")
async def get_risk_stats_endpoint(ticker: str, years: int = Query(default=3, ge=1, le=10)):
    """
    Risk statistics from Parquet price history.
    No auth required. 24-hour cache.

    Returns volatility, max drawdown, beta vs Nifty, returns, etc.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:risk-stats:{clean}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from data_pipeline.nse_prices.db_integration import get_risk_stats
        result = get_risk_stats(clean, benchmark_ticker="NIFTYBEES", years=years)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No price history for {clean}")
        result["ticker"] = ticker
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"risk-stats failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="Risk stats unavailable")


@router.get("/top-tickers")
async def get_public_top_tickers(limit: int = 500):
    """Public list of active NSE tickers sorted by market_cap_cr DESC.

    Used by the cache-warmup workflow (which runs under a service
    token that isn't in the admin allow-list) so it doesn't need
    admin privileges to fetch the warm-set.

    Read-only, non-sensitive: just a ticker list.
    """
    limit = max(1, min(int(limit), 2000))
    _key = f"public:top-tickers:{limit}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=3600, swr=14400)
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            rows = sess.execute(_t(
                "SELECT s.ticker "
                "FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT :lim"
            ), {"lim": limit}).fetchall()
            tickers = [r[0] for r in rows if r and r[0]]
            out = {"count": len(tickers), "tickers": tickers}
            cache.set(_key, out, ttl=3600)
            return _cached_json(out, s_maxage=3600, swr=14400)
        finally:
            sess.close()
    except Exception as exc:
        logger.warning(f"public top-tickers failed: {exc}")
        return {"count": 0, "tickers": []}


@router.get("/near-52w-lows")
async def get_near_52w_lows(limit: int = 6, max_distance_pct: float = 15.0, min_score: int = 55):
    """Stocks trading close to their 52-week low with strong fundamentals.

    Factual filter — NOT a recommendation.
    - Loads the top 400 by market cap from market_metrics
    - Joins live_quotes for current price
    - Computes 52w low via Parquet (data_pipeline.nse_prices.db_integration)
    - Filters: within `max_distance_pct` of 52w low AND yieldiq_score >= min_score
    - Returns sorted by proximity to low, ascending

    Cached 1hr. Response capped at `limit`.
    """
    limit = max(1, min(int(limit), 20))
    max_distance_pct = max(0.0, min(float(max_distance_pct), 50.0))
    min_score = max(0, min(int(min_score), 100))
    _key = f"public:near-52w-lows:{limit}:{int(max_distance_pct)}:{min_score}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=300, swr=3600)

    out = {"count": 0, "stocks": [], "disclaimer": "Model estimate. Not investment advice."}
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        from data_pipeline.nse_prices.db_integration import get_52w_high_low

        sess = Session()
        try:
            # Top 400 by market cap that have an analysis_cache entry
            # (strong-fundamentals proxy — scored stocks only). Left-join
            # live_quotes for current price in one pass.
            rows = sess.execute(_t(
                "SELECT s.ticker, s.company_name, "
                "       lq.last_price AS price, "
                "       (ac.payload->>'yieldiq_score')::int AS score "
                "FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "LEFT JOIN live_quotes lq ON lq.ticker = s.ticker "
                "LEFT JOIN analysis_cache ac ON ac.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "  AND ac.ticker IS NOT NULL "
                "  AND lq.last_price IS NOT NULL "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT 400"
            )).fetchall()
        finally:
            sess.close()

        candidates: list[dict] = []
        for r in rows:
            try:
                ticker = r[0]
                company = r[1] or ticker
                price = float(r[2]) if r[2] else None
                score = int(r[3]) if r[3] is not None else 0
                if price is None or price <= 0 or score < min_score:
                    continue
                clean = ticker.replace(".NS", "").replace(".BO", "")
                high_low = get_52w_high_low(clean)
                if not high_low:
                    continue
                w52_high, w52_low = high_low
                if not w52_low or w52_low <= 0:
                    continue
                distance_pct = (price - w52_low) / w52_low * 100.0
                if distance_pct > max_distance_pct:
                    continue
                candidates.append({
                    "ticker": ticker,
                    "company_name": company,
                    "price": round(price, 2),
                    "w52_low": round(float(w52_low), 2),
                    "w52_high": round(float(w52_high), 2) if w52_high else None,
                    "distance_pct": round(distance_pct, 2),
                    "yieldiq_score": score,
                })
            except Exception:
                continue

        candidates.sort(key=lambda c: c["distance_pct"])
        out = {
            "count": min(len(candidates), limit),
            "stocks": candidates[:limit],
            "disclaimer": "Factual filter based on 52-week price history + model fundamental scores. Model estimate. Not investment advice.",
        }
        cache.set(_key, out, ttl=3600)
    except Exception as exc:
        logger.warning(f"near-52w-lows failed: {exc}")
    return _cached_json(out, s_maxage=300, swr=3600)


@router.get("/lowest-pe")
async def get_lowest_pe(limit: int = 6, min_score: int = 55, max_pe: float = 40.0):
    """Stocks with the lowest P/E ratio that still pass fundamental quality.

    Factual composition — NOT a recommendation. Reads market_metrics.pe_ratio
    and joins analysis_cache.yieldiq_score for the quality filter.
    """
    limit = max(1, min(int(limit), 20))
    min_score = max(0, min(int(min_score), 100))
    max_pe = max(1.0, min(float(max_pe), 200.0))
    _key = f"public:lowest-pe:{limit}:{min_score}:{int(max_pe)}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=300, swr=3600)

    out = {"count": 0, "stocks": [], "disclaimer": "Model estimate. Not investment advice."}
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            rows = sess.execute(_t(
                "SELECT s.ticker, s.company_name, "
                "       mm.pe_ratio, "
                "       (ac.payload->>'yieldiq_score')::int AS score "
                "FROM stocks s "
                "JOIN market_metrics mm ON mm.ticker = s.ticker "
                "JOIN analysis_cache ac ON ac.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "  AND mm.pe_ratio IS NOT NULL "
                "  AND mm.pe_ratio > 0 "
                "  AND mm.pe_ratio <= :max_pe "
                "  AND (ac.payload->>'yieldiq_score')::int >= :min_score "
                "ORDER BY mm.pe_ratio ASC "
                "LIMIT :lim"
            ), {"max_pe": max_pe, "min_score": min_score, "lim": limit}).fetchall()
        finally:
            sess.close()

        stocks = []
        for r in rows:
            try:
                stocks.append({
                    "ticker": r[0],
                    "company_name": r[1] or r[0],
                    "pe_ratio": round(float(r[2]), 2),
                    "yieldiq_score": int(r[3]),
                })
            except Exception:
                continue
        out = {
            "count": len(stocks),
            "stocks": stocks,
            "disclaimer": "Factual filter: lowest P/E stocks with YieldIQ score >= {0}. Model estimate. Not investment advice.".format(min_score),
        }
        cache.set(_key, out, ttl=3600)
    except Exception as exc:
        logger.warning(f"lowest-pe failed: {exc}")
    return _cached_json(out, s_maxage=300, swr=3600)
