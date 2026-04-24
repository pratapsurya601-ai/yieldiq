#!/usr/bin/env python3
"""Re-ingest ONLY the historical-financials phase for one or more tickers.

Context (2026-04-25 LTIM bug): `fetch_and_store_yfinance` used to bail on
`return False` when `info["regularMarketPrice"]` was None, silently dropping
historical financials ingest for tickers with a temporary price-feed glitch.
The ingest path was refactored into three independently-gated phases. This
script runs ONLY the `_persist_historical_financials` phase so we can clean
up the already-affected tickers without a full-pipeline re-run.

Idempotent: existing rows are updated in place (`existing_fin` branch inside
`_persist_historical_financials`); new rows are inserted. Running this
script repeatedly for the same ticker is safe.

Usage:

    # Windows (miniconda python)
    $env:DATABASE_URL = "<neon uri>"
    python scripts/reingest_financials_only.py LTIM

    # Multiple tickers
    python scripts/reingest_financials_only.py LTIM KPITTECH PERSISTENT

    # All active tickers without `financials` rows in the last 12 months
    python scripts/reingest_financials_only.py --stale

The --stale mode targets exactly the bug class: tickers in `stocks` with
`is_active=true` that have zero annual `financials` rows where
`period_end >= today - 365 days`. Useful for the initial clean-up sweep.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Make the repo root importable so `data_pipeline.*` resolves.
sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from data_pipeline.sources.yfinance_supplement import (  # noqa: E402
    _persist_historical_financials,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reingest_financials_only")


def _make_session():
    db_url = os.environ["DATABASE_URL"]
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    engine = create_engine(db_url, pool_recycle=300, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine)


def _stale_tickers(engine) -> list[str]:
    """Active tickers with zero annual financials rows in the last 12 months."""
    cutoff = date.today() - timedelta(days=365)
    sql = text(
        """
        SELECT s.ticker
        FROM stocks s
        WHERE s.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM financials f
              WHERE f.ticker = s.ticker
                AND f.period_type = 'annual'
                AND f.period_end >= :cutoff
          )
        ORDER BY s.ticker
        """
    )
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(sql, {"cutoff": cutoff})]


def reingest_one(ticker: str, db) -> bool:
    """Run ONLY the historical-financials phase for one ticker.

    Returns True iff `_persist_historical_financials` wrote or updated at
    least one row.
    """
    ticker_ns = f"{ticker}.NS"
    try:
        stock = yf.Ticker(ticker_ns)
        try:
            info = stock.info or {}
        except Exception:
            info = {}
        ok = _persist_historical_financials(ticker, stock, info, db)
        if ok:
            logger.info("ticker=%s financials=ok", ticker)
        else:
            logger.warning("ticker=%s financials=failed", ticker)
        return ok
    except Exception as e:
        logger.error(
            "ticker=%s reingest failed: %s: %s",
            ticker, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="Tickers to reingest")
    parser.add_argument(
        "--stale",
        action="store_true",
        help="Reingest all active tickers without annual financials rows in the last 12 months",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to sleep between tickers (yfinance rate-limit guard)",
    )
    args = parser.parse_args()

    if not args.tickers and not args.stale:
        parser.error("provide at least one ticker or --stale")

    engine, Session = _make_session()

    targets: list[str] = list(args.tickers)
    if args.stale:
        stale = _stale_tickers(engine)
        logger.info("found %d stale tickers via --stale", len(stale))
        # De-dup while preserving order
        seen = set(targets)
        for t in stale:
            if t not in seen:
                targets.append(t)
                seen.add(t)

    logger.info("reingesting %d tickers", len(targets))

    db = Session()
    ok_count = 0
    fail_count = 0
    try:
        for i, ticker in enumerate(targets, start=1):
            if reingest_one(ticker, db):
                ok_count += 1
            else:
                fail_count += 1
            if i < len(targets):
                time.sleep(args.sleep)
            if i % 50 == 0:
                logger.info("progress: %d/%d (ok=%d fail=%d)", i, len(targets), ok_count, fail_count)
    finally:
        db.close()

    logger.info("DONE: ok=%d fail=%d total=%d", ok_count, fail_count, len(targets))
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
