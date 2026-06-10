"""Oil & Gas reserves-based valuation service — T3.7 Phase A.

Why this exists
───────────────
Indian listed oil & gas tickers (ONGC, OIL, IOC, BPCL, HPCL, RELIANCE,
GAIL, IGL, MGL, GUJGAS, PETRONET) span four structurally different
business models that no single valuation engine handles correctly:

  - **Upstream / E&P** (ONGC, OIL): fair value is dominated by PROVEN
    RESERVES × realized price minus extraction + royalty + cess + tax,
    discounted across the depletion curve. Generic DCF on trailing
    FCF misses that the asset base is exhaustible — a producer pumping
    250 MMBOE/yr against 5,500 MMBOE of reserves has a finite-life NPV
    profile, not a perpetuity.

  - **Downstream / Refining** (IOC, BPCL, HPCL): fair value tracks the
    refining margin (GRM) cycle. EV/EBITDA against mid-cycle GRM is
    the analyst-standard frame. P/E on trailing earnings whipsaws
    with GRM spikes; replacement-cost-per-tonne-of-refining-capacity
    is the cycle anchor.

  - **City Gas** (IGL, MGL, GUJGAS): volume × EBITDA-per-unit at a
    premium multiple (regulated utility-like growth with monopoly-ish
    geographic licenses).

  - **Integrated** (RELIANCE): refining + petrochem + retail + telecom.
    Single-multiple methods don't apply — needs SOTP (sum-of-the-parts)
    with each segment valued in its own frame.

Industry-standard formula for upstream:

    Reserves NPV = Σ_year (production × (price - opex - royalty - cess)
                            × (1 - tax) × (1 - depletion_factor)^year)
                    / (1 + r)^year

Probable reserves get a 50% probability weight; possible reserves are
excluded (too speculative to anchor a fair-value claim on).

For downstream:

    EV = Throughput (MMT) × utilization × bbl/MT × GRM (USD/bbl)
       × USD-INR × EBITDA-multiple
    Equity = EV - net debt

For city gas:

    EV = (CNG_vol + PNG_vol) × 365 × EBITDA/scm × multiple
    Equity = EV - net debt

For integrated:

    Equity = upstream_value + downstream_value + petrochem_value
             + other_value - net_debt

Caller contract
───────────────
The service exposes one entry point per segment plus a SOTP composer
for integrated names. ``select_method_for_ticker(ticker)`` routes the
11 named tickers to the correct segment; ``is_oil_gas_applicable``
covers the routing decision when the caller only has a sector hint.

Discipline
──────────
- Returns ``method="unavailable"`` when inputs don't allow a
  computation — never silently substitutes a fallback value.
- Sanity warnings are observational, not gating. Caller decides.
- Phase A is standalone — no router wiring, no manifest read-path
  invalidation of existing rows (manifest entry is documentation-
  only). Phase B routes the 11 oil-and-gas tickers through this
  engine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.oil_gas_valuation")


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

OilGasSegment = Literal[
    "upstream",
    "downstream",
    "integrated",
    "city_gas",
    "gas_transmission",
]


# Industry conversion constant: 1 metric tonne of crude ≈ 7.33 barrels.
# Used to translate refining throughput (reported in MMT) into GRM
# (denominated in USD/bbl). Caller can override per call if their
# inputs are already barrel-denominated.
_BARRELS_PER_METRIC_TONNE = 7.33


@dataclass
class UpstreamReserveInputs:
    """Inputs to the upstream reserves NPV engine.

    Reserve quantities are in million barrels of oil equivalent (MMBOE).
    Price / cost rates are in USD per BOE. Percentage fields are
    DECIMAL points (20.0 means 20%, not 0.20) — the suffix ``_pct``
    here is "percentage point" not "decimal rate", matching how Indian
    oil & gas disclosures publish royalty / cess.
    """

    proved_reserves_mmboe: float        # 1P reserves
    probable_reserves_mmboe: float = 0.0  # 2P delta over 1P
    annual_production_mmboe: float = 0.0
    realized_price_usd_per_boe: float = 70.0
    operating_cost_usd_per_boe: float = 25.0
    royalty_pct: float = 20.0           # India onshore
    cess_pct: float = 20.0
    income_tax_pct: float = 25.0
    discount_rate: float = 0.12
    usd_to_inr: float = 83.0


@dataclass
class DownstreamRefiningInputs:
    """Inputs to the downstream refining EV/EBITDA engine.

    ``ev_ebitda_multiple`` is mid-cycle by default; the caller can dial
    it down during a stressed cycle or up during a peak cycle to test
    sensitivity.
    """

    refining_throughput_mmt: float        # million metric tonnes/yr
    gross_refining_margin_usd_per_bbl: float = 8.0   # cycle midpoint
    capacity_utilization_pct: float = 95.0           # percentage points
    ev_ebitda_multiple: float = 6.5                  # mid-cycle
    net_debt_inr_cr: float = 0.0
    usd_to_inr: float = 83.0


@dataclass
class CityGasInputs:
    """Inputs to the city gas volume-multiple engine.

    Volumes in million standard cubic metres per day (MMSCM/day),
    EBITDA per unit in INR per SCM. The 14× default ``ebitda_multiple``
    reflects the historical city-gas premium for licensed geographic
    monopolies with regulated-utility-like volume growth.
    """

    cng_volume_mmscm_per_day: float
    png_volume_mmscm_per_day: float
    ebitda_per_unit_inr_per_scm: float = 6.5
    ebitda_multiple: float = 14.0
    net_debt_inr_cr: float = 0.0


@dataclass
class OilGasValuationResult:
    """Unified result shape across all segments.

    ``components`` carries the per-segment breakdown so callers can
    render the SOTP waterfall without recomputing. ``method`` records
    which engine produced the result so downstream consumers can route
    different surfaces (the integrated SOTP surface differs from the
    pure upstream surface).
    """

    fair_value_per_share: Optional[float]
    aggregate_value_inr_cr: Optional[float]
    components: dict = field(default_factory=dict)
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Ticker registry
# ─────────────────────────────────────────────────────────────────

# Bare tickers (no .NS) → segment. Used for router-side dispatch.
OIL_GAS_TICKERS: dict[str, OilGasSegment] = {
    "ONGC":      "upstream",
    "OIL":       "upstream",
    "IOC":       "downstream",
    "BPCL":      "downstream",
    "HPCL":      "downstream",
    "RELIANCE":  "integrated",
    "GAIL":      "gas_transmission",
    "IGL":       "city_gas",
    "MGL":       "city_gas",
    "GUJGAS":    "city_gas",
    "PETRONET":  "gas_transmission",
}


# Sector / industry strings that should route through this engine.
# Matched case-insensitively as substring on the caller-supplied sector.
_OIL_GAS_SECTOR_HINTS = (
    "oil & gas",
    "oil and gas",
    "petroleum",
    "refining",
    "refineries",
    "city gas",
    "natural gas",
    "gas distribution",
    "exploration & production",
    "exploration and production",
    "upstream oil",
)


# ─────────────────────────────────────────────────────────────────
# Sanity thresholds
# ─────────────────────────────────────────────────────────────────

_RESERVES_LIFE_LOW_YEARS = 5.0
_RESERVES_LIFE_HIGH_YEARS = 30.0
_GRM_STRESSED_USD = 4.0
_GRM_PEAK_USD = 15.0


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against OIL_GAS_TICKERS."""
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
# Upstream — reserves NPV
# ─────────────────────────────────────────────────────────────────

