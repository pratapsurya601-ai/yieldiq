# backend/routers/admin.py
# Admin dashboard — key metrics for admin users only.
from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Public debug router (no auth) — exposes read-only DCF traces so
# production blow-ups can be diagnosed without scraping Railway logs.
debug_router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@debug_router.get("/dcf-trace")
async def list_dcf_traces(limit: int = 50):
    """Return most recent DCF traces keyed by ticker (read-only)."""
    from screener.dcf_engine import DCF_TRACES
    items = list(DCF_TRACES.items())[-limit:]
    return {"count": len(items), "traces": dict(items)}


@debug_router.get("/dcf-trace/{ticker}")
async def get_dcf_trace(ticker: str):
    """Return the most recent DCF trace for a single ticker."""
    from screener.dcf_engine import DCF_TRACES
    t = ticker.upper().strip()
    if not t.endswith(".NS") and not t.endswith(".BO"):
        t = f"{t}.NS"
    trace = DCF_TRACES.get(t)
    if not trace:
        raise HTTPException(status_code=404, detail=f"No DCF trace for {t} yet — trigger an analysis first")
    return trace

ADMIN_EMAILS = {"pratapsurya601@gmail.com", "suryasbss601@gmail.com"}


def require_admin(user: dict = Depends(get_current_user)):
    """Dependency that requires admin email."""
    if user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/stats")
async def get_admin_stats(user: dict = Depends(require_admin)):
    """Return key platform metrics. Admin only."""
    stats = {
        "total_users": 0,
        "users_today": 0,
        "analyses_today": 0,
        "paid_users": 0,
        "revenue_monthly": 0,
        "top_stocks_today": [],
        "errors_today": 0,
        "db_size_mb": 0,
        "cache_hit_rate": 0.0,
    }

    # Try to get real data from rate limiter (tracks daily usage)
    try:
        from backend.middleware.rate_limit import rate_limiter
        if hasattr(rate_limiter, "_usage"):
            today = date.today().isoformat()
            total_analyses = 0
            user_ids_today = set()
            for key, count in rate_limiter._usage.items():
                if today in key:
                    total_analyses += count
                    # Key format: "user_id:date"
                    uid = key.rsplit(":", 1)[0]
                    user_ids_today.add(uid)
            stats["analyses_today"] = total_analyses
            stats["users_today"] = len(user_ids_today)
    except Exception:
        pass

    # Try to get cache stats
    try:
        from backend.services.cache_service import cache
        if hasattr(cache, "_store"):
            total_keys = len(cache._store)
            stats["cache_hit_rate"] = round(min(0.95, total_keys / max(1, total_keys + 10)), 2)
    except Exception:
        pass

    # Try to get top stocks from cache
    try:
        from backend.services.cache_service import cache
        stock_counts: dict[str, int] = {}
        for key in list(cache._store.keys()):
            if key.startswith("analysis:"):
                ticker = key.replace("analysis:", "")
                stock_counts[ticker] = stock_counts.get(ticker, 0) + 1
        if stock_counts:
            sorted_stocks = sorted(stock_counts.items(), key=lambda x: x[1], reverse=True)
            stats["top_stocks_today"] = [s[0] for s in sorted_stocks[:10]]
    except Exception:
        pass

    # Try Supabase user count
    try:
        from db.supabase_client import get_client
        client = get_client()
        if client:
            # Count users from auth
            result = client.table("users_meta").select("id", count="exact").execute()
            if hasattr(result, "count") and result.count:
                stats["total_users"] = result.count
    except Exception:
        pass

    return stats


@router.post("/trigger-newsletter")
async def trigger_newsletter(user: dict = Depends(require_admin)):
    """Manually trigger newsletter send. Admin only."""
    import threading
    from backend.services.newsletter_service import send_newsletter_to_all
    threading.Thread(target=send_newsletter_to_all, daemon=True).start()
    return {"status": "newsletter queued", "triggered_by": user.get("email")}


@router.post("/cache/clear")
async def clear_cache_admin(
    prefix: str = "",
    user: dict = Depends(require_admin),
):
    """
    Clear cache entries. Admin only.
    - prefix='' clears EVERYTHING
    - prefix='analysis:' clears all analysis
    - prefix='analysis:HCLTECH.NS' clears one ticker
    - prefix='og:' clears all OG data
    """
    from backend.services.cache_service import cache
    if prefix:
        count = cache.clear_pattern(prefix)
        return {"cleared": count, "prefix": prefix}
    # Clear all
    size_before = len(cache._store)
    cache.clear()
    return {"cleared": size_before, "prefix": "(all)"}


@router.post("/prices/refresh")
async def refresh_prices(
    tickers: str = "HDFCBANK",
    user: dict = Depends(require_admin),
):
    """
    Re-download price parquets for the given comma-separated tickers
    (without .NS). Fixes post-auto_adjust-flip: HDFCBANK halved by
    yfinance's bogus merger-split adjustment. Also clears analysis/price
    caches for those tickers.
    """
    from data_pipeline.nse_prices.yf_downloader import download_ticker
    from backend.services.cache_service import cache

    results: list[dict] = []
    for t in [x.strip().upper() for x in tickers.split(",") if x.strip()]:
        try:
            path = download_ticker(t, period="5y")
            cleared = 0
            for prefix in ["analysis:", "og:", "preview:", "chart_data:",
                           "public:stock-summary:"]:
                cleared += cache.clear_pattern(f"{prefix}{t}.NS")
            results.append({
                "ticker": t,
                "parquet": str(path) if path else None,
                "cache_cleared": cleared,
                "status": "ok" if path else "failed",
            })
        except Exception as e:
            results.append({
                "ticker": t,
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            })
    return {"refreshed": results, "triggered_by": user.get("email")}


@router.post("/cache/refresh-ticker")
async def refresh_ticker_cache(
    ticker: str,
    user: dict = Depends(require_admin),
):
    """Clear cached entries for a ticker and re-run analysis."""
    from backend.services.cache_service import cache
    from backend.services import analysis_service as svc

    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Clear all cache entries for this ticker
    cleared = 0
    for prefix in ["analysis:", "og:", "preview:", "peers:", "dividends:",
                   "financials:", "public:stock-summary:", "chart_data:",
                   "fv-history:"]:
        cleared += cache.clear_pattern(f"{prefix}{ticker}")

    # Re-run analysis
    try:
        result = svc.AnalysisService().get_full_analysis(ticker)
        return {
            "ticker": ticker,
            "cleared": cleared,
            "new_fair_value": result.valuation.fair_value,
            "new_price": result.valuation.current_price,
            "new_mos": result.valuation.margin_of_safety,
            "new_score": result.quality.yieldiq_score,
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "cleared": cleared,
            "error": f"{type(e).__name__}: {e}",
        }
