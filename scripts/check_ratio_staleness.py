#!/usr/bin/env python3
"""CI gate: warn (don't block) when too many ratio_history rows are stale.

Purpose
-------
Catches "we forgot to run weekly maintenance for 3 weeks" silently
breaking peer-cap. Runs on PRs that touch the data-shape surface
(``models/``, ``backend/services/``) and posts a warning comment when
more than ``--threshold`` tickers have stale rows.

This is intentionally a *warning*, not a blocker — an active maintenance
gap shouldn't prevent unrelated PRs from merging, but it should be
loudly visible.

Logic
-----
1. Pull every active ticker's latest ``period_end`` from ratio_history.
2. Count how many are older than ``--stale-days`` (default 90).
3. If count > ``--threshold`` (default 100), exit 0 but print a
   GITHUB_STEP_SUMMARY warning that the workflow renders into the PR.

Discipline
----------
Read-only. Never writes. Never bumps CACHE_VERSION.

Usage
-----
    DATABASE_URL=postgres://... python scripts/check_ratio_staleness.py
    DATABASE_URL=postgres://... python scripts/check_ratio_staleness.py \
        --threshold 50 --stale-days 60

Exit codes
----------
    0  — always (CI gate is non-blocking by design).
    1  — DB unreachable.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("check_ratio_staleness")


def _resolve_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("ERROR: DATABASE_URL not set.")
    return dsn


def count_stale(dsn: str, *, stale_days: int) -> tuple[int, int]:
    """Return (stale_count, total_active_with_rows)."""
    try:
        import psycopg2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "ERROR: psycopg2 not installed. `pip install psycopg2-binary`."
        ) from exc

    sql = """
        WITH latest AS (
            SELECT DISTINCT ON (rh.ticker)
                rh.ticker, rh.period_end
            FROM ratio_history rh
            JOIN stocks s ON s.ticker = rh.ticker
            WHERE s.is_active = TRUE
            ORDER BY rh.ticker, rh.period_end DESC
        )
        SELECT
            SUM(CASE WHEN (CURRENT_DATE - period_end) > %s THEN 1 ELSE 0 END) AS stale_n,
            COUNT(*) AS total_n
        FROM latest
    """
    with psycopg2.connect(dsn) as conn:  # type: ignore[attr-defined]
        with conn.cursor() as cur:
            cur.execute(sql, (stale_days,))
            row = cur.fetchone()
    if not row:
        return 0, 0
    stale_n = int(row[0] or 0)
    total_n = int(row[1] or 0)
    return stale_n, total_n


def evaluate(stale_n: int, total_n: int, *, threshold: int) -> tuple[bool, str]:
    """Pure helper — returns (warn, message). Used by tests."""
    pct = (100.0 * stale_n / total_n) if total_n else 0.0
    if stale_n > threshold:
        msg = (
            f"WARN: {stale_n} of {total_n} active tickers have stale "
            f"ratio_history rows ({pct:.1f}%). Threshold: {threshold}. "
            f"Trigger workflow_dispatch on `ratio_history_weekly.yml` to remediate."
        )
        return True, msg
    msg = (
        f"OK: {stale_n} of {total_n} active tickers stale "
        f"({pct:.1f}%). Threshold: {threshold}."
    )
    return False, msg


def _write_summary(msg: str, *, warn: bool) -> None:
    """Write to GITHUB_STEP_SUMMARY if available; always echo to stdout."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    header = "## ratio_history staleness check\n\n"
    body = f"{'WARNING' if warn else 'OK'}\n\n{msg}\n"
    out = header + body
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(out)
        except Exception as exc:  # pragma: no cover
            logger.warning("could not write GITHUB_STEP_SUMMARY: %s", exc)
    print(out)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--threshold", type=int, default=100)
    p.add_argument("--stale-days", type=int, default=90)
    p.add_argument(
        "--dry-db", action="store_true",
        help="Skip DB; print OK. Used for self-test.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_db:
        warn, msg = evaluate(0, 0, threshold=args.threshold)
        _write_summary(msg, warn=warn)
        return 0
    try:
        dsn = _resolve_dsn()
        stale_n, total_n = count_stale(dsn, stale_days=args.stale_days)
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("DB query failed: %s", exc)
        return 1
    warn, msg = evaluate(stale_n, total_n, threshold=args.threshold)
    _write_summary(msg, warn=warn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
