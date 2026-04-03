# screener/relative_valuation.py
# ═══════════════════════════════════════════════════════════════
# Relative-Valuation Engine — Non-DCF Sectors
# ═══════════════════════════════════════════════════════════════
#
# Used for sectors where FCF-based DCF is structurally invalid:
#   Financials  — banks, insurers, asset managers
#                 Net interest income IS the product; "capex" means lending.
#                 FCF projections have no structural meaning.
#   Real Estate — REITs use FFO/AFFO, not FCF.
#                 Depreciation add-back inflates reported OCF vs true cash.
#
# Instead we compare P/E, Forward P/E, P/B, P/S, EV/EBITDA to
# sector medians.  Signal = Premium / At Average / Discount.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import pathlib
from typing import Optional

import pandas as pd
import yfinance as yf

from utils.logger import get_logger

log = get_logger(__name__)

# ── Non-DCF sector identification ─────────────────────────────

# detect_sector() key prefixes that indicate non-DCF sectors
_NON_DCF_SECTOR_KEYS: set[str] = {
    "us_banks", "us_reits", "us_insurance", "in_banks",
}

# GICS sector name strings (from Yahoo Finance / usa_tickers.csv)
_NON_DCF_GICS_SECTORS: set[str] = {"Financials", "Real Estate"}

# ── Sector median reference table ─────────────────────────────
# Source: S&P 1500 trailing 5-year average medians (approximate).
# Updated as needed; overridable via batch_medians parameter.
#
# Metrics: pe, forward_pe, pb, ps, ev_ebitda
#
_SECTOR_MEDIANS: dict[str, dict[str, float]] = {
    "us_banks": {
        "pe":          13.0,
        "forward_pe":  11.0,
        "pb":           1.3,
        "ps":           3.0,
        "ev_ebitda":   11.0,
    },
    "us_reits": {
        "pe":          30.0,
        "forward_pe":  24.0,
        "pb":           1.6,
        "ps":           7.5,
        "ev_ebitda":   23.0,
    },
    "us_insurance": {
        "pe":          12.0,
        "forward_pe":  10.5,
        "pb":           1.5,
        "ps":           1.0,
        "ev_ebitda":   10.0,
    },
    "in_banks": {
        "pe":          14.0,
        "forward_pe":  12.0,
        "pb":           2.0,
        "ps":           3.5,
        "ev_ebitda":   12.0,
    },
    # Generic fallbacks keyed by GICS sector name
    "Financials": {
        "pe":          13.5,
        "forward_pe":  11.5,
        "pb":           1.4,
        "ps":           2.8,
        "ev_ebitda":   11.5,
    },
    "Real Estate": {
        "pe":          28.0,
        "forward_pe":  22.0,
        "pb":           1.6,
        "ps":           7.0,
        "ev_ebitda":   22.0,
    },
}

# Human-readable metric labels
_METRIC_LABELS: dict[str, str] = {
    "pe":          "Trailing P/E",
    "forward_pe":  "Forward P/E",
    "pb":          "Price / Book",
    "ps":          "Price / Sales",
    "ev_ebitda":   "EV / EBITDA",
}

# Signal thresholds (weighted average premium vs sector, %)
_PREMIUM_THRESHOLD  =  15.0   # avg > +15% → Premium to Sector
_DISCOUNT_THRESHOLD = -15.0   # avg < -15% → Discount to Sector

# ── CSV eligibility loader ─────────────────────────────────────

