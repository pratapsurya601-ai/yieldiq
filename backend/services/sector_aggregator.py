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
        if normalize_sector(c.get("sector")) == sector:
            matched.append(c)

    pillars: dict[str, dict] = {}
    for pillar in _PILLARS:
        scores: list[float] = []
        for c in matched:
            s = _pillar_score(c.get("analysis"), pillar)
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
