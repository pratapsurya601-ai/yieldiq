"""Apply the unit normalization derived by
`scripts/audit_shares_outstanding_units.py` — write `suggested_raw` to
`financials.shares_outstanding_raw` for every row the audit could
classify.

`--dry-run` is the default. To write, pass `--apply`.

Usage:
    DATABASE_URL=... python scripts/audit_shares_outstanding_units.py \
        --out reports/shares_outstanding_audit.csv

    DATABASE_URL=... python scripts/normalize_shares_outstanding.py \
        --in reports/shares_outstanding_audit.csv          # dry-run
    DATABASE_URL=... python scripts/normalize_shares_outstanding.py \
        --in reports/shares_outstanding_audit.csv --apply  # writes
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def _connect():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _iter_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            yield r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path",
                    default="reports/shares_outstanding_audit.csv",
                    help="audit CSV produced by audit_shares_outstanding_units")
    ap.add_argument("--apply", action="store_true",
                    help="write changes; default is dry-run")
    ap.add_argument("--unit-allowlist",
                    default="raw,lakh,crore,thousands,million",
                    help="comma-separated inferred_unit values to write")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found — run "
              f"scripts/audit_shares_outstanding_units.py first",
              file=sys.stderr)
        return 2

    allowed = {u.strip() for u in args.unit_allowlist.split(",") if u.strip()}
    engine = _connect()

    written = 0
    skipped_unknown = 0
    skipped_missing = 0
    seen = 0

    update_sql = text(
        """
        UPDATE financials
           SET shares_outstanding_raw = :raw
         WHERE ticker      = :ticker
           AND period_end  = :period_end
           AND period_type = :period_type
        """
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] reading {in_path}")

    with engine.begin() as conn:
        for r in _iter_rows(in_path):
            seen += 1
            unit = (r.get("inferred_unit") or "").strip()
            raw = r.get("suggested_raw") or ""
            if unit not in allowed:
                skipped_unknown += 1
                continue
            if not raw:
                skipped_missing += 1
                continue
            try:
                raw_val = float(raw)
            except (TypeError, ValueError):
                skipped_missing += 1
                continue
            # Sanity: anything < 1e6 raw shares is almost certainly
            # itself a unit error in the audit. Refuse to write.
            if raw_val < 1_000_000:
                skipped_missing += 1
                continue
            if args.apply:
                conn.execute(update_sql, {
                    "raw": raw_val,
                    "ticker": r["ticker"],
                    "period_end": r["period_end"],
                    "period_type": r["period_type"],
                })
            written += 1
        if not args.apply:
            # Roll the tx back even though we didn't issue any
            # statements; engine.begin() will commit otherwise.
            conn.rollback()

    print("=" * 60)
    print(f"[{mode}] rows seen         : {seen:,}")
    print(f"[{mode}] rows {'written' if args.apply else 'would-write'}: "
          f"{written:,}")
    print(f"[{mode}] skipped (unit)    : {skipped_unknown:,}")
    print(f"[{mode}] skipped (no raw)  : {skipped_missing:,}")
    if not args.apply:
        print("[DRY-RUN] no changes committed. re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