def load_dcf_eligibility_map(
    csv_path: pathlib.Path | str | None = None,
) -> dict[str, bool]:
    """
    Load {ticker: dcf_eligible} from usa_tickers.csv.
    Returns empty dict if file not found or missing column.
    """
    if csv_path is None:
        csv_path = pathlib.Path(__file__).parent.parent / "data" / "usa_tickers.csv"
    try:
        df = pd.read_csv(csv_path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "ticker" not in df.columns:
            return {}
        if "dcf_eligible" not in df.columns:
            # Derive from sector column if present
            if "sector" in df.columns:
                df["dcf_eligible"] = ~df["sector"].isin(_NON_DCF_GICS_SECTORS)
            else:
                return {}
        return dict(zip(df["ticker"].str.upper().str.strip(),
                        df["dcf_eligible"].astype(bool)))
    except Exception as exc:
        log.debug(f"load_dcf_eligibility_map: {exc}")
        return {}


def check_ticker_dcf_eligibility(
    ticker: str,
    sector_key: str = "",
    gics_sector: str = "",
    csv_path: pathlib.Path | str | None = None,
) -> bool:
    """
    Return True if the ticker should use full DCF analysis.

    Priority:
    1. usa_tickers.csv  dcf_eligible column  (most accurate — manually curated)
    2. sector_key       from detect_sector()  (internal key like "us_banks")
    3. gics_sector      from Yahoo Finance    ("Financials", "Real Estate")
    4. Default True     (DCF eligible unless proven otherwise)
    """
    # 1. CSV lookup
    elig_map = load_dcf_eligibility_map(csv_path)
    if ticker.upper() in elig_map:
        return elig_map[ticker.upper()]

    # 2. Internal sector key
    for key in _NON_DCF_SECTOR_KEYS:
        if sector_key.startswith(key) or sector_key == key:
            return False

    # 3. GICS sector name
    if gics_sector in _NON_DCF_GICS_SECTORS:
        return False

    return True


# ── Core computation ───────────────────────────────────────────

def _fetch_ratios(ticker: str, raw: dict | None = None) -> dict[str, float]:
    """
    Fetch valuation multiples from yfinance info dict.
    Falls back gracefully to raw dict keys from StockDataCollector.
    """
    info: dict = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as exc:
        log.debug(f"[{ticker}] yfinance info fetch: {exc}")

    def _f(primary_key: str, *fallback_keys: str) -> float:
        for k in (primary_key, *fallback_keys):
            v = info.get(k) or (raw or {}).get(k)
            try:
                f = float(v)
                if f > 0:
                    return round(f, 2)
            except (TypeError, ValueError):
                pass
        return 0.0

    return {
        "pe":         _f("trailingPE",  "trailingPe", "pe_ratio"),
        "forward_pe": _f("forwardPE",   "forward_pe"),
        "pb":         _f("priceToBook", "pb_ratio"),
        "ps":         _f("priceToSalesTrailing12Months", "ps_ratio"),
        "ev_ebitda":  _f("enterpriseToEbitda", "ev_ebitda"),
        "price":      _f("currentPrice", "regularMarketPrice", "price"),
        "name":       str(info.get("longName") or info.get("shortName") or ""),
        "market_cap": _f("marketCap"),
        "dividend_yield": round(float(info.get("dividendYield") or 0) * 100, 2),
        "beta":       _f("beta"),
        "52w_high":   _f("fiftyTwoWeekHigh"),
        "52w_low":    _f("fiftyTwoWeekLow"),
    }


def _resolve_medians(
    sector_key: str,
    gics_sector: str,
    batch_medians: dict | None,
) -> dict[str, float]:
    """Return the best available sector median dict."""
    if batch_medians:
        return batch_medians
    if sector_key in _SECTOR_MEDIANS:
        return _SECTOR_MEDIANS[sector_key]
    if gics_sector in _SECTOR_MEDIANS:
        return _SECTOR_MEDIANS[gics_sector]
    # Fallback: generic Financials
    return _SECTOR_MEDIANS["Financials"]


def _overall_signal(metric_results: list[dict]) -> tuple[str, float]:
    """
    Compute overall premium/discount signal from individual metric results.
    Returns (signal_label, avg_vs_sector_pct).
    """
    valid = [m for m in metric_results if m["available"]]
    if not valid:
        return "Insufficient Data", 0.0

    avg = sum(m["vs_sector_pct"] for m in valid) / len(valid)

    if avg >= _PREMIUM_THRESHOLD:
        signal = "Premium to Sector"
    elif avg <= _DISCOUNT_THRESHOLD:
        signal = "Discount to Sector"
    else:
        signal = "At Sector Average"

    return signal, round(avg, 1)


def relative_valuation_only(
    ticker: str,
    sector_key: str,
    raw: dict | None = None,
    gics_sector: str = "",
    batch_medians: dict | None = None,
) -> dict:
    """
    Run relative-valuation analysis for a non-DCF-eligible ticker.

    Parameters
    ----------
    ticker        : stock symbol
    sector_key    : internal sector key from detect_sector() e.g. "us_banks"
    raw           : optional StockDataCollector output (used for price fallback)
    gics_sector   : GICS sector string from Yahoo Finance (e.g. "Financials")
    batch_medians : override medians from screener batch computation

    Returns
    -------
    dict with keys:
        ticker, sector_key, gics_sector, dcf_eligible, price, name,
        metrics (list of per-metric dicts),
        signal, signal_avg_pct, overall_score,
        medians_used, market_cap, dividend_yield, beta
    """
    ratios  = _fetch_ratios(ticker, raw)
    medians = _resolve_medians(sector_key, gics_sector, batch_medians)
    price   = ratios.get("price") or (raw or {}).get("price", 0)

    metric_results: list[dict] = []
    for key in ("pe", "forward_pe", "pb", "ps", "ev_ebitda"):
        val    = ratios.get(key, 0)
        median = medians.get(key, 0)
        available = val > 0 and median > 0

        if available:
            vs_pct = round((val - median) / median * 100, 1)
            if vs_pct > 0:
                vs_label = f"+{vs_pct:.1f}% premium"
            elif vs_pct < 0:
                vs_label = f"{vs_pct:.1f}% discount"
            else:
                vs_label = "at sector average"
        else:
            vs_pct   = 0.0
            vs_label = "N/A"

        metric_results.append({
            "key":          key,
            "label":        _METRIC_LABELS[key],
            "value":        val,
            "sector_median":median,
            "vs_sector_pct":vs_pct,
            "vs_label":     vs_label,
            "available":    available,
        })

    signal, avg_pct = _overall_signal(metric_results)

    # Numeric score for screener sorting: +1 discount, 0 average, -1 premium
    if signal == "Discount to Sector":
        overall_score = 1
    elif signal == "At Sector Average":
        overall_score = 0
    else:
        overall_score = -1

    return {
        "ticker":          ticker,
        "sector_key":      sector_key,
        "gics_sector":     gics_sector or sector_key,
        "dcf_eligible":    False,
        "price":           round(float(price), 2) if price else 0.0,
        "name":            ratios.get("name", ""),
        "metrics":         metric_results,
        "signal":          signal,
        "signal_avg_pct":  avg_pct,
        "overall_score":   overall_score,
        "medians_used":    medians,
        "market_cap":      ratios.get("market_cap", 0),
        "dividend_yield":  ratios.get("dividend_yield", 0),
        "beta":            ratios.get("beta", 0),
        "52w_high":        ratios.get("52w_high", 0),
        "52w_low":         ratios.get("52w_low", 0),
    }


def compute_batch_medians(rel_val_results: list[dict]) -> dict[str, float]:
    """
    Compute actual sector medians from a batch of relative_valuation_only() outputs.
    Used by the screener to replace hardcoded medians after a full run.
    """
    if not rel_val_results:
        return {}

    collected: dict[str, list[float]] = {k: [] for k in ("pe", "forward_pe", "pb", "ps", "ev_ebitda")}
    for r in rel_val_results:
        for m in r.get("metrics", []):
            if m["available"] and m["value"] > 0:
                collected[m["key"]].append(m["value"])

    medians = {}
    for key, vals in collected.items():
        if vals:
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            mid = n // 2
            medians[key] = round(
                vals_sorted[mid] if n % 2 else (vals_sorted[mid - 1] + vals_sorted[mid]) / 2,
                2,
            )
    return medians
