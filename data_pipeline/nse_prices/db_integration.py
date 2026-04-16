"""
DuckDB queries over local Parquet files.

Each ticker has a ``parquet/{TICKER}.parquet`` file with columns:
  date, open, high, low, close, volume, vwap, prev_close, ltp, trades, value

DuckDB reads these directly — no server, no import step, no memory
copy.  Query time is typically <50ms for a full year of daily bars.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PARQUET_DIR = Path(__file__).parent / "parquet"


def _parquet_path(ticker: str) -> Path:
    """Resolve the parquet path for a ticker (strips .NS/.BO suffix)."""
    clean = ticker.replace(".NS", "").replace(".BO", "").upper()
    return PARQUET_DIR / f"{clean}.parquet"


def get_price_history(
    ticker: str,
    days: int = 365,
) -> Any:
    """
    Return a pandas DataFrame of daily OHLCV for the last ``days`` trading
    days. Returns ``None`` if the parquet file doesn't exist.
    """
    import duckdb

    path = _parquet_path(ticker)
    if not path.exists():
        return None

    conn = duckdb.connect()
    try:
        df = conn.execute(f"""
            SELECT date, open, high, low, close, volume
            FROM read_parquet('{path}')
            WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
            ORDER BY date ASC
        """).df()
        return df if not df.empty else None
    except Exception:
        return None
    finally:
        conn.close()


def get_52w_high_low(ticker: str) -> tuple[float | None, float | None]:
    """Return (52-week high, 52-week low) or (None, None)."""
    import duckdb

    path = _parquet_path(ticker)
    if not path.exists():
        return None, None

    conn = duckdb.connect()
    try:
        row = conn.execute(f"""
            SELECT MAX(high) AS w52h, MIN(low) AS w52l
            FROM read_parquet('{path}')
            WHERE date >= CURRENT_TIMESTAMP - INTERVAL '365 days'
        """).fetchone()
        return (row[0], row[1]) if row else (None, None)
    except Exception:
        return None, None
    finally:
        conn.close()


def get_returns(
    ticker: str,
    period_days: int = 252,
) -> dict | None:
    """Calculate total return over ``period_days`` trading days."""
    import duckdb

    path = _parquet_path(ticker)
    if not path.exists():
        return None

    conn = duckdb.connect()
    try:
        row = conn.execute(f"""
            WITH p AS (
                SELECT close, date
                FROM read_parquet('{path}')
                WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{period_days} days'
                ORDER BY date
            )
            SELECT
                FIRST(close) AS start_price,
                LAST(close)  AS end_price,
                ((LAST(close) - FIRST(close)) / FIRST(close) * 100) AS return_pct
            FROM p
        """).fetchone()
        if not row or row[0] is None:
            return None
        return {
            "start": round(float(row[0]), 2),
            "end":   round(float(row[1]), 2),
            "return_pct": round(float(row[2]), 2),
        }
    except Exception:
        return None
    finally:
        conn.close()


def get_latest_price(ticker: str) -> float | None:
    """Return the most recent closing price, or None."""
    import duckdb

    path = _parquet_path(ticker)
    if not path.exists():
        return None

    conn = duckdb.connect()
    try:
        row = conn.execute(f"""
            SELECT close FROM read_parquet('{path}')
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        return float(row[0]) if row else None
    except Exception:
        return None
    finally:
        conn.close()
