"""Lint: warn if any ETF / fund / index ticker is flagged is_active=TRUE in stocks.

Companion to scripts/deactivate_etfs.sql — that one-shot migration deactivated
236 ETF/fund/index tickers (2026-04-25) because they have no fundamentals and
pollute the analyzable universe (282/453 FV=0 rows traced to these).

If populate_stocks later re-flags any of them, this lint surfaces it loudly
instead of letting the pollution regress silently. Wire into a nightly
workflow or run by hand:

    DATABASE_URL=... python scripts/lint_etf_reactivation.py

Exit code 0 = clean, 1 = regression (ETFs are active again).
"""
from __future__ import annotations

import os
import sys

import psycopg2


_QUERY = """
SELECT ticker, sector
FROM stocks
WHERE is_active = TRUE
  AND (
       ticker ~ 'BEES$'
    OR ticker ~ 'IETF$'
    OR ticker ~ 'ETF'
    OR ticker ~ '^NIFTY'
    OR ticker ~ 'ADD$'
    OR ticker LIKE '%%CASHIETF%%'
    OR ticker LIKE '%%LIQUIDSHRI%%'
    OR ticker LIKE '%%MIDQ50%%'
    OR ticker LIKE '%%TOP15%%'
    OR sector IN ('ETF','Fund','Index')
  )
ORDER BY ticker
"""


def main() -> int:
    url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute(_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("OK: 0 ETF/fund/index tickers flagged is_active=TRUE")
        return 0

    print(f"WARN: {len(rows)} ETF/fund/index tickers are is_active=TRUE "
          f"(should be FALSE per scripts/deactivate_etfs.sql):")
    for ticker, sector in rows[:50]:
        print(f"  - {ticker} (sector={sector})")
    if len(rows) > 50:
        print(f"  ... and {len(rows) - 50} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
