# backend/services/composite_composition_service.py
# ═══════════════════════════════════════════════════════════════
# Composite Composition transparency payload
# ───────────────────────────────────────────
# v_composite_composition_transparency_2026_06_10
#
# Why this exists
# ───────────────
# After Phase C (composite_iv_service) the headline number on the
# analysis page is `composite_intrinsic_value` — a pro-rata weighted
# average of up to 7 estimators (DCF / Multiples / Wall St / Three-
# stage DCF / DDM / EPV / Probability-weighted) plus the Phase-B
# sector-specific slot. When N of 7 estimators are unavailable
# (bank with no broker coverage, fresh listing with no peer cohort,
# etc.) the surviving estimators' weights are renormalized to sum to
# 1.0 — and the resulting composite can sit within 0.5% of the DCF
# value with no on-page explanation of WHY.
#
# Two failure modes the user encounters in prod today:
#
#   1. HDFCBANK composite ₹1,147.77 vs DCF ₹1,141.82 (delta 0.5%).
#      The "Cross-engine consensus" chip ("Only 2 estimators
#      available; headline carries low confidence") is rendered too
#      small to read. User can't see WHY the composite ≈ DCF.
#
#   2. AXISBANK composite +60% Undervalued (FV ₹2,103 vs px ₹1,314).
#      Extreme number with no breakdown — user can't judge whether
#      one estimator is going crazy or a consensus signal is firing.
#
# This service builds the structured `composite_composition` payload
# that the frontend uses to render a per-estimator breakdown table.
# Pure derivation from the existing `composite_components` dict
# emitted by composite_iv_service — does NOT change the headline
# `composite_intrinsic_value` value or any existing field.
#
# Shape contract
# ──────────────
# {
#   "estimators": [
#     {
#       "key": "dcf",                     # canonical slot id
#       "label": "DCF",                   # human-readable label
#       "value": 1141.82,                 # this estimator's FV (₹/share)
#       "weight_nominal": 0.35,           # default weight before renorm
#       "weight_effective": 0.45,         # weight after renorm + clamp
#       "contribution": 513.82,           # value * weight_effective
#       "applicable": true,               # did the engine produce a value
#       "reason": null,                   # if !applicable, the explainer
#       "is_outlier": false,              # >40% deviation from median
#     },
#     ...
#   ],
#   "estimators_available": 3,            # estimators with applicable=true
#   "estimators_total": 7,                # canonical estimator count
#   "confidence_label": "LOW",            # HIGH / MODERATE / LOW / MINIMAL
#   "confidence_caption": "5 of 7 ...",   # short human caption
#   "outliers": ["wall_street"],          # slot keys flagged as outliers
#   "composite_value": 1147.77,           # cross-checked composite
# }
#
# Confidence label thresholds
# ───────────────────────────
# Coverage = applicable / total. Bands:
#   >= 6/7    -> HIGH
#   >= 4/7    -> MODERATE
#   >= 3/7    -> LOW
#   <= 2/7    -> MINIMAL  (treat as DCF + 1 corroborator)
#
# The frontend reads `confidence_caption` for the headline string and
# uses `confidence_label` to pick the chip tone. Never renders the raw
# integer fraction without the human-readable caption.
#
# Outlier detection
# ─────────────────
# An estimator is flagged as outlier when its value deviates more than
# OUTLIER_THRESHOLD_PCT (40%) from the median of the available
# estimators. The flag is purely INFORMATIONAL — we do NOT zero its
# weight or recompute the composite without it. That removal is a
# follow-up (T1.4): for now, surfacing the flag is the lift we need
# so users can manually judge whether the composite is consensus or
# outlier-driven.
#
# Backward compatibility
# ──────────────────────
# Purely additive. Callers that pre-date this field receive None on
# the new payload slot and the frontend collapses to the existing
# composite chip. No existing test fixture changes shape.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("yieldiq.composite_composition")


