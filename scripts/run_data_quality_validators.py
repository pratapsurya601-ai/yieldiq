"""Run the data-quality validators and persist results (Phase A.1).

Usage
-----
    python scripts/run_data_quality_validators.py [--dry-run] [--table NAME]

- `--dry-run`: skip the DB write; still runs every validator and prints
  the summary. Useful for local smoke checks before deploying.
- `--table NAME`: only run validators where `.table == NAME`. Useful for
  iterating on one validator at a time.

Exit codes
----------
- 0 if every run is green or yellow
- 1 if any run is red
- 2 if a validator raised (orchestrator-level failure)

A.2 will wire this script into a cron workflow and surface results via
an admin endpoint + UI. A.1 ships the script + framework only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Optional

# Allow running this script directly without `python -m`.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.services.data_quality import HealthCheckResult  # noqa: E402
from backend.services.data_quality.validators import REGISTRY  # noqa: E402


def _persist(result: HealthCheckResult, notes: Optional[str] = None) -> None:
    """Insert one HealthCheckResult into data_quality_runs.

    Uses psycopg2 (already a transitive dep via sqlalchemy). Kept tiny
    on purpose — A.2 may swap to SQLAlchemy when the admin endpoint
    needs richer queries.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set; use --dry-run for local runs without DB"
        )
    import psycopg2  # imported lazily so --dry-run works without psycopg2

    payload = result.to_jsonb()
    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_quality_runs
                    (table_name, populator, overall_status, checks, notes)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (
                    result.table,
                    result.populator,
                    result.overall_status,
                    json.dumps(payload),
                    notes,
                ),
            )


def _format_summary(result: HealthCheckResult) -> str:
    icon = {"green": "OK", "yellow": "WARN", "red": "FAIL"}[result.overall_status]
    head = f"[{icon}] {result.table} ({result.populator}) -> {result.overall_status}"
    lines = [head]
    for c in result.checks:
        tag = {"pass": "  pass", "warn": "  WARN", "fail": "  FAIL"}[c.status]
        lines.append(f"{tag}  {c.name}: {c.details}")
    return "\n".join(lines)


def run(dry_run: bool = False, table_filter: Optional[str] = None) -> int:
    selected = [v for v in REGISTRY if table_filter is None or v.table == table_filter]
    if not selected:
        print(f"no validators match --table {table_filter!r}", file=sys.stderr)
        return 2

    results: list[HealthCheckResult] = []
    for vcls in selected:
        try:
            validator = vcls()
            result = validator.run()
        except NotImplementedError as e:
            # A.1: DB loaders aren't wired yet. Skip cleanly so the
            # orchestrator can still be smoke-tested end-to-end.
            print(f"[SKIP] {vcls.table}: {e}", file=sys.stderr)
            continue
        except Exception:  # pragma: no cover — orchestrator-level safety
            print(f"[ERROR] {vcls.table}: validator raised", file=sys.stderr)
            traceback.print_exc()
            return 2
        results.append(result)
        print(_format_summary(result))
        if not dry_run:
            _persist(result)

    any_red = any(r.overall_status == "red" for r in results)
    print()
    print(
        f"summary: {len(results)} run(s); "
        f"red={sum(1 for r in results if r.overall_status == 'red')} "
        f"yellow={sum(1 for r in results if r.overall_status == 'yellow')} "
        f"green={sum(1 for r in results if r.overall_status == 'green')}"
    )
    return 1 if any_red else 0


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="don't write to DB")
    p.add_argument("--table", default=None, help="only run validators for this table")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    return run(dry_run=args.dry_run, table_filter=args.table)


if __name__ == "__main__":
    raise SystemExit(main())
