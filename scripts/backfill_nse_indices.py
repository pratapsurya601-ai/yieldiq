"""Backfill nse_index_history from the NSE ind_close_all archive.

The daily cron only keeps recent data (~weeks). The benchmark-proxy build
needs DEPTH — multi-year history so 1Y/3Y/5Y/10Y benchmark returns can be
computed. This loops trading dates from --start to today, pulling one
ind_close_all CSV per day via the existing nse_indices_history source
(~110 index rows/day) and upserting into nse_index_history.

Idempotent: ON CONFLICT (index_name, trade_date). With --resume it skips
dates already present, so a timeout re-dispatch continues. ~3,000 trading
days back to 2014; at ~1s/day that's well under the 350-min CI budget.

Run via the nse-indices-backfill.yml workflow_dispatch (DATABASE_URL
secret) — not a local prod write.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_pipeline.sources.nse_indices_history import (  # noqa: E402
    _get_session,
    fetch_ind_close_all,
    upsert_rows_psycopg,
)

logger = logging.getLogger("backfill_nse_indices")


def _existing_dates(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT trade_date FROM nse_index_history")
        return {r[0] for r in cur.fetchall()}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--start", default="2014-01-01", help="First date (YYYY-MM-DD).")
    p.add_argument("--end", default=None, help="Last date; default today.")
    p.add_argument("--throttle", type=float, default=0.3,
                   help="Seconds between day requests.")
    p.add_argument("--resume", action="store_true",
                   help="Skip dates already in nse_index_history.")
    args = p.parse_args(argv)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 2
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    import psycopg2
    conn = psycopg2.connect(db_url)

    existing = _existing_dates(conn) if args.resume else set()
    logger.info("resume=%s existing_dates=%s", args.resume, len(existing))

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()
    logger.info("backfilling nse_index_history %s .. %s", start, end)

    sess = _get_session()
    d = start
    days = rows_total = skipped = 0
    try:
        while d <= end:
            if d.weekday() >= 5 or d in existing:
                d += timedelta(days=1)
                continue
            rows = fetch_ind_close_all(d, session=sess)
            if rows:
                n = upsert_rows_psycopg(rows, conn)
                rows_total += n
                days += 1
                if days % 50 == 0:
                    logger.info("[%s] days=%s rows=%s", d, days, rows_total)
            else:
                skipped += 1
            time.sleep(args.throttle)
            d += timedelta(days=1)
    except KeyboardInterrupt:
        logger.warning("interrupted — partial backfill committed; rerun --resume")
    finally:
        conn.close()

    logger.info("DONE trading_days=%s rows=%s empty/holiday=%s", days, rows_total, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
