# backend/services/consumer_durables_wc_service.py
# ═══════════════════════════════════════════════════════════════
# Consumer-durables Working-Capital intensity valuation service
# (T3.13 Phase A).
#
# Standalone service. Phase B will wire into the analysis route in a
# separate PR — this Phase A ships only the engine math, the
# applicability gate, and a JSON-safe serializer so the wiring PR can
# mirror the financial / telecom / pharma plumbing without touching any
# caller today.
#
# Why this exists:
#   Standard DCF mis-prices Indian consumer-durables for three reasons:
#
#     1. Working capital DOMINATES FCF. A fan-maker's CFO can flip from
#        +₹400 Cr to −₹500 Cr in a single quarter just from inventory
#        build ahead of the summer AC / fan season. Single-year WC
#        snapshots are noise, not signal.
#     2. Dealer credit cycles are long (60-90 day receivables) and
#        seasonal. Aggregating one year's WC into the FCF bridge
#        produces a wildly different number depending on whether you
#        sampled a build quarter or a release quarter.
#     3. Brand premium is real and EV/EBITDA-anchored. HAVELLS / VOLTAS
#        trade at 25-35x EV/EBITDA on franchise strength, where generic
#        manufacturing trades at 12-15x. A DCF that ignores the brand-
#        multiple disconnect understates fair value by 30-50%.
#
#   Industry-standard frame: normalize WC intensity (WC / Revenue) on a
#   5-year median, charge "excess WC" (current − normalized) at the cost
#   of equity as a drag, and anchor enterprise value off forward EBITDA
#   × a brand-premium multiple. Cross-checked by the operating-cycle
#   median (days inventory + days receivable − days payable) as a
#   franchise-quality tell.
#
# Indian listed consumer-durables universe covered (12):
#   HAVELLS       — switchgear + premium kitchen / fans / lighting
#   VOLTAS        — AC + commercial refrigeration (Tata group)
#   CROMPTON      — fans + premium kitchen + lighting
#   WHIRLPOOL     — refrigerators + washing machines (MNC subsidiary)
#   BLUESTARCO    — AC + commercial refrigeration
#   ORIENTELEC    — fans + lighting + small appliances
#   BAJAJELEC     — fans + lighting + kitchen + EPC overhang
#   V-GUARD       — stabilizers + wires + water heaters
#   KEI           — cables + wires (industrial + housing)
#   AMBER         — AC OEM (component manufacturer for the brands above)
#   DIXON         — electronics contract manufacturer (TV / mobile / LED)
#   POLYCAB       — cables + wires + FMEG
#
#   RAJESHEXPO intentionally excluded from the frozenset universe — it
#   is a jewellery retailer mis-categorised as consumer durables by some
#   data providers; its WC pattern (gold inventory hedge) does not map
#   onto the white-goods seasonal-build frame. The brief lists it under
#   the prose universe for awareness but the frozenset is the source of
#   truth for is_consumer_durables_applicable.
#
# Caller contract (Phase B will wire these):
#   compute_consumer_durables_fv(inputs) -> ConsumerDurablesResult
#   compute_normalized_wc(history) -> float
#   compute_wc_drag(current, normalized, revenue) -> float
#   classify_wc_intensity(current_pct, median_pct) -> str
#   is_consumer_durables_applicable(ticker, sector) -> (bool, reason)
#   to_dict(result) -> dict
#
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.consumer_durables_wc")


# ── Universe ─────────────────────────────────────────────────────
#
# Frozenset is the source of truth for the applicability gate.
# RAJESHEXPO deliberately omitted — see module docstring.
CONSUMER_DURABLES_TICKERS: frozenset[str] = frozenset({
    "HAVELLS", "VOLTAS", "CROMPTON", "WHIRLPOOL", "BLUESTARCO",
    "ORIENTELEC", "BAJAJELEC", "V-GUARD", "KEI", "AMBER",
    "DIXON", "POLYCAB",
})


# ── Defaults + clamps ────────────────────────────────────────────
#
# Cost of equity used to charge excess working capital. Indian
# consumer-durables sit around 12-13% cost of equity on a CAPM read
# (Rf ~7% + 5-6% ERP × β ~1.0-1.1). 12% is the round-number midpoint.
_DEFAULT_COST_OF_EQUITY = 0.12

# Default EBITDA margin on revenue (8.5% picks up the cohort midpoint —
# CROMPTON sits ~10%, VOLTAS ~9%, KEI ~9-11%, DIXON ~4% as the EMS
# outlier on the low end).
_DEFAULT_MARGIN_PCT = 8.5

