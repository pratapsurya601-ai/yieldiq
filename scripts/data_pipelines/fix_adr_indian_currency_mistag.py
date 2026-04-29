#!/usr/bin/env python
"""Repair the v50-class currency mistag re-introduced by today's NSE backfill.

Symptom (verified on prod Neon, 2026-04-29 evening):
  15 Indian-primary IT/pharma tickers have rows with currency='USD' but
  revenue values in INR Crores. Example: INFY FY25 revenue=162,990 (matches
  actual ₹1,62,990 Cr) but currency tag says USD. The DCF then divides
  free_cash_flow=408.8 (also wrong magnitude — likely USD millions) by
  ~415 Cr shares ≈ ₹0.98/share → terminal multiple → FV ≈ ₹16.72.

Three column-level corruptions observed in the same row:
  1. currency='USD' but revenue/CFO are in INR Crores (correct)
  2. capex magnitude ≈ USD millions (e.g. INFY -26.6 vs real ~₹2,000 Cr)
  3. free_cash_flow magnitude similarly broken (288.2 vs real ~₹23,000 Cr)

Both yfinance and NSE_XBRL ingestion paths exhibit the bug for these
tickers because both copy financialCurrency='USD' from the wrong filing.

This script is idempotent. Per-ticker explicit allow-list — no heuristic
re-tag of the wider table. Re-tags currency, nulls capex/FCF where they
look magnitude-inconsistent with revenue/CFO; the DCF will then fall back
to revenue × historical FCF margin or compute FCF = CFO - capex once
the upstream ingest is patched (separate work).

Run:
    DATABASE_URL=$(sed -n '2p' /path/to/.env.local) \\
        python scripts/data_pipelines/fix_adr_indian_currency_mistag.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

# All 15 tickers confirmed via prod query. All Indian-primary listed on NSE/BSE.
# Excludes US-primary ADRs (SIFY, MMYT, WIT, HDB, IBN, TTM, RDY) which
# legitimately report USD on yfinance — those are NOT in our `financials`
# table because YieldIQ's universe is Indian-primary listings only.
AFFECTED_TICKERS = (
    "COFORGE", "CYIENT", "DIVISLAB", "HCLTECH", "INFY", "KPITTECH",
    "LAURUSLABS", "LTIM", "MASTEK", "MPHASIS", "OFSS", "PERSISTENT",
    "TATAELXSI", "TECHM", "WIPRO",
)


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
            # Step 1: count current mistagged rows.
            cur.execute("""
                SELECT ticker, COUNT(*)
                  FROM financials
                 WHERE ticker = ANY(%s) AND currency = 'USD'
                 GROUP BY ticker ORDER BY ticker
            """, (list(AFFECTED_TICKERS),))
            before = cur.fetchall()
            total_before = sum(c for _, c in before)
            print(f"Before: {total_before} rows currency='USD' across {len(before)} tickers")
            for t, c in before:
                print(f"  {t}: {c}")

            # Step 2: re-tag currency.
            sql_retag = """
                UPDATE financials SET currency = 'INR'
                 WHERE ticker = ANY(%s) AND currency = 'USD'
            """
            # Step 3: null FCF where magnitude inconsistent vs CFO.
            #   Heuristic: |FCF| < 10% × |CFO| AND |CFO| > 100 (Cr)
            #   This catches the 288.2 vs 25,210 case for INFY without
            #   touching genuinely small-FCF rows (DIVISLAB FCF=215 vs
            #   CFO=1653 = 13% — left intact).
            sql_null_fcf = """
                UPDATE financials SET free_cash_flow = NULL
                 WHERE ticker = ANY(%s)
                   AND cfo IS NOT NULL
                   AND ABS(cfo) > 100
                   AND free_cash_flow IS NOT NULL
                   AND ABS(free_cash_flow) < 0.10 * ABS(cfo)
            """
            # Step 3b: null CFO where magnitude wildly low vs revenue.
            #   Real IT/pharma CFO is 10-25% of revenue. INFY FY25 has
            #   cfo=435 vs revenue=162,990 (0.27%) — clearly USD millions
            #   leak. Catches the case where both CFO and FCF were
            #   corrupted in the same row (Step 3 alone misses this).
            sql_null_cfo = """
                UPDATE financials SET cfo = NULL, free_cash_flow = NULL
                 WHERE ticker = ANY(%s)
                   AND revenue IS NOT NULL AND revenue > 1000
                   AND cfo IS NOT NULL
                   AND ABS(cfo) < 0.02 * revenue
            """
            # Step 4: null capex where magnitude wildly low vs revenue.
            #   Real IT/pharma capex is typically 0.5%-15% of revenue.
            #   INFY rows show capex≈26 vs revenue≈162,990 → 0.016% (USD M leak).
            sql_null_capex = """
                UPDATE financials SET capex = NULL
                 WHERE ticker = ANY(%s)
                   AND revenue IS NOT NULL AND revenue > 1000
                   AND capex IS NOT NULL
                   AND ABS(capex) < 0.005 * revenue
            """

            if args.dry_run:
                print("\n[dry-run] would execute:")
                print("  " + sql_retag.strip())
                print("  " + sql_null_fcf.strip())
                print("  " + sql_null_capex.strip())
                return 0

            cur.execute(sql_retag, (list(AFFECTED_TICKERS),))
            n_retag = cur.rowcount
            cur.execute(sql_null_fcf, (list(AFFECTED_TICKERS),))
            n_null_fcf = cur.rowcount
            cur.execute(sql_null_cfo, (list(AFFECTED_TICKERS),))
            n_null_cfo = cur.rowcount
            cur.execute(sql_null_capex, (list(AFFECTED_TICKERS),))
            n_null_capex = cur.rowcount

            cx.commit()
            print(f"\nRe-tagged currency USD->INR: {n_retag} rows")
            print(f"Nulled free_cash_flow (FCF<<CFO): {n_null_fcf} rows")
            print(f"Nulled CFO+FCF (CFO<<revenue):    {n_null_cfo} rows")
            print(f"Nulled capex (|capex|<0.5% rev):  {n_null_capex} rows")

            # Step 5: verify INFY post-fix.
            cur.execute("""
                SELECT period_end, currency, revenue, cfo, capex, free_cash_flow
                  FROM financials
                 WHERE ticker='INFY' AND period_type='annual'
                 ORDER BY period_end DESC LIMIT 4
            """)
            print("\nINFY annual rows after fix:")
            for r in cur.fetchall():
                print(f"  {r}")

            # Step 6: confirm no rows still currency='USD' for affected tickers.
            cur.execute("""
                SELECT ticker, COUNT(*) FROM financials
                 WHERE ticker = ANY(%s) AND currency='USD'
                 GROUP BY ticker
            """, (list(AFFECTED_TICKERS),))
            remaining = cur.fetchall()
            if remaining:
                print(f"\nWARNING: {sum(c for _,c in remaining)} rows still USD-tagged:")
                for t, c in remaining:
                    print(f"  {t}: {c}")
                return 1
            print("\nAll 15 tickers fully re-tagged. Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
