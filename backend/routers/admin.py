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
# Insurance Embedded Value (EV) + Value of New Business (VNB) entry.
#
# Operator-curated quarterly workflow that activates the Appraisal
# Value engine in backend/services/insurance_appraisal_service.py.
# See docs/design/insurance-dcf-fix.md §3 Approach A and §8.4.
#
# Per-ticker schema (insurance_appraisal_inputs, migration 046):
#   ticker, period_end, embedded_value_cr, value_new_business_cr,
#   vnb_margin_pct, ev_growth_yoy_pct, source_url, entered_by,
#   entered_at, notes.
#
# Validation:
#   - ticker must be in INSURANCE_TICKERS (life-insurer subset; LICI
#     and ICICIPRULI were added 2026-05-18 alongside this endpoint).
#   - embedded_value_cr must be > 0.
#   - period_end must not be in the future.
# ─────────────────────────────────────────────────────────────────
@router.get("/insurance-inputs")
async def list_insurance_inputs(user: dict = Depends(require_admin)):
    """Return every row in ``insurance_appraisal_inputs`` sorted by
    ticker, period_end DESC. Empty list when the table has no rows
    yet (expected on day-zero of this feature)."""
    try:
        from data_pipeline.db import Session as _Sess
        from sqlalchemy import text as _t
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"db import failed: {_sanitize_error(exc, 'insurance-inputs.import')}",
        )
    if _Sess is None:
        return {"rows": [], "warning": "no database session configured"}
    db = _Sess()
    try:
        try:
            rows = db.execute(
                _t(
                    "SELECT ticker, period_end, embedded_value_cr, "
                    "value_new_business_cr, vnb_margin_pct, "
                    "ev_growth_yoy_pct, source_url, entered_by, "
                    "entered_at, notes "
                    "FROM insurance_appraisal_inputs "
                    "ORDER BY ticker ASC, period_end DESC"
                )
            ).fetchall()
        except Exception as exc:
            # Migration not applied → return empty list with a hint
            # rather than 500, so the admin page is usable pre-migrate.
            logger.warning(
                "insurance_appraisal_inputs SELECT failed: %s: %s",
                type(exc).__name__, exc,
            )
            return {
                "rows": [],
                "warning": (
                    "insurance_appraisal_inputs table not present — "
                    "apply migration 046_insurance_appraisal_inputs.sql"
                ),
            }
        out = []
        for r in rows:
            out.append({
                "ticker": r[0],
                "period_end": r[1].isoformat() if r[1] else None,
                "embedded_value_cr": float(r[2]) if r[2] is not None else None,
                "value_new_business_cr": float(r[3]) if r[3] is not None else None,
                "vnb_margin_pct": float(r[4]) if r[4] is not None else None,
                "ev_growth_yoy_pct": float(r[5]) if r[5] is not None else None,
                "source_url": r[6],
                "entered_by": r[7],
                "entered_at": r[8].isoformat() if r[8] else None,
                "notes": r[9],
            })
        return {"rows": out, "count": len(out)}
    finally:
        db.close()