# Default EV/EBITDA multiple. Brand-driven consumer durables trade
# 25-35x — HAVELLS ~32x, VOLTAS ~30x, CROMPTON ~28x. 28x is the
# cohort midpoint that matches the brief.
_DEFAULT_EV_EBITDA = 28.0

# Intensity-label thresholds. These are relative to the firm's OWN
# 5-year median, not an absolute %.
#   efficient  : current is at most 90% of median (running tighter
#                than its own historical norm; release tailwind)
#   normal     : within +10% of median
#   stretched  : 10-25% above median
#   stressed   : >25% above median (or any time WC > 30% of revenue
#                in absolute terms, which is the deepest white-goods
#                build-phase signature)
_INTENSITY_EFFICIENT_RATIO = 0.90
_INTENSITY_NORMAL_RATIO = 1.10
_INTENSITY_STRETCHED_RATIO = 1.25

# Absolute backstop — if current WC intensity is above this hard ceiling
# (30% of revenue), label is "stressed" regardless of the relative
# comparison to the firm's median. Cohort observation: durable WC > 30%
# of revenue has historically been associated with channel-stuffing or
# pre-festive over-build.
_INTENSITY_ABSOLUTE_CEILING_PCT = 30.0


# ── Dataclasses ──────────────────────────────────────────────────
@dataclass
class ConsumerDurablesInputs:
    """All amounts in ₹Cr (Indian convention) unless suffixed _pct.

    shares_outstanding is in Cr (Indian filings convention) so the
    aggregate-EV-to-per-share conversion folds directly without a 1e7
    factor.

    operating_cycle_days_history: last 5 fiscal years of operating
    cycle days (DIO + DSO − DPO). Median is the franchise-quality
    tell.

    wc_intensity_pct_history: last 5 fiscal years of WC / Revenue, in
    percent. Median is the normalization anchor used by compute_wc_drag.
    """
    revenue_inr_cr: float
    inventory_inr_cr: float
    receivables_inr_cr: float
    payables_inr_cr: float
    operating_cycle_days_history: list[float] = field(default_factory=list)
    wc_intensity_pct_history: list[float] = field(default_factory=list)
    margin_pct: float = _DEFAULT_MARGIN_PCT
    ev_ebitda_multiple: float = _DEFAULT_EV_EBITDA
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0
    cost_of_equity: float = _DEFAULT_COST_OF_EQUITY


@dataclass
class ConsumerDurablesResult:
    fair_value_per_share: Optional[float]
    normalized_wc_intensity_pct: float       # 5y median of WC / Revenue
    current_wc_intensity_pct: float          # latest period
    wc_swing_drag_inr_cr: float              # excess WC × cost of equity
    intensity_label: str                     # efficient | normal | stretched | stressed
    operating_cycle_days_median: float
    components: dict
    sanity_warnings: list[str]


# ── Helpers ──────────────────────────────────────────────────────
def _clean_ticker(t: Optional[str]) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "").upper()


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _median_or_default(values: list[float], default: float) -> float:
    """5y median with NaN-safe filter. Returns default on empty input."""
    cleaned = [_safe_float(v) for v in (values or []) if v is not None]
    cleaned = [v for v in cleaned if not (math.isnan(v) or math.isinf(v))]
    if not cleaned:
        return default
    return float(statistics.median(cleaned))


# ── Core math ────────────────────────────────────────────────────
def compute_normalized_wc(history: list[float]) -> float:
    """5-year median of WC / Revenue (in percent).

    Returns the median of the supplied history. Empty / all-NaN input
    falls back to 15.0 (cohort-typical WC intensity for Indian consumer-
    durables, sitting between VOLTAS ~10% and the stretched-WC tail).
    """
    return _median_or_default(history, default=15.0)


def compute_wc_drag(
    current_wc: float,
    normalized_wc: float,
    revenue: float,
    cost_of_equity: float = _DEFAULT_COST_OF_EQUITY,
) -> float:
    """Cost-of-equity charge on excess working capital.

    Excess WC (₹Cr) = max(0, (current_wc_pct − normalized_wc_pct) / 100)
                      × revenue (₹Cr)
    Drag (₹Cr)      = Excess WC × cost_of_equity

    Returns 0.0 when the firm is running TIGHTER than its normalized
    intensity (no drag from being efficient; the upside is already in
    EBITDA via lower funding cost). The drag is always ≥ 0.
    """
    cur = _safe_float(current_wc)
    norm = _safe_float(normalized_wc)
    rev = _safe_float(revenue)
    ke = _safe_float(cost_of_equity, _DEFAULT_COST_OF_EQUITY)
    excess_pct = max(0.0, cur - norm)
    excess_cr = (excess_pct / 100.0) * rev
    return excess_cr * ke


