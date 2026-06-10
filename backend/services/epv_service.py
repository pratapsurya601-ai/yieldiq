# backend/services/epv_service.py
"""Earnings Power Value (EPV) standalone service — Bruce Greenwald framework.

═══════════════════════════════════════════════════════════════
What this is
═══════════════════════════════════════════════════════════════

Bruce Greenwald's Earnings Power Value (from "Value Investing: From
Graham to Buffett and Beyond", 2001). The core idea:

    Strip out growth assumptions entirely and value the business on the
    perpetual stream of NORMALIZED earnings at current capacity.

Where DCF prices the growth story, EPV prices the business as-is.
The gap between EPV and DCF is the value attributable to growth —
useful as a sanity check ("how much of the DCF is a bet on growth
that may or may not happen?").

Headline formula:

    EPV = Normalized Earnings / Cost of Capital

"Normalized earnings" here means OWNER EARNINGS adjusted for:
  - cyclical normalization (avg EBIT margin over a 5-7 year window)
  - maintenance capex (NOT growth capex)
  - D&A added back (since maintenance capex is the real cash spend)
  - working-capital changes smoothed across the window
  - one-time items removed (handled by the caller via the history
    arrays — feed clean numbers in)
  - tax rate normalized to the country effective rate

═══════════════════════════════════════════════════════════════
Phase A scope (T2.2)
═══════════════════════════════════════════════════════════════

This module ships the standalone service only. Phase B (separate PR)
wires the result into the composite valuation engine and surfaces
``growth_value_gap`` on the analysis response.

The caller is responsible for:
  - pulling history arrays from the financials table
  - asking ``is_epv_applicable`` BEFORE calling ``compute_epv``
  - providing ``dcf_fv`` when it wants the growth-value gap surfaced

═══════════════════════════════════════════════════════════════
When NOT to use EPV
═══════════════════════════════════════════════════════════════

Greenwald is explicit that EPV is wrong for:
  - Recent IPOs (insufficient cycle history to normalize)
  - Persistently loss-making businesses (no positive earnings to
    capitalise)
  - Pure cyclicals near the top or bottom of the cycle (history
    misleads — top-of-cycle EPV is inflated, trough-of-cycle EPV
    looks like a fire sale that may never materialize)
  - Banks and insurers (different framework — appraisal value /
    embedded value lives in insurance_appraisal_service.py)
  - REITs and regulated utilities (rate-regulated returns; EPV
    understates the value of the regulated cap-base)

``is_epv_applicable`` enforces these rules.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Optional

logger = logging.getLogger("yieldiq.epv")


# ═══════════════════════════════════════════════════════════════
# Tunable constants
# ═══════════════════════════════════════════════════════════════

# Minimum history window for a valid EPV computation. Greenwald uses
# 5-7 years; we hard-floor at 5 because a 3-4 year window does not
# cover a full cycle in any cohort.
_MIN_HISTORY_YEARS = 5

# Tax rate is clamped to a sane range so a malformed input cannot
# produce a negative or implausibly-low normalized earnings figure.
_TAX_FLOOR = 0.0
_TAX_CEILING = 0.40

# Cost of capital sanity bounds. Negative or zero would divide by
# zero (or invert sign); a value above 30% is almost certainly a
# percent-vs-decimal mix-up.
_K_FLOOR = 0.001
_K_CEILING = 0.30

# Maintenance-capex fraction default. Per Greenwald, maintenance
# capex in steady-state businesses is approximately equal to D&A.
# Sector heuristic: capital-light services ~0.5, industrials ~0.7,
# heavy-cyclicals ~0.8. The caller can override per ticker / cohort.
_DEFAULT_MAINTENANCE_FRACTION = 0.6

# Sectors / classifications where EPV is NOT applicable. Matched
# case-insensitively against the ticker's sector / industry strings.
_BANK_SECTORS = frozenset({
    "bank", "banks", "private bank", "public sector bank",
    "psu bank", "financial services - bank",
})
_INSURANCE_SECTORS = frozenset({
    "insurance", "life insurance", "general insurance",
    "non-life insurance",
})
_REIT_UTILITY_SECTORS = frozenset({
    "reit", "invit", "utility", "utilities", "power utility",
    "regulated utility", "electric utility",
})


# ═══════════════════════════════════════════════════════════════
# Public dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class EPVInputs:
    """Caller-supplied inputs for one EPV computation.

    History arrays MUST be aligned (same length, same time ordering)
    with the MOST RECENT YEAR LAST. The caller is responsible for
    deduping and cleaning one-time items.
    """
    revenue_history: list[float]
    ebit_history: list[float]
    da_history: list[float]
    capex_history: list[float]
    working_capital_history: list[float]
    current_revenue: float
    cost_of_capital: float
    tax_rate: float
    shares_outstanding: float
    maintenance_capex_fraction: float = _DEFAULT_MAINTENANCE_FRACTION


@dataclass
class EPVResult:
    """Output of one EPV computation.

    ``method``:
      - ``"epv_normalized"`` — standard path: cycle-averaged EBIT
        margin × current revenue, owner-earnings adjusted.
      - ``"epv_minimum_owner_earnings"`` — fallback when the history
        carries one or more negative-EBIT years; we use the median
        rather than the mean and emit a warning. The number is still
        meaningful but less precise.
      - ``"unavailable"`` — applicability check failed or the inputs
        were defective. ``epv_per_share`` / ``epv_aggregate`` are
        None in this case.
    """
    epv_per_share: Optional[float]
    epv_aggregate: Optional[float]
    components: dict = field(default_factory=dict)
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)
    growth_value_gap: Optional[float] = None


# ═══════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════

def _is_finite_positive(x) -> bool:
    """True if x is a finite number > 0."""
    try:
        return math.isfinite(float(x)) and float(x) > 0.0
    except (TypeError, ValueError):
        return False


def _is_finite(x) -> bool:
    """True if x is a finite number (sign-agnostic)."""
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _clamp_tax_rate(t: float) -> float:
    """Bound the tax rate to a sane envelope."""
    if not _is_finite(t):
        return 0.25  # Indian effective corporate rate default
    return max(_TAX_FLOOR, min(_TAX_CEILING, float(t)))


def _clamp_maintenance_fraction(f: float) -> float:
    """Bound the maintenance-capex fraction to [0, 1]."""
    if not _is_finite(f):
        return _DEFAULT_MAINTENANCE_FRACTION
    return max(0.0, min(1.0, float(f)))


def _normalize_sector(s: Optional[str]) -> str:
    return (s or "").strip().lower()


# ═══════════════════════════════════════════════════════════════
# Public API — computational primitives
# ═══════════════════════════════════════════════════════════════

def compute_normalized_ebit_margin(
    revenue_history: list[float],
    ebit_history: list[float],
) -> Optional[float]:
    """Average EBIT margin over the history window.

    Defensive contract:
      - Lists must be the same length AND have at least
        ``_MIN_HISTORY_YEARS`` entries.
      - Years with non-positive revenue are silently dropped (you
        cannot compute a margin against zero or negative revenue).
      - Returns None when fewer than 3 valid years remain after
        cleaning — anything less is statistically meaningless.

    Returns the arithmetic mean of valid (ebit / revenue) ratios.
    The caller decides whether to swap in the median when the history
    has cyclical-trough years.
    """
    if not revenue_history or not ebit_history:
        return None
    if len(revenue_history) != len(ebit_history):
        logger.debug(
            "epv: revenue/ebit history length mismatch (%d vs %d)",
            len(revenue_history), len(ebit_history),
        )
        return None
    margins: list[float] = []
    for rev, ebit in zip(revenue_history, ebit_history):
        if not _is_finite_positive(rev):
            continue
        if not _is_finite(ebit):
            continue
        margins.append(float(ebit) / float(rev))
    if len(margins) < 3:
        return None
    return mean(margins)


def compute_owner_earnings(
    ebit: float,
    da: float,
    maintenance_capex: float,
    wc_change: float,
    tax_rate: float,
) -> float:
    """Owner earnings = EBIT(1 - t) + D&A - maint_capex - delta_WC.

    This is the Buffett / Greenwald owner-earnings definition:
      * Tax EBIT (not net income — we want pre-financing earnings)
      * Add back D&A (non-cash)
      * Subtract maintenance capex (the real cash drain that keeps
        the existing earnings stream alive)
      * Subtract working-capital change (cash trapped in receivables /
        inventory net of payables)

    All inputs in the same units (rupees, dollars — caller picks);
    returned value is in the same units.
    """
    t = _clamp_tax_rate(tax_rate)
    nopat = float(ebit) * (1.0 - t)
    return nopat + float(da) - float(maintenance_capex) - float(wc_change)


def is_epv_applicable(
    ticker: str,
    sector: Optional[str],
    revenue_history_years: int,
    has_negative_earnings: bool,
) -> tuple[bool, str]:
    """Gate: should EPV even be attempted for this name?

    Returns (applicable, reason). When applicable is False the
    ``reason`` string is human-readable and intended to be surfaced
    on the analysis page ("EPV not applicable: <reason>").

    Rules (checked in this order — the COHORT gate runs FIRST so a
    bank / insurer / REIT short-circuits with the correct copy even
    when its `revenue_history` array is empty on the cached payload):
      * Banks / insurers → use insurance_appraisal_service or
        bank cohort path (sector check FIRST so HDFCBANK et al.
        surface the right reason rather than "insufficient history
        (0 years)" — the bank cohort intentionally feeds the EPV
        adapter empty arrays since EPV is the wrong framework).
      * REITs / regulated utilities → use the regulated_utility
        or realty_valuation services.
      * Need at least ``_MIN_HISTORY_YEARS`` of history.
      * Persistently loss-making businesses → not applicable.
      * Pure cyclicals at cycle extremes: NOT gated here (we have
        no robust cycle-position detector). The caller's responsibility
        is to feed a full-cycle history.

    Order-of-checks rationale (P0 fix 2026-06-11): the bank-cohort
    path doesn't populate `computation_inputs.epv.revenue_history`
    because banks have NII not revenue — the EPV adapter input on
    those tickers is empty by construction. The PREVIOUS implementation
    short-circuited on "insufficient history (0 years; need at least
    5)" before ever reaching the sector check, which surfaced an
    incorrect reason on HDFCBANK / ICICIBANK / SBIN ("HDFCBANK is a
    30+ year listed bank with 30+ years of history — the bank cohort
    just doesn't feed EPV"). Reordering: the sector check now runs
    first so the right framework reason wins.
    """
    sec = _normalize_sector(sector)
    if sec in _BANK_SECTORS:
        return False, "banks use the financial-cohort path, not EPV"
    if sec in _INSURANCE_SECTORS:
        return False, "insurers use appraisal-value / embedded-value, not EPV"
    if sec in _REIT_UTILITY_SECTORS:
        return False, "regulated returns understate fair value under EPV"
    if revenue_history_years < _MIN_HISTORY_YEARS:
        return False, (
            f"insufficient history ({revenue_history_years} years; "
            f"need at least {_MIN_HISTORY_YEARS})"
        )
    if has_negative_earnings:
        return False, "persistently loss-making (no earnings to capitalise)"
    return True, "ok"


# ═══════════════════════════════════════════════════════════════
# Public API — main entry point
# ═══════════════════════════════════════════════════════════════

def compute_epv(
    inputs: EPVInputs,
    dcf_fv: Optional[float] = None,
) -> EPVResult:
    """Compute Earnings Power Value for one ticker.

    Returns an ``EPVResult`` with ``method = "unavailable"`` and
    ``epv_per_share = None`` when the inputs cannot support a
    meaningful computation. The caller should treat a None per-share
    as "EPV row hidden" rather than as "EPV = 0".

    When ``dcf_fv`` is supplied, ``growth_value_gap = dcf_fv - epv``
    is also returned — this is the value attributable to growth per
    Greenwald's "value of the franchise" decomposition.

    Path selection:
      * Cost-of-capital outside the sanity envelope → unavailable.
      * Shares outstanding non-positive → unavailable.
      * History arrays too short → unavailable.
      * History contains negative EBIT in any year → switch to
        median-of-margins (instead of mean) and tag method =
        ``"epv_minimum_owner_earnings"``.
    """
    warnings: list[str] = []

    # ── Cost-of-capital gate ─────────────────────────────────────
    k = float(inputs.cost_of_capital) if _is_finite(inputs.cost_of_capital) else 0.0
    if k < _K_FLOOR or k > _K_CEILING:
        return EPVResult(
            epv_per_share=None,
            epv_aggregate=None,
            components={"reason": "cost_of_capital_out_of_range", "k": k},
            method="unavailable",
            sanity_warnings=[
                f"cost_of_capital {k} outside [{_K_FLOOR}, {_K_CEILING}]"
            ],
        )

    # ── Shares-outstanding gate ─────────────────────────────────
    shares = float(inputs.shares_outstanding) if _is_finite(inputs.shares_outstanding) else 0.0
    if shares <= 0.0:
        return EPVResult(
            epv_per_share=None,
            epv_aggregate=None,
            components={"reason": "shares_outstanding_invalid", "shares": shares},
            method="unavailable",
            sanity_warnings=["shares_outstanding must be > 0"],
        )

    # ── History-length gate ─────────────────────────────────────
    n = len(inputs.revenue_history or [])
    if n < _MIN_HISTORY_YEARS:
        return EPVResult(
            epv_per_share=None,
            epv_aggregate=None,
            components={"reason": "insufficient_history", "years": n},
            method="unavailable",
            sanity_warnings=[
                f"history has {n} years; need at least {_MIN_HISTORY_YEARS}"
            ],
        )

    # ── Cyclical-trough detection ───────────────────────────────
    # If any year has negative EBIT, the mean is biased low by that
    # trough year. Greenwald's prescription is to swap to the median
    # and tag the result as the minimum-owner-earnings variant.
    has_neg_ebit = any(
        _is_finite(e) and float(e) < 0.0 for e in (inputs.ebit_history or [])
    )

    # ── Normalized EBIT margin ──────────────────────────────────
    if has_neg_ebit:
        warnings.append(
            "negative EBIT year(s) in history; using median-of-margins "
            "to dampen cyclical-trough bias"
        )
        # Median-of-margins variant
        margins: list[float] = []
        for rev, ebit in zip(inputs.revenue_history, inputs.ebit_history):
            if not _is_finite_positive(rev) or not _is_finite(ebit):
                continue
            margins.append(float(ebit) / float(rev))
        if len(margins) < 3:
            return EPVResult(
                epv_per_share=None,
                epv_aggregate=None,
                components={"reason": "too_few_valid_margins", "n": len(margins)},
                method="unavailable",
                sanity_warnings=warnings + [
                    "fewer than 3 valid margin observations after cleaning"
                ],
            )
        norm_margin = median(margins)
        method = "epv_minimum_owner_earnings"
    else:
        norm_margin = compute_normalized_ebit_margin(
            inputs.revenue_history, inputs.ebit_history
        )
        if norm_margin is None:
            return EPVResult(
                epv_per_share=None,
                epv_aggregate=None,
                components={"reason": "margin_unavailable"},
                method="unavailable",
                sanity_warnings=warnings + [
                    "normalized margin could not be computed"
                ],
            )
        method = "epv_normalized"

    # ── Apply normalized margin to current revenue ──────────────
    current_revenue = float(inputs.current_revenue) if _is_finite_positive(inputs.current_revenue) else 0.0
    if current_revenue <= 0.0:
        return EPVResult(
            epv_per_share=None,
            epv_aggregate=None,
            components={"reason": "current_revenue_invalid"},
            method="unavailable",
            sanity_warnings=warnings + ["current_revenue must be > 0"],
        )
    normalized_ebit = norm_margin * current_revenue

    # ── Maintenance capex (Greenwald conservative rule) ─────────
    # Use max(D&A, total_capex × maintenance_fraction) — Greenwald
    # argues that in steady-state, maintenance capex ≈ D&A. In growth
    # businesses, D&A understates maintenance because of inflation /
    # growth-capex commingled in capex. Take the more conservative
    # number to avoid systematically overstating owner earnings.
    da_recent = _safe_recent(inputs.da_history)
    capex_recent = _safe_recent(inputs.capex_history)
    maint_frac = _clamp_maintenance_fraction(inputs.maintenance_capex_fraction)
    capex_floor = abs(capex_recent) * maint_frac if _is_finite(capex_recent) else 0.0
    da_value = abs(da_recent) if _is_finite(da_recent) else 0.0
    maintenance_capex = max(da_value, capex_floor)

    # ── Working-capital change (smoothed across the window) ─────
    wc_change_avg = _avg_wc_change(inputs.working_capital_history)

    # ── Owner earnings ──────────────────────────────────────────
    owner_earnings = compute_owner_earnings(
        ebit=normalized_ebit,
        da=da_value,
        maintenance_capex=maintenance_capex,
        wc_change=wc_change_avg,
        tax_rate=inputs.tax_rate,
    )

    # ── Final capitalisation ────────────────────────────────────
    # EPV = owner earnings / k
    if owner_earnings <= 0.0:
        warnings.append("owner_earnings non-positive after normalization")
        return EPVResult(
            epv_per_share=None,
            epv_aggregate=None,
            components={
                "reason": "owner_earnings_non_positive",
                "owner_earnings": owner_earnings,
                "normalized_margin": norm_margin,
                "normalized_ebit": normalized_ebit,
                "maintenance_capex": maintenance_capex,
                "wc_change_avg": wc_change_avg,
            },
            method="unavailable",
            sanity_warnings=warnings,
        )

    epv_aggregate = owner_earnings / k
    epv_per_share = epv_aggregate / shares

    # ── Growth-value gap (optional) ─────────────────────────────
    growth_gap: Optional[float] = None
    if dcf_fv is not None and _is_finite(dcf_fv):
        growth_gap = float(dcf_fv) - epv_per_share

    components = {
        "normalized_margin": norm_margin,
        "normalized_ebit": normalized_ebit,
        "current_revenue": current_revenue,
        "da_recent": da_value,
        "capex_recent": capex_recent,
        "maintenance_capex": maintenance_capex,
        "maintenance_capex_fraction": maint_frac,
        "wc_change_avg": wc_change_avg,
        "tax_rate": _clamp_tax_rate(inputs.tax_rate),
        "owner_earnings": owner_earnings,
        "cost_of_capital": k,
        "shares_outstanding": shares,
        "history_years": n,
        "has_negative_ebit_year": has_neg_ebit,
    }

    return EPVResult(
        epv_per_share=epv_per_share,
        epv_aggregate=epv_aggregate,
        components=components,
        method=method,
        sanity_warnings=warnings,
        growth_value_gap=growth_gap,
    )


# ═══════════════════════════════════════════════════════════════
# Serialisation
# ═══════════════════════════════════════════════════════════════

def to_dict(result: EPVResult) -> dict:
    """JSON-safe projection of an EPVResult.

    All numeric fields stay as Python floats; the caller can let
    pydantic / json.dumps round-trip them.
    """
    return {
        "epv_per_share": result.epv_per_share,
        "epv_aggregate": result.epv_aggregate,
        "components": dict(result.components or {}),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
        "growth_value_gap": result.growth_value_gap,
    }


# ═══════════════════════════════════════════════════════════════
# Small helpers (kept private)
# ═══════════════════════════════════════════════════════════════

def _safe_recent(arr: Optional[list[float]]) -> float:
    """Return the most-recent value in a history array, or 0 on miss.

    "Most recent" is the last element (caller contract). Non-finite
    values fall through to 0 so downstream math stays well-defined.
    """
    if not arr:
        return 0.0
    last = arr[-1]
    return float(last) if _is_finite(last) else 0.0


def _avg_wc_change(wc_history: Optional[list[float]]) -> float:
    """Average year-over-year change in working capital.

    Smooths out one-year inventory blips. Returns 0 when fewer than
    2 valid points exist — there is no change to compute.
    """
    if not wc_history or len(wc_history) < 2:
        return 0.0
    deltas: list[float] = []
    prev: Optional[float] = None
    for raw in wc_history:
        if not _is_finite(raw):
            continue
        cur = float(raw)
        if prev is not None:
            deltas.append(cur - prev)
        prev = cur
    if not deltas:
        return 0.0
    return mean(deltas)
