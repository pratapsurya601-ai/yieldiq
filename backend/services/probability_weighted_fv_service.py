# backend/services/probability_weighted_fv_service.py
# ═══════════════════════════════════════════════════════════════
# Probability-Weighted Fair Value — T2.4 Phase A (2026-06-10).
#
# Why this exists
# ───────────────
# YieldIQ already computes bull / base / bear DCF scenarios for every
# ticker. The analysis page surfaces all three, but the single headline
# "fair value" reported alongside the verdict has historically been the
# point estimate from the base case. That carries a quiet falsehood —
# the headline number reads as "the answer" when, in practice, the
# scenarios disagree by 30-60% and the true point estimate is a mix.
#
# Standard sell-side practice is to weight the cases by probability:
#
#     bull  — 20-25% probability  (the rare upside lands)
#     base  — 50-60% probability  (the most likely trajectory)
#     bear  — 20-25% probability  (the rare downside lands)
#     disaster — 0-5% probability (tail / extreme scenario, optional)
#
# The weighted FV is the expected value of the scenarios under that
# probability distribution. The same machinery gives a crude "expected
# range" (5th / 95th percentile approximations) which is a calibrated
# uncertainty band rather than the spurious precision of the base case.
#
# Differentiator note
# ───────────────────
# AlphaSpread and Tickertape show scenario fan-outs but don't publish
# an EXPLICIT probability weighting — they leave the user to eyeball
# the mix. This service makes the weighting first-class and adjustable
# from observable signals (beta, sector cyclicality, earnings revisions,
# macro regime).
#
# Phase A vs Phase B
# ──────────────────
# Phase A (this PR): standalone service + unit tests + manifest entry.
# No wiring, no payload field change, no engine path mutation.
#
# Phase B (separate PR): wire `weighted_fv` into the composite intrinsic
# value pipeline so the headline number on the analysis page becomes
# the probability-weighted mix rather than the bare base case.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.probability_weighted_fv")


# ─────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────

@dataclass
class ScenarioInputs:
    """Inputs to the probability-weighted FV calculation.

    bull_fv / base_fv / bear_fv are the three DCF scenario midpoints.
    disaster_fv is optional; provided when an extreme-tail case has
    been modelled (e.g. balance-sheet stress on a cyclical at trough).

    The remaining fields are signals used by the weight-adjustment
    chain (beta + sector + revisions + macro). Each is Optional;
    missing signals leave the corresponding adjustment as a no-op.
    """
    bull_fv: float
    base_fv: float
    bear_fv: float
    disaster_fv: Optional[float] = None
    sector: Optional[str] = None
    beta: Optional[float] = None
    recent_earnings_revisions: Optional[str] = None  # "upgrades" | "downgrades" | "mixed"
    macro_regime: Optional[str] = None               # "expansion" | "neutral" | "contraction"


@dataclass
class ScenarioWeights:
    """Probability weights assigned to each scenario.

    Sums to 1.0 after `_normalize`. The disaster slot is 0.0 unless
    a 4-scenario distribution is in effect.
    """
    bull: float
    base: float
    bear: float
    disaster: float = 0.0

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.bull, self.base, self.bear, self.disaster)


@dataclass
class ProbabilityWeightedResult:
    """Output of `compute_probability_weighted_fv`.

    weighted_fv: the expected value under the final weight set, or
        None when the inputs were too degraded to compute (e.g. all
        scenarios non-positive).
    weights: the final, post-adjustment weight set (sums to 1.0).
    components: per-scenario breakdown
        {scenario_name: {"fv": <fv>, "weight": <w>, "contribution": <fv*w>}}
        — useful for the frontend tooltip showing how the mix landed.
    method: "three_scenario" | "four_scenario" | "unavailable".
    expected_range: a (5th-percentile, 95th-percentile) tuple
        approximation. Crude — true CDF would need Monte-Carlo
        sampling — but useful as a calibrated uncertainty band.
        (None, None) when method is "unavailable".
    sanity_warnings: list of human-readable warnings about input
        plausibility (e.g. "bull < base" or "spread > 100%").
    """
    weighted_fv: Optional[float]
    weights: ScenarioWeights
    components: dict
    method: str
    expected_range: tuple[Optional[float], Optional[float]]
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Canonical default weights
# ─────────────────────────────────────────────────────────────────

#: Three-scenario default — bull/base/bear at 25/50/25.
#:
#: Centred on the sell-side modal split (Damodaran "scenario weights"
#: chapter; ASA practice notes). Tighter than 30/40/30 because base-case
#: is the modelled posterior, not the prior — we already paid for the
#: information, so it deserves more weight than uniform.
DEFAULT_WEIGHTS_THREE: ScenarioWeights = ScenarioWeights(bull=0.25, base=0.50, bear=0.25)