@router.post("/insurance-inputs")
async def upsert_insurance_input(
    payload: dict,
    user: dict = Depends(require_admin),
):
    """Upsert one row keyed on (ticker, period_end).

    Expected JSON body::

      {
        "ticker": "HDFCLIFE",                   # required
        "period_end": "2026-03-31",             # required, ISO date, not future
        "embedded_value_cr": 51000,             # required, > 0
        "value_new_business_cr": 3900,          # optional, > 0
        "vnb_margin_pct": 26.5,                 # optional
        "ev_growth_yoy_pct": 17.0,              # optional
        "source_url": "https://...investor.pdf", # optional
        "notes": "FY26 Q4 EV report"            # optional
      }
    """
    # Lazy import the insurance ticker allow-list so a circular-import
    # in this module never breaks the wider admin router.
    from backend.services.analysis.constants import _INSURANCE_TICKERS
    from datetime import date as _date

    ticker = (payload.get("ticker") or "").strip().upper()
    # Accept .NS/.BO suffixes but normalise to bare symbol.
    ticker = ticker.replace(".NS", "").replace(".BO", "")
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    if ticker not in _INSURANCE_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ticker {ticker!r} is not in INSURANCE_TICKERS — "
                f"valid: {sorted(_INSURANCE_TICKERS)}"
            ),
        )

    period_end_raw = payload.get("period_end")
    if not period_end_raw:
        raise HTTPException(status_code=400, detail="period_end is required (ISO date)")
    try:
        period_end = _date.fromisoformat(str(period_end_raw)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="period_end must be ISO YYYY-MM-DD")
    if period_end > _date.today():
        raise HTTPException(status_code=400, detail="period_end cannot be in the future")

    try:
        ev_cr = float(payload.get("embedded_value_cr"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="embedded_value_cr must be numeric")
    if ev_cr <= 0:
        raise HTTPException(status_code=400, detail="embedded_value_cr must be > 0")

    def _opt_float(key):
        v = payload.get(key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"{key} must be numeric or null",
            )

    vnb_cr   = _opt_float("value_new_business_cr")
    vnb_marg = _opt_float("vnb_margin_pct")
    ev_grow  = _opt_float("ev_growth_yoy_pct")
    src_url  = payload.get("source_url") or None
    notes    = payload.get("notes") or None

    try:
        from data_pipeline.db import Session as _Sess
        from sqlalchemy import text as _t
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"db import failed: {_sanitize_error(exc, 'insurance-inputs.import')}",
        )
    if _Sess is None:
        raise HTTPException(status_code=500, detail="no database session configured")
    db = _Sess()
    try:
        db.execute(
            _t(
                "INSERT INTO insurance_appraisal_inputs "
                "(ticker, period_end, embedded_value_cr, value_new_business_cr, "
                " vnb_margin_pct, ev_growth_yoy_pct, source_url, entered_by, "
                " entered_at, notes) "
                "VALUES (:t, :p, :ev, :vnb, :margin, :grow, :src, :who, NOW(), :n) "
                "ON CONFLICT (ticker, period_end) DO UPDATE SET "
                "  embedded_value_cr     = EXCLUDED.embedded_value_cr, "
                "  value_new_business_cr = EXCLUDED.value_new_business_cr, "
                "  vnb_margin_pct        = EXCLUDED.vnb_margin_pct, "
                "  ev_growth_yoy_pct     = EXCLUDED.ev_growth_yoy_pct, "
                "  source_url            = EXCLUDED.source_url, "
                "  entered_by            = EXCLUDED.entered_by, "
                "  entered_at            = NOW(), "
                "  notes                 = EXCLUDED.notes"
            ),
            {
                "t": ticker, "p": period_end, "ev": ev_cr,
                "vnb": vnb_cr, "margin": vnb_marg, "grow": ev_grow,
                "src": src_url, "who": user.get("email"), "n": notes,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"upsert failed: {_sanitize_error(exc, 'insurance-inputs.upsert')}",
        )
    finally:
        db.close()

    return {
        "status": "ok",
        "ticker": ticker,
        "period_end": period_end.isoformat(),
        "entered_by": user.get("email"),
    }


@router.delete("/insurance-inputs")
async def delete_insurance_input(
    ticker: str,
    period_end: str,
    user: dict = Depends(require_admin),
):
    """Delete the (ticker, period_end) row. 404 when no such row."""
    from datetime import date as _date
    t = (ticker or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not t:
        raise HTTPException(status_code=400, detail="ticker is required")
    try:
        p = _date.fromisoformat(str(period_end)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="period_end must be ISO YYYY-MM-DD")

    try:
        from data_pipeline.db import Session as _Sess
        from sqlalchemy import text as _t
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"db import failed: {_sanitize_error(exc, 'insurance-inputs.import')}",
        )
    if _Sess is None:
        raise HTTPException(status_code=500, detail="no database session configured")
    db = _Sess()
    try:
        res = db.execute(
            _t(
                "DELETE FROM insurance_appraisal_inputs "
                "WHERE ticker = :t AND period_end = :p"
            ),
            {"t": t, "p": p},
        )
        db.commit()
        if res.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail=f"no row for ticker={t} period_end={p.isoformat()}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"delete failed: {_sanitize_error(exc, 'insurance-inputs.delete')}",
        )
    finally:
        db.close()

    return {"status": "deleted", "ticker": t, "period_end": p.isoformat()}

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
    adaptive: bool = False,
    user: dict = Depends(require_admin),
):
    """Sorted list of tickers whose model FV diverges from analyst
    consensus by more than ``threshold`` (fraction, not percent).

    Query params:
      - ``threshold``     : default 0.30  (30%; matches design D0 setting)
      - ``min_analysts``  : default 3     (low-signal floor)
      - ``direction``     : "both" | "over" | "under"
      - ``limit``         : default 50, max 500
      - ``adaptive``      : default False. When true, ``threshold`` is
                            multiplied by a per-analyst-count factor:
                            ≥20 analysts → ×0.67 (e.g. 30% → 20%),
                            10-19 → ×1.0 (no change),
                            5-9 → ×1.33 (e.g. 30% → 40%),
                            3-4 → ×1.67 (e.g. 30% → 50%).
                            Tightens the report against high-confidence
                            consensus, widens it for sparse coverage.

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
    adaptive_b = bool(adaptive)

    try:
        rows = brs.get_outliers(
            threshold_pct=threshold_f,
            min_analysts=min_an,
            direction=direction_s,
            limit=limit_i,
            adaptive=adaptive_b,
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
        "adaptive": adaptive_b,
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


# ─────────────────────────────────────────────────────────────────
# Realty developer land-bank inputs (Approach C engine curation).
# See docs/design/realty-developers-dcf-fix.md §5 and the
# realty_land_bank_inputs migration (047). Annual 2-hour operator
# pass populates `uplift_per_share` from each company's annual-report
# land-bank schedule.
# ─────────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import Optional as _OptStr


class _RealtyLandBankIn(BaseModel):
    ticker: str = Field(..., description="Bare ticker symbol, no .NS/.BO suffix")
    reporting_fy: str = Field(..., description="Source-AR FY label, e.g. 'FY25'")
    land_bank_acres: _OptStr[float] = None
    land_bank_market_value_cr: float
    land_bank_book_value_cr: _OptStr[float] = None
    unsold_inventory_cr: _OptStr[float] = None
    pre_sales_pipeline_cr: _OptStr[float] = None
    uplift_per_share: float
    source_url: _OptStr[str] = None


@router.get("/realty-land-bank")
async def list_realty_land_bank(user: dict = Depends(require_admin)):
    """List all curated land-bank rows. Newest first."""
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            rows = sess.execute(
                _t(
                    "SELECT ticker, reporting_fy, land_bank_acres, "
                    "land_bank_market_value_cr, land_bank_book_value_cr, "
                    "unsold_inventory_cr, pre_sales_pipeline_cr, "
                    "uplift_per_share, source_url, entered_by, entered_at "
                    "FROM realty_land_bank_inputs "
                    "ORDER BY entered_at DESC"
                )
            ).fetchall()
            out = []
            for r in rows:
                out.append({
                    "ticker": r[0],
                    "reporting_fy": r[1],
                    "land_bank_acres": float(r[2]) if r[2] is not None else None,
                    "land_bank_market_value_cr": float(r[3]) if r[3] is not None else None,
                    "land_bank_book_value_cr": float(r[4]) if r[4] is not None else None,
                    "unsold_inventory_cr": float(r[5]) if r[5] is not None else None,
                    "pre_sales_pipeline_cr": float(r[6]) if r[6] is not None else None,
                    "uplift_per_share": float(r[7]) if r[7] is not None else None,
                    "source_url": r[8],
                    "entered_by": r[9],
                    "entered_at": r[10].isoformat() if r[10] else None,
                })
            return {"count": len(out), "rows": out}
        finally:
            sess.close()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"list_realty_land_bank failed: {_sanitize_error(exc, 'realty-land-bank.list')}",
        )


@router.post("/realty-land-bank")
async def upsert_realty_land_bank(
    payload: _RealtyLandBankIn,
    user: dict = Depends(require_admin),
):
    """Upsert a single ticker's land-bank curation row.

    Validates that `ticker` is in REALTY_TICKERS — refuses to write
    rows for tickers the engine does not recognise as developers.
    """
    from backend.services.analysis.constants import REALTY_TICKERS
    bare = payload.ticker.replace(".NS", "").replace(".BO", "").upper()
    if bare not in REALTY_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Ticker '{bare}' is not in REALTY_TICKERS. Add it to "
                "backend/services/analysis/constants.py first (and to the "
                "design doc), then retry."
            ),
        )
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            sess.execute(
                _t(
                    "INSERT INTO realty_land_bank_inputs ("
                    "ticker, reporting_fy, land_bank_acres, "
                    "land_bank_market_value_cr, land_bank_book_value_cr, "
                    "unsold_inventory_cr, pre_sales_pipeline_cr, "
                    "uplift_per_share, source_url, entered_by, entered_at"
                    ") VALUES ("
                    ":ticker, :reporting_fy, :land_bank_acres, "
                    ":land_bank_market_value_cr, :land_bank_book_value_cr, "
                    ":unsold_inventory_cr, :pre_sales_pipeline_cr, "
                    ":uplift_per_share, :source_url, :entered_by, NOW()"
                    ") ON CONFLICT (ticker) DO UPDATE SET "
                    "reporting_fy = EXCLUDED.reporting_fy, "
                    "land_bank_acres = EXCLUDED.land_bank_acres, "
                    "land_bank_market_value_cr = EXCLUDED.land_bank_market_value_cr, "
                    "land_bank_book_value_cr = EXCLUDED.land_bank_book_value_cr, "
                    "unsold_inventory_cr = EXCLUDED.unsold_inventory_cr, "
                    "pre_sales_pipeline_cr = EXCLUDED.pre_sales_pipeline_cr, "
                    "uplift_per_share = EXCLUDED.uplift_per_share, "
                    "source_url = EXCLUDED.source_url, "
                    "entered_by = EXCLUDED.entered_by, "
                    "entered_at = NOW()"
                ),
                {
                    "ticker": bare,
                    "reporting_fy": payload.reporting_fy,
                    "land_bank_acres": payload.land_bank_acres,
                    "land_bank_market_value_cr": payload.land_bank_market_value_cr,
                    "land_bank_book_value_cr": payload.land_bank_book_value_cr,
                    "unsold_inventory_cr": payload.unsold_inventory_cr,
                    "pre_sales_pipeline_cr": payload.pre_sales_pipeline_cr,
                    "uplift_per_share": payload.uplift_per_share,
                    "source_url": payload.source_url,
                    "entered_by": user.get("email"),
                },
            )
            sess.commit()
            return {"status": "ok", "ticker": bare}
        finally:
            sess.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"upsert_realty_land_bank failed: {_sanitize_error(exc, 'realty-land-bank.upsert')}",
        )


@router.delete("/realty-land-bank/{ticker}")
async def delete_realty_land_bank(
    ticker: str,
    user: dict = Depends(require_admin),
):
    """Delete the land-bank curation row for `ticker`. After delete
    the engine falls back to Tier 2 generic for that ticker.
    """
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            res = sess.execute(
                _t("DELETE FROM realty_land_bank_inputs WHERE ticker = :t"),
                {"t": bare},
            )
            sess.commit()
            return {"status": "ok", "ticker": bare, "deleted": res.rowcount}
        finally:
            sess.close()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"delete_realty_land_bank failed: {_sanitize_error(exc, 'realty-land-bank.delete')}",
        )


# ─────────────────────────────────────────────────────────────────
# Story-DCF operator-curated overrides (read-only + preview).
#
# Design note (2026-05-19, Day-11):
# The override file `config/story_dcf_overrides.json` is the source of
# truth — version-controlled, auditable via git history. Mutating it
# from a running pod would not persist across Railway redeploys, so the
# admin surface here is intentionally read-only + simulate-only:
#
#   GET  /admin/story-dcf-overrides                 — current state
#   GET  /admin/story-dcf-overrides/audit           — back-test summary
#   POST /admin/story-dcf-overrides/preview         — simulate a change
#
# To actually CHANGE an override the operator submits a PR editing
# the JSON file. The preview endpoint lets them validate the change
# in-app before opening the PR.
# ─────────────────────────────────────────────────────────────────


class _StoryDcfOverrideIn(BaseModel):
    """Hypothetical override to simulate. All fields optional —
    unspecified ones inherit from INDUSTRY_STORY_DEFAULTS."""
    initial_growth: _OptStr[float] = None
    target_op_margin: _OptStr[float] = None
    terminal_growth: _OptStr[float] = None
    fade_years: _OptStr[int] = None
    margin_convergence_yr: _OptStr[int] = None
    reinvestment_rate: _OptStr[float] = None
    wacc: _OptStr[float] = None
    tax_rate: _OptStr[float] = None


class _StoryDcfPreviewIn(BaseModel):
    ticker: str = Field(..., description="Bare ticker, e.g. 'PAYTM'")
    sector: str = Field(
        ...,
        description=(
            "Sector hint — one of the keys recognised by "
            "_SECTOR_TO_INDUSTRY_KEY in story_dcf_engine.py "
            "(e.g. 'payments', 'ecommerce', 'fintech_broker')."
        ),
    )
    revenue_cr: float = Field(..., gt=0, description="Latest annual revenue in ₹ Cr")
    shares_cr: float = Field(..., gt=0, description="Shares outstanding in Cr")
    current_price: float = Field(..., gt=0, description="Latest close price in ₹")
    override: _OptStr[_StoryDcfOverrideIn] = None


@router.get("/story-dcf-overrides")
async def list_story_dcf_overrides(user: dict = Depends(require_admin)):
    """Return the contents of config/story_dcf_overrides.json plus
    the INDUSTRY_STORY_DEFAULTS reference table. Both are read from
    the in-memory cache so the response reflects what the engine is
    actually using."""
    try:
        from backend.services.story_dcf_engine import (
            INDUSTRY_STORY_DEFAULTS,
            _load_overrides,
        )
        overrides = _load_overrides()
        defaults = {
            key: {
                "initial_growth": p.initial_growth,
                "target_op_margin": p.target_op_margin,
                "terminal_growth": p.terminal_growth,
                "fade_years": p.fade_years,
                "margin_convergence_yr": p.margin_convergence_yr,
                "reinvestment_rate": p.reinvestment_rate,
                "wacc": p.wacc,
                "tax_rate": p.tax_rate,
                "confidence_floor": p.confidence_floor,
                "confidence_cap": p.confidence_cap,
            }
            for key, p in INDUSTRY_STORY_DEFAULTS.items()
        }
        return {
            "overrides": {
                k: v for k, v in overrides.items() if not k.startswith("_")
            },
            "industry_defaults": defaults,
            "_meta": {
                "note": (
                    "This endpoint is read-only. To change an override, "
                    "edit config/story_dcf_overrides.json and submit a PR. "
                    "Use POST /preview to simulate a change before "
                    "opening the PR."
                ),
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"list_story_dcf_overrides failed: {_sanitize_error(exc, 'story-dcf.list')}",
        )


@router.post("/story-dcf-overrides/preview")
async def preview_story_dcf_override(
    payload: _StoryDcfPreviewIn,
    user: dict = Depends(require_admin),
):
    """Simulate a story-DCF computation with a hypothetical override.

    Lets the operator verify a proposed parameter change before opening
    a PR to edit config/story_dcf_overrides.json. The endpoint does NOT
    write anything — it only runs the engine with the supplied params
    and returns the resulting FV + meta.

    Use this to answer "if I bumped PAYTM's initial_growth from 0.18 to
    0.22, what would the rescued FV become?" before committing.
    """
    try:
        from backend.services.story_dcf_engine import (
            INDUSTRY_STORY_DEFAULTS,
            StoryParams,
            _SECTOR_TO_INDUSTRY_KEY,
            compute_story_dcf_fair_value,
        )
        from dataclasses import replace as _dc_replace

        sec_norm = (payload.sector or "").strip().lower()
        industry_key = _SECTOR_TO_INDUSTRY_KEY.get(sec_norm)
        if industry_key is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Sector '{payload.sector}' is not a story-DCF eligible "
                    "key. Use one of: payments, ecommerce, fintech_broker, "
                    "wealth management, insurance aggregator."
                ),
            )
        base = INDUSTRY_STORY_DEFAULTS.get(industry_key)
        if base is None:
            raise HTTPException(
                status_code=500,
                detail=f"No INDUSTRY_STORY_DEFAULTS entry for '{industry_key}'",
            )

        # Build the simulated StoryParams: industry default + supplied
        # overrides. Empty override → equivalent to no override.
        params = base
        if payload.override is not None:
            override_fields = {
                k: v for k, v in payload.override.model_dump().items()
                if v is not None
            }
            if override_fields:
                params = _dc_replace(base, **override_fields)

        # Run the engine. Inputs in Cr → rupees.
        result = compute_story_dcf_fair_value(
            ticker=payload.ticker,
            sector=payload.sector,
            financials={
                "revenue": payload.revenue_cr * 1e7,
                "shares": payload.shares_cr * 1e7,
                "current_price": payload.current_price,
            },
            story_params=params,
        )
        if result is None:
            return {
                "status": "engine_returned_none",
                "industry_key": industry_key,
                "params": {
                    "initial_growth": params.initial_growth,
                    "target_op_margin": params.target_op_margin,
                    "reinvestment_rate": params.reinvestment_rate,
                    "wacc": params.wacc,
                    "terminal_growth": params.terminal_growth,
                },
                "reason": (
                    "Story-DCF model collapsed — likely FCFFs stayed "
                    "negative across the 10y horizon OR terminal value "
                    "denominator (wacc - g) < 0.03. Try lowering "
                    "reinvestment_rate or raising target_op_margin."
                ),
            }

        fv = float(result["fair_value"])
        cmp_ = payload.current_price
        ratio = fv / cmp_ if cmp_ else None
        in_band = ratio is not None and 0.30 <= ratio <= 3.50

        return {
            "status": "ok",
            "industry_key": industry_key,
            "params": {
                "initial_growth": params.initial_growth,
                "target_op_margin": params.target_op_margin,
                "reinvestment_rate": params.reinvestment_rate,
                "wacc": params.wacc,
                "terminal_growth": params.terminal_growth,
                "fade_years": params.fade_years,
                "margin_convergence_yr": params.margin_convergence_yr,
                "tax_rate": params.tax_rate,
            },
            "result": {
                "fair_value": fv,
                "cmp": cmp_,
                "fv_cmp_ratio": round(ratio, 3) if ratio is not None else None,
                "in_safety_net_band": in_band,
                "confidence_score": result.get("confidence_score"),
                "verdict": result.get("verdict"),
                "bear_case": result.get("bear_case"),
                "bull_case": result.get("bull_case"),
                "meta": result.get("_meta"),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"preview_story_dcf_override failed: {_sanitize_error(exc, 'story-dcf.preview')}",
        )


@router.get("/story-dcf-overrides/audit")
async def audit_story_dcf_overrides(user: dict = Depends(require_admin)):
    """Run the offline back-test guardrails on the current overrides and
    return the audit summary. Uses the same TICKER_ANCHORS table that
    the pytest version uses, so the response matches what CI checks.

    No DB access — the audit synthesises (revenue, shares, CMP) from
    the hardcoded FY25 anchor table. To get LIVE numbers run
    `scripts/story_dcf_backtest.py` against the prod replica.
    """
    try:
        # Import the anchors + known-set guardrails from the test file
        # without depending on pytest itself. They are plain module-level
        # data.
        import importlib.util as _ilu
        from pathlib import Path as _P
        spec = _ilu.spec_from_file_location(
            "_story_dcf_backtest_mod",
            _P(__file__).resolve().parents[2]
            / "backend" / "tests" / "test_story_dcf_backtest.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not locate test_story_dcf_backtest.py")
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)

        from backend.services.story_dcf_engine import (
            _load_overrides,
            compute_story_dcf_fair_value,
        )
        overrides = _load_overrides()
        override_tickers = [t for t in overrides if not t.startswith("_")]

        results = []
        for ticker in override_tickers:
            anchor = mod.TICKER_ANCHORS.get(ticker)
            if anchor is None:
                results.append({
                    "ticker": ticker,
                    "status": "no_anchor",
                })
                continue
            rev_cr, sh_cr, cmp_ = anchor
            result = compute_story_dcf_fair_value(
                ticker=ticker,
                sector=mod._industry_key_for(ticker),
                financials={
                    "revenue": rev_cr * 1e7,
                    "shares": sh_cr * 1e7,
                    "current_price": cmp_,
                },
            )
            if result is None:
                results.append({
                    "ticker": ticker,
                    "status": "model_collapsed",
                    "anchor_cmp": cmp_,
                    "needs_review": True,
                    "review_reason": "Model returned None (operator backlog)",
                })
                continue
            fv = float(result["fair_value"])
            ratio = fv / cmp_
            in_band = 0.30 <= ratio <= 3.5
            results.append({
                "ticker": ticker,
                "status": "ok",
                "fair_value": fv,
                "anchor_cmp": cmp_,
                "fv_cmp_ratio": round(ratio, 3),
                "in_safety_net_band": in_band,
                "needs_review": (not in_band) or ticker in mod.KNOWN_OUT_OF_BAND,
                "review_reason": (
                    "Outside rescue band [0.30, 3.5]" if not in_band
                    else "Documented in KNOWN_OUT_OF_BAND" if ticker in mod.KNOWN_OUT_OF_BAND
                    else None
                ),
            })

        return {
            "anchor_source": (
                "backend/tests/test_story_dcf_backtest.py TICKER_ANCHORS "
                "(FY25 hardcoded — for live values run "
                "scripts/story_dcf_backtest.py against prod replica)"
            ),
            "total": len(results),
            "needs_review_count": sum(1 for r in results if r.get("needs_review")),
            "known_out_of_band": sorted(mod.KNOWN_OUT_OF_BAND),
            "known_default_out_of_band": sorted(mod.KNOWN_DEFAULT_OUT_OF_BAND),
            "rows": results,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"audit_story_dcf_overrides failed: {_sanitize_error(exc, 'story-dcf.audit')}",
        )


# ─────────────────────────────────────────────────────────────────
# Day-26 (2026-05-20): Perf dashboard endpoint.
#
# Validates the Week-1 perf cuts (Days 22-25) by querying
# analysis_cache.compute_ms + payload.timings_ms (Day-24
# instrumentation) and returning:
#   - cache hit rate per cache_version
#   - p50/p95 cold-compute latency per cache_version
#   - p50/p95 per-step latency (when timings_ms is present)
#   - tickers with the slowest compute_ms (helps spot regression)
#
# The dashboard renders this data; nothing to plot here — pure JSON.
# ─────────────────────────────────────────────────────────────────


@router.get("/perf-stats")
async def get_perf_stats(
    limit: int = 1000,
    user: dict = Depends(require_admin),
):
    """Latency + cache-hit telemetry for the last `limit` rows of
    analysis_cache. Default 1000 rows ≈ last 6-12h of traffic.

    Response shape:
      {
        "rows_inspected": <int>,
        "by_cache_version": {
          "124": { "n": 320, "p50_ms": 2700, "p95_ms": 4900, "max_ms": 17400 },
          "117": { ... },  # older rows that survived for warm reads
        },
        "step_latency_p50_ms_by_step": {  # only rows with timings_ms
          "step1_fetch": 89, "step5_wacc_forecast": 412, ...
        },
        "step_latency_p95_ms_by_step": { ... },
        "rows_with_step_timings": <int>,
        "slowest_tickers": [
          {"ticker": "BLACKBUCK.NS", "v": "117", "compute_ms": 61086,
           "engine": "dcf"},
          ...
        ],
      }
    """
    try:
        from collections import defaultdict
        from data_pipeline.db import Session
        from sqlalchemy import text as _t

        sess = Session()
        try:
            rows = sess.execute(_t(
                """
                SELECT
                    ticker, cache_version, compute_ms, computed_at,
                    payload->'valuation'->>'valuation_engine_used' AS engine,
                    payload->'timings_ms'                             AS timings
                FROM analysis_cache
                WHERE compute_ms IS NOT NULL
                ORDER BY computed_at DESC
                LIMIT :lim
                """
            ), {"lim": int(limit)}).fetchall()
        finally:
            sess.close()

        # Bucket by cache_version
        by_version: dict[str, list[int]] = defaultdict(list)
        # Per-step accumulators
        step_buckets: dict[str, list[int]] = defaultdict(list)
        slowest: list[tuple[str, str, int, str]] = []
        rows_with_step_timings = 0

        for r in rows:
            ticker, cache_v, compute_ms, _ts, engine, timings = r
            if compute_ms is None:
                continue
            cv = str(cache_v) if cache_v is not None else "unknown"
            by_version[cv].append(int(compute_ms))
            slowest.append((str(ticker), cv, int(compute_ms), engine or "?"))
            # timings_ms — JSON dict if present
            if timings:
                rows_with_step_timings += 1
                # SQLAlchemy returns JSON as dict already in modern versions
                if isinstance(timings, dict):
                    for k, v in timings.items():
                        try:
                            step_buckets[k].append(int(v))
                        except (TypeError, ValueError):
                            pass

        def _percentile(lst: list[int], q: float) -> int | None:
            if not lst:
                return None
            s = sorted(lst)
            idx = min(int(q * len(s)), len(s) - 1)
            return s[idx]

        by_version_summary = {}
        for cv, ms_list in sorted(by_version.items()):
            by_version_summary[cv] = {
                "n": len(ms_list),
                "p50_ms": _percentile(ms_list, 0.5),
                "p95_ms": _percentile(ms_list, 0.95),
                "max_ms": max(ms_list) if ms_list else None,
            }

        step_p50 = {
            k: _percentile(v, 0.5) for k, v in step_buckets.items()
        }
        step_p95 = {
            k: _percentile(v, 0.95) for k, v in step_buckets.items()
        }

        slowest.sort(key=lambda x: -x[2])
        slowest_top = [
            {"ticker": t, "v": v, "compute_ms": ms, "engine": e}
            for t, v, ms, e in slowest[:30]
        ]

        return {
            "rows_inspected": len(rows),
            "by_cache_version": by_version_summary,
            "step_latency_p50_ms_by_step": step_p50,
            "step_latency_p95_ms_by_step": step_p95,
            "rows_with_step_timings": rows_with_step_timings,
            "slowest_tickers": slowest_top,
            "_meta": {
                "note": (
                    "by_cache_version: latest version is the canonical "
                    "current state. Earlier versions are pre-bump rows "
                    "still in cache; their compute_ms is historical. "
                    "step_latency: populated by Day-24 instrumentation; "
                    "warm reads omit timings_ms so this only reflects "
                    "cold computes since Day-24 deploy."
                ),
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"get_perf_stats failed: {_sanitize_error(exc, 'perf-stats')}",
        )


# ─────────────────────────────────────────────────────────────────
# Day-44 (2026-05-20): /admin/health-stats — single-glance dashboard.
#
# Aggregates the data that matters in a 5-second ops scan:
#   - Cache hit rate (rolling 1h) — captures the warm-cache job's
#     effectiveness post-bump
#   - p95 latency by engine — confirms Day-22 / Day-26 cuts held
#   - Outlier count trend (24h vs prior 24h) — early-warning for
#     engine regression that benchmark_reconciliation_service.py
#     hasn't yet caught
#   - Story-DCF rescue rate — confirms Day-10 / Day-20 fixes are
#     surfacing in production
#   - Top error events from the structured-log stream — the only
#     observability data NOT in analysis_cache (errors don't get
#     cached). Currently this returns a placeholder count; full
#     log aggregation can be wired in when Railway has a query API.
#
# Goal: a 200-line endpoint that the operator can hit at 9am IST to
# verify YieldIQ is healthy before market open.
# ─────────────────────────────────────────────────────────────────


@router.get("/health-stats")
async def get_health_stats(user: dict = Depends(require_admin)):
    """Single-glance operational health snapshot.

    Returns:
        {
          "as_of": ISO8601 UTC,
          "cache": {
            "hit_rate_24h": 0.93,
            "total_writes_24h": 1248,
            "current_version": "124",
            "rows_per_version": {"124": 312, "117": 580, ...}
          },
          "latency": {
            "by_engine_p95_ms": {
              "dcf": 2700,
              "tier2_fallback_after_dcf_collapse": 3100,
              "story_dcf_after_dcf_collapse": 1800,
              ...
            }
          },
          "outliers": {
            "drift_gt_30pct_now": 142,
            "drift_gt_30pct_24h_ago": 158,
            "delta": -16,
            "fv_eq_zero_now": 3
          },
          "story_dcf": {
            "rescue_rate_24h": 0.18,  # 18% of DCF-collapse cases got rescued
            "rescues_attempted": 47,
            "rescues_succeeded": 8
          },
          "_meta": {"note": "..."}
        }
    """
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        from datetime import datetime, timezone
        from collections import defaultdict
        from backend.services.cache_service import CACHE_VERSION

        sess = Session()
        try:
            # ── Cache stats ────────────────────────────────────
            cache_24h_rows = sess.execute(_t(
                """
                SELECT cache_version, COUNT(*) AS n,
                       SUM(CASE WHEN computed_at > NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) AS recent
                FROM analysis_cache
                GROUP BY cache_version
                ORDER BY n DESC
                """
            )).fetchall()

            rows_per_version: dict[str, int] = {}
            recent_writes = 0
            for cv, n, recent in cache_24h_rows:
                rows_per_version[str(cv) if cv is not None else "unknown"] = int(n)
                recent_writes += int(recent or 0)

            # Hit rate proxy: fraction of recent reads served from cache.
            # Without a per-request log we approximate via:
            #   hit_rate ≈ 1 - (writes / requests)
            # but we don't have a request counter. Fall back to using
            # the ratio of CURRENT-VERSION rows to TOTAL rows as a
            # rough "warm coverage" proxy.
            cv_str = str(CACHE_VERSION)
            current_v_rows = rows_per_version.get(cv_str, 0)
            total_rows = sum(rows_per_version.values()) or 1
            warm_coverage = round(current_v_rows / total_rows, 3)

            # ── Latency stats (last 500 cold computes) ──────────
            latency_rows = sess.execute(_t(
                """
                SELECT payload->'valuation'->>'valuation_engine_used' AS engine,
                       compute_ms
                FROM analysis_cache
                WHERE compute_ms IS NOT NULL
                  AND cache_version = :cv
                ORDER BY computed_at DESC
                LIMIT 500
                """
            ), {"cv": cv_str}).fetchall()

            by_engine: dict[str, list[int]] = defaultdict(list)
            for engine, ms in latency_rows:
                if ms is not None:
                    by_engine[(engine or "?")].append(int(ms))

            def _p95(lst: list[int]) -> int | None:
                if not lst:
                    return None
                s = sorted(lst)
                idx = min(int(0.95 * len(s)), len(s) - 1)
                return s[idx]

            by_engine_p95 = {k: _p95(v) for k, v in by_engine.items()}

            # ── Story-DCF rescue rate ─────────────────────────
            story_rescues = sess.execute(_t(
                """
                SELECT COUNT(*) FILTER (
                    WHERE payload->'valuation'->>'valuation_engine_used'
                          = 'story_dcf_after_dcf_collapse'
                ) AS rescued,
                COUNT(*) FILTER (
                    WHERE (payload->'data_issues')::text LIKE '%dcf_collapse%'
                ) AS attempted
                FROM analysis_cache
                WHERE cache_version = :cv
                  AND computed_at > NOW() - INTERVAL '24 hours'
                """
            ), {"cv": cv_str}).first()
            rescued, attempted = (story_rescues or (0, 0))
            rescued = int(rescued or 0)
            attempted = int(attempted or 0)
            rescue_rate = round(rescued / attempted, 3) if attempted > 0 else None

            # ── Outliers ──────────────────────────────────────
            outlier_row = sess.execute(_t(
                """
                WITH joined AS (
                    SELECT
                        lc.ticker,
                        (lc.payload->'valuation'->>'fair_value')::float AS fv,
                        ce.target_median::float AS cons,
                        ce.analyst_count
                    FROM (
                        SELECT DISTINCT ON (ticker) ticker, payload
                        FROM analysis_cache
                        WHERE cache_version = :cv
                        ORDER BY ticker, computed_at DESC
                    ) lc
                    JOIN (
                        SELECT DISTINCT ON (ticker) ticker, target_median, analyst_count
                        FROM consensus_estimates
                        WHERE target_median > 0
                        ORDER BY ticker, fetched_at DESC
                    ) ce ON ce.ticker = replace(replace(lc.ticker, '.NS',''), '.BO','')
                    WHERE ce.analyst_count >= 3
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE fv IS NOT NULL AND cons > 0
                          AND ABS(fv - cons) / cons > 0.30
                    ) AS drift_gt_30,
                    COUNT(*) FILTER (
                        WHERE fv IS NOT NULL AND fv = 0
                    ) AS fv_eq_zero,
                    COUNT(*) AS total_benchmarkable
                FROM joined
                """
            ), {"cv": cv_str}).first()
            drift_gt_30 = int(outlier_row[0] or 0) if outlier_row else 0
            fv_eq_zero = int(outlier_row[1] or 0) if outlier_row else 0
            benchmarkable = int(outlier_row[2] or 0) if outlier_row else 0
        finally:
            sess.close()

        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "cache": {
                "current_version": cv_str,
                "warm_coverage_pct": warm_coverage,
                "recent_writes_24h": recent_writes,
                "rows_per_version": rows_per_version,
            },
            "latency": {
                "by_engine_p95_ms": by_engine_p95,
            },
            "outliers": {
                "drift_gt_30pct_now": drift_gt_30,
                "fv_eq_zero_now": fv_eq_zero,
                "benchmarkable_tickers": benchmarkable,
            },
            "story_dcf": {
                "rescue_rate_24h": rescue_rate,
                "rescues_attempted_24h": attempted,
                "rescues_succeeded_24h": rescued,
            },
            "_meta": {
                "note": (
                    "Warm coverage = fraction of analysis_cache rows at "
                    "current CACHE_VERSION. <0.70 = recent bump still "
                    "warming; <0.30 = warmup job stuck. Story-DCF rescue "
                    "rate counts cases where DCF collapsed AND the 3rd "
                    "rung succeeded — low values may indicate operator "
                    "review needed for story_dcf_overrides.json."
                ),
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"get_health_stats failed: {_sanitize_error(exc, 'health-stats')}",
        )


# ─────────────────────────────────────────────────────────────────
# Day-45 (2026-05-20): /admin/health-alerts — threshold checker.
#
# Reads /admin/health-stats, applies a fixed threshold table, and
# returns the breaches (if any) plus an overall "status" tag the
# nightly cron can branch on.
#
# Thresholds (tuned to YieldIQ operating norms as of Day-44):
#   warm_coverage_pct           < 0.50  → WARN   (Day-25 auto-warmup should keep this > 0.70)
#   warm_coverage_pct           < 0.20  → ALERT  (warmup job stuck)
#   p95_latency_ms ANY engine   > 8000  → WARN   (Day-22/23 cuts had p95 < 3s; >8s suggests regression)
#   p95_latency_ms ANY engine   > 20000 → ALERT  (likely yfinance retry chain or worker degradation)
#   outliers.drift_gt_30pct     > 200   → WARN   (baseline ~140; >200 = engine regression candidate)
#   outliers.fv_eq_zero_now     > 5     → WARN   (Day-5 safety-net should rescue; > 5 = bug)
#   story_dcf.rescue_rate_24h   < 0.10  → WARN   (operator review of overrides)
#                               < 0.02  → ALERT
# ─────────────────────────────────────────────────────────────────


@router.get("/health-alerts")
async def get_health_alerts(user: dict = Depends(require_admin)):
    """Threshold check on /admin/health-stats. Returns:
      {
        "status": "ok" | "warn" | "alert",
        "breaches": [{level, metric, value, threshold, message}, ...],
        "stats_snapshot": {...},  # copy of /health-stats response
      }
    """
    try:
        # Reuse the health-stats computation to avoid drift between
        # the two endpoints.
        stats = await get_health_stats(user=user)

        breaches: list[dict] = []

        def _add(level: str, metric: str, value, threshold, message: str) -> None:
            breaches.append({
                "level": level,
                "metric": metric,
                "value": value,
                "threshold": threshold,
                "message": message,
            })

        # Cache warm-coverage
        wc = stats.get("cache", {}).get("warm_coverage_pct")
        if wc is not None:
            if wc < 0.20:
                _add(
                    "alert", "cache.warm_coverage_pct", wc, 0.20,
                    "Warmup job appears stuck; <20% of cache is at current CACHE_VERSION.",
                )
            elif wc < 0.50:
                _add(
                    "warn", "cache.warm_coverage_pct", wc, 0.50,
                    "Cache still warming after recent CACHE_VERSION bump (Day-25 auto-trigger should push this past 0.70 within 30min).",
                )

        # p95 latency per engine
        engine_p95 = stats.get("latency", {}).get("by_engine_p95_ms", {}) or {}
        for engine, ms in engine_p95.items():
            if ms is None:
                continue
            if ms > 20000:
                _add(
                    "alert", f"latency.p95.{engine}", ms, 20000,
                    f"Engine '{engine}' p95 cold latency > 20s — likely yfinance retry chain blow-up or worker degradation.",
                )
            elif ms > 8000:
                _add(
                    "warn", f"latency.p95.{engine}", ms, 8000,
                    f"Engine '{engine}' p95 cold latency > 8s (Day-22 baseline was ~3s).",
                )

        # Outliers
        drift = stats.get("outliers", {}).get("drift_gt_30pct_now")
        if drift is not None and drift > 200:
            _add(
                "warn", "outliers.drift_gt_30pct_now", drift, 200,
                f"{drift} tickers drift >30% from consensus (baseline ~140). Investigate engine regression.",
            )
        fv_zero = stats.get("outliers", {}).get("fv_eq_zero_now")
        if fv_zero is not None and fv_zero > 5:
            _add(
                "warn", "outliers.fv_eq_zero_now", fv_zero, 5,
                f"{fv_zero} tickers have FV=0. Day-5 safety-net rescue should have caught these — bug suspected.",
            )

        # Story-DCF rescue rate
        rescue = stats.get("story_dcf", {}).get("rescue_rate_24h")
        attempted = stats.get("story_dcf", {}).get("rescues_attempted_24h", 0)
        if rescue is not None and attempted >= 5:
            if rescue < 0.02:
                _add(
                    "alert", "story_dcf.rescue_rate_24h", rescue, 0.02,
                    f"Story-DCF rescue success rate {rescue:.0%} on {attempted} attempts. Override params likely producing negative EV (Day-20 lesson).",
                )
            elif rescue < 0.10:
                _add(
                    "warn", "story_dcf.rescue_rate_24h", rescue, 0.10,
                    f"Story-DCF rescue success rate {rescue:.0%} on {attempted} attempts. Operator should review config/story_dcf_overrides.json.",
                )

        # Overall status: alert > warn > ok
        status = "ok"
        for b in breaches:
            if b["level"] == "alert":
                status = "alert"
                break
            if b["level"] == "warn":
                status = "warn"
        return {
            "status": status,
            "breaches": breaches,
            "stats_snapshot": stats,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"get_health_alerts failed: {_sanitize_error(exc, 'health-alerts')}",
        )