def compute_upstream_reserves_npv(
    inputs: UpstreamReserveInputs,
    horizon_years: int = 15,
    depletion_per_year: float = 0.05,
) -> dict:
    """Per-year discount of net cash flow from reserves.

    Returns a dict with keys:
      - npv_inr_cr: aggregate NPV (INR crores)
      - year_by_year_cashflows: list of (year, production, net_cf_inr_cr,
        discounted_cf_inr_cr) tuples
      - terminal_residual: PV of reserves remaining at horizon end
      - sanity_warnings: observational list

    Depletes reserves over time at ``depletion_per_year``. Probable
    reserves (2P delta over 1P) get a 50% probability weight, matching
    the standard analyst convention. Possible (3P) reserves are
    deliberately excluded — they are too speculative to anchor a fair
    value claim.

    All inputs are validated defensively — non-positive reserves or
    production short-circuit to ``npv_inr_cr=0.0`` with a sanity
    warning.
    """
    warns: list[str] = []

    proved = _safe_pos(inputs.proved_reserves_mmboe)
    probable = _safe_pos(inputs.probable_reserves_mmboe)
    production = _safe_pos(inputs.annual_production_mmboe)
    price_usd = _safe_pos(inputs.realized_price_usd_per_boe)
    opex_usd = _safe_pos(inputs.operating_cost_usd_per_boe)
    royalty_dec = _safe_pos(inputs.royalty_pct) / 100.0
    cess_dec = _safe_pos(inputs.cess_pct) / 100.0
    tax_dec = _safe_pos(inputs.income_tax_pct) / 100.0
    discount = _safe_pos(inputs.discount_rate)
    usd_inr = _safe_pos(inputs.usd_to_inr)

    # Reserves base: proved + 50% × probable, the standard 2P-risked
    # convention used by every published Indian E&P research note.
    risked_reserves = proved + 0.5 * probable

    if risked_reserves <= 0 or production <= 0:
        warns.append(
            "non-positive reserves or production — NPV cannot compute"
        )
        return {
            "npv_inr_cr": 0.0,
            "year_by_year_cashflows": [],
            "terminal_residual": 0.0,
            "sanity_warnings": warns,
            "risked_reserves_mmboe": risked_reserves,
            "reserves_life_years": 0.0,
        }

    if discount <= 0 or usd_inr <= 0:
        warns.append(
            "non-positive discount_rate or usd_to_inr — NPV cannot compute"
        )
        return {
            "npv_inr_cr": 0.0,
            "year_by_year_cashflows": [],
            "terminal_residual": 0.0,
            "sanity_warnings": warns,
            "risked_reserves_mmboe": risked_reserves,
            "reserves_life_years": risked_reserves / production,
        }

    reserves_life_years = risked_reserves / production
    if reserves_life_years < _RESERVES_LIFE_LOW_YEARS:
        warns.append(
            f"reserves life {reserves_life_years:.1f}y < "
            f"{_RESERVES_LIFE_LOW_YEARS:.0f}y — near-term depletion risk"
        )
    elif reserves_life_years > _RESERVES_LIFE_HIGH_YEARS:
        warns.append(
            f"reserves life {reserves_life_years:.1f}y > "
            f"{_RESERVES_LIFE_HIGH_YEARS:.0f}y — ultra-long tail; "
            "verify reserve booking"
        )

    # Per-BOE net price after government take.
    # Royalty + cess are applied on REVENUE (not on profit), matching
    # India's onshore upstream tax regime. Income tax then applies on
    # post-royalty-and-cess earnings.
    revenue_per_boe = price_usd
    royalty_amount = revenue_per_boe * royalty_dec
    cess_amount = revenue_per_boe * cess_dec
    gross_profit_per_boe = revenue_per_boe - opex_usd - royalty_amount - cess_amount
    tax_amount = max(gross_profit_per_boe, 0.0) * tax_dec
    net_cf_per_boe_usd = gross_profit_per_boe - tax_amount

    cashflows: list[tuple] = []
    npv_inr_cr = 0.0
    remaining_reserves = risked_reserves

    for year in range(1, horizon_years + 1):
        if remaining_reserves <= 0:
            break

        # Production declines via depletion_per_year compounding (a
        # standard exponential decline curve). Cap at remaining
        # reserves so we don't pump phantom barrels in the final year.
        decline_factor = (1.0 - depletion_per_year) ** (year - 1)
        production_this_year = min(
            production * decline_factor,
            remaining_reserves,
        )

        # Cash flow in INR crores. MMBOE × USD/BOE × USD-INR = (10^6
        # boe) × (USD/boe) × (INR/USD) = INR × 10^6. Divide by 10^7 to
        # convert INR to crores (1 crore = 10^7 INR).
        net_cf_inr_cr = (
            production_this_year * net_cf_per_boe_usd * usd_inr / 10.0
        )
        discounted_cf = net_cf_inr_cr / ((1.0 + discount) ** year)

        cashflows.append(
            (year, production_this_year, net_cf_inr_cr, discounted_cf)
        )
        npv_inr_cr += discounted_cf
        remaining_reserves -= production_this_year

    # Terminal residual: PV of reserves remaining at horizon end,
    # valued at last-year net cash flow rate. Conservative compared
    # to a Gordon-growth perpetuity (which doesn't make physical
    # sense for an exhaustible asset).
    terminal_residual = 0.0
    if remaining_reserves > 0 and net_cf_per_boe_usd > 0:
        terminal_cf = (
            remaining_reserves * net_cf_per_boe_usd * usd_inr / 10.0
        )
        # Discount the terminal lump-sum back from horizon_years.
        terminal_residual = terminal_cf / (
            (1.0 + discount) ** horizon_years
        )
        npv_inr_cr += terminal_residual

    return {
        "npv_inr_cr": npv_inr_cr,
        "year_by_year_cashflows": cashflows,
        "terminal_residual": terminal_residual,
        "sanity_warnings": warns,
        "risked_reserves_mmboe": risked_reserves,
        "reserves_life_years": reserves_life_years,
        "net_cf_per_boe_usd": net_cf_per_boe_usd,
    }


