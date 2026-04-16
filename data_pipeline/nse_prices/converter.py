"""
Convert raw NSE CSV files to Parquet with standardised column names.

Each CSV from NSE has columns like:
  Date, OPEN, HIGH, LOW, CLOSE, PREV. CLOSE, ltp, vwap,
  52W H, 52W L, VOLUME, VALUE, No of Trades

We normalise to:
  date, open, high, low, close, prev_close, ltp, vwap,
  volume, value, trades, series
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("yieldiq.nse_prices")

RAW_DIR = Path(__file__).parent / "raw"
PARQUET_DIR = Path(__file__).parent / "parquet"
PARQUET_DIR.mkdir(exist_ok=True)

# Map raw NSE column names (case-insensitive) → standard names.
# NSE occasionally changes casing / spacing between downloads.
_COL_MAP = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "prev. close": "prev_close",
    "prevclose": "prev_close",
    "prev close": "prev_close",
    "ltp": "ltp",
    "vwap": "vwap",
    "52w h": "week52_high",
    "52w l": "week52_low",
    "volume": "volume",
    "value": "value",
    "no of trades": "trades",
    "no. of trades": "trades",
    "series": "series",
    "symbol": "symbol",
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to standard names; drop unknowns."""
    renames = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in _COL_MAP:
            renames[col] = _COL_MAP[key]
    df = df.rename(columns=renames)
    # Keep only known columns
    known = set(_COL_MAP.values())
    keep = [c for c in df.columns if c in known]
    return df[keep].copy()


def convert_one(ticker: str) -> Path | None:
    """Convert RAW_DIR/{ticker}.csv → PARQUET_DIR/{ticker}.parquet."""
    csv_path = RAW_DIR / f"{ticker}.csv"
    if not csv_path.exists():
        log.warning("No CSV for %s", ticker)
        return None

    try:
        df = pd.read_csv(csv_path, skipinitialspace=True)
    except Exception as exc:
        log.warning("CSV parse failed for %s: %s", ticker, exc)
        return None

    if df.empty:
        log.warning("Empty CSV for %s", ticker)
        return None

    df = _normalise_columns(df)

    # Parse date
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=True)
        df = df.sort_values("date").reset_index(drop=True)

    # Numeric coercion
    for col in ("open", "high", "low", "close", "prev_close", "ltp", "vwap",
                "volume", "value", "trades"):
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ""),
                errors="coerce",
            )

    out_path = PARQUET_DIR / f"{ticker}.parquet"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, out_path, compression="snappy")
    except ImportError:
        # Fallback: pandas native parquet (uses pyarrow if available, else fastparquet)
        df.to_parquet(out_path, index=False, compression="snappy")

    log.info("%s: %d rows → %s (%d KB)", ticker, len(df), out_path,
             out_path.stat().st_size // 1024)
    return out_path


def convert_all(tickers: list[str] | None = None) -> dict[str, Path | None]:
    """Convert all CSVs in RAW_DIR. Returns {ticker: path_or_None}."""
    if tickers is None:
        tickers = [p.stem for p in RAW_DIR.glob("*.csv")]
    results = {}
    for t in tickers:
        results[t] = convert_one(t)
    ok = sum(1 for v in results.values() if v)
    print(f"Converted: {ok}/{len(tickers)} tickers to Parquet")
    return results
