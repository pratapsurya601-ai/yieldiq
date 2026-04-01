# data/ticker_registry.py
# ═══════════════════════════════════════════════════════════════
# US Ticker Registry — Dynamic universe from Finnhub + CSV fallback
# ═══════════════════════════════════════════════════════════════
#
# Provides a live, filtered US equity universe by querying the
# Finnhub /stock/symbol endpoint.  Results are merged with the
# local usa_tickers.csv to attach canonical sector + name data,
# then cached on disk for 24 h using diskcache so the same
# expensive HTTP call is not repeated every process startup.
#
# Public API
# ----------
#   get_us_tickers(force_refresh=False) -> pd.DataFrame
#       Columns: ticker, name, sector
#       Returns ~7,000–9,000 rows of US common stocks.
#
#   get_ticker_count() -> int
#       Convenience wrapper — returns len(get_us_tickers()).
#
# Fallback chain
# --------------
#   1. diskcache hit  (< 24 h old)      → return cached DataFrame
#   2. Finnhub API    (FINNHUB_API_KEY)  → fetch, merge, cache, return
#   3. usa_tickers.csv                  → return CSV rows only
#
# Environment
# -----------
#   FINNHUB_API_KEY   Required for live fetch.  If absent, falls
#                     back to usa_tickers.csv immediately.
#
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from utils.logger import get_logger

log = get_logger(__name__)

# ── Paths ───────────────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent          # …/data/
_CSV_PATH    = _THIS_DIR / "usa_tickers.csv"
_CACHE_DIR   = _THIS_DIR.parent / "cache" / "ticker_registry"

# ── Finnhub settings ────────────────────────────────────────────
_FINNHUB_URL = "https://finnhub.io/api/v1/stock/symbol"
_EXCHANGE    = "US"
_TIMEOUT_SEC = 30

# ── Ticker validation patterns ──────────────────────────────────
# Standard 1–5 letter US tickers  (AAPL, GOOGL, BRK-B, etc.)
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$|^[A-Z]{1,4}-[A-Z]$")

# ── Cache TTL ───────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 24 * 3600   # 24 hours

# ── Cache key ───────────────────────────────────────────────────
_CACHE_KEY = "us_tickers_v1"


# ════════════════════════════════════════════════════════════════
# Internal helpers
# ════════════════════════════════════════════════════════════════

def _get_cache():
    """
    Return a diskcache.Cache instance pointed at the registry
    cache subdirectory.  Import is deferred so the module loads
    cleanly even when diskcache is not installed (rare).
    """
    try:
        import diskcache
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return diskcache.Cache(str(_CACHE_DIR))
    except ImportError:
        log.warning("diskcache not installed — disk caching disabled for ticker registry")
        return None


def _read_csv_fallback() -> pd.DataFrame:
    """
    Read usa_tickers.csv and return a normalised DataFrame with
    columns [ticker, name, sector].  Returns an empty DataFrame
    if the file is missing.
    """
    if not _CSV_PATH.exists():
        log.error(f"Fallback CSV not found: {_CSV_PATH}")
        return pd.DataFrame(columns=["ticker", "name", "sector"])

    df = pd.read_csv(_CSV_PATH, dtype=str)

    # Normalise column names to lower-case and strip whitespace
    df.columns = [c.strip().lower() for c in df.columns]

    # Ensure required columns exist
    for col in ("ticker", "name", "sector"):
        if col not in df.columns:
            df[col] = ""

    df = df[["ticker", "name", "sector"]].copy()
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df["name"]   = df["name"].str.strip().fillna("")
    df["sector"] = df["sector"].str.strip().fillna("General")
    df = df[df["ticker"].str.len() > 0].drop_duplicates(subset="ticker").reset_index(drop=True)

    log.info(f"Loaded {len(df):,} tickers from CSV fallback ({_CSV_PATH.name})")
    return df


