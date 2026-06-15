"""Populate funds.inception_date from the earliest NAV in fund_nav_history.

WHY THIS EXISTS
---------------
The AMFI scheme master (data_pipeline/sources/amfi_scheme_master.py)
deliberately leaves funds.inception_date NULL — AMFI's NAVAll feed has
no launch date, and AMFI publishes no separate machine-readable master.
The earliest NAV date for a scheme is a reliable proxy for its launch
(a fund's NAV series begins at inception), so we derive it here.

    inception_date := MIN(nav_date) over fund_nav_history

This fixes the "Inception —" gap on every fund page AND the internally
inconsistent since-inception return (ret_si), which the returns service
computes off the inception anchor.

DEPENDENCY / CAVEAT
-------------------
Accuracy depends on NAV depth. Run this AFTER the daily-NAV backfill to
true inception (scripts/backfill_mf_nav.py --years 10
--schemes-source funds_table). If NAV only goes back to ~2021, this sets
inception to the earliest AVAILABLE NAV, not the true launch — still
better than NULL, and it auto-corrects on a later run once history
extends. The UPDATE is IDEMPOTENT and only lowers inception_date toward
the true (earlier) value, never raises it.

NOT POPULATED HERE: TER (ter_direct / ter_regular). AMFI publishes the
Total Expense Ratio only as per-AMC HTML/Excel disclosures — there is no
machine-readable feed — so TER needs a dedicated scraper (separate task).

Usage
-----
    DATABASE_URL="..." python scripts/backfill_fund_inception.py --dry-run
    DATABASE_URL="..." python scripts/backfill_fund_inception.py --apply

Read-only by default (prints how many schemes would change); --apply
commits the UPDATE.
"""
from __future__ import annotations

import argparse
import os
import sys

# Rows whose inception_date is NULL, or later than the earliest NAV we
# now hold (i.e. a previous run anchored to shallower history and the NAV
# backfill has since extended further back).
_COUNT_SQL = """
SELECT COUNT(*)
FROM funds f
JOIN (
    SELECT scheme_code, MIN(nav_date) AS min_nav
    FROM fund_nav_history
    GROUP BY scheme_code
) sub ON sub.scheme_code = f.scheme_code
WHERE f.inception_date IS NULL
   OR f.inception_date > sub.min_nav
"""

_UPDATE_SQL = """
UPDATE funds f
SET inception_date = sub.min_nav
FROM (
    SELECT scheme_code, MIN(nav_date) AS min_nav
    FROM fund_nav_history
    GROUP BY scheme_code
) sub
WHERE f.scheme_code = sub.scheme_code
  AND (f.inception_date IS NULL OR f.inception_date > sub.min_nav)
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Populate funds.inception_date from earliest NAV.",
    )
    ap.add_argument(
        "--apply", action="store_true",
        help="commit the UPDATE (default: dry-run, count only)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="count rows that would change; never write (overrides --apply)",
    )
    args = ap.parse_args(argv)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("[fund-inception] DATABASE_URL not set", file=sys.stderr)
        return 2

    import psycopg2  # local import so --help works without the driver

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(_COUNT_SQL)
            to_change = cur.fetchone()[0]
            print(
                f"[fund-inception] {to_change} scheme(s) would get "
                f"inception_date set/corrected from earliest NAV."
            )
            if args.apply and not args.dry_run:
                cur.execute(_UPDATE_SQL)
                conn.commit()
                print(f"[fund-inception] APPLIED — {cur.rowcount} row(s) updated.")
            else:
                print("[fund-inception] dry-run only — pass --apply to commit.")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
