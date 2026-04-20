"""Diagnose why ratio_history.pe_ratio and ev_ebitda are 0% covered.

Usage:
    DATABASE_URL=... python scripts/diagnose_market_metrics.py

Prints:
  1. Column population counts on market_metrics (how many rows have PE/PB/EV etc.)
  2. Recent rows for a sample ticker
  3. Whether the ratio_history builder's point-in-time lookup is finding ANY
     market_metrics row per period_end for a sample ticker
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
    print("1. market_metrics column population")
    print("=" * 60)
    cur.execute("""
        SELECT
            COUNT(*)                                      AS total_rows,
            COUNT(market_cap_cr)                          AS with_mcap,
            COUNT(pe_ratio)                               AS with_pe,
            COUNT(pb_ratio)                               AS with_pb,
            COUNT(ev_cr)                                  AS with_ev,
            COUNT(ev_ebitda)                              AS with_ev_ebitda,
            COUNT(dividend_yield)                         AS with_dy,
            MAX(trade_date)                               AS latest
        FROM market_metrics
    """)
    total, mcap, pe, pb, ev, ev_e, dy, latest = cur.fetchone()
    print(f"  total rows            : {total}")
    print(f"  with market_cap_cr    : {mcap}   ({mcap/total:.1%})")
    print(f"  with pe_ratio         : {pe}     ({pe/total:.1%})")
    print(f"  with pb_ratio         : {pb}     ({pb/total:.1%})")
    print(f"  with ev_cr            : {ev}     ({ev/total:.1%})")
    print(f"  with ev_ebitda        : {ev_e}   ({ev_e/total:.1%})")
    print(f"  with dividend_yield   : {dy}     ({dy/total:.1%})")
    print(f"  latest trade_date     : {latest}")

    print()
    print("=" * 60)
    print("2. Sample: last 3 RELIANCE market_metrics rows")
    print("=" * 60)
    cur.execute("""
        SELECT trade_date, market_cap_cr, pe_ratio, pb_ratio, ev_ebitda, dividend_yield
        FROM market_metrics
        WHERE ticker = 'RELIANCE'
        ORDER BY trade_date DESC
        LIMIT 3
    """)
    rows = cur.fetchall()
    if not rows:
        print("  (no RELIANCE rows at all)")
    else:
        for d, m, p, b, e, y in rows:
            print(f"  {d}  mcap={m}  pe={p}  pb={b}  ev/e={e}  dy={y}")

    print()
    print("=" * 60)
    print("3. Point-in-time lookup test for RELIANCE financials periods")
    print("=" * 60)
    cur.execute("""
        SELECT period_end, period_type
        FROM financials WHERE ticker = 'RELIANCE'
        ORDER BY period_end DESC LIMIT 5
    """)
    periods = cur.fetchall()
    if not periods:
        print("  (no financials for RELIANCE)")
    else:
        for pe_end, pt in periods:
            cur.execute("""
                SELECT trade_date, market_cap_cr, pe_ratio, ev_ebitda
                FROM market_metrics
                WHERE ticker = 'RELIANCE' AND trade_date <= %s
                ORDER BY trade_date DESC LIMIT 1
            """, (pe_end,))
            mm = cur.fetchone()
            if mm:
                print(f"  {pe_end} ({pt:>9}) -> mm {mm[0]}  mcap={mm[1]}  pe={mm[2]}  ev/e={mm[3]}")
            else:
                print(f"  {pe_end} ({pt:>9}) -> NO market_metrics row at or before period_end")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