def _fetch_finnhub_symbols(api_key: str) -> list[dict]:
    """
    Call GET /stock/symbol?exchange=US and return the raw list of
    symbol dicts from Finnhub.  Raises requests.RequestException
    on network or HTTP errors.
    """
    params = {
        "exchange": _EXCHANGE,
        "token":    api_key,
    }
    log.info("Fetching US equity universe from Finnhub …")
    t0 = time.perf_counter()

    resp = requests.get(_FINNHUB_URL, params=params, timeout=_TIMEOUT_SEC)
    resp.raise_for_status()

    symbols: list[dict] = resp.json()
    elapsed = time.perf_counter() - t0
    log.info(f"Finnhub returned {len(symbols):,} raw symbols in {elapsed:.1f}s")
    return symbols


def _filter_symbols(symbols: list[dict]) -> list[dict]:
    """
    Keep only Common Stock entries whose display symbol matches
    the US ticker naming convention.
    """
    filtered = []
    for s in symbols:
        # Finnhub uses "type" field; we want "Common Stock" only
        if str(s.get("type", "")).strip() != "Common Stock":
            continue

        # Use displaySymbol preferentially; fall back to symbol
        raw_symbol = (s.get("displaySymbol") or s.get("symbol") or "").strip().upper()

        if _TICKER_RE.match(raw_symbol):
            filtered.append({
                "ticker":      raw_symbol,
                "fh_desc":     str(s.get("description", "")).strip(),
            })

    log.info(
        f"Filtered to {len(filtered):,} Common Stock tickers "
        f"(from {len(symbols):,} raw symbols)"
    )
    return filtered


def _merge_with_csv(finnhub_rows: list[dict]) -> pd.DataFrame:
    """
    Merge Finnhub symbol list with usa_tickers.csv.

    For tickers present in the CSV: use CSV name + sector.
    For tickers not in the CSV:     sector = "General",
                                    name   = Finnhub description.
    """
    # Build a lookup from the CSV
    csv_df = _read_csv_fallback()
    csv_lookup: dict[str, dict] = {}
    for _, row in csv_df.iterrows():
        csv_lookup[row["ticker"]] = {
            "name":   row["name"],
            "sector": row["sector"],
        }

    rows = []
    for entry in finnhub_rows:
        ticker   = entry["ticker"]
        fh_desc  = entry["fh_desc"]
        csv_info = csv_lookup.get(ticker)

        if csv_info:
            name   = csv_info["name"]   or fh_desc or ticker
            sector = csv_info["sector"] or "General"
        else:
            name   = fh_desc or ticker
            sector = "General"

        rows.append({
            "ticker": ticker,
            "name":   name,
            "sector": sector,
        })

    # Also include any CSV tickers that Finnhub did NOT return
    # (delisted / OTC names that are still in our curated list).
    fh_tickers = {r["ticker"] for r in rows}
    for _, row in csv_df.iterrows():
        if row["ticker"] not in fh_tickers:
            rows.append({
                "ticker": row["ticker"],
                "name":   row["name"],
                "sector": row["sector"],
            })

    df = pd.DataFrame(rows, columns=["ticker", "name", "sector"])
    df = df.drop_duplicates(subset="ticker").reset_index(drop=True)

    csv_known   = df["ticker"].isin(csv_lookup).sum()
    csv_unknown = len(df) - csv_known
    log.info(
        f"Merged universe: {len(df):,} tickers total "
        f"({csv_known:,} from CSV, {csv_unknown:,} Finnhub-only with sector=General)"
    )
    return df


# ════════════════════════════════════════════════════════════════
# Cache helpers
# ════════════════════════════════════════════════════════════════

