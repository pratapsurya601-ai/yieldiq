# backend/routers/admin.py
# Admin dashboard — key metrics for admin users only.
from __future__ import annotations
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.admin")


def _sanitize_error(exc: Exception, context: str = "") -> str:
    """
    Return a user-safe error string that never exposes exception messages.

    Context: a Postgres error once echoed JWT_SECRET back to an unauth'd
    caller because the secret had been concatenated into DATABASE_URL and
    appeared in the resulting exception message. We must never send the
    raw `str(exc)` to clients — it can contain DB URLs with passwords,
    JWT secrets, API keys, or other env-var values.

    Full exception (incl. traceback) is logged server-side so we keep
    debuggability without leaking to users.
    """
    try:
        logger.error(
            "sanitized error (%s) in %s", type(exc).__name__, context or "debug",
            exc_info=True,
        )
    except Exception:
        pass
    return f"{type(exc).__name__} (details suppressed; see server logs)"


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Admin allow-list + require_admin dependency. Defined BEFORE
# ``debug_router`` so the debug endpoints below can attach
# ``Depends(require_admin)`` at decoration time. Previously these were
# at the bottom of the file and the debug routes were unauthenticated —
# which leaked DCF traces, fv-history stats, and price-pipeline
# diagnostics to anyone who could guess the URL.
ADMIN_EMAILS = {"pratapsurya601@gmail.com", "suryasbss601@gmail.com"}


def require_admin(user: dict = Depends(get_current_user)):
    """Dependency that requires admin email."""
    if user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# admin-only debug router — read-only DCF traces, fv-history stats and
# price-pipeline diagnostics. Gated by require_admin (see above) so
# production blow-ups can be diagnosed without leaking internals to
# unauthenticated callers.
debug_router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@debug_router.get("/dcf-trace")
async def list_dcf_traces(limit: int = 50, user: dict = Depends(require_admin)):
    """Return most recent DCF traces keyed by ticker (read-only)."""
    from screener.dcf_engine import DCF_TRACES
    items = list(DCF_TRACES.items())[-limit:]
    return {"count": len(items), "traces": dict(items)}


@debug_router.get("/dcf-trace/{ticker}")
async def get_dcf_trace(ticker: str, user: dict = Depends(require_admin)):
    """Return the most recent DCF trace for a single ticker."""
    from screener.dcf_engine import DCF_TRACES
    t = ticker.upper().strip()
    if not t.endswith(".NS") and not t.endswith(".BO"):
        t = f"{t}.NS"
    trace = DCF_TRACES.get(t)
    if not trace:
        raise HTTPException(status_code=404, detail=f"No DCF trace for {t} yet — trigger an analysis first")
    return trace