def classify_wc_intensity(current_pct: float, median_pct: float) -> str:
    """Bucket the current WC intensity vs the firm's own 5y median.

    Returns one of: "efficient" | "normal" | "stretched" | "stressed".

    Absolute backstop: if current_pct > 30%, label is "stressed"
    regardless of relative ratio. This catches channel-stuffing /
    pre-festive over-build cases where even the median is also high.
    """
    cur = _safe_float(current_pct)
    med = _safe_float(median_pct)
    if cur >= _INTENSITY_ABSOLUTE_CEILING_PCT:
        return "stressed"
    if med <= 0:
        # No baseline — fall back to absolute thresholds.
        if cur < 10.0:
            return "efficient"
        if cur < 18.0:
            return "normal"
        if cur < 25.0:
            return "stretched"
        return "stressed"
    ratio = cur / med
    if ratio <= _INTENSITY_EFFICIENT_RATIO:
        return "efficient"
    if ratio <= _INTENSITY_NORMAL_RATIO:
        return "normal"
    if ratio <= _INTENSITY_STRETCHED_RATIO:
        return "stretched"
    return "stressed"


def _operating_cycle_current(
    inventory: float,
    receivables: float,
    payables: float,
    revenue: float,
) -> float:
    """Operating cycle days = DIO + DSO − DPO.

    Each leg uses (component / revenue) × 365. Revenue ≤ 0 → 0 (caller
    surfaces the sanity warning).
    """
    rev = _safe_float(revenue)
    if rev <= 0:
        return 0.0
    inv = _safe_float(inventory)
    rec = _safe_float(receivables)
    pay = _safe_float(payables)
    dio = (inv / rev) * 365.0
    dso = (rec / rev) * 365.0
    dpo = (pay / rev) * 365.0
    return dio + dso - dpo


def compute_consumer_durables_fv(
    inputs: ConsumerDurablesInputs,
) -> ConsumerDurablesResult:
    """Brand-multiple EV anchor with WC-drag charge.

    Steps:
      1. current_wc_cr   = inventory + receivables − payables
      2. current_wc_pct  = (current_wc_cr / revenue) × 100
      3. normalized_pct  = median(wc_intensity_pct_history)
                           (fallback 15% on empty history)
      4. drag_cr         = max(0, excess WC) × cost_of_equity
      5. ebitda_cr       = revenue × margin_pct / 100
      6. ev_cr           = ebitda_cr × ev_ebitda_multiple
      7. equity_cr       = ev_cr − net_debt − drag_cr
      8. fv_per_share    = equity_cr / shares_outstanding_cr

    The drag is charged at the EQUITY level (after net-debt), not the
    EV level. The interpretation: excess WC is funding cost the
    equity-holder is bearing today, and the present-value of that
    perpetual cost (rough proxy: excess × cost_of_equity, treating it
    as a one-period charge) is the equity-value cut.

    Returns a ConsumerDurablesResult with fair_value_per_share=None
    when shares are missing/zero or equity is non-positive (rare —
    requires WC > 100% of EV, which would be a distress profile).
    """
    warnings: list[str] = []

    revenue = _safe_float(inputs.revenue_inr_cr)
    if revenue <= 0:
        warnings.append("revenue non-positive — engine output suppressed")
        return ConsumerDurablesResult(
            fair_value_per_share=None,
            normalized_wc_intensity_pct=0.0,
            current_wc_intensity_pct=0.0,
            wc_swing_drag_inr_cr=0.0,
            intensity_label="unknown",
            operating_cycle_days_median=0.0,
            components={},
            sanity_warnings=warnings,
        )

    inv = _safe_float(inputs.inventory_inr_cr)
    rec = _safe_float(inputs.receivables_inr_cr)
    pay = _safe_float(inputs.payables_inr_cr)
    current_wc_cr = inv + rec - pay
    current_wc_pct = (current_wc_cr / revenue) * 100.0

    normalized_pct = compute_normalized_wc(inputs.wc_intensity_pct_history or [])
    if not inputs.wc_intensity_pct_history:
        warnings.append("wc_intensity_pct_history empty — fell back to 15% cohort default")

    ke = _safe_float(inputs.cost_of_equity, _DEFAULT_COST_OF_EQUITY)
    drag_cr = compute_wc_drag(current_wc_pct, normalized_pct, revenue, ke)

    label = classify_wc_intensity(current_wc_pct, normalized_pct)
    if label == "stressed":
        warnings.append(
            f"WC intensity stressed (current {current_wc_pct:.1f}% vs "
            f"median {normalized_pct:.1f}%) — channel-stuffing risk"
        )

    margin_pct = _safe_float(inputs.margin_pct, _DEFAULT_MARGIN_PCT)
    ev_mult = _safe_float(inputs.ev_ebitda_multiple, _DEFAULT_EV_EBITDA)
    ebitda_cr = revenue * (margin_pct / 100.0)
    ev_cr = ebitda_cr * ev_mult

    net_debt = _safe_float(inputs.net_debt_inr_cr)
    equity_cr = ev_cr - net_debt - drag_cr

    op_cycle_current = _operating_cycle_current(inv, rec, pay, revenue)
    op_cycle_median = _median_or_default(
        inputs.operating_cycle_days_history or [],
        default=op_cycle_current,
    )
    if not inputs.operating_cycle_days_history:
        warnings.append("operating_cycle_days_history empty — using current as proxy median")

    shares_cr = _safe_float(inputs.shares_outstanding)
    if shares_cr > 0 and equity_cr > 0:
        fv_per_share = round(equity_cr / shares_cr, 2)
    else:
        fv_per_share = None
        if shares_cr <= 0:
            warnings.append("shares_outstanding missing/zero — per-share suppressed")
        if equity_cr <= 0:
            warnings.append("equity_cr non-positive — distress profile or WC > EV")

    components = {
        "revenue_inr_cr": round(revenue, 2),
        "inventory_inr_cr": round(inv, 2),
        "receivables_inr_cr": round(rec, 2),
        "payables_inr_cr": round(pay, 2),
        "current_wc_inr_cr": round(current_wc_cr, 2),
        "ebitda_inr_cr": round(ebitda_cr, 2),
        "margin_pct": round(margin_pct, 2),
        "ev_ebitda_multiple": round(ev_mult, 2),
        "ev_inr_cr": round(ev_cr, 2),
        "net_debt_inr_cr": round(net_debt, 2),
        "wc_drag_inr_cr": round(drag_cr, 2),
        "equity_inr_cr": round(equity_cr, 2),
        "cost_of_equity": round(ke, 4),
        "shares_outstanding_cr": round(shares_cr, 4),
        "operating_cycle_days_current": round(op_cycle_current, 1),
        "operating_cycle_days_median": round(op_cycle_median, 1),
        "wc_intensity_pct_history": [
            round(_safe_float(v), 2) for v in (inputs.wc_intensity_pct_history or [])
        ],
        "operating_cycle_days_history": [
            round(_safe_float(v), 1) for v in (inputs.operating_cycle_days_history or [])
        ],
    }

    return ConsumerDurablesResult(
        fair_value_per_share=fv_per_share,
        normalized_wc_intensity_pct=round(normalized_pct, 2),
        current_wc_intensity_pct=round(current_wc_pct, 2),
        wc_swing_drag_inr_cr=round(drag_cr, 2),
        intensity_label=label,
        operating_cycle_days_median=round(op_cycle_median, 1),
        components=components,
        sanity_warnings=warnings,
    )


