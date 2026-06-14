# backend/services/sector_aggregator.py
# ═══════════════════════════════════════════════════════════════
# Sector Prism aggregator — builds a sector-level "Prism" from the
# per-ticker analyses of every constituent in the canonical sector.
#
# Output shape (build_sector_prism)
# ---------------------------------
#   {
#       "sector":        str,                # canonical name
#       "slug":          str,
#       "constituent_count": int,
#       "pillars": {
#           "value":   {"median": float|None, "dispersion": float|None, "n": int},
#           "quality": {...},
#           "growth":  {...},
#           "moat":    {...},
#           "safety":  {...},
#           "pulse":   {...},
#       },
#       "verdict":        "undervalued" | "fair" | "overvalued" | "insufficient",
#       "verdict_reason": str,
#   }
#
# Verdict thresholds (from spec)
# ------------------------------
# Compute   x = median(value pillar) * 10
#   x < 30  → "overvalued"
#   x > 70  → "undervalued"
#   else    → "fair"
#
# (Pillar scores are stored on a 0-10 scale; multiplying by 10
# gives the percentile-ish number the UI surfaces. The "value"
# pillar is the sector value-vs-history score from the Hex.)
#
# Data discipline
# ---------------
#  - Constituents are matched by `normalize_sector(stock.sector) == sector`.
#  - A pillar's median is None when fewer than 3 tickers in the sector
#    have a real (non-None) score for that pillar — small-N medians
#    on a 0-10 scale are noise, and the UI should render "n/a" rather
#    than a fake number.
#  - Verdict is "insufficient" when value-pillar n < 3.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
from typing import Optional

from backend.services.sector_taxonomy import (
    normalize_sector,
    sector_slug,
)

logger = logging.getLogger("yieldiq.sector_aggregator")

# Pillar key order — matches prism_service. The aggregator iterates
# this list when building the response so the dict key order is
# stable for downstream JSON consumers.
_PILLARS: tuple[str, ...] = ("value", "quality", "growth", "moat", "safety", "pulse")

# Minimum constituents-with-score required to publish a pillar median
# or compute a verdict. Below this, the cohort is too small for the
# median to be meaningful. Tuned to 3 to keep niche sectors (e.g.
# Media, sometimes only 4-5 listed names) addressable.
_MIN_N_FOR_MEDIAN = 3


def _median(xs: list[float]) -> Optional[float]:
    """Median of a list of floats, or None if empty."""
    if not xs:
        return None
    return float(statistics.median(xs))


def _dispersion(xs: list[float]) -> Optional[float]:
    """Population std-dev as a dispersion proxy.

    Returns None for n<2. We use population (pstdev) rather than
    sample stdev because the cohort IS the population for this
    sector — there is no larger universe to estimate from.
    """
    if len(xs) < 2:
        return None
    return float(statistics.pstdev(xs))


def _pillar_score(analysis: dict, pillar: str) -> Optional[float]:
    """Extract a single pillar's 0-10 score from a per-ticker analysis.

    The analysis payload follows the Hex/Prism contract:
        analysis["hex"]["axes"][pillar]["score"]  (0-10 float)

    Returns None when the pillar is missing, the score is None,
    or the structure is malformed. Aggregator skips Nones — a
    missing pillar must not poison the median.

    NOTE: the per-ticker `analysis` passed in by the production router
    is the raw `analysis_cache.payload`, which does NOT carry a "hex"
    key (the 6-axis hex is computed live by hex_service, never stored).
    `build_sector_prism` therefore injects a freshly-computed hex into
    each constituent's analysis (see `_axes_for_constituent`) before
    this function is called. This function itself stays a pure reader of
    the `["hex"]["axes"]` contract so the in-memory aggregator unit
    tests (which supply hex inline) keep exercising the same path.
    """
    if not isinstance(analysis, dict):
        return None
    hex_payload = analysis.get("hex")
    if not isinstance(hex_payload, dict):
        return None
    axes = hex_payload.get("axes")
    if not isinstance(axes, dict):
        return None
    axis = axes.get(pillar)
    if not isinstance(axis, dict):
        return None
    score = axis.get("score")
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _has_usable_hex(analysis: dict) -> bool:
    """True when `analysis` already carries at least one real pillar score.

    Used to decide whether we can read the hex straight off the supplied
    payload (the aggregator unit-test path, and any future writer that
    starts persisting hex) or whether we must compute it live. We treat
    a hex with *any* non-None pillar score as usable — a single lit axis
    is enough to prefer the supplied data over a re-compute.
    """
    if not isinstance(analysis, dict):
        return False
    hex_payload = analysis.get("hex")
    if not isinstance(hex_payload, dict):
        return False
    axes = hex_payload.get("axes")
    if not isinstance(axes, dict):
        return False
    for axis in axes.values():
        if isinstance(axis, dict) and axis.get("score") is not None:
            return True
    return False