@debug_router.get("/fv-history-stats")
async def fv_history_stats(user: dict = Depends(require_admin)):
    """
    Row counts per ticker in fair_value_history — monitors nightly
    collection accumulation. When min_days_covered crosses ~365, we
    have enough data for a real out-of-sample backtest.
    """
    try:
        from data_pipeline.db import Session as _Sess
        from data_pipeline.models import FairValueHistory
        from sqlalchemy import func
        db = _Sess()
        try:
            q = (
                db.query(
                    FairValueHistory.ticker,
                    func.count(FairValueHistory.id).label("count"),
                    func.min(FairValueHistory.date).label("first"),
                    func.max(FairValueHistory.date).label("last"),
                )
                .group_by(FairValueHistory.ticker)
                .order_by(func.count(FairValueHistory.id).desc())
                .all()
            )
            per_ticker = [
                {
                    "ticker": r.ticker,
                    "days": r.count,
                    "first": r.first.isoformat() if r.first else None,
                    "last": r.last.isoformat() if r.last else None,
                }
                for r in q
            ]
            # Overall rollup
            total_rows = sum(x["days"] for x in per_ticker)
            tickers_tracked = len(per_ticker)
            days_covered = [x["days"] for x in per_ticker]
            return {
                "total_rows": total_rows,
                "tickers_tracked": tickers_tracked,
                "max_days_any_ticker": max(days_covered) if days_covered else 0,
                "min_days_any_ticker": min(days_covered) if days_covered else 0,
                "median_days": sorted(days_covered)[len(days_covered)//2] if days_covered else 0,
                "backtest_ready_tickers": sum(1 for d in days_covered if d >= 365),
                "per_ticker": per_ticker[:100],  # cap to avoid huge payload
            }
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fv-history-stats failed: {_sanitize_error(e, 'fv-history-stats')}")


@debug_router.get("/universe-report")
async def get_universe_report(user: dict = Depends(require_admin)):
    """
    Returns the latest universe-scan report if present.

    The weekly GitHub Actions workflow produces this file and uploads
    it as an artifact. To make the report queryable via API, commit
    the latest good report to the repo at `reports/universe_scan_latest.json`
    or fetch via GitHub's artifact API. For now: returns whatever is
    at that path in the deployed bundle.
    """
    from pathlib import Path
    candidates = [
        Path(__file__).resolve().parents[2] / "reports" / "universe_scan_latest.json",
        Path(__file__).resolve().parents[2] / "universe_scan_report.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                import json as _json
                return _json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Report unreadable: {_sanitize_error(e, 'universe-report')}")
    raise HTTPException(
        status_code=404,
        detail="No universe scan report found. Run scripts/full_universe_scan.py or trigger the weekly workflow.",
    )


@debug_router.get("/price-diag/{ticker}")
async def price_diagnostic(ticker: str, user: dict = Depends(require_admin)):
    """
    Returns what every layer of the price pipeline sees for a given
    ticker — so we can tell whether bad prices are coming from yfinance,
    the parquet, or the cache.
    """
    import os
    from pathlib import Path
    t = ticker.upper().replace(".NS", "").replace(".BO", "").strip()
    out: dict = {"ticker": t}

    # 1. yfinance live quote
    try:
        import yfinance as yf
        fi = yf.Ticker(f"{t}.NS").fast_info
        out["yfinance_live"] = {
            "last_price": getattr(fi, "last_price", None),
            "regular_market_price": getattr(fi, "regular_market_price", None),
            "previous_close": getattr(fi, "previous_close", None),
        }
    except Exception as e:
        out["yfinance_live"] = {"error": _sanitize_error(e, 'price-diag.yfinance')}

    # 2. Parquet file
    try:
        from data_pipeline.nse_prices.db_integration import _parquet_path
        import duckdb
        p = _parquet_path(t)
        out["parquet_path"] = str(p)
        out["parquet_exists"] = p.exists()
        if p.exists():
            out["parquet_mtime"] = p.stat().st_mtime
            out["parquet_size_kb"] = p.stat().st_size // 1024
            rows = duckdb.connect().execute(
                f"SELECT date, close FROM read_parquet('{p}') ORDER BY date DESC LIMIT 3"
            ).fetchall()
            out["parquet_last_rows"] = [
                {"date": str(r[0]), "close": float(r[1])} for r in rows
            ]
    except Exception as e:
        out["parquet_error"] = _sanitize_error(e, 'price-diag.parquet')

    # 3. get_latest_price (what the app actually reads)
    try:
        from data_pipeline.nse_prices.db_integration import get_latest_price
        out["app_reads"] = get_latest_price(t)
    except Exception as e:
        out["app_reads_error"] = _sanitize_error(e, 'price-diag.app_reads')

    # 4. Auto-refresh status
    try:
        from backend.main import _auto_refresh_parquets_if_needed
        out["auto_refresh_done"] = getattr(_auto_refresh_parquets_if_needed, "_done", False)
    except Exception:
        out["auto_refresh_done"] = "unknown"

    # 5. Env / working dir
    out["cwd"] = os.getcwd()
    return out


# ADMIN_EMAILS + require_admin are defined above (before debug_router)
# so the /api/v1/debug/* routes can use Depends(require_admin) at
# decoration time. Do not redefine here.


@router.get("/coverage")
async def get_data_coverage(user: dict = Depends(require_admin)):
    """Data coverage snapshot across all YieldIQ tables.

    Answers questions like:
      - How many tickers in the stocks master?
      - How many have fundamentals in `company_financials` (new) vs
        `financials` (legacy)?
      - How many have analysis_cache entries (warmed)?
      - How many have fair_value_history (user-triggered analyses)?
    """
    out = {
        "stocks_active": None,
        "financials_distinct": None,
        "company_financials_distinct": None,
        "analysis_cache": None,
        "fair_value_history_distinct": None,
        "live_quotes": None,
        "endpoint_cache": None,
        "fresh_company_financials_7d": None,
        "errors": [],
    }

    def _scalar(session, sql: str):
        try:
            from sqlalchemy import text as _t
            row = session.execute(_t(sql)).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except Exception as exc:
            out["errors"].append(f"{sql[:50]}… {type(exc).__name__}: {str(exc)[:80]}")
            return None

    try:
        from data_pipeline.db import Session
        sess = Session()
        try:
            out["stocks_active"] = _scalar(
                sess,
                "SELECT COUNT(*) FROM stocks WHERE is_active = TRUE",
            )
            out["financials_distinct"] = _scalar(
                sess,
                "SELECT COUNT(DISTINCT ticker) FROM financials",
            )
            out["company_financials_distinct"] = _scalar(
                sess,
                "SELECT COUNT(DISTINCT ticker_nse) FROM company_financials",
            )
            out["fresh_company_financials_7d"] = _scalar(
                sess,
                "SELECT COUNT(DISTINCT ticker_nse) FROM company_financials "
                "WHERE period_end_date >= current_date - interval '400 days'",
            )
            out["analysis_cache"] = _scalar(
                sess,
                "SELECT COUNT(*) FROM analysis_cache",
            )
            out["fair_value_history_distinct"] = _scalar(
                sess,
                "SELECT COUNT(DISTINCT ticker) FROM fair_value_history",
            )
            out["live_quotes"] = _scalar(sess, "SELECT COUNT(*) FROM live_quotes")
            out["endpoint_cache"] = _scalar(
                sess, "SELECT COUNT(*) FROM endpoint_cache WHERE expires_at > now()"
            )
        finally:
            sess.close()
    except Exception as exc:
        out["errors"].append(_sanitize_error(exc, "coverage db"))

    return out


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


@router.get("/top-tickers")
async def get_top_tickers(
    limit: int = 500,
    only_gap: bool = False,
    user: dict = Depends(require_admin),
):
    """Return top-N NSE tickers sorted by market_cap_cr DESC.

    Used by the cache_warmup_top500 cron to keep the warmest 500
    stocks hot in analysis_cache so users get <1s response.

    - limit: how many to return (clamped to 1..2000)
    - only_gap: if True, return only tickers NOT yet in company_financials
      (useful for targeted XBRL backfill of the coverage gap)
    """
    limit = max(1, min(int(limit), 2000))
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            # DISTINCT ON dedupes cross-listing rows in market_metrics.
            # Same ticker on NSE+BSE would otherwise be counted twice.
            # See design note in backend/routers/screener.py.
            if only_gap:
                # Tickers in stocks master but missing from company_financials.
                sql = _t(
                    # PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
                    # Prevents 2026-04-30 yfinance-NULL incident class.
                    "WITH mm_dedup AS ("
                    "  SELECT DISTINCT ON (ticker) ticker, market_cap_cr "
                    "  FROM market_metrics "
                    "  WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0 "
                    "  ORDER BY ticker, COALESCE(data_quality_rank, 50) ASC, trade_date DESC"
                    ") "
                    "SELECT s.ticker "
                    "FROM stocks s "
                    "LEFT JOIN company_financials cf ON cf.ticker_nse = s.ticker "
                    "LEFT JOIN mm_dedup mm ON mm.ticker = s.ticker "
                    "WHERE s.is_active = TRUE AND cf.ticker_nse IS NULL "
                    "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                    "LIMIT :lim"
                )
            else:
                sql = _t(
                    # PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
                    # Prevents 2026-04-30 yfinance-NULL incident class.
                    "WITH mm_dedup AS ("
                    "  SELECT DISTINCT ON (ticker) ticker, market_cap_cr "
                    "  FROM market_metrics "
                    "  WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0 "
                    "  ORDER BY ticker, COALESCE(data_quality_rank, 50) ASC, trade_date DESC"
                    ") "
                    "SELECT s.ticker "
                    "FROM stocks s "
                    "LEFT JOIN mm_dedup mm ON mm.ticker = s.ticker "
                    "WHERE s.is_active = TRUE "
                    "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                    "LIMIT :lim"
                )
            rows = sess.execute(sql, {"lim": limit}).fetchall()
            tickers = [r[0] for r in rows if r and r[0]]
            return {"count": len(tickers), "tickers": tickers, "only_gap": only_gap}
        finally:
            sess.close()
    except Exception as exc:
        return {"count": 0, "tickers": [], "error": _sanitize_error(exc, "top-tickers")}


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


# Module-level state for long-running pipeline jobs. Simple in-memory
# status tracker -- resets on Railway boot but that's fine for a
# one-off admin operation.
_PIPELINE_JOBS: dict[str, dict] = {}


@router.post("/pipeline/refresh-fundamentals")
async def run_refresh_fundamentals(user: dict = Depends(require_admin)):
    """
    Kick off a full batch_fetch_fundamentals against NSE_UNIVERSE in a
    background daemon thread. Populates the `financials` table with
    revenue / FCF / margins / etc. for every tracked ticker, so local
    DB path works for all of them (speeds cold analyses from 10-25s
    down to ~200ms).

    Returns immediately with a job_id. Check progress via
    GET /api/v1/admin/pipeline/status.

    Expected runtime: 60-120 min (1-2 req/s to yfinance for ~100 tickers
    across multiple statements each).
    """
    import threading, uuid
    from datetime import datetime

    job_id = f"refresh-fundamentals-{uuid.uuid4().hex[:8]}"
    _PIPELINE_JOBS[job_id] = {
        "job_id": job_id,
        "status": "starting",
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "ok": 0,
        "failed": 0,
        "total": 0,
        "triggered_by": user.get("email"),
        "error": None,
    }

    def _run():
        try:
            from data_pipeline.db import Session as _Sess
            from data_pipeline.pipeline import NSE_UNIVERSE
            from data_pipeline.sources.yfinance_supplement import (
                batch_fetch_fundamentals,
            )
            _PIPELINE_JOBS[job_id]["total"] = len(NSE_UNIVERSE)
            _PIPELINE_JOBS[job_id]["status"] = "running"

            _db = _Sess()
            try:
                ok, failed = batch_fetch_fundamentals(NSE_UNIVERSE, _db)
                _PIPELINE_JOBS[job_id]["ok"] = ok
                _PIPELINE_JOBS[job_id]["failed"] = failed
                _PIPELINE_JOBS[job_id]["status"] = "done"
            finally:
                _db.close()
        except Exception as e:
            _PIPELINE_JOBS[job_id]["status"] = "error"
            _PIPELINE_JOBS[job_id]["error"] = _sanitize_error(e, "refresh-fundamentals")
        finally:
            from datetime import datetime as _dt
            _PIPELINE_JOBS[job_id]["finished_at"] = _dt.utcnow().isoformat()

    threading.Thread(target=_run, daemon=True, name=job_id).start()
    return _PIPELINE_JOBS[job_id]


@router.get("/pipeline/status")
async def pipeline_status(user: dict = Depends(require_admin)):
    """
    Return status of all pipeline jobs kicked off in this Railway
    container. Useful for monitoring the refresh-fundamentals job.
    """
    return {"jobs": list(_PIPELINE_JOBS.values())}


@router.post("/db/run-currency-migration")
async def run_currency_migration(user: dict = Depends(require_admin)):
    """
    ONE-SHOT migration: adds `currency` column to financials + tags
    USD-reporting tickers. Idempotent (IF NOT EXISTS guards). This
    exists because PG Studio is read-only and the Aiven CLI redacts
    passwords — admin triggers this via POST instead.

    Safe to run multiple times. Safe to call after the migration has
    already been applied (UPDATE will just re-mark the same rows).

    Returns before/after counts so we can see it worked.
    """
    try:
        from data_pipeline.db import Session as _Sess
        from sqlalchemy import text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"import failed: {_sanitize_error(e, 'run-currency-migration')}")

    db = _Sess()
    result: dict = {"steps": [], "triggered_by": user.get("email")}
    try:
        # 1. Add column (idempotent)
        db.execute(text(
            "ALTER TABLE financials "
            "ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'INR'"
        ))
        result["steps"].append("ALTER TABLE: ok")

        # 2. Tag USD reporters
        tickers = (
            "'INFY','WIPRO','HCLTECH','TECHM','MPHASIS','HEXAWARE','LTIM',"
            "'LTIMINDTR','PERSISTENT','COFORGE','KPITTECH','TATAELXSI','CYIENT',"
            "'ZENSAR','MASTEK','NIIT','OFSS','DIVISLAB','LAURUSLABS'"
        )
        res = db.execute(text(
            f"UPDATE financials SET currency='USD' WHERE ticker IN ({tickers})"
        ))
        result["steps"].append(f"UPDATE: {res.rowcount} rows tagged USD")

        # 3. Index
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_financials_currency "
            "ON financials(currency)"
        ))
        result["steps"].append("CREATE INDEX: ok")

        db.commit()

        # Verify
        verify = db.execute(text(
            "SELECT currency, COUNT(*) AS n FROM financials "
            "GROUP BY currency ORDER BY n DESC"
        )).fetchall()
        result["verify"] = [{"currency": r[0], "rows": r[1]} for r in verify]
        result["status"] = "ok"
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"migration failed: {_sanitize_error(e, 'run-currency-migration')}")
    finally:
        db.close()


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


