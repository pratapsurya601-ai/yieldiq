# yieldiq/seo/top500.py
# ─────────────────────────────────────────────────────────────
# Returns an ordered list of (ticker, name, sector, dcf_eligible)
# tuples for the top 500 US stocks by SEO priority.
#
# Priority ordering: mega-caps most searched on Google come first,
# then the remaining S&P 1500 universe fills up to n=500.
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

import pathlib
from typing import NamedTuple

import pandas as pd

# ── Non-DCF sectors (mirrors collector.py / relative_valuation.py) ───────────
_NON_DCF_SECTORS = {"Financials", "Real Estate"}

# ── Priority list: ~120 highest-traffic US stocks by search volume ────────────
# These are placed first in the output so the generator produces the most
# valuable SEO pages first (in case the run is interrupted or partially cached).
_PRIORITY_TICKERS: list[str] = [
    # ── Mega-cap tech ──────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
    "AVGO", "ORCL", "AMD", "INTC", "CSCO", "ADBE", "CRM", "INTU",
    "TXN", "QCOM", "AMAT", "LRCX", "MU", "KLAC", "NOW", "SNPS", "CDNS",
    "PANW", "CRWD", "FTNT", "PLTR", "SHOP",
    # ── Mega-cap financials ────────────────────────────────────
    "BRK-B", "JPM", "V", "MA", "BAC", "GS", "MS", "WFC", "C",
    "AXP", "BLK", "SPGI", "MCO", "CME", "ICE", "USB", "TFC", "SCHW",
    "CB", "MMC", "PGR", "MET", "PRU",
    # ── Healthcare & pharma ────────────────────────────────────
    "UNH", "LLY", "JNJ", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "PFE", "AMGN", "GILD", "ISRG", "SYK", "BSX", "MDT", "ELV", "CI",
    "VRTX", "REGN", "ZTS", "HCA", "CVS", "MCK", "ABC",
    # ── Consumer & retail ─────────────────────────────────────
    "WMT", "HD", "COST", "MCD", "SBUX", "NKE", "LOW", "TJX",
    "BKNG", "MAR", "HLT", "ABNB", "YUM", "CMG", "EBAY", "ETSY",
    "TGT", "DG", "DLTR",
    # ── Energy & industrials ───────────────────────────────────
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "VLO", "MPC",
    "GE", "CAT", "HON", "RTX", "LMT", "NOC", "BA", "UPS", "FDX",
    "DE", "ETN", "EMR", "ITW", "PH",
    # ── Consumer staples ──────────────────────────────────────
    "PG", "KO", "PEP", "PM", "MO", "MDLZ", "CL", "KMB", "GIS",
    "HSY", "SJM", "K", "CAG",
    # ── Utilities & real estate ───────────────────────────────
    "NEE", "SO", "DUK", "D", "SRE", "AEP", "PCG",
    "PLD", "AMT", "CCI", "EQIX", "SPG", "O",
    # ── Telecom & media ───────────────────────────────────────
    "T", "VZ", "TMUS", "NFLX", "DIS", "CMCSA", "CHTR",
    # ── Other large-caps ──────────────────────────────────────
    "ACN", "IBM", "UBER", "LYFT", "ABNB", "DDOG", "ZM", "SNOW", "COIN",
    "F", "GM", "RIVN", "LCID", "STLA", "TM",
]


class TickerInfo(NamedTuple):
    ticker: str
    name: str
    sector: str
    dcf_eligible: bool


def get_top500(
    csv_path: str | pathlib.Path | None = None,
    n: int = 500,
) -> list[TickerInfo]:
    """
    Return up to *n* TickerInfo tuples ordered by SEO priority.

    Priority order:
      1. _PRIORITY_TICKERS (in their defined order, filtered to those in CSV)
      2. Remaining CSV tickers (alphabetical)

    Parameters
    ----------
    csv_path : path to usa_tickers.csv. Auto-detects relative to this file
               if not given.
    n        : maximum number of tickers to return (default 500).
    """
    if csv_path is None:
        # Walk up from this file to find the data directory
        _here = pathlib.Path(__file__).parent
        csv_path = _here.parent / "data" / "usa_tickers.csv"

    csv_path = pathlib.Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Ticker CSV not found: {csv_path}\n"
            "Run  python build_us_tickers.py  first to generate it."
        )

    df = pd.read_csv(csv_path, dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    # Normalise column names
    if "ticker" not in df.columns:
        raise ValueError(f"Expected 'ticker' column in {csv_path}. Found: {list(df.columns)}")

    df["ticker"]  = df["ticker"].str.strip().str.upper()
    df["name"]    = df.get("name",   pd.Series([""] * len(df))).fillna("").str.strip()
    df["sector"]  = df.get("sector", pd.Series([""] * len(df))).fillna("").str.strip()

    # dcf_eligible: use CSV column if present, otherwise infer from sector
    if "dcf_eligible" in df.columns:
        df["dcf_eligible"] = df["dcf_eligible"].astype(str).str.lower().isin(("true", "1", "yes"))
    else:
        df["dcf_eligible"] = ~df["sector"].isin(_NON_DCF_SECTORS)

    # Build a lookup for O(1) access
    lookup: dict[str, TickerInfo] = {
        row["ticker"]: TickerInfo(
            ticker=row["ticker"],
            name=row["name"],
            sector=row["sector"],
            dcf_eligible=bool(row["dcf_eligible"]),
        )
        for _, row in df.iterrows()
    }

    # ── Ordered result: priority tickers first ────────────────────
    seen: set[str] = set()
    result: list[TickerInfo] = []

    for t in _PRIORITY_TICKERS:
        if t in lookup and t not in seen:
            result.append(lookup[t])
            seen.add(t)

    # Fill remaining slots from CSV (alphabetical)
    for t in sorted(lookup.keys()):
        if t not in seen:
            result.append(lookup[t])
            seen.add(t)

    return result[:n]
