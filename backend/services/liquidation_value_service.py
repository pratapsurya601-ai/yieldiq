# backend/services/liquidation_value_service.py
# ═══════════════════════════════════════════════════════════════
# Liquidation Value engine — Graham-style asset recovery floor.
#
# Why this exists (T2.8 of the engine refinement roadmap):
#   Liquidation value is the most conservative valuation. It answers
#   the question: "What would this business be worth if you shut it
#   down today, sold every asset, and paid every liability?"
#
#   The engine's bull / base case can sound too good in dislocations.
#   The bear DCF case is a function of trough operating cash flow,
#   not asset coverage. Neither of those gives the user a hard
#   "can't realistically fall below this" anchor. Liquidation value
#   does — it is the price at which the next dollar of downside
#   becomes an asset-coverage question, not an earnings question.
#
#   The floor is most informative in four scenarios:
#     1. Severe market dislocations (gives users a "this is the
#        absolute floor") anchor.
#     2. Distressed turnarounds where earnings power is uncertain.
#     3. Asset-heavy businesses (metals, real estate, capital goods,
#        utilities) where book value is meaningful.
#     4. Cyclical troughs where trailing P/E reads absurdly high
#        but tangible book is roughly stable.
#
# Phase A scope:
#   Standalone pure-math service. No wiring into the verdict gate
#   or analysis response. Phase B (separate PR) wires the floor
#   into the verdict gate as an anchor — if current_price <
#   liquidation_per_share, surfaces it as a "hard floor" data
#   point on the analysis page.
#
# Formula:
#     Liquidation Value = Sum(Asset × Recovery Rate) − Total Liabilities
#
# Recovery rates (Graham-style, sector-aware on PP&E):
#     Cash + equivalents                  100%
#     Short-term investments              90%
#     Receivables                         80%
#     Inventory blended                   50%
#       (raw materials 60%, WIP 30%, finished 50% when sub-broken)
#     PP&E                                30-70% by sector (default 40)
#     Long-term investments               80% (marketable)
#     Intangibles + Goodwill              0%  (orderly liquidation)
#     Other assets                        30%
#     Liabilities                         100% (must be paid)
#
# Caller contract (Phase A):
#     compute_liquidation_value(inputs, current_price=None)
#         -> LiquidationResult
#     is_liquidation_meaningful(ticker, sector, ppe_ratio)
#         -> (bool, str)
#     get_sector_ppe_recovery(sector) -> float
#     to_dict(result) -> dict
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.liquidation_value")


# ─────────────────────────────────────────────────────────────────
# Sector-aware PP&E recovery table.
#
# Graham defaults to ~50% for PP&E in an orderly liquidation, but
# the actual recovery is sector-dependent. Real estate PP&E IS the
# asset (a building has a deep resale market) while IT-services
# PP&E is mostly leasehold improvements and laptop fleets (almost
# no resale). The defaults below are conservative — actual auction
# proceeds on Indian industrial assets in NCLT proceedings have
# ranged 25-65% of book over the 2018-2024 window.
# ─────────────────────────────────────────────────────────────────
_SECTOR_PPE_RECOVERY: dict[str, float] = {
    # Auto / capital goods — specialised but resaleable in secondary
    # auction markets (Tata Motors plants, BHEL workshops, Cummins
    # engine lines have known buyers).
    "auto":                0.45,
    "automobile":          0.45,
    "auto components":     0.45,
    "capital goods":       0.45,
    "engineering":         0.45,
    "machinery":           0.45,

    # FMCG / Pharma — specialised factories with narrow buyer pools
    # (Hindustan Unilever soap line is not a turnkey buy for anyone
    # outside FMCG; Sun Pharma sterile facility requires WHO-GMP
    # recertification per buyer).
    "fmcg":                0.30,
    "consumer goods":      0.30,
    "pharma":              0.30,
    "pharmaceuticals":     0.30,
    "healthcare":          0.30,

    # Real estate — the asset IS the property. Deep secondary market
    # (DLF / Prestige inventory turns into sale-deeds at the next
    # NCLT auction). Higher recovery rate than any other sector.
    "real estate":         0.70,
    "realty":              0.70,

    # Hotels — location-anchored real estate plus operating equipment.
    # Mid-recovery: the building has resale, the F&B / housekeeping
    # equipment is more fungible than a chemical plant.
    "hotels":              0.50,
    "hospitality":         0.50,

    # Metals / cement — heavy machinery with commodity-demand backstop.
    # Higher than FMCG because the kit (rolling mills, cement kilns)
    # has resale into the same sector globally.
    "metals":              0.55,
    "mining":              0.55,
    "cement":              0.55,
    "construction materials": 0.55,

    # IT services — mostly leased offices, laptop fleets, leasehold
    # improvements. Very little owned PP&E with resale value.
    "it":                  0.20,
    "it services":         0.20,
    "technology":          0.20,
    "software":            0.20,

    # Utilities / power — fixed plants with regulated-asset-base
    # economics. Power-T&D assets recover well (NTPC plants have
    # known buyers); pure-play generation less so.
    "utilities":           0.50,
    "power":               0.50,
    "energy":              0.50,
    "oil & gas":           0.50,

    # Chemicals — specialised plants but commodity-grade kit has
    # global resale.
    "chemicals":           0.45,
    "fertilisers":         0.45,

    # Telecom — towers + spectrum (spectrum is intangible). Tower
    # PP&E has known resale (Indus Towers / ATC India absorptive
    # capacity).
    "telecom":             0.45,
}

