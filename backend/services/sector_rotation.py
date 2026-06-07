# backend/services/sector_rotation.py
# ═══════════════════════════════════════════════════════════════
# Sector rotation lens — cross-sector aggregation.
#
# Builds a single payload that ranks the Day-108c sector cohorts
# by their median margin-of-safety (MoS%), so the marketing surface
# /sector-rotation can render a heatmap-style "where in the cohort
# universe is the model pricing fundamentals at a discount today".
#
# This module is a pure aggregator over the existing per-sector
# landing-page aggregator (`_sector_page_aggregate` in routers/public.py)
# — it MUST NOT mutate any FV math, change verdict thresholds, or
# touch CACHE_VERSION. Read-only, derivative compute.
#
# Output shape (build_sector_rotation)
# ------------------------------------
#   {
#       "sectors": [
#           {
#               "slug": str,
#               "display_name": str,
#               "ticker_count": int,
#               "median_mos_pct": float | None,
#               "median_fv_to_price_ratio": float | None,
#               "median_score": float | None,
#               "verdict_distribution": {
#                   "undervalued": int,
#                   "fairly_valued": int,
#                   "overvalued": int,
#                   "other": int | absent,
#               },
#               "pct_undervalued": float | None,   # 0..100
#               "top_discounts": [                  # up to 3 tickers
#                   {"ticker": str, "name": str,
#                    "mos_pct": float, "verdict": str | None},
#                   ...
#               ],
#           },
#           ...
#       ],
#       "ranked_slugs": [str, ...],     # sectors sorted by median MoS desc
#       "computed_at": str,             # ISO-8601 UTC
#       "universe_ticker_count": int,   # sum of ticker_count across sectors
#       "notes": str,                   # SEBI-safe disclosure
#   }
#
# Ranking
# -------
# Sectors are sorted by median_mos_pct descending (most-discounted
# first). Sectors with median_mos_pct == None sort to the bottom in
# their original Day-108c slug order — they're "insufficient data",
# not "fully valued", and conflating them would mislead the heatmap.
#
# Disclosure
# ----------
# This is a *model-output* ranking, not a buy list. The notes string
# below is bolted onto the payload so any downstream consumer
# (frontend, JSON API client, email digest) carries the disclaimer.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.services.sector_pages import SECTOR_PAGE_SLUGS, get_cohort

logger = logging.getLogger("yieldiq.sector_rotation")


# How many "most discounted" tickers to surface per sector. 3 is
# enough to anchor the user on concrete names without turning the
# rotation card into a screen result. Larger numbers belong on the
# per-sector landing page.
_TOP_DISCOUNTS_PER_SECTOR = 3


# SEBI-safe disclosure. Descriptive, not advisory. Surfaced as-is
# on /sector-rotation and any downstream consumer.
ROTATION_DISCLOSURE = (
    "Sector rankings reflect the YieldIQ model's current margin-of-safety "
    "estimate over each cohort's constituents. Medians are computed daily "
    "from cached analyses and exclude tickers without a current score. "
    "This is a descriptive snapshot of where the model is pricing "
    "fundamentals at a discount today — not a recommendation to buy or "
    "sell any sector or ticker."
)


def _pct_undervalued(verdict_distribution: dict) -> Optional[float]:
    """Return the percentage of in-cohort tickers tagged 'undervalued'.

    None when the cohort is empty — distinguishes "no data" from
    "0% undervalued" in the UI. The denominator includes every verdict
    seen (including 'other'), so the headline number is honest about
    cohort size, not just the three named buckets.
    """
    if not isinstance(verdict_distribution, dict):
        return None
    total = sum(int(v) for v in verdict_distribution.values() if isinstance(v, int))
    if total <= 0:
        return None
    under = int(verdict_distribution.get("undervalued") or 0)
    return round((under / total) * 100.0, 1)


def _top_discounts(tickers: list[dict], k: int) -> list[dict]:
    """Pick the k tickers in `tickers` with the largest positive MoS.

    "Discount" here means the model's fair value is above the current
    price — i.e. positive MoS%. Tickers without a MoS or with MoS<=0
    are filtered out so the surface never advertises an overvalued
    name as "most discounted". Stable sort by ticker as the tie-break
    so the same input produces the same output across runs.
    """
    candidates: list[dict] = []
    for r in tickers or []:
        if not isinstance(r, dict):
            continue
        mos = r.get("mos_pct")
        if mos is None:
            continue
        try:
            mos_f = float(mos)
        except (TypeError, ValueError):
            continue
        if mos_f <= 0:
            continue
        candidates.append({
            "ticker": r.get("ticker"),
            "name": r.get("name"),
            "mos_pct": round(mos_f, 1),
            "verdict": r.get("verdict"),
        })
    # Sort by mos_pct desc, ticker asc as tie-break.
    candidates.sort(key=lambda x: (-x["mos_pct"], str(x.get("ticker") or "")))
    return candidates[:k]


