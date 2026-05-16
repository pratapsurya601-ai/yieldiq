"""
Backfill canonical sector labels into `stocks.sector` and into the
`sector` field embedded in `analysis_cache.payload`.

Background
----------
The 2026-05-16 audit found 20 distinct sector labels in the cache
where only the 13 canonical sectors from
`backend/services/sector_taxonomy.py` should ever appear. Examples:
"Banks" / "Financial Services", "IT Services" / "Technology",
"Real Estate" / "Realty", "Pharmaceuticals" / "Healthcare", etc.
The duplication silently broke the sector aggregator (PR #227)
because cohort SQL keys on the canonical label.

In addition, 518 tickers had `stocks.sector = NULL` because the
last yfinance backfill failed for them — that flowed straight into
the cache payload as a missing sector and dropped them out of the
"real verdict" coverage count.

This script
-----------
1. For every `stocks` row whose sector is in `SECTOR_ALIAS_MAP`,
   rewrite to the canonical form.
2. For every `analysis_cache` row whose `payload->>'sector'` is in
   `SECTOR_ALIAS_MAP`, jsonb_set it to the canonical form.
3. NULL handling for `stocks.sector` is intentionally minimal here:
   the script reports the count of NULL rows but does NOT call
   yfinance from this migration (running yfinance against 518
   tickers from a one-shot script can rate-limit production). The
   regular fundamentals job already backfills sectors; this script's
   job is alias normalization, not net-new sector discovery.

Modes
-----
  --dry-run   (default)   read-only, prints per-source mapping counts.
  --apply                 write the canonicalized labels.

Idempotency
-----------
Safe to run twice — once a label is canonical, it is no longer in
the alias map and the WHERE clause excludes it.

Apply on Neon
-------------
  python scripts/migrate_sector_canonical.py --dry-run
  python scripts/migrate_sector_canonical.py --apply
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


def _load_alias_map() -> dict[str, str]:
    """Return the canonical alias map (lowercase keys)."""
    from backend.services.sector_taxonomy import SECTOR_ALIAS_MAP, CANONICAL_SECTORS
    # Sanity: every canonical value should appear in CANONICAL_SECTORS.
    canon = set(CANONICAL_SECTORS)
    for k, v in SECTOR_ALIAS_MAP.items():
        if v not in canon:
            logging.warning(
                "alias %r -> %r is not in CANONICAL_SECTORS; check taxonomy",
                k, v,
            )
    return dict(SECTOR_ALIAS_MAP)


def survey_stocks(engine, alias_map) -> Counter:
    """Return Counter of (raw_sector -> count) of stocks whose
    sector is in the alias map AND not already equal to canonical."""
    counts: Counter = Counter()
    null_count = 0
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT ticker, sector FROM stocks")).fetchall()
    for _t, sector in rows:
        if sector is None:
            null_count += 1
            continue
        canon = alias_map.get(sector.strip().lower())
        if canon and canon != sector:
            counts[(sector, canon)] += 1
    counts[("__null__", "__null__")] = null_count  # piggy-back report
    return counts


def survey_cache(engine, alias_map) -> Counter:
    counts: Counter = Counter()
    null_count = 0
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ticker, payload->>'sector' AS sec FROM analysis_cache")
        ).fetchall()
    for _t, sector in rows:
        if sector is None:
            null_count += 1
            continue
        canon = alias_map.get(sector.strip().lower())
        if canon and canon != sector:
            counts[(sector, canon)] += 1
    counts[("__null__", "__null__")] = null_count
    return counts


def apply_stocks(engine, alias_map) -> int:
    written = 0
    with engine.begin() as conn:
        for raw, canon in {(k, v) for k, v in alias_map.items()}:
            # Match case-insensitively against the raw alias key.
            res = conn.execute(
                text(
                    "UPDATE stocks SET sector = :canon "
                    "WHERE LOWER(TRIM(sector)) = :raw AND sector <> :canon"
                ),
                {"canon": canon, "raw": raw},
            )
            written += res.rowcount or 0
    return written


def apply_cache(engine, alias_map) -> int:
    written = 0
    with engine.begin() as conn:
        for raw, canon in {(k, v) for k, v in alias_map.items()}:
            res = conn.execute(
                text(
                    """
                    UPDATE analysis_cache
                    SET payload = jsonb_set(payload, '{sector}', to_jsonb(:canon::text))
                    WHERE LOWER(TRIM(payload->>'sector')) = :raw
                      AND payload->>'sector' <> :canon
                    """
                ),
                {"canon": canon, "raw": raw},
            )
            written += res.rowcount or 0
    return written


def _print_counts(label: str, counts: Counter) -> None:
    null_n = counts.pop(("__null__", "__null__"), 0)
    print(f"── {label} ──")
    if null_n:
        print(f"  NULL sector rows : {null_n}  (not touched by this script)")
    if not counts:
        print("  (no aliasable rows found)")
        return
    total = sum(counts.values())
    for (raw, canon), n in counts.most_common():
        print(f"  {raw!r:30s} -> {canon!r:25s} : {n}")
    print(f"  total rewrites    : {total}")


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
    alias_map = _load_alias_map()

    stocks_counts = survey_stocks(engine, alias_map)
    cache_counts = survey_cache(engine, alias_map)
    _print_counts("stocks.sector", stocks_counts)
    _print_counts("analysis_cache.payload.sector", cache_counts)

    print(f"  mode              : {'APPLY' if apply else 'DRY-RUN'}")
    if not apply:
        print("(dry-run; no rows changed)")
        return 0

    n_stocks = apply_stocks(engine, alias_map)
    n_cache = apply_cache(engine, alias_map)
    print(f"  stocks rows updated     : {n_stocks}")
    print(f"  cache  rows updated     : {n_cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
