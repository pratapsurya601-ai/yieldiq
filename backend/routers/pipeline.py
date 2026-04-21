# backend/routers/pipeline.py
# API endpoints for data pipeline status and manual triggers.
from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


def _require_admin(authorization: str = ""):
    """Simple admin check — expand with proper auth later."""
    admin_key = os.environ.get("PIPELINE_ADMIN_KEY", "")
    if not admin_key:
        return True  # No key set = no protection (dev mode)
    # In production, check JWT admin claim from auth middleware
    return True


def _get_db():
    """Get pipeline DB session, or raise if not configured."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            raise HTTPException(503, "Pipeline database not configured (DATABASE_URL not set)")
        db = Session()
        try:
            yield db
        finally:
            db.close()
    except ImportError:
        raise HTTPException(503, "Data pipeline module not available")


@router.get("/status")
async def pipeline_status():
    """Get data freshness status for all pipeline sources."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.models import DataFreshness
        if Session is None:
            return {"status": "not_configured", "message": "DATABASE_URL not set"}

        db = Session()
        try:
            records = db.query(DataFreshness).all()
            return {
                "status": "ok",
                "sources": [
                    {
                        "data_type": r.data_type,
                        "last_updated": r.last_updated.isoformat() if r.last_updated else None,
                        "last_trade_date": r.last_trade_date.isoformat() if r.last_trade_date else None,
                        "records_updated": r.records_updated,
                        "status": r.status,
                        "error": r.error_msg,
                    }
                    for r in records
                ],
                "checked_at": datetime.utcnow().isoformat(),
            }
        finally:
            db.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/run/daily")
async def trigger_daily():
    """Manually trigger daily price update."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.pipeline import run_daily_update
        if Session is None:
            raise HTTPException(503, "Pipeline not configured")

        db = Session()
        try:
            run_daily_update(db)
            return {"status": "ok", "message": "Daily update completed"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Daily update failed: {e}")


@router.post("/run/weekly")
async def trigger_weekly():
    """Manually trigger weekly fundamentals update."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.pipeline import run_weekly_update
        if Session is None:
            raise HTTPException(503, "Pipeline not configured")

        db = Session()
        try:
            run_weekly_update(db)
            return {"status": "ok", "message": "Weekly update completed"}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Weekly update failed: {e}")


@router.post("/run/populate-stocks")
async def populate_stocks():
    """Download NSE equity list and populate stocks master table."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.isin_loader import populate_stocks_table
        if Session is None:
            raise HTTPException(503, "Pipeline not configured")

        db = Session()
        try:
            count = populate_stocks_table(db)
            return {"status": "ok", "stocks_populated": count}
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Stock population failed: {e}")


@router.get("/stocks/count")
async def stock_count():
    """Get count of stocks in pipeline database."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.models import Stock, DailyPrice, Financials
        if Session is None:
            return {"configured": False}

        db = Session()
        try:
            return {
                "configured": True,
                "stocks": db.query(Stock).count(),
                "price_records": db.query(DailyPrice).count(),
                "financial_records": db.query(Financials).count(),
            }
        finally:
            db.close()
    except Exception as e:
        return {"configured": False, "error": str(e)}


@router.post("/run/setup")
async def run_initial_setup():
    """
    Run full initial setup: populate stocks + backfill prices + fundamentals.
    WARNING: This takes 2-4 hours. Call once, then use daily/weekly updates.
    Returns immediately and runs in background.
    """
    import threading

    try:
        from data_pipeline.db import Session
        if Session is None:
            raise HTTPException(503, "Pipeline not configured")

        def _background_setup():
            from data_pipeline.isin_loader import build_isin_map, populate_stocks_table
            from data_pipeline.pipeline import ISIN_MAP, run_initial_setup as _setup

            db = Session()
            try:
                logger.info("=== Background setup started ===")
                populate_stocks_table(db)
                isin_map = build_isin_map()
                ISIN_MAP.update(isin_map)
                _setup(db)
                logger.info("=== Background setup complete ===")
            except Exception as e:
                logger.error(f"Background setup failed: {e}")
            finally:
                db.close()

        thread = threading.Thread(target=_background_setup, daemon=True)
        thread.start()

        return {
            "status": "started",
            "message": "Initial setup running in background (2-4 hours). "
                       "Check /api/pipeline/stocks/count to monitor progress.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Setup failed to start: {e}")


