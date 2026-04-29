# backend/services/finnhub_analyst_service.py
"""
Finnhub analyst-data fetcher.

Exposes ``fetch_analyst_consensus(ticker)`` which returns a normalized
dict combining three Finnhub endpoints:

  1. /stock/recommendation   — monthly rating-trend snapshots
  2. /stock/price-target     — analyst price-target high/low/mean/median
  3. /stock/earnings-estimate — annual EPS consensus (FY current + next)

Results are cached for 24h via the shared ``endpoint_cache`` table
(key: ``finnhub:analyst:{TICKER}``). Network failures degrade
gracefully — the function never raises; it returns ``None`` on hard
errors and an empty-but-valid dict (``coverage_count=0``) when the API
returns no coverage for that symbol.

The caller (analysis service) is responsible for computing
``vs_current_pct`` against the live current price, since that varies
per request and shouldn't be cached.

Indian listings: Finnhub uses the ``.NS`` (NSE) and ``.BO`` (BSE)
suffixes that Yahoo uses, so we pass tickers through verbatim.
The function uppercases, strips whitespace, and otherwise leaves the
symbol alone. Callers can pass either ``INFY.NS`` or ``infy.ns``.

NO secrets in this module — the API key is read from
``os.environ["FINNHUB_API_KEY"]`` only.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

from backend.services import endpoint_cache_service as _ecs

logger = logging.getLogger("yieldiq.finnhub_analyst")

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 8
_CACHE_TTL_HOURS = 24


def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "") or ""


def _get(endpoint: str, params: dict) -> Optional[Any]:
    """Best-effort GET against Finnhub. Returns parsed JSON or None."""
    key = _api_key()
    if not key:
        logger.debug("finnhub_analyst: no FINNHUB_API_KEY configured")
        return None
    try:
        merged = dict(params)
        merged["token"] = key
        r = requests.get(
            f"{_FINNHUB_BASE}{endpoint}",
            params=merged,
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            logger.warning("finnhub_analyst: rate-limited on %s", endpoint)
            return None
        logger.debug(
            "finnhub_analyst: %s -> HTTP %s", endpoint, r.status_code
        )
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("finnhub_analyst: %s error: %s", endpoint, exc)
        return None


# ── Endpoint adapters ───────────────────────────────────────────

def _fetch_recommendation(ticker: str) -> list[dict]:
    """Latest monthly snapshot of analyst recommendations."""
    data = _get("/stock/recommendation", {"symbol": ticker})
    if isinstance(data, list):
        return data
    return []


def _fetch_price_target(ticker: str) -> dict:
    data = _get("/stock/price-target", {"symbol": ticker})
    return data if isinstance(data, dict) else {}


def _fetch_eps_estimates(ticker: str) -> list[dict]:
    """Annual EPS consensus estimates."""
    data = _get(
        "/stock/earnings-estimate",
        {"symbol": ticker, "freq": "annual"},
    )
    if isinstance(data, dict):
        return data.get("data") or []
    return []


# ── Normalization ───────────────────────────────────────────────

def _consensus_label(rd: dict) -> str:
    """Weighted majority label from a rating distribution dict."""
    sb = int(rd.get("strong_buy", 0))
    b = int(rd.get("buy", 0))
    h = int(rd.get("hold", 0))
    s = int(rd.get("sell", 0))
    ss = int(rd.get("strong_sell", 0))
    total = sb + b + h + s + ss
    if total <= 0:
        return ""
    # Weighted average on a 1-5 scale:
    #   strong_buy=5, buy=4, hold=3, sell=2, strong_sell=1
    score = (5 * sb + 4 * b + 3 * h + 2 * s + 1 * ss) / total
    if score >= 4.5:
        return "Strong Buy"
    if score >= 3.5:
        return "Buy"
    if score >= 2.5:
        return "Hold"
    if score >= 1.5:
        return "Sell"
    return "Strong Sell"


def _normalize(
    rec: list[dict], pt: dict, eps: list[dict], as_of: str
) -> dict:
    """Combine the three raw payloads into the response shape."""
    latest_rec = rec[0] if rec else {}
    sb = int(latest_rec.get("strongBuy", 0) or 0)
    b = int(latest_rec.get("buy", 0) or 0)
    h = int(latest_rec.get("hold", 0) or 0)
    s = int(latest_rec.get("sell", 0) or 0)
    ss = int(latest_rec.get("strongSell", 0) or 0)
    rec_total = sb + b + h + s + ss

    rd = {
        "strong_buy": sb,
        "buy": b,
        "hold": h,
        "sell": s,
        "strong_sell": ss,
    }

    # Coverage = recommendations total OR price-target analyst count,
    # whichever is bigger. The two endpoints occasionally disagree
    # (some analysts publish targets without ratings or vice versa).
    pt_count = int(pt.get("numberOfAnalysts", 0) or 0)
    coverage = max(rec_total, pt_count)

    if coverage <= 0:
        return {
            "coverage_count": 0,
            "rating_distribution": None,
            "consensus_rating": None,
            "price_target": None,
            "eps_estimate": None,
            "as_of": as_of,
            "source": "Finnhub",
        }

    consensus = _consensus_label(rd) if rec_total > 0 else None

    price_target = None
    if pt and (pt.get("targetMean") or pt.get("targetMedian")):
        mean = float(pt.get("targetMean") or 0) or None
        median = float(pt.get("targetMedian") or 0) or None
        high = float(pt.get("targetHigh") or 0) or None
        low = float(pt.get("targetLow") or 0) or None
        price_target = {
            "median": median,
            "mean": mean,
            "high": high,
            "low": low,
            # vs_current_pct filled in later by the analysis service.
            "vs_current_pct": None,
        }

    # EPS estimates — pick FY current (period closest to today, future)
    # and FY next. Finnhub returns periods in ISO date format
    # ("2026-03-31"). We sort ascending and pick the first two future
    # periods.
    eps_estimate = None
    if eps:
        # Filter to entries with a numeric epsAvg.
        rows = []
        for row in eps:
            try:
                period = row.get("period") or ""
                avg = row.get("epsAvg")
                if avg is None:
                    continue
                rows.append({"period": period, "eps_avg": float(avg)})
            except (TypeError, ValueError):
                continue
        rows.sort(key=lambda r: r["period"])
        # Pick periods >= as_of when possible; fall back to the last two.
        future = [r for r in rows if r["period"] >= as_of]
        picked = future[:2] if len(future) >= 2 else rows[-2:]
        if picked:
            fy_current = picked[0]["eps_avg"] if len(picked) >= 1 else None
            fy_next = picked[1]["eps_avg"] if len(picked) >= 2 else None
            if fy_current is not None or fy_next is not None:
                eps_estimate = {
                    "fy_current": fy_current,
                    "fy_next": fy_next,
                }

    return {
        "coverage_count": coverage,
        "rating_distribution": rd if rec_total > 0 else None,
        "consensus_rating": consensus,
        "price_target": price_target,
        "eps_estimate": eps_estimate,
        "as_of": as_of,
        "source": "Finnhub",
    }


def _empty(as_of: str) -> dict:
    return {
        "coverage_count": 0,
        "rating_distribution": None,
        "consensus_rating": None,
        "price_target": None,
        "eps_estimate": None,
        "as_of": as_of,
        "source": "Finnhub",
    }


# ── Public API ──────────────────────────────────────────────────

def fetch_analyst_consensus(
    ticker: str,
    *,
    current_price: Optional[float] = None,
    use_cache: bool = True,
) -> Optional[dict]:
    """
    Fetch and normalize Finnhub analyst data for ``ticker``.

    Parameters
    ----------
    ticker : str
        Stock symbol with exchange suffix (e.g. ``INFY.NS``,
        ``RELIANCE.NS``, ``TCS.BO``). Case-insensitive.
    current_price : float, optional
        Live price used to compute ``price_target.vs_current_pct``.
        If None, ``vs_current_pct`` stays None.
    use_cache : bool
        Set False to bypass the 24h endpoint_cache (e.g. for testing).

    Returns
    -------
    dict or None
        Returns the normalized consensus dict on success (including
        when there is no coverage — see ``coverage_count``). Returns
        ``None`` only if ``FINNHUB_API_KEY`` is unset, so the caller
        can distinguish "no coverage" from "cannot query".
    """
    from datetime import date

    if not ticker:
        return None
    sym = ticker.strip().upper()
    if not sym:
        return None

    if not _api_key():
        return None

    cache_key = f"finnhub:analyst:{sym}"
    as_of = date.today().isoformat()

    cached = _ecs.get(cache_key) if use_cache else None
    if cached and isinstance(cached, dict):
        result = dict(cached)
    else:
        try:
            rec = _fetch_recommendation(sym)
            pt = _fetch_price_target(sym)
            eps = _fetch_eps_estimates(sym)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "finnhub_analyst: fetch failed for %s: %s", sym, exc
            )
            return _empty(as_of)

        result = _normalize(rec, pt, eps, as_of)
        if use_cache:
            try:
                _ecs.set(cache_key, result, ttl_hours=_CACHE_TTL_HOURS)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "finnhub_analyst: cache write failed for %s: %s",
                    sym, exc,
                )

    # Compute vs_current_pct outside the cache — current_price is live.
    if (
        current_price
        and current_price > 0
        and result.get("price_target")
        and result["price_target"].get("median")
    ):
        try:
            median = float(result["price_target"]["median"])
            result["price_target"]["vs_current_pct"] = round(
                (median / current_price - 1.0) * 100.0, 1
            )
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return result


__all__ = ["fetch_analyst_consensus"]
