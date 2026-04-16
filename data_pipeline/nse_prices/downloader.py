"""
Download historical equity OHLCV from NSE India.

NSE requires cookie warmup (visit the homepage first) and
rate-limits aggressively. We use curl_cffi to impersonate Chrome
(same pattern as the FII/DII fetcher in macro_service.py).

Downloads are chunked into 3-month windows because NSE's API
rejects requests spanning more than ~6 months.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger("yieldiq.nse_prices")

RAW_DIR = Path(__file__).parent / "raw"
RAW_DIR.mkdir(exist_ok=True)

NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "BAJFINANCE", "AXISBANK", "MARUTI", "TITAN",
    "SUNPHARMA", "WIPRO", "HCLTECH", "NESTLEIND", "ULTRACEMCO",
    "ASIANPAINT", "BAJAJFINSV", "DIVISLAB", "DRREDDY", "EICHERMOT",
    "CIPLA", "COALINDIA", "ONGC", "NTPC", "POWERGRID",
    "ADANIPORTS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "APOLLOHOSP", "BRITANNIA", "HEROMOTOCO", "BAJAJ-AUTO",
    "INDUSINDBK", "GRASIM", "JSWSTEEL", "BPCL", "HINDALCO",
    "M&M", "ADANIENT", "TATAPOWER", "VEDL", "SHREECEM",
]


def _create_session():
    """Create a curl_cffi session with Chrome impersonation."""
    try:
        from curl_cffi import requests as cffi
        session = cffi.Session(impersonate="chrome")
    except ImportError:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
        })
    return session


def _warmup(session) -> bool:
    """Warm up NSE cookies — required before any API call."""
    try:
        r = session.get("https://www.nseindia.com", timeout=15)
        return r.status_code == 200
    except Exception as exc:
        log.warning("NSE warmup failed: %s", exc)
        return False


def _download_chunk(
    session,
    symbol: str,
    from_date: date,
    to_date: date,
) -> str | None:
    """Download one date-range chunk as CSV text. Returns None on failure."""
    fmt = "%d-%m-%Y"
    url = (
        f"https://www.nseindia.com/api/historical/cm/equity"
        f"?symbol={symbol}"
        f'&series=["EQ"]'
        f"&from={from_date.strftime(fmt)}"
        f"&to={to_date.strftime(fmt)}"
        f"&csv=true"
    )
    try:
        # Hit the quote page first to refresh cookies for this symbol
        session.get(
            f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}",
            timeout=10,
        )
        time.sleep(0.5)

        r = session.get(url, timeout=20)
        if r.status_code != 200:
            log.warning("%s chunk %s→%s: HTTP %d", symbol, from_date, to_date, r.status_code)
            return None
        text = r.text if hasattr(r, "text") else r.content.decode("utf-8")
        # Sanity: must have header row + at least 1 data row
        lines = text.strip().split("\n")
        if len(lines) < 2:
            log.warning("%s chunk %s→%s: empty CSV (%d lines)", symbol, from_date, to_date, len(lines))
            return None
        return text
    except Exception as exc:
        log.warning("%s chunk %s→%s: %s", symbol, from_date, to_date, exc)
        return None


def download_ticker(
    session,
    symbol: str,
    start: date = date(2020, 4, 1),
    end: date | None = None,
    chunk_months: int = 3,
) -> Path | None:
    """
    Download full history for one ticker in 3-month chunks,
    merge into a single CSV file, and write to ``RAW_DIR/{symbol}.csv``.
    Returns the output path or None on total failure.
    """
    if end is None:
        end = date.today()

    all_rows: list[list[str]] = []
    header: list[str] | None = None

    cursor = start
    while cursor < end:
        chunk_end = min(
            cursor + timedelta(days=chunk_months * 30),
            end,
        )
        csv_text = _download_chunk(session, symbol, cursor, chunk_end)
        if csv_text:
            reader = csv.reader(io.StringIO(csv_text))
            rows = list(reader)
            if rows:
                if header is None:
                    header = rows[0]
                # Append data rows (skip header row of subsequent chunks)
                data_start = 0 if header is None else 1
                all_rows.extend(rows[data_start:])
        cursor = chunk_end + timedelta(days=1)
        time.sleep(1)  # Rate limit between chunks

    if not all_rows or header is None:
        log.warning("%s: no data after all chunks", symbol)
        return None

    out_path = RAW_DIR / f"{symbol}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

    log.info("%s: %d rows → %s", symbol, len(all_rows), out_path)
    return out_path


def download_all(
    tickers: list[str] | None = None,
    start: date = date(2020, 4, 1),
    delay_between: float = 2.0,
) -> dict[str, Path | None]:
    """Download all tickers. Returns {symbol: path_or_None}."""
    tickers = tickers or NIFTY50
    session = _create_session()

    log.info("Warming up NSE session...")
    if not _warmup(session):
        log.error("NSE warmup failed — aborting")
        return {}

    results: dict[str, Path | None] = {}
    for i, sym in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {sym}...", end=" ", flush=True)
        path = download_ticker(session, sym, start=start)
        results[sym] = path
        status = f"OK ({path.stat().st_size // 1024}KB)" if path else "FAILED"
        print(status, flush=True)
        if i < len(tickers):
            time.sleep(delay_between)

    ok = sum(1 for v in results.values() if v is not None)
    print(f"\nDownloaded: {ok}/{len(tickers)} tickers")
    return results
