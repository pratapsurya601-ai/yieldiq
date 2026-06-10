# backend/services/replacement_value_service.py
# ═══════════════════════════════════════════════════════════════
# Replacement Value engine — Tobin-Q-style "cost to recreate".
#
# Why this exists (T2.3 of the engine refinement roadmap):
#   Replacement value answers a different question from liquidation
#   (T2.8). Liquidation asks: "If we shut this business down today
#   and sold every asset at orderly-auction recovery rates, what
#   would equity holders receive?" — a downside floor.
#
#   Replacement asks the symmetric question on the OTHER side:
#   "What would it cost to recreate this business from scratch,
#   today, at current input prices?" — a build-vs-buy anchor.
#
#   The pair gives the analyst a two-sided economic frame:
#
#     Liquidation  : downside floor (asset recovery)
#     Replacement  : build-vs-buy ceiling on the asset base
#     Tobin's Q    : market cap divided by replacement value
#                    > 1 → market pays a premium over rebuild cost
#                          (moat / scarcity / over-valuation)
#                    < 1 → market discounts the rebuild cost
#                          (distress / orphaned franchise / deep value)
#                    ≈ 1 → market values the firm at the cost of
#                          recreating its asset base
#
#   This is the canonical Tobin's Q from corporate finance — the
#   ratio Wall Street has tracked at the aggregate level since
#   James Tobin published the framework in 1969. At the per-firm
#   level the input that's hardest to estimate is replacement
#   value itself (book understates because of inflation; market
#   cap overstates because it embeds franchise value). This
#   service produces a defensible per-firm replacement value the
#   composite engine can divide market cap by.
#
# Phase A scope:
#   Standalone pure-math service. No wiring into the analysis
#   response, no composite engine fold-in. Phase B (separate PR)
#   wires the result into AnalysisResponse and adds Tobin's Q as
#   a confidence-signal input.
#
# Formula:
#     Replacement Value (equity)
#       = PP&E_gross × inflation_factor(sector)
#       + working_capital_required
#       + cash_required_for_ops
#       + brand_replacement_cost      (if explicitly supplied)
#       + technology_replacement_cost (if explicitly supplied)
#       − total_debt
#
#   Intangibles + goodwill at book are deliberately EXCLUDED. Book
#   intangibles capitalise prior acquisition premia and amortised
#   IP at cost; replacement value asks what it would cost to
#   recreate those assets TODAY (which can be far more or far less
#   than the carrying value). The honest treatment is: omit by
#   default, warn when the omission is material, and let the caller
#   supply explicit brand_replacement_cost / technology_replacement_
#   cost when those numbers are defensible.
#
# Sector inflation factors:
#   Tunable per sector — heavy long-life assets (cement, hotels)
#   carry higher multipliers because the historical-cost base is
#   older; asset-refresh-heavy sectors (IT, auto) carry lower
#   multipliers because retooling churns the book closer to current
#   cost. Defaults below are calibrated against the 2018-2024
#   Indian capex inflation band (~5-8% p.a. weighted).
#
# Caller contract (Phase A):
#     compute_replacement_value(inputs, market_cap_inr_cr=None)
#         -> ReplacementValueResult
#     is_replacement_value_meaningful(ticker, sector, ppe_ratio)
#         -> (bool, str)
#     get_sector_inflation_factor(sector) -> float
#     to_dict(result) -> dict
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.replacement_value")


