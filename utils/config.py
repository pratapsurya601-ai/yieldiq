# utils/config.py
# ─────────────────────────────────────────────────────────────
# Central configuration for the AI DCF Screener platform.
# All tunable parameters live here so you never need to hunt
# through the codebase to change a discount rate or growth cap.
# ─────────────────────────────────────────────────────────────

# ── Launch Region ──────────────────────────────────────────────
# Controls market availability throughout the app.
#   "US"     — US-only launch: hides India/Europe, locks tickers to usa_tickers.csv
#   "GLOBAL" — Full multi-market mode: India, Europe, and US all accessible
LAUNCH_REGION = "GLOBAL"

# ── DCF Engine Parameters ──────────────────────────────────────
DISCOUNT_RATE        = 0.10   # WACC / required rate of return (10%)
TERMINAL_GROWTH_RATE = 0.025  # Long-run perpetual growth (2.5%)
FORECAST_YEARS       = 10     # Number of years to project FCF

# ── Screening Signals ──────────────────────────────────────────
STRONG_BUY_THRESHOLD = 0.40   # MoS > 40% → STRONG BUY alert
BUY_THRESHOLD        = 0.30   # MoS > 30% → BUY
WATCH_THRESHOLD      = 0.10   # MoS > 10% → WATCH
HOLD_THRESHOLD       = 0.00   # MoS > 0%  → HOLD
# MoS ≤ 0%                    →            SELL

# ── Data Collection ────────────────────────────────────────────
YFINANCE_TIMEOUT     = 10     # seconds before giving up on a ticker
MAX_RETRIES          = 3      # retry attempts for failed downloads
FCF_HISTORY_YEARS    = 10     # years of history for charts + ML training

# ── File Paths ─────────────────────────────────────────────────
TICKER_LIST_PATH     = "data/usa_tickers.csv" if LAUNCH_REGION == "US" else "data/tickers.csv"
RESULTS_PATH         = "data/screener_results.csv"
MODEL_SAVE_PATH      = "models/fcf_model.pkl"


# ═══════════════════════════════════════════════════════════════
# LIVE RISK-FREE RATE  —  6-hour cached yfinance fetch
# ═══════════════════════════════════════════════════════════════
#
# Sources
#   US    : ^TNX  — CBOE 10-Year Treasury Note Yield Index
#   India : ^INBMK — India 10-Year Government Bond Yield
#
# WACC adjustment rules (applied on top of any sector/CAPM WACC):
#   yield > 5.0%  → +50 bps  (tighter financial conditions)
#   yield < 3.0%  → −25 bps  (loose / ZIRP conditions)
#   3.0–5.0%      →  0 bps   (neutral)
#
# Cache TTL : 6 hours (21 600 s) — module-level dict, thread-safe.
# ═══════════════════════════════════════════════════════════════

import threading
import time as _time_mod

# Fallback rates (used when live fetch fails)
RF_US_FALLBACK    = 0.043   # 4.3%  US 10-Year Treasury (2025-2026 level)
RF_INDIA_FALLBACK = 0.0680  # 6.80% India 10-Year G-Sec (Apr 2026, RBI repo 5.50%)

# WACC adjustment thresholds
_RF_HIGH_THRESHOLD  = 0.050   # > 5.0%  → +50 bps to WACC
_RF_LOW_THRESHOLD   = 0.030   # < 3.0%  → −25 bps to WACC
_RF_HIGH_ADJ        = +0.005  # +50 bps
_RF_LOW_ADJ         = -0.0025 # −25 bps

# Cache internals
_RF_TTL  = 6 * 3600           # 6 hours in seconds
_rf_lock = threading.Lock()
_rf_cache: dict[str, dict] = {}


def _wacc_adj_from_rate(rate: float) -> float:
    """Return WACC delta based on the current risk-free rate level."""
    if rate > _RF_HIGH_THRESHOLD:
        return _RF_HIGH_ADJ
    if rate < _RF_LOW_THRESHOLD:
        return _RF_LOW_ADJ
    return 0.0


def _rate_environment(rate: float) -> str:
    """Human-readable description of the current rate environment."""
    if rate > _RF_HIGH_THRESHOLD:
        return "Tight (>5%) — WACC +0.5%"
    if rate < _RF_LOW_THRESHOLD:
        return "Loose (<3%) — WACC −0.25%"
    return "Neutral (3–5%)"


