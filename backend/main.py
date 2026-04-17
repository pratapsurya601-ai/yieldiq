# backend/main.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ API — FastAPI entry point
# Wraps existing 20,000+ lines of valuation logic in REST API.
#
# RAILWAY DEPLOYMENT:
# 1. Create new Railway service → connect GitHub repo
# 2. Root directory: / (not /backend)
# 3. Start command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
# 4. Add env vars from backend/.env.railway.example
# 5. Add custom domain: api.yieldiq.in
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

# PATH + ENV SETUP — must happen before ANY other imports
import sys, os
from pathlib import Path
_ROOT = str(Path(__file__).resolve().parent.parent)

# Load .env file if it exists (local dev — Railway uses dashboard env vars)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_DASHBOARD = os.path.join(_ROOT, "dashboard")
if _DASHBOARD not in sys.path:
    sys.path.insert(0, _DASHBOARD)

# Verify path works before importing anything else
import importlib.util as _ilu
_logger_spec = _ilu.spec_from_file_location("utils.logger", os.path.join(_ROOT, "utils", "logger.py"))
if _logger_spec and _logger_spec.loader:
    _logger_mod = _ilu.module_from_spec(_logger_spec)
    sys.modules["utils.logger"] = _logger_mod
    _logger_spec.loader.exec_module(_logger_mod)
# Also pre-load utils package
_utils_spec = _ilu.spec_from_file_location("utils", os.path.join(_ROOT, "utils", "__init__.py"),
                                            submodule_search_locations=[os.path.join(_ROOT, "utils")])
if _utils_spec:
    _utils_mod = _ilu.module_from_spec(_utils_spec)
    sys.modules.setdefault("utils", _utils_mod)
    try:
        _utils_spec.loader.exec_module(_utils_mod)
    except Exception:
        pass

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import analysis, screener, portfolio, watchlist, alerts, market, auth
from backend.routers import payments, pipeline, email, referral, admin, public
from backend.middleware.cors import ALLOWED_ORIGINS, ALLOWED_ORIGIN_REGEX

logger = logging.getLogger(__name__)