# Default PP&E recovery when sector is unknown or not in the table.
# Conservative middle-of-the-band.
_DEFAULT_PPE_RECOVERY: float = 0.40

# Sectors for which a liquidation floor is conceptually inapplicable.
# Banks and insurers run on capital adequacy / solvency-margin
# frameworks, not liquidation. Their "PP&E" is loan books + premia
# reserves — a different framework entirely.
_LIQUIDATION_NOT_APPLICABLE_SECTORS: frozenset[str] = frozenset({
    "banks", "banking", "bank",
    "psu banks", "private banks",
    "nbfc", "nbfcs", "financials", "finance", "financial services",
    "insurance", "life insurance", "general insurance",
    "asset management", "amc",
})

# PP&E ratio threshold below which liquidation is informative but
# misleading. IT services / AMCs / brokers carry minimal PP&E so
# their liquidation value is dominated by cash + receivables, which
# undersells the franchise economics (the value IS the contracts +
# headcount).
_LIQUIDATION_LOW_PPE_THRESHOLD: float = 0.10

# Threshold above which intangibles + goodwill dominate the asset
# base. When this fires we still compute the floor but emit a
# warning that liquidation under-states value (brand-heavy
# businesses).
_INTANGIBLES_DOMINANCE_THRESHOLD: float = 0.30


# ─────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────

@dataclass
class LiquidationInputs:
    """Balance-sheet line items required to compute liquidation.

    All amounts in the same unit (whatever the caller passes —
    typically INR Crores for Indian listed equities). The math is
    unit-agnostic; downstream consumers reading per_share need to
    align shares_outstanding to the same unit base.
    """
    cash_and_equivalents: float
    short_term_investments: float
    receivables: float
    inventory: float
    inventory_raw_materials: Optional[float] = None
    inventory_wip: Optional[float] = None
    inventory_finished: Optional[float] = None
    ppe_gross: float = 0.0
    ppe_net: float = 0.0
    intangibles: float = 0.0
    goodwill: float = 0.0
    long_term_investments: float = 0.0
    other_assets: float = 0.0
    short_term_debt: float = 0.0
    long_term_debt: float = 0.0
    accounts_payable: float = 0.0
    other_liabilities: float = 0.0
    shares_outstanding: float = 0.0
    sector: Optional[str] = None


@dataclass
class LiquidationRecoveryRates:
    """Recovery-rate haircut applied per asset class.

    Defaults track the Graham framework. Sector-aware adjustments
    happen at compute time via ``get_sector_ppe_recovery`` — the
    ``ppe`` field below is the default that is overridden when
    ``LiquidationInputs.sector`` is set.
    """
    cash: float = 1.00
    receivables: float = 0.80
    inventory_raw: float = 0.60
    inventory_wip: float = 0.30
    inventory_finished: float = 0.50
    inventory_blended: float = 0.50
    ppe: float = _DEFAULT_PPE_RECOVERY
    intangibles: float = 0.00
    goodwill: float = 0.00
    long_term_investments: float = 0.80
    other_assets: float = 0.30
    short_term_investments: float = 0.90