# ─────────────────────────────────────────────────────────────────
# Activation telemetry — per-user page-view summary.
#
# Motivation (2026-05-16): 5/5 organic signups in 16 days produced
# 0 watchlist/portfolio writes. Without page-view telemetry we can't
# tell "signed up, viewed nothing" from "signed up, viewed 50 stocks
# but never clicked add". This endpoint answers the activation
# question: did user X actually look at any analysis page?
#
# Data source: ``user_page_views`` (30-day retention). Schema in
# data_pipeline/migrations/029_user_page_views.sql.
# ─────────────────────────────────────────────────────────────────
@router.get("/user-activity/{email}")
async def get_user_activity(
    email: str,
    days: int = 30,
    user: dict = Depends(require_admin),
):
    """Admin-only: return a user's last-N-days of page-view activity.

    Returns ``{user_email, days, total_views, by_page_kind,
    by_ticker, first_view, last_view, views[]}``. ``views`` is capped
    at 1000 newest rows. Anonymous traffic is never recorded, so a
    zero total_views answer means "signed-in user never opened any
    instrumented page in the window".
    """
    from backend.services import page_view_service as _pvs
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    try:
        days_i = max(1, min(int(days or 30), 30))
    except (TypeError, ValueError):
        days_i = 30
    return _pvs.activity_summary(email, days=days_i)