# ─────────────────────────────────────────────────────────────────
# Sector-aware PP&E inflation factor.
#
# Multiplier applied to gross historical-cost PP&E to estimate
# current replacement cost. Calibration intuition:
#
#   factor ≈ (1 + capex_inflation) ^ weighted_asset_age_years
#
# Heavy-asset sectors (cement, metals, hotels) carry decade-old
# kit; ~5%/yr × 7-10 yrs ≈ 1.4-1.6.  IT services and auto OEMs
# refresh more aggressively (3-5 year cycles) so the weighted base
# is closer to current cost; multiplier 1.2-1.3.  Real estate is
# special — book IS roughly current resale value when the property
# is reasonably young, so the default multiplier is 1.0 (the user
# should mark up explicitly if a property is genuinely older).
# ─────────────────────────────────────────────────────────────────
_SECTOR_INFLATION_FACTORS: dict[str, float] = {
    # Cement / Metals — long-life heavy plants. Historical cost
    # rapidly understates replacement (e.g. UltraTech's clinker
    # capacity at 2014 prices vs 2026 prices is a ~1.6x gap).
    "cement":                  1.6,
    "construction materials":  1.6,
    "metals":                  1.6,
    "mining":                  1.6,

    # Auto OEM / components — modern factories, frequent retooling
    # for new model launches. Base depreciates and refreshes faster
    # so the historical-cost gap is narrower.
    "auto":                1.3,
    "automobile":          1.3,
    "auto components":     1.3,

    # FMCG — manufacturing plant + distribution capex. Mid-cycle
    # refresh. The brand is the real asset (see brand_replacement_
    # cost) but the rebuild factor for the factory line itself is
    # average.
    "fmcg":                1.4,
    "consumer goods":      1.4,

    # Pharma — specialised R&D facilities + sterile manufacturing.
    # Long-life, expensive to recreate (WHO-GMP recertification
    # adds time + cost beyond the build).
    "pharma":              1.5,
    "pharmaceuticals":     1.5,
    "healthcare":          1.5,

    # IT Services — mostly leased offices + frequent laptop refresh.
    # Historical book is close to current cost.
    "it":                  1.2,
    "it services":         1.2,
    "technology":          1.2,
    "software":            1.2,

    # Real Estate — book ≈ current property cost for reasonably
    # young inventory. The asset IS the value — no inflation
    # multiplier by default. Mark up explicitly for older property.
    "real estate":         1.0,
    "realty":              1.0,

    # Hotels — location-anchored real estate plus operating fit-out.
    # Slow refresh on the bones; the location premium can't be
    # rebuilt at any price (which makes Tobin's Q for hotels
    # particularly informative).
    "hotels":              1.5,
    "hospitality":         1.5,

    # Telecom — continuous capex with technology refresh (3G→4G→5G).
    # Each refresh moves book closer to current cost, so the
    # multiplier is lower than cement / hotels.
    "telecom":             1.3,

    # Utilities / power — regulated-asset-base economics, very
    # long-life kit (35-50yr depreciation). Historical cost rapidly
    # diverges from replacement.
    "utilities":           1.5,
    "power":               1.5,
    "energy":              1.5,
    "oil & gas":           1.5,

    # Capital goods / engineering — specialised plant, mid-life
    # refresh. Similar profile to FMCG manufacturing.
    "capital goods":       1.4,
    "engineering":         1.4,
    "machinery":           1.4,

    # Chemicals / fertilisers — long-life plants, sector-specific
    # capex inflation higher than headline.
    "chemicals":           1.5,
    "fertilisers":         1.5,
}

# Default inflation multiplier when sector is unknown.
# Anchors to "~5% × 7-year average asset age" ≈ 1.4.
_DEFAULT_INFLATION_FACTOR: float = 1.4

# Sectors for which replacement value is conceptually inapplicable.
# Banks / NBFCs / insurance run on capital-adequacy frameworks;
# their "asset base" is loan books + reserves, not PP&E. Holdcos
# trade on SOTP, not on the cost of recreating the asset base.
_REPLACEMENT_NOT_APPLICABLE_SECTORS: frozenset[str] = frozenset({
    "banks", "banking", "bank",
    "psu banks", "private banks",
    "nbfc", "nbfcs", "financials", "finance", "financial services",
    "insurance", "life insurance", "general insurance",
    "asset management", "amc",
    "holdco", "holding company", "diversified holdings",
})

# PP&E ratio (PP&E / total_assets) below which replacement value
# tells the user little — asset-light franchises derive value from
# headcount + contracts + customer relationships, not from
# recreatable plant.
_REPLACEMENT_LOW_PPE_THRESHOLD: float = 0.10

# When intangibles + goodwill exceed this share of the (book) asset
# base AND no explicit brand_replacement_cost is supplied, fire a
# warning — the omitted intangible-rebuild cost is material.
_BRAND_OMISSION_THRESHOLD: float = 0.05

# Tobin's Q thresholds for narrative flags. > 3 is "market pays a
# 3x rebuild premium" — moat or over-valuation; < 0.5 is "market
# discounts the asset base by half" — distress or deep value.
_TOBIN_Q_HIGH_THRESHOLD: float = 3.0
_TOBIN_Q_LOW_THRESHOLD: float = 0.5


# ─────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────

