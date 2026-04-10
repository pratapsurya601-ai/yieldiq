# data/collector.py  v5
# ═══════════════════════════════════════════════════════════════
# YieldIQ Data Collector — Finnhub + yfinance Hybrid
# ═══════════════════════════════════════════════════════════════
#
# Architecture:
#   PRIMARY  — Finnhub API
#     • Real-time price (no 15-min delay)
#     • Analyst price targets (mean/high/low/count)
#     • Analyst recommendation trend (buy/hold/sell counts)
#     • Earnings surprises (last 8 quarters actual vs estimate)
#     • Next earnings date + EPS estimate
#     • Company profile (sector, market cap, name)
#     • Company news (last 10 headlines)
#
#   SECONDARY — yfinance (financial statements)
#     • Income statement (revenue, operating income, net income)
#     • Cash flow statement (OCF, capex, FCF)
#     • Balance sheet (debt, cash)
#     • Shares outstanding
#     • Dividend data
#     • EV / EBITDA
#
#   FALLBACK — yfinance price if Finnhub unavailable
#
# All output keys are IDENTICAL to v4 so nothing else needs to change.
# New keys added (additive only, never removing):
#   finnhub_price_target   — dict: mean/high/low/count
#   finnhub_rec_trend      — list of recommendation trend dicts
#   finnhub_earnings       — list of earnings surprise dicts
#   finnhub_next_earnings  — dict: date/eps_estimate
#   company_name           — str: short name
#   news                   — list of recent headline dicts
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import hashlib
import os
import pathlib
import threading
import time
import warnings
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

# ── curl_cffi — yfinance auto-detects it for Chrome impersonation on cloud ──
# When curl_cffi is installed, yfinance 0.2.54+ automatically uses it internally
# to bypass Yahoo Finance bot detection (401 Invalid Crumb / Too Many Requests).
# Do NOT pass session= manually — it overrides yfinance's own crumb refresh logic.
try:
    import curl_cffi as _curl_cffi  # noqa: F401  — just trigger auto-detection
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False


def _yf_ticker(symbol: str) -> "yf.Ticker":
    """Return a yf.Ticker; curl_cffi Chrome impersonation is handled by yfinance internally."""
    return yf.Ticker(symbol)

from utils.logger import get_logger
from utils.config import MAX_RETRIES, FCF_HISTORY_YEARS

log = get_logger(__name__)

# ════════════════════════════════════════════════════════════════
# DISK CACHE  — 15-min TTL for price data, 24-hr for financials
# ════════════════════════════════════════════════════════════════

TTL_PRICE      = 900    # 15 minutes
TTL_FINANCIALS = 86400  # 24 hours

_CACHE_DIR = pathlib.Path.home() / ".yieldiq_cache"

try:
    import diskcache as _dc
    _dc_store = _dc.Cache(str(_CACHE_DIR))
    _CACHE_BACKEND = "diskcache"
    log.debug("Cache backend: diskcache")
except ImportError:
    import shelve as _shelve_mod
    _CACHE_BACKEND = "shelve"
    _shelve_lock   = threading.Lock()
    log.debug("Cache backend: shelve (diskcache not installed)")


def cache_key(ticker: str, data_type: str, date: str = "") -> str:
    """Build a deterministic cache key from ticker + data_type + date."""
    date = date or datetime.utcnow().strftime("%Y-%m-%d")
    raw  = f"{ticker.upper()}:{data_type}:{date}"
    # Prefix with a short hash so callers can use the key directly as a dict key
    prefix = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{prefix}:{raw}"


class _DiskCache:
    """Thin read/write wrapper over diskcache (preferred) or shelve (fallback)."""

    def _clear_shelve(self) -> None:
        """Delete corrupted shelve files so they can be recreated cleanly."""
        import glob, dbm
        cache_path = str(_CACHE_DIR / "cache")
        for f in glob.glob(cache_path + ".*") + [cache_path]:
            try:
                import os as _os
                if _os.path.exists(f):
                    _os.remove(f)
            except Exception:
                pass

    def get(self, key: str):
        """Return cached value, or None if missing / expired."""
        if _CACHE_BACKEND == "diskcache":
            return _dc_store.get(key)
        # shelve: entry = (stored_ts, ttl, value)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with _shelve_lock:
                with _shelve_mod.open(str(_CACHE_DIR / "cache")) as db:
                    entry = db.get(key)
        except Exception:
            self._clear_shelve()
            return None
        if entry is None:
            return None
        stored_ts, ttl, value = entry
        if time.time() - stored_ts > ttl:
            return None
        return value

    def set(self, key: str, value, ttl: int) -> None:
        """Store value with a TTL (seconds)."""
        if _CACHE_BACKEND == "diskcache":
            _dc_store.set(key, value, expire=ttl)
        else:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                with _shelve_lock:
                    with _shelve_mod.open(str(_CACHE_DIR / "cache")) as db:
                        db[key] = (time.time(), ttl, value)
            except Exception:
                self._clear_shelve()

    def delete(self, key: str) -> None:
        """Evict a single key."""
        if _CACHE_BACKEND == "diskcache":
            _dc_store.delete(key, retry=True)
        else:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                with _shelve_lock:
                    with _shelve_mod.open(str(_CACHE_DIR / "cache")) as db:
                        if key in db:
                            del db[key]
            except Exception:
                self._clear_shelve()


_cache = _DiskCache()

# ── Load API key from environment (.env file or system env) ────
def _load_env():
    """Load .env file if present — works locally and on Streamlit Cloud."""
    try:
        import pathlib
        env_path = pathlib.Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k.strip(), v)
    except Exception:
        pass

_load_env()
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"
if FINNHUB_KEY:
    log.info(f"Finnhub API key loaded ({len(FINNHUB_KEY)} chars)")
else:
    log.warning("FINNHUB_API_KEY not set — Finnhub fallback disabled. Add it to Streamlit Secrets.")

# ── Batch mode flag ──────────────────────────────────────────────
# When YIELDIQ_BATCH_MODE=1 is set (by nightly_precompute.py),
# all Finnhub API calls are skipped to avoid rate-limit delays
# on large universes (18,000+ tickers).  Sentiment score will be
# 0/10 for non-curated stocks, which is acceptable in batch runs.
_BATCH_MODE: bool = os.environ.get("YIELDIQ_BATCH_MODE", "0") == "1"

# Approximate USD→INR rate fallback (used only when live FX fails)
# Must match _FX_FALLBACK["USD","INR"] in app.py
APPROX_USD_TO_INR = 83.5


# ════════════════════════════════════════════════════════════════
# FINNHUB CLIENT
# ════════════════════════════════════════════════════════════════