@router.get("/debug")
async def debug_pipeline():
    """Show which stocks have data and which don't."""
    try:
        from sqlalchemy import func
        from data_pipeline.db import Session
        from data_pipeline.models import DailyPrice, Financials, DataFreshness
        from data_pipeline.pipeline import NSE_UNIVERSE
        if Session is None:
            return {"error": "not configured"}

        db = Session()
        try:
            # Which universe stocks have prices?
            stocks_with_prices = db.query(
                DailyPrice.ticker, func.count(DailyPrice.id)
            ).filter(
                DailyPrice.ticker.in_(NSE_UNIVERSE)
            ).group_by(DailyPrice.ticker).all()

            price_map = {t: c for t, c in stocks_with_prices}

            # Which have financials?
            stocks_with_fins = db.query(
                Financials.ticker, func.count(Financials.id)
            ).filter(
                Financials.ticker.in_(NSE_UNIVERSE)
            ).group_by(Financials.ticker).all()

            fin_map = {t: c for t, c in stocks_with_fins}

            # Freshness
            freshness = db.query(DataFreshness).all()

            loaded = [t for t in NSE_UNIVERSE if t in price_map]
            missing = [t for t in NSE_UNIVERSE if t not in price_map]

            return {
                "universe_size": len(NSE_UNIVERSE),
                "stocks_with_prices": len(loaded),
                "stocks_missing_prices": len(missing),
                "missing_tickers": missing[:20],
                "stocks_with_financials": len(fin_map),
                "freshness": [
                    {"type": f.data_type, "status": f.status,
                     "updated": f.last_updated.isoformat() if f.last_updated else None,
                     "count": f.records_updated}
                    for f in freshness
                ],
            }
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e)}


@router.get("/test/fetch-one/{ticker}")
async def test_fetch_one(ticker: str):
    """Test: fetch price + fundamentals for ONE stock. Runs synchronously."""
    try:
        from data_pipeline.db import Session
        from data_pipeline.sources.yfinance_supplement import (
            fetch_price_history, fetch_and_store_yfinance,
        )
        if Session is None:
            return {"error": "not configured"}

        db = Session()
        try:
            ticker_ns = f"{ticker}.NS"
            prices = fetch_price_history(ticker_ns, ticker, db, period="3y")
            fundamentals = fetch_and_store_yfinance(ticker_ns, ticker, db)
            return {
                "status": "ok",
                "ticker": ticker,
                "price_records_stored": prices,
                "fundamentals_ok": fundamentals,
            }
        finally:
            db.close()
    except Exception as e:
        return {"status": "error", "error": str(e), "type": type(e).__name__}