# ─────────────────────────────────────────────────────────────────
# Downstream — refining EV/EBITDA
# ─────────────────────────────────────────────────────────────────

def compute_downstream_ev_ebitda(
    inputs: DownstreamRefiningInputs,
) -> dict:
    """Throughput × GRM × utilization × multiple - net_debt.

    Returns:
      - ev_inr_cr: enterprise value
      - equity_value_inr_cr: ev - net_debt
      - ebitda_inr_cr: annual EBITDA at given GRM
      - throughput_actual_mmt: effective throughput after utilization
      - sanity_warnings: observational

    GRM in USD/bbl is converted to INR/MT using 7.33 bbl/MT and
    the supplied USD-INR rate. Mid-cycle defaults are tuned to the
    Indian refiner historical band (₹IOC/BPCL/HPCL traded between 5-7x
    on mid-cycle EBITDA across 2014-2024).
    """
    warns: list[str] = []

    throughput_mmt = _safe_pos(inputs.refining_throughput_mmt)
    grm_usd_bbl = _safe_pos(inputs.gross_refining_margin_usd_per_bbl)
    util_dec = _safe_pos(inputs.capacity_utilization_pct) / 100.0
    multiple = _safe_pos(inputs.ev_ebitda_multiple)
    net_debt = _safe_pos(inputs.net_debt_inr_cr)
    usd_inr = _safe_pos(inputs.usd_to_inr)

    if throughput_mmt <= 0:
        warns.append("non-positive throughput — refining EV cannot compute")
        return {
            "ev_inr_cr": 0.0,
            "equity_value_inr_cr": -net_debt,
            "ebitda_inr_cr": 0.0,
            "throughput_actual_mmt": 0.0,
            "sanity_warnings": warns,
        }

    if grm_usd_bbl < _GRM_STRESSED_USD:
        warns.append(
            f"GRM {grm_usd_bbl:.2f} USD/bbl < {_GRM_STRESSED_USD:.0f} "
            "— stressed refining cycle"
        )
    elif grm_usd_bbl > _GRM_PEAK_USD:
        warns.append(
            f"GRM {grm_usd_bbl:.2f} USD/bbl > {_GRM_PEAK_USD:.0f} "
            "— peak cycle, mean reversion risk"
        )

    throughput_actual_mmt = throughput_mmt * util_dec
    # EBITDA = throughput (MMT) × bbl/MT × GRM (USD/bbl) × INR/USD.
    # Result is in INR; convert to crores (÷ 10^7), with MMT carrying
    # an implicit 10^6 multiplier → net divisor is 10.
    ebitda_inr_cr = (
        throughput_actual_mmt
        * _BARRELS_PER_METRIC_TONNE
        * grm_usd_bbl
        * usd_inr
        / 10.0
    )
    ev_inr_cr = ebitda_inr_cr * multiple
    equity_value_inr_cr = ev_inr_cr - net_debt

    if equity_value_inr_cr < 0:
        warns.append(
            "negative equity value (net debt > EV) — distress"
        )

    return {
        "ev_inr_cr": ev_inr_cr,
        "equity_value_inr_cr": equity_value_inr_cr,
        "ebitda_inr_cr": ebitda_inr_cr,
        "throughput_actual_mmt": throughput_actual_mmt,
        "sanity_warnings": warns,
    }


