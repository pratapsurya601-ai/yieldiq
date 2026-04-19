"""Quick coverage + sample-peers report. Pastable output.

Usage:
    DATABASE_URL=... python scripts/verify_coverage.py
    DATABASE_URL=... python scripts/verify_coverage.py --ticker TCS
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import psycopg2
except ImportError:
    print("install psycopg2-binary first")
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="RELIANCE")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2

    conn = psycopg2.connect(url)
    cur = conn.cursor()

    # ratio_history coverage
    cur.execute(
        "SELECT COUNT(DISTINCT ticker), COUNT(*),"
        " AVG(CASE WHEN roe IS NOT NULL THEN 1.0 ELSE 0 END),"
        " AVG(CASE WHEN roce IS NOT NULL THEN 1.0 ELSE 0 END),"
        " AVG(CASE WHEN de_ratio IS NOT NULL THEN 1.0 ELSE 0 END),"
        " AVG(CASE WHEN pe_ratio IS NOT NULL THEN 1.0 ELSE 0 END),"
        " AVG(CASE WHEN ev_ebitda IS NOT NULL THEN 1.0 ELSE 0 END)"
        " FROM ratio_history"
    )
    t, rows, roe, roce, de, pe, ev = cur.fetchone()
    print("RATIO_HISTORY")
    print(f"  tickers    : {t}")
    print(f"  rows       : {rows}")
    print(f"  roe  cov   : {roe:.1%}")
    print(f"  roce cov   : {roce:.1%}")
    print(f"  de   cov   : {de:.1%}")
    print(f"  pe   cov   : {pe:.1%}")
    print(f"  ev/e cov   : {ev:.1%}")

    # peer_groups coverage
    cur.execute(
        "SELECT COUNT(DISTINCT ticker), COUNT(*), "
        " COUNT(*) FILTER (WHERE reason = 'same_sub_sector_mcap_proximity'),"
        " COUNT(*) FILTER (WHERE reason = 'same_sector_mcap_proximity'),"
        " COUNT(*) FILTER (WHERE reason = 'same_cap_tier_mcap_proximity')"
        " FROM peer_groups"
    )
    row = cur.fetchone()
    print()
    print("PEER_GROUPS")
    print(f"  tickers    : {row[0]}")
    print(f"  rows       : {row[1]}")
    print(f"  by_sub     : {row[2]}")
    print(f"  by_sector  : {row[3]}")
    print(f"  by_tier    : {row[4]}")

    # sample ticker
    print()
    print(f"SAMPLE PEERS for {args.ticker}")
    cur.execute(
        "SELECT peer_ticker, rank, reason, round(mcap_ratio * 100) / 100.0"
        " FROM peer_groups WHERE ticker = %s ORDER BY rank",
        (args.ticker,),
    )
    sample = cur.fetchall()
    if not sample:
        print(f"  (no peers found for {args.ticker} — expected if it has no market_metrics row)")
    else:
        for peer, rank, reason, ratio in sample:
            print(f"  #{rank:<2} {peer:<12}  {reason:<35}  mcap_ratio={ratio}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