# ── Scheduler for data pipeline ─────────────────────────────
def _start_pipeline_scheduler():
    """Start APScheduler for daily price + weekly fundamentals updates."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("apscheduler not installed — pipeline scheduler disabled")
        return None

    if not os.environ.get("DATABASE_URL"):
        logger.info("DATABASE_URL not set — pipeline scheduler disabled")
        return None

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Daily price update — 4:30pm IST (after market close)
    scheduler.add_job(
        _run_daily_prices,
        CronTrigger(hour=16, minute=30, timezone="Asia/Kolkata"),
        id="daily_prices",
        name="NSE Bhavcopy daily update",
        replace_existing=True,
    )

    # Weekly fundamentals — Sunday 11pm IST
    scheduler.add_job(
        _run_weekly_fundamentals,
        CronTrigger(day_of_week="sun", hour=23, minute=0, timezone="Asia/Kolkata"),
        id="weekly_fundamentals",
        name="Weekly fundamentals update",
        replace_existing=True,
    )

    # Price alerts — check every 3 hours during market hours (9am-5pm IST)
    scheduler.add_job(
        _run_alert_check,
        CronTrigger(hour="9,12,15,17", minute=15, timezone="Asia/Kolkata"),
        id="alert_check",
        name="Price alert check",
        replace_existing=True,
    )

    # Weekly digest email — Monday 9am IST
    scheduler.add_job(
        _send_weekly_digests,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Asia/Kolkata"),
        id="weekly_digest",
        name="Weekly digest email",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Pipeline scheduler started: daily 4:30pm IST, weekly Sun 11pm IST, alerts every 3h, digest Mon 9am IST")
    return scheduler


def _run_daily_prices():
    from data_pipeline.db import Session
    from data_pipeline.pipeline import run_daily_update
    if Session is None:
        return
    db = Session()
    try:
        run_daily_update(db)
    except Exception as e:
        logger.error(f"Daily pipeline failed: {e}")
    finally:
        db.close()


def _run_weekly_fundamentals():
    from data_pipeline.db import Session
    from data_pipeline.pipeline import run_weekly_update
    if Session is None:
        return
    db = Session()
    try:
        run_weekly_update(db)
    except Exception as e:
        logger.error(f"Weekly pipeline failed: {e}")
    finally:
        db.close()


def _run_alert_check():
    """Check all active price alerts and send email notifications for triggered ones."""
    try:
        from backend.services.alert_service import run_alert_check
        run_alert_check()
    except Exception as e:
        logger.error(f"Alert check failed: {e}")


def _send_weekly_digests():
    """Send weekly digest emails to all subscribed users."""
    try:
        from backend.services.email_service import send_weekly_digests_to_all
        count = send_weekly_digests_to_all()
        logger.info(f"Weekly digest job complete: {count} emails sent")
    except Exception as e:
        logger.error(f"Weekly digest job failed: {e}")


def _ensure_pipeline_tables():
    """Auto-create pipeline tables if DATABASE_URL is set."""
    if not os.environ.get("DATABASE_URL"):
        return
    try:
        from data_pipeline.db import engine
        from data_pipeline.models import Base
        if engine is not None:
            Base.metadata.create_all(engine)
            logger.info("Pipeline database tables created/verified")
    except Exception as e:
        logger.warning(f"Pipeline table creation skipped: {e}")


def _prewarm_popular_stocks():
    """Pre-warm cache for top 30 popular stocks on startup.

    Same list as the GitHub Actions cache_warmup cron so behaviour
    is consistent. Runs in a daemon thread to avoid blocking app
    startup; whole pass takes ~4-5 minutes in background.
    """
    import threading

    def _warm():
        import time
        from pathlib import Path
        time.sleep(5)  # Wait for app to fully start
        try:
            # ── Phase 1: Warm Aiven connection ───────────────────
            try:
                from data_pipeline.db import Session as _PS
                if _PS is not None:
                    _sess = _PS()
                    from sqlalchemy import text
                    _sess.execute(text("SELECT 1"))
                    _sess.close()
                    logger.info("Prewarm: Aiven DB connection OK")
            except Exception as _db_exc:
                logger.warning("Prewarm: Aiven DB connection failed (%s)", _db_exc)

            from backend.services.analysis_service import AnalysisService
            from backend.services.cache_service import cache
            svc = AnalysisService()

            # ── Phase 2: Prewarm top 50 (highest priority) ───────
            top50 = [
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
            ]
            warmed = 0
            for ticker in top50:
                _key = f"analysis:{ticker}"
                if cache.get(_key) is None:
                    try:
                        result = svc.get_full_analysis(ticker)
                        cache.set(_key, result, ttl=14400)
                        warmed += 1
                    except Exception:
                        pass
                    time.sleep(1)
            logger.info(f"Prewarm phase 2: {warmed} tickers cached")

            # ── Phase 3: Background refresh ALL Parquet tickers ──
            # Continuously cycle through all tickers so every user
            # hits a warm cache. 4-hour TTL means each ticker needs
            # refresh every 4 hours = ~500 tickers / 4 hrs = 2/min.
            parquet_dir = Path(__file__).resolve().parent / "data_pipeline" / "nse_prices" / "parquet"
            all_tickers = sorted([
                f"{p.stem}.NS" for p in parquet_dir.glob("*.parquet")
            ]) if parquet_dir.exists() else []
            logger.info(f"Background refresh: {len(all_tickers)} tickers to cycle")

            while True:
                for ticker in all_tickers:
                    _key = f"analysis:{ticker}"
                    if cache.get(_key) is None:
                        try:
                            result = svc.get_full_analysis(ticker)
                            cache.set(_key, result, ttl=14400)
                        except Exception:
                            pass
                        time.sleep(1)
                    else:
                        time.sleep(0.1)  # Already cached, skip fast
                logger.info("Background refresh: full cycle complete")
                time.sleep(60)  # Brief pause between cycles

        except Exception as e:
            logger.warning(f"Cache pre-warm failed: {e}")

    threading.Thread(target=_warm, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — creates tables + starts scheduler + pre-warms cache."""
    _ensure_pipeline_tables()
    sched = _start_pipeline_scheduler()
    _prewarm_popular_stocks()
    yield
    if sched:
        sched.shutdown(wait=False)

app = FastAPI(
    title="YieldIQ API",
    description="Institutional-grade DCF valuation API for Indian and global markets",
    version="1.0.1",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(screener.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(payments.router)
app.include_router(pipeline.router)
app.include_router(email.router)
app.include_router(referral.router)
app.include_router(admin.router)
app.include_router(public.router)


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway/monitoring."""
    return {"status": "ok", "version": "1.0.0", "service": "yieldiq-api"}


@app.get("/")
async def root():
    """API root — links to documentation."""
    return {
        "message": "YieldIQ API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/health",
    }
