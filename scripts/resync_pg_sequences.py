"""Resync every autoincrement PK sequence with actual MAX(id).

Fixes the classic post-bulk-load issue where rows were inserted with
explicit ids (e.g. via COPY FROM) but the sequence was never advanced,
so subsequent autoincrement inserts try to use ids that already exist
and hit PK conflicts silently (or loudly, depending on ON CONFLICT).

Safe to run repeatedly. Prints what it changed.

Usage:
    DATABASE_URL=... python scripts/resync_pg_sequences.py
"""
from __future__ import annotations

import os
import sys

try:
    import psycopg2
except ImportError:
    print("pip install psycopg2-binary", file=sys.stderr)
    sys.exit(2)


TABLES = [
    "daily_prices",
    "financials",
    "corporate_actions",
    "shareholding_pattern",
    "market_metrics",
    "bulk_deals",
    "upcoming_earnings",
    "fair_value_history",
    "ratio_history",
    "peer_groups",
]


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    conn = psycopg2.connect(url)
    cur = conn.cursor()

    for tbl in TABLES:
        try:
            cur.execute(f"SELECT pg_get_serial_sequence('{tbl}', 'id')")
            seq = cur.fetchone()[0]
            if not seq:
                print(f"-- {tbl}: no serial sequence on id — skipped")
                continue

            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tbl}")
            max_id = cur.fetchone()[0]

            cur.execute(f"SELECT last_value FROM {seq}")
            seq_before = cur.fetchone()[0]

            cur.execute(f"SELECT setval('{seq}', {max_id + 1}, false)")
            new_val = cur.fetchone()[0]

            drift = max_id - seq_before + 1 if seq_before < max_id else 0
            print(
                f"OK {tbl:<25} max_id={max_id:>12,}  seq_before={seq_before:>12,}"
                f"  seq_now={new_val:>12,}  drift={drift:,}"
            )
        except Exception as e:
            print(f"-- {tbl}: skipped ({type(e).__name__}: {e})")
            conn.rollback()

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
