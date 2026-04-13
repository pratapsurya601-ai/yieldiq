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


@router.get("/test/raw-price/{ticker}")
async def test_raw_price(ticker: str):
    """Test: show raw yfinance download result for a stock."""
    try:
        import yfinance as yf
        import pandas as pd
        df = yf.download(f"{ticker}.NS", period="5d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return {"status": "empty", "ticker": ticker}

        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        return {
            "status": "ok",
            "ticker": ticker,
            "rows": len(df),
            "columns": list(df.columns),
            "sample": df.tail(3).reset_index().to_dict("records"),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
