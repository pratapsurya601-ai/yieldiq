"""Relabel sector for tickers that were mis-classified as insurance
in the 2026-05-16 insurance-cohort recon.

Background
----------
The insurance-cohort recon flagged three tickers as members of the
"insurance" cohort that are not insurance businesses:

  - GOCOLORS : Go Fashion (India) — apparel/retail
  - MEDPLUS  : MedPlus Health Services — pharmacy retail
  - SBICARD  : SBI Cards and Payment Services — NBFC / credit cards

For each, this script:
  1. Reads the current `stocks.sector` value.
  2. Compares to a proposed target chosen to match the sector label
     already used by close-peer tickers (see PEER_REFERENCE).
  3. In --dry-run (default), prints the proposed change.
  4. In --apply, executes the UPDATE.

The proposed targets match the labels already used by peers in the
`stocks` table:

  GOCOLORS  -> "Consumer Cyclical"     (peers: ABFRL, TRENT, PAGEIND)
  MEDPLUS   -> "Pharma"                (peers: APOLLOHOSP, FORTIS, RAINBOW)
  SBICARD   -> "Financial Services"    (peers: BAJFINANCE, BAJAJFINSV, CHOLAFIN)

If the current sector already matches the proposed target, the row
is reported as "already-correct" and not touched.

The script also runs an audit query for any OTHER active tickers
whose `sector` or `industry` ILIKE '%insurance%' but whose company
name suggests a non-insurance business — these are reported for
manual review and NOT auto-relabeled.

Usage
-----
  python scripts/relabel_misclassified_insurers.py --dry-run
  python scripts/relabel_misclassified_insurers.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


# (ticker, proposed_sector, rationale, peer_examples)
TARGETS: list[tuple[str, str, str, str]] = [
    (
        "GOCOLORS",
        "Consumer Cyclical",
        "Apparel retail (Go Fashion). Not insurance.",
        "ABFRL, TRENT, PAGEIND",
    ),
    (
        "MEDPLUS",
        "Pharma",
        "Pharmacy retail / healthcare services. Not insurance.",
        "APOLLOHOSP, FORTIS, RAINBOW",
    ),
    (
        "SBICARD",
        "Financial Services",
        "NBFC / credit cards. Not insurance.",
        "BAJFINANCE, BAJAJFINSV, CHOLAFIN",
    ),
]


def _build_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def survey(engine) -> list[dict]:
    out: list[dict] = []
    with engine.connect() as conn:
        for ticker, target, rationale, peers in TARGETS:
            row = conn.execute(
                text(
                    "SELECT ticker, company_name, sector, industry "
                    "FROM stocks WHERE ticker = :t"
                ),
                {"t": ticker},
            ).fetchone()
            if row is None:
                out.append({
                    "ticker": ticker,
                    "found": False,
                    "current": None,
                    "target": target,
                    "rationale": rationale,
                    "peers": peers,
                    "action": "skip — ticker not in stocks",
                })
                continue
            current_sector = row[2]
            if current_sector == target:
                action = "already-correct (no-op)"
            else:
                action = f"UPDATE sector: {current_sector!r} -> {target!r}"
            out.append({
                "ticker": ticker,
                "found": True,
                "company_name": row[1],
                "current": current_sector,
                "industry": row[3],
                "target": target,
                "rationale": rationale,
                "peers": peers,
                "action": action,
            })
    return out


def apply_updates(engine, plan: list[dict]) -> int:
    written = 0
    with engine.begin() as conn:
        for row in plan:
            if not row["found"]:
                continue
            if row["current"] == row["target"]:
                continue
            res = conn.execute(
                text(
                    "UPDATE stocks SET sector = :target, "
                    "updated_at = NOW() "
                    "WHERE ticker = :t AND sector IS DISTINCT FROM :target"
                ),
                {"target": row["target"], "t": row["ticker"]},
            )
            written += res.rowcount or 0
    return written


def audit_other_insurance_labeled(engine) -> list[tuple]:
    """Report any other active tickers whose sector OR industry
    mentions 'insurance' — for the user to audit whether each row
    is a real insurer or a further mis-tag."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ticker, company_name, sector, industry "
                "FROM stocks "
                "WHERE is_active = true "
                "  AND (sector ILIKE '%insurance%' "
                "       OR industry ILIKE '%insurance%') "
                "ORDER BY ticker"
            )
        ).fetchall()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only (default).")
    args = parser.parse_args()
    do_apply = bool(args.apply) and not bool(args.dry_run)

    engine = _build_engine()
    plan = survey(engine)

    print("── Mis-classified insurance recon: proposed relabels ──")
    for row in plan:
        print(f"  {row['ticker']:10s}")
        if not row["found"]:
            print(f"     {row['action']}")
            continue
        print(f"     company   : {row.get('company_name', '')}")
        print(f"     industry  : {row.get('industry', '')}")
        print(f"     current   : {row['current']!r}")
        print(f"     target    : {row['target']!r}")
        print(f"     peers     : {row['peers']}")
        print(f"     rationale : {row['rationale']}")
        print(f"     action    : {row['action']}")

    print("\n── Audit: ALL active tickers with 'insurance' in sector or industry ──")
    audit_rows = audit_other_insurance_labeled(engine)
    for r in audit_rows:
        print(f"  {r[0]:14s} | {(r[1] or '')[:45]:45s} | {r[2]:25s} | {r[3] or ''}")
    print(f"  total: {len(audit_rows)}")
    print("  (review manually — these are the rows treated as 'insurance' "
          "by any downstream cohort that filters on sector/industry ILIKE "
          "'%insurance%'.)")

    print(f"\n  mode : {'APPLY' if do_apply else 'DRY-RUN'}")
    if not do_apply:
        print("(dry-run; no rows changed)")
        return 0

    n = apply_updates(engine, plan)
    print(f"  rows updated : {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
