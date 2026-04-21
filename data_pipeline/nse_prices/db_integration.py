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


def get_technical_indicators(
    ticker: str,
    days: int = 365,
) -> dict | None:
    """
    Compute technical indicators from Parquet price history.

    Returns daily series (date, close) plus indicator series:
        sma_20, sma_50, sma_200
        rsi_14
        macd_line, macd_signal, macd_histogram
        bollinger_upper, bollinger_lower (20-day, 2 std)

    Plus latest snapshot values + simple regime labels.
    All None if insufficient history.
    """
    import duckdb
    import numpy as np

    path = _parquet_path(ticker)
    if not path.exists():
        return None

    conn = duckdb.connect()
    try:
        df = conn.execute(f"""
            SELECT date, close, volume
            FROM read_parquet('{path}')
            WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
            ORDER BY date ASC
        """).df()

        if df is None or len(df) < 30:
            return None

        closes = df["close"].astype(float).values
        n = len(closes)

        # SMAs
        def _sma(arr, period):
            if len(arr) < period:
                return [None] * len(arr)
            out = [None] * (period - 1)
            for i in range(period - 1, len(arr)):
                out.append(float(np.mean(arr[i - period + 1: i + 1])))
            return out

        sma_20 = _sma(closes, 20)
        sma_50 = _sma(closes, 50)
        sma_200 = _sma(closes, 200)

        # RSI(14)
        def _rsi(arr, period=14):
            if len(arr) < period + 1:
                return [None] * len(arr)
            deltas = np.diff(arr)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            out = [None] * period
            avg_gain = np.mean(gains[:period])
            avg_loss = np.mean(losses[:period])
            for i in range(period, len(arr) - 1):
                rs = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = 100 - (100 / (1 + rs))
                out.append(float(rsi))
                # Wilder smoothing
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            # Final value
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            out.append(float(100 - (100 / (1 + rs))))
            return out

        rsi_14 = _rsi(closes, 14)

        # MACD (12, 26, 9)
        def _ema(arr, period):
            if len(arr) < period:
                return [None] * len(arr)
            out = [None] * (period - 1)
            ema = float(np.mean(arr[:period]))
            out.append(ema)
            k = 2 / (period + 1)
            for i in range(period, len(arr)):
                ema = float(arr[i]) * k + ema * (1 - k)
                out.append(ema)
            return out

        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        macd_line = [
            (e12 - e26) if e12 is not None and e26 is not None else None
            for e12, e26 in zip(ema12, ema26)
        ]
        # Signal line: 9-EMA of MACD line (only over valid values)
        valid_macd = [v for v in macd_line if v is not None]
        signal_part = _ema(valid_macd, 9) if len(valid_macd) >= 9 else []
        # Pad signal back to full length
        signal_pad_count = len(macd_line) - len(signal_part)
        macd_signal = [None] * signal_pad_count + signal_part
        macd_histogram = [
            (m - s) if m is not None and s is not None else None
            for m, s in zip(macd_line, macd_signal)
        ]

        # Bollinger Bands (20, 2)
        def _bollinger(arr, period=20, num_std=2):
            upper = [None] * (period - 1)
            lower = [None] * (period - 1)
            for i in range(period - 1, len(arr)):
                window = arr[i - period + 1: i + 1]
                mean = float(np.mean(window))
                std = float(np.std(window, ddof=1))
                upper.append(mean + num_std * std)
                lower.append(mean - num_std * std)
            return upper, lower

        boll_upper, boll_lower = _bollinger(closes, 20, 2)

        # Latest snapshot
        latest_close = float(closes[-1])
        latest_rsi = rsi_14[-1] if rsi_14[-1] is not None else None
        latest_sma20 = sma_20[-1]
        latest_sma50 = sma_50[-1]
        latest_sma200 = sma_200[-1]
        latest_macd = macd_line[-1]
        latest_macd_signal = macd_signal[-1]

        # Regime labels (factual, not buy/sell signals)
        rsi_zone = None
        if latest_rsi is not None:
            if latest_rsi >= 70:
                rsi_zone = "overbought_zone"
            elif latest_rsi <= 30:
                rsi_zone = "oversold_zone"
            else:
                rsi_zone = "neutral_zone"

        sma_position = None
        if latest_sma200 is not None:
            sma_position = "above_200dma" if latest_close > latest_sma200 else "below_200dma"

        # MACD crossover state
        macd_state = None
        if latest_macd is not None and latest_macd_signal is not None:
            macd_state = "macd_above_signal" if latest_macd > latest_macd_signal else "macd_below_signal"

        # Build daily series (downsample to ~150 points for chart performance)
        sample_step = max(1, n // 150)
        dates = df["date"].astype(str).values

        series = []
        for i in range(0, n, sample_step):
            series.append({
                "date": str(dates[i]),
                "close": round(float(closes[i]), 2),
                "sma_20": round(sma_20[i], 2) if sma_20[i] is not None else None,
                "sma_50": round(sma_50[i], 2) if sma_50[i] is not None else None,
                "sma_200": round(sma_200[i], 2) if sma_200[i] is not None else None,
                "rsi_14": round(rsi_14[i], 1) if rsi_14[i] is not None else None,
                "macd": round(macd_line[i], 2) if macd_line[i] is not None else None,
                "macd_signal": round(macd_signal[i], 2) if macd_signal[i] is not None else None,
                "macd_histogram": round(macd_histogram[i], 2) if macd_histogram[i] is not None else None,
                "boll_upper": round(boll_upper[i], 2) if boll_upper[i] is not None else None,
                "boll_lower": round(boll_lower[i], 2) if boll_lower[i] is not None else None,
            })
        # Always include the very last point
        if n > 0 and (n - 1) % sample_step != 0:
            i = n - 1
            series.append({
                "date": str(dates[i]),
                "close": round(float(closes[i]), 2),
                "sma_20": round(sma_20[i], 2) if sma_20[i] is not None else None,
                "sma_50": round(sma_50[i], 2) if sma_50[i] is not None else None,
                "sma_200": round(sma_200[i], 2) if sma_200[i] is not None else None,
                "rsi_14": round(rsi_14[i], 1) if rsi_14[i] is not None else None,
                "macd": round(macd_line[i], 2) if macd_line[i] is not None else None,
                "macd_signal": round(macd_signal[i], 2) if macd_signal[i] is not None else None,
                "macd_histogram": round(macd_histogram[i], 2) if macd_histogram[i] is not None else None,
                "boll_upper": round(boll_upper[i], 2) if boll_upper[i] is not None else None,
                "boll_lower": round(boll_lower[i], 2) if boll_lower[i] is not None else None,
            })

        return {
            "series": series,
            "latest": {
                "close": round(latest_close, 2),
                "sma_20": round(latest_sma20, 2) if latest_sma20 else None,
                "sma_50": round(latest_sma50, 2) if latest_sma50 else None,
                "sma_200": round(latest_sma200, 2) if latest_sma200 else None,
                "rsi_14": round(latest_rsi, 1) if latest_rsi is not None else None,
                "macd": round(latest_macd, 2) if latest_macd is not None else None,
                "macd_signal": round(latest_macd_signal, 2) if latest_macd_signal is not None else None,
                "rsi_zone": rsi_zone,
                "sma_position": sma_position,
                "macd_state": macd_state,
            },
            "days_in_sample": n,
        }
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

        import numpy as np

        # Root-cause guard (Sentry PYTHON-FASTAPI-6V):
        # Recently-listed / illiquid tickers occasionally have zero or
        # negative closes in the Parquet archive (corporate-action glitches
        # or pre-listing placeholder rows). np.log(0) returns -inf, which
        # then propagates NaN through every downstream metric (vol,
        # max_drawdown, sharpe_proxy) and blows up the FastAPI JSON encoder
        # via `allow_nan=False`. Filter non-positive closes up front.
        closes = df["close"].astype(float).values
        finite_mask = np.isfinite(closes) & (closes > 0)
        if not finite_mask.all():
            closes = closes[finite_mask]
            df = df.loc[finite_mask].reset_index(drop=True)
        if len(closes) < 30:
            return None

        # Daily log returns
        log_returns = np.diff(np.log(closes))
        if len(log_returns) < 2:
            # ddof=1 std needs at least 2 samples; single-sample → NaN.
            return None

        # Annualised volatility (assume 252 trading days/year)
        vol_raw = float(np.std(log_returns, ddof=1) * math.sqrt(252))
        vol = vol_raw if math.isfinite(vol_raw) else 0.0

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

        # Current drawdown (guard against zero running_max, which would NaN
        # the serializer; finite_mask above makes this mostly theoretical).
        current_dd = (
            float((closes[-1] - running_max[-1]) / running_max[-1])
            if running_max[-1] > 0
            else 0.0
        )

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
            base = closes[-days_back - 1]
            if base <= 0:  # avoid inf / NaN from zero-denominator
                return None
            val = float((closes[-1] - base) / base * 100)
            return val if math.isfinite(val) else None

        ret_1m = _return_over(21)
        ret_3m = _return_over(63)
        ret_1y = _return_over(252)
        ret_3y = _return_over(252 * 3)

        # Simple return/vol ratio (not true Sharpe — no risk-free sub)
        if closes[0] > 0:
            total_return = float((closes[-1] - closes[0]) / closes[0])
        else:
            total_return = 0.0
        n_years = max(len(closes) / 252.0, 0.1)
        annualized_return = (1 + total_return) ** (1 / n_years) - 1 if total_return > -1 else -1.0
        if not math.isfinite(annualized_return):
            annualized_return = 0.0
        sharpe_proxy = float(annualized_return / vol) if vol > 0 else 0.0
        if not math.isfinite(sharpe_proxy):
            sharpe_proxy = 0.0

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
                    # Align on dates; filter non-positive closes on both sides
                    merged = df.merge(bench_df, on="date", suffixes=("_s", "_b"))
                    if len(merged) >= 30:
                        s_close = merged["close_s"].astype(float).values
                        b_close = merged["close_b"].astype(float).values
                        mmask = (
                            np.isfinite(s_close) & (s_close > 0) &
                            np.isfinite(b_close) & (b_close > 0)
                        )
                        if mmask.sum() >= 30:
                            s_close = s_close[mmask]
                            b_close = b_close[mmask]
                            s_ret = np.diff(np.log(s_close))
                            b_ret = np.diff(np.log(b_close))
                            if len(b_ret) >= 2 and np.std(b_ret) > 0:
                                cov = np.cov(s_ret, b_ret, ddof=1)[0, 1]
                                var_b = np.var(b_ret, ddof=1)
                                if var_b > 0:
                                    beta_raw = float(cov / var_b)
                                    if math.isfinite(beta_raw):
                                        beta = beta_raw
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
