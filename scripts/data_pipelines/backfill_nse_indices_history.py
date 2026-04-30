#!/usr/bin/env python
"""Backfill NSE daily index history (close + P/E + P/B + Div Yield).

Source: archives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv
        — earliest available 2014-01-01.

Usage::

    DATABASE_URL=$(sed -n '2p' /e/Projects/yieldiq_v7/.env.local) \\
        python scripts/data_pipelines/backfill_nse_indices_history.py \\
            --from 2014-01-01 --to 2026-04-29

Flags:
    --from YYYY-MM-DD   Start date (inclusive). Default: 2014-01-01.
    --to   YYYY-MM-DD   End date (inclusive). Default: today.
    --sleep FLOAT       Polite throttle between dates (default 0.5s).
    --dry-run           Fetch but don't write to DB.

Idempotent — re-running is safe (UPSERT on (index_name, trade_date)).
Skips weekends and 404s (holidays). Refreshes the curl_cffi session
every 50 consecutive failures.

Time: ~3,000 trading days @ ~0.7s each ≈ 35 min for a full backfill.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Allow running as a script from anywhere in the repo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_pipeline.sources import nse_indices_history as nih


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _connect(database_url: str):
    """Open a psycopg2 connection (binary). Caller closes."""
    try:
        import psycopg2
    except ImportError:
        sys.stderr.write("psycopg2-binary required\n")
        raise
    # psycopg2 accepts both postgres:// and postgresql:// — normalise.
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    return psycopg2.connect(database_url)


def _iter_dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--from", dest="start", type=_parse_date,
                   default=date(2014, 1, 1), help="Start date (YYYY-MM-DD).")
    p.add_argument("--to", dest="end", type=_parse_date,
                   default=date.today(), help="End date (YYYY-MM-DD).")
    p.add_argument("--sleep", type=float, default=0.5,
                   help="Polite sleep between dates (seconds).")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch only, no DB writes.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("backfill_nse_indices_history")

    if args.start > args.end:
        log.error("--from %s is after --to %s", args.start, args.end)
        return 2

    db_url = os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        log.error("DATABASE_URL env var required (or use --dry-run).")
        return 2

    conn = None if args.dry_run else _connect(db_url)
    sess = nih._get_session()

    total_dates = 0
    total_rows = 0
    holiday_skips = 0
    consecutive_fail = 0

    log.info("Backfilling ind_close_all from %s to %s (dry_run=%s)",
             args.start, args.end, args.dry_run)

    try:
        for d in _iter_dates(args.start, args.end):
            if d.weekday() >= 5:
                continue  # weekend
            total_dates += 1
            rows = nih.fetch_ind_close_all(d, session=sess)
            if not rows:
                holiday_skips += 1
                consecutive_fail += 1
                if consecutive_fail >= 50:
                    log.info("Refreshing curl_cffi session (%d consecutive empties)",
                             consecutive_fail)
                    try:
                        sess = nih._get_session()
                    except Exception:
                        pass
                    consecutive_fail = 0
                time.sleep(args.sleep)
                continue
            consecutive_fail = 0
            if args.dry_run:
                log.info("%s: %d rows (dry-run)", d, len(rows))
            else:
                n = nih.upsert_rows_psycopg(rows, conn)
                total_rows += n
                if total_dates % 25 == 0:
                    log.info("%s: %d rows upserted (cum dates=%d, rows=%d, holidays=%d)",
                             d, n, total_dates, total_rows, holiday_skips)
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        log.warning("Interrupted — partial backfill committed.")
    finally:
        if conn is not None:
            conn.close()

    log.info("Done. dates=%d rows_upserted=%d holiday_skips=%d",
             total_dates, total_rows, holiday_skips)
    return 0


if __name__ == "__main__":
    sys.exit(main())
