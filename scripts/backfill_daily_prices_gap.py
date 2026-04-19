"""Fill the 2022-06-14 → 2023-04-13 gap in daily_prices via NSE bhavcopy.

Uses the existing data_pipeline.sources.nse_bhavcopy downloader to fetch
daily OHLCV files for every trading date in the gap window, then bulk-
inserts into the daily_prices table (ON CONFLICT DO NOTHING so re-runs
are safe).

Usage:
    DATABASE_URL=... python scripts/backfill_daily_prices_gap.py
    DATABASE_URL=... python scripts/backfill_daily_prices_gap.py --start 2022-06-15 --end 2023-04-13

Runtime: ~45-90 min for the full 2022-07 → 2023-04 gap (one NSE request
per trading date, ~250 days × ~2 sec = 8-15 min just for HTTP; writes
are bulk-insert so negligible DB time).

Resumable: rows are UPSERTed with DO NOTHING, so Ctrl-C and rerun is fine.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("bhavcopy_backfill")


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        # Skip weekends (NSE closed)
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-06-15", help="ISO date (default: 2022-06-15)")
    ap.add_argument("--end", default="2023-04-13", help="ISO date (default: 2023-04-13)")
    ap.add_argument("--sleep", type=float, default=1.2, help="Sleep between requests")
    ap.add_argument("--limit", type=int, default=None, help="Only process N days (testing)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from data_pipeline.sources.nse_bhavcopy import download_bhavcopy, _get_nse_session

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    session = _get_nse_session()
    dates = list(_daterange(start, end))
    if args.limit:
        dates = dates[:args.limit]

    logger.info("backfilling %d trading dates: %s → %s", len(dates), start, end)

    upsert = text("""
        INSERT INTO daily_prices (
            ticker, trade_date, open_price, high_price, low_price,
            close_price, prev_close, volume, turnover_cr, delivery_qty,
            delivery_pct, vwap, adj_close
        ) VALUES (
            :ticker, :trade_date, :open, :high, :low,
            :close, :prev_close, :volume, :turnover_cr, :delivery_qty,
            :delivery_pct, :vwap, :adj_close
        )
        ON CONFLICT DO NOTHING
    """)

    total_inserted = 0
    total_skipped_no_data = 0
    total_failed = 0

    for i, d in enumerate(dates, 1):
        try:
            df = download_bhavcopy(d, session=session)
        except Exception as exc:
            logger.warning("[%d/%d] %s download failed: %s", i, len(dates), d, exc)
            total_failed += 1
            time.sleep(args.sleep * 2)
            continue

        if df is None or df.empty:
            total_skipped_no_data += 1
            if i % 25 == 0:
                logger.info("[%d/%d] checkpoint: inserted=%d skipped=%d failed=%d",
                            i, len(dates), total_inserted, total_skipped_no_data, total_failed)
            time.sleep(args.sleep)
            continue

        # Normalise column names — NSE bhavcopy has specific format
        df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]

        # Only EQ series (equity shares), skip ETFs/bonds
        if "SERIES" in df.columns:
            df = df[df["SERIES"].str.strip() == "EQ"]
        if df.empty:
            time.sleep(args.sleep)
            continue

        rows_to_insert = []
        for row in df.itertuples(index=False):
            ticker = getattr(row, "SYMBOL", None)
            if not ticker:
                continue
            try:
                # NSE columns: SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE,
                # HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE,
                # TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
                rows_to_insert.append({
                    "ticker": ticker.strip(),
                    "trade_date": d,
                    "open": float(getattr(row, "OPEN_PRICE", 0) or 0) or None,
                    "high": float(getattr(row, "HIGH_PRICE", 0) or 0) or None,
                    "low": float(getattr(row, "LOW_PRICE", 0) or 0) or None,
                    "close": float(getattr(row, "CLOSE_PRICE", 0) or 0) or None,
                    "prev_close": float(getattr(row, "PREV_CLOSE", 0) or 0) or None,
                    "volume": int(getattr(row, "TTL_TRD_QNTY", 0) or 0) or None,
                    "turnover_cr": float(getattr(row, "TURNOVER_LACS", 0) or 0) / 100.0 or None,
                    "delivery_qty": int(getattr(row, "DELIV_QTY", 0) or 0) or None,
                    "delivery_pct": float(getattr(row, "DELIV_PER", 0) or 0) or None,
                    "vwap": float(getattr(row, "AVG_PRICE", 0) or 0) or None,
                    "adj_close": float(getattr(row, "CLOSE_PRICE", 0) or 0) or None,
                })
            except (TypeError, ValueError):
                continue

        if not rows_to_insert:
            time.sleep(args.sleep)
            continue

        sess = Session()
        try:
            for r in rows_to_insert:
                sess.execute(upsert, r)
            sess.commit()
            total_inserted += len(rows_to_insert)
            if i % 10 == 0:
                logger.info("[%d/%d] %s → %d rows (running total: %d)",
                            i, len(dates), d, len(rows_to_insert), total_inserted)
        except Exception as exc:
            sess.rollback()
            logger.error("[%d/%d] %s commit failed: %s", i, len(dates), d, exc)
            total_failed += 1
        finally:
            sess.close()

        time.sleep(args.sleep)

    logger.info("")
    logger.info("DONE")
    logger.info("  dates processed      : %d", len(dates))
    logger.info("  rows inserted        : %d", total_inserted)
    logger.info("  dates with no data   : %d (holidays / NSE closed)", total_skipped_no_data)
    logger.info("  failed dates         : %d", total_failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
