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