def _fh(endpoint: str, params: dict, timeout: int = 8) -> Optional[dict]:
    """
    Make a Finnhub API call. Returns parsed JSON or None on failure.
    Adds the API key automatically.
    """
    if not FINNHUB_KEY:
        return None
    try:
        params["token"] = FINNHUB_KEY
        r = requests.get(f"{FINNHUB_BASE}{endpoint}", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            log.warning("Finnhub rate limit hit — sleeping 2s")
            time.sleep(2)
            return None
        else:
            log.debug(f"Finnhub {endpoint} → HTTP {r.status_code}")
            return None
    except Exception as exc:
        log.debug(f"Finnhub {endpoint} error: {exc}")
        return None


def _fh_quote(ticker: str) -> dict:
    """
    Real-time quote from Finnhub.
    Returns: {price, prev_close, change, change_pct, high, low, open, volume}
    """
    data = _fh("/quote", {"symbol": ticker})
    if not data or not data.get("c"):
        return {}
    return {
        "price":       float(data.get("c", 0)),
        "prev_close":  float(data.get("pc", 0)),
        "change":      float(data.get("d", 0)),
        "change_pct":  float(data.get("dp", 0)),
        "day_high":    float(data.get("h", 0)),
        "day_low":     float(data.get("l", 0)),
        "day_open":    float(data.get("o", 0)),
        "volume":      float(data.get("t", 0)),  # timestamp, volume not in basic quote
    }


def _fh_profile(ticker: str) -> dict:
    """Company profile: name, sector, market cap, currency, country."""
    data = _fh("/stock/profile2", {"symbol": ticker})
    if not data:
        return {}
    return {
        "company_name":  data.get("name", ""),
        "sector_name":   data.get("finnhubIndustry", ""),
        "market_cap":    float(data.get("marketCapitalization", 0)) * 1e6,
        "currency":      data.get("currency", "USD"),
        "country":       data.get("country", "US"),
        "exchange":      data.get("exchange", ""),
        "logo":          data.get("logo", ""),
        "weburl":        data.get("weburl", ""),
    }


def _fh_price_target(ticker: str) -> dict:
    """
    Analyst price targets.
    Tries Finnhub first (paid), falls back to yfinance analyst_price_targets.
    Returns: {mean, high, low, median, count, source}
    """
    # Try Finnhub (paid endpoint — may return empty on free tier)
    data = _fh("/stock/price-target", {"symbol": ticker})
    if data and data.get("targetMean"):
        return {
            "mean":   float(data.get("targetMean",        0)),
            "high":   float(data.get("targetHigh",        0)),
            "low":    float(data.get("targetLow",         0)),
            "median": float(data.get("targetMedian",      0)),
            "count":  int(data.get("numberOfAnalysts",    0)),
            "source": "finnhub",
        }

    # Fallback: yfinance analyst_price_targets (free, less real-time)
    try:
        import yfinance as yf
        t   = _yf_ticker(ticker)
        apt = t.analyst_price_targets
        if apt and isinstance(apt, dict) and apt.get("mean"):
            return {
                "mean":   float(apt.get("mean",   0)),
                "high":   float(apt.get("high",   0)),
                "low":    float(apt.get("low",    0)),
                "median": float(apt.get("median", apt.get("mean", 0))),
                "count":  int(apt.get("numberOfAnalysts", 0)),
                "source": "yfinance",
            }
        # Also try info dict
        info = t.info
        mean = float(info.get("targetMeanPrice", 0))
        high = float(info.get("targetHighPrice", 0))
        low  = float(info.get("targetLowPrice",  0))
        med  = float(info.get("targetMedianPrice", mean))
        cnt  = int(info.get("numberOfAnalystOpinions", 0))
        if mean > 0:
            return {
                "mean": mean, "high": high, "low": low,
                "median": med, "count": cnt, "source": "yfinance",
            }
    except Exception as exc:
        log.debug(f"yfinance price target fallback failed: {exc}")
    return {}


def _fh_rec_trend(ticker: str) -> list:
    """
    Analyst recommendation trend — last 4 months.
    Finnhub primary (free), yfinance fallback.
    Returns list of {period, strongBuy, buy, hold, sell, strongSell}
    """
    # Finnhub (free tier)
    data = _fh("/stock/recommendation", {"symbol": ticker})
    if data and isinstance(data, list) and len(data) > 0:
        return data[:4]

    # yfinance fallback
    try:
        import yfinance as yf
        t  = _yf_ticker(ticker)
        rs = t.recommendations_summary
        if rs is not None and not rs.empty:
            return rs.head(4).to_dict("records")
    except Exception:
        pass
    return []


def _fh_earnings(ticker: str) -> list:
    """
    Historical EPS surprises — last 8 quarters.
    Returns list of {period, actual, estimate, surprise, surprisePercent}
    """
    data = _fh("/stock/earnings", {"symbol": ticker, "limit": 8})
    if not data or not isinstance(data, list):
        return []
    result = []
    for q in data:
        result.append({
            "period":          q.get("period", ""),
            "actual":          float(q.get("actual",          0) or 0),
            "estimate":        float(q.get("estimate",        0) or 0),
            "surprise":        float(q.get("surprise",        0) or 0),
            "surprise_pct":    float(q.get("surprisePercent", 0) or 0),
        })
    return result


def _fh_next_earnings(ticker: str) -> dict:
    """
    Next earnings date and EPS estimate from Finnhub calendar.
    Returns {date, eps_estimate, revenue_estimate}
    """
    today     = datetime.today().strftime("%Y-%m-%d")
    in_90days = (datetime.today() + timedelta(days=90)).strftime("%Y-%m-%d")
    data = _fh("/calendar/earnings", {
        "from":   today,
        "to":     in_90days,
        "symbol": ticker,
    })
    if not data or not data.get("earningsCalendar"):
        return {}
    cal = data["earningsCalendar"]
    if not cal:
        return {}
    next_ev = cal[0]
    return {
        "date":             next_ev.get("date", ""),
        "eps_estimate":     float(next_ev.get("epsEstimate",     0) or 0),
        "revenue_estimate": float(next_ev.get("revenueEstimate", 0) or 0),
        "hour":             next_ev.get("hour", ""),
    }


def _fh_news(ticker: str, days: int = 7) -> list:
    """
    Recent company news headlines — last N days.
    Returns list of {datetime, headline, source, url, summary}
    """
    today    = datetime.today().strftime("%Y-%m-%d")
    from_dt  = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _fh("/company-news", {"symbol": ticker, "from": from_dt, "to": today})
    if not data or not isinstance(data, list):
        return []
    result = []
    for item in data[:10]:
        result.append({
            "datetime": item.get("datetime", 0),
            "headline": item.get("headline", ""),
            "source":   item.get("source", ""),
            "url":      item.get("url", ""),
            "summary":  item.get("summary", "")[:200],
        })
    return result


def compute_insider_sentiment(net_shares: float) -> str:
    """Map net share change (90-day) to a sentiment label."""
    if net_shares > 100_000:
        return "STRONG BUY"
    elif net_shares > 10_000:
        return "BUY"
    elif net_shares >= -10_000:
        return "NEUTRAL"
    elif net_shares >= -100_000:
        return "SELL"
    else:
        return "STRONG SELL"


def _fh_insider_transactions(ticker: str, days: int = 365) -> dict:
    """
    Fetch insider transactions from Finnhub /stock/insider-transactions.

    Returns
    -------
    dict
        transactions   list  All P/S transactions sorted by date desc (last 12 months)
        net_shares_90d int   Net shares bought minus sold over last 90 days
        sentiment      str   'STRONG BUY' | 'BUY' | 'NEUTRAL' | 'SELL' | 'STRONG SELL'
        monthly_net    dict  {YYYY-MM: net_shares} for bar chart
    """
    from_dt = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    to_dt   = datetime.today().strftime("%Y-%m-%d")

    data = _fh("/stock/insider-transactions", {
        "symbol": ticker,
        "from":   from_dt,
        "to":     to_dt,
    })

    if not data or not isinstance(data.get("data"), list):
        return {}

    cutoff_90d   = datetime.today() - timedelta(days=90)
    net_90d      = 0
    monthly_net  = {}
    transactions = []

    for txn in data["data"]:
        code = (txn.get("transactionCode") or "").strip()
        if code not in ("P", "S"):          # Purchase / Sale only
            continue

        date_str = txn.get("transactionDate", "")
        try:
            txn_date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue

        shares = abs(float(txn.get("share", 0) or 0))
        if shares == 0:
            continue

        is_buy     = code == "P"
        net_change = shares if is_buy else -shares

        # 90-day net
        if txn_date >= cutoff_90d:
            net_90d += net_change

        # Monthly net for chart
        month_key = txn_date.strftime("%Y-%m")
        monthly_net[month_key] = monthly_net.get(month_key, 0) + net_change

        # Role hint: Finnhub often puts it in "name" field as "LastName, Role"
        name = txn.get("name", "") or ""

        transactions.append({
            "name":   name,
            "date":   date_str,
            "type":   "Buy" if is_buy else "Sell",
            "code":   code,
            "shares": int(shares),
            "price":  float(txn.get("transactionPrice", 0) or 0),
            "value":  shares * float(txn.get("transactionPrice", 0) or 0),
        })

    transactions.sort(key=lambda x: x["date"], reverse=True)

    return {
        "transactions":   transactions,
        "net_shares_90d": int(net_90d),
        "sentiment":      compute_insider_sentiment(net_90d),
        "monthly_net":    monthly_net,
    }


def compute_earnings_track_record(earnings: list) -> dict:
    """
    Compute beat-rate statistics from Finnhub earnings surprise history.

    Parameters
    ----------
    earnings : list
        As returned by _fh_earnings() — newest-first list of dicts with keys:
        period, actual, estimate, surprise, surprise_pct

    Returns
    -------
    dict
        beat_rate         float  Fraction of quarters where actual > estimate (0–1)
        avg_surprise_pct  float  Mean signed surprise % (positive = beat)
        trend             str    'Accelerating Beats' | 'Decelerating' |
                                 'Consistent Misses' | 'Mixed'
        num_quarters      int    Number of quarters analysed
        periods           list   Quarter labels, oldest-first (for chart x-axis)
        actuals           list   Actual EPS values, oldest-first
        estimates         list   Estimate EPS values, oldest-first
        surprises_pct     list   Signed surprise %, oldest-first
        beats             list   bool per quarter, oldest-first
    """
    if not earnings:
        return {}

    # Work oldest-first for trend analysis
    chron = list(reversed(earnings))

    periods       = [e.get("period", "")        for e in chron]
    actuals       = [float(e.get("actual",   0) or 0) for e in chron]
    estimates     = [float(e.get("estimate", 0) or 0) for e in chron]
    surprises_pct = [float(e.get("surprise_pct", 0) or 0) for e in chron]
    beats         = [a > est for a, est in zip(actuals, estimates)]

    n           = len(beats)
    beat_rate   = sum(beats) / n if n > 0 else 0.0
    avg_surp    = float(np.mean(surprises_pct)) if surprises_pct else 0.0

    # Trend: compare first-half vs second-half beat rates
    half        = max(n // 2, 1)
    first_half  = beats[:half]
    second_half = beats[half:]
    first_rate  = sum(first_half) / len(first_half) if first_half else 0.5
    second_rate = sum(second_half) / len(second_half) if second_half else 0.5
    delta       = second_rate - first_rate

    if beat_rate < 0.375:
        trend = "Consistent Misses"
    elif delta >= 0.25:
        trend = "Accelerating Beats"
    elif delta <= -0.25:
        trend = "Decelerating"
    else:
        trend = "Mixed"

    return {
        "beat_rate":        round(beat_rate, 4),
        "avg_surprise_pct": round(avg_surp, 2),
        "trend":            trend,
        "num_quarters":     n,
        "periods":          periods,
        "actuals":          actuals,
        "estimates":        estimates,
        "surprises_pct":    surprises_pct,
        "beats":            beats,
    }


def _fh_institutional_ownership(ticker: str) -> dict:
    """
    Institutional ownership from Finnhub /stock/institutional-ownership.

    Returns
    -------
    dict
        holders         list  Top-5 holders: name, shares, share_pct, change_shares, change_pct, filing_date
        total_pct       float Total institutional ownership % (sum of sharePercent × 100)
        qoq_change_pct  float QoQ change in total held shares expressed as %
        trend           str   'ACCUMULATING' | 'DISTRIBUTING' | 'STABLE'
        accumulation    bool  True if top-5 avg position change > +5%
        avg_top5_chg    float Average QoQ % change across top-5 holders
        quarter         str   Most-recent filing quarter, e.g. '2024-Q1'
        num_holders     int   Total number of reporting institutions
    """
    data = _fh("/stock/institutional-ownership", {
        "symbol":      ticker,
        "limitedInfo": "false",
    })
    if not data or not isinstance(data.get("ownership"), list):
        return {}
    owners = data["ownership"]
    if not owners:
        return {}

    # Sort by shares held desc so top-5 is straightforward
    owners_sorted = sorted(
        owners,
        key=lambda x: float(x.get("share", 0) or 0),
        reverse=True,
    )

    # ── Aggregate totals ─────────────────────────────────────────
    # Finnhub's sharePercent is a decimal fraction (0.065 = 6.5% of float)
    total_share_pct = sum(float(o.get("sharePercent", 0) or 0) for o in owners)
    total_shares    = sum(float(o.get("share",        0) or 0) for o in owners)
    total_change    = sum(float(o.get("change",       0) or 0) for o in owners)

    # QoQ change in aggregate shares as % of prior-quarter total
    prior_total  = total_shares - total_change
    qoq_chg_pct = (total_change / prior_total * 100) if prior_total > 0 else 0.0

    trend = ("ACCUMULATING" if qoq_chg_pct >  1.0 else
             "DISTRIBUTING" if qoq_chg_pct < -1.0 else
             "STABLE")

    # ── Top-5 holders ─────────────────────────────────────────────
    top5 = []
    for o in owners_sorted[:5]:
        sp     = float(o.get("sharePercent",  0) or 0)   # decimal fraction
        cp     = float(o.get("changePercent", 0) or 0)   # decimal fraction QoQ change
        ch_sh  = int(float(o.get("change",    0) or 0))

        top5.append({
            "name":          (o.get("name", "") or "").title(),
            "shares":        int(float(o.get("share", 0) or 0)),
            "share_pct":     round(sp * 100, 3),    # % of shares outstanding
            "change_shares": ch_sh,
            "change_pct":    round(cp * 100, 3),    # % change in their position QoQ
            "filing_date":   o.get("filingDate", ""),
        })

    # Institutional Accumulation signal:
    # top-5 averaged a >+5% increase in their position last quarter
    top5_chg = [h["change_pct"] for h in top5 if h["change_pct"] != 0]
    avg_top5 = (sum(top5_chg) / len(top5_chg)) if top5_chg else 0.0
    accumulation = avg_top5 > 5.0   # >5% average QoQ position increase

    # ── Filing quarter ─────────────────────────────────────────────
    latest_date = owners_sorted[0].get("filingDate", "") if owners_sorted else ""
    quarter = ""
    if latest_date:
        try:
            _dt = datetime.strptime(latest_date[:10], "%Y-%m-%d")
            quarter = f"{_dt.year}-Q{(_dt.month - 1) // 3 + 1}"
        except Exception:
            quarter = latest_date[:7]

    return {
        "holders":        top5,
        "total_pct":      round(total_share_pct * 100, 2),
        "qoq_change_pct": round(qoq_chg_pct, 3),
        "trend":          trend,
        "accumulation":   accumulation,
        "avg_top5_chg":   round(avg_top5, 2),
        "quarter":        quarter,
        "num_holders":    len(owners),
    }


def _fh_basic_financials(ticker: str) -> dict:
    """
    Finnhub basic financials — key ratios and TTM metrics.
    Used to supplement yfinance data.
    """
    data = _fh("/stock/metric", {"symbol": ticker, "metric": "all"})
    if not data or not data.get("metric"):
        return {}
    m = data["metric"]
    return {
        "pe_ttm":          float(m.get("peTTM",          0) or 0),
        "pb":              float(m.get("pbAnnual",        0) or 0),
        "ps_ttm":          float(m.get("psTTM",          0) or 0),
        "ev_ebitda_ttm":   float(m.get("evEbitdaTTM",   0) or 0),
        "roe_ttm":         float(m.get("roeTTM",         0) or 0),
        "roic_ttm":        float(m.get("roicTTM",        0) or 0),
        "gross_margin_ttm":float(m.get("grossMarginTTM", 0) or 0),
        "net_margin_ttm":  float(m.get("netProfitMarginTTM", 0) or 0),
        "debt_to_equity":  float(m.get("totalDebt/totalEquityAnnual", 0) or 0),
        "current_ratio":   float(m.get("currentRatioAnnual", 0) or 0),
        "beta":            float(m.get("beta",           0) or 0),
        "52w_high":        float(m.get("52WeekHigh",     0) or 0),
        "52w_low":         float(m.get("52WeekLow",      0) or 0),
        "div_yield_ttm":   float(m.get("dividendYieldIndicatedAnnual", 0) or 0),
        "eps_ttm":         float(m.get("epsTTM",         0) or 0),
        "rev_per_share":   float(m.get("revenuePerShareTTM", 0) or 0),
        "fcf_per_share":   float(m.get("freeCashFlowPerShareTTM", 0) or 0),
        "rev_growth_3y":   float(m.get("revenueGrowth3Y", 0) or 0),
        "eps_growth_3y":   float(m.get("epsGrowth3Y",   0) or 0),
    }


# ════════════════════════════════════════════════════════════════
# YFINANCE HELPERS (unchanged from v4)
# ════════════════════════════════════════════════════════════════

def _safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _ttm_or_annual(series: pd.Series) -> float:
    clean = series.dropna()
    return _safe_float(clean.iloc[-1]) if len(clean) > 0 else 0.0


def _detect_financial_currency(info: dict, is_indian: bool) -> float:
    """Detect USD-reporting Indian stocks and return multiplier."""
    if not is_indian:
        return 1.0
    USD_REPORTERS = [
        "infy", "wipro", "hcltech", "techm", "mphasis",
        "hexaware", "ltim", "ltimindtr", "persistent",
        "coforge", "kpittech", "tataelxsi", "cyient",
        "zensar", "mastek", "niit", "ofss",
    ]
    try:
        ticker_name = info.get("symbol", "").lower()
        if not any(kw in ticker_name for kw in USD_REPORTERS):
            return 1.0
        price  = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        shares = _safe_float(info.get("sharesOutstanding"))
        revenue= _safe_float(info.get("totalRevenue", 0))
        mktcap = _safe_float(info.get("marketCap", 0))
        if price <= 0 or shares <= 0 or revenue <= 0:
            return 1.0
        if mktcap < 5000e7:
            return 1.0
        rev_to_price = (revenue / shares) / price
        if rev_to_price < 0.02:
            return APPROX_USD_TO_INR
        return 1.0
    except Exception:
        return 1.0


# ════════════════════════════════════════════════════════════════
# MAIN COLLECTOR CLASS
# ════════════════════════════════════════════════════════════════

class StockDataCollector:
    """
    Hybrid Finnhub + yfinance data collector.

    Finnhub provides real-time price and market intelligence.
    yfinance provides financial statement history (income, CF, BS).
    All output keys are backward-compatible with v4.
    """

    def __init__(self, ticker: str):
        self.ticker          = ticker.upper().strip()
        self._ticker_obj: Optional[yf.Ticker] = None
        self._fin_multiplier: float = 1.0
        self._yf_info: dict  = {}
        self._fh_available   = bool(FINNHUB_KEY)

        if self._fh_available:
            log.debug(f"[{self.ticker}] Finnhub mode active")
        else:
            log.warning(
                f"[{self.ticker}] FINNHUB_API_KEY not set — "
                "falling back to yfinance for price data"
            )

    # ── yfinance load ─────────────────────────────────────────
    def _load_yf(self) -> bool:
        # Aggressive backoff: 0s, 10s, 30s, 60s, 90s — survives even heavy rate limits
        _backoff = [0, 10, 30, 60, 90]
        for attempt in range(1, len(_backoff) + 1):
            try:
                self._ticker_obj = _yf_ticker(self.ticker)
                self._yf_info    = self._ticker_obj.info or {}
                if attempt > 1:
                    log.info(f"[{self.ticker}] yfinance succeeded on attempt {attempt}")
                return True
            except Exception as exc:
                _wait = _backoff[attempt - 1]
                _is_rate_limit = "429" in str(exc) or "rate" in str(exc).lower() or "Too Many" in str(exc)
                if _is_rate_limit:
                    log.warning(f"[{self.ticker}] yfinance rate-limited (attempt {attempt}/{len(_backoff)}), waiting {_wait}s...")
                else:
                    log.warning(f"[{self.ticker}] yfinance attempt {attempt}: {exc}")
                if attempt < len(_backoff):
                    time.sleep(_wait)
        return False

    # ── Price resolution ──────────────────────────────────────
    def get_price(self, force_refresh: bool = False) -> float:
        """
        Price resolution order:
        1. Finnhub real-time quote (if key available)
        2. yfinance currentPrice / regularMarketPrice

        Results are cached for TTL_PRICE (15 minutes).
        Pass force_refresh=True to bypass the cache.
        """
        ck = cache_key(self.ticker, "price")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                log.debug(f"[{self.ticker}] Price from cache: {cached}")
                return cached

        if self._fh_available:
            fh_q = _fh_quote(self.ticker)
            if fh_q.get("price", 0) > 0:
                log.debug(f"[{self.ticker}] Price from Finnhub: {fh_q['price']}")
                _cache.set(ck, fh_q["price"], TTL_PRICE)
                return fh_q["price"]

        # yfinance fallback
        info  = self._yf_info or {}
        price = _safe_float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or 0
        )
        log.debug(f"[{self.ticker}] Price from yfinance: {price}")
        if price > 0:
            _cache.set(ck, price, TTL_PRICE)
        return price

    # ── Financial statements (yfinance) ───────────────────────
    def get_shares_outstanding(self, force_refresh: bool = False) -> float:
        """Returns shares outstanding. Cached for TTL_FINANCIALS (24 hours)."""
        ck = cache_key(self.ticker, "shares_outstanding")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                return cached
        try:
            result = _safe_float(
                self._yf_info.get("sharesOutstanding")
                or self._yf_info.get("impliedSharesOutstanding")
                or 0
            )
        except Exception:
            result = 0.0
        _cache.set(ck, result, TTL_FINANCIALS)
        return result

    def get_balance_sheet_snapshot(self, force_refresh: bool = False) -> dict:
        """Returns balance sheet snapshot dict. Cached for TTL_FINANCIALS (24 hours)."""
        ck = cache_key(self.ticker, "balance_sheet")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                return cached
        result = {
            "total_debt": 0.0, "total_cash": 0.0,
            "total_assets": 0.0, "total_assets_prev": 0.0,
            "current_assets": 0.0, "current_liabilities": 0.0,
            "current_ratio": 0.0, "current_ratio_prev": 0.0,
            "lt_debt": 0.0, "lt_debt_prev": 0.0,
            "shares_prev_year": 0.0,
        }
        try:
            bs = self._ticker_obj.balance_sheet
            if bs is None or bs.empty:
                return result
            m = self._fin_multiplier
            cols = list(bs.columns)  # newest first

            def _bs(label_list, col_idx=0):
                for label in label_list:
                    if label in bs.index and col_idx < len(cols):
                        return _safe_float(bs.loc[label, cols[col_idx]]) * m
                return 0.0

            # Total debt (current year and prior year)
            for label in ["Total Debt", "Long Term Debt"]:
                if label in bs.index:
                    result["total_debt"]   = _safe_float(bs.loc[label, cols[0]]) * m
                    result["lt_debt"]      = result["total_debt"]
                    if len(cols) > 1:
                        result["lt_debt_prev"] = _safe_float(bs.loc[label, cols[1]]) * m
                    break

            # Cash
            for label in ["Cash And Cash Equivalents", "Cash",
                           "Cash And Short Term Investments"]:
                if label in bs.index:
                    result["total_cash"] = _safe_float(bs.loc[label, cols[0]]) * m
                    break

            # Total assets (current + prior year for F9 asset turnover)
            for label in ["Total Assets"]:
                if label in bs.index:
                    result["total_assets"] = _safe_float(bs.loc[label, cols[0]]) * m
                    if len(cols) > 1:
                        result["total_assets_prev"] = _safe_float(bs.loc[label, cols[1]]) * m
                    break

            # Current ratio components (for F6 liquidity improving)
            for label in ["Current Assets", "Total Current Assets"]:
                if label in bs.index:
                    result["current_assets"] = _safe_float(bs.loc[label, cols[0]]) * m
                    break
            for label in ["Current Liabilities", "Total Current Liabilities"]:
                if label in bs.index:
                    result["current_liabilities"] = _safe_float(bs.loc[label, cols[0]]) * m
                    break

            if result["current_liabilities"] > 0:
                result["current_ratio"] = result["current_assets"] / result["current_liabilities"]
            if len(cols) > 1:
                ca_prev = _bs(["Current Assets","Total Current Assets"], 1)
                cl_prev = _bs(["Current Liabilities","Total Current Liabilities"], 1)
                if cl_prev > 0:
                    result["current_ratio_prev"] = ca_prev / cl_prev

        except Exception as exc:
            log.debug(f"[{self.ticker}] Balance sheet: {exc}")

        # Prior-year shares outstanding — from balance sheet or quarterly shares
        try:
            cf = self._ticker_obj.cashflow
            if cf is not None and not cf.empty:
                cf_cols = list(cf.columns)
                if len(cf_cols) > 1:
                    # Shares from prior year cashflow period (if available)
                    pass
            # Primary: read from income statement shares column
            inc = self._ticker_obj.financials
            if inc is not None and not inc.empty:
                inc_cols = list(inc.columns)
                for label in ["Diluted Average Shares", "Basic Average Shares",
                               "Diluted EPS", "Weighted Average Diluted Shares"]:
                    if label in inc.index and len(inc_cols) > 1:
                        result["shares_prev_year"] = _safe_float(
                            inc.loc[label, inc_cols[1]]
                        )
                        break
            # Fallback: use shares_history from quarterly data
            if result["shares_prev_year"] == 0:
                try:
                    q_inc = self._ticker_obj.quarterly_financials
                    if q_inc is not None and not q_inc.empty:
                        q_cols = list(q_inc.columns)
                        # Go back ~4 quarters for prior year
                        if len(q_cols) >= 4:
                            for label in ["Diluted Average Shares", "Basic Average Shares"]:
                                if label in q_inc.index:
                                    result["shares_prev_year"] = _safe_float(
                                        q_inc.loc[label, q_cols[3]]
                                    )
                                    break
                except Exception:
                    pass
        except Exception as exc:
            log.debug(f"[{self.ticker}] shares_prev_year fetch: {exc}")

        _cache.set(ck, result, TTL_FINANCIALS)
        return result

    def get_income_history(self, force_refresh: bool = False) -> pd.DataFrame:
        """Returns income history DataFrame. Cached for TTL_FINANCIALS (24 hours)."""
        ck = cache_key(self.ticker, "income_history")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                return cached
        try:
            inc = self._ticker_obj.financials
            if inc is None or inc.empty:
                return pd.DataFrame()
            rows = []
            for col in inc.columns:
                year     = col.year if hasattr(col, "year") else int(str(col)[:4])
                revenue  = op_income = net_income = 0.0
                for label in ["Total Revenue", "Revenue"]:
                    if label in inc.index:
                        revenue = _safe_float(inc.loc[label, col]) * self._fin_multiplier
                        break
                for label in ["Operating Income", "Ebit"]:
                    if label in inc.index:
                        op_income = _safe_float(inc.loc[label, col]) * self._fin_multiplier
                        break
                for label in ["Net Income", "Net Income Common Stockholders"]:
                    if label in inc.index:
                        net_income = _safe_float(inc.loc[label, col]) * self._fin_multiplier
                        break
                gross_profit = 0.0
                for label in ["Gross Profit"]:
                    if label in inc.index:
                        gross_profit = _safe_float(inc.loc[label, col]) * self._fin_multiplier
                        break
                rows.append({
                    "year": year, "revenue": revenue,
                    "operating_income": op_income, "net_income": net_income,
                    "gross_profit": gross_profit,
                })
            df = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
            result = df.tail(FCF_HISTORY_YEARS).copy()
            # Compute margin columns for the financial statements table
            rev = result["revenue"].replace(0, float("nan"))
            result["op_margin"]    = result["operating_income"] / rev
            result["net_margin"]   = result["net_income"]       / rev
            result["gross_margin"] = result["gross_profit"]     / rev
            _cache.set(ck, result, TTL_FINANCIALS)
            return result
        except Exception as exc:
            log.debug(f"[{self.ticker}] Income history: {exc}")
            return pd.DataFrame()

    def get_cashflow_history(self, force_refresh: bool = False) -> pd.DataFrame:
        """Returns cashflow history DataFrame. Cached for TTL_FINANCIALS (24 hours)."""
        ck = cache_key(self.ticker, "cashflow_history")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                return cached
        try:
            cf = self._ticker_obj.cashflow
            if cf is None or cf.empty:
                return pd.DataFrame()
            rows = []
            for col in cf.columns:
                year = col.year if hasattr(col, "year") else int(str(col)[:4])
                ocf  = capex = 0.0
                for label in ["Operating Cash Flow",
                               "Total Cash From Operating Activities"]:
                    if label in cf.index:
                        ocf = _safe_float(cf.loc[label, col]) * self._fin_multiplier
                        break
                for label in ["Capital Expenditure", "Capital Expenditures"]:
                    if label in cf.index:
                        capex = abs(_safe_float(cf.loc[label, col])) * self._fin_multiplier
                        break
                rows.append({
                    "year": year, "ocf": ocf,
                    "capex": capex, "fcf": ocf - capex,
                })
            df = pd.DataFrame(rows).sort_values("year").reset_index(drop=True)
            result = df.tail(FCF_HISTORY_YEARS).copy()
            # cfo alias: financial table config expects "cfo" column
            result["cfo"] = result["ocf"]
            # fcf_growth: YoY % change in FCF for each year row
            result["fcf_growth"] = result["fcf"].pct_change()
            _cache.set(ck, result, TTL_FINANCIALS)
            return result
        except Exception as exc:
            log.debug(f"[{self.ticker}] Cashflow history: {exc}")
            return pd.DataFrame()

    def get_price_history(self, period: str = "1y", force_refresh: bool = False) -> pd.DataFrame:
        """Returns OHLCV price history DataFrame. Cached for TTL_PRICE (15 minutes)."""
        ck = cache_key(self.ticker, f"price_history:{period}")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                return cached
        try:
            hist = self._ticker_obj.history(period=period)
            if hist is None or hist.empty:
                return pd.DataFrame()
            hist   = hist.reset_index()
            result = hist[["Date", "Open", "High", "Low", "Close", "Volume"]]
            _cache.set(ck, result, TTL_PRICE)
            return result
        except Exception as exc:
            log.debug(f"[{self.ticker}] Price history: {exc}")
            return pd.DataFrame()

    # ── Main entry point ──────────────────────────────────────
    def get_all(self, force_refresh: bool = False) -> Optional[dict]:
        """
        Fetch all data. Returns complete dict or None on failure.

        Results are cached for TTL_PRICE (15 minutes) since they include
        live price data.  Pass force_refresh=True to bypass the cache.

        Data flow:
          1. Load yfinance (needed for financial statements)
          2. Detect currency mismatch for Indian stocks
          3. Get real-time price (Finnhub preferred, yfinance fallback)
          4. Fetch Finnhub market intelligence (non-blocking if unavailable)
          5. Build output dict — all v4 keys preserved + new Finnhub keys
        """
        ck = cache_key(self.ticker, "all")
        if not force_refresh:
            cached = _cache.get(ck)
            if cached is not None:
                log.info(f"[{self.ticker}] get_all() served from cache")
                return cached

        # ── Step 1: Load yfinance ──────────────────────────────
        _yf_ok = self._load_yf()
        if not _yf_ok:
            log.warning(f"[{self.ticker}] yfinance load failed — trying Finnhub-only mode")

        info       = self._yf_info if _yf_ok else {}
        is_indian  = self.ticker.endswith(".NS") or self.ticker.endswith(".BO")
        if _yf_ok:
            self._fin_multiplier = _detect_financial_currency(info, is_indian)
        else:
            self._fin_multiplier = 1.0

        if self._fin_multiplier != 1.0:
            log.info(f"[{self.ticker}] USD→INR multiplier ×{self._fin_multiplier:.0f}")

        # ── Step 2: Get real-time price ────────────────────────
        price = self.get_price(force_refresh=force_refresh)
        if price <= 0:
            log.warning(f"[{self.ticker}] Invalid price: {price}")
            return None

        # ── Step 3: Financial statements (yfinance) ────────────
        if _yf_ok:
            income_df = self.get_income_history(force_refresh=force_refresh)
            cf_df     = self.get_cashflow_history(force_refresh=force_refresh)
            bs        = self.get_balance_sheet_snapshot(force_refresh=force_refresh)
            shares    = self.get_shares_outstanding(force_refresh=force_refresh)
        else:
            income_df = pd.DataFrame()
            cf_df     = pd.DataFrame()
            bs        = {"total_debt": 0, "total_cash": 0, "shares_prev_year": 0,
                         "total_assets": 0, "current_ratio": 0, "current_ratio_prev": 0,
                         "lt_debt": 0, "lt_debt_prev": 0, "total_assets_prev": 0}
            # Estimate shares from Finnhub market cap / price
            shares    = 0
            log.info(f"[{self.ticker}] Finnhub-only mode — financial statements unavailable")
        # Use shares from info; prior-year from BS extraction
        shares_prev = bs.get("shares_prev_year", 0)
        total_assets    = bs.get("total_assets", 0)
        current_ratio   = bs.get("current_ratio", 0)
        current_ratio_prev = bs.get("current_ratio_prev", 0)
        lt_debt         = bs.get("lt_debt", 0)
        lt_debt_prev    = bs.get("lt_debt_prev", 0)
        total_assets_prev = bs.get("total_assets_prev", 0)

        # ── Step 4: Finnhub market intelligence ───────────────
        fh_profile     = {}
        fh_price_target= {}
        fh_rec_trend   = []
        fh_earnings    = []
        fh_next_earn   = {}
        fh_news        = []
        fh_financials  = {}
        fh_quote_data  = {}
        fh_insider     = {}
        fh_inst        = {}

        if self._fh_available and not _BATCH_MODE:
            log.debug(f"[{self.ticker}] Fetching Finnhub data...")
            fh_profile      = _fh_profile(self.ticker)
            fh_price_target = _fh_price_target(self.ticker)
            fh_rec_trend    = _fh_rec_trend(self.ticker)
            fh_earnings     = _fh_earnings(self.ticker)
            fh_next_earn    = _fh_next_earnings(self.ticker)
            fh_news         = _fh_news(self.ticker)
            fh_financials   = _fh_basic_financials(self.ticker)
            fh_quote_data   = _fh_quote(self.ticker)
            fh_insider      = _fh_insider_transactions(self.ticker)
            fh_inst         = _fh_institutional_ownership(self.ticker)
        elif _BATCH_MODE:
            log.debug(f"[{self.ticker}] BATCH_MODE — skipping all Finnhub calls")

        # ── Step 5: yfinance supplementary fields ─────────────
        m = self._fin_multiplier
        forward_eps   = _safe_float(info.get("forwardEps",   0))
        trailing_eps  = _safe_float(info.get("trailingEps",  0))
        forward_pe    = _safe_float(info.get("forwardPE",    0))
        peg_ratio     = _safe_float(info.get("pegRatio",     0))
        roe           = _safe_float(info.get("returnOnEquity", 0))
        roce_proxy    = _safe_float(info.get("returnOnAssets", 0))
        de_ratio      = _safe_float(info.get("debtToEquity",  0)) / 100 \
                        if info.get("debtToEquity") else 0
        interest_cov  = _safe_float(info.get("interestCoverage", 0))
        gross_margin  = _safe_float(info.get("grossMargins",   0))
        sector_name   = (fh_profile.get("sector_name") or
                         info.get("sector", ""))
        company_name  = (fh_profile.get("company_name") or
                         info.get("shortName", self.ticker))
        dividend_yield   = _safe_float(
            info.get("dividendYield") or
            info.get("trailingAnnualDividendYield") or 0
        )
        dividend_rate    = _safe_float(
            info.get("dividendRate") or
            info.get("trailingAnnualDividendRate") or 0
        )
        payout_ratio     = _safe_float(info.get("payoutRatio",          0))
        five_yr_avg_div  = _safe_float(info.get("fiveYearAvgDividendYield", 0))
        ebitda           = _safe_float(info.get("ebitda",              0)) * m
        enterprise_value = _safe_float(info.get("enterpriseValue",     0))
        ev_to_ebitda     = _safe_float(info.get("enterpriseToEbitda",  0))
        ev_to_revenue    = _safe_float(info.get("enterpriseToRevenue", 0))
        yahoo_fcf_ttm    = _safe_float(info.get("freeCashflow",        0)) * m
        native_ccy       = "INR" if is_indian else "USD"

        # Price change % — use Finnhub if available, else compute from yfinance
        if fh_quote_data.get("change_pct"):
            price_change_pct = fh_quote_data["change_pct"]
        else:
            prev_close = _safe_float(info.get("regularMarketPreviousClose") or
                                     info.get("previousClose") or 0)
            price_change_pct = ((price - prev_close) / prev_close * 100) \
                               if prev_close > 0 else 0.0

        # Capex normalisation (unchanged from v4)
        norm_capex_pct = None
        if not cf_df.empty and "capex" in cf_df.columns:
            try:
                capex_vals = cf_df["capex"].abs().dropna()
                if len(capex_vals) >= 2:
                    sorted_capex   = capex_vals.sort_values()
                    normal_capex   = float(sorted_capex.iloc[:max(1, int(len(sorted_capex)*0.75))].mean())
                    latest_capex   = float(capex_vals.iloc[-1])
                    if latest_capex > normal_capex * 2.5 and normal_capex > 0:
                        if not income_df.empty and "revenue" in income_df.columns:
                            avg_rev = float(income_df["revenue"].replace(0, float("nan")).dropna().mean())
                            if avg_rev > 0:
                                norm_capex_pct = normal_capex / avg_rev
            except Exception:
                pass

        # ── Step 6: Build output dict ──────────────────────────
        output = {
            # ── Core (v4 keys — unchanged) ──────────────────────
            "ticker":           self.ticker,
            "price":            price,
            "shares":           shares,
            "total_debt":       bs["total_debt"],
            "total_cash":       bs["total_cash"],
            "income_df":        income_df,
            "cf_df":            cf_df,
            "native_ccy":       native_ccy,
            "fin_multiplier":   self._fin_multiplier,
            # IB-quality yfinance fields
            "forward_eps":      forward_eps,
            "trailing_eps":     trailing_eps,
            "forward_pe":       forward_pe,
            "peg_ratio":        peg_ratio,
            "roe":              roe,
            "roce_proxy":       roce_proxy,
            "de_ratio":         de_ratio,
            "interest_cov":     interest_cov,
            "gross_margin":     gross_margin,
            "sector_name":      sector_name,
            "norm_capex_pct":   norm_capex_pct,
            "ebitda":           ebitda,
            "enterprise_value": enterprise_value,
            "ev_to_ebitda":     ev_to_ebitda,
            "ev_to_revenue":    ev_to_revenue,
            "yahoo_fcf_ttm":    yahoo_fcf_ttm,
            "dividend_yield":   dividend_yield,
            "dividend_rate":    dividend_rate,
            "payout_ratio":     payout_ratio,
            "five_yr_avg_div_yield": five_yr_avg_div,
            # ── NEW Finnhub fields ───────────────────────────────
            "company_name":         company_name,
            "price_change_pct":     price_change_pct,
            "day_high":             fh_quote_data.get("day_high", 0),
            "day_low":              fh_quote_data.get("day_low",  0),
            "finnhub_price_target": fh_price_target,   # {mean,high,low,median,count}
            "finnhub_rec_trend":    fh_rec_trend,       # list of monthly trend dicts
            "finnhub_earnings":      fh_earnings,                        # list of EPS surprise dicts
            "earnings_track_record": compute_earnings_track_record(fh_earnings),  # beat stats
            "finnhub_next_earnings": fh_next_earn,      # {date,eps_estimate,...}
            "news":                 fh_news,            # list of recent headline dicts
            "finnhub_financials":   fh_financials,      # key ratios from Finnhub
            "finnhub_insider":      fh_insider,         # insider transactions + sentiment
            "finnhub_institutional": fh_inst,           # institutional ownership snapshot
            "fh_beta":              fh_financials.get("beta", 0),
            "fh_52w_high":          fh_financials.get("52w_high", 0),
            "fh_52w_low":           fh_financials.get("52w_low",  0),
            "fh_roic_ttm":          fh_financials.get("roic_ttm", 0),
            "fh_rev_growth_3y":     fh_financials.get("rev_growth_3y", 0),
            "fh_div_yield":         fh_financials.get("div_yield_ttm", 0),
            # ── Piotroski F-Score inputs ─────────────────────────
            # C5: day_change_pct alias (app.py header reads this key)
            "day_change_pct":       price_change_pct,
            # C2: prior-year shares for F7 dilution check
            "shares_prev_year":     shares_prev,
            # C3: balance sheet fields for F5/F6/F9
            "total_assets":         total_assets,
            "total_assets_prev":    total_assets_prev,
            "current_ratio":        current_ratio,
            "current_ratio_prev":   current_ratio_prev,
            "lt_debt":              lt_debt,
            "lt_debt_prev":         lt_debt_prev,
        }
        _cache.set(ck, output, TTL_PRICE)
        return output


# ════════════════════════════════════════════════════════════════
# TICKER LIST LOADER (unchanged)
# ════════════════════════════════════════════════════════════════

def load_tickers(path: str) -> list[str]:
    """
    Load tickers from *path*.

    When LAUNCH_REGION == "US", the path is silently overridden to
    usa_tickers.csv (same directory as the original path) so that Indian
    tickers from the legacy tickers.csv are never loaded.  The override
    is skipped when:
      • the caller already passed a usa_tickers.csv path, OR
      • LAUNCH_REGION is not "US"
    """
    try:
        from utils.config import LAUNCH_REGION as _lr
    except Exception:
        _lr = "US"

    if _lr == "US" and not str(path).endswith("usa_tickers.csv"):
        _us_path = pathlib.Path(path).parent / "usa_tickers.csv"
        if _us_path.exists():
            log.info(f"LAUNCH_REGION=US — loading from {_us_path} instead of {path}")
            path = str(_us_path)
        else:
            log.warning(
                f"LAUNCH_REGION=US but usa_tickers.csv not found at {_us_path}; "
                "falling back to original path"
            )

    try:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        col = "ticker" if "ticker" in df.columns else df.columns[0]
        tickers = df[col].dropna().str.upper().str.strip().tolist()

        # In US mode, strip any Indian tickers that may have slipped in
        if _lr == "US":
            tickers = [t for t in tickers if not (t.endswith(".NS") or t.endswith(".BO"))]

        return tickers
    except FileNotFoundError:
        log.error(f"Ticker file not found: {path}")
        return []
    except Exception as exc:
        log.error(f"Error loading tickers: {exc}")
        return []


# ════════════════════════════════════════════════════════════════
# US TICKER UNIVERSE BUILDER  — S&P 1500 + Russell 3000
# ════════════════════════════════════════════════════════════════

# Sectors where DCF is structurally unreliable:
#   Financials  → earnings-driven, not FCF; capital structure is the product
#   Real Estate → NAV / FFO-based; FCF is distorted by depreciation add-back
_NON_DCF_SECTORS = {"Financials", "Real Estate"}

# Micro-cap threshold — companies below this market cap are routed to
# relative valuation (DCF unreliable on thin / volatile FCF histories).
_MICRO_CAP_THRESHOLD: float = 300_000_000   # $300 M

# iShares Russell 3000 ETF (IWV) holdings CSV download URLs.
# Two URL patterns are tried in order; the first successful one is used.
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

# Map iShares sector labels → canonical GICS names used in the rest of
# the codebase. iShares uses GICS labels but occasionally differs in
# spacing / abbreviation.
_ISHARES_SECTOR_NORM: dict[str, str] = {
    "information technology":   "Information Technology",
    "technology":               "Information Technology",
    "financials":               "Financials",
    "health care":              "Health Care",
    "healthcare":               "Health Care",
    "consumer discretionary":   "Consumer Discretionary",
    "consumer staples":         "Consumer Staples",
    "industrials":              "Industrials",
    "energy":                   "Energy",
    "utilities":                "Utilities",
    "real estate":              "Real Estate",
    "materials":                "Materials",
    "communication services":   "Communication Services",
    "telecommunication services": "Communication Services",
    "telecom":                  "Communication Services",
}

def _fetch_russell3000_ishares(
    url: str | None = None,
    local_csv: str | pathlib.Path | None = None,
    timeout: int = 30,
) -> pd.DataFrame:
    """
    Download and parse the iShares Russell 3000 ETF (IWV) holdings CSV.

    Returns a DataFrame with columns [ticker, name, sector] for equity
    holdings only (cash, futures, and other non-equity rows are dropped).

    Parameters
    ----------
    url        : override the download URL (defaults to _RUSSELL_ETF_URLS[0]).
    local_csv  : path to a pre-downloaded iShares CSV file. Skips the
                 network fetch when provided.
    timeout    : HTTP request timeout in seconds.
    """
    import io

    # ── Load raw text ──────────────────────────────────────────────
    if local_csv is not None:
        raw_text = pathlib.Path(local_csv).read_text(encoding="utf-8", errors="replace")
        log.info(f"Russell 3000: reading from local file {local_csv}")
    else:
        urls_to_try = [url] if url else _RUSSELL_ETF_URLS
        raw_text = None
        last_err: Exception | None = None
        for u in urls_to_try:
            try:
                log.info(f"Russell 3000: downloading from {u} …")
                resp = requests.get(u, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                raw_text = resp.text
                break
            except Exception as exc:
                last_err = exc
                log.warning(f"Russell 3000: failed to fetch {u}: {exc}")
        if raw_text is None:
            raise RuntimeError(
                f"Could not download Russell 3000 holdings from any URL. "
                f"Last error: {last_err}"
            )

    # ── Find the data header row ───────────────────────────────────
    # iShares CSVs have ~4 metadata lines before the actual column headers.
    # We scan for the first row whose first cell is "Name" or "Ticker".
    lines = raw_text.splitlines()
    header_idx: int | None = None
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

    data_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(data_text), dtype=str)

    # ── Normalise column names ─────────────────────────────────────
    df.columns = [c.strip().lower() for c in df.columns]

    # Locate the columns we need (iShares occasionally renames them)
    _TICKER_CANDIDATES = ["ticker", "exchange ticker", "issuer ticker"]
    _NAME_CANDIDATES   = ["name", "security name", "issuer name"]
    _SECTOR_CANDIDATES = ["sector", "gics sector classification"]
    _ASSET_CANDIDATES  = ["asset class", "type"]

    def _find_col(candidates: list[str], cols: list[str]) -> str | None:
        for c in candidates:
            if c in cols:
                return c
        return None

    cols = list(df.columns)
    ticker_col = _find_col(_TICKER_CANDIDATES, cols)
    name_col   = _find_col(_NAME_CANDIDATES, cols)
    sector_col = _find_col(_SECTOR_CANDIDATES, cols)
    asset_col  = _find_col(_ASSET_CANDIDATES, cols)

    if ticker_col is None or sector_col is None:
        raise RuntimeError(
            f"iShares CSV missing expected columns. Found: {cols}"
        )

    # ── Filter to equity holdings only ────────────────────────────
    if asset_col:
        equity_mask = df[asset_col].str.strip().str.lower().isin(
            {"equity", "common stock", "depositary receipts"}
        )
        df = df[equity_mask].copy()

    # ── Build clean output ─────────────────────────────────────────
    out = pd.DataFrame()
    out["ticker"] = (
        df[ticker_col]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", "", regex=True)
    )
    out["name"] = (
        df[name_col].astype(str).str.strip()
        if name_col else "Unknown"
    )
    raw_sector = df[sector_col].astype(str).str.strip()
    out["sector"] = raw_sector.str.lower().map(
        lambda s: _ISHARES_SECTOR_NORM.get(s, s.title())
    )

    # Drop rows with missing or invalid tickers
    out = out[out["ticker"].str.match(r"^[A-Z]{1,5}(\.[A-Z])?$")]
    out = out.dropna(subset=["ticker"])
    out = out[out["ticker"] != ""]
    out = out.drop_duplicates(subset="ticker").reset_index(drop=True)

    log.info(f"Russell 3000: {len(out)} equity tickers parsed from iShares CSV")
    return out


def _fetch_market_caps_yf(
    tickers: list[str],
    max_workers: int = 20,
) -> dict[str, float | None]:
    """
    Fetch market caps for a list of tickers using yfinance fast_info.

    Returns a dict mapping ticker → market_cap (float) or None if unavailable.
    Uses a thread pool to parallelise requests.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    result: dict[str, float | None] = {}

    def _get_one(ticker: str) -> tuple[str, float | None]:
        try:
            mc = _yf_ticker(ticker).fast_info.market_cap
            return ticker, float(mc) if mc else None
        except Exception:
            return ticker, None

    total = len(tickers)
    log.info(f"Fetching market caps for {total} tickers (workers={max_workers}) …")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_get_one, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            ticker, cap = fut.result()
            result[ticker] = cap
            done += 1
            if done % 200 == 0:
                log.info(f"  market cap fetch: {done}/{total}")

    fetched = sum(1 for v in result.values() if v is not None)
    log.info(f"Market cap fetch complete: {fetched}/{total} succeeded")
    return result


# Wikipedia table specs: (url, table_index, ticker_col, name_col, sector_col)
# table_index = which <table class="wikitable"> on the page (0-based)
_SP_SOURCES = [
    (
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        0,          # first sortable wikitable
        "Symbol",
        "Security",
        "GICS Sector",
        "S&P 500",
    ),
    (
        "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        0,
        "Ticker symbol",   # Wikipedia uses this header for the 400
        "Company",
        "GICS Sector",
        "S&P 400",
    ),
    (
        "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
        0,
        "Ticker symbol",
        "Company",
        "GICS Sector",
        "S&P 600",
    ),
]

# Fallback column name aliases (Wikipedia edits headers occasionally)
_TICKER_ALIASES = ["Symbol", "Ticker symbol", "Ticker", "Ticker Symbol"]
_NAME_ALIASES   = ["Security", "Company", "Name", "Company name"]
_SECTOR_ALIASES = ["GICS Sector", "Sector", "GICS sector"]


def _pick_col(df: pd.DataFrame, aliases: list[str]) -> str:
    """Return the first column name from *aliases* that exists in *df*."""
    cols_lower = {c.strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias in df.columns:
            return alias
        if alias.lower() in cols_lower:
            return cols_lower[alias.lower()]
    raise KeyError(f"None of {aliases} found in columns: {list(df.columns)}")


def _fetch_sp_index(
    url: str,
    table_idx: int,
    ticker_col: str,
    name_col: str,
    sector_col: str,
    index_name: str,
) -> pd.DataFrame:
    """
    Fetch one S&P index table from Wikipedia.

    Returns a clean DataFrame with columns [ticker, name, sector, index].
    Raises on any network or parse failure so the caller can skip gracefully.
    """
    log.info(f"Fetching {index_name} from Wikipedia …")
    tables = pd.read_html(url, attrs={"class": "wikitable"}, flavor="lxml")

    if table_idx >= len(tables):
        # Fallback: try the largest table
        table_idx = max(range(len(tables)), key=lambda i: len(tables[i]))
        log.warning(f"{index_name}: table_idx out of range, using largest table ({table_idx})")

    df = tables[table_idx].copy()

    # Flatten multi-level columns that Wikipedia sometimes generates
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(c) for c in col).strip() for col in df.columns]

    # Strip whitespace from all column names
    df.columns = [str(c).strip() for c in df.columns]

    try:
        tc = _pick_col(df, _TICKER_ALIASES)
        nc = _pick_col(df, _NAME_ALIASES)
        sc = _pick_col(df, _SECTOR_ALIASES)
    except KeyError as exc:
        raise RuntimeError(
            f"{index_name}: could not locate required columns — {exc}\n"
            f"Available columns: {list(df.columns)}"
        )

    out = pd.DataFrame({
        "ticker": df[tc].astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True),
        "name":   df[nc].astype(str).str.strip(),
        "sector": df[sc].astype(str).str.strip(),
        "index":  index_name,
    })

    # Drop header-repeat rows and obviously bad tickers
    out = out[out["ticker"].str.match(r"^[A-Z]{1,5}(\.[A-Z])?$")]
    out = out.dropna(subset=["ticker"])
    out = out[out["ticker"] != ""]

    log.info(f"  {index_name}: {len(out)} tickers parsed")
    return out


def build_us_ticker_universe(
    output_path: str | pathlib.Path | None = None,
    *,
    source: str = "both",
    russell_csv: str | pathlib.Path | None = None,
    fetch_market_caps: bool = False,
    market_cap_threshold: float = _MICRO_CAP_THRESHOLD,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Build and save the US ticker universe (S&P 1500 and/or Russell 3000).

    Parameters
    ----------
    output_path          : path to write the CSV. Defaults to
                           <this_file's_dir>/usa_tickers.csv
    source               : "sp1500"    — Wikipedia S&P 500/400/600 only
                           "russell3000" — iShares IWV holdings only
                           "both"      — merge both (S&P takes priority for
                                         duplicates; Russell adds ~1,500 extras)
    russell_csv          : path to a pre-downloaded iShares IWV holdings CSV.
                           Skips the network fetch when provided. Only used
                           when source is "russell3000" or "both".
    fetch_market_caps    : if True, fetch market caps via yfinance for Russell-
                           only tickers and mark those below market_cap_threshold
                           as dcf_eligible=False (micro-cap filter).
    market_cap_threshold : market cap cutoff in USD (default $300 M).
    verbose              : print a build summary to stdout.

    Returns
    -------
    DataFrame with columns: ticker, name, sector, dcf_eligible
    """
    if output_path is None:
        output_path = pathlib.Path(__file__).parent / "usa_tickers.csv"
    output_path = pathlib.Path(output_path)

    source = source.lower()
    if source not in ("sp1500", "russell3000", "both"):
        raise ValueError(f"source must be 'sp1500', 'russell3000', or 'both', got {source!r}")

    frames_sp: list[pd.DataFrame] = []
    failed: list[str] = []

    # ── Step 1: S&P 1500 from Wikipedia ───────────────────────────
    if source in ("sp1500", "both"):
        for src in _SP_SOURCES:
            url, tbl_idx, ticker_col, name_col, sector_col, index_name = src
            try:
                df = _fetch_sp_index(url, tbl_idx, ticker_col, name_col, sector_col, index_name)
                frames_sp.append(df)
            except Exception as exc:
                log.error(f"Failed to fetch {index_name}: {exc}")
                failed.append(index_name)

        if source == "sp1500" and not frames_sp:
            raise RuntimeError(
                "Could not fetch any S&P index from Wikipedia. "
                "Check your internet connection and try again."
            )

    # ── Step 2: Russell 3000 from iShares ─────────────────────────
    russell_df: pd.DataFrame | None = None
    if source in ("russell3000", "both"):
        try:
            russell_df = _fetch_russell3000_ishares(local_csv=russell_csv)
            russell_df["index"] = "Russell 3000"
        except Exception as exc:
            log.error(f"Failed to fetch Russell 3000: {exc}")
            if source == "russell3000":
                raise
            # In "both" mode, fall back to S&P 1500 alone
            log.warning("Continuing with S&P 1500 only (Russell 3000 fetch failed).")

    # ── Step 3: Merge ─────────────────────────────────────────────
    if frames_sp and russell_df is not None:
        sp_combined = pd.concat(frames_sp, ignore_index=True)
        sp_combined = sp_combined.drop_duplicates(subset="ticker", keep="first")
        sp_tickers  = set(sp_combined["ticker"])

        # Russell-only extras (not already in S&P 1500)
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
        raise RuntimeError("No tickers loaded from any source.")

    # ── Step 4: Sector-based DCF eligibility ──────────────────────
    combined["dcf_eligible"] = ~combined["sector"].isin(_NON_DCF_SECTORS)

    # ── Step 5: Micro-cap filter (Russell-only tickers, optional) ─
    micro_cap_tickers: set[str] = set()
    if fetch_market_caps and russell_df is not None:
        # Only bother fetching caps for Russell-only tickers that are currently
        # sector-eligible (saves API calls for already-excluded tickers)
        candidates = combined[
            (~combined["_source_sp"]) & combined["dcf_eligible"]
        ]["ticker"].tolist()

        if candidates:
            caps = _fetch_market_caps_yf(candidates)
            micro_cap_tickers = {
                t for t, cap in caps.items()
                if cap is not None and cap < market_cap_threshold
            }
            # Mark micro-caps as non-DCF
            combined.loc[
                combined["ticker"].isin(micro_cap_tickers), "dcf_eligible"
            ] = False
            log.info(
                f"Micro-cap filter: {len(micro_cap_tickers)} tickers marked "
                f"dcf_eligible=False (market cap < ${market_cap_threshold:,.0f})"
            )

    # ── Step 6: Final cleanup ─────────────────────────────────────
    out = combined[["ticker", "name", "sector", "dcf_eligible"]].copy()
    out = out.sort_values("ticker").reset_index(drop=True)

    # ── Save ──────────────────────────────────────────────────────
    out.to_csv(output_path, index=False)
    log.info(f"Saved {len(out)} tickers → {output_path}")

    # ── Summary ──────────────────────────────────────────────────
    if verbose:
        total   = len(out)
        dcf_ok  = int(out["dcf_eligible"].sum())
        non_dcf = total - dcf_ok

        by_index: dict[str, int] = {}
        if "index" in combined.columns:
            by_index = combined.groupby("index").size().to_dict()
        by_sector = out.groupby("sector").size().sort_values(ascending=False)

        print("\n" + "═" * 56)
        print("  YieldIQ — US Ticker Universe Build Complete")
        print("═" * 56)
        if failed:
            print(f"  ⚠  Failed sources: {', '.join(failed)}")
        for idx_name, cnt in sorted(by_index.items()):
            print(f"  {idx_name:<18}: {cnt:>4} tickers")
        print(f"  {'─'*40}")
        print(f"  Total unique    : {total:>4}")
        print(f"  DCF-eligible    : {dcf_ok:>4}  (excl. Financials & Real Estate)")
        non_dcf_sector = total - dcf_ok - len(micro_cap_tickers)
        if micro_cap_tickers:
            print(f"  Non-DCF sector  : {non_dcf_sector:>4}  (Financials, Real Estate)")
            print(f"  Micro-cap (<$300M): {len(micro_cap_tickers):>4}")
        else:
            print(f"  Non-DCF         : {non_dcf:>4}  (Financials, Real Estate)")
        print("─" * 56)
        print("  Top sectors by ticker count:")
        for sector, cnt in by_sector.items():
            flag = "  [non-DCF]" if sector in _NON_DCF_SECTORS else ""
            print(f"    {sector:<35} {cnt:>4}{flag}")
        print(f"\n  Saved → {output_path}")
        print("═" * 56 + "\n")

    return out


# ════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
#   python -m data.collector --rebuild-us-tickers
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m data.collector",
        description="YieldIQ data collector CLI",
    )
    parser.add_argument(
        "--rebuild-us-tickers",
        action="store_true",
        help=(
            "Build/regenerate data/usa_tickers.csv. "
            "Fetches S&P 1500 from Wikipedia and/or Russell 3000 from iShares."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Override the output CSV path (default: data/usa_tickers.csv).",
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
            "Skips the network fetch when provided. "
            "Only used with --source russell3000 or both."
        ),
    )
    parser.add_argument(
        "--fetch-market-caps",
        action="store_true",
        help=(
            "Fetch market caps via yfinance for Russell-only tickers and mark "
            "micro-caps (below --market-cap-threshold) as dcf_eligible=False. "
            "Slow: makes one yfinance call per ticker. Default: off."
        ),
    )
    parser.add_argument(
        "--market-cap-threshold",
        type=float,
        default=_MICRO_CAP_THRESHOLD,
        metavar="USD",
        help=(
            f"Market cap cutoff in USD for the micro-cap DCF exclusion filter. "
            f"Default: {_MICRO_CAP_THRESHOLD:,.0f} ($300 M)."
        ),
    )

    args = parser.parse_args()

    if args.rebuild_us_tickers:
        build_us_ticker_universe(
            output_path=args.output,
            source=args.source,
            russell_csv=args.russell_csv,
            fetch_market_caps=args.fetch_market_caps,
            market_cap_threshold=args.market_cap_threshold,
        )
    else:
        parser.print_help()
