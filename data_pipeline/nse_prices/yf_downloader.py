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
        # auto_adjust=False: yfinance's split-adjustment feed misclassified the
        # July-2023 HDFC Ltd → HDFCBANK merger share issuance as a ~2.12× split,
        # halving every HDFCBANK close in our pipeline (₹1,700 → ₹800). The DCF
        # uses point-in-time market price, so un-adjusted raw Close is correct.
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=False)
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

        # ── Override last close with live quote ───────────────────
        # yfinance's history endpoint returns SPLIT-ADJUSTED closes even
        # with auto_adjust=False — the flag only governs dividend adjust.
        # For tickers with bogus splits in Yahoo's feed (e.g. HDFCBANK's
        # 2023 merger encoded as a 2.12× split), every historical close
        # is wrong. We trust the LIVE quote far more than the adjusted
        # history because it comes from the real-time feed, not the
        # corporate-actions-adjusted archive. Overriding just the last
        # row fixes the "current price" field without claiming to fix
        # historical charts (which remain best-effort).
        try:
            info_obj = yf.Ticker(symbol).fast_info
            live = (
                getattr(info_obj, "last_price", None)
                or getattr(info_obj, "regular_market_price", None)
                or getattr(info_obj, "previous_close", None)
            )
            if live and float(live) > 0 and len(df) > 0:
                last_close = float(df.iloc[-1]["close"])
                live = float(live)
                # Only override when they disagree by >5% — avoids
                # accidentally corrupting good data due to intraday noise.
                if last_close > 0 and abs(live - last_close) / last_close > 0.05:
                    log.info(
                        "%s: live quote ₹%.2f vs parquet last close ₹%.2f "
                        "(%.1f%% diff) — overriding last row with live",
                        ticker, live, last_close,
                        (live - last_close) / last_close * 100.0,
                    )
                    df.loc[df.index[-1], "close"] = live
                    # Also update open/high/low floor so charts don't
                    # render a weird spike at the final bar.
                    df.loc[df.index[-1], "open"] = live
                    df.loc[df.index[-1], "high"] = max(
                        float(df.iloc[-1].get("high") or 0), live
                    )
                    df.loc[df.index[-1], "low"] = min(
                        float(df.iloc[-1].get("low") or live), live
                    ) if float(df.iloc[-1].get("low") or 0) > 0 else live
        except Exception as _exc:
            log.debug("%s: live-quote override skipped: %s", ticker, _exc)

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
