"""Cement capacity-utilization valuation service — T3.8 Phase A.

Why this exists
───────────────
Indian cement (ULTRACEMCO, AMBUJACEM, ACC, SHREECEM, JKCEMENT, RAMCOCEM,
DALBHARAT, INDIACEM, JKLAKSHMI, BIRLACORPN, ORIENTCEM) is a textbook
cyclical: fair value is dominated by VOLUME × REALIZATION × MARGIN, and
the volume term is bounded by INSTALLED CAPACITY × UTILIZATION. A
generic DCF on trailing FCF doesn't know that:

  - 75% utilization is breakeven for most Indian integrated cement
    players (fixed-cost-heavy operations — kilns, grinding units,
    captive power, fly-ash logistics).
  - 85% utilization is the "strong cycle" zone — operating leverage
    flips the EBITDA/tonne curve sharply upward.
  - 95% utilization is stretched — incremental capacity must come
    online soon or realizations get bid up irrationally before
    correcting.

Industry-standard frame used by every sell-side cement analyst:

    Mid-cycle EBITDA = installed_capacity × mid_cycle_utilization
                       × EBITDA-per-tonne
    EV               = Mid-cycle EBITDA × EV/EBITDA multiple
    Equity value     = EV - net debt
    Fair value/share = Equity / shares outstanding

Mid-cycle utilization for Indian cement sits around 78-82% across the
12-year average (FY13-FY24 spans two clear demand-driven super-cycles
plus the COVID drawdown). The 80% default reflects the cohort mean.

Segment multiples reflect the historical traded band for each tier:

  - **Premium** (ULTRACEMCO, SHREECEM): 16-18× mid-cycle EBITDA.
    Pricing power on brand + distribution; high mix of branded
    trade-channel volumes; low historical utilization volatility.
  - **Mid-tier** (AMBUJACEM, ACC, DALBHARAT, JKCEMENT, RAMCOCEM,
    BIRLACORPN): 13-14× mid-cycle EBITDA. Solid franchises,
    regional concentration, intermediate utilization volatility.
  - **Weak** (INDIACEM, JKLAKSHMI, ORIENTCEM): 10-11× mid-cycle
    EBITDA. Sub-scale, weak balance sheets, or regional demand
    headwinds; trade at structural discount even mid-cycle.

Caller contract
───────────────
``compute_cement_fv(inputs)`` is the single entry point. It produces a
``CementResult`` with a per-share fair value, the mid-cycle EBITDA, the
enterprise value, a transparent ``components`` dict, and a
``cycle_position_signal`` ("trough" / "mid" / "peak") that summarizes
where the CURRENT utilization sits relative to mid-cycle.

``classify_cycle_position(current, mid)`` is the public helper exposing
the breakpoint logic so other engines (router heuristics, the analysis
page narrative) can render the same label consistently.

``is_cement_applicable(ticker, sector)`` covers router dispatch when the
caller only has a sector hint.

Discipline
──────────
- Returns ``method="unavailable"`` when inputs don't allow a
  computation. Never silently substitutes a fallback FV.
- Sanity warnings are observational, not gating. Caller decides.
- Phase A is standalone — no router wiring, no manifest read-path
  invalidation of existing rows (manifest entry is documentation-
  only). Phase B (separate PR) routes the 11 cement tickers through
  this engine and surfaces the cycle-position chip on the analysis
  page.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.cement_utilization")


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

CementSubSegment = Literal["premium", "mid_tier", "weak"]

CyclePosition = Literal["trough", "mid", "peak"]


@dataclass
class CementInputs:
    """Inputs to the cement capacity-utilization engine.

    Capacities are in MTPA (million tonnes per annum). Realization and
    EBITDA per tonne are in INR. Utilization fields are PERCENTAGE
    POINTS (80.0 means 80%, not 0.80) — matches how Indian cement
    quarterly disclosures publish capacity utilization.
    """

    installed_capacity_mtpa: float
    current_utilization_pct: float
    mid_cycle_utilization_pct: float = 80.0
    realization_per_tonne_inr: float = 5800.0
    ebitda_per_tonne_inr: float = 1100.0
    ev_ebitda_multiple: float = 14.0
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0
    sub_segment: CementSubSegment = "mid_tier"


@dataclass
class CementResult:
    """Unified result shape for the cement engine.

    ``components`` carries the full breakdown so callers can render
    the EBITDA → EV → equity → per-share waterfall transparently.
    ``method`` is ``"cement_capacity_utilization"`` on a successful
    computation and ``"unavailable"`` when inputs prevent it.
    """

    fair_value_per_share: Optional[float]
    mid_cycle_ebitda_inr_cr: float
    enterprise_value_inr_cr: Optional[float]
    components: dict = field(default_factory=dict)
    cycle_position_signal: CyclePosition = "mid"
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Ticker registry
# ─────────────────────────────────────────────────────────────────

# Bare tickers (no .NS) → sub-segment. Used for router-side dispatch.
CEMENT_TICKERS: dict[str, CementSubSegment] = {
    "ULTRACEMCO": "premium",
    "SHREECEM":   "premium",
    "AMBUJACEM":  "mid_tier",
    "ACC":        "mid_tier",
    "DALBHARAT":  "mid_tier",
    "JKCEMENT":   "mid_tier",
    "RAMCOCEM":   "mid_tier",
    "BIRLACORPN": "mid_tier",
    "INDIACEM":   "weak",
    "JKLAKSHMI":  "weak",
    "ORIENTCEM":  "weak",
}


# Mid-cycle multiples by sub-segment. Used as the default when caller
# does not override ``ev_ebitda_multiple`` and as the reference band
# for the sanity warning when the caller's multiple is far from the
# historical mid-cycle.
SEGMENT_MULTIPLES: dict[CementSubSegment, float] = {
    "premium":  17.0,
    "mid_tier": 13.5,
    "weak":     10.5,
}


# Sector / industry strings that should route through this engine.
# Matched case-insensitively as substring on the caller-supplied
# sector hint.
_CEMENT_SECTOR_HINTS = (
    "cement",
    "building materials",
    "construction materials",
)


# ─────────────────────────────────────────────────────────────────
# Cycle-position thresholds
# ─────────────────────────────────────────────────────────────────

# Current utilization more than this far BELOW mid-cycle → "trough".
_TROUGH_GAP_PCT = 7.0
# Current utilization more than this far ABOVE mid-cycle → "peak".
_PEAK_GAP_PCT = 7.0

# Sanity boundaries on utilization values themselves.
_UTIL_BREAKEVEN_PCT = 75.0
_UTIL_STRETCHED_PCT = 95.0

# Sanity boundaries on EBITDA per tonne (INR). The Indian cement cohort
# has historically traded between ~₹600 (deep trough) and ~₹1600 (peak)
# per tonne EBITDA. Values outside this band are flagged but not gated.
_EBITDA_PER_TONNE_LOW_INR = 600.0
_EBITDA_PER_TONNE_HIGH_INR = 1600.0


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against CEMENT_TICKERS."""
    if not ticker:
        return ""
    bare = ticker
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.upper().endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare.upper()