@dataclass
class LiquidationResult:
    """Output shape — defensive, never raises on bad inputs."""
    liquidation_value_aggregate: Optional[float]
    liquidation_per_share: Optional[float]
    asset_recoveries: dict
    total_liabilities: float
    method: str
    sanity_warnings: list = field(default_factory=list)
    floor_safety_margin: Optional[float] = None


# ─────────────────────────────────────────────────────────────────
# Sector helper
# ─────────────────────────────────────────────────────────────────

def _normalise_sector(sector: Optional[str]) -> str:
    if not sector:
        return ""
    return str(sector).strip().lower()


def get_sector_ppe_recovery(sector: Optional[str]) -> float:
    """Return the PP&E recovery rate for a given sector.

    Auto / Capital Goods: 0.45 (specialised but resaleable)
    FMCG / Pharma: 0.30 (specialised factories, low resale)
    Real Estate: 0.70 (the asset IS the property)
    Hotels: 0.50 (location-anchored)
    Metals / Cement: 0.55 (heavy machinery, commodity demand)
    IT Services: 0.20 (mostly leased offices, low PP&E)
    Default: 0.40
    """
    key = _normalise_sector(sector)
    if not key:
        return _DEFAULT_PPE_RECOVERY
    if key in _SECTOR_PPE_RECOVERY:
        return _SECTOR_PPE_RECOVERY[key]
    # Substring fallback so callers passing "Auto Components" or
    # "IT - Software" land on the right bucket.
    for known_key, rate in _SECTOR_PPE_RECOVERY.items():
        if known_key in key or key in known_key:
            return rate
    return _DEFAULT_PPE_RECOVERY


# ─────────────────────────────────────────────────────────────────
# Inventory recovery — prefers sub-breakdown when present
# ─────────────────────────────────────────────────────────────────

def _compute_inventory_recovery(
    inputs: LiquidationInputs,
    rates: LiquidationRecoveryRates,
) -> tuple[float, str]:
    """Return (recovered_value, mode).

    Mode is "sub_breakdown" when raw/WIP/finished were provided
    individually, "blended" when only the aggregate inventory line
    was available.
    """
    raw = inputs.inventory_raw_materials
    wip = inputs.inventory_wip
    finished = inputs.inventory_finished
    if (
        raw is not None
        and wip is not None
        and finished is not None
        and (raw + wip + finished) > 0
    ):
        recovered = (
            max(0.0, float(raw)) * rates.inventory_raw
            + max(0.0, float(wip)) * rates.inventory_wip
            + max(0.0, float(finished)) * rates.inventory_finished
        )
        return recovered, "sub_breakdown"
    blended = max(0.0, float(inputs.inventory or 0.0)) * rates.inventory_blended
    return blended, "blended"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────