def _summarise_one_sector(slug: str, sector_payload: dict) -> dict:
    """Compact one sector landing-page payload into a rotation row.

    sector_payload is the dict returned by `_sector_page_aggregate`
    (Day-108c landing-page payload). We only need a subset of its
    fields. Defensive against missing keys — never raise on a sector
    with partial data; surface what we have and let the UI render the
    rest as "—".
    """
    aggregates = sector_payload.get("aggregates") or {}
    verdict_distribution = aggregates.get("verdict_distribution") or {}
    tickers = sector_payload.get("tickers") or []
    return {
        "slug": slug,
        "display_name": sector_payload.get("display_name") or slug,
        "ticker_count": int(aggregates.get("ticker_count") or 0),
        "median_mos_pct": aggregates.get("median_mos_pct"),
        "median_fv_to_price_ratio": aggregates.get("median_fair_value_to_price_ratio"),
        "median_score": aggregates.get("median_score"),
        "verdict_distribution": verdict_distribution,
        "pct_undervalued": _pct_undervalued(verdict_distribution),
        "top_discounts": _top_discounts(tickers, _TOP_DISCOUNTS_PER_SECTOR),
    }


def _rank_sectors(sectors: list[dict]) -> list[str]:
    """Return slugs sorted by median_mos_pct desc.

    Sectors with median_mos_pct == None are appended at the end in
    their original Day-108c slug order. This is deliberate: a sector
    with insufficient constituents in cache should not be confused
    with a sector trading at fair value (which has a real, near-zero
    median MoS). Tie-break on slug to keep ordering deterministic
    when two sectors happen to median to the same MoS.
    """
    with_data: list[dict] = []
    without_data: list[dict] = []
    for s in sectors:
        if s.get("median_mos_pct") is None:
            without_data.append(s)
        else:
            with_data.append(s)
    with_data.sort(
        key=lambda x: (-float(x["median_mos_pct"]), str(x.get("slug") or ""))
    )
    return [s["slug"] for s in with_data] + [s["slug"] for s in without_data]


def build_sector_rotation(
    sector_aggregator: Callable[[str], Optional[dict]],
    slugs: tuple[str, ...] = SECTOR_PAGE_SLUGS,
) -> dict:
    """Aggregate all cohort slugs into a single rotation payload.

    Parameters
    ----------
    sector_aggregator : callable
        Function `slug -> dict | None` matching the signature of
        `_sector_page_aggregate` in routers/public.py. Passed in
        rather than imported so tests can stub the cohort source
        without spinning up a FastAPI test client or the full
        analysis_cache stack.
    slugs : tuple[str, ...]
        Slugs to iterate. Defaults to the Day-108c canonical set.
        Tests may pass a subset.

    Returns
    -------
    dict — see module docstring for the schema.
    """
    sectors: list[dict] = []
    for slug in slugs:
        if get_cohort(slug) is None:
            # Defensive — caller passed a slug not in our cohort table.
            # Skip rather than raise so the lens still renders the
            # known sectors.
            logger.warning("sector_rotation: unknown slug skipped: %s", slug)
            continue
        try:
            sp = sector_aggregator(slug)
        except Exception as exc:
            logger.warning(
                "sector_rotation: aggregator failed for %s: %s", slug, exc
            )
            sp = None
        if sp is None:
            # Cohort exists but aggregator returned nothing (very rare —
            # the per-sector aggregator returns None only on unknown
            # slug, which we already gated). Surface an empty card so
            # the UI shows the sector with "insufficient data".
            cohort = get_cohort(slug) or {}
            sectors.append({
                "slug": slug,
                "display_name": cohort.get("display_name") or slug,
                "ticker_count": 0,
                "median_mos_pct": None,
                "median_fv_to_price_ratio": None,
                "median_score": None,
                "verdict_distribution": {
                    "undervalued": 0,
                    "fairly_valued": 0,
                    "overvalued": 0,
                },
                "pct_undervalued": None,
                "top_discounts": [],
            })
            continue
        sectors.append(_summarise_one_sector(slug, sp))

    ranked = _rank_sectors(sectors)
    universe_count = sum(int(s.get("ticker_count") or 0) for s in sectors)

    return {
        "sectors": sectors,
        "ranked_slugs": ranked,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "universe_ticker_count": universe_count,
        "notes": ROTATION_DISCLOSURE,
    }