def _safe_pos(value: Optional[float]) -> float:
    """Return float(value) or 0.0 on missing/non-numeric input."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────
# Cycle position
# ─────────────────────────────────────────────────────────────────

def classify_cycle_position(
    current_util_pct: float,
    mid_util_pct: float,
) -> CyclePosition:
    """Bucket current utilization vs mid-cycle into trough / mid / peak.

    Symmetric ±``_TROUGH_GAP_PCT`` / ±``_PEAK_GAP_PCT`` band around
    mid-cycle. The default 7pp gap matches the historical Indian
    cement cohort spread (mid-cycle ≈ 80%; clearly trough below 73%;
    clearly peak above 87%).

    Public helper so the analysis-page narrative and any
    router-side dispatch render the same label without re-inventing
    the breakpoints.
    """
    current = _safe_pos(current_util_pct)
    mid = _safe_pos(mid_util_pct)

    if mid <= 0:
        # Defensive — without a mid-cycle anchor the question is
        # ill-posed. Caller is responsible for supplying a sane
        # default (we ship 80.0).
        return "mid"

    if current <= mid - _TROUGH_GAP_PCT:
        return "trough"
    if current >= mid + _PEAK_GAP_PCT:
        return "peak"
    return "mid"


# ─────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────

def compute_cement_fv(inputs: CementInputs) -> CementResult:
    """Capacity × mid-cycle utilization × EBITDA/t × multiple - net_debt.

    The framework deliberately VALUES THE COMPANY AT MID-CYCLE, not at
    current-cycle. Current utilization is REPORTED as a cycle-position
    chip on the result so the caller can communicate where the cohort
    sits today, but it does NOT scale the EBITDA going into the
    valuation. The whole point of using mid-cycle is to avoid
    overpaying at the peak and underpaying at the trough.

    Returns ``CementResult`` with method ``"cement_capacity_utilization"``
    on success and ``"unavailable"`` when inputs prevent it.
    """
    warns: list[str] = []

    capacity = _safe_pos(inputs.installed_capacity_mtpa)
    current_util = _safe_pos(inputs.current_utilization_pct)
    mid_util = _safe_pos(inputs.mid_cycle_utilization_pct)
    realization = _safe_pos(inputs.realization_per_tonne_inr)
    ebitda_per_tonne = _safe_pos(inputs.ebitda_per_tonne_inr)
    multiple = _safe_pos(inputs.ev_ebitda_multiple)
    net_debt = _safe_pos(inputs.net_debt_inr_cr)
    shares = _safe_pos(inputs.shares_outstanding)
    sub_segment = inputs.sub_segment if inputs.sub_segment in SEGMENT_MULTIPLES else "mid_tier"

    components: dict = {
        "installed_capacity_mtpa": capacity,
        "current_utilization_pct": current_util,
        "mid_cycle_utilization_pct": mid_util,
        "realization_per_tonne_inr": realization,
        "ebitda_per_tonne_inr": ebitda_per_tonne,
        "ev_ebitda_multiple": multiple,
        "net_debt_inr_cr": net_debt,
        "shares_outstanding": shares,
        "sub_segment": sub_segment,
    }

    cycle_position = classify_cycle_position(current_util, mid_util)
    components["cycle_position_signal"] = cycle_position

    # ── Defensive guards ────────────────────────────────────────────
    if capacity <= 0:
        warns.append("non-positive installed capacity — cement FV cannot compute")
        return CementResult(
            fair_value_per_share=None,
            mid_cycle_ebitda_inr_cr=0.0,
            enterprise_value_inr_cr=None,
            components=components,
            cycle_position_signal=cycle_position,
            method="unavailable",
            sanity_warnings=warns,
        )

    if mid_util <= 0:
        warns.append("non-positive mid-cycle utilization — cement FV cannot compute")
        return CementResult(
            fair_value_per_share=None,
            mid_cycle_ebitda_inr_cr=0.0,
            enterprise_value_inr_cr=None,
            components=components,
            cycle_position_signal=cycle_position,
            method="unavailable",
            sanity_warnings=warns,
        )

    if ebitda_per_tonne <= 0:
        warns.append("non-positive EBITDA per tonne — cement FV cannot compute")
        return CementResult(
            fair_value_per_share=None,
            mid_cycle_ebitda_inr_cr=0.0,
            enterprise_value_inr_cr=None,
            components=components,
            cycle_position_signal=cycle_position,
            method="unavailable",
            sanity_warnings=warns,
        )

    if multiple <= 0:
        warns.append("non-positive EV/EBITDA multiple — cement FV cannot compute")
        return CementResult(
            fair_value_per_share=None,
            mid_cycle_ebitda_inr_cr=0.0,
            enterprise_value_inr_cr=None,
            components=components,
            cycle_position_signal=cycle_position,
            method="unavailable",
            sanity_warnings=warns,
        )

    # ── Observational sanity warnings ───────────────────────────────
    if current_util > 0 and current_util < _UTIL_BREAKEVEN_PCT:
        warns.append(
            f"current utilization {current_util:.1f}% < {_UTIL_BREAKEVEN_PCT:.0f}% "
            "— below typical cement breakeven (fixed costs heavy)"
        )
    if current_util > _UTIL_STRETCHED_PCT:
        warns.append(
            f"current utilization {current_util:.1f}% > {_UTIL_STRETCHED_PCT:.0f}% "
            "— stretched; expansion needed or realization will mean-revert"
        )

    if ebitda_per_tonne < _EBITDA_PER_TONNE_LOW_INR:
        warns.append(
            f"EBITDA/tonne ₹{ebitda_per_tonne:.0f} < ₹{_EBITDA_PER_TONNE_LOW_INR:.0f} "
            "— trough margins, mean reversion likely"
        )
    elif ebitda_per_tonne > _EBITDA_PER_TONNE_HIGH_INR:
        warns.append(
            f"EBITDA/tonne ₹{ebitda_per_tonne:.0f} > ₹{_EBITDA_PER_TONNE_HIGH_INR:.0f} "
            "— peak margins, mean reversion likely"
        )

    # Multiple-vs-segment sanity check. ±25% band around the segment
    # reference multiple — beyond that, flag for review.
    ref_multiple = SEGMENT_MULTIPLES.get(sub_segment, 13.5)
    if ref_multiple > 0:
        ratio = multiple / ref_multiple
        if ratio < 0.75 or ratio > 1.25:
            warns.append(
                f"EV/EBITDA multiple {multiple:.1f}x vs {sub_segment} "
                f"reference {ref_multiple:.1f}x — outside ±25% band"
            )

    # ── Core formula ────────────────────────────────────────────────
    # Mid-cycle production = capacity (MTPA) × mid_util (decimal).
    # Mid-cycle EBITDA = production × EBITDA-per-tonne.
    # MTPA carries an implicit 10^6 multiplier (million tonnes); INR
    # values are in INR per tonne. Product is in INR × 10^6.
    # Convert INR → crores (÷ 10^7) → net divisor is 10.
    mid_util_dec = mid_util / 100.0
    mid_cycle_production_mtpa = capacity * mid_util_dec
    mid_cycle_ebitda_inr_cr = (
        mid_cycle_production_mtpa * ebitda_per_tonne / 10.0
    )

    # Also surface the implied revenue at mid-cycle for caller
    # transparency — not used in the EV computation but useful for
    # rendering the analysis-page narrative.
    mid_cycle_revenue_inr_cr = (
        mid_cycle_production_mtpa * realization / 10.0
    )

    enterprise_value_inr_cr = mid_cycle_ebitda_inr_cr * multiple
    equity_value_inr_cr = enterprise_value_inr_cr - net_debt

    components["mid_cycle_production_mtpa"] = mid_cycle_production_mtpa
    components["mid_cycle_revenue_inr_cr"] = mid_cycle_revenue_inr_cr
    components["mid_cycle_ebitda_inr_cr"] = mid_cycle_ebitda_inr_cr
    components["enterprise_value_inr_cr"] = enterprise_value_inr_cr
    components["equity_value_inr_cr"] = equity_value_inr_cr

    if equity_value_inr_cr < 0:
        warns.append("negative equity value (net debt > EV) — distress")

    fv_per_share: Optional[float] = None
    if shares > 0 and equity_value_inr_cr > 0:
        # equity in INR crores → × 1e7 to INR → divide by shares.
        fv_per_share = (equity_value_inr_cr * 1e7) / shares
    elif shares <= 0:
        warns.append(
            "shares_outstanding not supplied — per-share FV unavailable"
        )

    return CementResult(
        fair_value_per_share=fv_per_share,
        mid_cycle_ebitda_inr_cr=mid_cycle_ebitda_inr_cr,
        enterprise_value_inr_cr=enterprise_value_inr_cr,
        components=components,
        cycle_position_signal=cycle_position,
        method="cement_capacity_utilization",
        sanity_warnings=warns,
    )


# ─────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────

def is_cement_applicable(
    ticker: str, sector: Optional[str]
) -> tuple[bool, str]:
    """True iff the ticker should be routed through this engine.

    Resolution order:
      1. Bare ticker present in CEMENT_TICKERS → True
      2. Sector substring matches a cement hint → True
      3. Otherwise → False

    Returns (applicable, reason) where ``reason`` is a short log /
    admin string — never user-facing.
    """
    bare = _bare_ticker(ticker)
    if bare in CEMENT_TICKERS:
        return True, (
            f"ticker {bare} in CEMENT_TICKERS ({CEMENT_TICKERS[bare]})"
        )

    if not sector:
        return False, "no sector hint and ticker not in CEMENT_TICKERS"

    s = sector.strip().lower()
    for hint in _CEMENT_SECTOR_HINTS:
        if hint in s:
            return True, f"sector matches cement hint '{hint}'"

    return False, f"sector '{sector}' does not match cement hints"


# ─────────────────────────────────────────────────────────────────
# Result serialization
# ─────────────────────────────────────────────────────────────────

def to_dict(result: CementResult) -> dict:
    """JSON-safe projection — every value is a plain Python primitive.

    The ``components`` dict is shallow-copied; the caller can mutate
    the returned dict without polluting the source result.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "mid_cycle_ebitda_inr_cr": result.mid_cycle_ebitda_inr_cr,
        "enterprise_value_inr_cr": result.enterprise_value_inr_cr,
        "components": dict(result.components or {}),
        "cycle_position_signal": result.cycle_position_signal,
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
    }


__all__ = [
    "CementSubSegment",
    "CyclePosition",
    "CementInputs",
    "CementResult",
    "CEMENT_TICKERS",
    "SEGMENT_MULTIPLES",
    "classify_cycle_position",
    "compute_cement_fv",
    "is_cement_applicable",
    "to_dict",
]
