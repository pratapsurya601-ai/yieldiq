# backend/services/industry_percentile_service.py
# ═══════════════════════════════════════════════════════════════
# Day-99: industry-relative percentile rankings.
#
# Why: no Indian competitor surfaces percentile context next to a
# pillar score. "Quality 8.5/10" is meaningless without the cohort
# distribution. Putting "75th percentile in IT Services" next to
# the score is the cheapest possible trust-builder — every input
# is already in analysis_cache.
#
# Cohort definition: stocks sharing the same `stocks.industry` (the
# yfinance industry, e.g. "Banks - Private Sector", "IT Services")
# with a fresh analysis_cache row (computed_at within the last 7
# days). Industry is more specific than sector — "Financial
# Services" sector lumps banks + AMCs + insurers + exchanges
# together, which makes cohort comparisons useless.
#
# Metrics: composite "score" plus the 6 hex pillars
# (value/quality/growth/moat/safety/pulse). Pillar scores are
# derived via the canonical pure helper
# `hex_axes.compute_axes_from_payload` so they match the live hex
# render. Composite "score" is read from
# `payload.quality.yieldiq_score` (0-100).
#
# Cache: 6h TTL keyed on canonical-ticker. Industry distributions
# don't shift hour-to-hour and recomputing them per request would
# hit the analysis_cache table once per ticker (cheap, but wasteful
# on warm cohorts where we'd be re-deriving 60+ pillar tuples).
#
# Read-only: no writes anywhere, no CACHE_VERSION dependency, no
# manifest entry. Fair-value for any ticker is unchanged.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from sqlalchemy import text

from backend.services.analysis.hex_axes import compute_axes_from_payload

logger = logging.getLogger("yieldiq.industry_percentile")

# Composite + 6 pillars. The composite "score" lives on the 0-100
# scale (matches yieldiq_score in the response models); the 6
# pillars are on the 0-10 hex scale. Percentile rank is scale-
# invariant so we don't normalise.
SUPPORTED_METRICS: tuple[str, ...] = (
    "score", "value", "quality", "growth", "moat", "safety", "pulse",
)

# Minimum cohort size for a meaningful percentile. Below this we
# return cohort_size + null percentiles + a caveat — never a
# misleading "100th percentile of 3 stocks" number.
MIN_COHORT_SIZE: int = 5

_CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def percentile_rank(value: float, cohort_values: list[float]) -> int:
    """Standard percentile rank (no interpolation), 0-100.

    Defined as the percent of cohort values strictly less than
    `value`. Empty cohort or non-finite `value` returns 0. Matches
    the convention used by `sector_percentile.percentile_rank` so
    callers reasoning across both modules see consistent numbers.
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


def _extract_metrics(payload: dict) -> dict[str, Optional[float]]:
    """Pull the 7 metrics out of an analysis_cache row's payload.

    Pillars come from the canonical pure derivation (cache-row
    shape → 6 axes). Composite score comes from
    `quality.yieldiq_score`. Any missing input is None — the
    caller filters them out of the cohort before ranking.
    """
    out: dict[str, Optional[float]] = {k: None for k in SUPPORTED_METRICS}
    if not isinstance(payload, dict):
        return out
    quality = payload.get("quality") if isinstance(payload, dict) else None
    if isinstance(quality, dict):
        raw = quality.get("yieldiq_score")
        try:
            v = float(raw)
            if v == v:
                out["score"] = v
        except (TypeError, ValueError):
            pass
    try:
        axes = compute_axes_from_payload(payload)
        out["value"] = axes.value
        out["quality"] = axes.quality
        out["growth"] = axes.growth
        out["moat"] = axes.moat
        out["safety"] = axes.safety
        out["pulse"] = axes.pulse
    except Exception as exc:  # pragma: no cover - never raise
        logger.debug("industry_percentile: hex derive failed: %s", exc)
    return out


def _normalise_metrics(metrics: Optional[list[str]]) -> list[str]:
    """Filter the caller's metric list down to supported keys.

    Empty / None → return all supported. Order is preserved so
    response keys mirror the user's query.
    """
    if not metrics:
        return list(SUPPORTED_METRICS)
    seen: set[str] = set()
    out: list[str] = []
    for m in metrics:
        key = (m or "").strip().lower()
        if key in SUPPORTED_METRICS and key not in seen:
            out.append(key)
            seen.add(key)
    return out or list(SUPPORTED_METRICS)


def _fetch_industry(db_session, ticker: str) -> tuple[Optional[str], Optional[str]]:
    """Return (industry, sub_sector_or_sector) for the ticker, or (None, None).

    We prefer `stocks.industry` because it's the granular yfinance
    classification (e.g. "Banks - Private Sector" vs "Banks -
    Regional"). `sector` is returned as a fallback display label
    so callers can render something even when industry is null.

    Fix (audit #5 P0a, 2026-05-22): the `stocks` table stores tickers
    in BARE form (`RELIANCE`) with the `.NS` form in a separate
    `ticker_ns` column. Callers / analysis_cache.ticker keys are
    canonicalized to `.NS` form. Matching `ticker = 'RELIANCE.NS'`
    therefore matched nothing, so every prod lookup returned null
    industry → cohort_size 0 → empty percentiles, even though
    `stocks.industry` is populated for ~75% of the universe.
    Match on `ticker_ns` first, fall back to `ticker` so callers
    passing either form land the same row.
    """
    try:
        row = db_session.execute(
            text(
                "SELECT industry, sector FROM stocks "
                "WHERE ticker_ns = :t OR ticker = :t LIMIT 1"
            ),
            {"t": ticker},
        ).fetchone()
    except Exception as exc:
        logger.warning("industry_percentile: stocks lookup failed for %s: %s", ticker, exc)
        return None, None
    if not row:
        return None, None
    try:
        industry, sector = row[0], row[1]
    except Exception:
        return None, None
    industry = (industry or "").strip() or None
    sector = (sector or "").strip() or None
    return industry, sector


def _fetch_cohort_payloads(
    db_session, industry: str, max_age_days: int = 7,
) -> list[tuple[str, dict]]:
    """Return [(ticker, payload)] for every active ticker in `industry`
    with a fresh analysis_cache row.

    Uses DISTINCT ON to dedupe to one row per ticker (latest by
    computed_at). The 7-day window is loose enough to absorb a
    yfinance hiccup yet tight enough that the cohort reflects the
    current market.
    """
    # Fix (audit #5 P0a, 2026-05-22): join on stocks.ticker_ns since
    # analysis_cache.ticker is canonicalized to `.NS` form while
    # stocks.ticker is the bare form. Return the canonical .NS ticker
    # so the subject-in-cohort match (`tk == t`) in the caller works
    # for tickers passed in as `RELIANCE.NS`.
    sql = text(
        """
        WITH latest_ac AS (
            SELECT DISTINCT ON (ac.ticker)
                ac.ticker, ac.payload, ac.computed_at
            FROM analysis_cache ac
            WHERE ac.computed_at > now() - (:days || ' days')::interval
            ORDER BY ac.ticker, ac.computed_at DESC
        )
        SELECT COALESCE(s.ticker_ns, s.ticker) AS ticker, la.payload
        FROM stocks s
        JOIN latest_ac la ON la.ticker = COALESCE(s.ticker_ns, s.ticker)
        WHERE COALESCE(s.is_active, TRUE) = TRUE
          AND s.industry = :industry
        """
    )
    try:
        rows = db_session.execute(sql, {"industry": industry, "days": str(max_age_days)}).fetchall()
    except Exception as exc:
        logger.warning("industry_percentile: cohort query failed for %s: %s", industry, exc)
        return []
    out: list[tuple[str, dict]] = []
    for r in rows:
        try:
            t = r[0]
            p = r[1]
        except Exception:
            continue
        if not t:
            continue
        if isinstance(p, (bytes, bytearray)):
            try:
                import json as _json
                p = _json.loads(p.decode("utf-8"))
            except Exception:
                continue
        if isinstance(p, str):
            try:
                import json as _json
                p = _json.loads(p)
            except Exception:
                continue
        if not isinstance(p, dict):
            continue
        out.append((str(t), p))
    return out


def compute_industry_percentiles(
    ticker: str,
    db_session,
    metrics: Optional[list[str]] = None,
) -> dict:
    """Public entry point. Returns the API-shape dict.

    Shape on success:
        {ticker, industry, cohort_size, percentiles: {metric: int}}

    Shape on thin cohort (< MIN_COHORT_SIZE):
        {ticker, industry, cohort_size, percentiles: {metric: None},
         caveat: "Cohort too small for a meaningful percentile."}

    Shape when ticker absent / industry unknown:
        {ticker, industry: None, cohort_size: 0,
         percentiles: {metric: None}, caveat: "..."}

    Never raises: any DB problem degrades to the unknown-industry
    shape with a logged warning.
    """
    wanted = _normalise_metrics(metrics)
    t = (ticker or "").strip().upper()
    if not t:
        return {
            "ticker": ticker, "industry": None, "cohort_size": 0,
            "percentiles": {m: None for m in wanted},
            "caveat": "Ticker is empty.",
        }
    industry, sector = _fetch_industry(db_session, t)
    if not industry:
        return {
            "ticker": t, "industry": sector,
            "cohort_size": 0,
            "percentiles": {m: None for m in wanted},
            "caveat": "Industry classification missing for this ticker.",
        }
    pairs = _fetch_cohort_payloads(db_session, industry)
    cohort_size = len(pairs)

    # Extract the subject's metrics from the cohort (or fetch directly).
    subject_metrics: dict[str, Optional[float]] = {m: None for m in SUPPORTED_METRICS}
    cohort_metrics: dict[str, list[float]] = {m: [] for m in SUPPORTED_METRICS}
    for tk, payload in pairs:
        extracted = _extract_metrics(payload)
        if tk == t:
            subject_metrics = extracted
        for m in SUPPORTED_METRICS:
            v = extracted.get(m)
            if v is not None:
                cohort_metrics[m].append(v)

    # If the subject wasn't in the fresh cohort, try the subject directly
    # so it can still get an (out-of-cohort) percentile reading. We do
    # NOT add it to the cohort — that would skew the distribution.
    if all(v is None for v in subject_metrics.values()):
        try:
            row = db_session.execute(
                text(
                    "SELECT payload FROM analysis_cache "
                    "WHERE ticker = :t ORDER BY computed_at DESC LIMIT 1"
                ),
                {"t": t},
            ).fetchone()
            if row:
                p = row[0]
                if isinstance(p, (bytes, bytearray)):
                    import json as _json
                    p = _json.loads(p.decode("utf-8"))
                if isinstance(p, str):
                    import json as _json
                    p = _json.loads(p)
                if isinstance(p, dict):
                    subject_metrics = _extract_metrics(p)
        except Exception as exc:
            logger.debug("industry_percentile: subject fetch failed for %s: %s", t, exc)

    if cohort_size < MIN_COHORT_SIZE:
        return {
            "ticker": t, "industry": industry,
            "cohort_size": cohort_size,
            "percentiles": {m: None for m in wanted},
            "caveat": (
                f"Only {cohort_size} peer(s) in {industry} have fresh "
                f"data — need at least {MIN_COHORT_SIZE} for a "
                f"meaningful percentile."
            ),
        }

    percentiles: dict[str, Optional[int]] = {}
    for m in wanted:
        sv = subject_metrics.get(m)
        cohort = cohort_metrics.get(m) or []
        if sv is None or len(cohort) < MIN_COHORT_SIZE:
            percentiles[m] = None
            continue
        percentiles[m] = percentile_rank(sv, cohort)

    return {
        "ticker": t,
        "industry": industry,
        "cohort_size": cohort_size,
        "percentiles": percentiles,
    }


def get_cached_percentiles(
    ticker: str,
    db_session,
    metrics: Optional[list[str]] = None,
) -> dict:
    """6-hour in-process cache wrapper around `compute_industry_percentiles`.

    Cache key is (canonical-ticker, sorted requested metric tuple)
    so callers asking for different metric subsets get independent
    entries. The cache is in-process (single-worker scope) which is
    fine for the read-only nature of this data — process restarts
    rebuild it lazily.
    """
    wanted = _normalise_metrics(metrics)
    t = (ticker or "").strip().upper()
    key = t + "|" + ",".join(sorted(wanted))
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
            return dict(hit[1])
    payload = compute_industry_percentiles(t, db_session, wanted)
    with _cache_lock:
        _cache[key] = (now, dict(payload))
    return payload


def _clear_cache() -> None:
    """Test hook — flush the in-memory cache."""
    with _cache_lock:
        _cache.clear()
