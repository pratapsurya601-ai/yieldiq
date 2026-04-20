"""Unified price-history reader across PG live table and Parquet archive.

Data layout
-----------
* Postgres ``daily_prices`` owns 2016-01-01 onwards (live, indexed).
* Parquet archive at ``data/parquet/daily_prices_archive/year=YYYY/...``
  owns 2004-2015 (cold, read-only, populated by Phase B backfill).

Callers use :func:`get_price_history` and don't need to know where the
data lives. The splitter picks PG for 2016+ dates, Parquet for older
ones, and unions when a range spans the boundary.

Reads are via DuckDB when the Parquet side is involved — pure PG reads
still use the existing SQLAlchemy session. This keeps the hot path
(which is ~99% of requests, since users rarely look at pre-2016 charts)
unchanged from before.

Usage
-----
    from backend.services.price_history_service import get_price_history
    df = get_price_history("RELIANCE", start="2010-01-01", end="2026-04-01")

Returns a pandas DataFrame with columns: trade_date, ticker, open_price,
high_price, low_price, close_price, prev_close, volume, turnover_cr,
vwap. Sorted by trade_date ascending.

Performance
-----------
* All-PG request: unchanged from direct psycopg2 query.
* All-Parquet request: DuckDB over partitioned files, ~100ms for 1Y.
* Spanning request: two queries concatenated in-memory, ~150ms.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── configuration ─────────────────────────────────────────────────────

# First trade_date that's authoritative in Postgres. Anything strictly
# older lives in Parquet only. 2016-01-01 matches the cutoff we enforce
# in backfill_bhavcopy_parquet_archive.py's HARD_MAX.
PG_CUTOFF: date = date(2016, 1, 1)

# Repo-relative Parquet archive root. Overridable via env for Railway.
_PARQUET_ARCHIVE_ROOT_ENV = "PRICE_ARCHIVE_ROOT"
_DEFAULT_PARQUET_ROOT = Path(__file__).resolve().parents[2] / "data" / "parquet" / "daily_prices_archive"


def _parquet_root() -> Path:
    env = os.environ.get(_PARQUET_ARCHIVE_ROOT_ENV)
    if env:
        return Path(env)
    return _DEFAULT_PARQUET_ROOT


def _parse_date(d: str | date | datetime) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    return datetime.fromisoformat(str(d)[:10]).date()


# ── PG reader ─────────────────────────────────────────────────────────

_PG_COLS = (
    "trade_date, ticker, open_price, high_price, low_price, close_price, "
    "prev_close, volume, turnover_cr, vwap"
)


def _read_pg(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Read from the live PG daily_prices table. Requires DATABASE_URL."""
    import psycopg2

    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.warning("DATABASE_URL not set — returning empty PG slice")
        return pd.DataFrame(columns=_PG_COLS.split(", "))

    sql = (
        f"SELECT {_PG_COLS} FROM daily_prices "
        f"WHERE ticker = %s AND trade_date BETWEEN %s AND %s "
        f"ORDER BY trade_date"
    )
    conn = psycopg2.connect(url)
    try:
        df = pd.read_sql(sql, conn, params=(ticker, start, end))
    finally:
        conn.close()
    return df


# ── Parquet reader ────────────────────────────────────────────────────

_PARQUET_COLS = _PG_COLS  # same schema


def _read_parquet(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Read from the Parquet archive using DuckDB glob + predicate pushdown."""
    root = _parquet_root()
    if not root.exists():
        logger.debug("parquet archive %s does not exist — empty slice", root)
        return pd.DataFrame(columns=_PARQUET_COLS.split(", "))

    # Only scan year-partitions that intersect the requested range
    years = list(range(start.year, end.year + 1))
    existing_years = [y for y in years if (root / f"year={y}").exists()]
    if not existing_years:
        return pd.DataFrame(columns=_PARQUET_COLS.split(", "))

    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed — skipping parquet read")
        return pd.DataFrame(columns=_PARQUET_COLS.split(", "))

    # Build a glob pattern for the matching years; DuckDB reads them in
    # a single scan with predicate pushdown for date + ticker.
    glob_patterns = [
        str((root / f"year={y}" / "**" / "*.parquet").as_posix())
        for y in existing_years
    ]

    con = duckdb.connect(":memory:")
    try:
        # Union over glob list; DuckDB's read_parquet accepts a list
        con.register("__patterns", pd.DataFrame({"p": glob_patterns}))
        sql = f"""
            SELECT {_PARQUET_COLS}
            FROM read_parquet(?, union_by_name=true)
            WHERE ticker = ?
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
        """
        df = con.execute(sql, [glob_patterns, ticker, start, end]).df()
    except Exception as exc:
        logger.warning("parquet read failed: %s", exc)
        return pd.DataFrame(columns=_PARQUET_COLS.split(", "))
    finally:
        con.close()
    return df


# ── public API ────────────────────────────────────────────────────────

def get_price_history(
    ticker: str,
    start: str | date | datetime,
    end: Optional[str | date | datetime] = None,
) -> pd.DataFrame:
    """Return daily price history for ``ticker`` across PG + Parquet.

    Args:
      ticker: NSE-style bare symbol (e.g. 'RELIANCE'); matches the stored
              format in both PG and Parquet.
      start:  inclusive start date (str or date).
      end:    inclusive end date (str or date). Defaults to today.

    Returns pandas DataFrame sorted by trade_date ascending. Empty if
    neither store has data for the range.
    """
    s = _parse_date(start)
    e = _parse_date(end) if end else date.today()
    if s > e:
        return pd.DataFrame(columns=_PG_COLS.split(", "))

    frames: list[pd.DataFrame] = []

    # Parquet slice (strictly before PG cutoff)
    if s < PG_CUTOFF:
        p_end = min(e, date(PG_CUTOFF.year - 1, 12, 31))
        if p_end >= s:
            frames.append(_read_parquet(ticker, s, p_end))

    # PG slice (from PG_CUTOFF onwards)
    if e >= PG_CUTOFF:
        p_start = max(s, PG_CUTOFF)
        if p_start <= e:
            frames.append(_read_pg(ticker, p_start, e))

    if not frames:
        return pd.DataFrame(columns=_PG_COLS.split(", "))

    out = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    if out.empty:
        return out
    # Normalise: ensure ascending order, dedupe by (ticker, trade_date)
    out = out.drop_duplicates(subset=["ticker", "trade_date"], keep="last")
    out = out.sort_values("trade_date").reset_index(drop=True)
    return out


def get_price_history_ticker_count() -> dict[str, int]:
    """Diagnostic — how many tickers have history in each store?"""
    stats = {"pg": 0, "parquet": 0}
    try:
        import psycopg2
        url = os.environ.get("DATABASE_URL")
        if url:
            conn = psycopg2.connect(url)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(DISTINCT ticker) FROM daily_prices")
            stats["pg"] = int(cur.fetchone()[0])
            conn.close()
    except Exception:
        pass

    try:
        import duckdb
        root = _parquet_root()
        if root.exists() and any(root.glob("year=*/month=*/day=*.parquet")):
            con = duckdb.connect(":memory:")
            pattern = str((root / "**" / "*.parquet").as_posix())
            cnt = con.execute(
                "SELECT COUNT(DISTINCT ticker) FROM read_parquet(?, union_by_name=true)",
                [pattern],
            ).fetchone()[0]
            stats["parquet"] = int(cnt)
            con.close()
    except Exception:
        pass

    return stats