#: Four-scenario default — bull/base/bear/disaster at 20/50/25/5.
#:
#: The disaster slot peels 5pp off the bull (rare upside is the
#: symmetric counterpart to the tail-disaster we are now pricing).
#: Bear stays at 25 because "bad case" and "disaster" are separate
#: ideas; a 2008-style scenario is a different distribution tail
#: from "earnings miss by 20%".
DEFAULT_WEIGHTS_FOUR: ScenarioWeights = ScenarioWeights(bull=0.20, base=0.50, bear=0.25, disaster=0.05)


# ─────────────────────────────────────────────────────────────────
# Cyclical sector identification
# ─────────────────────────────────────────────────────────────────

# Bare sector substrings used by adjust_weights_for_cyclical. We match
# substring + case-insensitive so "Auto OEM", "Auto Ancillaries", and
# "Automobile" all hit. Order doesn't matter — set semantics.
_CYCLICAL_SECTOR_KEYWORDS: frozenset[str] = frozenset({
    "metal", "mining",
    "cement",
    "auto", "automobile",
    "oil", "gas", "energy",
    "realty", "real estate", "construction",
    "shipping", "airline",
    "capital goods",
})


def _is_cyclical_sector(sector: Optional[str]) -> bool:
    """True if the sector string matches any known cyclical keyword.

    Defensive: empty / None / non-string inputs return False.
    """
    if not sector or not isinstance(sector, str):
        return False
    sec = sector.lower()
    for kw in _CYCLICAL_SECTOR_KEYWORDS:
        if kw in sec:
            return True
    return False


# ─────────────────────────────────────────────────────────────────
# Weight helpers
# ─────────────────────────────────────────────────────────────────

def _nonneg(x: float) -> float:
    """Clamp negatives to zero. Protects against an adjustment pushing
    any slot below zero before renormalization. Values > 1 are left
    intact — renormalize will divide them by the total."""
    if x < 0.0:
        return 0.0
    return x


def _normalize(weights: ScenarioWeights) -> ScenarioWeights:
    """Renormalize so the four slots sum to 1.0.

    After every adjustment we clamp negatives to 0 and divide by the
    new total. Falls back to the canonical default for the relevant
    scenario count when the total collapses to zero (defensive — should
    never happen given default starting weights).
    """
    b = _nonneg(weights.bull)
    m = _nonneg(weights.base)
    r = _nonneg(weights.bear)
    d = _nonneg(weights.disaster)
    total = b + m + r + d
    if total <= 0:
        # Degenerate input — fall back to canonical defaults.
        if d > 0 or weights.disaster > 0:
            return ScenarioWeights(
                bull=DEFAULT_WEIGHTS_FOUR.bull,
                base=DEFAULT_WEIGHTS_FOUR.base,
                bear=DEFAULT_WEIGHTS_FOUR.bear,
                disaster=DEFAULT_WEIGHTS_FOUR.disaster,
            )
        return ScenarioWeights(
            bull=DEFAULT_WEIGHTS_THREE.bull,
            base=DEFAULT_WEIGHTS_THREE.base,
            bear=DEFAULT_WEIGHTS_THREE.bear,
            disaster=0.0,
        )
    return ScenarioWeights(
        bull=b / total,
        base=m / total,
        bear=r / total,
        disaster=d / total,
    )


def compute_default_weights(scenarios: int = 3) -> ScenarioWeights:
    """Return the canonical default weight set for `scenarios` cases.

    Args:
        scenarios: 3 or 4. Any other value defaults to 3.

    Returns:
        A fresh ScenarioWeights instance — callers can mutate without
        leaking back into the module-level DEFAULT_WEIGHTS_* constants.
    """
    if scenarios == 4:
        return ScenarioWeights(
            bull=DEFAULT_WEIGHTS_FOUR.bull,
            base=DEFAULT_WEIGHTS_FOUR.base,
            bear=DEFAULT_WEIGHTS_FOUR.bear,
            disaster=DEFAULT_WEIGHTS_FOUR.disaster,
        )
    return ScenarioWeights(
        bull=DEFAULT_WEIGHTS_THREE.bull,
        base=DEFAULT_WEIGHTS_THREE.base,
        bear=DEFAULT_WEIGHTS_THREE.bear,
        disaster=0.0,
    )


