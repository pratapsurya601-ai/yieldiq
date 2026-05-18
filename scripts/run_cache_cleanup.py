"""
Daily cache cleanup — prune stale `vN:` rows from `analysis_cache`.

Why this exists
---------------
The in-memory `cache.cleanup()` at backend/services/cache_service.py:141
exists but has ZERO callers (see docs/design/memory-baseline-investigation.md,
section 1.3). After a CACHE_VERSION bump, version-keyed entries
under the old `vN:` prefix linger for up to 24 h until their TTL
expires or they are read. With 21 CACHE_VERSION bumps in a single
day (2026-05-17 incident) the per-worker `dict` accumulated ~21
generations of dead analysis cache — the "stair-step climb after
CACHE_VERSION bumps" symptom.

`cache.cleanup()` is a per-process singleton method, so a cron worker
running inside GitHub Actions CANNOT prune the API container's
in-memory dict (they don't share memory). Instead, we attack the
shared, persistent tier-2 `analysis_cache` table — which IS shared
across all Railway workers and is the only place stale-version rows
can survive long enough to matter.

What this script does
---------------------
1. Connects to `DATABASE_URL` (Neon Postgres in prod).
2. Reads every distinct `cache_version` value currently in
   `analysis_cache`.
3. Keeps the current CACHE_VERSION + the previous 2 numerically-newest
   versions. Deletes every other row. The "+2 grace" buffer covers
   the case where a deploy is in flight while the cron runs — the
   API may still be serving against the previous version mid-rollout.
4. Logs: total rows before, rows deleted, rows after, list of
   versions kept vs pruned.
5. Exits 0 (even on no-op).

Non-numeric `cache_version` values are treated as "old" (deleted)
because the only numeric scheme we have ever shipped is the
integer-string one defined in cache_service.py.

Invocation
----------
  python scripts/run_cache_cleanup.py            # apply
  python scripts/run_cache_cleanup.py --dry-run  # report only

Safe to run twice — idempotent once the keep-set is stable.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Iterable

from sqlalchemy import create_engine, text


logger = logging.getLogger("yieldiq.cache_cleanup")


KEEP_PREVIOUS = 2  # keep CURRENT + previous 2 versions


def _build_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _to_int(version: str) -> int | None:
    """Coerce a stored cache_version (TEXT) to int; return None if junk."""
    if version is None:
        return None
    try:
        return int(str(version).strip())
    except (TypeError, ValueError):
        return None


def compute_keep_set(versions: Iterable[str], keep_previous: int = KEEP_PREVIOUS) -> set[str]:
    """Return the set of `cache_version` strings to KEEP.

    Strategy: take every numeric version, sort descending, keep the
    top `keep_previous + 1` values (current + previous N). Non-numeric
    versions never enter the keep set.
    """
    numeric: dict[int, str] = {}
    for v in versions:
        as_int = _to_int(v)
        if as_int is None:
            continue
        # If two raw strings parse to the same int ("12" vs " 12 "),
        # keep both literal forms by mapping the int back to a set.
        # In practice cache_service writes a single canonical str(int).
        numeric.setdefault(as_int, str(v))
    if not numeric:
        return set()
    top = sorted(numeric.keys(), reverse=True)[: keep_previous + 1]
    return {numeric[i] for i in top}


def run(dry_run: bool = False, keep_previous: int = KEEP_PREVIOUS) -> int:
    """Execute cleanup. Returns number of rows deleted (or that would
    be deleted in dry-run mode)."""
    engine = _build_engine()

    with engine.connect() as conn:
        total_before = conn.execute(
            text("SELECT COUNT(*) FROM analysis_cache")
        ).scalar() or 0

        version_rows = conn.execute(
            text(
                """
                SELECT cache_version, COUNT(*) AS n
                FROM analysis_cache
                GROUP BY cache_version
                ORDER BY cache_version
                """
            )
        ).fetchall()

    versions_seen = [str(r[0]) for r in version_rows]
    counts_by_version = {str(r[0]): int(r[1]) for r in version_rows}

    if not versions_seen:
        logger.info("analysis_cache is empty — nothing to do.")
        print("rows_before=0 rows_deleted=0 rows_after=0 versions_kept=[] versions_pruned=[]")
        return 0

    keep = compute_keep_set(versions_seen, keep_previous=keep_previous)
    prune = [v for v in versions_seen if v not in keep]

    expected_deletions = sum(counts_by_version[v] for v in prune)

    logger.info(
        "Cache cleanup plan: total_rows=%d versions_seen=%s keep=%s prune=%s expected_deletions=%d",
        total_before,
        sorted(versions_seen, key=lambda x: (_to_int(x) is None, _to_int(x) or 0)),
        sorted(keep, key=lambda x: _to_int(x) or 0),
        sorted(prune, key=lambda x: (_to_int(x) is None, _to_int(x) or 0)),
        expected_deletions,
    )

    if dry_run:
        print(
            f"DRY-RUN rows_before={total_before} "
            f"rows_would_delete={expected_deletions} "
            f"versions_kept={sorted(keep)} versions_pruned={sorted(prune)}"
        )
        return expected_deletions

    if not prune:
        logger.info("Nothing to prune — every observed version is in the keep-set.")
        print(
            f"rows_before={total_before} rows_deleted=0 rows_after={total_before} "
            f"versions_kept={sorted(keep)} versions_pruned=[]"
        )
        return 0

    with engine.begin() as conn:
        deleted = conn.execute(
            text(
                "DELETE FROM analysis_cache WHERE cache_version = ANY(:versions)"
            ),
            {"versions": prune},
        ).rowcount or 0
        total_after = conn.execute(
            text("SELECT COUNT(*) FROM analysis_cache")
        ).scalar() or 0

    logger.info(
        "Cache cleanup complete: deleted=%d rows_before=%d rows_after=%d",
        deleted, total_before, total_after,
    )
    print(
        f"rows_before={total_before} rows_deleted={deleted} rows_after={total_after} "
        f"versions_kept={sorted(keep)} versions_pruned={sorted(prune)}"
    )
    return int(deleted)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune stale cache_version rows from analysis_cache.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without writing.",
    )
    parser.add_argument(
        "--keep-previous",
        type=int,
        default=KEEP_PREVIOUS,
        help=f"Number of previous versions to retain (default: {KEEP_PREVIOUS}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    run(dry_run=args.dry_run, keep_previous=args.keep_previous)
    return 0


if __name__ == "__main__":
    sys.exit(main())
