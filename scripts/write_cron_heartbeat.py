"""Write a heartbeat row to `cron_heartbeats` for a successful cron run.

Invoked as the last step of each scheduled GH Actions workflow that we
care about. Pairs with `scripts/check_cron_deadman.py` (run every 30 min
by `.github/workflows/cron-deadman-checker.yml`) which flags any
workflow whose last_success_at is older than 2 * expected_interval.

Usage:
    DATABASE_URL=... python scripts/write_cron_heartbeat.py \
        --workflow cron-market-live-quotes \
        --interval-minutes 5

Design notes:
  * Pure UPSERT on (workflow_name). consecutive_misses is reset to 0 on
    every successful write — the dead-man checker is the only writer
    that increments it.
  * Idempotent and side-effect-light: a single round-trip per call,
    swallows no errors (the calling step uses `if: success()` so a
    heartbeat failure visibly fails the workflow, which is what we
    want — silent metric loss is exactly the problem we're solving).
  * No external deps beyond psycopg2 (already pinned in every cron
    workflow's `pip install` step).
"""
from __future__ import annotations

import argparse
import os
import sys


def write_heartbeat(
    *,
    workflow: str,
    interval_minutes: int,
    database_url: str,
    psycopg2_module=None,
) -> None:
    """Upsert a row into cron_heartbeats.

    Split out from main() so the unit tests can exercise the SQL
    against an in-memory SQLite engine without touching argparse.
    The `psycopg2_module` hook is injection-only for the test that
    asserts the script does not hard-import psycopg2 until needed.
    """
    if psycopg2_module is None:
        import psycopg2 as psycopg2_module  # type: ignore

    url = database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    conn = psycopg2_module.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cron_heartbeats
                        (workflow_name, last_success_at,
                         expected_interval_minutes, consecutive_misses,
                         updated_at)
                    VALUES (%s, now(), %s, 0, now())
                    ON CONFLICT (workflow_name) DO UPDATE SET
                        last_success_at = EXCLUDED.last_success_at,
                        expected_interval_minutes =
                            EXCLUDED.expected_interval_minutes,
                        consecutive_misses = 0,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (workflow, interval_minutes),
                )
    finally:
        conn.close()


def upsert_heartbeat_sqlite(session, *, workflow: str, interval_minutes: int) -> None:
    """SQLite-flavoured upsert used by the unit tests.

    The production path above uses Postgres ON CONFLICT semantics that
    SQLite also supports (3.24+), so the test re-implements the same
    statement against a sqlalchemy Session.
    """
    from sqlalchemy import text

    session.execute(
        text(
            """
            INSERT INTO cron_heartbeats
                (workflow_name, last_success_at,
                 expected_interval_minutes, consecutive_misses,
                 updated_at)
            VALUES (:wf, :now, :iv, 0, :now)
            ON CONFLICT (workflow_name) DO UPDATE SET
                last_success_at = excluded.last_success_at,
                expected_interval_minutes = excluded.expected_interval_minutes,
                consecutive_misses = 0,
                updated_at = excluded.updated_at
            """
        ),
        {"wf": workflow, "iv": interval_minutes, "now": _utcnow_iso()},
    )
    session.commit()


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workflow", required=True,
                    help="Workflow file basename minus .yml, e.g. cron-market-live-quotes")
    ap.add_argument("--interval-minutes", required=True, type=int,
                    help="Declared cadence in minutes. Dead-man threshold = 2x this.")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2

    write_heartbeat(
        workflow=args.workflow,
        interval_minutes=args.interval_minutes,
        database_url=url,
    )
    print(
        f"cron_heartbeat: workflow={args.workflow} "
        f"interval_minutes={args.interval_minutes} ok"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