def _load_from_cache() -> Optional[pd.DataFrame]:
    """
    Return the cached DataFrame if it exists and is younger than
    _CACHE_TTL_SECONDS.  Returns None on any failure.
    """
    cache = _get_cache()
    if cache is None:
        return None
    try:
        with cache:
            entry = cache.get(_CACHE_KEY)
            if entry is None:
                return None
            cached_at: float = entry.get("cached_at", 0.0)
            age = time.time() - cached_at
            if age > _CACHE_TTL_SECONDS:
                log.debug(f"Ticker registry cache expired ({age/3600:.1f}h old)")
                return None
            df: pd.DataFrame = entry["df"]
            log.info(
                f"Ticker registry loaded from disk cache "
                f"({len(df):,} tickers, {age/3600:.1f}h old)"
            )
            return df
    except Exception as exc:
        log.warning(f"Could not read ticker registry cache: {exc}")
        return None


def _save_to_cache(df: pd.DataFrame) -> None:
    """Persist the DataFrame to diskcache with a timestamp."""
    cache = _get_cache()
    if cache is None:
        return
    try:
        with cache:
            cache.set(
                _CACHE_KEY,
                {"df": df, "cached_at": time.time()},
                expire=_CACHE_TTL_SECONDS + 300,   # slight grace period
            )
        log.info(f"Ticker registry cached ({len(df):,} tickers)")
    except Exception as exc:
        log.warning(f"Could not write ticker registry cache: {exc}")


# ════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════

def get_us_tickers(force_refresh: bool = False) -> pd.DataFrame:
    """
    Return a DataFrame of US common-stock tickers with columns:
        ticker  (str)  — uppercase, e.g. "AAPL", "BRK-B"
        name    (str)  — company display name
        sector  (str)  — GICS-style sector, or "General"

    Parameters
    ----------
    force_refresh : bool
        When True, skip the disk cache and re-fetch from Finnhub
        (or fall back to CSV if the API is unavailable).

    Fallback chain
    --------------
    1. Disk cache (if fresh and force_refresh=False)
    2. Finnhub API  → merged with usa_tickers.csv
    3. usa_tickers.csv alone (if API key missing or HTTP error)
    """
    # ── Step 1: Try the disk cache ──────────────────────────────
    if not force_refresh:
        cached = _load_from_cache()
        if cached is not None:
            return cached

    # ── Step 2: Attempt live Finnhub fetch ──────────────────────
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        log.warning(
            "FINNHUB_API_KEY not set — falling back to usa_tickers.csv"
        )
        df = _read_csv_fallback()
        _save_to_cache(df)
        return df

    try:
        raw_symbols  = _fetch_finnhub_symbols(api_key)
        filtered     = _filter_symbols(raw_symbols)
        df           = _merge_with_csv(filtered)
        _save_to_cache(df)
        return df

    except requests.HTTPError as exc:
        log.error(
            f"Finnhub HTTP error {exc.response.status_code} — "
            f"falling back to usa_tickers.csv"
        )
    except requests.RequestException as exc:
        log.error(f"Finnhub request failed ({exc}) — falling back to usa_tickers.csv")
    except Exception as exc:
        log.error(f"Unexpected error fetching Finnhub symbols: {exc} — using CSV")

    # ── Step 3: CSV-only fallback ────────────────────────────────
    df = _read_csv_fallback()
    # Cache the fallback result too so repeated failures don't hammer the API
    _save_to_cache(df)
    return df


def get_ticker_count(force_refresh: bool = False) -> int:
    """
    Return the number of tickers in the current US universe.

    Parameters
    ----------
    force_refresh : bool
        Passed through to get_us_tickers().
    """
    return len(get_us_tickers(force_refresh=force_refresh))


# ════════════════════════════════════════════════════════════════
# Quick smoke-test  (python -m data.ticker_registry)
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    force = "--refresh" in sys.argv
    print(f"force_refresh={force}")

    df = get_us_tickers(force_refresh=force)
    print(f"\nUS ticker universe: {len(df):,} tickers")
    print(f"Sectors:\n{df['sector'].value_counts().head(20).to_string()}")
    print(f"\nSample rows:\n{df.head(10).to_string(index=False)}")
