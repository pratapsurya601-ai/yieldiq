#!/usr/bin/env python3
"""
build_us_tickers.py  — Standalone Russell 3000 / S&P 1500 ticker universe builder
==================================================================================
Run from the project root (yieldiq_v6/) with:

    python build_us_tickers.py                        # S&P 1500 + Russell 3000
    python build_us_tickers.py --source sp1500        # S&P 1500 only (faster)
    python build_us_tickers.py --source russell3000   # Russell 3000 only
    python build_us_tickers.py --fetch-market-caps    # also mark micro-caps non-DCF
    python build_us_tickers.py --russell-csv IWV.csv  # use pre-downloaded CSV

or with an explicit output path:

    python build_us_tickers.py --output path/to/usa_tickers.csv

Requires: pandas lxml requests yfinance
    pip install pandas lxml requests yfinance
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys
import threading
from typing import Optional

try:
    import pandas as pd
except ImportError:
    sys.exit("ERROR: pandas is not installed.  Run: pip install pandas lxml requests yfinance")

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]


# ── Constants ─────────────────────────────────────────────────────────────────

_NON_DCF_SECTORS = {"Financials", "Real Estate"}

_MICRO_CAP_THRESHOLD: float = 300_000_000   # $300 M

_RUSSELL_ETF_URLS: list[str] = [
    (
        "https://www.ishares.com/us/products/239714/"
        "ISHARES-RUSSELL-3000-ETF/1467271812596.ajax"
        "?fileType=csv&fileName=IWV_holdings&dataType=fund"
    ),
    (
        "https://www.ishares.com/us/products/239714/"
        "ishares-russell-3000-etf/1467271812596.ajax"
        "?fileType=csv&dataType=fund"
    ),
]

_ISHARES_SECTOR_NORM: dict[str, str] = {
    "information technology":     "Information Technology",
    "technology":                 "Information Technology",
    "financials":                 "Financials",
    "health care":                "Health Care",
    "healthcare":                 "Health Care",
    "consumer discretionary":     "Consumer Discretionary",
    "consumer staples":           "Consumer Staples",
    "industrials":                "Industrials",
    "energy":                     "Energy",
    "utilities":                  "Utilities",
    "real estate":                "Real Estate",
    "materials":                  "Materials",
    "communication services":     "Communication Services",
    "telecommunication services": "Communication Services",
    "telecom":                    "Communication Services",
}

# Wikipedia table specs
_SP_SOURCES = [
    {
        "url":        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "index_name": "S&P 500",
    },
    {
        "url":        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        "index_name": "S&P 400",
    },
    {
        "url":        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        "index_name": "S&P 600",
    },
]

# Wikipedia edits column headers occasionally; accept any of these aliases
_TICKER_ALIASES = ["Symbol", "Ticker symbol", "Ticker", "Ticker Symbol"]
_NAME_ALIASES   = ["Security", "Company", "Name", "Company name"]
_SECTOR_ALIASES = ["GICS Sector", "Sector", "GICS sector"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_col(df: pd.DataFrame, aliases: list[str]) -> str:
    """Return the first matching column name (case-insensitive fallback)."""
    cols_lower = {c.strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias in df.columns:
            return alias
        if alias.lower() in cols_lower:
            return cols_lower[alias.lower()]
    raise KeyError(f"None of {aliases} found. Available columns: {list(df.columns)}")


def _fetch_sp_index(url: str, index_name: str) -> pd.DataFrame:
    """Download and parse one S&P index table from Wikipedia."""
    print(f"  Fetching {index_name} from Wikipedia …", end=" ", flush=True)

    try:
        tables = pd.read_html(url, attrs={"class": "wikitable"}, flavor="lxml")
    except Exception as exc:
        raise RuntimeError(f"Network/parse error: {exc}") from exc

    df = max(tables, key=len).copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(c) for c in col).strip() for col in df.columns]
    df.columns = [str(c).strip() for c in df.columns]

    tc = _pick_col(df, _TICKER_ALIASES)
    nc = _pick_col(df, _NAME_ALIASES)
    sc = _pick_col(df, _SECTOR_ALIASES)

    out = pd.DataFrame({
        "ticker": (
            df[tc].astype(str)
                  .str.strip()
                  .str.upper()
                  .str.replace(r"\s+", "", regex=True)
        ),
        "name":   df[nc].astype(str).str.strip(),
        "sector": df[sc].astype(str).str.strip(),
        "index":  index_name,
    })

    out = out[out["ticker"].str.match(r"^[A-Z]{1,5}(\.[A-Z])?$", na=False)]
    out = out.dropna(subset=["ticker"])

    print(f"{len(out)} tickers")
    return out


def _fetch_russell3000_ishares(
    url: Optional[str] = None,
    local_csv: Optional[pathlib.Path] = None,
    timeout: int = 30,
) -> pd.DataFrame:
    """
    Download and parse the iShares Russell 3000 ETF (IWV) holdings CSV.

    Returns a DataFrame with columns [ticker, name, sector, index].
    """
    if requests is None:
        raise ImportError("requests is required.  Run: pip install requests")

    if local_csv is not None:
        print(f"  Reading Russell 3000 from local file: {local_csv}")
        raw_text = pathlib.Path(local_csv).read_text(encoding="utf-8", errors="replace")
    else:
        urls_to_try = [url] if url else _RUSSELL_ETF_URLS
        raw_text = None
        last_err: Exception | None = None
        for u in urls_to_try:
            try:
                print(f"  Downloading Russell 3000 from iShares …", end=" ", flush=True)
                resp = requests.get(u, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                raw_text = resp.text
                print("done")
                break
            except Exception as exc:
                last_err = exc
                print(f"failed ({exc})")
        if raw_text is None:
            raise RuntimeError(
                f"Could not download Russell 3000 holdings. Last error: {last_err}"
            )

    # iShares CSVs have metadata rows before the data header.
    # Scan for the first row whose first cell is "Name" or "Ticker".
    lines = raw_text.splitlines()
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        first_cell = line.split(",")[0].strip().strip('"')
        if first_cell.lower() in ("name", "ticker"):
            header_idx = i
            break

    if header_idx is None:
        raise RuntimeError(
            "Could not locate the data header in the iShares CSV. "
            "The file format may have changed."
        )

    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    _TICKER_CANDS = ["ticker", "exchange ticker", "issuer ticker"]
    _NAME_CANDS   = ["name", "security name", "issuer name"]
    _SECTOR_CANDS = ["sector", "gics sector classification"]
    _ASSET_CANDS  = ["asset class", "type"]

    def _find(candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    ticker_col = _find(_TICKER_CANDS)
    name_col   = _find(_NAME_CANDS)
    sector_col = _find(_SECTOR_CANDS)
    asset_col  = _find(_ASSET_CANDS)

    if ticker_col is None or sector_col is None:
        raise RuntimeError(f"iShares CSV missing expected columns. Found: {list(df.columns)}")

    # Filter to equity holdings only
    if asset_col:
        df = df[
            df[asset_col].str.strip().str.lower().isin(
                {"equity", "common stock", "depositary receipts"}
            )
        ].copy()

    out = pd.DataFrame()
    out["ticker"] = (
        df[ticker_col].astype(str).str.strip().str.upper()
                      .str.replace(r"\s+", "", regex=True)
    )
    out["name"]   = df[name_col].astype(str).str.strip() if name_col else "Unknown"
    out["sector"] = (
        df[sector_col].astype(str).str.strip().str.lower()
                      .map(lambda s: _ISHARES_SECTOR_NORM.get(s, s.title()))
    )
    out["index"] = "Russell 3000"

    out = out[out["ticker"].str.match(r"^[A-Z]{1,5}(\.[A-Z])?$", na=False)]
    out = out.dropna(subset=["ticker"])
    out = out.drop_duplicates(subset="ticker").reset_index(drop=True)

    print(f"  Russell 3000: {len(out)} equity tickers parsed")
    return out


def _fetch_market_caps_yf(
    tickers: list[str],
    max_workers: int = 20,
) -> dict[str, Optional[float]]:
    """
    Fetch market caps for a list of tickers via yfinance fast_info (threaded).
    """
    if yf is None:
        raise ImportError("yfinance is required.  Run: pip install yfinance")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    result: dict[str, Optional[float]] = {}

    def _get_one(ticker: str) -> tuple[str, Optional[float]]:
        try:
            mc = yf.Ticker(ticker).fast_info.market_cap
            return ticker, float(mc) if mc else None
        except Exception:
            return ticker, None

    total = len(tickers)
    print(f"  Fetching market caps for {total} tickers (workers={max_workers}) …")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_get_one, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            ticker, cap = fut.result()
            result[ticker] = cap
            done += 1
            if done % 200 == 0:
                print(f"    … {done}/{total}")

    fetched = sum(1 for v in result.values() if v is not None)
    print(f"  Market cap fetch complete: {fetched}/{total} succeeded")
    return result


# ── Main builder ──────────────────────────────────────────────────────────────

def build_us_ticker_universe(
    output_path: pathlib.Path,
    *,
    source: str = "both",
    russell_csv: Optional[pathlib.Path] = None,
    fetch_market_caps: bool = False,
    market_cap_threshold: float = _MICRO_CAP_THRESHOLD,
) -> pd.DataFrame:
    """
    Build and write usa_tickers.csv.

    Parameters
    ----------
    output_path          : destination CSV file path
    source               : "sp1500", "russell3000", or "both"
    russell_csv          : path to pre-downloaded iShares IWV CSV (skips download)
    fetch_market_caps    : fetch market caps and mark micro-caps dcf_eligible=False
    market_cap_threshold : USD cutoff for micro-cap exclusion (default $300 M)
    """
    source = source.lower()
    assert source in ("sp1500", "russell3000", "both"), f"Invalid source: {source!r}"

    frames_sp: list[pd.DataFrame] = []
    failed: list[str] = []

    print(f"\nBuilding US ticker universe  [source={source}]\n")

    # ── S&P 1500 from Wikipedia ────────────────────────────────────
    if source in ("sp1500", "both"):
        for src in _SP_SOURCES:
            try:
                df = _fetch_sp_index(src["url"], src["index_name"])
                frames_sp.append(df)
            except Exception as exc:
                print(f"  WARNING: {src['index_name']} failed — {exc}")
                failed.append(src["index_name"])

        if source == "sp1500" and not frames_sp:
            sys.exit(
                "\nERROR: Could not fetch any S&P index from Wikipedia.\n"
                "Check your internet connection and try again."
            )

    # ── Russell 3000 from iShares ─────────────────────────────────
    russell_df: Optional[pd.DataFrame] = None
    if source in ("russell3000", "both"):
        try:
            russell_df = _fetch_russell3000_ishares(local_csv=russell_csv)
        except Exception as exc:
            print(f"  WARNING: Russell 3000 fetch failed — {exc}")
            if source == "russell3000":
                sys.exit("\nERROR: Could not load Russell 3000 holdings. Aborting.")
            print("  Continuing with S&P 1500 only.")

    # ── Merge ─────────────────────────────────────────────────────
    if frames_sp and russell_df is not None:
        sp_combined = pd.concat(frames_sp, ignore_index=True)
        sp_combined = sp_combined.drop_duplicates(subset="ticker", keep="first")
        sp_tickers  = set(sp_combined["ticker"])
        russell_only = russell_df[~russell_df["ticker"].isin(sp_tickers)].copy()
        combined = pd.concat([sp_combined, russell_only], ignore_index=True)
        combined["_source_sp"] = combined["ticker"].isin(sp_tickers)
    elif frames_sp:
        combined = pd.concat(frames_sp, ignore_index=True)
        combined = combined.drop_duplicates(subset="ticker", keep="first")
        combined["_source_sp"] = True
    elif russell_df is not None:
        combined = russell_df.copy()
        combined["_source_sp"] = False
    else:
        sys.exit("\nERROR: No tickers loaded from any source.")

    # ── Sector-based DCF eligibility ──────────────────────────────
    combined["dcf_eligible"] = ~combined["sector"].isin(_NON_DCF_SECTORS)

    # ── Micro-cap filter (optional, Russell-only tickers) ─────────
    micro_cap_tickers: set[str] = set()
    if fetch_market_caps and russell_df is not None:
        candidates = combined[
            (~combined["_source_sp"]) & combined["dcf_eligible"]
        ]["ticker"].tolist()

        if candidates:
            caps = _fetch_market_caps_yf(candidates)
            micro_cap_tickers = {
                t for t, cap in caps.items()
                if cap is not None and cap < market_cap_threshold
            }
            combined.loc[
                combined["ticker"].isin(micro_cap_tickers), "dcf_eligible"
            ] = False
            print(
                f"  Micro-cap filter: {len(micro_cap_tickers)} tickers marked "
                f"dcf_eligible=False (market cap < ${market_cap_threshold:,.0f})"
            )

    # ── Final cleanup + save ──────────────────────────────────────
    out = (
        combined[["ticker", "name", "sector", "dcf_eligible"]]
        .sort_values("ticker")
        .reset_index(drop=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    # ── Summary ───────────────────────────────────────────────────
    total   = len(out)
    dcf_ok  = int(out["dcf_eligible"].sum())
    non_dcf = total - dcf_ok

    by_index  = combined.groupby("index").size() if "index" in combined.columns else pd.Series(dtype=int)
    by_sector = out.groupby("sector").size().sort_values(ascending=False)

    print("\n" + "═" * 56)
    print("  YieldIQ — US Ticker Universe Build Complete")
    print("═" * 56)

    if failed:
        print(f"  ⚠  Skipped (fetch failed): {', '.join(failed)}")

    for idx_name in ["S&P 500", "S&P 400", "S&P 600", "Russell 3000"]:
        cnt = int(by_index.get(idx_name, 0))
        if cnt:
            print(f"  {idx_name:<18} : {cnt:>4} tickers")

    print(f"  {'─' * 40}")
    print(f"  Total unique      : {total:>4}")
    print(f"  DCF-eligible      : {dcf_ok:>4}  (excl. Financials & Real Estate)")
    if micro_cap_tickers:
        sector_non_dcf = non_dcf - len(micro_cap_tickers)
        print(f"  Non-DCF (sector)  : {sector_non_dcf:>4}  (Financials, Real Estate)")
        print(f"  Non-DCF (micro-cap): {len(micro_cap_tickers):>4}  (<${market_cap_threshold/1e6:.0f}M)")
    else:
        print(f"  Non-DCF           : {non_dcf:>4}  (Financials + Real Estate)")

    print()
    print("  Sector breakdown:")
    for sector, cnt in by_sector.items():
        flag = " ← non-DCF" if sector in _NON_DCF_SECTORS else ""
        print(f"    {sector:<38} {int(cnt):>4}{flag}")

    print(f"\n  ✓ Saved → {output_path}")
    print("═" * 56 + "\n")

    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def _default_output() -> pathlib.Path:
    return pathlib.Path(__file__).parent / "yieldiq" / "data" / "usa_tickers.csv"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Build the US ticker universe CSV for YieldIQ. "
            "Combines S&P 1500 (Wikipedia) and/or Russell 3000 (iShares IWV)."
        )
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=f"Output CSV path (default: {_default_output()})",
    )
    parser.add_argument(
        "--source",
        default="both",
        choices=["sp1500", "russell3000", "both"],
        help=(
            "Ticker universe source: 'sp1500' (Wikipedia S&P 500/400/600), "
            "'russell3000' (iShares IWV holdings), or 'both' (merge, S&P takes "
            "priority for duplicates). Default: both."
        ),
    )
    parser.add_argument(
        "--russell-csv",
        default=None,
        metavar="PATH",
        help=(
            "Path to a pre-downloaded iShares IWV holdings CSV. "
            "Skips the network fetch. Only used with --source russell3000 or both."
        ),
    )
    parser.add_argument(
        "--fetch-market-caps",
        action="store_true",
        help=(
            "Fetch market caps via yfinance for Russell-only tickers and mark "
            "those below --market-cap-threshold as dcf_eligible=False. "
            "Slow: makes one yfinance call per ticker."
        ),
    )
    parser.add_argument(
        "--market-cap-threshold",
        type=float,
        default=_MICRO_CAP_THRESHOLD,
        metavar="USD",
        help=(
            f"Market cap cutoff in USD for micro-cap DCF exclusion. "
            f"Default: {_MICRO_CAP_THRESHOLD:,.0f} ($300 M)."
        ),
    )

    args = parser.parse_args()

    out_path = pathlib.Path(args.output) if args.output else _default_output()
    russell_path = pathlib.Path(args.russell_csv) if args.russell_csv else None

    build_us_ticker_universe(
        out_path,
        source=args.source,
        russell_csv=russell_path,
        fetch_market_caps=args.fetch_market_caps,
        market_cap_threshold=args.market_cap_threshold,
    )
