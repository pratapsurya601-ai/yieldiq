# backend/services/portfolio_aggregator.py
"""
Portfolio Prism aggregator (Phase 1, 2026-05-03).

Pure-Python aggregation over already-cached single-ticker analysis
payloads. NEVER recomputes — every per-ticker lookup goes through
`analysis_cache_service.get_cached`. If a ticker is not in the cache
(or the per-ticker lookup exceeds the budget) the holding is recorded
as `data_limited` and excluded from the weighted aggregates.

Phase 1 scope (this PR):
    * Aggregate Prism scores (value-weighted across holdings, per pillar)
    * Sector concentration (% of portfolio value by sector)
    * Valuation skew (% in undervalued / fairly_valued / overvalued)
    * Piotroski distribution (count of holdings with score >=7, 4-6, <4)

Explicitly NOT in this PR (deferred to Phase 2):
    * Substitution suggestions
    * Persistence (no user_portfolios table)
    * Tier gating (any signed-in user can call the endpoint)

Hard caps applied here:
    * 25 holdings per request (caller enforces — reject with 400)
    * 2s per-ticker timeout
    * 30s total request budget

The 6 Prism pillars come from the in-memory prism cache
(`prism:{TICKER}:raw`) populated by `prism_service.get_prism`. We do
NOT call `prism_service.get_prism` directly from the aggregator — that
would risk a cold compute. Instead we read `cache.get(...)` only and
treat a miss as a missing-pillar contribution.

The composite Prism score (yieldiq_score_100), sector, verdict_band,
piotroski_score, and current_price all come from the persistent
analysis cache (`analysis_cache_service.get_cached`), which is the
exact same source the public single-ticker endpoint serves from.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from typing import Any, Optional

from backend.services import analysis_cache_service
from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.portfolio_aggregator")

# Hard caps — duplicated as constants here so tests + router share the
# same numbers. Router enforces MAX_HOLDINGS at the request layer.
MAX_HOLDINGS = 25
PER_TICKER_TIMEOUT_S = 2.0
TOTAL_BUDGET_S = 30.0

# Canonical pillar order — must match
# `backend.services.analysis.hex_axes.AXIS_WEIGHTS` keys. Defined
# locally so the aggregator does not depend on hex_axes import-time
# side effects.
PILLARS = ("value", "quality", "growth", "moat", "safety", "pulse")


def _normalize_ticker(raw: str) -> str:
    """Canonicalise to upper-case .NS form used by the cache."""
    t = (raw or "").strip().upper()
    if not t:
        return ""
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


def _fetch_one(ticker: str) -> dict:
    """Fetch the cached analysis + cached prism axes for one ticker.

    Returns a dict with the fields the aggregator consumes. Never
    raises — failures are surfaced via `data_limited=True` so the
    caller can decide whether to skip or include.
    """
    norm = _normalize_ticker(ticker)
    out: dict[str, Any] = {
        "ticker": norm,
        "data_limited": True,
        "current_price": None,
        "sector": None,
        "verdict_band": None,
        "piotroski_score": None,
        "composite_score": None,  # 0-100 (yieldiq_score)
        "axes": {},               # pillar -> 0..10 (or absent)
    }

    # Tier-2 (Postgres) analysis cache — same source as the public
    # single-ticker endpoint. Returns None on any failure.
    try:
        payload = analysis_cache_service.get_cached(norm)
    except Exception as exc:
        logger.warning("aggregator: get_cached raised for %s: %s", norm, exc)
        payload = None

    if isinstance(payload, dict):
        try:
            valuation = payload.get("valuation") or {}
            quality = payload.get("quality") or {}
            company = payload.get("company") or {}

            out["current_price"] = (
                valuation.get("current_price")
                or payload.get("current_price")
            )
            out["sector"] = (
                company.get("sector")
                or payload.get("sector")
                or "Unknown"
            )
            out["verdict_band"] = valuation.get("verdict")
            ps = quality.get("piotroski_score")
            out["piotroski_score"] = int(ps) if ps is not None else None
            cs = quality.get("yieldiq_score")
            out["composite_score"] = int(cs) if cs is not None else None
            # Mark not-data-limited only when we have at minimum a price
            # AND a verdict — the two fields the skew/weighting math
            # actually depends on.
            if out["current_price"] and out["verdict_band"]:
                out["data_limited"] = False
        except Exception as exc:
            logger.warning("aggregator: payload parse failed for %s: %s", norm, exc)

    # Tier-0 in-memory prism cache for the per-pillar axes. Reading
    # only, never compute. Cold worker = missing axes for this ticker;
    # the aggregator simply won't contribute to the weighted pillar
    # average for that holding.
    try:
        prism_raw = cache.get(f"prism:{norm}:raw")
    except Exception:
        prism_raw = None
    if isinstance(prism_raw, dict):
        try:
            axes = ((prism_raw.get("hex") or {}).get("axes")) or {}
            cleaned: dict[str, float] = {}
            for k in PILLARS:
                node = axes.get(k) or {}
                score = node.get("score")
                if score is None:
                    continue
                try:
                    cleaned[k] = float(score)
                except (TypeError, ValueError):
                    continue
            if cleaned:
                out["axes"] = cleaned
        except Exception as exc:
            logger.warning("aggregator: prism parse failed for %s: %s", norm, exc)

    return out


def _piotroski_bucket(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score >= 7:
        return "strong"
    if score >= 4:
        return "moderate"
    return "weak"


def aggregate_portfolio(
    holdings: list[dict],
    *,
    deadline_s: float = TOTAL_BUDGET_S,
    per_ticker_timeout_s: float = PER_TICKER_TIMEOUT_S,
) -> dict:
    """Aggregate cached Prism payloads across `holdings`.

    `holdings` is a list of `{ticker: str, shares: float}`. The router
    enforces MAX_HOLDINGS — this function does not (so tests can pass
    arbitrary fixtures).

    Weighting rule: each holding's weight = shares × current_price.
    Holdings with no cached current_price contribute zero weight (and
    are reported in `data_limited_tickers` so the UI can warn).
    """
    started = time.monotonic()
    deadline = started + max(0.5, float(deadline_s))

    # Parallel cache-only fetch. Each lookup is sub-50ms in the warm
    # case; the per-ticker timeout exists purely to bound the worst
    # case (Aiven session hiccup) so a single slow query can't sink
    # the whole request.
    fetched: list[dict] = []
    data_limited_tickers: list[str] = []
    invalid_tickers: list[str] = []

    n = len(holdings)
    workers = min(max(n, 1), 8)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="agg") as pool:
        futures = {}
        for h in holdings:
            t = _normalize_ticker(h.get("ticker", ""))
            if not t:
                invalid_tickers.append(str(h.get("ticker", "")))
                continue
            futures[pool.submit(_fetch_one, t)] = (t, float(h.get("shares") or 0))

        for fut, (t, shares) in futures.items():
            remaining = deadline - time.monotonic()
            timeout = min(per_ticker_timeout_s, max(0.05, remaining))
            try:
                row = fut.result(timeout=timeout)
            except FutTimeout:
                logger.warning("aggregator: per-ticker timeout for %s (%.2fs)", t, timeout)
                row = {
                    "ticker": t,
                    "data_limited": True,
                    "current_price": None,
                    "sector": "Unknown",
                    "verdict_band": None,
                    "piotroski_score": None,
                    "composite_score": None,
                    "axes": {},
                }
            except Exception as exc:
                logger.warning("aggregator: fetch raised for %s: %s", t, exc)
                row = {
                    "ticker": t,
                    "data_limited": True,
                    "current_price": None,
                    "sector": "Unknown",
                    "verdict_band": None,
                    "piotroski_score": None,
                    "composite_score": None,
                    "axes": {},
                }
            row["shares"] = shares
            row["weight_value"] = (
                float(row["current_price"]) * shares
                if row.get("current_price") and shares > 0 else 0.0
            )
            if row.get("data_limited"):
                data_limited_tickers.append(t)
            fetched.append(row)

    total_value = sum(r["weight_value"] for r in fetched)

    # ── Per-pillar value-weighted Prism score (0..100 display scale) ──
    pillar_num = {p: 0.0 for p in PILLARS}
    pillar_den = {p: 0.0 for p in PILLARS}
    for r in fetched:
        w = r["weight_value"]
        if w <= 0:
            continue
        axes = r.get("axes") or {}
        for p in PILLARS:
            if p in axes:
                pillar_num[p] += axes[p] * w
                pillar_den[p] += w
    prism_pillars: dict[str, Optional[float]] = {}
    for p in PILLARS:
        if pillar_den[p] > 0:
            # axes are 0..10; convert to 0..100 for the UI bars
            prism_pillars[p] = round((pillar_num[p] / pillar_den[p]) * 10.0, 1)
        else:
            prism_pillars[p] = None

    # ── Aggregate composite score (value-weighted, 0..100) ──
    comp_num = 0.0
    comp_den = 0.0
    for r in fetched:
        cs = r.get("composite_score")
        w = r["weight_value"]
        if cs is None or w <= 0:
            continue
        comp_num += float(cs) * w
        comp_den += w
    composite = round(comp_num / comp_den, 1) if comp_den > 0 else None

    # ── Sector concentration ──
    sector_value: dict[str, float] = {}
    for r in fetched:
        if r["weight_value"] <= 0:
            continue
        sec = r.get("sector") or "Unknown"
        sector_value[sec] = sector_value.get(sec, 0.0) + r["weight_value"]
    sector_concentration = []
    if total_value > 0:
        for sec, val in sorted(sector_value.items(), key=lambda kv: kv[1], reverse=True):
            sector_concentration.append({
                "sector": sec,
                "value": round(val, 2),
                "pct": round(val / total_value * 100.0, 2),
            })

    # ── Valuation skew (by verdict_band) ──
    skew_buckets = {
        "undervalued": 0.0,
        "fairly_valued": 0.0,
        "overvalued": 0.0,
        "other": 0.0,  # avoid / data_limited / unavailable / unknown
    }
    for r in fetched:
        v = (r.get("verdict_band") or "").lower()
        w = r["weight_value"]
        if w <= 0:
            continue
        if v in ("undervalued", "fairly_valued", "overvalued"):
            skew_buckets[v] += w
        else:
            skew_buckets["other"] += w
    valuation_skew = {}
    if total_value > 0:
        for k, v in skew_buckets.items():
            valuation_skew[k] = round(v / total_value * 100.0, 2)
    else:
        valuation_skew = {k: 0.0 for k in skew_buckets}

    # ── Piotroski distribution (count of holdings, not weighted) ──
    piotroski = {"strong": 0, "moderate": 0, "weak": 0, "unknown": 0}
    for r in fetched:
        b = _piotroski_bucket(r.get("piotroski_score"))
        if b is None:
            piotroski["unknown"] += 1
        else:
            piotroski[b] += 1

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Per-holding rows (lightweight — no full payload echoed). Useful
    # for the UI table and for debugging "why is my pillar X?".
    holding_rows = [
        {
            "ticker": r["ticker"],
            "shares": r["shares"],
            "current_price": r.get("current_price"),
            "value": round(r["weight_value"], 2),
            "weight_pct": (
                round(r["weight_value"] / total_value * 100.0, 2)
                if total_value > 0 else 0.0
            ),
            "sector": r.get("sector"),
            "verdict_band": r.get("verdict_band"),
            "piotroski_score": r.get("piotroski_score"),
            "composite_score": r.get("composite_score"),
            "data_limited": r.get("data_limited", False),
        }
        for r in fetched
    ]

    return {
        "summary": {
            "holding_count": len(fetched),
            "total_value": round(total_value, 2),
            "composite_score": composite,
            "data_limited_count": len(data_limited_tickers),
            "invalid_tickers": invalid_tickers,
            "data_limited_tickers": data_limited_tickers,
            "elapsed_ms": elapsed_ms,
        },
        "prism_pillars": prism_pillars,
        "sector_concentration": sector_concentration,
        "valuation_skew": valuation_skew,
        "piotroski_distribution": piotroski,
        "holdings": holding_rows,
        # Phase-2 markers — explicit so the frontend knows it's not a
        # forgotten field, it's a deliberate Phase-1 cut.
        "substitutions": None,
        "phase": 1,
    }


__all__ = ["aggregate_portfolio", "MAX_HOLDINGS", "PILLARS"]
