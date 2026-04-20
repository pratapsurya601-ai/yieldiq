"""Backfill earnings-call / analyst-meet filings into concall_transcripts.

Pulls from NSE's corporate-announcements JSON endpoint for each ticker
in the chosen universe, filters by subject/category for concall-type
records, and inserts metadata (NOT PDF contents) with
ON CONFLICT DO NOTHING semantics so re-runs are idempotent.

Usage:
    DATABASE_URL=... python scripts/backfill_concall_transcripts.py \
        --top 500 --days-back 120
    DATABASE_URL=... python scripts/backfill_concall_transcripts.py \
        --top 5 --days-back 30 --dry-run
    DATABASE_URL=... python scripts/backfill_concall_transcripts.py \
        --tickers RELIANCE,TCS --days-back 365

Args:
    --top N          Top-N active tickers by market cap (default 500)
    --tickers        Comma-separated ticker override
    --all            All active tickers
    --days-back N    Look back window in days (default 120)
    --sleep          Seconds between NSE requests (default 1.5 -- polite)
    --dry-run        Fetch + filter + print counts, DO NOT write

Apply migration first:
    DATABASE_URL=... python scripts/apply_migration.py \
        data_pipeline/migrations/009_concall_transcripts.sql
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("concall_backfill")

DEFAULT_SLEEP = 1.5
DEFAULT_TOP = 500
DEFAULT_DAYS_BACK = 120


def _resolve_universe(args, engine) -> list[str]:
    from sqlalchemy import text

    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    with engine.connect() as conn:
        if args.all:
            rows = conn.execute(text(
                "SELECT s.ticker FROM stocks s "
                "WHERE s.is_active = TRUE "
                "ORDER BY s.ticker"
            )).fetchall()
        else:
            n = args.top or DEFAULT_TOP
            # GROUP BY -- market_metrics can have multiple rows per
            # ticker (history) so a naive JOIN duplicates tickers.
            rows = conn.execute(text(
                "SELECT s.ticker "
                "FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "GROUP BY s.ticker "
                "ORDER BY COALESCE(MAX(mm.market_cap_cr), 0) DESC "
                "LIMIT :n"
            ), {"n": n}).fetchall()
    return [r[0] for r in rows if r and r[0]]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--top", type=int, default=None,
                   help=f"Top-N by market cap (default {DEFAULT_TOP})")
    g.add_argument("--tickers", help="Comma-separated ticker list")
    g.add_argument("--all", action="store_true", help="All active tickers")

    ap.add_argument("--days-back", type=int, default=DEFAULT_DAYS_BACK,
                    help=f"Days of filings to pull (default {DEFAULT_DAYS_BACK})")
    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                    help=f"Seconds between NSE requests (default {DEFAULT_SLEEP})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + print, do NOT write to DB")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap tickers processed (smoke testing)")
    args = ap.parse_args()

    if args.top is None and not args.tickers and not args.all:
        args.top = DEFAULT_TOP

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data_pipeline.sources.nse_concall_transcripts import (
        fetch_filings_for_symbol,
        normalize_record,
        upsert_records,
        get_nse_session,
    )

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    universe = _resolve_universe(args, engine)
    if args.limit:
        universe = universe[: args.limit]

    if not universe:
        logger.info("nothing to do -- empty universe")
        return 0

    to_d = date.today()
    from_d = to_d - timedelta(days=args.days_back)
    logger.info(
        "window: %s -> %s (%d days) | tickers: %d | dry_run=%s",
        from_d.isoformat(), to_d.isoformat(), args.days_back,
        len(universe), args.dry_run,
    )

    session_http = get_nse_session()

    processed = 0
    filings_found = 0
    new_rows = 0
    failed = 0

    for i, ticker in enumerate(universe, 1):
        try:
            raw_items = fetch_filings_for_symbol(
                ticker, from_d, to_d, session=session_http,
            )
        except Exception as exc:
            logger.warning("[%d/%d] %s fetch failed: %s",
                           i, len(universe), ticker, exc)
            failed += 1
            time.sleep(args.sleep)
            continue

        processed += 1

        rows: list[dict] = []
        for it in raw_items:
            norm = normalize_record(it, ticker)
            if norm:
                rows.append(norm)

        filings_found += len(rows)

        if rows and not args.dry_run:
            db = Session()
            try:
                added = upsert_records(rows, db)
                new_rows += added
            finally:
                db.close()
        elif rows and args.dry_run:
            logger.info(
                "[%d/%d] %s: %d concall filings (dry-run, first subject: %r)",
                i, len(universe), ticker, len(rows),
                rows[0]["subject"][:120],
            )
        # If rows is empty we stay quiet unless on a tick boundary.

        if i % 25 == 0 or i == len(universe):
            logger.info(
                "[%d/%d] processed=%d filings_found=%d new_rows=%d failed=%d",
                i, len(universe), processed, filings_found, new_rows, failed,
            )

        time.sleep(args.sleep)

    logger.info("")
    logger.info("DONE concall transcripts backfill")
    logger.info("  processed      : %d", processed)
    logger.info("  filings_found  : %d", filings_found)
    logger.info("  new_rows       : %d%s",
                new_rows, " (dry-run, not written)" if args.dry_run else "")
    logger.info("  failed         : %d", failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
