"""
Dedup `analysis_cache` rows that were stored under both bare and
.NS-suffixed keys for the same Indian ticker.

Background
----------
The 2026-05-16 audit found the table had 5,062 rows but only 3,141
unique tickers — every Indian symbol was stored twice (FOO and
FOO.NS) because the writer used the raw ticker string as the PK
and two callers passed two different surface forms. The Python
writer is now fixed to funnel every read/write through
`_canonical_cache_key` (see backend/services/analysis_cache_service.py),
but the legacy duplicates remain and need a one-shot collapse.

This script
-----------
1. Pulls every `(ticker, computed_at)` row from `analysis_cache`.
2. Bucket by canonical form (uses the same `_canonicalize_ticker`
   helper the live writer now uses, so the bucket key matches what
   future writes will produce).
3. For each bucket with > 1 row: keep the row with the most-recent
   `computed_at` and delete the rest.
4. Bonus: if the surviving row is NOT stored under the canonical
   key, rename it (DELETE + INSERT under the canonical key) so
   subsequent canonical reads land on the surviving payload.

Modes
-----
  --dry-run   (default)   read-only, prints before/after counts and
                          a per-bucket plan, performs ZERO writes.
  --apply                 actually delete/rename the rows. Wrapped
                          in a single transaction per bucket so a
                          mid-run failure leaves the table in a
                          consistent state.

Idempotency
-----------
Safe to run twice. After a successful --apply pass, every bucket
has size 1 and the surviving row's key already equals the canonical
form, so a second pass finds nothing to do and exits clean.

Apply on Neon
-------------
  python scripts/migrate_dedup_analysis_cache.py --dry-run
  python scripts/migrate_dedup_analysis_cache.py --apply
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy import create_engine, text


def _build_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _canonicalize(raw: str) -> str:
    """Reuse the same canonicalizer the live writer uses, so the
    bucket key produced here matches what `save_cached` writes after
    the fix lands."""
    try:
        from backend.services.analysis.utils import _canonicalize_ticker
        return _canonicalize_ticker(raw)
    except Exception:
        # Standalone fallback: bare-Indian-suffix heuristic. Strips
        # whitespace + uppercases. Without DB access we can't tell
        # bare US from bare Indian, so we leave bare keys alone — the
        # live writer's better cache will handle that on first call.
        if not raw:
            return raw
        return str(raw).strip().upper()


def collect_buckets(engine) -> Dict[str, List[Tuple[str, object]]]:
    """Return canonical_key -> [(ticker, computed_at), ...]."""
    buckets: Dict[str, List[Tuple[str, object]]] = defaultdict(list)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ticker, computed_at FROM analysis_cache")
        ).fetchall()
    for ticker, computed_at in rows:
        canonical = _canonicalize(ticker)
        buckets[canonical].append((ticker, computed_at))
    return buckets


def plan(buckets) -> Tuple[int, int, int, List[Tuple[str, str, List[str]]]]:
    """
    Return (total_rows, kept_rows, deleted_rows, actions).
    actions = list of (canonical_key, surviving_ticker, [tickers_to_delete]).
    """
    total = sum(len(v) for v in buckets.values())
    actions: List[Tuple[str, str, List[str]]] = []
    deleted = 0
    for canonical, rows in buckets.items():
        if len(rows) <= 1:
            # Single row but key may not be canonical; only act if
            # rename would actually change the key.
            if rows and rows[0][0] != canonical:
                actions.append((canonical, rows[0][0], []))
            continue
        # Sort newest first
        rows_sorted = sorted(
            rows,
            key=lambda r: (r[1] is None, r[1]),
            reverse=True,
        )
        survivor = rows_sorted[0][0]
        losers = [r[0] for r in rows_sorted[1:]]
        deleted += len(losers)
        actions.append((canonical, survivor, losers))
    kept = total - deleted
    return total, kept, deleted, actions


def apply_plan(engine, actions) -> None:
    """Execute the plan one bucket at a time inside its own
    transaction. Failure on one bucket does not roll back others."""
    for canonical, survivor, losers in actions:
        try:
            with engine.begin() as conn:
                if losers:
                    # IN(:tickers) with bindparam expanding works on
                    # both Postgres and SQLite (the test backend).
                    from sqlalchemy import bindparam
                    stmt = text(
                        "DELETE FROM analysis_cache "
                        "WHERE ticker IN :tickers"
                    ).bindparams(bindparam("tickers", expanding=True))
                    conn.execute(stmt, {"tickers": losers})
                if survivor != canonical:
                    # Rename: copy survivor row under canonical key,
                    # then drop the old key. ON CONFLICT skips if a
                    # canonical row somehow already exists (race-safe).
                    conn.execute(
                        text(
                            """
                            INSERT INTO analysis_cache
                                (ticker, payload, computed_at,
                                 cache_version, compute_ms)
                            SELECT :canonical, payload, computed_at,
                                   cache_version, compute_ms
                            FROM analysis_cache
                            WHERE ticker = :survivor
                            ON CONFLICT (ticker) DO NOTHING
                            """
                        ),
                        {"canonical": canonical, "survivor": survivor},
                    )
                    conn.execute(
                        text(
                            "DELETE FROM analysis_cache "
                            "WHERE ticker = :survivor"
                        ),
                        {"survivor": survivor},
                    )
        except Exception as exc:
            logging.exception(
                "dedup: bucket %s failed; continuing. %s", canonical, exc
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only (default).")
    parser.add_argument("--verbose", action="store_true",
                        help="Print one line per non-trivial bucket.")
    args = parser.parse_args()
    apply = bool(args.apply) and not bool(args.dry_run)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    engine = _build_engine()
    buckets = collect_buckets(engine)
    total, kept, deleted, actions = plan(buckets)
    rename_count = sum(1 for _, surv, los in actions if surv != _ and not los)
    dedup_count = sum(1 for _, _, los in actions if los)

    print("── analysis_cache dedup plan ────────────────────────────")
    print(f"  rows now              : {total}")
    print(f"  unique canonical keys : {len(buckets)}")
    print(f"  rows after dedup      : {kept}")
    print(f"  rows to delete        : {deleted}")
    print(f"  buckets w/ duplicates : {dedup_count}")
    print(f"  buckets needing rename: {rename_count}")
    print(f"  mode                  : {'APPLY' if apply else 'DRY-RUN'}")

    if args.verbose:
        for canonical, surv, losers in actions:
            if losers or surv != canonical:
                print(f"   - {canonical}: keep={surv} drop={losers}")

    if not apply:
        print("(dry-run; no rows changed)")
        return 0

    apply_plan(engine, actions)

    # Re-collect to confirm.
    after = collect_buckets(engine)
    total_after = sum(len(v) for v in after.values())
    print(f"  rows after apply      : {total_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
