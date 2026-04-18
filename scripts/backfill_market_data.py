#!/usr/bin/env python3
"""
scripts/backfill_market_data.py

Idempotent one-shot backfill for the three market-data tables added in
migration 003:
    • live_quotes       (portfolio holdings + top-200 FV tickers)
    • fx_rates          (USDINR)
    • index_snapshots   (NIFTY, SENSEX, BANK, VIX, gold, silver, midcap)

Runs on demand so the tables aren't empty when the APScheduler crons
first tick. Re-running is safe — every write is an UPSERT.

Usage
-----
    export DATABASE_URL="postgres://…aiven…"
    python scripts/backfill_market_data.py

Add `--quotes-only`, `--fx-only`, or `--indices-only` to scope the run.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root on sys.path so `backend.*` / `data_pipeline.*` import.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backfill_market_data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotes-only", action="store_true")
    parser.add_argument("--fx-only", action="store_true")
    parser.add_argument("--indices-only", action="store_true")
    parser.add_argument(
        "--limit-fv", type=int, default=200,
        help="How many top tickers from fair_value_history to include "
             "in the live_quotes backfill (default: 200).",
    )
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL is not set — cannot backfill.")
        return 2

    from backend.workers.market_data_refresher import (
        collect_refresh_tickers,
        refresh_fx_rates,
        refresh_index_snapshots,
        refresh_live_quotes,
    )

    run_all = not (args.quotes_only or args.fx_only or args.indices_only)

    if args.fx_only or run_all:
        log.info("Backfilling fx_rates …")
        stats = refresh_fx_rates()
        log.info("  fx_rates: %s", stats)

    if args.indices_only or run_all:
        log.info("Backfilling index_snapshots …")
        stats = refresh_index_snapshots()
        log.info("  index_snapshots: %s", stats)

    if args.quotes_only or run_all:
        log.info("Collecting tickers for live_quotes backfill …")
        tickers = collect_refresh_tickers(limit_fv=args.limit_fv)
        log.info("  found %d unique tickers", len(tickers))
        if tickers:
            stats = refresh_live_quotes(tickers)
            log.info("  live_quotes: %s", stats)
        else:
            log.warning("  no tickers found — skipping live_quotes")

    log.info("Backfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