# ── Applicability gate ───────────────────────────────────────────
def is_consumer_durables_applicable(
    ticker: str,
    sector: Optional[str],
) -> tuple[bool, str]:
    """Gate for whether the consumer-durables WC engine should fire.

    Returns ``(applicable, reason)``. RAJESHEXPO is explicitly rejected
    even when miscategorised as consumer durables — its jewellery /
    gold-inventory WC pattern doesn't match the seasonal build frame.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return False, "empty ticker"
    if clean in CONSUMER_DURABLES_TICKERS:
        return True, f"{clean} in CONSUMER_DURABLES_TICKERS"
    if clean == "RAJESHEXPO":
        return False, (
            "RAJESHEXPO is jewellery retail — gold-inventory WC pattern "
            "does not match white-goods seasonal-build frame"
        )
    sec = (sector or "").strip().lower()
    if "consumer durable" in sec or "household appliance" in sec:
        return False, f"sector tagged consumer durables but {clean} not in CONSUMER_DURABLES_TICKERS"
    return False, f"{clean} not a consumer-durables ticker"


# ── JSON-safe serializer ─────────────────────────────────────────
def to_dict(result: ConsumerDurablesResult) -> dict:
    """Project a ConsumerDurablesResult into a plain dict for JSON
    responses or DB persistence. Numbers as floats; no dataclass
    instances, no datetime / Decimal types leak through.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "normalized_wc_intensity_pct": result.normalized_wc_intensity_pct,
        "current_wc_intensity_pct": result.current_wc_intensity_pct,
        "wc_swing_drag_inr_cr": result.wc_swing_drag_inr_cr,
        "intensity_label": result.intensity_label,
        "operating_cycle_days_median": result.operating_cycle_days_median,
        "components": result.components,
        "sanity_warnings": list(result.sanity_warnings),
    }
