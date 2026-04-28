"""run_sebi_crawler.py — cron driver for the SEBI filings crawler.

Recommended schedule (Asia/Kolkata, market days only):

    */30 9-18 * * 1-6  python scripts/run_sebi_crawler.py --mode discover --lookback-hours 2
    */10 9-19 * * 1-6  python scripts/run_sebi_crawler.py --mode process --limit 50

Outside market hours run --mode discover once at 23:00 to catch
post-market filings.

This is SCAFFOLDING — discover_new_filings() is a stub. See
backend/workers/sebi_filings_crawler.py for the real-implementation
notes.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _cmd_discover(args: argparse.Namespace) -> int:
    from backend.workers.sebi_filings_crawler import (
        discover_new_filings, enqueue_filing, with_backoff,
    )
    filings = with_backoff(discover_new_filings, lookback_hours=args.lookback_hours)
    if not filings:
        logging.info("discover: 0 new filings (stub returns empty)")
        return 0

    logging.info("discover: %d new filings", len(filings))
    if args.dry_run:
        for f in filings:
            logging.info("DRY-RUN would enqueue: %s %s %s", f.ticker, f.fiscal_period, f.source_exchange)
        return 0

    inserted = 0
    for f in filings:
        if args.ticker and f.ticker != args.ticker.upper():
            continue
        try:
            with_backoff(enqueue_filing, f, attempts=2)
            inserted += 1
        except Exception:
            logging.exception("enqueue failed for %s %s", f.ticker, f.fiscal_period)
    logging.info("discover: inserted/updated %d rows", inserted)
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    from backend.workers.sebi_filings_crawler import process_pending
    counters = process_pending(limit=args.limit, dry_run=args.dry_run)
    logging.info("process: %s", counters)
    return 0 if counters["failed"] == 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEBI quarterly-results crawler driver")
    p.add_argument("--mode", choices=["discover", "process", "both"], default="both")
    p.add_argument("--ticker", default=None,
                   help="Limit discover to a single ticker (case-insensitive)")
    p.add_argument("--lookback-hours", type=int, default=2,
                   help="Window for discover (default 2). Use 8760 for first-deploy backfill.")
    p.add_argument("--limit", type=int, default=50,
                   help="Max rows to walk in process mode")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    rc = 0
    if args.mode in ("discover", "both"):
        rc = _cmd_discover(args) or rc
    if args.mode in ("process", "both"):
        rc = _cmd_process(args) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
