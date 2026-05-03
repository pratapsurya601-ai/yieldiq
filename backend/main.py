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
import os
from contextlib import asynccontextmanager

# ── Sentry error monitoring ─────────────────────────────────
# Init as early as possible so unhandled exceptions raised during
# module import (e.g. a broken env var parse) are captured.
# Skips cleanly when SENTRY_DSN is unset — no-op in local dev.
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            release=os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")[:12],
            # Sample rate is conservative — 10% traces + 100% errors.
            # Free tier caps at ~5k events/month; bumping traces to 1.0
            # would burn through that in days.
            traces_sample_rate=0.10,
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                # Capture WARNING+ as breadcrumbs, ERROR+ as events.
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            # Scrub common secret patterns from any captured strings.
            # Sentry's default PII stripping handles headers; this adds
            # JWT_SECRET-style leaks in stringified payloads.
            before_send=lambda event, hint: _scrub_event(event),
        )
    except ImportError:
        # sentry-sdk not installed — log and continue silently.
        import logging as _boot_log
        _boot_log.getLogger("yieldiq.sentry").warning(
            "SENTRY_DSN set but sentry-sdk not installed — run `pip install sentry-sdk[fastapi]`"
        )
    except Exception as exc:
        import logging as _boot_log
        _boot_log.getLogger("yieldiq.sentry").warning("Sentry init failed: %s", exc)


def _init_yfinance_tz_cache() -> None:
    """Move yfinance's peewee SQLite tz cache to a per-worker directory.

    yfinance ships a process-shared SQLite cache at ``~/.cache/py-yfinance/``
    for timezone metadata. When Railway runs N uvicorn workers all hitting
    yf.Ticker() concurrently (HDFCBANK is the hot path — ~150 RPS at peak),
    they race on the same file and emit ``OperationalError: database is
    locked``. yfinance/base.py:190 then logs ERROR which Sentry escalates
    to an issue (27 events/24h observed 2026-05-03).

    Fix: point each worker at its own cache dir under /tmp keyed by PID.
    Cheap (the cache rebuilds in ms on first .info call) and removes the
    contention entirely. Safe no-op if yfinance isn't installed yet.
    """
    try:
        import tempfile
        import yfinance as _yf
        _per_worker = os.path.join(tempfile.gettempdir(), f"yf-tz-{os.getpid()}")
        os.makedirs(_per_worker, exist_ok=True)
        _yf.set_tz_cache_location(_per_worker)
    except Exception:
        # yfinance not importable, or set_tz_cache_location unavailable on
        # this version — both fine. We still have the Sentry noise filter
        # for "reason: database is locked" as a safety net.
        pass


_init_yfinance_tz_cache()


# Known-benign event signatures that should NEVER hit Sentry. Every
# pattern here represents a class of "expected noise" we explicitly
# chose to swallow — not a bug class we're hiding. If a real regression
# surfaces as a new variant of one of these, grep the list first.
_SENTRY_NOISE_PATTERNS = (
    # yfinance: ticker 404s and "delisted" warnings. These fire routinely
    # for invalid tickers that bots/crawlers hit via /api/og/{ticker} and
    # for BSE-only symbols (*-X, *-E series) that Yahoo doesn't index.
    # They're bubbling up from inside service.get_full_analysis() — the
    # outer try/except in the route returns a fallback, but the logged
    # ERROR from yfinance still triggers Sentry via LoggingIntegration.
    "possibly delisted; no price data found",
    "Quote not found for symbol:",
    "No data found, symbol may be delisted",
    # yfinance curl_cffi cookie jar race — concurrent requests writing to
    # the same _cookieschema.strategy row. Harmless; retry succeeds.
    "UNIQUE constraint failed: _cookieschema.strategy",
    # yfinance internal SQLite tz-cache lock. yfinance/base.py:190 logs
    # `Failed to get ticker '<TKR>' reason: database is locked` at ERROR
    # whenever multiple workers race on the shared peewee tz cache file
    # (~/.cache/py-yfinance/tkr-tz.db). 27 events/24h on HDFCBANK alone
    # in prod 2026-05-03. We've also moved the tz cache to a per-worker
    # path below (_init_yfinance_tz_cache) so this race shouldn't happen,
    # but keep the noise filter as belt-and-suspenders for any path that
    # still imports yfinance before that init runs.
    "reason: database is locked",
    # holdings lives in Supabase, migration 011 targets Neon pipeline DB
    # and always fails cleanly (ALTER on non-existent table). The portfolio
    # feature uses Supabase directly; this ALTER is a no-op that should
    # stay a no-op. Already handled by the non-critical migration path;
    # suppressing the Sentry noise for schema drift we've accepted.
    'relation "holdings" does not exist',
    # 011-related: the outer "Migration NNN failed (non-blocking)" log.
    "Migration 011_holdings_account_label.sql failed",
)