# ─── canonical estimator slot definitions ─────────────────────────
# The seven public-facing estimator slots that contribute to the
# composite intrinsic value. Order matches the canonical display
# order in the frontend panel (primary first, sanity-check next,
# outside-view last). The labels are read by the frontend; keep
# them SHORT (`label`) and human (`description`) — no jargon.
#
# `nominal_weight` is the default weight from composite_iv_service
# BEFORE pro-rata renormalization. Surfaced so the panel can show
# the user "nominal X% -> effective Y%" for the math reveal.
#
# `default_reason` is the canonical "why not applicable" string
# the frontend renders when the corresponding *_fv field is None
# and the backend hasn't emitted a more specific reason via the
# `_reason` slots. Mirrors the existing valuation-methods-panel
# microcopy.
@dataclass(frozen=True)
class EstimatorSlot:
    key: str
    label: str
    description: str
    nominal_weight: float
    default_reason: str


CANONICAL_ESTIMATORS: tuple[EstimatorSlot, ...] = (
    EstimatorSlot(
        key="dcf",
        label="DCF",
        description="Two-stage discounted cash flow",
        nominal_weight=0.35,
        default_reason=(
            "DCF requires positive base-year FCF and at least 3 years of "
            "historical financials"
        ),
    ),
    EstimatorSlot(
        key="multiples",
        label="Peer multiples",
        description="Sector-median PE / PB applied to this ticker",
        nominal_weight=0.20,
        default_reason=(
            "Peer multiples need a sector cohort with a usable median "
            "and a positive own-ticker multiple"
        ),
    ),
    EstimatorSlot(
        key="three_stage",
        label="Three-stage DCF",
        description="Damodaran linear-fade DCF",
        nominal_weight=0.15,
        default_reason=(
            "Three-stage DCF needs positive base-year FCF and a non-"
            "holdco / non-REIT classification"
        ),
    ),
    EstimatorSlot(
        key="analyst",
        label="Wall St analyst",
        description="Broker consensus price target",
        nominal_weight=0.15,
        default_reason="No broker coverage on this ticker",
    ),
    EstimatorSlot(
        key="ddm",
        label="Dividend discount",
        description="Gordon / two-stage / H-model DDM",
        nominal_weight=0.05,
        default_reason=(
            "DDM needs payout >= 30% and a 5+ year dividend streak"
        ),
    ),
    EstimatorSlot(
        key="epv",
        label="Earnings Power Value",
        description="Greenwald no-growth steady-state",
        nominal_weight=0.05,
        default_reason=(
            "EPV needs 5+ years of stable EBIT history; banks / insurers "
            "use the financial-cohort path"
        ),
    ),
    EstimatorSlot(
        key="probability_weighted",
        label="Probability-weighted",
        description="Bull / base / bear scenario mix",
        nominal_weight=0.05,
        default_reason=(
            "Probability-weighted mix needs positive bull / base / bear "
            "scenarios"
        ),
    ),
)

# Labels for the Phase-B sector-specific slot. When set, this slot
# REPLACES the headline-scheme weights (composite_iv_service applies
# the with-sector default of 0.40 to this slot). For the composition
# panel we display it as an additional row above DCF with its tag
# read from `composite_components.sector_specific_label`.
SECTOR_SPECIFIC_NOMINAL_WEIGHT: float = 0.40

# Outlier detection — >40% deviation from the median of available
# estimators marks an estimator as an outlier. Documented in module
# docstring. Threshold chosen to catch the "one estimator going
# crazy" failure mode (e.g. WIPRO MoS +321% pre-clamp) without
# tripping on normal cohort dispersion.
OUTLIER_THRESHOLD_PCT: float = 40.0

# Confidence label thresholds — see module docstring.
CONFIDENCE_HIGH_THRESHOLD: int = 6      # >= 6/7 -> HIGH
CONFIDENCE_MODERATE_THRESHOLD: int = 4  # >= 4/7 -> MODERATE
CONFIDENCE_LOW_THRESHOLD: int = 3       # >= 3/7 -> LOW
# < 3/7 -> MINIMAL.


# ─── result dataclasses ───────────────────────────────────────────


