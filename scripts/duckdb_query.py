"""Query the Parquet dual-write layer via DuckDB.

Zero Postgres dependency. Read-only. Useful for analytics, spot-checks,
and sharing ad-hoc queries with collaborators who only have the Parquet
snapshot.

Usage
-----
    # Interactive REPL against all the Parquet files
    python scripts/duckdb_query.py

    # One-shot query
    python scripts/duckdb_query.py -q "SELECT ticker, AVG(roe) FROM ratio_history WHERE period_type='annual' GROUP BY ticker ORDER BY 2 DESC LIMIT 10"

    # Point at a different Parquet root
    python scripts/duckdb_query.py --root /mnt/s3-sync/yieldiq-parquet

Each Parquet file is registered as a DuckDB view of the same name:
  stocks                 -- stocks.parquet
  financials             -- financials.parquet
  ratio_history          -- ratio_history.parquet
  peer_groups            -- peer_groups.parquet
  market_metrics         -- market_metrics.parquet
  shareholding_pattern   -- shareholding_pattern.parquet
  fair_value_history     -- fair_value_history.parquet
  daily_prices           -- daily_prices/year=*/part-0.parquet (glob)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("pip install duckdb", file=sys.stderr)
    sys.exit(2)


SINGLE_FILE_TABLES = [
    "stocks",
    "financials",
    "ratio_history",
    "peer_groups",
    "market_metrics",
    "shareholding_pattern",
    "fair_value_history",
]

PARTITIONED_TABLES = ["daily_prices"]


def _open(root: Path) -> "duckdb.DuckDBPyConnection":
    con = duckdb.connect(":memory:")
    for name in SINGLE_FILE_TABLES:
        path = root / f"{name}.parquet"
        if path.exists():
            con.execute(
                f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')"
            )
        else:
            print(f"  (skip) {name}: {path} missing", file=sys.stderr)

    for name in PARTITIONED_TABLES:
        glob = root / name / "*/*.parquet"
        if any(root.joinpath(name).rglob("*.parquet")):
            con.execute(
                f"CREATE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{glob.as_posix()}', "
                f"hive_partitioning = 1)"
            )
        else:
            print(f"  (skip) {name}: {glob} has no parquet files", file=sys.stderr)

    return con


def _repl(con: "duckdb.DuckDBPyConnection") -> int:
    con.execute("SELECT name FROM (SHOW TABLES)")
    tables = [r[0] for r in con.fetchall()]
    print("tables registered:", ", ".join(tables))
    print("type .exit or Ctrl-D to quit")
    while True:
        try:
            q = input("duck> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in (".exit", ".quit"):
            break
        try:
            df = con.execute(q).df()
            if df.empty:
                print("(0 rows)")
            else:
                with_more_cols = df.to_string(index=False, max_rows=40, max_cols=10)
                print(with_more_cols)
                print(f"({len(df)} rows)")
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/parquet", help="Parquet root dir")
    ap.add_argument("-q", "--query", default=None, help="One-shot query")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"Parquet root {root} does not exist. Run scripts/export_to_parquet.py first.",
              file=sys.stderr)
        return 2

    con = _open(root)

    if args.query:
        try:
            df = con.execute(args.query).df()
            if df.empty:
                print("(0 rows)")
            else:
                print(df.to_string(index=False, max_rows=200))
                print(f"({len(df)} rows)")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 1

    return _repl(con)


if __name__ == "__main__":
    sys.exit(main())
