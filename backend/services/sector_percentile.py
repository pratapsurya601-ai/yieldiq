# backend/services/sector_percentile.py
# ═══════════════════════════════════════════════════════════════
# Sector-percentile module — Stage 1 of 3.
#
# Why: a single ticker's PE/PB/MoS only mean something relative to
# its sector peers. This module assembles per-sector cohorts and
# ranks values within them, so callers can render bands like
# "below peers" or "notably overvalued" instead of context-free
# numbers.
#
# Stage scope:
#   Stage 1 (this file): module + tests, no callers wired up.
#                        Importing this has zero side effects.
#   Stage 2: hex_service / payload integration.
#   Stage 3: CACHE_VERSION bump + canary diff.
#
# Sources: sector taxonomy from sector_benchmarks.py (PR #161),
# mos_pct from analysis_cache.payload.valuation.margin_of_safety,
# pe_ratio/pb_ratio from market_metrics (latest row per ticker).
# Cohort filter: market_cap_cr > 100 (exclude micro-caps).
# Cache: in-process, 1h TTL per canonical sector label.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

from sqlalchemy import text

from backend.services import sector_benchmarks

logger = logging.getLogger("yieldiq.sector_percentile")

_COHORT_TTL_SECONDS = 3600
_MIN_MARKET_CAP_CR = 100.0
_cohort_cache: dict[str, tuple[float, list[dict]]] = {}
_cohort_cache_lock = threading.Lock()

# Percentile thresholds (lower = cheaper). Callers passing PE/PB
# should invert via 100 - pr before mapping.
_BAND_THRESHOLDS = (
    (10,  "strong_discount",     "Strong discount vs peers"),
    (30,  "below_peers",         "Below peer range"),
    (70,  "in_range",            "In peer range"),
    (90,  "above_peers",         "Above peer range"),
    (101, "notably_overvalued",  "Notably overvalued vs peers"),
)


def percentile_rank(value: float, cohort_values: list[float]) -> int:
    """Standard percentile rank (no interpolation), 0-100.

    Defined as the percent of cohort values strictly less than
    `value`. Empty cohort or non-finite `value` returns 0.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    if v != v or v in (float("inf"), float("-inf")):
        return 0
    if not cohort_values:
        return 0

    n = 0
    below = 0
    for raw in cohort_values:
        try:
            x = float(raw)
        except (TypeError, ValueError):
            continue
        if x != x:
            continue
        n += 1
        if x < v:
            below += 1
    if n == 0:
        return 0
    return int(round((below / n) * 100))


def value_band_for_percentile(percentile: Optional[int]) -> dict:
    """Map 0-100 percentile to {band, label}. None / out-of-range → data_limited."""
    if percentile is None:
        return {"band": "data_limited", "label": "Insufficient peer data"}
    try:
        p = int(percentile)
    except (TypeError, ValueError):
        return {"band": "data_limited", "label": "Insufficient peer data"}
    if p < 0 or p > 100:
        return {"band": "data_limited", "label": "Insufficient peer data"}
    for upper, band, label in _BAND_THRESHOLDS:
        if p < upper:
            return {"band": band, "label": label}
    return {"band": "data_limited", "label": "Insufficient peer data"}


def _canonical_sector(sector_label: str) -> Optional[str]:
    """Resolve free-form sector → canonical key, or None if unmapped.

    We deliberately do NOT fall back to '_default' — mixing every
    unmapped ticker into one cohort produces noise, not signal.
    """
    if not sector_label:
        return None
    s = str(sector_label).strip()
    if s in sector_benchmarks.SECTOR_BENCHMARK_MAP and s != "_default":
        return s
    canonical = sector_benchmarks.SECTOR_ALIASES.get(s.lower())
    if canonical and canonical in sector_benchmarks.SECTOR_BENCHMARK_MAP:
        return canonical
    return None


def _extract_mos_pct(payload) -> Optional[float]:
    """Pull margin_of_safety out of an analysis_cache payload (dict or JSON str)."""
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except Exception:
            return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if not isinstance(payload, dict):
        return None
    valuation = payload.get("valuation") or {}
    if not isinstance(valuation, dict):
        return None
    raw = valuation.get("margin_of_safety")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _coerce_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _fetch_cohort_rows(canonical_sector: str, db_session) -> list[dict]:
    """Run the cohort query. Latest market_metrics + latest analysis_cache per ticker."""
    sql = text(
        """
        WITH latest_mm AS (
            SELECT DISTINCT ON (mm.ticker)
                mm.ticker, mm.market_cap_cr, mm.pe_ratio, mm.pb_ratio
            FROM market_metrics mm
            ORDER BY mm.ticker, mm.trade_date DESC
        ),
        latest_ac AS (
            SELECT DISTINCT ON (ac.ticker)
                ac.ticker, ac.payload
            FROM analysis_cache ac
            ORDER BY ac.ticker, ac.computed_at DESC
        )
        SELECT s.ticker, lm.market_cap_cr, lm.pe_ratio, lm.pb_ratio, la.payload
        FROM stocks s
        LEFT JOIN latest_mm lm ON lm.ticker = s.ticker
        LEFT JOIN latest_ac la ON la.ticker = s.ticker
        WHERE s.sector = :sector
          AND COALESCE(s.is_active, TRUE) = TRUE
        """
    )
    try:
        rows = db_session.execute(sql, {"sector": canonical_sector}).fetchall()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "sector_percentile: cohort query failed for %s: %s",
            canonical_sector, exc,
        )
        return []

    out: list[dict] = []
    for row in rows:
        try:
            m = row._mapping
            ticker = m["ticker"]
            market_cap_cr = m["market_cap_cr"]
            pe_ratio = m["pe_ratio"]
            pb_ratio = m["pb_ratio"]
            payload = m["payload"]
        except Exception:
            ticker, market_cap_cr, pe_ratio, pb_ratio, payload = row

        if not ticker:
            continue
        mc = _coerce_float(market_cap_cr)
        if mc is None or mc <= _MIN_MARKET_CAP_CR:
            continue

        pe = _coerce_float(pe_ratio)
        pb = _coerce_float(pb_ratio)
        mos = _extract_mos_pct(payload)
        if mos is None and pe is None and pb is None:
            continue

        out.append({
            "ticker":   str(ticker),
            "mos_pct":  mos,
            "pe_ratio": pe,
            "pb_ratio": pb,
        })
    return out


def compute_sector_cohort(sector_label: str, db_session) -> list[dict]:
    """Return [{ticker, mos_pct, pe_ratio, pb_ratio}] for the sector cohort.

    Filters to market_cap_cr > 100. Drops tickers with all three
    metrics None. Cached per canonical sector for 1 hour. Unmapped
    sector_label returns [] without touching the DB.
    """
    canonical = _canonical_sector(sector_label)
    if canonical is None:
        return []

    now = time.time()
    with _cohort_cache_lock:
        hit = _cohort_cache.get(canonical)
        if hit is not None and now - hit[0] < _COHORT_TTL_SECONDS:
            return list(hit[1])

    cohort = _fetch_cohort_rows(canonical, db_session)
    with _cohort_cache_lock:
        _cohort_cache[canonical] = (now, list(cohort))
    return cohort


def _clear_cohort_cache() -> None:
    """Test hook — flush the in-memory cohort cache."""
    with _cohort_cache_lock:
        _cohort_cache.clear()
