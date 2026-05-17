#!/usr/bin/env python3
"""
scripts/backfill_earnings_calendar.py
─────────────────────────────────────────────────────────────────────
One-shot backfill for the unified earnings calendar.

Usage:
    python scripts/backfill_earnings_calendar.py            # all active tickers
    python scripts/backfill_earnings_calendar.py --top 50   # Nifty-50 only
    python scripts/backfill_earnings_calendar.py --dry-run  # print plan, no writes

What it does
------------
1. Loads the active ticker universe from `stocks` (active=true) — or a
   canary subset if --top is given.
2. For each ticker, calls earnings_calendar_service.refresh_all which:
     • skips if a confirmed NSE row already exists in the next 90d
     • otherwise tries yfinance .info.earningsTimestamp and writes a
       row with source='yfinance', confirmed=false
3. Prints a per-ticker summary and an aggregate count.

Idempotent: safe to re-run. yfinance is the only network call.

Run this once post-deploy of 040_earnings_calendar.sql. The daily
NSE event-calendar cron continues to populate confirmed rows; this
script just guarantees nobody sees a bare "Not scheduled".
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backfill_earnings_calendar")


def _load_canary_50() -> list[str]:
    path = Path(__file__).resolve().parent / "canary_stocks_50.json"
    if not path.exists():
        return []
    import json
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [str(x).strip() for x in data if x]
    if isinstance(data, dict) and "tickers" in data:
        return [str(x).strip() for x in data["tickers"] if x]
    return []


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=0,
                   help="If set, only backfill the canary-50 (or first N).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ticker plan and exit; no DB writes.")
    args = p.parse_args()

    from data_pipeline.db import SessionLocal
    from data_pipeline.models import Stock
    from backend.services.earnings_calendar_service import refresh_all

    db = SessionLocal()
    try:
        tickers: list[str]
        if args.top:
            tickers = _load_canary_50()[: args.top] or [
                t for (t,) in db.query(Stock.ticker)
                .filter(Stock.active.is_(True))
                .order_by(Stock.market_cap_cr.desc().nullslast())
                .limit(args.top)
                .all()
            ]
        else:
            tickers = [t for (t,) in db.query(Stock.ticker)
                       .filter(Stock.active.is_(True)).all()]

        log.info("Backfill plan: %d tickers", len(tickers))
        if args.dry_run:
            for t in tickers[:20]:
                log.info("  · %s", t)
            if len(tickers) > 20:
                log.info("  · …and %d more", len(tickers) - 20)
            return 0

        result = refresh_all(tickers, db)
        log.info("Backfill complete: %s", result)
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
