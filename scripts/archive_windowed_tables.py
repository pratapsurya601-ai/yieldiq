"""Window-and-archive growth tables to Parquet.

Rationale
---------
Aiven Hobby caps us at 1 GB. Tables that grow unbounded over time
(``fair_value_history``, ``market_metrics``, ``shareholding_pattern``)
will eventually push us over the cap. Most live-API reads only need
the most recent window of each, so this script:

  1. Exports rows OLDER than the keep-window into a Parquet archive.
  2. DELETEs those archived rows from Postgres.
  3. Verifies row counts match (archive rows == deleted rows) before
     committing the DELETE.

Safe to run repeatedly. Missing Parquet files are recreated. Already-
archived rows (below the window cutoff) are no-ops on the DELETE side.

Output layout::

    data/parquet/archive/
      fair_value_history/YYYY-MM-DD.parquet   # one file per run
      market_metrics/YYYY-MM-DD.parquet
      shareholding_pattern/YYYY-MM-DD.parquet

Each run writes a dated snapshot, never overwrites — DuckDB will
union them at read time via ``read_parquet('.../YYYY-MM-*.parquet')``.

Usage
-----
    DATABASE_URL=... python scripts/archive_windowed_tables.py
    DATABASE_URL=... python scripts/archive_windowed_tables.py --dry-run
    DATABASE_URL=... python scripts/archive_windowed_tables.py --table market_metrics

Config (tweak only after understanding live-API impact)::

    fair_value_history    keep last 90 days
    market_metrics        keep last 730 days (2Y)
    shareholding_pattern  keep last 12 quarters (3Y)

Schedule: run weekly (Sunday) from GH Actions alongside the newsletter.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import psycopg2
except ImportError as e:
    print(f"missing dep: {e} — pip install pandas pyarrow psycopg2-binary", file=sys.stderr)
    sys.exit(2)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("archive_windowed")


# Each entry: table, date column, days to keep in PG
CONFIGS: list[dict[str, Any]] = [
    {
        "table": "fair_value_history",
        "date_col": "date",
        "keep_days": 90,
    },
    {
        "table": "market_metrics",
        "date_col": "trade_date",
        "keep_days": 730,
    },
    {
        "table": "shareholding_pattern",
        "date_col": "quarter_end",
        "keep_days": 365 * 3,  # ~12 quarters
    },
]


def _archive_table(
    conn,
    cfg: dict[str, Any],
    out_root: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    table = cfg["table"]
    date_col = cfg["date_col"]
    cutoff = (date.today() - timedelta(days=cfg["keep_days"])).isoformat()

    cur = conn.cursor()

    # Count rows to be archived
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {date_col} < %s", (cutoff,))
    n_old = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {date_col} >= %s", (cutoff,))
    n_keep = cur.fetchone()[0]

    logger.info(
        "[%s] cutoff=%s  to_archive=%d  to_keep=%d",
        table, cutoff, n_old, n_keep,
    )

    if n_old == 0:
        return {"table": table, "archived": 0, "deleted": 0}

    if dry_run:
        logger.info("[%s] --dry-run — not writing or deleting", table)
        return {"table": table, "archived": n_old, "deleted": 0, "dry_run": True}

    # Pull the old rows into a DataFrame
    sql = f"SELECT * FROM {table} WHERE {date_col} < %s"
    df = pd.read_sql(sql, conn, params=(cutoff,))
    assert len(df) == n_old, f"row count mismatch: df={len(df)} expected={n_old}"

    # Write dated Parquet
    out_dir = out_root / table
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{date.today().isoformat()}.parquet"
    t = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(t, str(out_file), compression="zstd")
    size_mb = out_file.stat().st_size / 1e6
    logger.info("[%s] wrote %s (%.2f MB)", table, out_file, size_mb)

    # Sanity check — re-read Parquet and compare row count before deleting
    rt = pq.read_table(str(out_file))
    if rt.num_rows != n_old:
        raise RuntimeError(
            f"Parquet readback mismatch for {table}: "
            f"written={n_old} readback={rt.num_rows} — aborting DELETE"
        )

    # Now it's safe to delete from PG
    cur.execute(f"DELETE FROM {table} WHERE {date_col} < %s", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    logger.info("[%s] deleted %d rows from PG", table, deleted)

    return {
        "table": table, "archived": n_old, "deleted": deleted,
        "parquet": str(out_file), "size_mb": round(size_mb, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/parquet/archive",
                    help="Archive root dir (default: data/parquet/archive)")
    ap.add_argument("--table", default=None,
                    help="Single table (default: all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts, write nothing, delete nothing")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    selected = CONFIGS
    if args.table:
        selected = [c for c in CONFIGS if c["table"] == args.table]
        if not selected:
            print(f"unknown table: {args.table}", file=sys.stderr)
            return 2

    conn = psycopg2.connect(url)
    results: list[dict[str, Any]] = []
    try:
        for cfg in selected:
            try:
                res = _archive_table(conn, cfg, out_root, dry_run=args.dry_run)
                results.append(res)
            except Exception as exc:
                logger.exception("[%s] FAILED: %s", cfg["table"], exc)
                conn.rollback()
                results.append({"table": cfg["table"], "error": str(exc)})
    finally:
        conn.close()

    logger.info("SUMMARY")
    for r in results:
        if r.get("error"):
            logger.error("  %s: ERROR — %s", r["table"], r["error"])
        elif r.get("dry_run"):
            logger.info("  %s: would archive %d rows (dry-run)", r["table"], r["archived"])
        else:
            logger.info(
                "  %s: archived=%d deleted=%d size=%sMB",
                r["table"], r.get("archived", 0), r.get("deleted", 0),
                r.get("size_mb", "?"),
            )

    errs = [r for r in results if r.get("error")]
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