# ─────────────────────────────────────────────────────────────────
# Benchmark reconciliation — Layer A safety net (PR #335 follow-on).
#
# Surfaces the join of analysis_cache.fair_value vs
# latest_consensus_per_ticker.target_median. Operators check this
# daily to catch sector-engine regressions before users complain
# (POWERGRID @ ₹59 vs market @ ₹305 was the motivating incident).
#
# Design: docs/design/benchmark-reconciliation-framework.md §6.1.
# Service:   backend/services/benchmark_reconciliation_service.py.
#
# Auth: require_admin (same JWT allow-list as the other admin routes).
# Never exposes the consensus number to non-admin callers — the
# user-facing caveat path lives in the analysis serializer and uses
# the abs-delta integer only.
# ─────────────────────────────────────────────────────────────────
@router.get("/benchmark-outliers")
async def get_benchmark_outliers(
    threshold: float = 0.30,
    min_analysts: int = 3,
    direction: str = "both",
    limit: int = 50,
    user: dict = Depends(require_admin),
):
    """Sorted list of tickers whose model FV diverges from analyst
    consensus by more than ``threshold`` (fraction, not percent).

    Query params:
      - ``threshold``     : default 0.30  (30%; matches design D0 setting)
      - ``min_analysts``  : default 3     (low-signal floor)
      - ``direction``     : "both" | "over" | "under"
      - ``limit``         : default 50, max 500

    Returns ``{generated_at, threshold_pct, count, rows[]}`` sorted by
    ``|delta_pct|`` desc. Each row carries our_fv, consensus_fv,
    delta_pct, direction, analyst_count, source, fetched_at — see
    OutlierRow in the service module. Admin-only; consensus values
    never appear in non-admin responses.
    """
    from datetime import datetime, timezone
    from backend.services import benchmark_reconciliation_service as brs

    # Defensive clamping. The endpoint is admin-only so we don't worry
    # about adversarial input, but we still bound the values to keep
    # operator typos from producing a 50-page response.
    try:
        threshold_f = max(0.01, min(float(threshold), 5.0))
    except (TypeError, ValueError):
        threshold_f = 0.30
    try:
        min_an = max(1, min(int(min_analysts), 50))
    except (TypeError, ValueError):
        min_an = 3
    try:
        limit_i = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit_i = 50
    direction_s = (direction or "both").lower().strip()
    if direction_s not in ("both", "over", "under"):
        direction_s = "both"

    try:
        rows = brs.get_outliers(
            threshold_pct=threshold_f,
            min_analysts=min_an,
            direction=direction_s,
            limit=limit_i,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"benchmark-outliers failed: {_sanitize_error(e, 'benchmark-outliers')}",
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold_pct": threshold_f,
        "min_analysts": min_an,
        "direction": direction_s,
        "count": len(rows),
        "rows": [r.to_dict() for r in rows],
    }