# ─────────────────────────────────────────────────────────────────
# Adjustment functions
# Each returns a new ScenarioWeights — never mutates input.
# Each renormalizes the output so the four slots still sum to 1.0.
# ─────────────────────────────────────────────────────────────────

def adjust_weights_for_beta(
    weights: ScenarioWeights,
    beta: Optional[float],
) -> ScenarioWeights:
    """High-beta names widen the tails of the FV distribution.

    Adjustment ladder:
      - beta > 1.5: bull +5%, bear +5%, base -10% (wider tails)
      - beta < 0.7: bull -5%, bear -5%, base +10% (tighter tails)
      - else: unchanged

    Defensive against None / non-numeric beta — passthrough.
    Always renormalizes.
    """
    if beta is None:
        return _normalize(weights)
    try:
        b = float(beta)
    except (TypeError, ValueError):
        return _normalize(weights)
    if b != b:  # NaN
        return _normalize(weights)

    if b > 1.5:
        out = ScenarioWeights(
            bull=weights.bull + 0.05,
            base=weights.base - 0.10,
            bear=weights.bear + 0.05,
            disaster=weights.disaster,
        )
    elif b < 0.7:
        out = ScenarioWeights(
            bull=weights.bull - 0.05,
            base=weights.base + 0.10,
            bear=weights.bear - 0.05,
            disaster=weights.disaster,
        )
    else:
        out = weights
    return _normalize(out)


def adjust_weights_for_cyclical(
    weights: ScenarioWeights,
    sector: Optional[str],
) -> ScenarioWeights:
    """Cyclical sectors flatten the distribution toward the bear case.

    Rationale: at the top of the cycle, the bear case (downturn) is
    more likely than the symmetric weighting would suggest. We don't
    know where in the cycle we are without earnings-revision data, so
    the adjustment is intentionally modest.

    Adjustment:
      - cyclical sector (metals/cement/auto/oil&gas/...): bear +5%, base -5%
      - else: unchanged

    Always renormalizes.
    """
    if not _is_cyclical_sector(sector):
        return _normalize(weights)
    out = ScenarioWeights(
        bull=weights.bull,
        base=weights.base - 0.05,
        bear=weights.bear + 0.05,
        disaster=weights.disaster,
    )
    return _normalize(out)


def adjust_weights_for_revisions(
    weights: ScenarioWeights,
    revisions: Optional[str],
) -> ScenarioWeights:
    """Earnings revision direction shifts weight toward the matching tail.

    Earnings revisions are the cleanest forward-looking signal of
    realized scenario likelihood — analysts move estimates ~6-8 weeks
    ahead of the print, and the cumulative direction of those moves
    is correlated with which case lands.

    Adjustment:
      - "downgrades": bear +10%, bull -5%, base -5%
      - "upgrades":   bull +5%, bear -5%
      - "mixed" / None / unknown: unchanged

    Always renormalizes.
    """
    if revisions is None:
        return _normalize(weights)
    direction = revisions.strip().lower() if isinstance(revisions, str) else ""

    if direction == "downgrades":
        out = ScenarioWeights(
            bull=weights.bull - 0.05,
            base=weights.base - 0.05,
            bear=weights.bear + 0.10,
            disaster=weights.disaster,
        )
    elif direction == "upgrades":
        out = ScenarioWeights(
            bull=weights.bull + 0.05,
            base=weights.base,
            bear=weights.bear - 0.05,
            disaster=weights.disaster,
        )
    else:
        out = weights
    return _normalize(out)


def adjust_weights_for_macro(
    weights: ScenarioWeights,
    macro_regime: Optional[str],
) -> ScenarioWeights:
    """Macro regime shifts weight toward the matching tail.

    Adjustment:
      - "contraction" (recession risk):   bear +10%, bull -5%, base -5%
      - "expansion" (cyclical upswing):   bull +5%, bear -5%
      - "neutral" / None / unknown:       unchanged

    Always renormalizes.
    """
    if macro_regime is None:
        return _normalize(weights)
    regime = macro_regime.strip().lower() if isinstance(macro_regime, str) else ""

    if regime == "contraction":
        out = ScenarioWeights(
            bull=weights.bull - 0.05,
            base=weights.base - 0.05,
            bear=weights.bear + 0.10,
            disaster=weights.disaster,
        )
    elif regime == "expansion":
        out = ScenarioWeights(
            bull=weights.bull + 0.05,
            base=weights.base,
            bear=weights.bear - 0.05,
            disaster=weights.disaster,
        )
    else:
        out = weights
    return _normalize(out)