@dataclass
class ReplacementValueInputs:
    """Balance-sheet line items required to compute replacement value.

    All amounts in the same unit (typically INR Crores for Indian
    listed equities). Math is unit-agnostic; downstream consumers
    reading per-share must align ``shares_outstanding`` to the same
    base.
    """
    # Asset base — at current values
    ppe_gross: float
    ppe_age_years: Optional[float] = None
    intangibles_book: float = 0.0
    goodwill: float = 0.0
    working_capital_required: float = 0.0
    cash_required_for_ops: float = 0.0

    # Adjustments
    inflation_factor_ppe: float = 1.4
    brand_replacement_cost: float = 0.0
    technology_replacement_cost: float = 0.0

    # Liabilities
    total_debt: float = 0.0

    # Output normalizers
    shares_outstanding: float = 0.0
    sector: Optional[str] = None


@dataclass
class ReplacementValueResult:
    """Output shape — defensive, never raises on bad inputs.

    Per-share is None when ``shares_outstanding`` is missing /
    zero. Aggregate may be negative (distress: debt exceeds
    replaceable asset base).
    """
    replacement_value_aggregate: Optional[float]
    replacement_value_per_share: Optional[float]
    components: dict
    method: str
    tobins_q: Optional[float] = None
    sanity_warnings: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Sector helpers
# ─────────────────────────────────────────────────────────────────

def _normalise_sector(sector: Optional[str]) -> str:
    if not sector:
        return ""
    return str(sector).strip().lower()


def get_sector_inflation_factor(sector: Optional[str]) -> float:
    """Return the PP&E replacement-cost inflation multiplier.

    Cement / Metals (long-life heavy assets): 1.6
    Auto OEM (modern factories, frequent retooling): 1.3
    FMCG (factory + distribution): 1.4
    Pharma (specialised R&D facilities): 1.5
    IT Services (mostly leased offices, frequent refresh): 1.2
    Real Estate (the asset IS the value): 1.0
    Hotels (location-anchored, slow depreciation): 1.5
    Telecom (continuous capex, tech refresh): 1.3
    Utilities / Power (regulated long-life kit): 1.5
    Default: 1.4
    """
    key = _normalise_sector(sector)
    if not key:
        return _DEFAULT_INFLATION_FACTOR
    if key in _SECTOR_INFLATION_FACTORS:
        return _SECTOR_INFLATION_FACTORS[key]
    # Substring fallback so callers passing "Auto Components" or
    # "IT - Software" land on the right bucket.
    for known_key, factor in _SECTOR_INFLATION_FACTORS.items():
        if known_key in key or key in known_key:
            return factor
    return _DEFAULT_INFLATION_FACTOR


# ─────────────────────────────────────────────────────────────────
# Numeric helpers
# ─────────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_non_negative(value, default: float = 0.0) -> float:
    """Clamp negative numerics to zero — asset / cost inputs must
    not contribute negative numbers to a replacement-value sum."""
    return max(0.0, _safe_float(value, default))


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────