def _axes_for_constituent(constituent: dict) -> dict:
    """Return a per-ticker `analysis` dict guaranteed to carry a hex.

    Resolution order:
      1. If the supplied analysis ALREADY has a usable hex (any lit
         pillar score), return it unchanged — cheap, no DB hit. This is
         the path the in-memory unit tests and any future hex-persisting
         writer take.
      2. Otherwise compute the hex live via
         `hex_service.compute_hex_safe(ticker)` and graft its `axes`
         (plus `overall`) onto a shallow copy of the analysis so
         `_pillar_score` can read the standard `["hex"]["axes"]` path.

    Why live compute is acceptable here: the 6-axis hex is derived
    on the read side (it blends analysis_cache + market_metrics +
    financials + the live sector cohort + pulse inputs) and is NEVER
    written into analysis_cache.payload. The stored payload genuinely
    lacks pillar scores, so reading them is impossible without
    recomputing. The /sectors/{slug}/prism endpoint caches its whole
    response for 1h (see routers/sectors.py `_SECTOR_CACHE_TTL`), so
    the per-constituent hex compute runs at most once per sector per
    hour — a tolerable cost for an aggregate page. The trade-off is a
    cold-cache request that fans N constituents × ~1 hex compute each;
    bounded by the cohort size (≤ ~200) and amortised by the cache.

    `compute_hex_safe` NEVER raises and always returns an `axes` dict
    (data_limited axes carry score=None), so a single bad ticker can't
    break the aggregate — its null pillars simply don't contribute to
    the medians, exactly like a missing stored score would.
    """
    analysis = constituent.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}

    if _has_usable_hex(analysis):
        return analysis

    ticker = constituent.get("ticker")
    if not ticker:
        # No ticker → can't compute live. Return as-is; every pillar
        # will read None and this constituent won't poison the median.
        return analysis

    try:
        # Local import keeps cold-start fast and avoids a hard module
        # dependency for the in-memory unit tests that never hit this path.
        from backend.services import hex_service

        hex_payload = hex_service.compute_hex_safe(ticker)
    except Exception as exc:  # pragma: no cover - defensive; compute_hex_safe is no-raise
        logger.warning(
            "sector_aggregator: live hex compute failed for %s: %s",
            ticker, exc,
        )
        return analysis

    if not isinstance(hex_payload, dict) or not isinstance(
        hex_payload.get("axes"), dict
    ):
        return analysis

    # Graft the computed hex onto a shallow copy so we never mutate the
    # caller's payload (it may be a shared/cached object).
    merged = dict(analysis)
    merged["hex"] = {
        "axes": hex_payload.get("axes"),
        "overall": hex_payload.get("overall"),
    }
    return merged


def _verdict_from_value_median(value_median: Optional[float], n: int) -> tuple[str, str]:
    """Compute (verdict, reason) from the value-pillar median.

    See module docstring for thresholds. `n` is the constituent
    count that contributed to the median — used both to gate the
    insufficient-data path and to produce a human reason string.
    """
    if value_median is None or n < _MIN_N_FOR_MEDIAN:
        return (
            "insufficient",
            f"Only {n} constituent(s) with a value score — need {_MIN_N_FOR_MEDIAN}+ for a sector verdict.",
        )
    x = value_median * 10.0
    if x < 30.0:
        return (
            "overvalued",
            f"Sector value score median {value_median:.1f}/10 (×10 = {x:.0f}) below 30 — priced above history.",
        )
    if x > 70.0:
        return (
            "undervalued",
            f"Sector value score median {value_median:.1f}/10 (×10 = {x:.0f}) above 70 — discounted vs history.",
        )
    return (
        "fair",
        f"Sector value score median {value_median:.1f}/10 (×10 = {x:.0f}) in 30–70 fair-value band.",
    )


def build_sector_prism(
    sector: str,
    constituents: list[dict],
) -> dict:
    """Aggregate per-ticker analyses into a sector-level Prism.

    Parameters
    ----------
    sector : str
        Canonical sector name (must match CANONICAL_SECTORS — the
        router enforces this via sector_from_slug). The aggregator
        filters `constituents` so only stocks whose normalized sector
        matches are included; any with a different sector are dropped.
    constituents : list[dict]
        Each item: {"ticker": str, "sector": str|None, "analysis": dict}.
        Empty list → returns the "insufficient" baseline.

    Returns
    -------
    dict — see module docstring for the schema.
    """
    # Filter to constituents that actually belong to this sector.
    # An upstream caller might pass a broader pool (e.g. all NSE
    # stocks) and rely on us to slice — that's the intended pattern
    # so the router doesn't have to know about normalize_sector.
    matched: list[dict] = []
    for c in constituents or []:
        if not isinstance(c, dict):
            continue
        # Prefer the migration 035 canonical_sector column when the
        # caller passed it through; fall back to normalize_sector() on
        # the raw label for legacy callers / older cache payloads that
        # predate the canonical backfill.
        canon = c.get("canonical_sector")
        if not canon:
            canon = normalize_sector(c.get("sector"))
        if canon == sector:
            matched.append(c)

    # Ensure every matched constituent's `analysis` carries a hex before
    # we read pillar scores. The stored analysis_cache.payload has NO
    # "hex" key (the 6-axis hex is computed live, never persisted), so
    # without this each `_pillar_score` would read None and every pillar
    # would collapse to n=0 / median=None — the prod bug this fixes. The
    # in-memory unit-test path (analysis already carries a hex) is a
    # no-op here. See `_axes_for_constituent` for the perf trade-off.
    enriched: list[dict] = [_axes_for_constituent(c) for c in matched]

    pillars: dict[str, dict] = {}
    for pillar in _PILLARS:
        scores: list[float] = []
        for analysis in enriched:
            s = _pillar_score(analysis, pillar)
            if s is not None:
                scores.append(s)
        n = len(scores)
        if n < _MIN_N_FOR_MEDIAN:
            pillars[pillar] = {"median": None, "dispersion": None, "n": n}
        else:
            pillars[pillar] = {
                "median": _median(scores),
                "dispersion": _dispersion(scores),
                "n": n,
            }

    value_block = pillars["value"]
    verdict, reason = _verdict_from_value_median(value_block["median"], value_block["n"])

    return {
        "sector": sector,
        "slug": sector_slug(sector),
        "constituent_count": len(matched),
        "pillars": pillars,
        "verdict": verdict,
        "verdict_reason": reason,
    }
