"""Logistics & freight valuation service — T3.15 Phase A.

Why this exists
───────────────
Indian listed logistics breaks into six structurally different cost
and asset models that a generic DCF on trailing FCF mis-prices:

  - **Road express** (TCI, BLUEDART, GATI, TCIEXP): truck fleet +
    hub-and-spoke. Volume × revenue/kg × yield × asset turn ×
    utilization. Diesel + driver are the dominant cost levers — when
    crude bumps 15% or wage hikes flow through, EBITDA margin
    swings 200-400bp.
  - **Container rail** (CONCOR): franchise moat from Indian Railways
    exclusivity; capex-heavy terminal infra; volumes in TEUs not MT.
    Trades at a premium multiple (15x) because the moat is durable
    and railway rates are policy-anchored.
  - **Container shipping** (SCI): commoditized global freight rates;
    BDI / SCFI cycle whipsaw makes trailing EBITDA noisy. Low
    multiple (6-7x) reflects no pricing power.
  - **Warehousing** (no pure-plays public yet; covered as a
    classification): rental yield + lease-tenor economics. Trades
    closer to a REIT multiple (~20x).
  - **3PL / supply chain** (MAHLOG, ALLCARGO): asset-light, tech-
    enabled, customer-stickiness. Premium 18x reflects the operating
    leverage of a software-margin layer over outsourced fleet.
  - **Tanker shipping** (GESHIP): commoditized like container
    shipping but on crude / product tanker rates. Same low-multiple
    treatment (6x).

GOFASHION explicitly excluded — it's apparel retail, not logistics.
Brokers and old-economy classifiers sometimes lump it in; we don't.

Industry-standard frame used by every sell-side logistics analyst:

    Revenue  = annual_volume × revenue_per_unit
    EBITDA   = Revenue × operating_margin
    EV       = EBITDA × EV/EBITDA multiple
    Equity   = EV - net_debt
    Fair val = Equity / shares_outstanding

The yield-per-unit growth term informs Phase B (composite weighting
toward yield-sensitive sectors); in Phase A it is captured on the
result dict but does not yet scale the EBITDA — the engine values at
the CURRENT yield, with the growth term carried forward as a hint.

Cost-pressure label
───────────────────
Road express tickers carry two dominant variable-cost lines —
diesel and driver wages. When either crosses an analyst-watch
threshold, sell-side notes flag it. We surface the same chip:

  - diesel_pct > 25% of revenue       → "diesel_squeeze"
  - driver_pct > 14% of revenue       → "labor_pressure"
  - both within band                  → "normal"

Diesel takes precedence when both fire — diesel is shorter-cycle
(weeks to recover via fuel surcharges); labor is structural.

Caller contract
───────────────
``compute_logistics_fv(inputs)`` is the single entry point. It
produces a ``LogisticsResult`` with a per-share fair value, the
revenue / EBITDA waterfall, a transparent ``components`` dict, an
``operating_leverage_ratio`` (fixed-cost intensity proxy), and a
``cost_pressure_label`` ("diesel_squeeze" / "labor_pressure" /
"normal").

``classify_cost_pressure(diesel_pct, driver_pct)`` is the public
helper exposing the threshold logic so the analysis-page narrative
and any router-side dispatch render the same label consistently.

``is_logistics_applicable(ticker, sector)`` covers router dispatch
when the caller only has a sector hint.

Discipline
──────────
- Returns ``fair_value_per_share=None`` and an "unavailable" cost
  pressure label when inputs don't allow a computation. Never
  silently substitutes a fallback FV.
- Sanity warnings are observational, not gating. Caller decides.
- Phase A is standalone — no router wiring, no manifest read-path
  invalidation of existing rows (manifest entry is documentation-
  only). Phase B (separate PR) routes the 9 logistics tickers
  through this engine and surfaces the cost-pressure chip on the
  analysis page.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.logistics_freight")


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

LogisticsSegment = Literal[
    "road_express",
    "container_rail",
    "container_shipping",
    "warehousing",
    "3pl_supply_chain",
    "tanker_shipping",
]

CostPressureLabel = Literal[
    "diesel_squeeze",
    "labor_pressure",
    "normal",
    "unavailable",
]


@dataclass
class LogisticsInputs:
    """Inputs to the logistics freight engine.

    Units:
      - ``annual_volume_mt``: million tonnes for tonnage-based
        segments (road / shipping / 3PL by weight); million TEUs for
        container segments (CONCOR). The dataclass does not enforce
        which — the caller picks the right ``revenue_per_unit_inr``
        to match (₹/kg for tonnage; ₹/TEU for containers).
      - ``revenue_per_unit_inr``: average realized revenue per unit
        of volume. Road express typically ₹12-20/kg; CONCOR
        ₹25,000-35,000/TEU.
      - ``operating_margin_pct``: PERCENTAGE POINTS (12.0 means 12%).
      - ``fleet_utilization_pct``: PERCENTAGE POINTS (70.0 means
        70%). Reflects truck/box turn — how many days of the year
        the asset is earning.
      - ``diesel_cost_pct_of_revenue``: PERCENTAGE POINTS. Default
        22% reflects the FY24 cohort average for road express;
        container rail is ~0 (electric traction); shipping is ~25-30
        on bunker oil.
      - ``driver_cost_pct_of_revenue``: PERCENTAGE POINTS. Default
        12% reflects the FY24 road-express cohort.
      - ``yield_per_unit_growth_pct_3y``: PERCENTAGE POINTS.
        Recorded for Phase B; not currently used to scale EBITDA.
      - ``ev_ebitda_multiple``: caller-supplied; default 14x is the
        cohort midpoint. Use ``SEGMENT_MULTIPLES`` for per-segment
        anchors.
      - ``net_debt_inr_cr``: INR crores (1 cr = 1e7 INR).
      - ``shares_outstanding``: raw share count (not in crores).
    """

    annual_volume_mt: float
    revenue_per_unit_inr: float
    operating_margin_pct: float
    fleet_utilization_pct: float = 70.0
    diesel_cost_pct_of_revenue: float = 22.0
    driver_cost_pct_of_revenue: float = 12.0
    yield_per_unit_growth_pct_3y: float = 6.0
    ev_ebitda_multiple: float = 14.0
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0
    segment: LogisticsSegment = "road_express"


@dataclass
class LogisticsResult:
    """Unified result shape for the logistics engine.

    ``components`` carries the full breakdown so callers can render
    the volume → revenue → EBITDA → EV → equity → per-share waterfall
    transparently. ``method`` is ``"logistics_freight_volume_yield"``
    on a successful computation and ``"unavailable"`` when inputs
    prevent it.

    ``operating_leverage_ratio`` is a proxy for fixed-cost intensity:
    higher utilization implies more revenue spread over the same fleet
    cost base, so the ratio scales with utilization. Used by the
    Phase B narrative to flag asset-heavy vs asset-light operators.
    """

    fair_value_per_share: Optional[float]
    revenue_inr_cr: float
    ebitda_inr_cr: float
    operating_leverage_ratio: float
    components: dict = field(default_factory=dict)
    cost_pressure_label: CostPressureLabel = "normal"
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Ticker registry
# ─────────────────────────────────────────────────────────────────

# Bare tickers (no .NS) → segment. Used for router-side dispatch.
# GOFASHION (apparel retail) is intentionally excluded — sometimes
# mis-classified by external feeds, but not a logistics name.
LOGISTICS_TICKERS: dict[str, LogisticsSegment] = {
    "TCI":      "road_express",
    "BLUEDART": "road_express",
    "GATI":     "road_express",
    "TCIEXP":   "road_express",
    "CONCOR":   "container_rail",
    "MAHLOG":   "3pl_supply_chain",
    "ALLCARGO": "3pl_supply_chain",
    "SCI":      "container_shipping",
    "GESHIP":   "tanker_shipping",
}


# Mid-cycle multiples by segment. Used as the default when caller
# does not override ``ev_ebitda_multiple`` and as the reference band
# for the sanity warning when the caller's multiple is far from the
# historical mid-cycle.
SEGMENT_MULTIPLES: dict[LogisticsSegment, float] = {
    "road_express":        16.0,   # premium for organized + tech-enabled
    "container_rail":      15.0,   # CONCOR moat (IR exclusivity)
    "container_shipping":   7.0,   # commoditized global rates
    "warehousing":         20.0,   # rental yield premium (REIT-adjacent)
    "3pl_supply_chain":    18.0,   # asset-light, customer-sticky
    "tanker_shipping":      6.0,   # commoditized like containers
}


# Sector / industry strings that should route through this engine.
# Matched case-insensitively as substring on the caller-supplied
# sector hint.
_LOGISTICS_SECTOR_HINTS = (
    "logistic",
    "freight",
    "transport",
    "shipping",
    "courier",
    "express delivery",
    "supply chain",
    "3pl",
    "warehous",  # warehouse / warehousing
)


# ─────────────────────────────────────────────────────────────────
# Cost-pressure thresholds
# ─────────────────────────────────────────────────────────────────

# Above this, road-express EBITDA margin is squeezed unless fuel
# surcharges have flowed through fully. Matches sell-side analyst
# watch level for FY24 cohort (cohort mean was ~22%, +3pp is
# stress).
_DIESEL_SQUEEZE_PCT = 25.0

# Above this, driver costs are flagging structural wage inflation
# (e-commerce + minimum-wage hikes). Cohort mean was ~12%, +2pp is
# the analyst chip-fire level.
_LABOR_PRESSURE_PCT = 14.0

# Sanity boundaries on utilization. Truck fleets running below 55%
# are economically broken — the fleet finance + insurance + drivers
# costs are largely fixed. Above 90% is unsustainable — implies no
# turnaround buffer for maintenance / monsoon disruption.
_UTIL_BREAKEVEN_PCT = 55.0
_UTIL_STRETCHED_PCT = 90.0

# Sanity boundaries on operating margin. Road logistics cohort
# historically prints 8-18% EBITDA margin; container rail and 3PL
# stretch toward 20-25%; shipping cycles between -5% and +35%.
_MARGIN_LOW_PCT = 5.0
_MARGIN_HIGH_PCT = 35.0


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against LOGISTICS_TICKERS."""
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
# Cost pressure
# ─────────────────────────────────────────────────────────────────