def _try_fetch_yield(ticker_sym: str) -> float | None:
    """
    Attempt to fetch the latest yield (in percent) from yfinance.
    Returns the decimal rate (e.g. 0.043 for 4.3%) or None on failure.
    """
    try:
        import yfinance as yf
        import logging as _yf_log
        # Suppress yfinance errors for delisted tickers (^INBMK spam)
        _yf_log.getLogger("yfinance").setLevel(_yf_log.CRITICAL)

        t = yf.Ticker(ticker_sym)

        # Method 1 — fast_info (no network round-trip if already cached by yf)
        try:
            lp = t.fast_info.last_price
            if lp and 0.5 < float(lp) < 20.0:
                return float(lp) / 100.0
        except Exception:
            pass

        # Method 2 — recent close history (5 trading days)
        try:
            hist = t.history(period="5d", auto_adjust=True, progress=False)
            if not hist.empty:
                last = float(hist["Close"].dropna().iloc[-1])
                if 0.5 < last < 20.0:
                    return last / 100.0
        except Exception:
            pass

    except Exception:
        pass

    return None


def _try_fetch_india_10y() -> float | None:
    """
    Fetch India 10Y G-Sec yield from multiple sources.
    ^INBMK was delisted by Yahoo Finance in 2024-2025, so we try
    alternative tickers and finally fall back to the FRED API.
    """
    # Try Yahoo Finance alternatives in order of reliability
    # ^NSEI10Y doesn't exist; IN10YT=X is Reuters India 10Y; IRGB10Y is
    # another alias. None of these are super reliable, so we try them all.
    for ticker in ("IN10YT=X", "^INBMK", "INDIABOND10Y=RR"):
        rate = _try_fetch_yield(ticker)
        if rate is not None:
            return rate

    # Fallback: FRED API (free, reliable, no API key needed for this series)
    # Series: INDIRLTLT01STM — India Long-Term Government Bond Yield
    try:
        import urllib.request as _ur
        import json as _json
        url = "https://api.stlouisfed.org/fred/series/observations?series_id=INDIRLTLT01STM&sort_order=desc&limit=1&api_key=demo&file_type=json"
        with _ur.urlopen(url, timeout=5) as _r:
            data = _json.loads(_r.read())
            if data.get("observations"):
                val = data["observations"][0].get("value")
                if val and val != ".":
                    rate = float(val) / 100.0
                    if 0.04 < rate < 0.12:  # sanity check: 4%-12%
                        return rate
    except Exception:
        pass

    return None


def fetch_risk_free_rate(market: str = "us") -> dict:
    """
    Return the current 10-year risk-free rate for the requested market.

    Parameters
    ----------
    market : str
        "us"    → ^TNX  (US 10-Year Treasury)
        "india" → ^INBMK (India 10-Year G-Sec)

    Returns
    -------
    dict
        rate         float   Decimal rate (e.g. 0.0432 for 4.32%)
        rate_pct     float   Percent rate (e.g. 4.32)
        wacc_adj     float   WACC delta to apply:
                             +0.005 if rate > 5%
                             -0.0025 if rate < 3%
                             0.0 otherwise
        environment  str     Human-readable rate regime label
        source       str     "live" | "fallback"
        ticker       str     yfinance ticker used
        fetched_at   float   Unix timestamp of last successful fetch
        market       str     "us" | "india"

    Notes
    -----
    Results are cached for 6 hours in a module-level dict (thread-safe).
    Safe to call from non-Streamlit code (screener scripts, tests).
    """
    market = market.lower()
    if market not in ("us", "india"):
        market = "us"

    # ── Return from cache if still fresh ───────────────────────
    with _rf_lock:
        cached = _rf_cache.get(market)
        if cached and (_time_mod.time() - cached["fetched_at"]) < _RF_TTL:
            return dict(cached)   # defensive copy

    # ── Fetch live rate ─────────────────────────────────────────
    if market == "us":
        ticker  = "^TNX"
        default = RF_US_FALLBACK
        live_rate = _try_fetch_yield(ticker)
    else:
        # India: ^INBMK was delisted by Yahoo Finance. Use multi-source fetcher.
        ticker  = "IN10Y (multi-source)"
        default = RF_INDIA_FALLBACK
        live_rate = _try_fetch_india_10y()

    if live_rate is not None:
        rate   = live_rate
        source = "live"
    else:
        rate   = default
        source = "fallback"

    result = {
        "rate":        rate,
        "rate_pct":    round(rate * 100, 4),
        "wacc_adj":    _wacc_adj_from_rate(rate),
        "environment": _rate_environment(rate),
        "source":      source,
        "ticker":      ticker,
        "fetched_at":  _time_mod.time(),
        "market":      market,
    }

    with _rf_lock:
        _rf_cache[market] = result

    return dict(result)


def get_cached_rf(market: str = "us") -> dict | None:
    """
    Return the cached RF result without triggering a new fetch.
    Returns None if nothing has been cached yet.
    """
    with _rf_lock:
        return dict(_rf_cache[market]) if market in _rf_cache else None


def invalidate_rf_cache(market: str | None = None) -> None:
    """
    Force next call to fetch_risk_free_rate() to go to the network.
    Pass market=None to clear both caches.
    """
    with _rf_lock:
        if market is None:
            _rf_cache.clear()
        else:
            _rf_cache.pop(market, None)
