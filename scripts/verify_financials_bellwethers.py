"""Bellwether-ticker coverage check for the `financials` table.

Exits non-zero if any bellwether ticker fails the gates defined in
PR A's scope contract. Used as a post-backfill smoke test — intended
to be run manually (or in CI, gated by DATABASE_URL presence) after
`phase_c_nse_xbrl.yml` re-dispatches with the extended parser.

Gates (per ticker, applied to the last 5 annual rows):
    1. >= 3 rows have non-null free_cash_flow
    2. >= 4 rows have non-null revenue AND non-null total_assets
    3. YoY revenue swing < 30% (|delta|/prev < 0.30)

Usage
-----
    DATABASE_URL=... python scripts/verify_financials_bellwethers.py
    DATABASE_URL=... python scripts/verify_financials_bellwethers.py --verbose

Output is a compact pass/fail table plus, on --verbose, the raw rows
that produced each verdict. Exit 0 = all tickers pass; exit 1 = any
ticker fails any gate; exit 2 = env / DB error.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:
    import psycopg2
except ImportError:
    print("install psycopg2-binary first", file=sys.stderr)
    sys.exit(2)


BELLWETHERS = [
    "TCS", "RELIANCE", "INFY", "HDFCBANK",
    "BPCL", "ONGC", "IOC", "HPCL",
    "TITAN", "ITC",
]


def _fetch_rows(cur, ticker: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT period_end, revenue, total_assets, free_cash_flow,
               cfo, capex, data_source
        FROM financials
        WHERE ticker = %s AND period_type = 'annual'
        ORDER BY period_end DESC
        LIMIT 5
        """,
        (ticker,),
    )
    cols = ["period_end", "revenue", "total_assets", "fcf", "cfo", "capex", "data_source"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _check(ticker: str, rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Return (pass, reasons). reasons is empty on pass."""
    reasons: list[str] = []
    if not rows:
        return False, [f"no annual rows for {ticker}"]

    fcf_n = sum(1 for r in rows if r["fcf"] is not None)
    if fcf_n < 3:
        reasons.append(f"fcf coverage {fcf_n}/5 (need >=3)")

    both_n = sum(
        1 for r in rows
        if r["revenue"] is not None and r["total_assets"] is not None
    )
    if both_n < 4:
        reasons.append(f"revenue+total_assets coverage {both_n}/5 (need >=4)")

    # YoY revenue swing — iterate oldest→newest and check each pair.
    # Rows come back newest-first, so reverse for readability.
    rev_series = [(r["period_end"], r["revenue"]) for r in reversed(rows)]
    for (_, prev), (pe, curr) in zip(rev_series, rev_series[1:]):
        if prev is None or curr is None or prev == 0:
            continue
        swing = abs(curr - prev) / abs(prev)
        if swing >= 0.30:
            reasons.append(f"yoy revenue swing {swing:.0%} at {pe}")
            break

    return (not reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    try:
        conn = psycopg2.connect(url)
    except Exception as exc:
        print(f"DB connect failed: {exc}", file=sys.stderr)
        return 2
    cur = conn.cursor()

    print(f"{'TICKER':<10} {'VERDICT':<6}  REASONS")
    print("-" * 70)

    any_fail = False
    for t in BELLWETHERS:
        rows = _fetch_rows(cur, t)
        ok, reasons = _check(t, rows)
        verdict = "PASS" if ok else "FAIL"
        if not ok:
            any_fail = True
        reason_s = "; ".join(reasons) if reasons else "-"
        print(f"{t:<10} {verdict:<6}  {reason_s}")
        if args.verbose and rows:
            for r in rows:
                print(
                    f"    {r['period_end']}  rev={r['revenue']}"
                    f"  ta={r['total_assets']}  cfo={r['cfo']}"
                    f"  capex={r['capex']}  fcf={r['fcf']}"
                    f"  src={r['data_source']}"
                )

    cur.close()
    conn.close()
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