# ── Sentry wiring smoke test ─────────────────────────────────
# Hit this after a deploy to confirm SENTRY_DSN is wired and the
# event lands in the Sentry dashboard. Auth-gated so random callers
# can't fill our event quota with synthetic 500s.
class _SentryWiringTestError(RuntimeError):
    """Synthetic exception raised by /admin/sentry-test only.

    Distinct type so the dashboard filter `error.type:_SentryWiringTestError`
    isolates wiring smoke tests from real prod errors.
    """


@router.get("/sentry-test")
async def sentry_test(user: dict = Depends(require_admin)):
    """Raise a synthetic exception to verify Sentry capture works.

    Returns 500 by design — the exception bubbles to the FastAPI integration
    which captures it. If the wiring is correct you'll see a
    `_SentryWiringTestError` event in the Sentry dashboard within ~10s. If
    Sentry is unconfigured (no DSN), the response is still 500 but no event
    is shipped — behaviour is identical for the caller either way.
    """
    try:
        import sentry_sdk as _sentry
        _sentry.set_tag("smoke_test", "sentry_wiring")
        _sentry.set_tag("triggered_by", user.get("email", "unknown"))
    except Exception:
        pass
    raise _SentryWiringTestError(
        "Synthetic exception from /admin/sentry-test — wiring smoke test"
    )
