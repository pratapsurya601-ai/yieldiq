"""Export every persistent table to Parquet.

This is the dual-write layer: Postgres stays authoritative for the live
API (sub-ms indexed reads), Parquet files mirror the same data for
analytics (DuckDB / Polars / pandas) and portability (S3 sync, git-lfs,
backups, cross-validation).

Output layout under ``data/parquet/``:

    stocks.parquet                   # full stocks table
    financials.parquet               # full financials — all periods, all tickers
    ratio_history.parquet            # full ratio_history
    peer_groups.parquet              # full peer_groups
    market_metrics.parquet           # full market_metrics (small today)
    shareholding_pattern.parquet
    fair_value_history.parquet
    daily_prices/
        year=2021/part-0.parquet     # partitioned because this table is large
        year=2022/part-0.parquet
        ...

Usage
-----
    DATABASE_URL=... python scripts/export_to_parquet.py
    DATABASE_URL=... python scripts/export_to_parquet.py --tables ratio_history,peer_groups
    DATABASE_URL=... python scripts/export_to_parquet.py --out data/parquet

Requirements
------------
pip install pyarrow pandas

Idempotent: overwrites each target file on every run.

Performance
-----------
~15-30 seconds on a modern laptop with Aiven prod-tier:
  - financials:     ~50k rows
  - ratio_history:  ~10k rows (after Phase-1 rebuild)
  - daily_prices:   ~300k rows → partitioned by year, still fits in RAM
  - market_metrics: ~9k rows
  - peer_groups:    ~14k rows
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print(
        "Missing dep — run: pip install pyarrow pandas",
        file=sys.stderr,
    )
    sys.exit(2)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("export_to_parquet")


# ── tables ────────────────────────────────────────────────────────────
# Each entry:
#   name              — logical name (also becomes file / dir name)
#   sql               — SELECT statement (ordered for stable output)
#   partition_by      — None for single file; a column name for partitioned
#                       (we use "year(trade_date)" etc. as virtual)
#   compression       — snappy for most (fast, good ratio); zstd for
#                       cold/archive-y tables (slower, better ratio)
TABLES: list[dict[str, Any]] = [
    {
        "name": "stocks",
        "sql": "SELECT * FROM stocks ORDER BY ticker",
        "partition_by": None,
        "compression": "snappy",
    },
    {
        "name": "financials",
        "sql": (
            "SELECT * FROM financials "
            "ORDER BY ticker, period_end, period_type"
        ),
        "partition_by": None,
        "compression": "zstd",   # big text column (raw_data), zstd helps
    },
    {
        "name": "ratio_history",
        "sql": (
            "SELECT * FROM ratio_history "
            "ORDER BY ticker, period_end, period_type"
        ),
        "partition_by": None,
        "compression": "snappy",
    },
    {
        "name": "peer_groups",
        "sql": "SELECT * FROM peer_groups ORDER BY ticker, rank",
        "partition_by": None,
        "compression": "snappy",
    },
    {
        "name": "market_metrics",
        "sql": (
            "SELECT * FROM market_metrics "
            "ORDER BY ticker, trade_date"
        ),
        "partition_by": None,
        "compression": "snappy",
    },
    {
        "name": "shareholding_pattern",
        "sql": (
            "SELECT * FROM shareholding_pattern "
            "ORDER BY ticker, quarter_end"
        ),
        "partition_by": None,
        "compression": "snappy",
    },
    {
        "name": "fair_value_history",
        "sql": "SELECT * FROM fair_value_history ORDER BY ticker, date",
        "partition_by": None,
        "compression": "snappy",
    },
    # daily_prices is partitioned by year because it grows ~75k rows/year
    # for 500 tickers and single-file gets unwieldy in source control.
    # Each year-partition stays under 5MB with snappy.
    {
        "name": "daily_prices",
        "sql": (
            "SELECT *, EXTRACT(YEAR FROM trade_date)::int AS _year "
            "FROM daily_prices ORDER BY ticker, trade_date"
        ),
        "partition_by": "_year",
        "compression": "snappy",
    },
]


def _df_from_sql(conn, sql: str) -> pd.DataFrame:
    """Read a SQL result into a DataFrame. Uses pandas.read_sql under the
    hood. Cast Postgres Decimal to float so Arrow doesn't choke."""
    df = pd.read_sql(sql, conn)
    # Downcast numeric objects so Parquet picks stable types
    for col in df.columns:
        if df[col].dtype == "object":
            # Try conservative numeric cast — bools stay bool, dates stay dates
            try:
                sample = df[col].dropna().iloc[0] if df[col].notna().any() else None
                if sample is not None and hasattr(sample, "is_finite"):  # Decimal
                    df[col] = pd.to_numeric(df[col], errors="ignore")
            except Exception:
                pass
    return df


