"""Apply a .sql migration file to the DATABASE_URL target.

Usage:
    DATABASE_URL=... python scripts/apply_migration.py data_pipeline/migrations/005_ratio_history_peer_groups.sql

Drop-in replacement for `psql -f <file>` when the psql CLI isn't
installed. Uses psycopg2 directly (already a dep via sqlalchemy).

Splits on semicolons naively — fine for our migrations which use
standard DDL. For complex migrations with functions/triggers, use
real psql.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_migration.py <path-to-sql-file>", file=sys.stderr)
        return 2

    sql_path = Path(sys.argv[1])
    if not sql_path.exists():
        print(f"error: {sql_path} not found", file=sys.stderr)
        return 2

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2

    try:
        import psycopg2
    except ImportError:
        print("error: psycopg2 not installed. run: pip install psycopg2-binary", file=sys.stderr)
        return 2

    sql = sql_path.read_text(encoding="utf-8")

    # Strip line comments but keep block structure
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)

    # Naive split on semicolons, drop empties
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]

    print(f"applying {len(statements)} statement(s) from {sql_path.name}")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        for i, stmt in enumerate(statements, 1):
            first_words = " ".join(stmt.split()[:4])
            print(f"  [{i}/{len(statements)}] {first_words}...")
            cur.execute(stmt)
        conn.commit()
        print("migration applied successfully")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"error: {exc}", file=sys.stderr)
        print("migration rolled back", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
