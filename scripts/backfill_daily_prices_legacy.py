"""Backfill daily_prices for the pre-2020-07 era using NSE's legacy
bhavcopy archive (cm<DD><MMM><YYYY>bhav.csv.zip URL pattern).

Why this exists:
  daily_prices currently spans 2021-04 → 2026-04 (~1.04M rows). The
  modern sec_bhavdata_full_DDMMYYYY.csv URL only works from 2020-07-08
  onwards, so anything earlier needs the OLD archive endpoint that this
  script targets.

Default window: 2016-01-01 → 2020-07-07. Roughly 1,130 trading days,
~1.7M new rows expected.

Usage:
    DATABASE_URL=... python scripts/backfill_daily_prices_legacy.py
    DATABASE_URL=... python scripts/backfill_daily_prices_legacy.py --start 2018-01-01 --end 2018-12-31
    DATABASE_URL=... python scripts/backfill_daily_prices_legacy.py --tickers RELIANCE,TCS  # filter
    DATABASE_URL=... python scripts/backfill_daily_prices_legacy.py --top 500              # limit to top-N
    DATABASE_URL=... python scripts/backfill_daily_prices_legacy.py --all                  # keep every symbol

Runtime: ~45-90 min per year of history at the default 1.5 sec sleep
between requests. The full 4.5 year backfill takes ~4-7 hours wall-clock.

Resumable: rows go in via INSERT ... ON CONFLICT DO NOTHING on the
(ticker, trade_date) unique index, so Ctrl-C and rerun is fine. If you
hit a sequence-PK collision, run scripts/resync_pg_sequences.py first.
"""
from __future__ import annotations

import argparse
import logging
import math
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
logger = logging.getLogger("legacy_bhavcopy")

DEFAULT_START = "2016-01-01"
DEFAULT_END = "2020-07-07"


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:  # skip Sat/Sun
            yield d
        d += timedelta(days=1)


def _resolve_ticker_filter(args, engine) -> set[str] | None:
    """None = no filter (insert everything). A set means keep-only filter."""
    if args.all:
        return None
    if args.tickers:
        return {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
    if args.top:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT s.ticker FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT :n"
            ), {"n": args.top}).fetchall()
        tickers = {r[0] for r in rows if r and r[0]}
        logger.info("top-%d filter resolved to %d tickers", args.top, len(tickers))
        return tickers
    # Default behaviour: top-500 (matches scripts/backfill_xbrl_10y.py).
    return _resolve_ticker_filter(
        argparse.Namespace(all=False, tickers=None, top=500), engine
    )


def _num(v, kind=float):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
        x = kind(v)
        if isinstance(x, float) and math.isnan(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="Sleep between NSE requests (be polite)")
    ap.add_argument("--limit-days", type=int, default=None,
                    help="Cap days processed (smoke testing)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--top", type=int, help="Restrict to top-N tickers by market cap")
    g.add_argument("--tickers", help="Comma-separated ticker filter")
    g.add_argument("--all", action="store_true", help="Insert every symbol in bhavcopy")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if start > end:
        print("start must be <= end", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from data_pipeline.sources.nse_bhavcopy_legacy import (
        download_bhavcopy_legacy,
        _get_nse_session,
    )

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    keep_set = _resolve_ticker_filter(args, engine)

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
        ON CONFLICT (ticker, trade_date) DO NOTHING
    """)

    dates = list(_daterange(start, end))
    if args.limit_days:
        dates = dates[: args.limit_days]

    logger.info(
        "legacy backfill: %d trading days %s → %s, ticker filter=%s",
        len(dates), start, end,
        f"{len(keep_set)} tickers" if keep_set else "ALL",
    )

    nse_session = _get_nse_session()
    total_inserted = 0
    total_no_data = 0
    total_failed = 0
    consecutive_fails = 0

    for i, d in enumerate(dates, 1):
        try:
            df = download_bhavcopy_legacy(d, session=nse_session)
        except Exception as exc:
            logger.warning("[%d/%d] %s download error: %s", i, len(dates), d, exc)
            total_failed += 1
            consecutive_fails += 1
            time.sleep(args.sleep * 2)
            if consecutive_fails >= 8:
                logger.info("refreshing NSE session after %d fails", consecutive_fails)
                nse_session = _get_nse_session()
                consecutive_fails = 0
            continue

        if df is None or df.empty:
            total_no_data += 1
            time.sleep(args.sleep)
            if i % 25 == 0:
                logger.info(
                    "[%d/%d] checkpoint inserted=%d no_data=%d failed=%d",
                    i, len(dates), total_inserted, total_no_data, total_failed,
                )
            continue

        consecutive_fails = 0
        if keep_set is not None:
            df = df[df["ticker"].isin(keep_set)]
        if df.empty:
            time.sleep(args.sleep)
            continue

        rows = []
        for rec in df.to_dict("records"):
            ticker = rec.get("ticker")
            if not ticker or (isinstance(ticker, float) and math.isnan(ticker)):
                continue
            ticker_str = str(ticker).strip()
            if not ticker_str or ticker_str.lower() == "nan":
                continue
            close = _num(rec.get("close_price"))
            rows.append({
                "ticker": ticker_str,
                "trade_date": d,
                "open": _num(rec.get("open_price")),
                "high": _num(rec.get("high_price")),
                "low": _num(rec.get("low_price")),
                "close": close,
                "prev_close": _num(rec.get("prev_close")),
                "volume": _num(rec.get("volume"), int),
                "turnover_cr": _num(rec.get("turnover_cr")),
                "delivery_qty": _num(rec.get("delivery_qty"), int),
                "delivery_pct": _num(rec.get("delivery_pct")),
                "vwap": _num(rec.get("vwap")),
                "adj_close": close,
            })

        if not rows:
            time.sleep(args.sleep)
            continue

        sess = Session()
        try:
            for r in rows:
                sess.execute(upsert, r)
            sess.commit()
            total_inserted += len(rows)
            if i % 10 == 0:
                logger.info(
                    "[%d/%d] %s → %d rows (running total %d)",
                    i, len(dates), d, len(rows), total_inserted,
                )
        except Exception as exc:
            sess.rollback()
            logger.error("[%d/%d] %s commit failed: %s", i, len(dates), d, exc)
            total_failed += 1
        finally:
            sess.close()

        time.sleep(args.sleep)

    logger.info("")
    logger.info("DONE legacy bhavcopy backfill")
    logger.info("  trading days processed : %d", len(dates))
    logger.info("  rows inserted          : %d", total_inserted)
    logger.info("  days with no data      : %d", total_no_data)
    logger.info("  failed days            : %d", total_failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