def _scrub_event(event):
    """Strip secrets from Sentry events AND drop known-benign noise.

    Two jobs:
      1. Redact accidentally-embedded secret strings (JWT_SECRET, API keys,
         DATABASE_URL) before shipping to Sentry. Cheap defence-in-depth.
      2. Return None for events matching our known-benign noise patterns
         (see _SENTRY_NOISE_PATTERNS above). Sentry treats a None return
         as "don't send this event" — stops the 80%+ of traffic that was
         yfinance 404s and schema-drift noise drowning real signal.
    """
    try:
        import re as _re
        # ── (2) noise filter — fast exit before doing anything else ──
        def _matches_noise(payload: str) -> bool:
            if not payload:
                return False
            return any(p in payload for p in _SENTRY_NOISE_PATTERNS)

        for ex in (event.get("exception", {}).get("values") or []):
            if _matches_noise(ex.get("value", "")) or _matches_noise(ex.get("type", "")):
                return None  # drop this event entirely
        msg = event.get("message") or ""
        if isinstance(msg, dict):
            msg = msg.get("formatted") or msg.get("message") or ""
        if _matches_noise(msg):
            return None
        # logentry shape (from the Logging integration)
        logentry = event.get("logentry") or {}
        if _matches_noise(logentry.get("message", "")) or _matches_noise(logentry.get("formatted", "")):
            return None

        # ── (1) secret scrubbing ──
        SECRET_NAMES = ("JWT_SECRET", "DATABASE_URL", "SUPABASE_SERVICE_KEY",
                        "SENDGRID_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
                        "FINNHUB_API_KEY", "FMP_API_KEY",
                        "RAZORPAY_KEY_SECRET", "SERVICE_WARMUP_TOKEN")
        pat = _re.compile(r"(" + "|".join(SECRET_NAMES) + r")=\S+")
        def _clean(s):
            if not isinstance(s, str):
                return s
            return pat.sub(lambda m: f"{m.group(1)}=***", s)
        for ex in (event.get("exception", {}).get("values") or []):
            if "value" in ex:
                ex["value"] = _clean(ex["value"])
        for bc in (event.get("breadcrumbs", {}).get("values") or []):
            if "message" in bc:
                bc["message"] = _clean(bc["message"])
    except Exception:
        # Scrubber crashes must never block event delivery — if we can't
        # scrub, send the raw event rather than silently dropping.
        pass
    return event


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.routers import analysis, screener, portfolio, watchlist, alerts, market, auth
from backend.routers import payments, pipeline, email, referral, admin, public, tax, concall
from backend.routers import account as account_router
from backend.routers import analytics as analytics_router
from backend.routers import notifications as notifications_router
from backend.routers import api_keys as api_keys_router
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

    # ── DISABLED 2026-04-27 — both jobs duplicated 4× per send because
    # APScheduler runs in-process inside every uvicorn worker and Railway
    # boots 4 workers. Last fire (Mon Apr 27 09:00 IST) sent 4 copies of
    # a digest containing US OTC tickers (BATMF/SBBTF/etc.) and the
    # banned phrase "Top Opportunities This Week" — SEBI risk + quality
    # disaster. Do NOT re-enable until ALL of the following are true:
    #   1. Send is moved out of in-process scheduler (GitHub Actions or
    #      APScheduler with a Postgres jobstore + distributed lock).
    #   2. Stock universe filter restricted to NSE/BSE only
    #      (ticker LIKE '%.NS' OR ticker LIKE '%.BO').
    #   3. value_score > 0 AND mos > 0 filter on the picks query.
    #   4. Email copy reviewed for SEBI compliance — remove all
    #      recommendation language ("Top Opportunities", "picks", etc.).
    #      Replace with neutral factual framing.
    #   5. Idempotency key per (user_id, send_date) so a re-fire can't
    #      double-send.
    # See backend/services/email_service.py:458 for the copy that needs
    # the rewrite.
    # scheduler.add_job(
    #     _send_weekly_digests,
    #     CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Asia/Kolkata"),
    #     id="weekly_digest",
    #     name="Weekly digest email",
    #     replace_existing=True,
    # )
    # scheduler.add_job(
    #     _send_newsletter,
    #     CronTrigger(day_of_week="sun", hour=8, minute=0, timezone="Asia/Kolkata"),
    #     id="weekly_newsletter",
    #     name="Weekly newsletter email",
    #     replace_existing=True,
    # )

    # ── Market data refreshers ─────────────────────────────────
    # Live quotes: every 5 min during market hours (Mon-Fri, 09:15-15:30 IST).
    # Cron fires */5 from 9..15 IST; the wrapper gates the exact 09:15-15:30 window.
    scheduler.add_job(
        _run_refresh_live_quotes,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone="Asia/Kolkata",
        ),
        id="market_live_quotes",
        name="Refresh live_quotes (portfolio + top-200 FV)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # FX rates: every 15 min, 24x7.
    scheduler.add_job(
        _run_refresh_fx_rates,
        CronTrigger(minute="*/15", timezone="Asia/Kolkata"),
        id="market_fx_rates",
        name="Refresh fx_rates",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Index + commodity snapshots: every 15 min, 24x7.
    scheduler.add_job(
        _run_refresh_index_snapshots,
        CronTrigger(minute="*/15", timezone="Asia/Kolkata"),
        id="market_index_snapshots",
        name="Refresh index_snapshots",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info(
        "Pipeline scheduler started: daily 4:30pm IST, weekly Sun 11pm IST, "
        "alerts every 3h, weekly digest+newsletter DISABLED (see comment), "
        "live_quotes every 5m (mkt hrs), fx+indices every 15m"
    )
    return scheduler


def _within_market_hours() -> bool:
    """True iff now() is Mon-Fri 09:15-15:30 IST."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return True  # fail-open
    if now.weekday() > 4:
        return False
    minute_of_day = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= minute_of_day <= (15 * 60 + 30)


def _run_refresh_live_quotes():
    """Refresh live_quotes for portfolio + top-200 FV tickers."""
    if not _within_market_hours():
        return
    try:
        from backend.workers.market_data_refresher import (
            collect_refresh_tickers, refresh_live_quotes,
        )
        tickers = collect_refresh_tickers(limit_fv=200)
        if not tickers:
            return
        refresh_live_quotes(tickers)
    except Exception as e:
        logger.error(f"live_quotes refresh failed: {e}")


def _run_refresh_fx_rates():
    try:
        from backend.workers.market_data_refresher import refresh_fx_rates
        refresh_fx_rates()
    except Exception as e:
        logger.error(f"fx_rates refresh failed: {e}")


def _run_refresh_index_snapshots():
    try:
        from backend.workers.market_data_refresher import refresh_index_snapshots
        refresh_index_snapshots()
    except Exception as e:
        logger.error(f"index_snapshots refresh failed: {e}")


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


def _send_newsletter():
    """Send weekly newsletter to all subscribed users."""
    try:
        from backend.services.newsletter_service import send_newsletter_to_all
        count = send_newsletter_to_all()
        logger.info(f"Newsletter job complete: {count} emails sent")
    except Exception as e:
        logger.error(f"Newsletter job failed: {e}")


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

    # Apply SQL migrations that live outside the declarative Base
    # (e.g. analysis_cache, which is managed by raw SQL so the JSONB
    # column maps cleanly and doesn't get accidentally dropped by a
    # future SQLAlchemy model rename).
    #
    # History / why this looks the way it does:
    #   The previous implementation logged every failure at WARNING
    #   with just the str(exc) — no traceback. Migration 012 was
    #   failing on every Railway boot with
    #     "sqlalchemy.cyextension.immutabledict.immutabledict is not a sequence"
    #   and nobody noticed because the single-line warning got lost in
    #   the boot spam and Sentry was configured to ignore WARNINGs.
    #
    #   Root cause of the immutabledict error: Connection.exec_driver_sql()
    #   in SQLAlchemy 2.0 can pass an immutabledict as the `parameters`
    #   argument to psycopg2's cursor.execute(). psycopg2 then tries to
    #   iterate it as a positional-parameter sequence and raises
    #   TypeError. The fix is to route parameterless DDL through
    #   Connection.execute(text(sql)) — that path never hands a bound-
    #   parameters dict to the DBAPI when the text has no placeholders.
    #
    # Policy:
    #   - Log failures at ERROR with full traceback (Sentry sees them).
    #   - Never block startup on a migration failure by default — schema
    #     drift is preferable to a crash-loop on boot. But route known
    #     schema-critical migrations through an allowlist that bubbles
    #     and halts startup (set _CRITICAL_MIGRATIONS below when/if we
    #     ever have a migration that MUST succeed).
    #   - Known-safe-to-ignore error substrings stay at WARNING without
    #     traceback so they don't create Sentry noise on every boot.
    _KNOWN_NOISE_SUBSTRINGS: tuple[str, ...] = (
        # Postgres idempotency chatter — these happen because our
        # migrations use IF NOT EXISTS / ON CONFLICT so re-runs are
        # already no-ops at the SQL level. If psycopg2 ever does raise
        # these it's not a real failure.
        "already exists",
        "duplicate column",
        "duplicate_object",
    )
    _CRITICAL_MIGRATIONS: frozenset[str] = frozenset({
        # Add filenames here if a migration must succeed to keep the app
        # functional. Empty today — all current migrations are defensive/
        # additive and safe to skip (the downstream code already null-
        # checks the columns they add).
    })

    try:
        from pathlib import Path as _Path
        from data_pipeline.db import engine as _eng
        if _eng is None:
            return
        _mig_dir = _Path(__file__).resolve().parent.parent / "data_pipeline" / "migrations"
        if not _mig_dir.exists():
            return
        for _f in sorted(_mig_dir.glob("*.sql")):
            _sql = _f.read_text(encoding="utf-8")
            # Migrations wrap their own BEGIN/COMMIT, so strip those and
            # let SQLAlchemy's transaction own it.
            _cleaned = "\n".join(
                line for line in _sql.splitlines()
                if line.strip().upper() not in ("BEGIN;", "COMMIT;")
            ).strip()
            if not _cleaned:
                continue
            try:
                # Go through the raw DBAPI cursor instead of
                # Connection.exec_driver_sql(). exec_driver_sql() in
                # SQLAlchemy 2.0 can hand an immutabledict to psycopg2
                # as the parameters argument, and psycopg2 then tries
                # to iterate it as a positional sequence and raises:
                #     TypeError: ...immutabledict is not a sequence
                # The raw cursor.execute(sql) path accepts multi-statement
                # DDL scripts (including DO $$ ... $$ blocks in some of
                # the later migrations) without SQLAlchemy interposing
                # parameter binding at all.
                _raw = _eng.raw_connection()
                try:
                    _cur = _raw.cursor()
                    try:
                        _cur.execute(_cleaned)
                        _raw.commit()
                    except Exception:
                        try:
                            _raw.rollback()
                        except Exception:
                            pass
                        raise
                    finally:
                        _cur.close()
                finally:
                    _raw.close()
                logger.info("Migration applied/verified: %s", _f.name)
            except Exception as _me:
                _err_str = str(_me).lower()
                _is_noise = any(s in _err_str for s in _KNOWN_NOISE_SUBSTRINGS)
                if _f.name in _CRITICAL_MIGRATIONS and not _is_noise:
                    # Schema-critical: halt boot so ops notices and
                    # doesn't silently serve a broken schema.
                    logger.error(
                        "CRITICAL migration %s failed — aborting startup",
                        _f.name, exc_info=True,
                    )
                    raise
                if _is_noise:
                    logger.warning(
                        "Migration %s skipped (benign — %s)",
                        _f.name, _me,
                    )
                else:
                    # Non-critical but unexpected: ERROR + traceback so
                    # Sentry captures it and ops sees schema drift as it
                    # happens instead of months later.
                    logger.error(
                        "Migration %s failed (non-blocking) — schema drift possible",
                        _f.name, exc_info=True,
                    )
    except Exception as e:
        # Outer guard for the runner itself (Path/glob/engine init bugs).
        # Still non-blocking but logged loudly.
        logger.error("Migration runner aborted: %s", e, exc_info=True)


def _prewarm_popular_stocks():
    """
    DISABLED — user-driven cache-on-read is sufficient.

    History: this function was repeatedly saturating Railway's single
    web worker. Every time it ran a Phase 2 + Phase 3 prewarm, users
    experienced 8-15 second response times (including /health) because
    the synchronous DCF compute blocked the worker for 7+ minutes per
    boot cycle. Killed via redeploy 3+ times on 17-Apr.

    Correct architecture:
      - Cache TTL is 24h (bumped earlier today) so a single user hit
        warms a ticker for the whole day.
      - OG scrapers + organic traffic populate cache naturally.
      - Full-universe data freshness is handled by the GitHub Actions
        fundamentals_backfill workflow which runs off-Railway.
      - If we later get a multi-worker Railway plan, this can be
        re-enabled selectively for the top-5-10 most-trafficked tickers.

    Leaving the function as a no-op so the call site at lifespan()
    doesn't need to change.
    """
    logger.info("Prewarm disabled (see docstring): relying on user-driven + GH backfill")
    return

    # Old implementation below — never executed but preserved for reference
    import threading

    def _warm():  # pragma: no cover
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
                        cache.set(_key, result, ttl=86400)
                        warmed += 1
                    except Exception:
                        pass
                    time.sleep(1)
            logger.info(f"Prewarm phase 2: {warmed} tickers cached")

            # ── Phase 3: Background refresh NSE_UNIVERSE (~100) ──
            # Cycle only the curated NSE universe (not every parquet).
            # Previous version cycled ~500 tickers with 1s sleep, which
            # saturated the single Railway worker and caused user
            # requests to queue (8-11s latency while the cycle was
            # active). New version: smaller list + 10s sleep between
            # computes so user requests get ~90% worker availability.
            # Keep prewarm SMALL (NSE_UNIVERSE ~98 only) because the
            # Railway worker is single-threaded. Cycling 550 tickers
            # saturates it for ~2.5 hours per cycle and blocks user
            # requests (observed 17-Apr: /health timing out at 15s).
            # The full-universe backfill runs on GitHub Actions where
            # it can't impact users — that's where "all 550" work
            # belongs. Prewarm stays small + hot.
            try:
                from data_pipeline.pipeline import NSE_UNIVERSE
                cycle_tickers = [f"{t}.NS" for t in NSE_UNIVERSE]
            except Exception:
                cycle_tickers = []
            logger.info(f"Background refresh: cycling {len(cycle_tickers)} NSE_UNIVERSE tickers (worker-safe)")

            while True:
                for ticker in cycle_tickers:
                    _key = f"analysis:{ticker}"
                    if cache.get(_key) is None:
                        try:
                            result = svc.get_full_analysis(ticker)
                            cache.set(_key, result, ttl=86400)
                        except Exception:
                            pass
                        time.sleep(10)  # heavy throttle to stay off user path
                    else:
                        time.sleep(0.5)  # cached -> cheap skip
                logger.info("Background refresh: full cycle complete")
                time.sleep(300)  # 5 min rest between cycles

        except Exception as e:
            logger.warning(f"Cache pre-warm failed: {e}")

    threading.Thread(target=_warm, daemon=True).start()


def _auto_refresh_parquets_if_needed():
    """
    One-shot post-deploy price refresh. Runs once per container boot.
    Re-downloads parquets for the Nifty-50 core so bug fixes in
    yf_downloader (auto_adjust flip, live-quote override, etc.) take
    effect without requiring an admin to curl the refresh endpoint.

    Idempotent: a second call within the same container does nothing
    (sentinel var on the function itself).

    Gated by env var AUTO_REFRESH_PARQUETS (default "1"); set to "0"
    to disable on a specific deploy.
    """
    if getattr(_auto_refresh_parquets_if_needed, "_done", False):
        return
    _auto_refresh_parquets_if_needed._done = True
    if os.getenv("AUTO_REFRESH_PARQUETS", "1") != "1":
        logger.info("AUTO_REFRESH_PARQUETS disabled by env var")
        return

    def _refresh():
        try:
            from data_pipeline.nse_prices.yf_downloader import download_ticker
            from backend.services.cache_service import cache, CACHE_VERSION
            tickers = [
                "HDFCBANK", "RELIANCE", "TCS", "INFY", "ITC", "ICICIBANK",
                "SBIN", "KOTAKBANK", "AXISBANK", "LT", "BAJFINANCE", "MARUTI",
                "TITAN", "NESTLEIND", "WIPRO", "HCLTECH", "SUNPHARMA",
                "ASIANPAINT", "ULTRACEMCO", "BHARTIARTL", "POWERGRID", "NTPC",
                "HINDUNILVR",
            ]
            logger.info(
                "AUTO_REFRESH: starting parquet refresh for %d tickers "
                "(CACHE_VERSION=%d)", len(tickers), CACHE_VERSION,
            )
            ok, fail = 0, 0
            for t in tickers:
                try:
                    p = download_ticker(t, period="5y")
                    if p:
                        ok += 1
                        # Clear dependent caches so next read recomputes
                        for prefix in ["analysis:", "og:", "preview:",
                                       "chart_data:", "public:stock-summary:"]:
                            cache.clear_pattern(f"{prefix}{t}.NS")
                    else:
                        fail += 1
                except Exception as _exc:
                    fail += 1
                    logger.warning("AUTO_REFRESH: %s failed: %s", t, _exc)
            logger.info(
                "AUTO_REFRESH: done — %d ok, %d failed", ok, fail,
            )
        except Exception as e:
            logger.warning("AUTO_REFRESH: aborted: %s", e)

    import threading
    threading.Thread(target=_refresh, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — starts scheduler + pre-warms cache.
    Table creation and prewarm run in background threads so the
    /health endpoint responds immediately for Railway healthcheck."""
    import threading
    threading.Thread(target=_ensure_pipeline_tables, daemon=True).start()

    # Screener column-mapping self-test. If SCREENER_FIELD_MAP has drifted
    # from the live PG schema (the 2026-04-25 incident: pe_ratio mapped
    # to rh.pe_ratio when the latest_ratio CTE only projected ROE/ROCE/D-E),
    # log a SCREENER_SCHEMA_DRIFT line at ERROR so it shows up in Railway
    # logs and Sentry. Runs in a background thread so it can't block the
    # /health endpoint Railway uses for healthcheck.
    def _screener_self_test() -> None:
        try:
            dsn = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
            if not dsn:
                return
            from backend.routers.public import validate_screener_column_mapping
            failures = validate_screener_column_mapping(dsn)
            if failures:
                for f in failures:
                    logger.error("SCREENER_SCHEMA_DRIFT %s", f)
        except Exception as exc:  # never raise from startup hook
            logger.error("SCREENER_SCHEMA_DRIFT self-test crashed: %r", exc)

    threading.Thread(target=_screener_self_test, daemon=True).start()

    sched = _start_pipeline_scheduler()
    _prewarm_popular_stocks()
    _auto_refresh_parquets_if_needed()
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
    # Custom response headers have to be whitelisted here or the browser
    # strips them from JS-visible headers.
    #   - X-Cache: hit memory/DB cache vs. computed fresh (debug + obs).
    #   - X-Analyses-Today / X-Analyses-Limit: usage counter for the
    #     free-tier rate limiter. Surfaced from `check_analysis_limit`
    #     so the frontend auth store can update in lock-step with the
    #     backend after every /analysis/:ticker call, without a second
    #     round-trip to /auth/me.
    expose_headers=["X-Cache", "X-Analyses-Today", "X-Analyses-Limit"],
)

# ── GZip compression ─────────────────────────────────────────
# Compress responses larger than 1KB. Big wins on the Prism /
# analysis / index-dashboard payloads (20-200 KB JSON) which
# typically compress 4-8x. Must be added AFTER CORSMiddleware
# so ASGI composes them in the right order (CORS outermost).
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── CORS on 500 responses ─────────────────────────────────────
# FastAPI's default 500 handler emits a plain response without CORS
# headers, because the built-in ServerErrorMiddleware runs inside the
# CORS middleware boundary. The result: users hitting a genuine 500
# from the frontend see a CORS error in their browser console
# ("No 'Access-Control-Allow-Origin' header") instead of a clean
# "something went wrong" from our API — making real bugs look like
# connectivity issues. The Sentry event still lands, but the UX is
# broken.
#
# Fix: register an explicit exception handler that always returns a
# JSONResponse with the CORS headers reconstructed from the request's
# Origin header. The exception has already been captured by Sentry
# (its integration hooks earlier in the ASGI stack) so we don't
# lose observability.
from fastapi import Request
from fastapi.responses import JSONResponse


def _cors_headers_for(request: Request) -> dict:
    origin = request.headers.get("origin", "")
    from backend.middleware.cors import ALLOWED_ORIGIN_REGEX as _re
    import re as _re_mod
    allowed = origin and (origin in ALLOWED_ORIGINS
                          or (_re and _re_mod.match(_re, origin)))
    if not allowed:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort 500 handler that preserves CORS headers.

    CRITICAL: must NOT swallow HTTPException — FastAPI raises those
    for legitimate 401/404/429/etc. and has its own handler that
    converts them to the right status code. If we catch them here,
    every 404 becomes a misleading 500 and the frontend shows
    "Analysis unavailable" instead of "Ticker not found". Re-raise
    so FastAPI's built-in handler takes over.
    """
    from fastapi import HTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        raise exc

    import logging as _el
    _el.getLogger("yieldiq.api").exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=_cors_headers_for(request),
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
app.include_router(admin.debug_router)
app.include_router(public.router)
app.include_router(analytics_router.router)
app.include_router(tax.router)
app.include_router(concall.router)
app.include_router(account_router.router)
app.include_router(notifications_router.router)
app.include_router(api_keys_router.router)
from backend.routers import hex as hex_router
app.include_router(hex_router.router)
from backend.routers import prism as prism_router
app.include_router(prism_router.router)
from backend.routers import strategies as strategies_router
app.include_router(strategies_router.router)
from backend.routers import sectors as sectors_router
app.include_router(sectors_router.router)


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
