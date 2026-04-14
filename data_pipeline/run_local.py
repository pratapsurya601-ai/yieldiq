#!/usr/bin/env python3
"""
data_pipeline/run_local.py
Run the India data pipeline from YOUR LOCAL MACHINE.

Your PC has an Indian residential IP — NSE/BSE won't block it.
This script connects to Railway's PostgreSQL and populates all data
using official NSE Bhavcopy, BSE XBRL, and NSE Shareholding sources.

USAGE:
  1. Copy DATABASE_URL from Railway Postgres → Variables → DATABASE_PUBLIC_URL
  2. Run:
     python data_pipeline/run_local.py --db "postgresql://postgres:xxxx@xxx.proxy.rlwy.net:xxxxx/railway"

  Or set as environment variable:
     set DATABASE_URL=postgresql://postgres:xxxx@xxx.proxy.rlwy.net:xxxxx/railway
     python data_pipeline/run_local.py

  Options:
     --prices-only     Only download NSE Bhavcopy prices (fastest)
     --fundamentals    Only download yfinance fundamentals
     --shareholding    Only download NSE shareholding
     --corporate       Only download NSE corporate actions
     --rbi             Only download RBI risk-free rate
     --full            Run everything (default)
     --days 365        How many days of price history (default: 1095 = 3 years)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("local_pipeline")


def main():
    parser = argparse.ArgumentParser(description="YieldIQ India Data Pipeline — Local Runner")
    parser.add_argument("--db", type=str, help="Railway DATABASE_PUBLIC_URL")
    parser.add_argument("--prices-only", action="store_true", help="Only NSE Bhavcopy prices")
    parser.add_argument("--fundamentals", action="store_true", help="Only yfinance fundamentals")
    parser.add_argument("--shareholding", action="store_true", help="Only NSE shareholding")
    parser.add_argument("--corporate", action="store_true", help="Only NSE corporate actions")
    parser.add_argument("--rbi", action="store_true", help="Only RBI risk-free rate")
    parser.add_argument("--earnings", action="store_true", help="Only NSE earnings dates")
    parser.add_argument("--full", action="store_true", help="Run everything (default)")
    parser.add_argument("--days", type=int, default=1095, help="Days of price history (default: 1095)")
    args = parser.parse_args()

    # Set DATABASE_URL
    db_url = args.db or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: Provide --db URL or set DATABASE_URL environment variable.")
        print("Copy DATABASE_PUBLIC_URL from Railway Postgres → Variables tab.")
        print('Example: python data_pipeline/run_local.py --db "postgresql://postgres:xxx@xxx.proxy.rlwy.net:12345/railway"')
        sys.exit(1)

    os.environ["DATABASE_URL"] = db_url

    # Now import pipeline modules (they read DATABASE_URL on import)
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from data_pipeline.models import Base

    engine = create_engine(
        db_url,
        pool_recycle=300,        # Recycle connections every 5 min
        pool_pre_ping=True,      # Test connection before using
        pool_size=2,
        max_overflow=3,
    )
    Session = sessionmaker(bind=engine)

    # Test connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connected to Railway PostgreSQL")
    except Exception as e:
        print(f"ERROR: Cannot connect to database: {e}")
        print("Make sure you're using DATABASE_PUBLIC_URL (with proxy.rlwy.net), not the internal one.")
        sys.exit(1)

    # Create tables if they don't exist
    Base.metadata.create_all(engine)
    logger.info("Database tables verified")

    db = Session()

    # Determine what to run
    run_all = args.full or not any([
        args.prices_only, args.fundamentals, args.shareholding,
        args.corporate, args.rbi, args.earnings,
    ])

    try:
        # ── Step 1: Populate stocks master table ──────────────────
        if run_all:
            logger.info("=" * 60)
            logger.info("Step 0: Populating stocks master table from NSE equity list")
            logger.info("=" * 60)
            from data_pipeline.isin_loader import build_isin_map, populate_stocks_table
            count = populate_stocks_table(db)
            logger.info(f"Loaded {count} stocks into master table")
            isin_map = build_isin_map()
            logger.info(f"Built ISIN map: {len(isin_map)} entries")

        # ── Step 2: NSE Bhavcopy prices ───────────────────────────
        if run_all or args.prices_only:
            logger.info("=" * 60)
            logger.info(f"Step 1: NSE Bhavcopy — {args.days} days of price history")
            logger.info("=" * 60)
            from data_pipeline.sources.nse_bhavcopy import backfill_history
            total = backfill_history(db, days=args.days)
            logger.info(f"NSE Bhavcopy: {total} price records stored")

        # ── Step 3: NSE Corporate Actions ─────────────────────────
        if run_all or args.corporate:
            logger.info("=" * 60)
            logger.info("Step 2: NSE Corporate Actions (splits, bonuses, dividends)")
            logger.info("=" * 60)
            from data_pipeline.sources.nse_bhavcopy import download_corporate_actions
            count = download_corporate_actions(db)
            logger.info(f"Corporate actions: {count} records")

        # ── Step 4: NSE Shareholding Pattern ──────────────────────
        if run_all or args.shareholding:
            logger.info("=" * 60)
            logger.info("Step 3: NSE Shareholding Pattern (last 5 quarters)")
            logger.info("=" * 60)
            from datetime import date
            from data_pipeline.sources.nse_shareholding import download_bulk_shareholding
            current_year = date.today().year
            for quarter in [1, 2, 3, 4]:
                download_bulk_shareholding(current_year - 1, quarter, db)
            for quarter in range(1, (date.today().month - 1) // 3 + 2):
                download_bulk_shareholding(current_year, quarter, db)

        # ── Step 5: BSE XBRL Financials ───────────────────────────
        if run_all:
            logger.info("=" * 60)
            logger.info("Step 4: BSE XBRL Financials")
            logger.info("=" * 60)
            from data_pipeline.sources.bse_xbrl import batch_update_financials
            from data_pipeline.pipeline import NSE_UNIVERSE
            if 'isin_map' in dir() and isin_map:
                success, failed = batch_update_financials(db, NSE_UNIVERSE, isin_map)
                logger.info(f"BSE XBRL: {success} success, {failed} failed")
            else:
                logger.warning("No ISIN map — skipping BSE XBRL (run --full to include)")

        # ── Step 6: yfinance Fundamentals ─────────────────────────
        if run_all or args.fundamentals:
            logger.info("=" * 60)
            logger.info("Step 5: yfinance Fundamentals (financials + market metrics)")
            logger.info("=" * 60)
            from data_pipeline.pipeline import NSE_UNIVERSE
            from data_pipeline.sources.yfinance_supplement import batch_fetch_fundamentals
            success, failed = batch_fetch_fundamentals(NSE_UNIVERSE, db)
            logger.info(f"Fundamentals: {success} ok, {failed} failed")

        # ── Step 7: RBI Risk-Free Rate ────────────────────────────
        if run_all or args.rbi:
            logger.info("=" * 60)
            logger.info("Step 6: RBI 10-year G-Sec yield")
            logger.info("=" * 60)
            try:
                from data_pipeline.sources.rbi_rate import fetch_rbi_gsec_yield
                fetch_rbi_gsec_yield(db)
            except ImportError:
                logger.warning("RBI rate module not available yet")

        # ── Step 8: NSE Earnings Dates ────────────────────────────
        if run_all or args.earnings:
            logger.info("=" * 60)
            logger.info("Step 7: NSE Upcoming Earnings Dates")
            logger.info("=" * 60)
            try:
                from data_pipeline.sources.nse_earnings import fetch_earnings_dates
                count = fetch_earnings_dates(db)
                logger.info(f"Earnings dates: {count} records")
            except ImportError:
                logger.warning("NSE earnings module not available yet")

        logger.info("=" * 60)
        logger.info("ALL DONE!")
        logger.info("=" * 60)

        # Print summary
        from data_pipeline.models import DailyPrice, Financials, Stock, ShareholdingPattern, MarketMetrics
        print(f"\nStocks:        {db.query(Stock).count()}")
        print(f"Price records: {db.query(DailyPrice).count()}")
        print(f"Financials:    {db.query(Financials).count()}")
        print(f"Shareholding:  {db.query(ShareholdingPattern).count()}")
        print(f"Market metrics:{db.query(MarketMetrics).count()}")

    except KeyboardInterrupt:
        logger.info("Interrupted by user — data saved so far is safe")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
