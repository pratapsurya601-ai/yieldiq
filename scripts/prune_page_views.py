#!/usr/bin/env python3
"""Daily cron: delete user_page_views rows older than 30 days.

Invoked by .github/workflows/prune_page_views_daily.yml at 02:00 UTC.
Idempotent and safe to run ad-hoc.

Usage:
    python scripts/prune_page_views.py             # 30-day retention
    python scripts/prune_page_views.py --days 30
    python scripts/prune_page_views.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure repo root is importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("prune_page_views")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=30,
                   help="Retention window in days (default: 30).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be deleted without deleting.")
    args = p.parse_args()

    days = max(1, int(args.days))

    if args.dry_run:
        try:
            from backend.services.page_view_service import _get_raw_cursor
        except Exception as exc:
            log.error("could not import page_view_service: %s", exc)
            return 1
        conn, cur = _get_raw_cursor()
        if conn is None or cur is None:
            log.error("DB unavailable (DATABASE_URL set?)")
            return 1
        try:
            cur.execute(
                "SELECT count(*) FROM user_page_views "
                "WHERE viewed_at < now() - (%s || ' days')::interval",
                (str(days),),
            )
            (n,) = cur.fetchone()
            log.info("[dry-run] would delete %d rows older than %d days", int(n), days)
            return 0
        finally:
            try:
                cur.close()
            finally:
                conn.close()

    from backend.services.page_view_service import prune_older_than
    deleted = prune_older_than(days=days)
    log.info("deleted %d rows older than %d days", deleted, days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
