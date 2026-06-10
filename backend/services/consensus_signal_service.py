# backend/services/consensus_signal_service.py
"""
Cross-engine consensus signal (2026-06-10).

YieldIQ runs 7+ standalone valuation estimators (DCF, Multiples, Wall
Street, Three-stage growth DCF, Dividend Discount Model, Earnings
Power Value, Probability-weighted scenarios). The composite IV
service blends them with sector-aware weights into a single intrinsic
value.

This service answers a different, complementary question:

    How many of these estimators agree on the *direction* of the
    valuation gap vs the live price, irrespective of their magnitudes?

Direction agreement is a fundamentally different signal from the
composite weighted average. A composite can show "fair value 10%
above price" while 4 of 7 estimators sit BELOW price and 3 of 7 sit
ABOVE — the composite is pulled up by one or two large outliers. A
consensus headline of "6 of 7 estimators above price" is a much
stronger directional read than the same average.

Outperformance hypothesis (the reason the spec frames this as an
"outperformance play"): when multiple INDEPENDENT methodologies
agree on direction, the price gap is more likely to close in that
direction than when only one method agrees. Competitors surface a
single intrinsic value; we additionally surface the cross-method
agreement count.

═══════════════════════════════════════════════════════════════
SEBI vocab posture
═══════════════════════════════════════════════════════════════
Headline strings are descriptive — counts plus relative direction
("above current price", "below current price", "near current
price"). No advisory vocab. No words from the banned list. The
frontend component (ConsensusSignalBadge) mirrors this discipline.

═══════════════════════════════════════════════════════════════
Defensive posture
═══════════════════════════════════════════════════════════════
* Pure derivation — no DB / cache / I/O.
* compute_consensus_signal never raises on bad inputs; it returns
  a "dispersed" signal with the appropriate sanity warnings.
* Non-finite, None, or non-positive estimator values are filtered
  out (matches the existing composite_iv / derived_insights
  treatment — see derived_insights_service._safe_pos_float).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Public dataclass
# ─────────────────────────────────────────────────────────────────
@dataclass
class ConsensusSignal:
    """Cross-engine direction-agreement signal.

    direction_agreement_count
        Number of estimators that point in the SAME (most-common)
        direction vs the live price.
    total_estimators
        Number of estimators with a usable (positive, finite) value.
    direction_agreement_pct
        ``direction_agreement_count / total_estimators * 100``
        rounded to one decimal. ``0.0`` when ``total_estimators`` is 0.
    magnitude_clustering_cv
        Coefficient of variation (stdev / mean) of the estimator
        values, expressed as a fraction. ``None`` when fewer than
        two estimators have positive values, or when the mean is
        non-positive. Lower = tighter magnitude clustering.
    consensus_level
        One of: ``"very_high"``, ``"high"``, ``"moderate"``,
        ``"low"``, ``"dispersed"``. See
        ``classify_consensus_level`` for the thresholds.
    consensus_direction
        ``"above_price"`` | ``"below_price"`` | ``"near_price"`` |
        ``"split"`` | ``None``. ``"split"`` only when at least two
        directional buckets tie for the lead. ``None`` only when no
        estimator survived the filter.
    headline
        Human-readable single-line summary suitable for a UI badge.
    sanity_warnings
        Caveats the UI may want to render — e.g. "only 2 estimators
        available", "estimators dispersed across all three buckets".
        Never causes the signal to be suppressed; just informs.
    """
    direction_agreement_count: int = 0
    total_estimators: int = 0
    direction_agreement_pct: float = 0.0
    magnitude_clustering_cv: Optional[float] = None
    consensus_level: str = "dispersed"
    consensus_direction: Optional[str] = None
    headline: str = ""
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────
def _safe_pos_float(x: object) -> Optional[float]:
    """Return ``x`` as a finite, strictly positive float, else None.

    Matches the filter that ``derived_insights_service`` and
    ``composite_iv_service`` use so the two surfaces never disagree
    about which estimators were "active".
    """
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


# Friendly slot -> label map. Mirrors derived_insights_service so the
# two cards reference the same names.
_ESTIMATOR_LABELS: dict[str, str] = {
    "dcf": "DCF",
    "multiples": "Multiples",
    "analyst": "Wall Street",
    "wall_st": "Wall Street",  # alias — some call sites use this slot
    "three_stage": "Three-stage",
    "ddm": "DDM",
    "epv": "EPV",
    "probability_weighted": "Probability-weighted",
}


def _estimator_label(slot: str) -> str:
    return _ESTIMATOR_LABELS.get(slot, slot)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────
def classify_consensus_level(agreement_count: int, total: int) -> str:
    """Map agreement count + total estimators to a consensus level.

    Thresholds are calibrated to the 7-estimator universe described
    in the spec but generalised so a payload missing one or two
    estimators still classifies meaningfully:

      ≥ 85% of estimators agree            -> "very_high"
      ≥ 70% (and not very_high)            -> "high"
      ≥ 55% (and not high)                 -> "moderate"
      ≥ 40% (and not moderate)             -> "low"
      everything else                      -> "dispersed"

    Edge cases:
      * ``total <= 0`` -> "dispersed" (no signal possible).
      * ``total == 1`` -> "dispersed" (a single estimator cannot
        agree with anything).
      * ``agreement_count > total`` (a bug in the caller) is clamped
        to ``total`` before classification.
    """
    if total <= 1 or agreement_count <= 0:
        return "dispersed"
    if agreement_count > total:
        agreement_count = total
    pct = agreement_count / total
    if pct >= 0.85:
        return "very_high"
    if pct >= 0.70:
        return "high"
    if pct >= 0.55:
        return "moderate"
    if pct >= 0.40:
        return "low"
    return "dispersed"


def build_headline(
    level: str,
    direction: Optional[str],
    count: int,
    total: int,
) -> str:
    """Produce a single-line human-readable consensus summary.

    Examples:
      "6 of 7 estimators agree: above current price"
      "5 of 7 estimators agree: below current price"
      "3 of 7 estimators agree: near current price"
      "No estimators available for cross-engine consensus"
      "Estimators split across directions (3 of 7 lead)"
    """
    if total <= 0:
        return "No estimators available for cross-engine consensus"
    if direction is None:
        return f"Estimators split across directions ({count} of {total} lead)"
    direction_phrase = {
        "above_price": "above current price",
        "below_price": "below current price",
        "near_price": "near current price",
        "split": "split across directions",
    }.get(direction, direction)
    if direction == "split":
        return f"Estimators split across directions ({count} of {total} lead)"
    # Singular grammar for total==1
    estimators_word = "estimator" if total == 1 else "estimators"
    return f"{count} of {total} {estimators_word} agree: {direction_phrase}"


def _bucket_for(value: float, lower: float, upper: float) -> str:
    """Return 'above', 'below', or 'near' for an estimator value."""
    if value >= upper:
        return "above"
    if value <= lower:
        return "below"
    return "near"


def _direction_label(bucket: str) -> str:
    return {
        "above": "above_price",
        "below": "below_price",
        "near": "near_price",
    }.get(bucket, "near_price")


def compute_consensus_signal(
    estimator_values: dict[str, Optional[float]],
    current_price: float,
    tolerance_pct: float = 5.0,
) -> ConsensusSignal:
    """Analyse direction agreement of N estimators vs the live price.

    Args:
        estimator_values: ``{slot: value | None}`` map. Slot names
            should match those in ``_ESTIMATOR_LABELS`` (``dcf``,
            ``multiples``, ``analyst``, ``three_stage``, ``ddm``,
            ``epv``, ``probability_weighted``); unknown slots are
            still counted (treated as a generic estimator).
        current_price: live price the estimators are compared to.
        tolerance_pct: half-width of the "near price" band, in
            percent. Estimator values inside ``[price * (1 - t/100),
            price * (1 + t/100)]`` count as "near". Default ``5.0``
            matches the spec.

    Returns:
        ConsensusSignal — always returns a populated dataclass
        (never raises). When no usable inputs exist the signal is
        ``("dispersed", direction=None, headline="No estimators
        available…")`` with a sanity warning explaining why.
    """
    warnings: list[str] = []

    # Defensive: bad price -> we can't compute direction. Still emit a
    # well-formed signal so the inject pattern never breaks the response.
    if (
        current_price is None
        or not isinstance(current_price, (int, float))
        or not math.isfinite(float(current_price))
        or float(current_price) <= 0
    ):
        warnings.append("Current price unavailable — consensus cannot be computed")
        return ConsensusSignal(
            direction_agreement_count=0,
            total_estimators=0,
            direction_agreement_pct=0.0,
            magnitude_clustering_cv=None,
            consensus_level="dispersed",
            consensus_direction=None,
            headline=build_headline("dispersed", None, 0, 0),
            sanity_warnings=warnings,
        )

    price = float(current_price)

    if not isinstance(estimator_values, dict):
        warnings.append("No estimator dictionary supplied")
        return ConsensusSignal(
            headline=build_headline("dispersed", None, 0, 0),
            sanity_warnings=warnings,
        )

    # Filter out None / non-finite / non-positive estimator values.
    usable: list[tuple[str, float]] = []
    for slot, raw in estimator_values.items():
        v = _safe_pos_float(raw)
        if v is not None:
            usable.append((slot, v))

    total = len(usable)
    if total == 0:
        warnings.append("No estimators returned a finite, positive value")
        return ConsensusSignal(
            direction_agreement_count=0,
            total_estimators=0,
            direction_agreement_pct=0.0,
            magnitude_clustering_cv=None,
            consensus_level="dispersed",
            consensus_direction=None,
            headline=build_headline("dispersed", None, 0, 0),
            sanity_warnings=warnings,
        )

    # Sanity tolerance — clamp to [0, 50] so a misconfigured caller
    # can't silently swallow every estimator into the "near" bucket.
    try:
        tol = float(tolerance_pct)
    except (TypeError, ValueError):
        tol = 5.0
    if not math.isfinite(tol) or tol < 0:
        tol = 0.0
    if tol > 50.0:
        tol = 50.0

    lower = price * (1.0 - tol / 100.0)
    upper = price * (1.0 + tol / 100.0)

    bucket_counts = {"above": 0, "below": 0, "near": 0}
    for _slot, value in usable:
        bucket_counts[_bucket_for(value, lower, upper)] += 1

    # Pick the leading bucket. Ties default to "split" with the tied
    # count surfaced — the UI can choose to render this as neutral.
    sorted_buckets = sorted(
        bucket_counts.items(), key=lambda kv: kv[1], reverse=True
    )
    top_bucket, top_count = sorted_buckets[0]
    second_count = sorted_buckets[1][1] if len(sorted_buckets) > 1 else 0
    is_split = top_count > 0 and top_count == second_count
    direction: Optional[str]
    if top_count == 0:
        direction = None
    elif is_split:
        direction = "split"
    else:
        direction = _direction_label(top_bucket)

    agreement_count = top_count
    pct = (agreement_count / total) * 100.0 if total > 0 else 0.0

    # Magnitude clustering — coefficient of variation across the
    # positive estimator values. Smaller = tighter magnitude
    # agreement. Distinct from direction agreement; both are useful.
    cv: Optional[float] = None
    values = [v for _, v in usable]
    if len(values) >= 2:
        mean_val = statistics.fmean(values)
        if mean_val > 0:
            try:
                stdev_val = statistics.pstdev(values)
                cv = round(stdev_val / mean_val, 4)
            except statistics.StatisticsError:
                cv = None

    # Level — split direction caps the level at "dispersed" because
    # a tied vote across buckets isn't a directional consensus even
    # if the tied count is large.
    if is_split:
        level = "dispersed"
    else:
        level = classify_consensus_level(agreement_count, total)

    # Sanity warnings — informative, never gate the result.
    if total < 3:
        warnings.append(
            f"Only {total} estimator{'s' if total != 1 else ''} available; "
            "headline carries low confidence"
        )
    nonzero_buckets = sum(1 for _b, c in bucket_counts.items() if c > 0)
    if nonzero_buckets == 3:
        warnings.append(
            "Estimators spread across above / near / below buckets"
        )
    if is_split:
        warnings.append(
            "Top two direction buckets tied — no leading direction"
        )
    if cv is not None and cv > 0.50:
        warnings.append(
            f"Estimator magnitudes vary widely (CV = {cv:.2f})"
        )

    headline = build_headline(level, direction, agreement_count, total)

    return ConsensusSignal(
        direction_agreement_count=agreement_count,
        total_estimators=total,
        direction_agreement_pct=round(pct, 1),
        magnitude_clustering_cv=cv,
        consensus_level=level,
        consensus_direction=direction,
        headline=headline,
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# JSON projection + payload-extraction helper
# ─────────────────────────────────────────────────────────────────
def to_dict(signal: ConsensusSignal) -> dict:
    """Project a ConsensusSignal to a JSON-safe dict.

    Field order mirrors the dataclass so frontend consumers can rely
    on the shape. ``None`` slots are emitted (not omitted) for
    schema stability.
    """
    if signal is None:
        return {
            "direction_agreement_count": 0,
            "total_estimators": 0,
            "direction_agreement_pct": 0.0,
            "magnitude_clustering_cv": None,
            "consensus_level": "dispersed",
            "consensus_direction": None,
            "headline": "",
            "sanity_warnings": [],
            "estimator_breakdown": [],
        }
    out = asdict(signal)
    # ``estimator_breakdown`` is filled by the inject helper when it
    # has the raw estimator dict + price. The service-level to_dict
    # leaves it empty so the dataclass stays a pure value object.
    out["estimator_breakdown"] = []
    return out


def build_estimator_breakdown(
    estimator_values: dict[str, Optional[float]],
    current_price: float,
    tolerance_pct: float = 5.0,
) -> list[dict]:
    """Per-estimator direction breakdown for UI display.

    Mirrors the bucketing inside ``compute_consensus_signal`` so
    callers can render the same classification next to each
    estimator without re-deriving the band.

    Returns a list of ``{name, slot, value, direction}`` dicts —
    one per estimator that returned a usable (positive, finite)
    value. Direction is one of ``"above_price"``, ``"below_price"``,
    ``"near_price"``.
    """
    if (
        current_price is None
        or not isinstance(current_price, (int, float))
        or not math.isfinite(float(current_price))
        or float(current_price) <= 0
    ):
        return []
    if not isinstance(estimator_values, dict):
        return []
    price = float(current_price)
    try:
        tol = float(tolerance_pct)
    except (TypeError, ValueError):
        tol = 5.0
    if not math.isfinite(tol) or tol < 0:
        tol = 0.0
    if tol > 50.0:
        tol = 50.0
    lower = price * (1.0 - tol / 100.0)
    upper = price * (1.0 + tol / 100.0)

    out: list[dict] = []
    for slot, raw in estimator_values.items():
        v = _safe_pos_float(raw)
        if v is None:
            continue
        bucket = _bucket_for(v, lower, upper)
        out.append(
            {
                "name": _estimator_label(slot),
                "slot": slot,
                "value": round(v, 2),
                "direction": _direction_label(bucket),
            }
        )
    return out
