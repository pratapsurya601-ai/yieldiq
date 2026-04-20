"""Check daily_prices coverage — needed for historical PE/PB/EV computation.

If daily_prices has 5+ years of history for most tickers, we can compute
per-period valuation ratios at build-time from primitives
(close_price × shares / pat) instead of depending on market_metrics.
"""
from __future__ import annotations
import os
import sys

try:
    import psycopg2
except ImportError:
    print("install psycopg2-binary first"); sys.exit(1)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set"); return 2

    conn = psycopg2.connect(url)
    cur = conn.cursor()

    print("=" * 60)
    print("1. daily_prices coverage")
    print("=" * 60)
    cur.execute("""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT ticker) AS tickers,
            MIN(trade_date) AS earliest,
            MAX(trade_date) AS latest
        FROM daily_prices
    """)
    r, t, earliest, latest = cur.fetchone()
    print(f"  rows       : {r:,}")
    print(f"  tickers    : {t}")
    print(f"  earliest   : {earliest}")
    print(f"  latest     : {latest}")

    print()
    print("=" * 60)
    print("2. Per-period lookup test — RELIANCE close price at each period_end")
    print("=" * 60)
    cur.execute("""
        SELECT period_end, period_type
        FROM financials WHERE ticker = 'RELIANCE'
        ORDER BY period_end DESC LIMIT 8
    """)
    periods = cur.fetchall()
    for pe_end, pt in periods:
        cur.execute("""
            SELECT trade_date, close_price, adj_close
            FROM daily_prices
            WHERE ticker = 'RELIANCE' AND trade_date <= %s
            ORDER BY trade_date DESC LIMIT 1
        """, (pe_end,))
        row = cur.fetchone()
        if row:
            print(f"  {pe_end} ({pt:>9}) -> {row[0]}  close={row[1]}  adj={row[2]}")
        else:
            print(f"  {pe_end} ({pt:>9}) -> NO daily_prices row at or before")

    print()
    print("=" * 60)
    print("3. How far back does daily_prices go per ticker? (sample)")
    print("=" * 60)
    cur.execute("""
        SELECT ticker, MIN(trade_date) AS first_date, COUNT(*) AS n
        FROM daily_prices
        WHERE ticker IN ('RELIANCE','TCS','HDFCBANK','INFY','ITC','BAJFINANCE')
        GROUP BY ticker ORDER BY ticker
    """)
    for t, first, n in cur.fetchall():
        print(f"  {t:<12}  first={first}  rows={n}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
