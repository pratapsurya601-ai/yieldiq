"""Steel cost-curve valuation service — T3.9 Phase A.

Why this exists
───────────────
Indian listed steel and primary-aluminium tickers (TATASTEEL, JSWSTEEL,
SAIL, JINDALSTEL, HINDALCO, VEDL, WELCORP, JSL) share one structural
feature that generic DCF mis-prices: steel is a commodity whose
realized price moves on a global cycle, while each producer's cost per
tonne is **fixed by its position on the global cost curve**. Through a
full cycle, low-cost producers (Q1) earn an EBITDA-per-tonne spread on
every tonne sold; high-cost producers (Q4) earn only during tight
markets and post losses in troughs.

The analyst-standard framework is therefore:

    EBITDA_per_tonne  =  realization_per_tonne - cost_per_tonne
                         + integration_credit_per_tonne
    mid_cycle_EBITDA  =  capacity × mid_cycle_utilization × EBITDA_per_t
    EV                =  mid_cycle_EBITDA × (quartile_multiple
                                             + integration_premium)
    equity            =  EV - net_debt
    fair_value/share  =  equity ÷ shares_outstanding

Where:

    quartile_multiple    is dictated by cost-curve position
        (Q1 lowest → highest multiple; Q4 highest cost → lowest)
    integration_premium  is an additive 0–1.0× kicker reflecting that
        captive iron ore / coking coal insulates EBITDA in a trough
        and is a recurring value source through the cycle

Generic DCF on trailing free cash flow whipsaws with the cycle:
trailing-12-month FCF at a cycle peak overstates intrinsic value;
trailing FCF at a trough understates it. The cost-curve / mid-cycle
EBITDA frame is the standard anchor in equity research and is what
all-Indian-broker sell-side models use for these names.

Caller contract
───────────────
- ``compute_steel_fv(inputs)`` produces a ``SteelResult`` containing a
  per-share fair value (when shares > 0) and the per-component
  breakdown so the analysis surface can render a transparent waterfall.
- ``is_steel_applicable(ticker, sector)`` routes the eight named
  tickers and matches a sector-hint substring for unknown tickers.
- ``to_dict(result)`` projects the dataclass to a JSON-safe dict.

Discipline
──────────
- Returns ``method="unavailable"`` and ``fair_value_per_share=None``
  when inputs do not allow a computation — never substitutes a
  silent fallback.
- Sanity warnings are observational, not gating. The caller decides
  whether to surface, suppress, or override.
- Phase A is standalone — no router wiring, no read-path entry in
  the analysis cache shape. The manifest entry is documentation-
  only (empty fields list). Phase B (separate PR) routes the eight
  steel tickers through this engine and surfaces the waterfall.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.steel_cost_curve")


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

# Q1 = lowest cost quartile (best cost position, highest multiple),
# Q4 = highest cost quartile (worst, lowest multiple). Producers
# slide between quartiles over multi-year horizons (capex /
# decarb / energy-cost shifts), but for a single Phase-A fair-
# value snapshot the quartile label is fixed.
CostCurveQuartile = Literal["q1", "q2", "q3", "q4"]


@dataclass
class SteelInputs:
    """Inputs to the steel cost-curve fair-value engine.

    Units:
        capacity in MTPA (million tonnes per annum)
        utilization fields in PERCENTAGE POINTS (82.0 means 82%)
        realization / cost in INR per tonne
        net debt in INR crore
        shares in absolute count

    ``mid_cycle_utilization_pct`` defaults to 82% — the through-cycle
    average for the Indian primary-steel cohort. Caller can override
    for tickers with structurally lower run-rate utilization (e.g.
    a producer mid-expansion).
    """

    crude_steel_capacity_mtpa: float
    current_utilization_pct: float
    mid_cycle_utilization_pct: float = 82.0
    realization_per_tonne_inr: float = 60000.0
    cost_per_tonne_inr: float = 48000.0
    cost_curve_quartile: CostCurveQuartile = "q2"
    ev_ebitda_multiple_mid_cycle: float = 6.5
    iron_ore_integration_pct: float = 50.0
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0


@dataclass
class SteelResult:
    """Output of the steel cost-curve engine.

    ``components`` carries the intermediate values so the caller can
    render a SOTP-style waterfall (EBITDA/t → mid-cycle EBITDA → EV
    → equity → per-share) without recomputing.

    ``method`` records which path produced the result so downstream
    consumers can distinguish a clean computation from the
    ``"unavailable"`` short-circuit.
    """

    fair_value_per_share: Optional[float]
    through_cycle_ebitda_per_tonne: float
    mid_cycle_ebitda_inr_cr: float
    integration_premium_pct: float
    components: dict = field(default_factory=dict)
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Ticker registry + multiple tables
# ─────────────────────────────────────────────────────────────────

# Bare ticker → default cost-curve quartile. The quartile is the
# anchor; per-call overrides are still respected via SteelInputs.
# Rationale per name:
#   JSWSTEEL  q1 — among lowest-cost global producers (captive iron
#                  ore + scale + Bellary location)
#   TATASTEEL q2 — strong Indian cost position; Europe ops drag
#   JINDALSTEL q2 — Angul integrated; mid-cost
#   HINDALCO  q2 — aluminium leverages Novelis + captive bauxite
#   VEDL      q2 — diversified resources; aluminium / zinc / iron ore
#   SAIL      q3 — legacy PSU; higher cost base
#   WELCORP   q3 — pipes / value-add steel; smaller scale
#   JSL       q3 — specialty stainless; small-scale premium
STEEL_TICKERS: dict[str, CostCurveQuartile] = {
    "TATASTEEL":  "q2",
    "JSWSTEEL":   "q1",
    "SAIL":       "q3",
    "JINDALSTEL": "q2",
    "HINDALCO":   "q2",
    "VEDL":       "q2",
    "WELCORP":    "q3",
    "JSL":        "q3",
}


# Through-cycle EV/EBITDA multiples by cost-curve quartile. These
# are the analyst-standard mid-cycle multiples applied to mid-cycle
# EBITDA — they reflect the durability of EBITDA across the cycle,
# not a single point-in-time peer multiple.
#   Q1 (lowest cost) earns through the entire cycle → highest mult
#   Q4 (highest cost) only earns in tight markets → lowest mult
QUARTILE_MULTIPLES: dict[CostCurveQuartile, float] = {
    "q1": 7.5,
    "q2": 6.5,
    "q3": 5.0,
    "q4": 4.0,
}


# Sector / industry strings that should route through this engine.
# Matched case-insensitively as substring on the caller-supplied
# sector hint. The aluminium hit is intentional — HINDALCO / VEDL
# value the same way as primary steel (commodity × cost-curve
# position × cycle), so they share the framework.
_STEEL_SECTOR_HINTS = (
    "steel",
    "iron",
    "metals",
    "metals & mining",
    "metals and mining",
    "aluminium",
    "aluminum",
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip the ``.NS`` / ``.BO`` suffix and uppercase.

    Defensive — callers sometimes pass the Yahoo-style suffixed
    symbol and sometimes the bare BSE/NSE code.
    """
    if not ticker:
        return ""
    t = ticker.strip().upper()
    for suffix in (".NS", ".BO"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return t


def _safe_pos(value: Optional[float]) -> float:
    """Coerce to float; non-finite or None → 0.0."""
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    # NaN / inf guard
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    return v


# ─────────────────────────────────────────────────────────────────
# Integration premium
# ─────────────────────────────────────────────────────────────────

def compute_cost_curve_premium(integration_pct: float) -> float:
    """Iron-ore / coking-coal integration premium on EV/EBITDA.

    Tiered additive kicker to the quartile multiple. Rationale: a
    fully-integrated producer locks in raw-material cost through a
    trough — when spot iron ore spikes, the captive miner harvests
    the full delta rather than passing it through cost.

    Tiers (percentage points of integration → additive multiple):
        ≥ 70%   → +1.0x
        40-69%  → +0.5x
        < 40%   →  0.0x

    Negative or non-finite values clamp to 0.0.
    """
    pct = _safe_pos(integration_pct)
    if pct >= 70.0:
        return 1.0
    if pct >= 40.0:
        return 0.5
    return 0.0


# ─────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────

def compute_steel_fv(inputs: SteelInputs) -> SteelResult:
    """Cost-curve mid-cycle EV/EBITDA → per-share fair value.

    Steps:
        1. through_cycle_EBITDA_per_t  = realization - cost
                                          + integration_credit_per_t
           (integration credit here is implicit in the cost figure —
            we surface the multiple-premium separately; see note
            below)
        2. mid_cycle_EBITDA_INR_cr     = capacity_MTPA
                                          × mid_cycle_util/100
                                          × through_cycle_EBITDA_per_t
                                          × 10  (MTPA × INR/t → INR cr)
        3. effective_multiple          = quartile_multiple
                                          + integration_premium
        4. EV_INR_cr                    = mid_cycle_EBITDA × effective_multiple
        5. equity_INR_cr                = EV - net_debt
        6. fair_value_per_share         = equity × 1e7 / shares  (cr → INR)

    Note on integration credit-vs-premium: integration shows up
    twice in real cost-curve models — once in a lower realized
    cost per tonne (already captured in ``cost_per_tonne_inr``
    when the caller supplies an integrated cost) and once as a
    multiple-premium reflecting durability through the cycle. We
    surface ONLY the multiple-premium here; the caller is expected
    to feed the integrated cost in ``cost_per_tonne_inr`` directly.

    Returns ``SteelResult`` with ``method="cost_curve_ev_ebitda"`` on
    success or ``method="unavailable"`` when inputs are degenerate
    (zero capacity, negative through-cycle EBITDA per tonne with no
    integration cushion, etc.).
    """
    warns: list[str] = []
    components: dict = {}

    capacity = _safe_pos(inputs.crude_steel_capacity_mtpa)
    current_util = _safe_pos(inputs.current_utilization_pct)
    mid_util = _safe_pos(inputs.mid_cycle_utilization_pct)
    realization = _safe_pos(inputs.realization_per_tonne_inr)
    cost = _safe_pos(inputs.cost_per_tonne_inr)
    integration_pct = _safe_pos(inputs.iron_ore_integration_pct)
    net_debt_cr = _safe_pos(inputs.net_debt_inr_cr)
    shares = _safe_pos(inputs.shares_outstanding)

    quartile = inputs.cost_curve_quartile
    if quartile not in QUARTILE_MULTIPLES:
        warns.append(
            f"unknown cost-curve quartile '{quartile}' — defaulting to q2"
        )
        quartile = "q2"

    quartile_multiple = QUARTILE_MULTIPLES[quartile]
    integration_premium = compute_cost_curve_premium(integration_pct)
    effective_multiple = quartile_multiple + integration_premium

    through_cycle_ebitda_per_t = realization - cost

    # Cycle-position observation: current utilization vs mid-cycle
    if mid_util > 0 and current_util > 0:
        cycle_gap = current_util - mid_util
        if cycle_gap >= 8.0:
            warns.append(
                "current utilization runs hot vs mid-cycle "
                f"({current_util:.0f}% vs {mid_util:.0f}%) — cycle "
                "peak; mid-cycle EBITDA is below trailing"
            )
        elif cycle_gap <= -10.0:
            warns.append(
                "current utilization below mid-cycle "
                f"({current_util:.0f}% vs {mid_util:.0f}%) — cycle "
                "trough; mid-cycle EBITDA is above trailing"
            )

    components["capacity_mtpa"] = capacity
    components["current_utilization_pct"] = current_util
    components["mid_cycle_utilization_pct"] = mid_util
    components["realization_per_tonne_inr"] = realization
    components["cost_per_tonne_inr"] = cost
    components["through_cycle_ebitda_per_tonne"] = through_cycle_ebitda_per_t
    components["cost_curve_quartile"] = quartile
    components["quartile_multiple"] = quartile_multiple
    components["integration_pct"] = integration_pct
    components["integration_premium"] = integration_premium
    components["effective_multiple"] = effective_multiple
    components["net_debt_inr_cr"] = net_debt_cr
    components["shares_outstanding"] = shares

    # Defensive: degenerate inputs short-circuit to unavailable
    if capacity <= 0:
        warns.append("non-positive capacity — fair value unavailable")
        return SteelResult(
            fair_value_per_share=None,
            through_cycle_ebitda_per_tonne=through_cycle_ebitda_per_t,
            mid_cycle_ebitda_inr_cr=0.0,
            integration_premium_pct=integration_premium,
            components=components,
            method="unavailable",
            sanity_warnings=warns,
        )

    if mid_util <= 0:
        warns.append("non-positive mid-cycle utilization — fair value unavailable")
        return SteelResult(
            fair_value_per_share=None,
            through_cycle_ebitda_per_tonne=through_cycle_ebitda_per_t,
            mid_cycle_ebitda_inr_cr=0.0,
            integration_premium_pct=integration_premium,
            components=components,
            method="unavailable",
            sanity_warnings=warns,
        )

    if through_cycle_ebitda_per_t <= 0:
        warns.append(
            f"non-positive through-cycle EBITDA/t "
            f"({through_cycle_ebitda_per_t:,.0f} INR/t) — producer "
            "structurally loss-making through cycle"
        )
        # We still return a result so the caller can render the
        # waterfall, but per-share fair value is None.
        return SteelResult(
            fair_value_per_share=None,
            through_cycle_ebitda_per_tonne=through_cycle_ebitda_per_t,
            mid_cycle_ebitda_inr_cr=0.0,
            integration_premium_pct=integration_premium,
            components=components,
            method="unavailable",
            sanity_warnings=warns,
        )

    # Mid-cycle EBITDA in INR crore.
    # capacity (MTPA = million tonnes/yr) × utilization fraction
    # × INR/tonne → INR/yr. Divide by 1e7 → crore. capacity carries
    # an implicit 1e6 multiplier; divisor net is 10.
    mid_cycle_ebitda_inr_cr = (
        capacity * (mid_util / 100.0) * through_cycle_ebitda_per_t / 10.0
    )

    ev_inr_cr = mid_cycle_ebitda_inr_cr * effective_multiple
    equity_inr_cr = ev_inr_cr - net_debt_cr

    components["mid_cycle_ebitda_inr_cr"] = mid_cycle_ebitda_inr_cr
    components["ev_inr_cr"] = ev_inr_cr
    components["equity_inr_cr"] = equity_inr_cr

    if equity_inr_cr < 0:
        warns.append(
            "negative equity value (net debt > EV) — distress"
        )

    # EBITDA-margin sanity check (observational)
    if realization > 0:
        ebitda_margin = through_cycle_ebitda_per_t / realization
        components["through_cycle_ebitda_margin"] = ebitda_margin
        if ebitda_margin > 0.35:
            warns.append(
                f"through-cycle EBITDA margin {ebitda_margin * 100:.0f}% "
                "exceeds 35% — verify cost figures are mid-cycle "
                "(could be cycle-peak)"
            )

    fv_per_share: Optional[float] = None
    if shares > 0 and equity_inr_cr > 0:
        # equity_inr_cr is in INR crores; multiply by 1e7 to get INR.
        fv_per_share = (equity_inr_cr * 1e7) / shares
    elif shares <= 0:
        warns.append(
            "shares_outstanding not supplied — per-share FV unavailable"
        )

    components["fair_value_per_share"] = fv_per_share

    return SteelResult(
        fair_value_per_share=fv_per_share,
        through_cycle_ebitda_per_tonne=through_cycle_ebitda_per_t,
        mid_cycle_ebitda_inr_cr=mid_cycle_ebitda_inr_cr,
        integration_premium_pct=integration_premium,
        components=components,
        method="cost_curve_ev_ebitda",
        sanity_warnings=warns,
    )


# ─────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────

def is_steel_applicable(
    ticker: str, sector: Optional[str]
) -> tuple[bool, str]:
    """True iff the ticker should be routed through this engine.

    Resolution order:
      1. Bare ticker present in STEEL_TICKERS → True
      2. Sector substring matches a steel hint → True
      3. Otherwise → False

    Returns ``(applicable, reason)`` where ``reason`` is a short
    log / admin string — never user-facing.
    """
    bare = _bare_ticker(ticker)
    if bare in STEEL_TICKERS:
        return True, (
            f"ticker {bare} in STEEL_TICKERS "
            f"(quartile {STEEL_TICKERS[bare]})"
        )

    if not sector:
        return False, "no sector hint and ticker not in STEEL_TICKERS"

    s = sector.strip().lower()
    for hint in _STEEL_SECTOR_HINTS:
        if hint in s:
            return True, f"sector matches steel hint '{hint}'"

    return False, f"sector '{sector}' does not match steel hints"


# ─────────────────────────────────────────────────────────────────
# Result serialization
# ─────────────────────────────────────────────────────────────────

def to_dict(result: SteelResult) -> dict:
    """JSON-safe projection — every value is a plain Python primitive.

    The ``components`` dict is shallow-copied so the caller can
    mutate the returned dict without polluting the source result.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "through_cycle_ebitda_per_tonne": result.through_cycle_ebitda_per_tonne,
        "mid_cycle_ebitda_inr_cr": result.mid_cycle_ebitda_inr_cr,
        "integration_premium_pct": result.integration_premium_pct,
        "components": dict(result.components or {}),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
    }


__all__ = [
    "CostCurveQuartile",
    "SteelInputs",
    "SteelResult",
    "STEEL_TICKERS",
    "QUARTILE_MULTIPLES",
    "compute_cost_curve_premium",
    "compute_steel_fv",
    "is_steel_applicable",
    "to_dict",
]