@dataclass
class CompositionEstimatorRow:
    """One row in the composition table."""

    key: str
    label: str
    value: Optional[float]
    weight_nominal: float
    weight_effective: float
    contribution: Optional[float]
    applicable: bool
    reason: Optional[str] = None
    is_outlier: bool = False
    description: str = ""


@dataclass
class CompositeComposition:
    """Top-level composition payload."""

    estimators: list[CompositionEstimatorRow] = field(default_factory=list)
    estimators_available: int = 0
    estimators_total: int = 0
    confidence_label: str = "MINIMAL"
    confidence_caption: str = ""
    outliers: list[str] = field(default_factory=list)
    composite_value: Optional[float] = None


# ─── helpers ──────────────────────────────────────────────────────


def _coerce_pos_float(v: Any) -> Optional[float]:
    """Float-coerce that drops None, NaN, infinity, and non-positive.

    Mirrors composite_iv_service._coerce_pos_float so the
    composition panel reaches the same applicability verdict as the
    composite math itself.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if f == float("inf") or f == float("-inf"):
        return None
    if f <= 0:
        return None
    return f


def _pick_reason(
    slot_key: str,
    *,
    payload: dict,
    default: str,
) -> str:
    """Return the per-ticker reason string when available, else default.

    The backend's `_reason` slots are populated when an estimator
    fails its applicability gate (e.g. `epv_reason = "banks use the
    financial-cohort path, not EPV"`). Surfacing the specific reason
    avoids the panel reading "DDM needs payout >= 30%" for a name that
    pays 60% but lacks the dividend streak — the per-ticker reason is
    more precise than the generic gate copy.
    """
    reason_key = f"{slot_key}_reason"
    raw = payload.get(reason_key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


def _confidence_label_for(available: int, total: int) -> str:
    """Pick the confidence band tag from the coverage count."""
    if total <= 0:
        return "MINIMAL"
    if available >= CONFIDENCE_HIGH_THRESHOLD:
        return "HIGH"
    if available >= CONFIDENCE_MODERATE_THRESHOLD:
        return "MODERATE"
    if available >= CONFIDENCE_LOW_THRESHOLD:
        return "LOW"
    return "MINIMAL"


def _confidence_caption_for(
    available: int,
    total: int,
    label: str,
) -> str:
    """Build the human-readable caption that sits under the headline.

    Examples (all `N of M` framed so the math is legible):
      "7 of 7 estimators populated — HIGH composite confidence"
      "5 of 7 estimators populated — MODERATE confidence; weights renormalized"
      "3 of 7 estimators populated — LOW confidence; composite reduces toward best-available estimators"
      "2 of 7 estimators populated — MINIMAL confidence; treat as DCF plus 1 corroborator"
    """
    base = f"{available} of {total} estimators populated"
    if label == "HIGH":
        return f"{base} — HIGH composite confidence"
    if label == "MODERATE":
        return (
            f"{base} — MODERATE confidence; weights renormalized"
        )
    if label == "LOW":
        return (
            f"{base} — LOW confidence; composite reduces toward best-"
            "available estimators"
        )
    return (
        f"{base} — MINIMAL confidence; treat as DCF plus 1 corroborator"
    )


def _detect_outliers(rows: list[CompositionEstimatorRow]) -> list[str]:
    """Flag applicable rows whose value sits >OUTLIER_THRESHOLD_PCT
    from the median of the available estimators.

    Returns the list of slot `key`s flagged as outliers. Each row's
    `is_outlier` flag is mutated in place so the per-row payload
    carries the same answer the headline list does.

    Median-based detection (not mean-based) so a single outlier does
    not pull the central tendency toward itself and mask its own flag.
    Requires at least 3 applicable estimators — with only 2 the
    concept of an outlier isn't well-defined (which one is right?).
    """
    applicable_rows = [
        r for r in rows if r.applicable and r.value is not None and r.value > 0
    ]
    if len(applicable_rows) < 3:
        return []
    values = [r.value for r in applicable_rows if r.value is not None]
    if not values:
        return []
    try:
        median_val = float(statistics.median(values))
    except statistics.StatisticsError:
        return []
    if median_val <= 0:
        return []
    flagged: list[str] = []
    for row in applicable_rows:
        if row.value is None:
            continue
        deviation_pct = abs(row.value - median_val) / median_val * 100.0
        if deviation_pct > OUTLIER_THRESHOLD_PCT:
            row.is_outlier = True
            flagged.append(row.key)
    return flagged


# ─── public API ───────────────────────────────────────────────────


def build_composite_composition(
    payload: dict,
    composite_components: Optional[dict] = None,
) -> CompositeComposition:
    """Build the composition payload from a response dict.

    Arguments
    ─────────
    payload
        The analysis response dict (or model_dump). Must carry the
        per-estimator *_fv fields (dcf via valuation.fair_value,
        multiples via multiples_based_fv, etc.) and the *_reason
        slots when an estimator was inapplicable.
    composite_components
        The dict written by composite_iv_service via composite_to_dict
        and stored on `composite_components.components`. When supplied
        the EFFECTIVE weights and per-row VALUES come from this dict
        verbatim, so the panel agrees with the composite math
        byte-for-byte. When None we fall back to recomputing the
        renormalized weights from the canonical defaults.

    Returns
    ───────
    `CompositeComposition` — always safe to render; an empty payload
    (no available estimators) still returns a populated object with
    `estimators_available = 0` and the MINIMAL confidence caption so
    the frontend can render a coherent "no estimators populated" view.

    Never raises. Defensive — used inside try/except in the router
    inject helpers.
    """
    valuation = payload.get("valuation") or {}
    insights = payload.get("insights") or {}

    # ── Step 1: gather per-estimator values from the payload.
    # Reuse the same precedence chain composite_iv_service uses so the
    # panel sees the same picture the math saw.
    dcf_fv = _coerce_pos_float(valuation.get("fair_value"))
    multiples_fv = _coerce_pos_float(payload.get("multiples_based_fv"))
    # Analyst — prefer the structured consensus block.
    analyst_avg: Optional[float] = None
    cons = insights.get("analyst_consensus")
    if isinstance(cons, dict):
        pt = cons.get("price_target") or {}
        analyst_avg = pt.get("mean") or pt.get("median")
    if analyst_avg is None:
        analyst_avg = insights.get("wall_street_avg_target")
    analyst_avg = _coerce_pos_float(analyst_avg)
    three_stage_fv = _coerce_pos_float(payload.get("three_stage_fv"))
    ddm_fv = _coerce_pos_float(payload.get("ddm_fv"))
    epv_fv = _coerce_pos_float(payload.get("epv_per_share"))
    prob_weighted_fv = _coerce_pos_float(payload.get("probability_weighted_fv"))

    raw_values: dict[str, Optional[float]] = {
        "dcf": dcf_fv,
        "multiples": multiples_fv,
        "three_stage": three_stage_fv,
        "analyst": analyst_avg,
        "ddm": ddm_fv,
        "epv": epv_fv,
        "probability_weighted": prob_weighted_fv,
    }

    # ── Step 2: pull the EFFECTIVE weights from composite_components
    # when the caller supplied them. The composite_iv_service may
    # apply the with-sector weight scheme (different defaults) so we
    # trust the values it produced rather than re-deriving them.
    eff_components: dict[str, dict] = {}
    components_method: Optional[str] = None
    composite_value: Optional[float] = None
    if isinstance(composite_components, dict):
        components = composite_components.get("components")
        if isinstance(components, dict):
            for key, comp in components.items():
                if isinstance(comp, dict):
                    eff_components[key] = comp
        components_method = composite_components.get("method")
        # The composite headline is carried alongside in the top-level
        # payload — this is the rounded weighted average post-overlay.
        composite_value = payload.get("composite_intrinsic_value")

    # ── Step 3: figure out the renormalization denominator for nominal
    # -> effective fallback when the composite_components dict didn't
    # carry the slot (e.g. legacy cached payload). We re-do the pro-rata
    # math against CANONICAL_ESTIMATORS exactly so the panel never
    # disagrees with composite_iv_service on the renorm posture.
    available_nominal_sum = sum(
        slot.nominal_weight
        for slot in CANONICAL_ESTIMATORS
        if raw_values.get(slot.key) is not None
    )

    # ── Step 4: build per-slot rows.
    rows: list[CompositionEstimatorRow] = []
    for slot in CANONICAL_ESTIMATORS:
        raw = raw_values.get(slot.key)
        applicable = raw is not None
        # Effective weight: pull from composite_components when present,
        # else compute via pro-rata renormalization (matches the
        # composite_iv_service path).
        weight_effective = 0.0
        # The composite_iv_service uses a different default weight
        # scheme when sector_specific_fv is present (with-sector
        # scheme). Trust its emitted effective weights when present.
        eff = eff_components.get(slot.key)
        if isinstance(eff, dict) and "weight" in eff:
            try:
                weight_effective = float(eff["weight"])
            except (TypeError, ValueError):
                weight_effective = 0.0
        elif applicable and available_nominal_sum > 0:
            weight_effective = round(
                slot.nominal_weight / available_nominal_sum, 4
            )
        # Component value — prefer the composite_components value when
        # present (it's already 2dp-rounded by composite_to_dict).
        comp_value: Optional[float] = None
        if isinstance(eff, dict) and "value" in eff:
            try:
                comp_value = float(eff["value"])
            except (TypeError, ValueError):
                comp_value = raw
        else:
            comp_value = raw
        contribution = (
            round(comp_value * weight_effective, 2)
            if (applicable and comp_value is not None and weight_effective > 0)
            else None
        )
        reason: Optional[str] = None
        if not applicable:
            reason = _pick_reason(
                slot.key, payload=payload, default=slot.default_reason
            )
        rows.append(
            CompositionEstimatorRow(
                key=slot.key,
                label=slot.label,
                value=comp_value if applicable else None,
                weight_nominal=slot.nominal_weight,
                weight_effective=weight_effective,
                contribution=contribution,
                applicable=applicable,
                reason=reason,
                is_outlier=False,  # filled in by _detect_outliers
                description=slot.description,
            )
        )

    # ── Step 5: outlier flagging (mutates each row in place).
    outlier_keys = _detect_outliers(rows)

    # ── Step 6: confidence labelling.
    available = sum(1 for r in rows if r.applicable)
    total = len(CANONICAL_ESTIMATORS)
    label = _confidence_label_for(available, total)
    caption = _confidence_caption_for(available, total, label)

    # ── Step 7: composite_value fallback.
    # Prefer the value the headline already shows; else recompute from
    # the applicable rows as a sanity-check value. The frontend uses
    # composite_value as the row-by-row total reconciliation anchor.
    if composite_value is None:
        # Sum of contributions across applicable rows ≈ composite.
        cv_sum = 0.0
        any_present = False
        for r in rows:
            if r.applicable and r.contribution is not None:
                cv_sum += r.contribution
                any_present = True
        composite_value = round(cv_sum, 2) if any_present else None

    return CompositeComposition(
        estimators=rows,
        estimators_available=available,
        estimators_total=total,
        confidence_label=label,
        confidence_caption=caption,
        outliers=outlier_keys,
        composite_value=composite_value,
    )


def composition_to_dict(c: CompositeComposition) -> dict:
    """Serialize a CompositeComposition to a JSON-safe dict.

    Mirrors composite_to_dict — the router writes this to
    ``payload.composite_composition`` and the frontend reads it via
    its API type binding. Always returns the same shape so the
    frontend never branches on "field missing".
    """
    return {
        "estimators": [
            {
                "key": r.key,
                "label": r.label,
                "value": r.value,
                "weight_nominal": round(r.weight_nominal, 4),
                "weight_effective": round(r.weight_effective, 4),
                "contribution": r.contribution,
                "applicable": r.applicable,
                "reason": r.reason,
                "is_outlier": r.is_outlier,
                "description": r.description,
            }
            for r in c.estimators
        ],
        "estimators_available": c.estimators_available,
        "estimators_total": c.estimators_total,
        "confidence_label": c.confidence_label,
        "confidence_caption": c.confidence_caption,
        "outliers": list(c.outliers),
        "composite_value": c.composite_value,
    }
