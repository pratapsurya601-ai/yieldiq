# backend/services/backtest_service.py
# ═══════════════════════════════════════════════════════════════
# Backtest engine — "how would this filter have performed?"
#
# Scope: backtest the CURRENT constituents of a screen over the
# last N years, equal-weighted, with quarterly rebalancing.
# Compares vs NIFTYBEES benchmark.
#
# This is NOT a true rolling backtest (which would require
# re-running the filter at each historical date). It answers a
# simpler question: "the kinds of stocks this filter picks —
# how have they done recently?"
#
# Disclaimer: Survivorship bias is present. Past performance does
# not guarantee future results. Shown prominently on the UI.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("yieldiq.backtest")

# Benchmark: composite of Nifty 50's top 5 weights (proxy for Nifty index)
# since NIFTYBEES ETF may not be in our Parquet cache
BENCHMARK_TICKERS = ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"]
BENCHMARK_LABEL = "Nifty proxy (top 5)"


def _load_prices_df(
    tickers: list[str], years: int, dropped: list[str] | None = None
) -> pd.DataFrame | None:
    """
    Load aligned daily close prices for multiple tickers from Parquet.
    Returns a DataFrame with date index, one column per ticker.

    A single bad ticker (missing parquet, malformed history, duckdb hiccup)
    must NOT kill the whole backtest — every per-ticker failure is logged
    and the ticker is appended to ``dropped`` (if provided).
    """
    import duckdb
    from data_pipeline.nse_prices.db_integration import _parquet_path

    frames: dict[str, pd.Series] = {}
    conn = duckdb.connect()
    try:
        days = years * 365
        for ticker in tickers:
            clean = ticker.replace(".NS", "").replace(".BO", "").upper()
            path = _parquet_path(clean)
            if not path.exists():
                if dropped is not None:
                    dropped.append(clean)
                continue
            try:
                df = conn.execute(f"""
                    SELECT date, close
                    FROM read_parquet('{path}')
                    WHERE date >= CURRENT_TIMESTAMP - INTERVAL '{days} days'
                    ORDER BY date ASC
                """).df()
                if df is None or len(df) <= 10:
                    if dropped is not None:
                        dropped.append(clean)
                    continue
                df["date"] = pd.to_datetime(df["date"])
                s = df.set_index("date")["close"].astype(float)
                # Skip series that are entirely NaN or constant-zero —
                # they break pct_change and downstream metrics.
                if s.dropna().empty or float(s.dropna().iloc[0]) <= 0:
                    if dropped is not None:
                        dropped.append(clean)
                    continue
                frames[clean] = s
            except Exception as e:
                logger.warning("backtest: skipping %s due to %s: %s", clean, type(e).__name__, e)
                if dropped is not None:
                    dropped.append(clean)
                continue
    finally:
        conn.close()

    if not frames:
        return None

    # Align on the intersection of dates (inner join) then forward-fill gaps
    combined = pd.concat(frames, axis=1)
    combined = combined.sort_index()
    # Only keep rows where at least 50% of tickers have data
    min_valid = max(1, len(frames) // 2)
    combined = combined.dropna(thresh=min_valid)
    combined = combined.ffill()
    return combined if len(combined) > 10 else None


def _compute_equity_curve(prices_df: pd.DataFrame, rebalance_days: int = 63) -> pd.Series:
    """
    Equal-weighted portfolio with periodic rebalancing.
    rebalance_days=63 ~= quarterly (63 trading days).

    Returns a pd.Series of portfolio value starting at 100.
    """
    if prices_df is None or prices_df.empty:
        return pd.Series([], dtype=float)

    # Daily returns
    returns = prices_df.pct_change().fillna(0)

    n_tickers = len(prices_df.columns)
    if n_tickers == 0:
        return pd.Series([], dtype=float)

    weights = np.full(n_tickers, 1.0 / n_tickers)
    portfolio_values = [100.0]  # start at 100
    current_weights = weights.copy()

    dates = list(returns.index)
    for i, dt in enumerate(dates[1:], start=1):
        daily_ret_per_ticker = returns.iloc[i].values
        # Update each ticker's weight by its return
        new_weights = current_weights * (1.0 + daily_ret_per_ticker)
        # Handle NaN (missing data)
        new_weights = np.nan_to_num(new_weights, nan=0.0)
        portfolio_ret = float(np.sum(current_weights * daily_ret_per_ticker) / (np.sum(current_weights) or 1))
        portfolio_values.append(portfolio_values[-1] * (1 + portfolio_ret))
        current_weights = new_weights
        # Rebalance every rebalance_days
        if i % rebalance_days == 0:
            current_weights = weights.copy()

    return pd.Series(portfolio_values, index=returns.index, name="portfolio")


def _compute_metrics(equity: pd.Series, benchmark: pd.Series | None = None) -> dict:
    """CAGR, volatility, Sharpe proxy, max drawdown, beta vs benchmark, alpha."""
    if equity is None or len(equity) < 30:
        return {}

    n_days = len(equity)
    n_years = n_days / 252.0
    start_val = float(equity.iloc[0])
    end_val = float(equity.iloc[-1])
    total_return = (end_val / start_val) - 1
    cagr = ((end_val / start_val) ** (1 / n_years) - 1) if n_years > 0 else 0

    # Daily returns
    daily_ret = equity.pct_change().dropna()
    vol = float(daily_ret.std() * math.sqrt(252))
    sharpe = (cagr / vol) if vol > 0 else 0

    # Max drawdown
    running_max = equity.cummax()
    drawdowns = (equity - running_max) / running_max
    max_dd = float(drawdowns.min())

    result = {
        "start_value": 100.0,
        "end_value": round(end_val, 2),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "volatility_pct": round(vol * 100, 2),
        "sharpe_proxy": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_days": n_days,
        "n_years": round(n_years, 2),
    }

    if benchmark is not None and len(benchmark) > 30:
        # Align on common index
        aligned = pd.concat([equity, benchmark], axis=1).dropna()
        aligned.columns = ["p", "b"]
        if len(aligned) > 30:
            p_ret = aligned["p"].pct_change().dropna()
            b_ret = aligned["b"].pct_change().dropna()
            # Align returns
            common = p_ret.index.intersection(b_ret.index)
            p_ret = p_ret.loc[common]
            b_ret = b_ret.loc[common]
            if len(p_ret) > 30:
                cov = float(np.cov(p_ret, b_ret, ddof=1)[0, 1])
                var_b = float(np.var(b_ret, ddof=1))
                beta = cov / var_b if var_b > 0 else None

                # Benchmark CAGR
                b_start = float(aligned["b"].iloc[0])
                b_end = float(aligned["b"].iloc[-1])
                b_years = len(aligned) / 252.0
                b_cagr = ((b_end / b_start) ** (1 / b_years) - 1) if b_years > 0 else 0

                # Alpha = portfolio CAGR - beta * benchmark CAGR (rough CAPM)
                alpha = None
                if beta is not None:
                    alpha = cagr - (beta * b_cagr)

                result["beta"] = round(beta, 2) if beta is not None else None
                result["benchmark_cagr_pct"] = round(b_cagr * 100, 2)
                result["alpha_pct"] = round(alpha * 100, 2) if alpha is not None else None
                result["outperformance_pct"] = round((cagr - b_cagr) * 100, 2)

    return result


def backtest_tickers(
    tickers: list[str],
    years: int = 3,
    rebalance_days: int = 63,
    include_benchmark: bool = True,
    downsample_points: int = 150,
) -> dict:
    """
    Run backtest for a list of tickers.
    Returns equity curve, benchmark curve, and performance metrics.
    """
    if not tickers:
        return {"error": "No tickers provided"}

    dropped: list[str] = []
    prices_df = _load_prices_df(tickers, years, dropped=dropped)
    if prices_df is None or prices_df.empty:
        return {
            "error": f"No price history available for {len(tickers)} tickers",
            "tickers_dropped": len(dropped),
            "tickers_dropped_sample": dropped[:10],
        }

    equity = _compute_equity_curve(prices_df, rebalance_days=rebalance_days)
    if equity.empty:
        return {"error": "Could not compute equity curve", "tickers_dropped": len(dropped)}

    # Benchmark (equal-weighted basket of Nifty top 5)
    benchmark_series = None
    benchmark_curve_series = None
    if include_benchmark:
        bench_df = _load_prices_df(BENCHMARK_TICKERS, years)
        if bench_df is not None and not bench_df.empty:
            # Equal-weighted benchmark equity curve
            bench_equity = _compute_equity_curve(bench_df, rebalance_days=rebalance_days)
            if not bench_equity.empty:
                aligned_bench = bench_equity.reindex(equity.index, method="ffill")
                # iloc[0] can be NaN if the benchmark history starts AFTER
                # the portfolio history (reindex+ffill leaves leading NaNs).
                # Guard against NaN/None/zero before normalising.
                if not aligned_bench.empty:
                    first = aligned_bench.dropna()
                    if not first.empty and float(first.iloc[0]) > 0:
                        base = float(first.iloc[0])
                        benchmark_curve_series = aligned_bench / base * 100
                        benchmark_series = benchmark_curve_series

    metrics = _compute_metrics(equity, benchmark_series)

    # Downsample for chart (e.g., 150 points)
    n = len(equity)
    step = max(1, n // downsample_points)

    curve = []
    for i in range(0, n, step):
        row = {
            "date": str(equity.index[i].date()),
            "portfolio": round(float(equity.iloc[i]), 2),
        }
        if benchmark_curve_series is not None and i < len(benchmark_curve_series):
            row["benchmark"] = round(float(benchmark_curve_series.iloc[i]), 2)
        curve.append(row)
    # Always include last point
    if n > 0 and (n - 1) % step != 0:
        i = n - 1
        row = {
            "date": str(equity.index[i].date()),
            "portfolio": round(float(equity.iloc[i]), 2),
        }
        if benchmark_curve_series is not None and i < len(benchmark_curve_series):
            row["benchmark"] = round(float(benchmark_curve_series.iloc[i]), 2)
        curve.append(row)

    return {
        "tickers_backtested": len(prices_df.columns),
        "tickers_requested": len(tickers),
        "tickers_dropped": len(dropped),
        "tickers_dropped_sample": dropped[:10],
        "benchmark": BENCHMARK_LABEL,
        "rebalance_days": rebalance_days,
        "years": years,
        "curve": curve,
        "metrics": metrics,
    }