# ─────────────────────────────────────────────────────────────────
# Sanity warnings
# ─────────────────────────────────────────────────────────────────

def _sanity_warnings(
    bull_fv: Optional[float],
    base_fv: Optional[float],
    bear_fv: Optional[float],
    disaster_fv: Optional[float],
) -> list[str]:
    """Build the human-readable warning list for the input FVs.

    The compute path STILL runs even when warnings fire — the gate is
    "are the inputs nonsensical?" not "should we bail?". The frontend
    can decide whether to surface the warning or just gray out the
    badge.
    """
    warnings: list[str] = []
    # Only meaningful when bull/base both positive.
    if (
        bull_fv is not None
        and base_fv is not None
        and bull_fv > 0
        and base_fv > 0
        and bull_fv < base_fv
    ):
        warnings.append("bull < base (likely incorrect input)")
    if (
        bear_fv is not None
        and base_fv is not None
        and bear_fv > 0
        and base_fv > 0
        and bear_fv > base_fv
    ):
        warnings.append("bear > base (likely incorrect input)")
    if (
        disaster_fv is not None
        and bear_fv is not None
        and disaster_fv > 0
        and bear_fv > 0
        and disaster_fv > bear_fv
    ):
        warnings.append("disaster > bear (likely incorrect input)")

    # Spread checks vs. base_fv.
    if (
        bull_fv is not None
        and bear_fv is not None
        and base_fv is not None
        and base_fv > 0
    ):
        spread = abs(bull_fv - bear_fv)
        spread_pct = spread / base_fv
        if spread_pct > 1.0:
            warnings.append(
                f"spread > 100% of base_fv ({spread_pct * 100:.0f}%) — "
                "very wide; high uncertainty signal"
            )
        elif spread_pct < 0.10:
            warnings.append(
                f"spread < 10% of base_fv ({spread_pct * 100:.0f}%) — "
                "very narrow; probably synthetic"
            )
    return warnings


# ─────────────────────────────────────────────────────────────────
# Expected-range (5th / 95th percentile approximations)
# ─────────────────────────────────────────────────────────────────

def _expected_range(
    bull_fv: float,
    base_fv: float,
    bear_fv: float,
    weights: ScenarioWeights,
) -> tuple[float, float]:
    """Crude (5th, 95th) percentile estimates from the weighted mix.

    This is NOT a real CDF — that would require Monte-Carlo sampling
    of the underlying DCF parameter distributions. We approximate by:

      - p5  ≈ bear_fv  when bear weight ≥ 0.20
              else interpolate toward base by how much weight is
              "missing" relative to a fully-modelled 20% bear slot
      - p95 ≈ bull_fv  when bull weight ≥ 0.20
              else interpolate toward base by how much weight is
              "missing" relative to a fully-modelled 20% bull slot

    The 0.20 threshold matches the canonical bear/bull default
    weights. Below that, the tail isn't carrying enough probability
    mass to read as "the 5th/95th percentile" so we soften the
    estimate toward base.
    """
    bear_w = weights.bear
    bull_w = weights.bull

    if bear_w >= 0.20:
        p5 = bear_fv
    else:
        # weight in [0, 0.20) — interpolate between bear (weight=0.20)
        # and base (weight=0).
        t = bear_w / 0.20  # 0 -> base, 1 -> bear
        p5 = base_fv + t * (bear_fv - base_fv)

    if bull_w >= 0.20:
        p95 = bull_fv
    else:
        t = bull_w / 0.20
        p95 = base_fv + t * (bull_fv - base_fv)

    return (p5, p95)


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────

