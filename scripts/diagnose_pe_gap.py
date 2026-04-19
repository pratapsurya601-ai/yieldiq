"""Why is PE coverage stuck at 6% when daily_prices has 500 tickers?

Breaks down the ratio_history × financials × daily_prices × shares_outstanding
space to find which filter is dropping rows.

Usage:
    DATABASE_URL=... python scripts/diagnose_pe_gap.py
"""
from __future__ import annotations
import os, sys

try:
    import psycopg2
except ImportError:
    print("pip install psycopg2-binary"); sys.exit(2)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url: print("DATABASE_URL not set"); return 2
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    conn = psycopg2.connect(url.replace("postgresql://", "postgres://", 1))
    cur = conn.cursor()

    print("=" * 66)
    print("Funnel — why does PE end up on only 6% of ratio_history rows?")
    print("=" * 66)

    cur.execute("SELECT COUNT(*) FROM ratio_history")
    total_rh = cur.fetchone()[0]
    print(f"  ratio_history rows                           : {total_rh:,}")

    cur.execute("""
        SELECT COUNT(*) FROM ratio_history rh
        JOIN financials f USING (ticker, period_end, period_type)
        WHERE f.shares_outstanding IS NOT NULL
          AND f.shares_outstanding > 0
          AND f.pat IS NOT NULL
          AND f.pat > 0
    """)
    n_with_primitives = cur.fetchone()[0]
    print(f"  … with shares_outstanding > 0 and pat > 0    : {n_with_primitives:,}")

    cur.execute("""
        SELECT COUNT(*) FROM ratio_history rh
        JOIN financials f USING (ticker, period_end, period_type)
        WHERE f.shares_outstanding IS NOT NULL AND f.shares_outstanding > 0
          AND f.pat IS NOT NULL AND f.pat > 0
          AND EXISTS (SELECT 1 FROM daily_prices dp WHERE dp.ticker = rh.ticker)
    """)
    n_with_dp_any = cur.fetchone()[0]
    print(f"  … AND ticker has ANY daily_prices row        : {n_with_dp_any:,}")

    cur.execute("""
        SELECT COUNT(*) FROM ratio_history rh
        JOIN financials f USING (ticker, period_end, period_type)
        WHERE f.shares_outstanding IS NOT NULL AND f.shares_outstanding > 0
          AND f.pat IS NOT NULL AND f.pat > 0
          AND EXISTS (
              SELECT 1 FROM daily_prices dp
              WHERE dp.ticker = rh.ticker
                AND dp.trade_date <= rh.period_end
                AND dp.trade_date >= (rh.period_end - interval '180 days')
          )
    """)
    n_within_180d = cur.fetchone()[0]
    print(f"  … AND a price exists within 180d before p/e  : {n_within_180d:,}")

    print()
    print("=" * 66)
    print("Coverage of PE actually stored in ratio_history")
    print("=" * 66)
    cur.execute("SELECT COUNT(DISTINCT ticker), COUNT(*) FROM ratio_history WHERE pe_ratio IS NOT NULL")
    t, r = cur.fetchone()
    print(f"  tickers with any PE row : {t}")
    print(f"  rows with PE            : {r}")

    print()
    print("=" * 66)
    print("Sample — ratio_history for 5 diverse tickers, all 4 periods")
    print("=" * 66)
    for tkr in ("RELIANCE", "TCS", "INFY", "ITC", "HINDUNILVR"):
        cur.execute("""
            SELECT period_end,
                   (SELECT shares_outstanding FROM financials f
                    WHERE f.ticker=rh.ticker AND f.period_end=rh.period_end
                      AND f.period_type=rh.period_type LIMIT 1) AS shares,
                   (SELECT pat FROM financials f
                    WHERE f.ticker=rh.ticker AND f.period_end=rh.period_end
                      AND f.period_type=rh.period_type LIMIT 1) AS pat,
                   (SELECT close_price FROM daily_prices dp
                    WHERE dp.ticker=rh.ticker AND dp.trade_date<=rh.period_end
                    ORDER BY trade_date DESC LIMIT 1) AS latest_price_before,
                   (SELECT trade_date FROM daily_prices dp
                    WHERE dp.ticker=rh.ticker AND dp.trade_date<=rh.period_end
                    ORDER BY trade_date DESC LIMIT 1) AS price_date,
                   rh.pe_ratio, rh.market_cap_cr
            FROM ratio_history rh
            WHERE rh.ticker = %s AND rh.period_type = 'annual'
            ORDER BY period_end
        """, (tkr,))
        rows = cur.fetchall()
        if not rows:
            print(f"\n  {tkr}: no annual rows"); continue
        print(f"\n  {tkr}")
        for pe_end, shares, pat, px, pxd, pe_ratio, mcap in rows:
            gap = (pe_end - pxd).days if pxd else "?"
            print(f"    {pe_end}  shares={shares}  pat={pat}  px@{pxd}={px} (gap {gap}d)  mcap={mcap}  PE={pe_ratio}")

    cur.close(); conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
