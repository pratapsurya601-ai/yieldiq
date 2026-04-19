"""Quick diagnostic — shows why build_peer_groups.py finds no candidates.

Usage:
    DATABASE_URL=... python scripts/diagnose_peer_inputs.py

Checks the three inputs the peer builder needs:
  1. stocks.industry coverage
  2. stocks.market_cap_category coverage
  3. market_metrics recency
"""
from __future__ import annotations

import os
import sys

try:
    import psycopg2
except ImportError:
    print("install psycopg2-binary first")
    sys.exit(1)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2

    conn = psycopg2.connect(url)
    cur = conn.cursor()

    print("=" * 60)
    print("1. stocks.industry coverage")
    print("=" * 60)
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(industry) AS with_industry,
            COUNT(DISTINCT industry) AS distinct_industries
        FROM stocks WHERE is_active = TRUE
    """)
    row = cur.fetchone()
    print(f"  total active stocks     : {row[0]}")
    print(f"  with industry populated : {row[1]}")
    print(f"  distinct industries     : {row[2]}")

    cur.execute("""
        SELECT industry, COUNT(*) AS n
        FROM stocks WHERE is_active = TRUE AND industry IS NOT NULL AND industry != ''
        GROUP BY industry ORDER BY n DESC LIMIT 10
    """)
    print("\n  top 10 industries:")
    for r in cur.fetchall():
        print(f"    {r[1]:>5}  {r[0]}")

    print()
    print("=" * 60)
    print("2. stocks.market_cap_category coverage")
    print("=" * 60)
    cur.execute("""
        SELECT
            COALESCE(market_cap_category, '(null)') AS cat,
            COUNT(*) AS n
        FROM stocks WHERE is_active = TRUE
        GROUP BY market_cap_category ORDER BY n DESC
    """)
    for r in cur.fetchall():
        print(f"    {r[1]:>5}  {r[0]}")

    print()
    print("=" * 60)
    print("3. market_metrics recency")
    print("=" * 60)
    cur.execute("""
        SELECT
            COUNT(DISTINCT ticker) AS tickers_with_metrics,
            MAX(trade_date) AS latest_metric
        FROM market_metrics
    """)
    row = cur.fetchone()
    print(f"  tickers with any metrics : {row[0]}")
    print(f"  most recent trade_date   : {row[1]}")

    cur.execute("""
        SELECT COUNT(DISTINCT ticker) AS n
        FROM market_metrics
        WHERE trade_date > current_date - interval '30 days'
          AND market_cap_cr IS NOT NULL AND market_cap_cr > 0
    """)
    row = cur.fetchone()
    print(f"  tickers with recent mcap : {row[0]}  (within 30 days, mcap_cr > 0)")

    print()
    print("=" * 60)
    print("4. candidate counts per ticker (sample)")
    print("=" * 60)
    cur.execute("""
        WITH me AS (
          SELECT ticker, industry, market_cap_category
          FROM stocks WHERE ticker IN ('RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ITC')
        )
        SELECT
            me.ticker,
            me.industry,
            me.market_cap_category,
            (SELECT COUNT(*) FROM stocks s2
             WHERE s2.is_active = TRUE
               AND s2.ticker != me.ticker
               AND s2.industry = me.industry
               AND s2.market_cap_category = me.market_cap_category) AS candidate_count
        FROM me
    """)
    print(f"  {'ticker':<12}{'industry':<35}{'cap':<10}{'candidates'}")
    for r in cur.fetchall():
        ind = (r[1] or '')[:33]
        cat = r[2] or '(null)'
        print(f"  {r[0]:<12}{ind:<35}{cat:<10}{r[3]}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