def compute_liquidation_value(
    inputs: LiquidationInputs,
    current_price: Optional[float] = None,
) -> LiquidationResult:
    """Compute Graham-style liquidation value. Defensive — never raises.

    When ``current_price`` is provided, the result includes a
    ``floor_safety_margin`` (current_price - liquidation_per_share).
    Positive means the market price is above the asset floor;
    negative means the market is pricing the equity below
    asset-coverage value (a deep-value signal).

    Returns a LiquidationResult with method:
      - "liquidation_full" when the headline assets (cash, receivables,
        inventory, PP&E net) are all positive numerics
      - "liquidation_partial_inputs" when only a subset is available
      - "unavailable" when nothing usable was supplied

    Sanity warnings (emitted on the result):
      - "negative_liquidation_value" — liabilities exceed even
        full-recovery assets (distress signal)
      - "negative_per_share" — per_share fell below zero (distress)
      - "intangibles_dominate_assets" — goodwill + intangibles > 30%
        of total assets (asset-light; floor under-states value)
      - "no_shares_outstanding" — shares=0 means per_share is None
    """
    if inputs is None:
        return LiquidationResult(
            liquidation_value_aggregate=None,
            liquidation_per_share=None,
            asset_recoveries={},
            total_liabilities=0.0,
            method="unavailable",
            sanity_warnings=["null_inputs"],
        )

    rates = LiquidationRecoveryRates()
    rates.ppe = get_sector_ppe_recovery(inputs.sector)

    # ── Asset recoveries ──────────────────────────────────────────
    cash = max(0.0, _safe_float(inputs.cash_and_equivalents))
    sti = max(0.0, _safe_float(inputs.short_term_investments))
    recv = max(0.0, _safe_float(inputs.receivables))
    inv_recovered, inv_mode = _compute_inventory_recovery(inputs, rates)

    # Prefer ppe_net (book net of accumulated depreciation) — that
    # is the actual carrying value the auction would proceed against.
    # Fall back to ppe_gross when net is missing.
    ppe_basis = _safe_float(inputs.ppe_net)
    if ppe_basis <= 0.0:
        ppe_basis = _safe_float(inputs.ppe_gross)
    ppe_basis = max(0.0, ppe_basis)

    intang = max(0.0, _safe_float(inputs.intangibles))
    goodwill = max(0.0, _safe_float(inputs.goodwill))
    lti = max(0.0, _safe_float(inputs.long_term_investments))
    other = max(0.0, _safe_float(inputs.other_assets))

    asset_recoveries: dict = {
        "cash_and_equivalents": round(cash * rates.cash, 4),
        "short_term_investments": round(sti * rates.short_term_investments, 4),
        "receivables": round(recv * rates.receivables, 4),
        "inventory": round(inv_recovered, 4),
        "ppe": round(ppe_basis * rates.ppe, 4),
        "intangibles": round(intang * rates.intangibles, 4),
        "goodwill": round(goodwill * rates.goodwill, 4),
        "long_term_investments": round(lti * rates.long_term_investments, 4),
        "other_assets": round(other * rates.other_assets, 4),
    }

    total_recovered = sum(asset_recoveries.values())

    # ── Liabilities (must be paid in full) ────────────────────────
    st_debt = max(0.0, _safe_float(inputs.short_term_debt))
    lt_debt = max(0.0, _safe_float(inputs.long_term_debt))
    ap = max(0.0, _safe_float(inputs.accounts_payable))
    ol = max(0.0, _safe_float(inputs.other_liabilities))
    total_liabilities = st_debt + lt_debt + ap + ol

    # ── Aggregate liquidation value ───────────────────────────────
    liquidation_aggregate = total_recovered - total_liabilities

    # ── Method classification ─────────────────────────────────────
    # "Full" requires at minimum cash, receivables, inventory, and
    # PP&E to be present and the aggregate to be a real number.
    has_full_assets = (
        cash > 0.0
        and (recv > 0.0 or inv_recovered > 0.0)
        and ppe_basis > 0.0
    )
    if total_recovered <= 0.0 and total_liabilities <= 0.0:
        method = "unavailable"
    elif has_full_assets:
        method = "liquidation_full"
    else:
        method = "liquidation_partial_inputs"

    # ── Per-share derivation ──────────────────────────────────────
    shares = _safe_float(inputs.shares_outstanding)
    sanity_warnings: list = []
    per_share: Optional[float]
    if shares > 0.0:
        per_share = round(liquidation_aggregate / shares, 4)
    else:
        per_share = None
        sanity_warnings.append("no_shares_outstanding")

    # ── Sanity warnings ───────────────────────────────────────────
    if liquidation_aggregate < 0.0:
        sanity_warnings.append("negative_liquidation_value")
    if per_share is not None and per_share < 0.0:
        # Avoid double-flag — negative_liquidation_value implies this.
        if "negative_liquidation_value" not in sanity_warnings:
            sanity_warnings.append("negative_per_share")

    # Intangibles + goodwill dominance check — denominator is the
    # gross asset base BEFORE haircuts, so we measure the
    # composition of book value rather than the composition of
    # recovered value (which is 0 for these lines by construction).
    gross_assets = (
        cash + sti + recv + max(0.0, _safe_float(inputs.inventory))
        + ppe_basis + intang + goodwill + lti + other
    )
    if gross_assets > 0.0:
        intang_share = (intang + goodwill) / gross_assets
        if intang_share > _INTANGIBLES_DOMINANCE_THRESHOLD:
            sanity_warnings.append("intangibles_dominate_assets")

    # ── Floor safety margin (price - floor) ───────────────────────
    floor_safety_margin: Optional[float] = None
    if current_price is not None and per_share is not None:
        try:
            floor_safety_margin = round(float(current_price) - per_share, 4)
        except (TypeError, ValueError):
            floor_safety_margin = None

    # Augment asset_recoveries with the inventory mode marker for
    # observability — downstream consumers can surface "used
    # sub-breakdown" vs "blended" in the explainer panel.
    asset_recoveries["_inventory_mode"] = inv_mode
    asset_recoveries["_ppe_recovery_rate"] = round(rates.ppe, 4)

    return LiquidationResult(
        liquidation_value_aggregate=round(liquidation_aggregate, 4),
        liquidation_per_share=per_share,
        asset_recoveries=asset_recoveries,
        total_liabilities=round(total_liabilities, 4),
        method=method,
        sanity_warnings=sanity_warnings,
        floor_safety_margin=floor_safety_margin,
    )