def classify_cost_pressure(
    diesel_pct: float,
    driver_pct: float,
) -> CostPressureLabel:
    """Bucket the variable-cost mix into a single analyst-chip label.

    Precedence order:
      1. Diesel pressure (shorter-cycle, faster to re-rate margins).
      2. Driver / labor pressure (structural, slower to recover).
      3. Otherwise "normal".

    Public helper so the analysis-page narrative and any router-side
    dispatch render the same label without re-inventing the
    thresholds.
    """
    d = _safe_pos(diesel_pct)
    l = _safe_pos(driver_pct)

    if d > _DIESEL_SQUEEZE_PCT:
        return "diesel_squeeze"
    if l > _LABOR_PRESSURE_PCT:
        return "labor_pressure"
    return "normal"


# ─────────────────────────────────────────────────────────────────
# Core engine
# ─────────────────────────────────────────────────────────────────

def compute_logistics_fv(inputs: LogisticsInputs) -> LogisticsResult:
    """Volume × revenue/unit × margin × multiple - net_debt.

    The framework values the company at the CURRENT yield and
    utilization. The yield-growth term is recorded for Phase B but
    does not scale EBITDA today — the standalone engine deliberately
    avoids stacking too many assumption layers in v1.

    Returns ``LogisticsResult`` with method
    ``"logistics_freight_volume_yield"`` on success and
    ``"unavailable"`` when inputs prevent it.
    """
    warns: list[str] = []

    volume = _safe_pos(inputs.annual_volume_mt)
    revenue_per_unit = _safe_pos(inputs.revenue_per_unit_inr)
    margin_pct = _safe_pos(inputs.operating_margin_pct)
    utilization = _safe_pos(inputs.fleet_utilization_pct)
    diesel_pct = _safe_pos(inputs.diesel_cost_pct_of_revenue)
    driver_pct = _safe_pos(inputs.driver_cost_pct_of_revenue)
    yield_growth = _safe_pos(inputs.yield_per_unit_growth_pct_3y)
    multiple = _safe_pos(inputs.ev_ebitda_multiple)
    net_debt = _safe_pos(inputs.net_debt_inr_cr)
    shares = _safe_pos(inputs.shares_outstanding)
    segment = (
        inputs.segment if inputs.segment in SEGMENT_MULTIPLES
        else "road_express"
    )

    cost_pressure = classify_cost_pressure(diesel_pct, driver_pct)

    components: dict = {
        "annual_volume_mt": volume,
        "revenue_per_unit_inr": revenue_per_unit,
        "operating_margin_pct": margin_pct,
        "fleet_utilization_pct": utilization,
        "diesel_cost_pct_of_revenue": diesel_pct,
        "driver_cost_pct_of_revenue": driver_pct,
        "yield_per_unit_growth_pct_3y": yield_growth,
        "ev_ebitda_multiple": multiple,
        "net_debt_inr_cr": net_debt,
        "shares_outstanding": shares,
        "segment": segment,
        "cost_pressure_label": cost_pressure,
    }

    # ── Defensive guards ────────────────────────────────────────────
    if volume <= 0:
        warns.append(
            "non-positive annual volume — logistics FV cannot compute"
        )
        return LogisticsResult(
            fair_value_per_share=None,
            revenue_inr_cr=0.0,
            ebitda_inr_cr=0.0,
            operating_leverage_ratio=0.0,
            components=components,
            cost_pressure_label="unavailable",
            method="unavailable",
            sanity_warnings=warns,
        )

    if revenue_per_unit <= 0:
        warns.append(
            "non-positive revenue per unit — logistics FV cannot compute"
        )
        return LogisticsResult(
            fair_value_per_share=None,
            revenue_inr_cr=0.0,
            ebitda_inr_cr=0.0,
            operating_leverage_ratio=0.0,
            components=components,
            cost_pressure_label="unavailable",
            method="unavailable",
            sanity_warnings=warns,
        )

    if margin_pct <= 0:
        warns.append(
            "non-positive operating margin — logistics FV cannot compute"
        )
        return LogisticsResult(
            fair_value_per_share=None,
            revenue_inr_cr=0.0,
            ebitda_inr_cr=0.0,
            operating_leverage_ratio=0.0,
            components=components,
            cost_pressure_label=cost_pressure,
            method="unavailable",
            sanity_warnings=warns,
        )

    if multiple <= 0:
        warns.append(
            "non-positive EV/EBITDA multiple — logistics FV cannot compute"
        )
        return LogisticsResult(
            fair_value_per_share=None,
            revenue_inr_cr=0.0,
            ebitda_inr_cr=0.0,
            operating_leverage_ratio=0.0,
            components=components,
            cost_pressure_label=cost_pressure,
            method="unavailable",
            sanity_warnings=warns,
        )

    # ── Observational sanity warnings ───────────────────────────────
    if utilization > 0 and utilization < _UTIL_BREAKEVEN_PCT:
        warns.append(
            f"fleet utilization {utilization:.1f}% < {_UTIL_BREAKEVEN_PCT:.0f}% "
            "— below typical logistics breakeven (fixed costs heavy)"
        )
    if utilization > _UTIL_STRETCHED_PCT:
        warns.append(
            f"fleet utilization {utilization:.1f}% > {_UTIL_STRETCHED_PCT:.0f}% "
            "— stretched; no buffer for maintenance / monsoon disruption"
        )

    if margin_pct < _MARGIN_LOW_PCT:
        warns.append(
            f"operating margin {margin_pct:.1f}% < {_MARGIN_LOW_PCT:.0f}% "
            "— trough; cost-pressure squeeze or volume shock"
        )
    elif margin_pct > _MARGIN_HIGH_PCT:
        warns.append(
            f"operating margin {margin_pct:.1f}% > {_MARGIN_HIGH_PCT:.0f}% "
            "— peak; likely shipping-cycle top or one-off boost"
        )

    # Multiple-vs-segment sanity check. ±25% band around the segment
    # reference multiple — beyond that, flag for review.
    ref_multiple = SEGMENT_MULTIPLES.get(segment, 14.0)
    if ref_multiple > 0:
        ratio = multiple / ref_multiple
        if ratio < 0.75 or ratio > 1.25:
            warns.append(
                f"EV/EBITDA multiple {multiple:.1f}x vs {segment} "
                f"reference {ref_multiple:.1f}x — outside ±25% band"
            )

    if cost_pressure == "diesel_squeeze":
        warns.append(
            f"diesel {diesel_pct:.1f}% > {_DIESEL_SQUEEZE_PCT:.0f}% of revenue "
            "— margin squeezed unless fuel surcharges flow through"
        )
    elif cost_pressure == "labor_pressure":
        warns.append(
            f"driver wages {driver_pct:.1f}% > {_LABOR_PRESSURE_PCT:.0f}% of revenue "
            "— structural wage inflation pressure"
        )

    # ── Core formula ────────────────────────────────────────────────
    # Volume is in millions of units (MT or TEU); revenue_per_unit is
    # INR per unit. Product is in INR × 10^6. Convert to INR crores
    # (÷ 10^7) → net divisor 10.
    revenue_inr_cr = volume * revenue_per_unit / 10.0
    ebitda_inr_cr = revenue_inr_cr * (margin_pct / 100.0)
    enterprise_value_inr_cr = ebitda_inr_cr * multiple
    equity_value_inr_cr = enterprise_value_inr_cr - net_debt

    # Operating-leverage proxy: scales with utilization, falls when
    # utilization is low (fixed fleet cost spread over fewer revenue
    # units). Bounded to a usable [0, 2] band — anything above 1 means
    # the company is running its assets harder than the cohort mean
    # (70%); below 1 means slack.
    util_dec = max(0.0, utilization) / 70.0
    operating_leverage_ratio = round(util_dec, 4)

    components["revenue_inr_cr"] = revenue_inr_cr
    components["ebitda_inr_cr"] = ebitda_inr_cr
    components["enterprise_value_inr_cr"] = enterprise_value_inr_cr
    components["equity_value_inr_cr"] = equity_value_inr_cr
    components["operating_leverage_ratio"] = operating_leverage_ratio

    if equity_value_inr_cr < 0:
        warns.append(
            "negative equity value (net debt > EV) — distress"
        )

    fv_per_share: Optional[float] = None
    if shares > 0 and equity_value_inr_cr > 0:
        # equity in INR crores → × 1e7 to INR → divide by shares.
        fv_per_share = (equity_value_inr_cr * 1e7) / shares
    elif shares <= 0:
        warns.append(
            "shares_outstanding not supplied — per-share FV unavailable"
        )

    return LogisticsResult(
        fair_value_per_share=fv_per_share,
        revenue_inr_cr=revenue_inr_cr,
        ebitda_inr_cr=ebitda_inr_cr,
        operating_leverage_ratio=operating_leverage_ratio,
        components=components,
        cost_pressure_label=cost_pressure,
        method="logistics_freight_volume_yield",
        sanity_warnings=warns,
    )