# ─────────────────────────────────────────────────────────────────
# City gas — volume × EBITDA-per-unit × multiple
# ─────────────────────────────────────────────────────────────────

def compute_city_gas_value(
    inputs: CityGasInputs,
) -> dict:
    """Volume × EBITDA-per-unit × multiple - net_debt.

    Returns:
      - ev_inr_cr
      - equity_value_inr_cr
      - annual_ebitda_inr_cr
      - total_volume_mmscm_per_day
      - sanity_warnings

    The 14× default multiple reflects the historical city-gas premium
    for IGL / MGL / GUJGAS — geographic-monopoly licenses with
    regulated-utility-like volume growth.
    """
    warns: list[str] = []

    cng = _safe_pos(inputs.cng_volume_mmscm_per_day)
    png = _safe_pos(inputs.png_volume_mmscm_per_day)
    ebitda_per_scm = _safe_pos(inputs.ebitda_per_unit_inr_per_scm)
    multiple = _safe_pos(inputs.ebitda_multiple)
    net_debt = _safe_pos(inputs.net_debt_inr_cr)

    total_volume = cng + png

    if total_volume <= 0:
        warns.append("non-positive volume — city gas EV cannot compute")
        return {
            "ev_inr_cr": 0.0,
            "equity_value_inr_cr": -net_debt,
            "annual_ebitda_inr_cr": 0.0,
            "total_volume_mmscm_per_day": 0.0,
            "sanity_warnings": warns,
        }

    # Annual volume = daily MMSCM × 365 days. EBITDA in INR = annual
    # SCM × INR/SCM. MMSCM carries an implicit 10^6 multiplier; convert
    # INR → crores (÷ 10^7) → net divisor is 10.
    annual_ebitda_inr_cr = (
        total_volume * 365.0 * ebitda_per_scm / 10.0
    )
    ev_inr_cr = annual_ebitda_inr_cr * multiple
    equity_value_inr_cr = ev_inr_cr - net_debt

    if equity_value_inr_cr < 0:
        warns.append("negative equity value (net debt > EV) — distress")

    return {
        "ev_inr_cr": ev_inr_cr,
        "equity_value_inr_cr": equity_value_inr_cr,
        "annual_ebitda_inr_cr": annual_ebitda_inr_cr,
        "total_volume_mmscm_per_day": total_volume,
        "sanity_warnings": warns,
    }


