"""NBFC ROA-decomposition (DuPont) valuation service — T3.2 Phase A.

Why this exists
───────────────
Indian Non-Banking Financial Companies (NBFCs) are mis-valued by every
existing engine:

  - Generic DCF: lending businesses don't have "free cash flow" in the
    industrial sense — incremental loans are an investing outflow, not
    an operating one. Trailing FCF is structurally negative for any
    growing NBFC.
  - Bank cohort (P/BV anchor at sub-segment medians): NBFCs don't take
    deposits, so cost-of-funds, leverage caps, and regulatory capital
    rules all differ from banks. A 3.0× P/BV that's correct for HDFCBANK
    is meaningless for MUTHOOTFIN (gold-loan specialist, no deposits,
    different RBI capital regime).
  - Tier 2 cohort (P/E peer median): the 12 NBFCs the cut list covers
    span four sub-segments (gold loan / vehicle / housing / consumer)
    that trade at structurally different P/E multiples — pooling them
    into a generic financials peer median produces noise, not signal.

The standard analyst frame for NBFC valuation is the **ROA tree**
(DuPont decomposition for financials):

    ROA = (II - IE - Provisions - Opex + Fee Income) × (1 - tax) / Avg Assets
    ROE = ROA × Leverage              where Leverage = Avg Assets / Avg Equity

Then convert to P/B via Gordon growth on book value:

    Fair P/B = ROE × Payout / (k_e - g_sustainable)
    Fair Value per Share = Fair P/B × Book Value per Share

Sub-segment defaults (yield / cost-of-funds / credit cost / opex) are
calibrated by ROA-tree component to the published RBI sectoral data
plus the FY25/FY26 disclosure pack of the 12 listed NBFCs in
``NBFC_TICKERS``. They are starting points — the caller passes
ticker-level inputs in ``NBFCInputs`` which always override defaults.

Caller contract
───────────────
compute_nbfc_fair_value(inputs) -> NBFCROAResult

Each scalar in NBFCInputs is a decimal (0.18 = 18%), except the
two _inr_cr fields which are amounts in INR crores. The result
carries the full ROA-tree breakdown in ``components`` so the caller
can render the DuPont waterfall without recomputing.

Discipline
──────────
- Returns ``method="unavailable"`` (not None) when ROA can't compute —
  the caller can still surface sanity warnings and the partial
  components dict.
- Gordon (k - g) inversion returns ``fair_pb=None`` — never silently
  flips sign or substitutes a fallback multiple.
- Sanity warnings are observational, not gating. Caller decides what
  to do with "leverage > 10x".
- Phase A is standalone — no router wiring, no manifest read-path
  invalidation of existing rows (manifest entry is documentation-only).
  Phase B routes the 12 NBFC tickers through this engine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.nbfc_roa")


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────

NBFCSegment = Literal[
    "gold_loan",
    "vehicle_finance",
    "housing_finance",
    "consumer_finance",
    "sme_finance",
    "diversified",
    "amc",
]


@dataclass
class NBFCInputs:
    """Inputs to the ROA-tree DuPont valuation.

    All ratio fields are DECIMAL (0.18 = 18%), NOT percentage points,
    despite the ``_pct`` suffix in their names (the suffix indicates
    "this is a rate-like quantity", not the unit). Two amount fields
    (``average_assets_inr_cr``, ``average_equity_inr_cr``) are in
    INR crores.

    The ratio fields are all computed against **average assets** (not
    against the loan book alone) so the components sum cleanly into
    ROA. Callers who have NIM-on-AUM should re-base to NIM-on-assets
    before populating ``yield_on_assets_pct`` / ``cost_of_funds_pct``.
    """

    average_assets_inr_cr: float
    average_equity_inr_cr: float
    # ROA-tree components (annualized, decimal, all on avg assets)
    yield_on_assets_pct: float           # interest income / avg assets
    cost_of_funds_pct: float             # interest expense / avg assets
    credit_cost_pct: float               # provisions + write-offs / avg assets
    opex_ratio_pct: float                # operating expenses / avg assets
    fee_income_pct: float = 0.0          # non-interest income / avg assets
    tax_rate: float = 0.25
    # Forward inputs for fair-PB derivation
    expected_loan_growth_pct: float = 0.18
    payout_ratio: float = 0.20           # dividend payout
    cost_of_equity: float = 0.135        # NBFC k_e — higher than banks
    sustainable_growth: float = 0.10     # long-term BV growth
    # Per-share normalizers (optional — leave 0 to skip per-share output)
    shares_outstanding: float = 0.0
    book_value_per_share: float = 0.0
    segment: NBFCSegment = "diversified"


@dataclass
class NBFCROAResult:
    """ROA-tree decomposition + Gordon-derived P/B + per-share value.

    ``components`` always carries the full DuPont waterfall (even when
    method == "unavailable") so the caller can render whichever
    sub-components did compute. ``sanity_warnings`` is observational;
    the caller decides whether to surface or gate on them.
    """

    roa_pct: Optional[float]
    roe_pct: Optional[float]
    leverage: Optional[float]
    fair_pb: Optional[float]
    fair_value_per_share: Optional[float]
    components: dict = field(default_factory=dict)
    sanity_warnings: list[str] = field(default_factory=list)
    method: str = "roa_tree_dupont"


# ─────────────────────────────────────────────────────────────────
# Segment defaults
# ─────────────────────────────────────────────────────────────────

NBFC_SEGMENT_DEFAULTS: dict[str, dict] = {
    "gold_loan": {
        # MUTHOOTFIN / MANAPPURAM — short-tenor, high-yield, low-risk
        # because of LTV cushion + auction recourse.
        "expected_yield": 0.22,
        "expected_credit_cost": 0.005,
        "expected_opex_ratio": 0.045,
        "expected_cof": 0.085,
        "expected_growth": 0.15,
        "cost_of_equity": 0.13,
    },
    "vehicle_finance": {
        # CHOLAFIN / M&MFIN / SHRIRAMFIN — secured against CV / passenger
        # vehicle / tractor collateral; medium yield, mid-cycle credit
        # costs around 1.5%.
        "expected_yield": 0.14,
        "expected_credit_cost": 0.015,
        "expected_opex_ratio": 0.04,
        "expected_cof": 0.075,
        "expected_growth": 0.18,
        "cost_of_equity": 0.135,
    },
    "housing_finance": {
        # LICHSGFIN — long-tenor secured against home, low yield, very
        # low credit cost, low opex (low fee/touch product).
        "expected_yield": 0.09,
        "expected_credit_cost": 0.005,
        "expected_opex_ratio": 0.015,
        "expected_cof": 0.07,
        "expected_growth": 0.14,
        "cost_of_equity": 0.12,
    },
    "consumer_finance": {
        # BAJFINANCE / POONAWALLA — diversified consumer + SME unsecured
        # + secured mix. Higher yield, cycle-dependent credit cost.
        "expected_yield": 0.18,
        "expected_credit_cost": 0.025,
        "expected_opex_ratio": 0.055,
        "expected_cof": 0.08,
        "expected_growth": 0.22,
        "cost_of_equity": 0.14,
    },
    "sme_finance": {
        # Pure SME lenders. Yield close to consumer, credit cost slightly
        # lower than unsecured consumer (some collateral).
        "expected_yield": 0.16,
        "expected_credit_cost": 0.02,
        "expected_opex_ratio": 0.045,
        "expected_cof": 0.08,
        "expected_growth": 0.18,
        "cost_of_equity": 0.135,
    },
    "diversified": {
        # LTFH / IIFL — mixed book; blended midpoint of the above.
        "expected_yield": 0.13,
        "expected_credit_cost": 0.015,
        "expected_opex_ratio": 0.035,
        "expected_cof": 0.075,
        "expected_growth": 0.16,
        "cost_of_equity": 0.135,
    },
    "amc": {
        # HDFCAMC — fee-revenue model, not lending. ROA tree doesn't
        # naturally apply (no interest spread). Defaults here are
        # placeholders so the dispatch path doesn't crash; the caller
        # SHOULD route AMCs through a P/AUM or P/E peer engine
        # instead. is_nbfc_applicable() returns True for AMC tickers
        # to keep the cohort enumerable, but the caller is expected
        # to skip this engine for them.
        "expected_yield": 0.0,
        "expected_credit_cost": 0.0,
        "expected_opex_ratio": 0.03,
        "expected_cof": 0.0,
        "expected_growth": 0.18,
        "cost_of_equity": 0.13,
    },
}


# Bare tickers (no .NS) → segment. Keep alphabetical for readability.
NBFC_TICKERS: dict[str, NBFCSegment] = {
    "BAJFINANCE":  "consumer_finance",
    "BAJAJFINSV":  "diversified",
    "CHOLAFIN":    "vehicle_finance",
    "HDFCAMC":     "amc",
    "IIFL":        "diversified",
    "LICHSGFIN":   "housing_finance",
    "LTFH":        "diversified",
    "M&MFIN":      "vehicle_finance",
    "MANAPPURAM":  "gold_loan",
    "MUTHOOTFIN":  "gold_loan",
    "POONAWALLA":  "consumer_finance",
    "SHRIRAMFIN":  "vehicle_finance",
}


# Sector / industry strings that should route through the NBFC engine.
# Matched case-insensitively against a stripped substring of the
# caller-supplied sector. Banks are EXPLICITLY excluded — the caller's
# bank-cohort engine owns those tickers.
_NBFC_SECTOR_HINTS = (
    "nbfc",
    "non-banking financial",
    "non banking financial",
    "consumer finance",
    "vehicle finance",
    "housing finance",
    "gold loan",
    "asset management",
)

_BANK_SECTOR_HINTS = (
    "bank",
    "banking",
)


# Sanity thresholds (decimal where applicable)
_ROA_LOSS_THRESHOLD = 0.0
_ROA_EXCEPTIONAL_THRESHOLD = 0.05
_CREDIT_COST_STRESS_THRESHOLD = 0.05
_LEVERAGE_HIGH_THRESHOLD = 10.0
_FAIR_PB_EXTREME_THRESHOLD = 8.0


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None:
        return None
    try:
        if den == 0:
            return None
        return num / den
    except (TypeError, ZeroDivisionError):
        return None


def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against NBFC_TICKERS keys."""
    if not ticker:
        return ""
    bare = ticker
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.upper().endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare.upper()


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def get_segment_defaults(segment: NBFCSegment) -> dict:
    """Return the calibrated defaults dict for a segment.

    Always returns a fresh shallow copy so callers can mutate the
    result without polluting the module-level constant. Falls back
    to ``diversified`` if an unknown segment is passed.
    """
    payload = NBFC_SEGMENT_DEFAULTS.get(
        segment, NBFC_SEGMENT_DEFAULTS["diversified"]
    )
    return dict(payload)


