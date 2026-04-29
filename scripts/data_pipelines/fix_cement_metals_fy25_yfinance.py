#!/usr/bin/env python
"""NULL corrupted FY25 yfinance rows on 16 cement+metals tickers.

Symptom (verified on prod Neon, 2026-04-29):
  PR #194 / v74 NSE-archive backfill let yfinance overwrite NSE_XBRL for
  FY25 (period_end='2025-03-31') on 16 cement+metals tickers. yfinance's
  metals/cement annual numbers have incomplete capex / working-capital
  data, producing nonsense FCF that breaks DCF for HINDALCO (₹370 vs
  street ₹650-750) and GRASIM (₹927 / data_limited vs street ₹2,500-3,000).

Fix: for these 16 tickers, where data_source='yfinance' on the FY25
(period_end='2025-03-31') annual row, NULL out cfo / capex / free_cash_flow
so the DCF falls back to the FY24 NSE_XBRL anchor row (which has clean
values from the pre-PR-194 ingest path).

We deliberately preserve revenue/PAT — yfinance often gets those right
even when the cash-flow columns are bad — so any non-DCF analyses that
depend on them remain available.

This script is idempotent. Per-ticker explicit allow-list — no heuristic.

Run:
    DATABASE_URL=$(sed -n '2p' /path/to/.env.local) \\
        python scripts/data_pipelines/fix_cement_metals_fy25_yfinance.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

# 16 cement + metals tickers diagnosed today as having FY25 yfinance rows
# that overwrote the clean NSE_XBRL data from earlier ingest cycles.
AFFECTED_TICKERS = (
    # Cement
    "SHREECEM", "ULTRACEMCO", "AMBUJACEM", "ACC", "GRASIM",
    "JKCEMENT", "RAMCOCEM", "DALBHARAT",
    # Metals & Mining
    "TATASTEEL", "JSWSTEEL", "HINDALCO", "JINDALSTEL",
    "NMDC", "SAIL", "VEDL", "COALINDIA",
)


SELECT_SQL = """
    SELECT ticker, period_end, data_source, cfo, capex, free_cash_flow, revenue
      FROM financials
     WHERE ticker = ANY(%s)
       AND period_type = 'annual'
       AND period_end = '2025-03-31'
       AND data_source = 'yfinance'
     ORDER BY ticker
"""

NULL_SQL = """
    UPDATE financials
       SET cfo = NULL, capex = NULL, free_cash_flow = NULL
     WHERE ticker = ANY(%s)
       AND period_type = 'annual'
       AND period_end = '2025-03-31'
       AND data_source = 'yfinance'
"""

VERIFY_SQL = """
    SELECT ticker, period_end, data_source, revenue, cfo, capex, free_cash_flow
      FROM financials
     WHERE ticker = ANY(%s)
       AND period_type = 'annual'
       AND period_end >= '2024-03-31'
     ORDER BY ticker, period_end DESC
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change, no writes.")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL env var required", file=sys.stderr)
        return 2

    import psycopg

    with psycopg.connect(url, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            # Step 1: read-only — show what we're about to touch.
            cur.execute(SELECT_SQL, (list(AFFECTED_TICKERS),))
            before = cur.fetchall()
            print(f"Before: {len(before)} FY25 yfinance rows on affected tickers")
            print(f"  cols: ticker, period_end, data_source, cfo, capex, fcf, revenue")
            for r in before:
                print(f"  {r}")

            if args.dry_run:
                print("\n[dry-run] would execute:")
                print("  " + NULL_SQL.strip())
                return 0

            # Step 2: execute the NULL update.
            cur.execute(NULL_SQL, (list(AFFECTED_TICKERS),))
            n_nulled = cur.rowcount
            cx.commit()
            print(f"\nNulled cfo+capex+fcf on {n_nulled} rows")

            # Step 3: verify — show FY24 + FY25 for each affected ticker.
            cur.execute(VERIFY_SQL, (list(AFFECTED_TICKERS),))
            print("\nFY24/FY25 annual rows after fix (ticker, period_end, src, rev, cfo, capex, fcf):")
            for r in cur.fetchall():
                print(f"  {r}")

            # Step 4: confirm no FY25 yfinance rows still have non-null cfo.
            cur.execute("""
                SELECT ticker, cfo, capex, free_cash_flow
                  FROM financials
                 WHERE ticker = ANY(%s)
                   AND period_type = 'annual'
                   AND period_end = '2025-03-31'
                   AND data_source = 'yfinance'
                   AND (cfo IS NOT NULL OR capex IS NOT NULL OR free_cash_flow IS NOT NULL)
            """, (list(AFFECTED_TICKERS),))
            stragglers = cur.fetchall()
            if stragglers:
                print(f"\nWARNING: {len(stragglers)} rows still have non-null cash-flow cols:")
                for r in stragglers:
                    print(f"  {r}")
                return 1
            print(f"\nAll {len(AFFECTED_TICKERS)} affected tickers cleaned. Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
