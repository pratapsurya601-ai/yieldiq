"""Dead-man check for scheduled GH Actions workflows.

Reads `cron_heartbeats` and prints one line per workflow whose
`last_success_at` is older than `2 * expected_interval_minutes`. Exit
code 0 always (so the calling workflow can decide what to do with the
output); the workflow opens a GitHub issue when this script prints any
"DEAD:" lines.

Usage:
    DATABASE_URL=... python scripts/check_cron_deadman.py
    DATABASE_URL=... python scripts/check_cron_deadman.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Tuple


def find_dead_workflows_rows(
    rows: List[Tuple[str, "datetime", int]],  # type: ignore[name-defined]
    *,
    now,
) -> List[dict]:
    """Pure function: given heartbeat rows + a `now`, return the dead ones.

    Each row is (workflow_name, last_success_at, expected_interval_minutes).
    A workflow is "dead" iff (now - last_success_at) > 2 * interval.
    """
    dead: List[dict] = []
    for workflow_name, last_success_at, expected_interval_minutes in rows:
        if last_success_at is None:
            continue
        age_minutes = (now - last_success_at).total_seconds() / 60.0
        threshold = 2 * expected_interval_minutes
        if age_minutes > threshold:
            dead.append({
                "workflow_name": workflow_name,
                "last_success_at": last_success_at.isoformat(),
                "expected_interval_minutes": expected_interval_minutes,
                "age_minutes": round(age_minutes, 1),
                "threshold_minutes": threshold,
            })
    return dead


def _fetch_rows(database_url: str):
    import psycopg2
    url = database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workflow_name, last_success_at, "
                "expected_interval_minutes FROM cron_heartbeats"
            )
            return cur.fetchall()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON instead of human-readable lines.")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2

    from datetime import datetime, timezone
    rows = _fetch_rows(url)
    # Heartbeat timestamps are stored as naive UTC (TIMESTAMP, written
    # via `now()` on the Postgres side). Compare in naive UTC to avoid
    # tz-arithmetic skew.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dead = find_dead_workflows_rows(rows, now=now)

    if args.json:
        print(json.dumps({"dead": dead, "checked": len(rows)}))
    else:
        print(f"checked {len(rows)} workflow heartbeats")
        for d in dead:
            print(
                f"DEAD: {d['workflow_name']} "
                f"age={d['age_minutes']}min "
                f"threshold={d['threshold_minutes']}min "
                f"last_success_at={d['last_success_at']}"
            )
        if not dead:
            print("all cron workflows healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
