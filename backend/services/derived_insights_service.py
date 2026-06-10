# backend/services/derived_insights_service.py
"""
T5.3 (2026-06-10) — Derived insights service.

YieldIQ accumulated a lot of rich data: composite IV from 7
estimators, 5 confidence pillars, bear/base/bull scenarios, sector
calibration, liquidation/replacement anchors, etc. Users get
OVERWHELMED. Derived insights are the antidote: take the rich data,
output 4 clear "look at this" callouts.

The four insights:

1. **Confidence summary** — synthesizes the 5 confidence pillars
   (data_quality, model_confidence, valuation_stability,
   sensitivity, composite_agreement) into one headline ("YieldIQ
   HIGHLY CONFIDENT") plus a per-pillar breakdown.

2. **Estimator clustering** — how tightly the composite IV
   constituents (DCF, Multiples, Wall Street, Three-stage, DDM,
   EPV, Probability-weighted) cluster around their median. The
   headline reports "N of M estimators cluster within X% of ₹Y".

3. **Floor + ceiling anchor** — where the Graham liquidation floor
   and the Tobin replacement-cost ceiling sit vs. the live price
   and the engine's DCF/composite. Flags distress when the price
   sits below the liquidation floor.

4. **Sector calibration** — how accurate YieldIQ has been
   historically in this stock's sector (median |error|, direction
   accuracy, observation count). Sourced from PR #790
   ``backtest_publisher.compute_sector_calibration``.

═══════════════════════════════════════════════════════════════
SEBI vocab posture
═══════════════════════════════════════════════════════════════
Every headline / level / detail string is descriptive — counts,
percentages, confidence levels, factual anchors. No advisory
vocabulary (no buy/sell/hold/recommend/should/cheap/expensive/
appears/undervalued/etc). The frontend mirrors this discipline.

═══════════════════════════════════════════════════════════════
Defensive posture
═══════════════════════════════════════════════════════════════
Every function:
  * Never raises — bad inputs return None for that insight.
  * Treats missing / non-finite numerics as absent (None).
  * Pure derivation — no DB / cache / I/O. Sector calibration uses
    an injectable provider so the request path can keep it cached
    upstream.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from typing import Any, Callable, Optional

log = logging.getLogger("yieldiq.derived_insights")


# ─────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────
@dataclass
class ConfidenceSummaryInsight:
    """Synthesis of the 5 confidence pillars into one headline.

    overall_level    — one of:
        "very_high"  (>= 85)
        "high"       (70..84)
        "moderate"   (50..69)
        "low"        (30..49)
        "very_low"   (< 30)
    overall_score    — 0..100 (mean of the present pillars).
    pillar_breakdown — dict of slot -> {"score": int, "label": str}.
    headline         — human-readable lead string.
    pillars_present  — int 1..5; how many of the 5 pillars carry
                       a value on this payload.
    """

    overall_level: str
    overall_score: int
    pillar_breakdown: dict
    headline: str
    pillars_present: int


@dataclass
class EstimatorClusteringInsight:
    """How tightly the composite IV constituents cluster.

    cluster_center    — median value across the active estimators.
    cluster_count     — number of estimators within ``cluster_pct``
                        of the cluster center.
    total_estimators  — number of active estimators (composite
                        components with a finite positive value).
    cluster_pct       — the proximity band used (15.0 by default).
    estimator_details — list of dicts ``{"name": str, "value": float,
                        "delta_pct": float, "in_cluster": bool}``.
    headline          — "N of M estimators cluster within X% of ₹Y".
    """

    cluster_center: float
    cluster_count: int
    total_estimators: int
    cluster_pct: float
    estimator_details: list[dict]
    headline: str


@dataclass
class FloorCeilingInsight:
    """Floor + ceiling anchor framing.

    Distress is flagged when price is below the liquidation floor.

    liquidation_per_share / replacement_per_share / dcf_fv /
    composite_iv are Optional — the headline composes from whichever
    fields are present.
    """

    liquidation_per_share: Optional[float]
    replacement_per_share: Optional[float]
    current_price: float
    dcf_fv: Optional[float]
    composite_iv: Optional[float]
    floor_distance_pct: Optional[float]
    ceiling_distance_pct: Optional[float]
    headline: str
    distress_flag: bool


@dataclass
class SectorCalibrationInsight:
    """Historical YieldIQ accuracy for this stock's sector.

    Sourced from backend.services.backtest_publisher (PR #790).
    The provider is injectable so the request path can supply a
    pre-cached result rather than re-querying on every analysis.
    """

    sector: str
    median_abs_error_pct: Optional[float]
    direction_accuracy_pct: Optional[float]
    observation_count: Optional[int]
    headline: str


@dataclass
class DerivedInsights:
    """Bundle of all four insights. Each slot is Optional."""

    confidence_summary: Optional[ConfidenceSummaryInsight] = None
    estimator_clustering: Optional[EstimatorClusteringInsight] = None
    floor_ceiling: Optional[FloorCeilingInsight] = None
    sector_calibration: Optional[SectorCalibrationInsight] = None


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _safe_float(v: Any) -> Optional[float]:
    """Coerce to a finite float; otherwise None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _safe_pos_float(v: Any) -> Optional[float]:
    """Like _safe_float but rejects values <= 0."""
    f = _safe_float(v)
    if f is None or f <= 0:
        return None
    return f


def _safe_int_score(v: Any) -> Optional[int]:
    """Coerce a 0..100 score to a clamped int; otherwise None."""
    f = _safe_float(v)
    if f is None:
        return None
    if f < 0:
        return 0
    if f > 100:
        return 100
    return int(round(f))


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ─────────────────────────────────────────────────────────────────
# Insight 1 — confidence summary
# ─────────────────────────────────────────────────────────────────

# Bucketing thresholds — single source of truth.
_LEVEL_VERY_HIGH = 85
_LEVEL_HIGH = 70
_LEVEL_MODERATE = 50
_LEVEL_LOW = 30
# (below _LEVEL_LOW -> very_low)


def _level_for_score(score: int) -> str:
    """Map 0..100 score to a 5-bucket confidence level string."""
    if score >= _LEVEL_VERY_HIGH:
        return "very_high"
    if score >= _LEVEL_HIGH:
        return "high"
    if score >= _LEVEL_MODERATE:
        return "moderate"
    if score >= _LEVEL_LOW:
        return "low"
    return "very_low"


# Human-readable phrase for each level. Uses confidence vocabulary
# only — no SEBI-banned advisory words.
_LEVEL_PHRASES: dict[str, str] = {
    "very_high": "YieldIQ is VERY HIGHLY confident in this valuation",
    "high": "YieldIQ is HIGHLY confident in this valuation",
    "moderate": "YieldIQ has MODERATE confidence in this valuation",
    "low": "YieldIQ has LOW confidence in this valuation",
    "very_low": "YieldIQ has VERY LOW confidence in this valuation",
}


# Pillar slot -> display label (mirrors backend/services/confidence_service.py).
_PILLAR_LABELS: dict[str, str] = {
    "data_quality": "Data quality",
    "model_fit": "Model fit",
    "stability": "Stability",
    "sensitivity": "Sensitivity",
    "estimator_agreement": "Estimator agreement",
}


def compute_confidence_summary(scores: dict) -> Optional[ConfidenceSummaryInsight]:
    """Synthesize the 5 confidence pillars into one headline insight.

    ``scores`` is a free-form dict where the canonical keys
    correspond to the slots on AnalysisResponse:
        data_quality        <- data_quality_score
        model_fit           <- model_confidence_score
        stability           <- valuation_stability_score
        sensitivity         <- confidence_sensitivity
        estimator_agreement <- confidence_composite_agreement

    Missing / non-numeric pillars are skipped. Returns None when
    NO pillar carries a finite score (legacy cached payloads).
    """
    if not isinstance(scores, dict):
        return None
    breakdown: dict[str, dict] = {}
    present: list[int] = []
    for slot, label in _PILLAR_LABELS.items():
        sc = _safe_int_score(scores.get(slot))
        if sc is None:
            continue
        breakdown[slot] = {"score": sc, "label": label}
        present.append(sc)
    if not present:
        return None
    overall = int(round(sum(present) / len(present)))
    level = _level_for_score(overall)
    headline = _LEVEL_PHRASES[level]
    return ConfidenceSummaryInsight(
        overall_level=level,
        overall_score=overall,
        pillar_breakdown=breakdown,
        headline=headline,
        pillars_present=len(present),
    )


# ─────────────────────────────────────────────────────────────────
# Insight 2 — estimator clustering
# ─────────────────────────────────────────────────────────────────

# Default proximity band — 15% of the cluster center matches the
# spec example. Tunable via the function signature; the manifest
# entry mentions 15% so this stays the public number.
_DEFAULT_CLUSTER_PCT = 15.0

# Friendly label for each estimator slot in composite_components.
_ESTIMATOR_LABELS: dict[str, str] = {
    "dcf": "DCF",
    "multiples": "Multiples",
    "analyst": "Wall Street",
    "three_stage": "Three-stage",
    "ddm": "DDM",
    "epv": "EPV",
    "probability_weighted": "Probability-weighted",
}


def compute_estimator_clustering(
    composite_components: Optional[dict],
    *,
    cluster_pct: float = _DEFAULT_CLUSTER_PCT,
) -> Optional[EstimatorClusteringInsight]:
    """Surface how tightly the composite IV constituents cluster.

    ``composite_components`` is the dict from
    ``composite_iv_service.composite_to_dict`` (also the shape on
    the AnalysisResponse field). Two accepted shapes:
        {"components": {<slot>: {"value": float, "weight": float}}}
        {<slot>: {"value": float, "weight": float}}

    Anything else (None, non-dict, empty components) -> None.
    Singletons (1 estimator) -> None: clustering of one is undefined.
    """
    if not isinstance(composite_components, dict):
        return None
    # Accept both wrapped (components-key) and flat shapes.
    raw_components = composite_components.get("components")
    if not isinstance(raw_components, dict):
        raw_components = composite_components
    # Extract finite positive values per known slot.
    estimators: list[tuple[str, float]] = []
    for slot, comp in raw_components.items():
        if slot not in _ESTIMATOR_LABELS:
            continue
        if not isinstance(comp, dict):
            continue
        val = _safe_pos_float(comp.get("value"))
        if val is None:
            continue
        estimators.append((slot, val))
    if len(estimators) < 2:
        return None
    values = [v for _, v in estimators]
    center = _median(values)
    if center is None or center <= 0:
        return None
    # Per-estimator delta vs the center.
    details: list[dict] = []
    cluster_count = 0
    for slot, val in estimators:
        delta_pct = (val - center) / center * 100.0
        in_cluster = abs(delta_pct) <= cluster_pct
        if in_cluster:
            cluster_count += 1
        details.append(
            {
                "name": _ESTIMATOR_LABELS[slot],
                "slot": slot,
                "value": round(val, 2),
                "delta_pct": round(delta_pct, 1),
                "in_cluster": in_cluster,
            }
        )
    headline = (
        f"{cluster_count} of {len(estimators)} estimators cluster "
        f"within {int(round(cluster_pct))}% of {round(center, 2)}"
    )
    return EstimatorClusteringInsight(
        cluster_center=round(center, 2),
        cluster_count=cluster_count,
        total_estimators=len(estimators),
        cluster_pct=cluster_pct,
        estimator_details=details,
        headline=headline,
    )


# ─────────────────────────────────────────────────────────────────
# Insight 3 — floor + ceiling anchor
# ─────────────────────────────────────────────────────────────────

def _format_distance_pct(delta_pct: float) -> str:
    """Format a signed % delta with direction word ("above"/"below")."""
    abs_pct = abs(delta_pct)
    if delta_pct >= 0:
        return f"{abs_pct:.0f}% above"
    return f"{abs_pct:.0f}% below"


def compute_floor_ceiling(
    liquidation: Optional[float],
    replacement: Optional[float],
    current_price: float,
    dcf: Optional[float],
    composite: Optional[float],
) -> Optional[FloorCeilingInsight]:
    """Compose the floor + ceiling anchor insight.

    Distress flag fires when the live price sits below the
    liquidation floor.

    Returns None when current_price is unusable AND no floor /
    ceiling anchor is available — there is nothing to anchor against.
    """
    price = _safe_pos_float(current_price)
    liq = _safe_pos_float(liquidation)
    rep = _safe_pos_float(replacement)
    dcf_v = _safe_pos_float(dcf)
    comp_v = _safe_pos_float(composite)
    # If neither anchor exists, the insight has nothing to say.
    if liq is None and rep is None:
        return None
    if price is None:
        return None
    floor_distance_pct: Optional[float] = None
    ceiling_distance_pct: Optional[float] = None
    distress = False
    parts: list[str] = []
    if liq is not None:
        # Distance from FLOOR (price vs. liquidation).
        delta = (price - liq) / liq * 100.0
        floor_distance_pct = round(delta, 1)
        if price < liq:
            distress = True
            parts.append(
                f"Distress signal — price trades {_format_distance_pct(delta)} "
                f"liquidation floor of {round(liq, 2)}"
            )
        else:
            parts.append(
                f"Floor support: {round(liq, 2)} "
                f"({_format_distance_pct(-abs(delta))} price)"
            )
    if rep is not None:
        # Distance from CEILING (price vs. replacement).
        delta = (price - rep) / rep * 100.0
        ceiling_distance_pct = round(delta, 1)
        parts.append(
            f"Replacement cost: {round(rep, 2)} "
            f"({_format_distance_pct(delta)} price)"
        )
    headline = ". ".join(parts) + "."
    return FloorCeilingInsight(
        liquidation_per_share=round(liq, 2) if liq is not None else None,
        replacement_per_share=round(rep, 2) if rep is not None else None,
        current_price=round(price, 2),
        dcf_fv=round(dcf_v, 2) if dcf_v is not None else None,
        composite_iv=round(comp_v, 2) if comp_v is not None else None,
        floor_distance_pct=floor_distance_pct,
        ceiling_distance_pct=ceiling_distance_pct,
        headline=headline,
        distress_flag=distress,
    )


# ─────────────────────────────────────────────────────────────────
# Insight 4 — sector calibration
# ─────────────────────────────────────────────────────────────────

# Provider signature: (sector_name) -> Optional[dict] with keys
# ``median_abs_error_pct``, ``direction_accuracy_pct``,
# ``observation_count``. Returning None or raising is treated as
# "no data" by the caller.
SectorCalibrationProvider = Callable[[str], Optional[dict]]


def compute_sector_calibration(
    sector: Optional[str],
    sector_calibration_provider: Optional[SectorCalibrationProvider] = None,
) -> Optional[SectorCalibrationInsight]:
    """Look up published YieldIQ accuracy for ``sector``.

    Returns None when:
      * ``sector`` is missing / not a non-empty string;
      * provider is None (caller declined to wire it up);
      * provider raises;
      * provider returns None (sector lacks the 30-observation
        threshold backtest_publisher enforces).
    """
    if not sector or not isinstance(sector, str):
        return None
    if sector_calibration_provider is None:
        return None
    try:
        row = sector_calibration_provider(sector)
    except Exception as exc:
        log.warning(
            "derived_insights: sector calibration provider raised "
            "(%s) — returning None",
            exc,
        )
        return None
    if not isinstance(row, dict):
        return None
    median_err = _safe_float(row.get("median_abs_error_pct"))
    direction = _safe_float(row.get("direction_accuracy_pct"))
    count_raw = row.get("observation_count")
    try:
        count: Optional[int] = (
            int(count_raw) if count_raw is not None else None
        )
    except (TypeError, ValueError):
        count = None
    if median_err is None and direction is None and count is None:
        return None
    parts: list[str] = [f"YieldIQ's {sector} calibration"]
    detail_parts: list[str] = []
    if median_err is not None:
        detail_parts.append(f"median absolute error = {median_err:.1f}%")
    if direction is not None:
        detail_parts.append(f"direction accuracy = {direction:.0f}%")
    if detail_parts:
        parts.append(": " + ", ".join(detail_parts))
    if count is not None:
        parts.append(f" (based on {count} observations)")
    headline = "".join(parts)
    return SectorCalibrationInsight(
        sector=sector,
        median_abs_error_pct=(
            round(median_err, 2) if median_err is not None else None
        ),
        direction_accuracy_pct=(
            round(direction, 1) if direction is not None else None
        ),
        observation_count=count,
        headline=headline,
    )


# ─────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ─────────────────────────────────────────────────────────────────

def compute_all_insights(
    *,
    confidence_scores: Optional[dict] = None,
    composite_components: Optional[dict] = None,
    liquidation: Optional[float] = None,
    replacement: Optional[float] = None,
    current_price: Optional[float] = None,
    dcf_fv: Optional[float] = None,
    composite_iv: Optional[float] = None,
    sector: Optional[str] = None,
    sector_calibration_provider: Optional[SectorCalibrationProvider] = None,
) -> DerivedInsights:
    """Compute all 4 derived insights from an analysis payload.

    Every individual computation is defensive — exceptions inside
    a single insight are logged and that insight surfaces as None
    on the returned bundle. Other insights are unaffected.

    Returns an empty bundle (all four slots None) when no data
    supports any insight — the router still emits the field; the
    frontend simply hides the panel.
    """
    out = DerivedInsights()
    try:
        out.confidence_summary = compute_confidence_summary(
            confidence_scores or {}
        )
    except Exception as exc:
        log.warning("derived_insights: confidence summary failed (%s)", exc)
    try:
        out.estimator_clustering = compute_estimator_clustering(
            composite_components
        )
    except Exception as exc:
        log.warning("derived_insights: estimator clustering failed (%s)", exc)
    try:
        # Floor/ceiling requires a current price to anchor against.
        if current_price is not None:
            out.floor_ceiling = compute_floor_ceiling(
                liquidation=liquidation,
                replacement=replacement,
                current_price=current_price,
                dcf=dcf_fv,
                composite=composite_iv,
            )
    except Exception as exc:
        log.warning("derived_insights: floor/ceiling failed (%s)", exc)
    try:
        out.sector_calibration = compute_sector_calibration(
            sector=sector,
            sector_calibration_provider=sector_calibration_provider,
        )
    except Exception as exc:
        log.warning("derived_insights: sector calibration failed (%s)", exc)
    return out


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────

def to_dict(insights: DerivedInsights) -> dict:
    """Project a DerivedInsights bundle to a JSON-safe dict.

    Slot keys mirror the dataclass field names so the frontend
    types map one-to-one. Slots whose insight could not be
    computed surface as ``null`` (rather than being omitted) so
    schema consumers see a stable shape.
    """
    if insights is None:
        return {
            "confidence_summary": None,
            "estimator_clustering": None,
            "floor_ceiling": None,
            "sector_calibration": None,
        }
    return {
        "confidence_summary": (
            asdict(insights.confidence_summary)
            if insights.confidence_summary is not None
            else None
        ),
        "estimator_clustering": (
            asdict(insights.estimator_clustering)
            if insights.estimator_clustering is not None
            else None
        ),
        "floor_ceiling": (
            asdict(insights.floor_ceiling)
            if insights.floor_ceiling is not None
            else None
        ),
        "sector_calibration": (
            asdict(insights.sector_calibration)
            if insights.sector_calibration is not None
            else None
        ),
    }