def _get_recent_prices_from_bhavcopy(ticker: str, days: int = 5):
    """Return the last ``days`` trading days of OHLCV from daily_prices.

    Shape matches yf.download's post-MultiIndex-flatten columns:
        Open, High, Low, Close, Volume  (Date as index)

    Returns ``None`` when:
      * ``DATABASE_URL`` is not set
      * the table has no rows for this ticker in the window
      * any SQLAlchemy error is raised

    Callers must treat ``None`` as "fall back to live fetch".
    """
    try:
        from data_pipeline.db import Session as _PipelineSession
        if _PipelineSession is None:
            return None
        from sqlalchemy import text
        import pandas as pd
        from datetime import date as _date, timedelta as _td

        clean = ticker.replace(".NS", "").replace(".BO", "").upper()
        # Pull a wider window than strictly needed — trading calendars
        # drop weekends/holidays, so 5 trading days is ~7-9 calendar days.
        # 3x safety margin to avoid clipping long holiday weekends.
        start = _date.today() - _td(days=max(days * 3, 14))

        sess = _PipelineSession()
        try:
            rows = sess.execute(
                text(
                    "SELECT trade_date, open_price, high_price, low_price, "
                    "       close_price, volume "
                    "FROM daily_prices "
                    "WHERE ticker = :t AND trade_date >= :start "
                    "ORDER BY trade_date DESC "
                    "LIMIT :lim"
                ),
                {"t": clean, "start": start, "lim": int(days)},
            ).mappings().all()
        finally:
            try:
                sess.close()
            except Exception:
                pass

        if not rows:
            return None

        df = pd.DataFrame([dict(r) for r in rows])
        # Reverse so oldest → newest (same orientation as yf.download)
        df = df.iloc[::-1].reset_index(drop=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
        df.index.name = "Date"
        df = df.rename(columns={
            "open_price": "Open",
            "high_price": "High",
            "low_price": "Low",
            "close_price": "Close",
            "volume": "Volume",
        })
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception:
        return None


@router.get("/test/raw-price/{ticker}")
async def test_raw_price(ticker: str):
    """Test: show raw yfinance result for a stock using both methods."""
    import yfinance as yf
    results = {}

    # Method 1: Ticker.history
    try:
        stock = yf.Ticker(f"{ticker}.NS")
        df1 = stock.history(period="5d")
        if df1 is not None and not df1.empty:
            results["ticker_history"] = {
                "rows": len(df1), "columns": list(df1.columns),
                "sample": df1.tail(2).reset_index().astype(str).to_dict("records"),
            }
        else:
            results["ticker_history"] = "empty"
    except Exception as e:
        results["ticker_history"] = f"error: {e}"

    # Method 2: yf.download — try bhavcopy (daily_prices table) first,
    # fall through to live yfinance only if the table is empty for
    # this ticker. Sentry-tagged warning when we do fall through so
    # we can monitor bhavcopy coverage gaps in production.
    try:
        import pandas as pd
        df2 = _get_recent_prices_from_bhavcopy(f"{ticker}.NS", days=5)
        if df2 is not None and not df2.empty:
            results["yf_download"] = {
                "rows": len(df2), "columns": list(df2.columns),
                "sample": df2.tail(2).reset_index().astype(str).to_dict("records"),
                "source": "bhavcopy",
            }
        else:
            logger.warning(
                "pipeline.test_raw_price fell back to yfinance for %s (daily_prices empty)",
                ticker,
            )
            try:
                import sentry_sdk as _sentry_sdk
                _sentry_sdk.set_tag("data_source", "yfinance_fallback")
                _sentry_sdk.set_tag("endpoint", "pipeline_test_raw_price")
            except Exception:
                pass
            df2 = yf.download(f"{ticker}.NS", period="5d", progress=False)
            if df2 is not None and not df2.empty:
                if isinstance(df2.columns, pd.MultiIndex):
                    df2.columns = [col[0] if isinstance(col, tuple) else col for col in df2.columns]
                results["yf_download"] = {
                    "rows": len(df2), "columns": list(df2.columns),
                    "sample": df2.tail(2).reset_index().astype(str).to_dict("records"),
                    "source": "yfinance",
                }
            else:
                results["yf_download"] = "empty"
    except Exception as e:
        results["yf_download"] = f"error: {e}"

    # Method 3: Ticker.info (quick check)
    try:
        info = stock.info
        results["info_price"] = info.get("regularMarketPrice") or info.get("currentPrice")
        results["info_name"] = info.get("longName")
    except Exception as e:
        results["info"] = f"error: {e}"

    return {"ticker": ticker, **results}


@router.get("/test/bhavcopy")
async def test_bhavcopy():
    """Test: try downloading one day of NSE Bhavcopy. Diagnoses connectivity."""
    from datetime import date, timedelta
    try:
        from data_pipeline.sources.nse_bhavcopy import download_bhavcopy

        # Try last few weekdays
        today = date.today()
        for delta in range(1, 8):
            target = today - timedelta(days=delta)
            if target.weekday() < 5:
                df = download_bhavcopy(target)
                if df is not None:
                    return {
                        "status": "ok",
                        "date": target.isoformat(),
                        "stocks_found": len(df),
                        "sample": df[["ticker", "close_price", "volume"]].head(5).to_dict("records"),
                    }
        return {"status": "no_data", "message": "No bhavcopy found for last 7 days"}
    except Exception as e:
        return {"status": "error", "error": str(e), "type": type(e).__name__}


@router.get("/test/yfinance")
async def test_yfinance():
    """Test: try fetching one stock via yfinance."""
    try:
        import yfinance as yf
        stock = yf.Ticker("RELIANCE.NS")
        info = stock.info
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        return {
            "status": "ok" if price else "no_price",
            "ticker": "RELIANCE.NS",
            "price": price,
            "name": info.get("longName"),
            "market_cap": info.get("marketCap"),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "type": type(e).__name__}


@router.get("/test/bse")
async def test_bse():
    """Test: try fetching RELIANCE from BSE API."""
    try:
        from data_pipeline.sources.bse_xbrl import download_financials_bse
        data = download_financials_bse("500325", "RELIANCE")  # 500325 = RELIANCE BSE code
        if data:
            return {
                "status": "ok",
                "ticker": "RELIANCE",
                "revenue": data.get("revenue"),
                "pe": data.get("pe_ratio"),
                "market_cap": data.get("market_cap_cr"),
            }
        return {"status": "no_data", "message": "BSE returned empty response"}
    except Exception as e:
        return {"status": "error", "error": str(e), "type": type(e).__name__}