# ─────────────────────────────────────────────────────────────────
# Applicability helper
# ─────────────────────────────────────────────────────────────────

def is_liquidation_meaningful(
    ticker: str,
    sector: Optional[str],
    ppe_ratio: Optional[float],
) -> tuple[bool, str]:
    """Return ``(meaningful, reason)`` for whether the liquidation
    floor is informative for this ticker.

    Liquidation value is most informative for asset-heavy businesses.
    Banks and insurers run on a different framework (capital adequacy)
    — return False with a reason so the caller can omit the panel.
    IT services / AMCs are technically computable but the floor is
    dominated by cash, which under-states franchise value.

    ``ppe_ratio`` is PP&E / Total Assets. When provided, we use it as
    the primary signal; the sector-level fallback is informative when
    the caller has no balance-sheet ratio handy.
    """
    sec = _normalise_sector(sector)

    # Hard exclusion: banks / NBFCs / insurance run on different
    # frameworks. Their balance sheets are dominated by loan books,
    # deposit liabilities, and reserve assets; a liquidation-value
    # floor is conceptually misleading.
    if sec in _LIQUIDATION_NOT_APPLICABLE_SECTORS:
        return (
            False,
            "Banks / NBFCs / insurers operate under a capital-"
            "adequacy framework. Liquidation value is not applicable.",
        )

    # PP&E ratio signal: if the company is asset-light, flag.
    if ppe_ratio is not None:
        try:
            ratio = float(ppe_ratio)
        except (TypeError, ValueError):
            ratio = None  # type: ignore[assignment]
        else:
            if ratio < _LIQUIDATION_LOW_PPE_THRESHOLD:
                return (
                    False,
                    f"PP&E is {ratio * 100:.1f}% of total assets. "
                    "Asset-light businesses derive value from "
                    "earnings power, not asset coverage.",
                )

    # Sector-level fallback for asset-light cohorts when no
    # explicit ratio is available.
    if sec in {"it", "it services", "technology", "software"}:
        return (
            False,
            "IT services derive value from headcount + contracts, "
            "not PP&E. Liquidation floor under-states franchise value.",
        )

    return (True, "Asset-heavy business — liquidation floor is informative.")


# ─────────────────────────────────────────────────────────────────
# JSON projection
# ─────────────────────────────────────────────────────────────────

def to_dict(result: LiquidationResult) -> dict:
    """JSON-safe projection of a LiquidationResult.

    Mirrors the shape of compute_financial_fair_value /
    compute_appraisal_fair_value so the analysis pipeline can splice
    this into the response payload alongside the other valuation
    methods without reshaping the surrounding code.
    """
    if result is None:
        return {
            "liquidation_value_aggregate": None,
            "liquidation_per_share": None,
            "asset_recoveries": {},
            "total_liabilities": 0.0,
            "method": "unavailable",
            "sanity_warnings": ["null_result"],
            "floor_safety_margin": None,
        }
    return {
        "liquidation_value_aggregate": result.liquidation_value_aggregate,
        "liquidation_per_share": result.liquidation_per_share,
        "asset_recoveries": dict(result.asset_recoveries or {}),
        "total_liabilities": result.total_liabilities,
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
        "floor_safety_margin": result.floor_safety_margin,
    }