def is_nbfc_applicable(
    ticker: str, sector: Optional[str]
) -> tuple[bool, str]:
    """True iff the ticker should be routed through the NBFC engine.

    Returns (applicable, reason). ``reason`` is a short human-readable
    string for logs / admin tooling — never user-facing.

    Resolution order:
      1. Bare ticker present in NBFC_TICKERS → True
      2. Sector substring matches a bank hint → False (banks own those)
      3. Sector substring matches an NBFC hint → True
      4. Otherwise → False
    """
    bare = _bare_ticker(ticker)
    if bare in NBFC_TICKERS:
        return True, f"ticker {bare} in NBFC_TICKERS ({NBFC_TICKERS[bare]})"

    if not sector:
        return False, "no sector hint and ticker not in NBFC_TICKERS"

    s = sector.strip().lower()

    # NBFC hint check FIRST — "Non-Banking Financial Company" contains
    # the substring "banking" but is explicitly an NBFC label, so the
    # NBFC hint must take precedence over the bank substring check.
    for hint in _NBFC_SECTOR_HINTS:
        if hint in s:
            return True, f"sector matches NBFC hint '{hint}'"

    # Bank check — "Banking and Financial Services" routes to the bank
    # engine, not here. Substring match is safe now that the NBFC hints
    # ("nbfc", "non-banking financial", ...) have already won above.
    for hint in _BANK_SECTOR_HINTS:
        if hint in s:
            return False, f"sector matches bank hint '{hint}' — not an NBFC"

    return False, f"sector '{sector}' does not match NBFC hints"