def _write_single(df: pd.DataFrame, out: Path, compression: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, str(out), compression=compression)


def _write_partitioned(
    df: pd.DataFrame,
    out_dir: Path,
    partition_col: str,
    compression: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Drop the virtual partition column from the data frame (it's encoded
    # in the directory structure); keep a copy for grouping
    partitions = df[partition_col].unique()
    data_cols = [c for c in df.columns if c != partition_col]
    for p in sorted(partitions):
        sub = df[df[partition_col] == p][data_cols]
        part_dir = out_dir / f"{partition_col.lstrip('_')}={int(p)}"
        part_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(sub, preserve_index=False)
        pq.write_table(
            table, str(part_dir / "part-0.parquet"), compression=compression,
        )


def export_table(conn, spec: dict[str, Any], out_root: Path) -> dict[str, Any]:
    """Returns {rows, files, bytes, path}."""
    name = spec["name"]
    logger.info("exporting %s ...", name)
    df = _df_from_sql(conn, spec["sql"])
    rows = len(df)

    if rows == 0:
        logger.warning("  %s is empty — skipping", name)
        return {"name": name, "rows": 0, "files": 0, "bytes": 0, "path": None}

    if spec["partition_by"]:
        out_dir = out_root / name
        # Wipe the dir first so stale partitions don't accumulate
        if out_dir.exists():
            for f in out_dir.rglob("*.parquet"):
                f.unlink()
        _write_partitioned(
            df, out_dir, spec["partition_by"], spec["compression"],
        )
        files = list(out_dir.rglob("*.parquet"))
        total_bytes = sum(f.stat().st_size for f in files)
        logger.info(
            "  %s: %d rows → %d partitioned files (%.1f MB)",
            name, rows, len(files), total_bytes / 1e6,
        )
        return {
            "name": name, "rows": rows, "files": len(files),
            "bytes": total_bytes, "path": str(out_dir),
        }
    else:
        out = out_root / f"{name}.parquet"
        _write_single(df, out, spec["compression"])
        size = out.stat().st_size
        logger.info(
            "  %s: %d rows → %s (%.1f MB)", name, rows, out, size / 1e6,
        )
        return {
            "name": name, "rows": rows, "files": 1,
            "bytes": size, "path": str(out),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default="data/parquet",
        help="Output root dir (default: data/parquet)",
    )
    ap.add_argument(
        "--tables", default=None,
        help=(
            "Comma-separated subset of table names to export. "
            "Defaults to all."
        ),
    )
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    try:
        from sqlalchemy import create_engine
    except ImportError:
        print("sqlalchemy required", file=sys.stderr)
        return 2

    selected = None
    if args.tables:
        selected = {t.strip() for t in args.tables.split(",") if t.strip()}

    engine = create_engine(url)
    conn = engine.connect()
    try:
        out_root = Path(args.out)
        out_root.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for spec in TABLES:
            if selected and spec["name"] not in selected:
                continue
            try:
                res = export_table(conn, spec, out_root)
                results.append(res)
            except Exception as e:  # noqa: BLE001
                logger.exception("failed to export %s: %s", spec["name"], e)
                results.append({
                    "name": spec["name"], "rows": 0, "files": 0,
                    "bytes": 0, "path": None, "error": str(e),
                })

        # Summary
        total_rows = sum(r["rows"] for r in results)
        total_bytes = sum(r["bytes"] for r in results)
        logger.info("")
        logger.info("SUMMARY")
        logger.info("  %d tables exported", len([r for r in results if r["rows"] > 0]))
        logger.info("  %d total rows", total_rows)
        logger.info("  %.1f MB total on disk", total_bytes / 1e6)
        logger.info("  output: %s", out_root.resolve())

        failed = [r for r in results if r.get("error")]
        if failed:
            logger.error("  %d tables FAILED: %s", len(failed), ", ".join(r["name"] for r in failed))
            return 1
    finally:
        conn.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