# ─────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────

def is_logistics_applicable(
    ticker: str, sector: Optional[str]
) -> tuple[bool, str]:
    """True iff the ticker should be routed through this engine.

    Resolution order:
      1. Bare ticker present in LOGISTICS_TICKERS → True
      2. Sector substring matches a logistics hint → True
      3. Otherwise → False

    Returns (applicable, reason) where ``reason`` is a short log /
    admin string — never user-facing.
    """
    bare = _bare_ticker(ticker)
    if bare in LOGISTICS_TICKERS:
        return True, (
            f"ticker {bare} in LOGISTICS_TICKERS "
            f"({LOGISTICS_TICKERS[bare]})"
        )

    # Explicit GOFASHION exclusion (apparel retail mis-classified by
    # some feeds — guard against future drift).
    if bare == "GOFASHION":
        return False, "GOFASHION is apparel retail, not logistics"

    if not sector:
        return False, "no sector hint and ticker not in LOGISTICS_TICKERS"

    s = sector.strip().lower()
    for hint in _LOGISTICS_SECTOR_HINTS:
        if hint in s:
            return True, f"sector matches logistics hint '{hint}'"

    return False, f"sector '{sector}' does not match logistics hints"


# ─────────────────────────────────────────────────────────────────
# Result serialization
# ─────────────────────────────────────────────────────────────────

def to_dict(result: LogisticsResult) -> dict:
    """JSON-safe projection — every value is a plain Python primitive.

    The ``components`` dict is shallow-copied; the caller can mutate
    the returned dict without polluting the source result.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "revenue_inr_cr": result.revenue_inr_cr,
        "ebitda_inr_cr": result.ebitda_inr_cr,
        "operating_leverage_ratio": result.operating_leverage_ratio,
        "components": dict(result.components or {}),
        "cost_pressure_label": result.cost_pressure_label,
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
    }


__all__ = [
    "LogisticsSegment",
    "CostPressureLabel",
    "LogisticsInputs",
    "LogisticsResult",
    "LOGISTICS_TICKERS",
    "SEGMENT_MULTIPLES",
    "classify_cost_pressure",
    "compute_logistics_fv",
    "is_logistics_applicable",
    "to_dict",
]