def compute_roa_tree(inputs: NBFCInputs) -> dict:
    """Compute the full DuPont decomposition (decimal, on avg assets).

    Returns a dict with all components present, even when the rollup
    is degenerate (e.g. avg assets = 0 → roa = None). Component fields:
      yield, cost_of_funds, nim_proxy, credit_cost, opex, fee_income,
      pre_tax_roa, tax, roa.
    """
    y = float(inputs.yield_on_assets_pct or 0.0)
    cof = float(inputs.cost_of_funds_pct or 0.0)
    cc = float(inputs.credit_cost_pct or 0.0)
    opex = float(inputs.opex_ratio_pct or 0.0)
    fee = float(inputs.fee_income_pct or 0.0)
    tax = float(inputs.tax_rate or 0.0)

    nim_proxy = y - cof
    pre_tax_roa = nim_proxy - cc - opex + fee
    # Tax applies on positive earnings; losses pass through unshielded
    # so we don't inflate ROA via a tax credit assumption.
    if pre_tax_roa > 0:
        tax_drag = pre_tax_roa * tax
        roa = pre_tax_roa - tax_drag
    else:
        tax_drag = 0.0
        roa = pre_tax_roa

    return {
        "yield": y,
        "cost_of_funds": cof,
        "nim_proxy": nim_proxy,
        "credit_cost": cc,
        "opex": opex,
        "fee_income": fee,
        "pre_tax_roa": pre_tax_roa,
        "tax": tax_drag,
        "roa": roa,
    }