def _coerce_positive(x) -> Optional[float]:
    """Float-coerce, returning None for missing / non-positive / NaN."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v <= 0:
        return None
    return v


def compute_probability_weighted_fv(
    inputs: ScenarioInputs,
    weight_overrides: Optional[ScenarioWeights] = None,
) -> ProbabilityWeightedResult:
    """Compute the probability-weighted FV from the scenario inputs.

    Algorithm:
      1. Sanitize inputs (positive floats only; emit sanity warnings).
      2. Decide method ("three_scenario" / "four_scenario") based on
         whether a positive disaster_fv was supplied.
      3. Pick the starting weight set:
         - `weight_overrides` if provided (skips the adjustment chain),
           else
         - the canonical three- or four-scenario default.
      4. If using defaults, chain the four adjustment passes:
            beta -> cyclical -> revisions -> macro
         Each pass is independent (commutative-ish — they nudge by
         small fixed pp deltas) and renormalizes after itself.
      5. Compute weighted_fv = sum(fv_i * w_i) over the available
         scenarios.
      6. Build components dict + expected_range + warnings.

    Returns:
      ProbabilityWeightedResult. weighted_fv is None and method is
      "unavailable" when at least one of bull/base/bear is non-positive
      (we don't try to compute a 2-scenario fallback — the user wanted
      a probability-weighted mix and we don't have one).
    """
    # Sanity warnings consider RAW inputs (including non-positive)
    # so the "bull < base" check still fires even if e.g. base_fv was
    # zeroed by upstream gating.
    warnings = _sanity_warnings(
        inputs.bull_fv, inputs.base_fv, inputs.bear_fv, inputs.disaster_fv,
    )

    bull = _coerce_positive(inputs.bull_fv)
    base = _coerce_positive(inputs.base_fv)
    bear = _coerce_positive(inputs.bear_fv)
    disaster = _coerce_positive(inputs.disaster_fv)

    # Non-positive FVs collapse the calculation to unavailable.
    if bull is None or base is None or bear is None:
        empty_weights = ScenarioWeights(bull=0.0, base=0.0, bear=0.0, disaster=0.0)
        return ProbabilityWeightedResult(
            weighted_fv=None,
            weights=empty_weights,
            components={},
            method="unavailable",
            expected_range=(None, None),
            sanity_warnings=warnings,
        )

    has_disaster = disaster is not None
    method = "four_scenario" if has_disaster else "three_scenario"

    # Starting weight set.
    if weight_overrides is not None:
        weights = _normalize(weight_overrides)
    else:
        weights = compute_default_weights(scenarios=4 if has_disaster else 3)
        # Run the adjustment chain only when using defaults — explicit
        # overrides imply the caller knows what they want.
        weights = adjust_weights_for_beta(weights, inputs.beta)
        weights = adjust_weights_for_cyclical(weights, inputs.sector)
        weights = adjust_weights_for_revisions(weights, inputs.recent_earnings_revisions)
        weights = adjust_weights_for_macro(weights, inputs.macro_regime)

    # Weighted FV.
    if has_disaster:
        weighted_fv = (
            bull * weights.bull
            + base * weights.base
            + bear * weights.bear
            + disaster * weights.disaster
        )
    else:
        # Three-scenario — zero out disaster weight and renormalize bull/base/bear.
        if weights.disaster > 0:
            # Caller passed an override with a disaster slot but no disaster_fv;
            # collapse the disaster mass back into bear (the most-conservative
            # absorbing slot) and renormalize.
            renorm = ScenarioWeights(
                bull=weights.bull,
                base=weights.base,
                bear=weights.bear + weights.disaster,
                disaster=0.0,
            )
            weights = _normalize(renorm)
        weighted_fv = bull * weights.bull + base * weights.base + bear * weights.bear

    # Per-scenario breakdown.
    components: dict = {
        "bull": {
            "fv": bull,
            "weight": weights.bull,
            "contribution": bull * weights.bull,
        },
        "base": {
            "fv": base,
            "weight": weights.base,
            "contribution": base * weights.base,
        },
        "bear": {
            "fv": bear,
            "weight": weights.bear,
            "contribution": bear * weights.bear,
        },
    }
    if has_disaster:
        components["disaster"] = {
            "fv": disaster,
            "weight": weights.disaster,
            "contribution": disaster * weights.disaster,
        }

    # Expected range — three-scenario approximation. The disaster
    # scenario does NOT shift p5 (it's a tail beyond the 5th percentile);
    # if it ever needs to surface, that's a separate "disaster_floor"
    # field rather than a wider expected_range.
    p5, p95 = _expected_range(bull, base, bear, weights)

    return ProbabilityWeightedResult(
        weighted_fv=weighted_fv,
        weights=weights,
        components=components,
        method=method,
        expected_range=(p5, p95),
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────

def to_dict(result: ProbabilityWeightedResult) -> dict:
    """Project a ProbabilityWeightedResult into a JSON-safe dict.

    Field shape designed to match the frontend tooltip + the eventual
    Phase-B composite payload. expected_range emits as a 2-element list
    rather than a tuple so the JSON serializer doesn't choke; None
    entries inside become null on the wire.
    """
    p5, p95 = result.expected_range
    return {
        "weighted_fv": result.weighted_fv,
        "method": result.method,
        "weights": {
            "bull": result.weights.bull,
            "base": result.weights.base,
            "bear": result.weights.bear,
            "disaster": result.weights.disaster,
        },
        "components": result.components,
        "expected_range": [p5, p95],
        "sanity_warnings": list(result.sanity_warnings),
    }
