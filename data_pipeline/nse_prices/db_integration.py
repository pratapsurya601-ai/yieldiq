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


def get_risk_stats(
    ticker: str,
    benchmark_ticker: str = "NIFTYBEES",
    years: int = 3,
) -> dict | None:
    """
    Compute risk/volatility statistics from daily price history.

    Returns a dict with:
        volatility_pct:       float   Annualised volatility of daily returns (%)
        max_drawdown_pct:     float   Worst peak-to-trough decline (%)
        max_drawdown_days:    int     Days from peak to trough
        recovery_days:        int|None Days from trough back to peak (None if not recovered)
        beta:                 float|None Beta vs NIFTY (if benchmark available)
        sharpe_proxy:         float   Return-to-vol ratio (no risk-free sub)
        current_drawdown_pct: float   Current drawdown from all-time high in window
        week52_high:          float
        week52_low:           float
        return_1m:            float
        return_3m:            float
        return_1y:            float
        return_3y:            float
        days_in_sample:       int

    All None if no price history available.
    """
    import duckdb
    import math

    path = _parquet_path(ticker)
    if not path.exists():
        return None

    days = years * 365
    conn = duckdb.connect()
    try:
        df = conn.execute(f"""
            SELECT date, close
            FROM read_parquet('{path}')
            WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
            ORDER BY date ASC
        """).df()

        if df is None or len(df) < 30:
            return None

        closes = df["close"].astype(float).values

        # Daily log returns
        import numpy as np
        log_returns = np.diff(np.log(closes))
        if len(log_returns) == 0:
            return None

        # Annualised volatility (assume 252 trading days/year)
        vol = float(np.std(log_returns, ddof=1) * math.sqrt(252))

        # Max drawdown calculation
        running_max = np.maximum.accumulate(closes)
        drawdowns = (closes - running_max) / running_max  # negative values
        max_dd_idx = int(np.argmin(drawdowns))
        max_dd = float(drawdowns[max_dd_idx])

        # Find peak before max drawdown
        peak_idx = int(np.argmax(closes[: max_dd_idx + 1]))
        dd_duration = max_dd_idx - peak_idx

        # Recovery: has price returned to peak level after trough?
        peak_val = float(closes[peak_idx])
        recovery_days = None
        for j in range(max_dd_idx + 1, len(closes)):
            if closes[j] >= peak_val:
                recovery_days = j - max_dd_idx
                break

        # Current drawdown
        current_dd = float((closes[-1] - running_max[-1]) / running_max[-1])

        # 52-week high/low
        if len(closes) >= 252:
            w52_window = closes[-252:]
        else:
            w52_window = closes
        week52_high = float(np.max(w52_window))
        week52_low = float(np.min(w52_window))

        # Returns over various windows
        def _return_over(days_back: int) -> float | None:
            if len(closes) < days_back + 1:
                return None
            return float((closes[-1] - closes[-days_back - 1]) / closes[-days_back - 1] * 100)

        ret_1m = _return_over(21)
        ret_3m = _return_over(63)
        ret_1y = _return_over(252)
        ret_3y = _return_over(252 * 3)

        # Simple return/vol ratio (not true Sharpe — no risk-free sub)
        total_return = float((closes[-1] - closes[0]) / closes[0])
        n_years = max(len(closes) / 252.0, 0.1)
        annualized_return = (1 + total_return) ** (1 / n_years) - 1 if total_return > -1 else -1
        sharpe_proxy = float(annualized_return / vol) if vol > 0 else 0

        # Beta calculation vs benchmark
        beta = None
        try:
            bench_path = _parquet_path(benchmark_ticker)
            if bench_path.exists():
                bench_df = conn.execute(f"""
                    SELECT date, close
                    FROM read_parquet('{bench_path}')
                    WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
                    ORDER BY date ASC
                """).df()
                if bench_df is not None and len(bench_df) >= 30:
                    # Align on dates
                    merged = df.merge(bench_df, on="date", suffixes=("_s", "_b"))
                    if len(merged) >= 30:
                        s_ret = np.diff(np.log(merged["close_s"].astype(float).values))
                        b_ret = np.diff(np.log(merged["close_b"].astype(float).values))
                        if np.std(b_ret) > 0:
                            cov = np.cov(s_ret, b_ret, ddof=1)[0, 1]
                            var_b = np.var(b_ret, ddof=1)
                            if var_b > 0:
                                beta = float(cov / var_b)
        except Exception:
            pass

        return {
            "volatility_pct": round(vol * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "max_drawdown_days": int(dd_duration),
            "recovery_days": int(recovery_days) if recovery_days is not None else None,
            "current_drawdown_pct": round(current_dd * 100, 2),
            "beta": round(beta, 2) if beta is not None else None,
            "sharpe_proxy": round(sharpe_proxy, 2),
            "week52_high": round(week52_high, 2),
            "week52_low": round(week52_low, 2),
            "return_1m": round(ret_1m, 2) if ret_1m is not None else None,
            "return_3m": round(ret_3m, 2) if ret_3m is not None else None,
            "return_1y": round(ret_1y, 2) if ret_1y is not None else None,
            "return_3y": round(ret_3y, 2) if ret_3y is not None else None,
            "days_in_sample": len(closes),
            "peak_date": str(df.iloc[peak_idx]["date"]),
            "trough_date": str(df.iloc[max_dd_idx]["date"]),
        }
    except Exception:
        return None
    finally:
        conn.close()