def compute_replacement_value(
    inputs: ReplacementValueInputs,
    market_cap_inr_cr: Optional[float] = None,
) -> ReplacementValueResult:
    """Compute Tobin-Q-style replacement value. Defensive — never raises.

    Algorithm:
      1. PP&E_replaced = ppe_gross × inflation_factor
         (when ``inputs.sector`` is set we PREFER the sector-tuned
         factor over the ``inputs.inflation_factor_ppe`` default —
         the explicit sector is a stronger signal than the carried
         default. When ``sector`` is None / unknown we use the
         caller-supplied factor as-is.)
      2. Working capital + cash-required carried at book (these
         lines turn over fast enough that historical cost ≈
         replacement cost).
      3. Intangibles + goodwill book-value EXCLUDED. Brand and
         technology rebuild costs only included when explicitly
         supplied by the caller (brand_replacement_cost,
         technology_replacement_cost).
      4. Total debt subtracted to yield equity replacement value.
      5. Tobin's Q = market_cap_inr_cr / replacement_value_aggregate
         when both are positive numerics.

    Sanity warnings (emitted on the result):
      - "null_inputs" — ``inputs`` was None.
      - "brand_value_omitted_material" — intangibles + goodwill at
        book exceed 5% of the gross replacement asset base AND no
        brand_replacement_cost was supplied (the omission is
        material; the result understates).
      - "high_tobins_q" — Q > 3.0 (market premium over rebuild —
        moat or over-valuation).
      - "low_tobins_q" — Q < 0.5 (market discount to rebuild —
        distress or deep value).
      - "negative_replacement_value" — total_debt exceeds the
        replaceable asset base (distress signal).
      - "no_shares_outstanding" — per_share is None.

    Returns a ReplacementValueResult with method:
      - "replacement_full"     headline PP&E present + working_capital
                               or cash_required supplied
      - "replacement_partial"  PP&E present but no working capital /
                               cash signal
      - "unavailable"          nothing usable supplied
    """
    if inputs is None:
        return ReplacementValueResult(
            replacement_value_aggregate=None,
            replacement_value_per_share=None,
            components={},
            method="unavailable",
            tobins_q=None,
            sanity_warnings=["null_inputs"],
        )

    sanity_warnings: list = []

    # ── PP&E replacement at current cost ──────────────────────────
    ppe_gross = _safe_non_negative(inputs.ppe_gross)
    # Prefer sector-tuned factor when sector is known; fall back to
    # the caller-supplied default otherwise.
    if inputs.sector:
        inflation_factor = get_sector_inflation_factor(inputs.sector)
    else:
        inflation_factor = max(0.0, _safe_float(
            inputs.inflation_factor_ppe, _DEFAULT_INFLATION_FACTOR
        ))
    ppe_replaced = ppe_gross * inflation_factor

    # ── Working capital + ops cash carried at book ────────────────
    working_capital = _safe_non_negative(inputs.working_capital_required)
    cash_for_ops = _safe_non_negative(inputs.cash_required_for_ops)

    # ── Intangibles handling — book excluded by default ───────────
    intangibles_book = _safe_non_negative(inputs.intangibles_book)
    goodwill_book = _safe_non_negative(inputs.goodwill)
    brand_rebuild = _safe_non_negative(inputs.brand_replacement_cost)
    tech_rebuild = _safe_non_negative(inputs.technology_replacement_cost)

    intangibles_omitted = intangibles_book + goodwill_book
    intangibles_included = brand_rebuild + tech_rebuild

    # ── Liabilities ───────────────────────────────────────────────
    total_debt = _safe_non_negative(inputs.total_debt)

    # ── Component breakdown ───────────────────────────────────────
    components: dict = {
        "ppe_replaced": round(ppe_replaced, 4),
        "ppe_gross_input": round(ppe_gross, 4),
        "inflation_factor_applied": round(inflation_factor, 4),
        "working_capital_required": round(working_capital, 4),
        "cash_required_for_ops": round(cash_for_ops, 4),
        "brand_replacement_cost": round(brand_rebuild, 4),
        "technology_replacement_cost": round(tech_rebuild, 4),
        "intangibles_book_omitted": round(intangibles_book, 4),
        "goodwill_book_omitted": round(goodwill_book, 4),
        "total_debt": round(total_debt, 4),
    }

    # ── Aggregate replacement value (equity) ──────────────────────
    asset_replacement_total = (
        ppe_replaced
        + working_capital
        + cash_for_ops
        + brand_rebuild
        + tech_rebuild
    )
    replacement_aggregate = asset_replacement_total - total_debt

    components["asset_replacement_total"] = round(asset_replacement_total, 4)
    components["equity_replacement_value"] = round(replacement_aggregate, 4)

    # ── Method classification ─────────────────────────────────────
    if ppe_gross <= 0.0 and brand_rebuild <= 0.0 and tech_rebuild <= 0.0:
        method = "unavailable"
    elif ppe_gross > 0.0 and (working_capital > 0.0 or cash_for_ops > 0.0):
        method = "replacement_full"
    elif ppe_gross > 0.0 or brand_rebuild > 0.0 or tech_rebuild > 0.0:
        method = "replacement_partial"
    else:
        method = "unavailable"

    # ── Per-share derivation ──────────────────────────────────────
    shares = _safe_float(inputs.shares_outstanding)
    per_share: Optional[float]
    if shares > 0.0 and method != "unavailable":
        per_share = round(replacement_aggregate / shares, 4)
    else:
        per_share = None
        if shares <= 0.0:
            sanity_warnings.append("no_shares_outstanding")

    # ── Tobin's Q ─────────────────────────────────────────────────
    tobins_q: Optional[float] = None
    if (
        market_cap_inr_cr is not None
        and replacement_aggregate > 0.0
        and method != "unavailable"
    ):
        mcap = _safe_float(market_cap_inr_cr)
        if mcap > 0.0:
            tobins_q = round(mcap / replacement_aggregate, 4)

    # ── Sanity warnings ───────────────────────────────────────────
    # Brand omission: only fire when the book-intangible base is a
    # material share of the gross replacement asset base AND no
    # explicit brand cost was supplied. Denominator is the gross
    # asset replacement total (NOT post-debt equity) so the test
    # measures composition, not leverage.
    denom_for_brand_check = asset_replacement_total + intangibles_omitted
    if (
        intangibles_omitted > 0.0
        and brand_rebuild <= 0.0
        and denom_for_brand_check > 0.0
        and (intangibles_omitted / denom_for_brand_check) > _BRAND_OMISSION_THRESHOLD
    ):
        sanity_warnings.append("brand_value_omitted_material")

    if replacement_aggregate < 0.0:
        sanity_warnings.append("negative_replacement_value")

    if tobins_q is not None:
        if tobins_q > _TOBIN_Q_HIGH_THRESHOLD:
            sanity_warnings.append("high_tobins_q")
        elif tobins_q < _TOBIN_Q_LOW_THRESHOLD:
            sanity_warnings.append("low_tobins_q")

    return ReplacementValueResult(
        replacement_value_aggregate=round(replacement_aggregate, 4)
        if method != "unavailable" else None,
        replacement_value_per_share=per_share,
        components=components,
        method=method,
        tobins_q=tobins_q,
        sanity_warnings=sanity_warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Applicability helper
# ─────────────────────────────────────────────────────────────────

def is_replacement_value_meaningful(
    ticker: str,
    sector: Optional[str],
    ppe_ratio: Optional[float],
) -> tuple[bool, str]:
    """Return ``(meaningful, reason)`` for whether replacement value
    is informative for this ticker.

    Replacement value is most informative for asset-heavy businesses
    where the question "what would it cost to rebuild this asset base
    from scratch?" has a defensible answer:

      - Manufacturing, cement, metals, auto, real estate, hotels,
        utilities, telecom, oil & gas

    Not very meaningful for:
      - Banks / NBFCs / insurance — capital adequacy framework, not
        asset replacement
      - IT services — asset-light, leased offices, value is headcount
        + contracts, not rebuildable plant
      - Holdcos — SOTP is the right framework

    ``ppe_ratio`` is PP&E / Total Assets. When provided, it's the
    primary signal; the sector-level fallback is informative when
    the caller has no balance-sheet ratio handy.
    """
    sec = _normalise_sector(sector)

    # Hard exclusion: banks / NBFCs / insurance / holdcos.
    if sec in _REPLACEMENT_NOT_APPLICABLE_SECTORS:
        return (
            False,
            "Banks / NBFCs / insurers operate under a capital-"
            "adequacy framework. Holding companies trade on SOTP. "
            "Replacement value is not applicable.",
        )

    # PP&E-ratio signal — asset-light businesses don't derive value
    # from rebuildable plant.
    if ppe_ratio is not None:
        try:
            ratio = float(ppe_ratio)
        except (TypeError, ValueError):
            ratio = None  # type: ignore[assignment]
        else:
            if ratio < _REPLACEMENT_LOW_PPE_THRESHOLD:
                return (
                    False,
                    f"PP&E is {ratio * 100:.1f}% of total assets. "
                    "Asset-light businesses derive value from "
                    "headcount, contracts, and customer "
                    "relationships — not from rebuildable plant.",
                )

    # Sector-level fallback for asset-light cohorts when no explicit
    # ratio is available.
    if sec in {"it", "it services", "technology", "software"}:
        return (
            False,
            "IT services derive value from headcount + contracts, "
            "not PP&E. Replacement-cost framework under-states "
            "franchise value.",
        )

    return (
        True,
        "Asset-heavy business — replacement value (and Tobin's Q) "
        "are informative.",
    )


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────

def to_dict(result: ReplacementValueResult) -> dict:
    """JSON-safe projection of a ReplacementValueResult.

    Mirrors the shape liquidation_value_service.to_dict produces so
    the analysis pipeline can splice both side by side without
    reshaping the surrounding code in Phase B.
    """
    if result is None:
        return {
            "replacement_value_aggregate": None,
            "replacement_value_per_share": None,
            "components": {},
            "method": "unavailable",
            "tobins_q": None,
            "sanity_warnings": ["null_result"],
        }
    return {
        "replacement_value_aggregate": result.replacement_value_aggregate,
        "replacement_value_per_share": result.replacement_value_per_share,
        "components": dict(result.components or {}),
        "method": result.method,
        "tobins_q": result.tobins_q,
        "sanity_warnings": list(result.sanity_warnings or []),
    }
