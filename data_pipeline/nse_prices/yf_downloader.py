"""
Download price history from yfinance and save as Parquet.

Fallback for when NSE's direct API blocks non-browser clients.
yfinance pulls from Yahoo Finance which has NSE data mirrored.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

log = logging.getLogger("yieldiq.nse_prices")

PARQUET_DIR = Path(__file__).parent / "parquet"
PARQUET_DIR.mkdir(exist_ok=True)

NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "BAJFINANCE", "AXISBANK", "MARUTI", "TITAN",
    "SUNPHARMA", "WIPRO", "HCLTECH", "NESTLEIND", "ULTRACEMCO",
    "ASIANPAINT", "BAJAJFINSV", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "CIPLA", "COALINDIA", "ONGC", "NTPC", "POWERGRID",
    "ADANIPORTS", "TATACONSUM", "TATASTEEL", "TECHM",
    "APOLLOHOSP", "BRITANNIA", "HEROMOTOCO", "BAJAJ-AUTO",
    "INDUSINDBK", "GRASIM", "JSWSTEEL", "BPCL", "HINDALCO",
    "M&M", "ADANIENT", "TATAPOWER", "VEDL", "SHREECEM",
]


def download_ticker(ticker: str, period: str = "5y") -> Path | None:
    """Download OHLCV for one ticker via yfinance, save as Parquet."""
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed")
        return None

    symbol = f"{ticker}.NS"
    try:
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        if hist is None or hist.empty:
            log.warning("%s: no data from yfinance", ticker)
            return None

        # Standardise columns
        df = hist.reset_index()
        rename = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Dividends": "dividends",
            "Stock Splits": "splits",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Remove timezone from date (Parquet doesn't need it)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        # Sort chronologically
        df = df.sort_values("date").reset_index(drop=True)

        out = PARQUET_DIR / f"{ticker}.parquet"
        df.to_parquet(out, index=False, compression="snappy")
        log.info("%s: %d rows → %s (%d KB)",
                 ticker, len(df), out.name, out.stat().st_size // 1024)
        return out

    except Exception as exc:
        log.warning("%s: yfinance download failed: %s", ticker, exc)
        return None


def download_all(
    tickers: list[str] | None = None,
    period: str = "5y",
    delay: float = 1.0,
) -> dict[str, Path | None]:
    """Download all tickers. Returns {ticker: path}."""
    tickers = tickers or NIFTY50
    results: dict[str, Path | None] = {}

    for i, t in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {t}...", end=" ", flush=True)
        path = download_ticker(t, period=period)
        results[t] = path
        if path:
            print(f"OK ({path.stat().st_size // 1024} KB, "
                  f"{pd.read_parquet(path).shape[0]} rows)")
        else:
            print("FAILED")
        if i < len(tickers):
            time.sleep(delay)

    ok = sum(1 for v in results.values() if v is not None)
    print(f"\nDownloaded: {ok}/{len(tickers)} tickers")
    return results


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        download_all(["RELIANCE", "TCS", "ITC", "INFY", "HDFCBANK"], delay=2)
    elif "--full" in sys.argv:
        download_all(delay=2)
    else:
        print("Usage: python yf_downloader.py --test | --full")
