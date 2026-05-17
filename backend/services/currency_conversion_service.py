"""USD → INR conversion for Indian IT-services tickers that report financials
in USD on yfinance (MPHASIS, COFORGE, PERSISTENT, KPITTECH, etc).

Why this exists
---------------
A handful of Indian IT-services issuers list on NSE/BSE in INR but file
their statutory financials in USD (their largest customer is in the US
and group reporting consolidates in dollars). yfinance faithfully passes
these statements through with ``financialCurrency='USD'``.

The rest of YieldIQ assumes every financial-statement number that
reaches the model is denominated in INR Crores. If we feed a USD-denominated
Total Revenue into a DCF whose discount rate, terminal-growth, and price
all live in INR, the resulting fair value is off by ~83× and the
analysis cache falls to ``data_limited`` with a multi-trillion-Cr FV.

Pre-2026-05-17 the codebase handled this case by *rejecting* USD rows
entirely (see ``data_pipeline/xbrl/yf_fetcher.py`` and
``data_pipeline/sources/yf_info_cache.py``). That was the right call
for ADR mistags (INFY-ADR returning USD data on the .NS ticker) but
wrong for legitimate USD reporters — for those issuers there is no
INR statement anywhere to fall back to.

This module fills that gap: if a ticker is a confirmed USD reporter,
convert every monetary field to INR using the USD/INR spot rate at the
statement period-end, then hand the converted dict back to the rest of
the pipeline as if it had always been INR.

Detection
---------
Two complementary signals:

1. **Allow-list** (``USD_REPORTER_TICKERS``) — explicit, hard-coded
   seed of issuers that are *known* to report in USD. This is the
   safety floor: even if yfinance flips a field back to INR for one
   refresh cycle, the allow-list keeps the conversion stable.

2. **Live yfinance signal** — ``info.get('financialCurrency') == 'USD'``
   on a ticker that *is* in the Indian-primary universe (i.e. not an
   explicit ADR like INFY-ADR/WIT/HDB). This grows the population over
   time without code changes.

Either signal flips conversion on. Both must be false to leave the
data untouched.

Conversion
----------
``convert_usd_to_inr(amount_usd, period_end_date)`` returns
``amount_usd × rate(period_end_date)`` where ``rate`` is the daily
close of yfinance's ``INR=X`` series (USDINR spot). Rates are fetched
once per process and cached in-memory; missing dates back-fill to the
nearest prior available trading day (USDINR doesn't trade on Indian
holidays, US Thanksgiving, etc — backfilling avoids spurious gaps).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping

log = logging.getLogger("yieldiq.currency_conversion")


# ── Allow-list ──────────────────────────────────────────────────────
# Indian IT-services issuers whose statutory financials are filed in
# USD. Listings are on NSE/BSE in INR but the income statement,
# balance sheet, and cash flow on yfinance come back USD-denominated.
#
# Seed list curated 2026-05-17 from the ``data_limited`` cohort —
# every ticker here was producing multi-trillion-Cr FVs because the
# USD figures were being treated as INR by the DCF. Expand by adding
# bare NSE tickers (no ``.NS`` suffix); detection is suffix-agnostic.
USD_REPORTER_TICKERS: frozenset[str] = frozenset({
    "MPHASIS",
    "COFORGE",
    "PERSISTENT",
    "KPITTECH",
})


def _bare(ticker: str) -> str:
    """Strip exchange suffix for allow-list comparison."""
    if not ticker:
        return ""
    return (
        ticker.upper()
        .replace(".NS", "")
        .replace(".BO", "")
        .replace("-EQ", "")
    )


def is_usd_reporter(ticker: str, info: Mapping | None = None) -> bool:
    """Return True if ``ticker`` reports financials in USD.

    Decision is the OR of:

    * ``ticker`` (suffix-stripped) appears in :data:`USD_REPORTER_TICKERS`, or
    * ``info['financialCurrency'] == 'USD'`` AND the ticker carries an
      Indian exchange suffix (``.NS`` / ``.BO``) — the suffix check
      keeps actual ADRs (INFY, WIT, HDB) from being mis-classified
      here when callers pass ADR tickers through by mistake.

    ``info`` is the dict from :class:`yfinance.Ticker.info`. Callers
    that don't have it handy can pass ``None`` and rely on the
    allow-list only.
    """
    bare = _bare(ticker)
    if bare in USD_REPORTER_TICKERS:
        return True
    if info:
        ccy = str(info.get("financialCurrency") or "").upper()
        if ccy == "USD":
            upper = (ticker or "").upper()
            if upper.endswith(".NS") or upper.endswith(".BO"):
                return True
    return False


# ── USD/INR rate cache ──────────────────────────────────────────────
# Per-process. Built lazily on first lookup. Map of YYYY-MM-DD → rate.
_RATE_CACHE: dict[str, float] = {}
_RATE_FETCH_DONE: bool = False

# Last-resort fallback when yfinance INR=X is unreachable (CI offline,
# Yahoo down, etc). Mid-2024 → 2026 averaged ~83 ± 1.5; using 83.0
# keeps a conversion path open in degraded conditions. Logged at
# WARNING so the staleness is visible in Railway logs.
_FALLBACK_RATE: float = 83.0


def _fetch_inr_rate_history() -> dict[str, float]:
    """Pull USDINR daily close from yfinance ``INR=X`` and return a
    ``{YYYY-MM-DD: rate}`` map. Returns ``{}`` on any failure."""
    try:
        import yfinance as yf
        # 15 years covers every period_end_date we plausibly see in
        # yfinance fundamentals (which top out at ~5 years of annual
        # statements). ``auto_adjust=False`` to keep the raw close.
        hist = yf.Ticker("INR=X").history(period="15y", auto_adjust=False)
        if hist is None or hist.empty:
            return {}
        out: dict[str, float] = {}
        for ts, close in hist["Close"].items():
            try:
                key = ts.strftime("%Y-%m-%d")
                val = float(close)
                if val > 0:
                    out[key] = val
            except Exception:
                continue
        return out
    except Exception as exc:
        log.warning("USD/INR rate fetch failed: %s", exc)
        return {}


def _ensure_rates_loaded() -> None:
    global _RATE_FETCH_DONE
    if _RATE_FETCH_DONE:
        return
    _RATE_FETCH_DONE = True  # set first to avoid retry storms on failure
    rates = _fetch_inr_rate_history()
    if rates:
        _RATE_CACHE.update(rates)
        log.info("USD/INR rate cache loaded: %d daily points", len(rates))
    else:
        log.warning(
            "USD/INR rate cache empty — falling back to flat %.2f for all conversions",
            _FALLBACK_RATE,
        )


def get_usd_inr_rate(period_end: date | datetime | str) -> float:
    """Return the USD/INR rate at ``period_end``.

    Looks up the exact date in the cached daily-close series. If the
    date is a non-trading day (weekend / holiday) walks backward up
    to 14 days for the nearest prior trading day. If the cache is
    empty (offline / CI) returns :data:`_FALLBACK_RATE`.
    """
    _ensure_rates_loaded()

    if isinstance(period_end, str):
        try:
            d = datetime.strptime(period_end[:10], "%Y-%m-%d").date()
        except Exception:
            return _FALLBACK_RATE
    elif isinstance(period_end, datetime):
        d = period_end.date()
    elif isinstance(period_end, date):
        d = period_end
    else:
        return _FALLBACK_RATE

    if not _RATE_CACHE:
        return _FALLBACK_RATE

    for offset in range(0, 15):
        key = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
        if key in _RATE_CACHE:
            return _RATE_CACHE[key]
    # Future date or pre-history: return most recent cached point.
    try:
        latest_key = max(_RATE_CACHE.keys())
        return _RATE_CACHE[latest_key]
    except Exception:
        return _FALLBACK_RATE


def convert_usd_to_inr(
    amount_usd: float | int | None,
    period_end_date: date | datetime | str,
) -> float | None:
    """Convert a USD amount to INR using the rate at ``period_end_date``.

    Returns ``None`` if the input is ``None`` / non-numeric so callers
    that route raw yfinance values through here don't crash on NaN.
    """
    if amount_usd is None:
        return None
    try:
        amt = float(amount_usd)
    except (TypeError, ValueError):
        return None
    rate = get_usd_inr_rate(period_end_date)
    return amt * rate


# ── Statement-level conversion ──────────────────────────────────────
# Applied by the yfinance fetcher just before records are handed to
# the rest of the pipeline. Operates on the raw pandas frames in the
# dict returned by ``_fetch_once`` in ``data_pipeline/xbrl/yf_fetcher.py``.

# Frames that hold monetary values (every cell × rate). EPS / ratios
# are NOT in this list — they stay USD-denominated *per share* and are
# handled separately by the per-row extractor (EPS is in USD per share
# for USD reporters; we convert it the same way as a monetary field).
_MONETARY_FRAME_KEYS: tuple[str, ...] = (
    "annual_income",
    "quarterly_income",
    "annual_balance",
    "quarterly_balance",
    "annual_cashflow",
    "quarterly_cashflow",
)

# Income-statement rows that are PER-SHARE, not aggregate monetary.
# These get the same USD→INR rate (Basic EPS in USD × rate = EPS in INR)
# but exist as a separate concept so future ratio-only rows can be
# excluded easily.
_PER_SHARE_ROWS: frozenset[str] = frozenset({
    "Basic EPS",
    "Diluted EPS",
})


def convert_statement_frames(frames: dict, period_end_by_col: Iterable | None = None) -> dict:
    """Multiply every numeric cell in the monetary frames by the
    USD/INR rate at the cell's column-date.

    yfinance statement frames are indexed by line-item (rows) and dated
    by column (one column per period). The rate to apply is the spot
    rate at *that column's* period-end date, so we look up per-column
    and broadcast down the column.

    The function MUTATES ``frames`` in place and also returns it for
    convenience. Non-monetary keys (``_yf_ticker`` etc) are left alone.
    """
    try:
        import pandas as pd
    except Exception:
        return frames

    for key in _MONETARY_FRAME_KEYS:
        df = frames.get(key)
        if df is None or not hasattr(df, "columns") or df.empty:
            continue
        for col in df.columns:
            try:
                # Column label is a Timestamp/date; use it as period_end.
                rate = get_usd_inr_rate(col)
                if rate <= 0:
                    continue
                df[col] = df[col].apply(
                    lambda v: (float(v) * rate)
                    if (v is not None and not (isinstance(v, float) and pd.isna(v)))
                    else v
                )
            except Exception as exc:
                log.debug("convert col=%s key=%s failed: %s", col, key, exc)
                continue
    return frames


__all__ = [
    "USD_REPORTER_TICKERS",
    "is_usd_reporter",
    "get_usd_inr_rate",
    "convert_usd_to_inr",
    "convert_statement_frames",
]
