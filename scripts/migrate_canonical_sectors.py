"""
Populate `stocks.canonical_sector` and `stocks.canonical_industry`
from the raw (sector, industry) pair using
`backend.services.sector_taxonomy.to_canonical()`.

Background
----------
The 2026-05-16 audit found 30 distinct values in `stocks.sector`
where the canonical taxonomy only allows 13. Migration
035_canonical_sector_column.sql adds the two new columns; this
script backfills them.

Unlike the older `scripts/migrate_sector_canonical.py` (which
rewrites the raw `sector` column in-place), this script is purely
additive — the raw `sector` and `industry` columns are never
modified. Downstream cohort queries should switch to
`canonical_sector` (the sector aggregator already prefers it when
present).

Special handling
----------------
* Per-ticker overrides for the audit's known mis-tags live in
  TICKER_CANONICAL_OVERRIDES (in sector_taxonomy.py):
    POLICYBZR, RELIGARE     -> Financial Services
    HDFCLIFE, ICICIGI, SBILIFE, ICICIPRULI, LICI, MAXLIFE,
    STARHEALTH, GICRE, NIACL -> Financial Services / Insurance
    GOCOLORS                -> Consumer Durables / Apparel Retail
    MEDPLUS                 -> Pharma / Pharmaceutical Retailers
    SBICARD                 -> Financial Services / NBFC

* Rows with NULL raw sector get canonical_sector = 'Unknown' (NOT
  NULL) so cohort queries never have to special-case NULL. Net-new
  sector discovery (yfinance / EQUITY_L.csv) is intentionally NOT
  done here — the fundamentals job already does that, and running
  yfinance against hundreds of tickers from a one-shot can
  rate-limit production.

Modes
-----
  --dry-run   (default)   read-only, prints sector → count summary
                          and the rewrite distribution.
  --apply                 write canonical_sector / canonical_industry.

Idempotency
-----------
Safe to re-run: each row is rewritten to the same canonical pair
the mapping function produces.

Apply on Neon
-------------
  python scripts/migrate_canonical_sectors.py --dry-run
  python scripts/migrate_canonical_sectors.py --apply
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter

from sqlalchemy import create_engine, text


def _build_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _compute_rows(rows):
    """Yield (ticker, canon_sector, canon_industry) for every input row.

    Imported lazily so a `--dry-run` against a stub DB (or tests) does
    not require the DB driver before the taxonomy module is reachable.
    """
    from backend.services.sector_taxonomy import to_canonical

    for ticker, raw_sector, raw_industry in rows:
        canon_sec, canon_ind = to_canonical(raw_sector, raw_industry, ticker)
        yield ticker, canon_sec, canon_ind


def survey(engine) -> tuple[Counter, Counter, int]:
    """Return (sector_distribution, transitions, total_rows).

    sector_distribution : Counter[canonical_sector] -> n
    transitions         : Counter[(raw_sector, canonical_sector)] -> n
    total_rows          : int
    """
    sector_dist: Counter = Counter()
    transitions: Counter = Counter()
    n = 0
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ticker, sector, industry FROM stocks "
                "WHERE is_active = TRUE"
            )
        ).fetchall()
    for ticker, canon_sec, _canon_ind in _compute_rows(rows):
        # Re-derive raw sector for the transition counter without
        # calling to_canonical twice — small enough that it's cheap.
        sector_dist[canon_sec] += 1
        n += 1
    # Build transitions in a second pass (kept separate for clarity).
    for ticker, raw_sector, _raw_industry in rows:
        from backend.services.sector_taxonomy import to_canonical
        canon_sec, _ = to_canonical(raw_sector, _raw_industry, ticker)
        transitions[(raw_sector or "<null>", canon_sec)] += 1
    return sector_dist, transitions, n


def apply_canonical(engine) -> int:
    written = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT ticker, sector, industry FROM stocks "
                "WHERE is_active = TRUE"
            )
        ).fetchall()
        for ticker, canon_sec, canon_ind in _compute_rows(rows):
            res = conn.execute(
                text(
                    """
                    UPDATE stocks
                       SET canonical_sector = :sec,
                           canonical_industry = :ind
                     WHERE ticker = :tkr
                       AND (
                            canonical_sector IS DISTINCT FROM :sec
                         OR canonical_industry IS DISTINCT FROM :ind
                       )
                    """
                ),
                {"sec": canon_sec, "ind": canon_ind, "tkr": ticker},
            )
            written += res.rowcount or 0
    return written


def _print_distribution(dist: Counter, total: int) -> None:
    print("-- canonical_sector distribution --")
    for sec, n in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])):
        pct = (100.0 * n / total) if total else 0.0
        print(f"  {sec:25s} : {n:5d}  ({pct:5.1f}%)")


def _print_transitions(trans: Counter, head: int = 40) -> None:
    print(f"-- top {head} raw -> canonical transitions --")
    for (raw, canon), n in trans.most_common(head):
        print(f"  {raw!r:40s} -> {canon!r:25s} : {n}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only (default).")
    args = parser.parse_args()
    apply = bool(args.apply) and not bool(args.dry_run)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    engine = _build_engine()
    dist, trans, total = survey(engine)
    _print_distribution(dist, total)
    _print_transitions(trans)
    print(f"  total active rows       : {total}")
    print(f"  mode                    : {'APPLY' if apply else 'DRY-RUN'}")
    if not apply:
        print("(dry-run; no rows changed)")
        return 0

    n = apply_canonical(engine)
    print(f"  stocks rows updated     : {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