def compute_fair_pb_gordon(
    roe: float,
    payout: float,
    cost_of_equity: float,
    sustainable_growth: float,
) -> Optional[float]:
    """Gordon-growth fair P/B.

        Fair P/B = ROE × Payout / (k_e - g)

    Returns None when (k_e - g) <= 0 — the Gordon model is undefined
    in that region and the caller must use a different anchor. Also
    returns None on non-finite / negative-ROE inputs (negative ROE
    produces a negative fair P/B which is conceptually meaningless
    — a loss-making book doesn't deserve a "negative price-to-book").
    """
    try:
        spread = float(cost_of_equity) - float(sustainable_growth)
    except (TypeError, ValueError):
        return None
    if spread <= 0:
        return None
    try:
        roe_f = float(roe)
        payout_f = float(payout)
    except (TypeError, ValueError):
        return None
    if roe_f <= 0:
        return None
    fair_pb = roe_f * payout_f / spread
    if fair_pb <= 0:
        return None
    return fair_pb


def _build_sanity_warnings(
    roa: Optional[float],
    credit_cost: float,
    leverage: Optional[float],
    fair_pb: Optional[float],
    fair_pb_invert: bool,
) -> list[str]:
    """Collect observational warnings — never raises, never gates."""
    warns: list[str] = []
    if roa is not None:
        if roa < _ROA_LOSS_THRESHOLD:
            warns.append(
                "ROA < 0 — loss-making; check credit cycle stress "
                "or one-off provisions"
            )
        elif roa > _ROA_EXCEPTIONAL_THRESHOLD:
            warns.append(
                f"ROA > {_ROA_EXCEPTIONAL_THRESHOLD * 100:.1f}% — "
                "exceptional yield (gold-loan peak?) or data error"
            )
    if credit_cost > _CREDIT_COST_STRESS_THRESHOLD:
        warns.append(
            f"credit cost > {_CREDIT_COST_STRESS_THRESHOLD * 100:.1f}% "
            "— stressed loan book"
        )
    if leverage is not None and leverage > _LEVERAGE_HIGH_THRESHOLD:
        warns.append(
            f"leverage > {_LEVERAGE_HIGH_THRESHOLD:.0f}x — high even "
            "for an NBFC"
        )
    if fair_pb is not None and fair_pb > _FAIR_PB_EXTREME_THRESHOLD:
        warns.append(
            f"fair P/B > {_FAIR_PB_EXTREME_THRESHOLD:.0f} — valuation "
            "seems extreme; revisit ROE / cost-of-equity inputs"
        )
    if fair_pb_invert:
        warns.append(
            "(k - g) inversion — terminal-growth assumption needs "
            "tightening (sustainable_growth >= cost_of_equity)"
        )
    return warns


