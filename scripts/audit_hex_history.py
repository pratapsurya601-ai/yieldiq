#!/usr/bin/env python3
"""
scripts/audit_hex_history.py
═══════════════════════════════════════════════════════════════════
Fails loudly (exit 1) if the hex_history table is empty or stale.

Used by `.github/workflows/hex_history_audit.yml` (daily cron) to
catch the class of bug where the weekly backfill silently produced
zero rows and nobody noticed until a user loaded the Prism Time
Machine scrubber and saw an empty chart.

CLI:
    python scripts/audit_hex_history.py [--fresh-days 14] [--min-tickers 100]

Exit codes:
    0 — healthy
    1 — empty OR stale OR fewer than --min-tickers distinct tickers
    2 — DB connection / schema issue
═══════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh-days", type=int, default=14,
                    help="Fail if no rows have been (re)computed in the last N days.")
    ap.add_argument("--min-tickers", type=int, default=50,
                    help="Fail if fewer than this many distinct tickers have rows.")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("::error::DATABASE_URL not set in env.")
        return 2
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        from sqlalchemy import create_engine, text  # type: ignore
    except Exception as exc:
        print(f"::error::sqlalchemy import failed: {exc}")
        return 2

    try:
        eng = create_engine(url, connect_args={"connect_timeout": 10})
        with eng.connect() as cx:
            total = cx.execute(text("SELECT COUNT(*) FROM hex_history")).scalar_one()
            distinct = cx.execute(text(
                "SELECT COUNT(DISTINCT ticker) FROM hex_history"
            )).scalar_one()
            fresh = cx.execute(text(
                "SELECT COUNT(*) FROM hex_history "
                "WHERE computed_at > now() - (:d || ' days')::interval"
            ), {"d": args.fresh_days}).scalar_one()
            newest = cx.execute(text(
                "SELECT MAX(computed_at) FROM hex_history"
            )).scalar_one()
    except Exception as exc:
        print(f"::error::hex_history query failed: {exc}")
        return 2

    print(f"hex_history audit:")
    print(f"  total rows          = {total}")
    print(f"  distinct tickers    = {distinct}")
    print(f"  rows fresh ({args.fresh_days}d)    = {fresh}")
    print(f"  newest computed_at  = {newest}")

    problems: list[str] = []
    if total == 0:
        problems.append("table is EMPTY — weekly backfill is broken.")
    if distinct < args.min_tickers:
        problems.append(
            f"only {distinct} distinct tickers (< min {args.min_tickers})."
        )
    if fresh == 0:
        problems.append(
            f"no rows refreshed in the last {args.fresh_days} days — "
            f"weekly backfill has stopped landing writes."
        )

    if problems:
        print("::error::hex_history unhealthy:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("hex_history looks healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