# ─────────────────────────────────────────────────────────────────
# Integrated — SOTP composer
# ─────────────────────────────────────────────────────────────────

def compute_integrated_sotp(
    upstream_value_inr_cr: Optional[float],
    downstream_value_inr_cr: Optional[float],
    petrochem_value_inr_cr: Optional[float] = None,
    other_value_inr_cr: Optional[float] = None,
    net_debt_inr_cr: float = 0.0,
    shares_outstanding: float = 0.0,
) -> OilGasValuationResult:
    """SOTP for integrated names (RELIANCE-shaped).

    Sums the per-segment equity values, subtracts consolidated net
    debt, and divides by shares outstanding to derive a per-share
    fair value. Any component that is None is skipped (missing
    segment → not counted), not treated as zero.

    Returns ``OilGasValuationResult(method="integrated_sotp")``. The
    ``components`` dict records every per-segment input so the caller
    can render the SOTP waterfall transparently.
    """
    components: dict = {}
    aggregate = 0.0
    contributed_any = False

    for label, value in (
        ("upstream", upstream_value_inr_cr),
        ("downstream", downstream_value_inr_cr),
        ("petrochem", petrochem_value_inr_cr),
        ("other", other_value_inr_cr),
    ):
        if value is None:
            components[label] = None
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            components[label] = None
            continue
        components[label] = v
        aggregate += v
        contributed_any = True

    components["net_debt"] = float(net_debt_inr_cr or 0.0)
    components["shares_outstanding"] = float(shares_outstanding or 0.0)

    warns: list[str] = []
    if not contributed_any:
        warns.append(
            "no segment values supplied — integrated SOTP cannot compute"
        )
        return OilGasValuationResult(
            fair_value_per_share=None,
            aggregate_value_inr_cr=None,
            components=components,
            method="unavailable",
            sanity_warnings=warns,
        )

    equity_value_inr_cr = aggregate - float(net_debt_inr_cr or 0.0)
    components["equity_value_inr_cr"] = equity_value_inr_cr

    if equity_value_inr_cr < 0:
        warns.append("negative aggregate equity (net debt > SOTP) — distress")

    fv_per_share: Optional[float] = None
    shares = float(shares_outstanding or 0.0)
    if shares > 0 and equity_value_inr_cr > 0:
        # equity_value is in INR crores; multiply by 1e7 to get INR.
        fv_per_share = (equity_value_inr_cr * 1e7) / shares
    elif shares <= 0:
        warns.append(
            "shares_outstanding not supplied — per-share FV unavailable"
        )

    return OilGasValuationResult(
        fair_value_per_share=fv_per_share,
        aggregate_value_inr_cr=equity_value_inr_cr,
        components=components,
        method="integrated_sotp",
        sanity_warnings=warns,
    )