def compute_nbfc_fair_value(inputs: NBFCInputs) -> NBFCROAResult:
    """Main entry — ROA tree → ROE → Gordon fair-PB → per-share value.

    Always returns an NBFCROAResult. ``method == "unavailable"`` when
    average assets / average equity are non-positive (we can't even
    compute leverage). All other failure modes (Gordon inversion,
    negative ROE) leave method == "roa_tree_dupont" but null the
    downstream fields.
    """
    components = compute_roa_tree(inputs)
    roa = components.get("roa")

    avg_assets = float(inputs.average_assets_inr_cr or 0.0)
    avg_equity = float(inputs.average_equity_inr_cr or 0.0)

    leverage: Optional[float] = None
    if avg_assets > 0 and avg_equity > 0:
        leverage = avg_assets / avg_equity

    if leverage is None or roa is None:
        warns = _build_sanity_warnings(
            roa=roa,
            credit_cost=float(inputs.credit_cost_pct or 0.0),
            leverage=leverage,
            fair_pb=None,
            fair_pb_invert=False,
        )
        warns.append(
            "ROA tree unavailable — need positive average_assets_inr_cr "
            "and average_equity_inr_cr"
        )
        return NBFCROAResult(
            roa_pct=roa,
            roe_pct=None,
            leverage=leverage,
            fair_pb=None,
            fair_value_per_share=None,
            components=components,
            sanity_warnings=warns,
            method="unavailable",
        )

    roe = roa * leverage

    fair_pb = compute_fair_pb_gordon(
        roe=roe,
        payout=float(inputs.payout_ratio or 0.0),
        cost_of_equity=float(inputs.cost_of_equity or 0.0),
        sustainable_growth=float(inputs.sustainable_growth or 0.0),
    )

    fair_pb_invert = (
        float(inputs.cost_of_equity or 0.0)
        - float(inputs.sustainable_growth or 0.0)
        <= 0
    )

    fv_per_share: Optional[float] = None
    bvps = float(inputs.book_value_per_share or 0.0)
    shares = float(inputs.shares_outstanding or 0.0)
    if fair_pb is not None and bvps > 0 and shares > 0:
        fv_per_share = fair_pb * bvps

    warns = _build_sanity_warnings(
        roa=roa,
        credit_cost=float(inputs.credit_cost_pct or 0.0),
        leverage=leverage,
        fair_pb=fair_pb,
        fair_pb_invert=fair_pb_invert,
    )

    return NBFCROAResult(
        roa_pct=roa,
        roe_pct=roe,
        leverage=leverage,
        fair_pb=fair_pb,
        fair_value_per_share=fv_per_share,
        components=components,
        sanity_warnings=warns,
        method="roa_tree_dupont",
    )


def to_dict(result: NBFCROAResult) -> dict:
    """JSON-safe projection — every value is a plain Python primitive."""
    return {
        "roa_pct": result.roa_pct,
        "roe_pct": result.roe_pct,
        "leverage": result.leverage,
        "fair_pb": result.fair_pb,
        "fair_value_per_share": result.fair_value_per_share,
        "components": dict(result.components or {}),
        "sanity_warnings": list(result.sanity_warnings or []),
        "method": result.method,
    }


__all__ = [
    "NBFCSegment",
    "NBFCInputs",
    "NBFCROAResult",
    "NBFC_SEGMENT_DEFAULTS",
    "NBFC_TICKERS",
    "compute_roa_tree",
    "compute_fair_pb_gordon",
    "compute_nbfc_fair_value",
    "get_segment_defaults",
    "is_nbfc_applicable",
    "to_dict",
]