# ─────────────────────────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────────────────────────

def select_method_for_ticker(ticker: str) -> Optional[OilGasSegment]:
    """Return the segment for a known oil & gas ticker, or None.

    Bare-ticker resolution only — sector-hint resolution is handled
    by ``is_oil_gas_applicable``. Callers wanting both should call
    this first, then fall through to ``is_oil_gas_applicable``.
    """
    bare = _bare_ticker(ticker)
    return OIL_GAS_TICKERS.get(bare)


def is_oil_gas_applicable(
    ticker: str, sector: Optional[str]
) -> tuple[bool, str]:
    """True iff the ticker should be routed through this engine.

    Resolution order:
      1. Bare ticker present in OIL_GAS_TICKERS → True
      2. Sector substring matches an oil-and-gas hint → True
      3. Otherwise → False

    Returns (applicable, reason) where ``reason`` is a short log /
    admin string — never user-facing.
    """
    bare = _bare_ticker(ticker)
    if bare in OIL_GAS_TICKERS:
        return True, (
            f"ticker {bare} in OIL_GAS_TICKERS ({OIL_GAS_TICKERS[bare]})"
        )

    if not sector:
        return False, "no sector hint and ticker not in OIL_GAS_TICKERS"

    s = sector.strip().lower()
    for hint in _OIL_GAS_SECTOR_HINTS:
        if hint in s:
            return True, f"sector matches oil-gas hint '{hint}'"

    return False, f"sector '{sector}' does not match oil-gas hints"


# ─────────────────────────────────────────────────────────────────
# Result serialization
# ─────────────────────────────────────────────────────────────────

def to_dict(result: OilGasValuationResult) -> dict:
    """JSON-safe projection — every value is a plain Python primitive.

    The ``components`` dict is shallow-copied; the caller can mutate
    the returned dict without polluting the source result.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "aggregate_value_inr_cr": result.aggregate_value_inr_cr,
        "components": dict(result.components or {}),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
    }


__all__ = [
    "OilGasSegment",
    "UpstreamReserveInputs",
    "DownstreamRefiningInputs",
    "CityGasInputs",
    "OilGasValuationResult",
    "OIL_GAS_TICKERS",
    "compute_upstream_reserves_npv",
    "compute_downstream_ev_ebitda",
    "compute_city_gas_value",
    "compute_integrated_sotp",
    "select_method_for_ticker",
    "is_oil_gas_applicable",
    "to_dict",
]
