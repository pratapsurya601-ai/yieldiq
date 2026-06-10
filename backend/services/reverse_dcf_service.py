# backend/services/reverse_dcf_service.py
# ═══════════════════════════════════════════════════════════════
# REVERSE-DCF SERVICE — "what is the market pricing in?"
# ═══════════════════════════════════════════════════════════════
#
# Given the current market price as the *target*, solve for the
# inputs (FCF growth, margin) that would make a 10y two-stage
# DCF equal that price.
#
# Two implied dimensions:
#   1. implied_growth_pct  — solve for FCF growth, holding margin
#                            (and therefore current FCF) fixed.
#   2. implied_margin_pct  — solve for FCF margin, holding the
#                            consensus growth fixed and rebuilding
#                            FCF from current revenue × margin.
#
# The third deliverable (`iso_fv_curve`) is three (growth, margin)
# pairs along the iso-fair-value curve — useful for plotting "if
# the market is right about growth at X%, then it must believe
# margins will be Y%".
#
# This service is INDEPENDENT of the heavy analysis pipeline:
#   - It reads the lattice from `models.forecaster` read-only
#     (TERMINAL_FADE_G / FADE_K / _exponential_fade) so it stays
#     consistent with the forward DCF the rest of the app uses.
#   - It does NOT call backend.services.analysis.service (Task 2
#     worktree) — it accepts pre-resolved inputs directly. The
#     /api/v1/public/reverse-dcf/{ticker} router pulls those from
#     the existing AnalysisResponse cache (computation_inputs).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from typing import Optional

# Read-only import from Task 1's lattice. We deliberately do NOT
# import the FCFForecaster class — only the constants and the
# pure fade helper — so we never accidentally retrain or mutate
# anything in that module.
from models.forecaster import (
    TERMINAL_FADE_G,
    FADE_K,
    _exponential_fade,
)

log = logging.getLogger("yieldiq.reverse_dcf_service")


# ── Search bounds (per task spec) ──────────────────────────────
SEARCH_MIN_GROWTH = -0.05   # -5%
SEARCH_MAX_GROWTH = 0.50    # +50%
SEARCH_MIN_MARGIN = 0.005   # 0.5%
SEARCH_MAX_MARGIN = 0.60    # 60% (asset-light extreme)
SEARCH_TOL = 1e-3
MAX_ITERS = 80
DEFAULT_YEARS = 10
DEFAULT_TERMINAL_G = TERMINAL_FADE_G

# Consensus FCF-growth assumption used when the caller does not
# supply one. Mirrors the long-run anchor used by _rule_based_growth
# in the forward DCF (India nominal GDP ≈ 10%, US ≈ 3.5%) but we
# pick a single mid value for the iso curve so the public endpoint
# is deterministic. Callers can override with `consensus_growth`.
DEFAULT_CONSENSUS_GROWTH_INDIA = 0.12
DEFAULT_CONSENSUS_GROWTH_US = 0.05


def _is_finite_positive(x: Optional[float]) -> bool:
    try:
        return x is not None and math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def _dcf_per_share(
    fcf_base: float,
    growth_rate: float,
    wacc: float,
    terminal_g: float,
    years: int,
    total_debt: float,
    total_cash: float,
    shares: float,
) -> float:
    """Two-stage DCF with the same exponential fade used by the
    forward forecaster. Returns equity value per share.

    Stage 1 (years 1..N): FCF grows at the faded rate
            g(t) = g_T + (g_0 - g_T) × exp(-FADE_K × t)
    Stage 2: Gordon growth on the year-N terminal FCF at terminal_g.

    Mirrors the math in screener/reverse_dcf._dcf_iv_for_growth but
    with the fade lattice from models/forecaster instead of constant
    growth, so the implied number is directly comparable to the
    forward DCF base case.
    """
    if not (_is_finite_positive(fcf_base) and _is_finite_positive(shares)):
        return 0.0
    if wacc <= terminal_g:
        # Pathological inputs — Gordon denominator collapses. Caller
        # has already clamped wacc>=terminal_g+0.02 in practice.
        return 0.0

    # Project FCFs with faded growth
    fcf = fcf_base
    pv_fcfs = 0.0
    last_fcf = fcf
    for t in range(1, years + 1):
        g_t = _exponential_fade(t, growth_rate, terminal_g)
        # Clamp identically to forecaster (-15%..+35%) so the iso curve
        # does not silently extrapolate past the lattice.
        g_t = max(-0.15, min(0.35, float(g_t)))
        fcf = fcf * (1 + g_t)
        pv_fcfs += fcf / (1 + wacc) ** t
        last_fcf = fcf

    # Terminal value — Gordon
    tv = last_fcf * (1 + terminal_g) / (wacc - terminal_g)
    pv_tv = tv / (1 + wacc) ** years

    enterprise_value = pv_fcfs + pv_tv
    equity_value = enterprise_value - (total_debt or 0) + (total_cash or 0)
    if equity_value <= 0:
        return 0.0
    return equity_value / shares


def _binary_search(
    f,
    target: float,
    lo: float,
    hi: float,
    tol: float = SEARCH_TOL,
    max_iters: int = MAX_ITERS,
) -> tuple[float, bool]:
    """Bisect for the input x in [lo, hi] such that f(x) ≈ target.

    Assumes f is monotonically non-decreasing in x over [lo, hi].
    Returns (x, converged).
    """
    f_lo = f(lo)
    f_hi = f(hi)
    if f_lo > f_hi:
        # Function is decreasing — flip search direction by negating
        def g(x):
            return -f(x)
        target_g = -target
        x, ok = _binary_search(g, target_g, lo, hi, tol, max_iters)
        return x, ok
    if target < f_lo:
        return lo, False
    if target > f_hi:
        return hi, False
    a, b = lo, hi
    mid = 0.5 * (a + b)
    for _ in range(max_iters):
        mid = 0.5 * (a + b)
        f_mid = f(mid)
        if abs(f_mid - target) / max(abs(target), 1e-9) < tol:
            return mid, True
        if f_mid < target:
            a = mid
        else:
            b = mid
    return mid, False


def compute_reverse_dcf(
    ticker: str,
    current_price: float,
    wacc: float,
    current_fcf: float,
    current_margin: float,
    current_revenue: float,
    total_debt: float = 0.0,
    total_cash: float = 0.0,
    shares: float = 0.0,
    terminal_g: float = DEFAULT_TERMINAL_G,
    years: int = DEFAULT_YEARS,
    consensus_growth: Optional[float] = None,
    historical_revenue_cagr: Optional[float] = None,
    historical_fcf_margin: Optional[float] = None,
    normalized_fcf: Optional[float] = None,
) -> Optional[dict]:
    """Compute the reverse-DCF answer dict.

    Returns None if inputs are insufficient (caller should hide the
    UI panel). Otherwise returns a dict with:

      - ``implied_growth_pct``  : market-implied annual FCF growth
                                  (decimal, e.g. 0.18 = 18%)
      - ``implied_margin_pct``  : market-implied steady-state FCF
                                  margin under consensus growth
      - ``iso_fv_curve``        : list of 3 ``{growth, margin}`` dicts
      - ``current_market_implied_summary`` : plain-English string
      - inputs snapshot for the response model
    """
    # ── Validate ─────────────────────────────────────────────────
    if not _is_finite_positive(current_price):
        return None
    if not _is_finite_positive(shares):
        return None
    if not _is_finite_positive(current_fcf):
        # Loss-making companies — reverse DCF is not meaningful.
        return None
    if not _is_finite_positive(current_revenue):
        return None
    # Margin may legitimately be missing on cached payloads — derive
    # it from FCF / revenue when we have both.
    if not _is_finite_positive(current_margin):
        try:
            current_margin = float(current_fcf) / float(current_revenue)
        except (TypeError, ZeroDivisionError):
            return None
    if not (0.05 <= wacc <= 0.25):
        return None
    if terminal_g >= wacc:
        terminal_g = max(wacc - 0.02, 0.0)

    is_indian = ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO")
    if consensus_growth is None:
        consensus_growth = (
            DEFAULT_CONSENSUS_GROWTH_INDIA if is_indian else DEFAULT_CONSENSUS_GROWTH_US
        )

    # ── 1. Implied growth — hold margin (FCF) fixed ─────────────
    # Upstream-normalised FCF anchor (Option B per
    # docs/design/reverse-dcf-normalization.md). When the caller
    # supplies `normalized_fcf` (populated from QualityOutput.
    # normalized_fcf_cr → models/forecaster._compute_fcf_base), use
    # it as the growth-axis anchor instead of the raw trailing
    # `current_fcf`. For cyclical companies at a margin trough
    # (RELIANCE refinery cycle, BPCL, TATASTEEL, JSWSTEEL,
    # SHREECEM, etc.) `current_fcf` is depressed and the bisector
    # has to reach the market price by inflating growth — producing
    # the absurd 48.6% implied growth on RELIANCE. The normalised
    # base — already mid-cycle smoothed by the forward DCF — lets
    # the solver report what the market is really pricing in.
    # `current_fcf` is retained for the margin-axis and iso curve
    # because those paths already rebuild FCF from revenue × margin.
    fcf_anchor = (
        float(normalized_fcf)
        if _is_finite_positive(normalized_fcf)
        else float(current_fcf)
    )
    normalization_applied = (
        _is_finite_positive(normalized_fcf)
        and abs(float(normalized_fcf) - float(current_fcf)) /
            max(abs(float(current_fcf)), 1.0) > 0.01
    )
    def f_growth(g: float) -> float:
        return _dcf_per_share(
            fcf_base=fcf_anchor,
            growth_rate=g,
            wacc=wacc,
            terminal_g=terminal_g,
            years=years,
            total_debt=total_debt,
            total_cash=total_cash,
            shares=shares,
        )

    implied_growth, growth_converged = _binary_search(
        f_growth, current_price, SEARCH_MIN_GROWTH, SEARCH_MAX_GROWTH
    )
    # Hard clamp to the documented range so a non-convergent corner
    # cannot leak ±60% values into the UI.
    implied_growth = max(SEARCH_MIN_GROWTH, min(SEARCH_MAX_GROWTH, implied_growth))

    # ── Day-76 boundary-peg guard (audit 2026-05-20 P5) ──────────
    # When the bisector pegs at SEARCH_MIN_GROWTH or SEARCH_MAX_GROWTH
    # without a normalised anchor in play, the displayed number is a
    # bound, not a market-implied estimate. The audit caught this on
    # RELIANCE (50.0% growth = SEARCH_MAX_GROWTH; refining-cycle FCF
    # trough) and HDFCBANK (-5.0% growth = SEARCH_MIN_GROWTH; post-
    # HDFC-merger balance-sheet inflation). Tag the result so the
    # frontend can render an "off-scale" qualifier rather than a
    # spurious precise number — and surface this in the summary so the
    # plain-English line carries the caveat too.
    _eps = 1e-4
    growth_pegged_high = abs(implied_growth - SEARCH_MAX_GROWTH) < _eps
    growth_pegged_low = abs(implied_growth - SEARCH_MIN_GROWTH) < _eps
    growth_off_scale = (
        (growth_pegged_high or growth_pegged_low) and not growth_converged
    )

    # ── 2. Implied margin — hold consensus growth fixed ─────────
    # Rebuild FCF from revenue × candidate margin so the search has
    # a meaningful axis. Output is the steady-state FCF margin the
    # market is implicitly assigning at consensus growth.
    def f_margin(m: float) -> float:
        return _dcf_per_share(
            fcf_base=current_revenue * m,
            growth_rate=consensus_growth,
            wacc=wacc,
            terminal_g=terminal_g,
            years=years,
            total_debt=total_debt,
            total_cash=total_cash,
            shares=shares,
        )

    implied_margin, margin_converged = _binary_search(
        f_margin, current_price, SEARCH_MIN_MARGIN, SEARCH_MAX_MARGIN
    )
    implied_margin = max(SEARCH_MIN_MARGIN, min(SEARCH_MAX_MARGIN, implied_margin))

    # ── 3. Iso-FV curve — 3 (growth, margin) points ─────────────
    # Pick three growth anchors spanning [consensus, implied,
    # implied×1.25] then for each solve the inner f_margin(m | g) to
    # find the matching margin. This gives users a feel for how
    # tightly the market's price constrains the trade-off.
    iso_growths: list[float] = []
    g_lo = min(consensus_growth, implied_growth)
    g_hi = max(consensus_growth, implied_growth)
    if g_hi - g_lo < 0.01:
        # Degenerate — spread artificially so the three points differ
        g_lo = max(SEARCH_MIN_GROWTH, implied_growth - 0.04)
        g_hi = min(SEARCH_MAX_GROWTH, implied_growth + 0.04)
    iso_growths = [g_lo, 0.5 * (g_lo + g_hi), g_hi]
    iso_curve: list[dict] = []
    for g in iso_growths:
        def f_m(m: float, _g: float = g) -> float:
            return _dcf_per_share(
                fcf_base=current_revenue * m,
                growth_rate=_g,
                wacc=wacc,
                terminal_g=terminal_g,
                years=years,
                total_debt=total_debt,
                total_cash=total_cash,
                shares=shares,
            )
        m, _ok = _binary_search(
            f_m, current_price, SEARCH_MIN_MARGIN, SEARCH_MAX_MARGIN
        )
        m = max(SEARCH_MIN_MARGIN, min(SEARCH_MAX_MARGIN, m))
        iso_curve.append({
            "growth": float(g),
            "margin": float(m),
        })

    # ── 4. Plain-English summary ────────────────────────────────
    cur_m_pct = current_margin * 100
    impl_g_pct = implied_growth * 100
    impl_m_pct = implied_margin * 100
    cons_g_pct = consensus_growth * 100
    if growth_off_scale:
        # Day-76: peg-without-convergence means the solver could not
        # reach the market price inside the documented search window
        # using the supplied FCF anchor. Most often a cyclical-margin
        # trough (current FCF depressed) or a merger-distorted balance
        # sheet (HDFCBANK post-HDFC merger). The number is reported as
        # a bound, never as a point estimate.
        _bound_word = ">=" if growth_pegged_high else "<="
        summary = (
            f"Market-implied FCF growth is {_bound_word} {impl_g_pct:.1f}% "
            f"at current {cur_m_pct:.1f}% margins -- solver pegged at "
            f"the search bound, so the trailing-margin anchor is likely "
            f"distorted by a cyclical trough or balance-sheet event. "
            f"Margin-axis read: {impl_m_pct:.1f}% at consensus "
            f"{cons_g_pct:.1f}% growth."
        )
    else:
        summary = (
            f"Market is pricing in {impl_g_pct:.1f}% FCF growth "
            f"at current {cur_m_pct:.1f}% margins, "
            f"or {impl_m_pct:.1f}% margins at consensus {cons_g_pct:.1f}% growth."
        )

    # ── 5. Sanity-check vs trailing actuals (optional) ──────────
    sanity_lines: list[str] = []
    if historical_revenue_cagr is not None and math.isfinite(historical_revenue_cagr):
        delta = implied_growth - historical_revenue_cagr
        sanity_lines.append(
            f"Implied growth {impl_g_pct:.1f}% vs trailing 5y revenue CAGR "
            f"{historical_revenue_cagr * 100:.1f}% "
            f"({'+' if delta >= 0 else ''}{delta * 100:.1f}pp)."
        )
    if historical_fcf_margin is not None and math.isfinite(historical_fcf_margin):
        delta = implied_margin - historical_fcf_margin
        sanity_lines.append(
            f"Implied margin {impl_m_pct:.1f}% vs trailing 5y FCF margin "
            f"{historical_fcf_margin * 100:.1f}% "
            f"({'+' if delta >= 0 else ''}{delta * 100:.1f}pp)."
        )

    return {
        "ticker": ticker,
        "implied_growth_pct": float(implied_growth),
        "implied_margin_pct": float(implied_margin),
        "iso_fv_curve": iso_curve,
        "current_market_implied_summary": summary,
        "sanity_check_lines": sanity_lines,
        "converged": bool(growth_converged and margin_converged),
        "inputs": {
            "current_price": float(current_price),
            "wacc": float(wacc),
            "terminal_g": float(terminal_g),
            "current_fcf": float(current_fcf),
            "current_margin": float(current_margin),
            "current_revenue": float(current_revenue),
            "consensus_growth": float(consensus_growth),
            "total_debt": float(total_debt or 0.0),
            "total_cash": float(total_cash or 0.0),
            "shares": float(shares),
            "years": int(years),
            # Reverse-DCF upstream-normalisation transparency. Both
            # additive; pre-design-doc payloads will not carry them.
            "normalized_fcf": (
                float(normalized_fcf) if _is_finite_positive(normalized_fcf) else None
            ),
            "fcf_anchor_used": float(fcf_anchor),
            "normalization_applied": bool(normalization_applied),
        },
        # Day-76 (audit 2026-05-20 P5): boundary-peg telemetry. When
        # `growth_off_scale` is True the implied_growth_pct value is a
        # bound, not a point estimate; the frontend should render it
        # with a >= / <= qualifier and warn that the trailing-margin
        # anchor is likely cycle-distorted.
        "growth_off_scale": bool(growth_off_scale),
        "growth_pegged_high": bool(growth_pegged_high),
        "growth_pegged_low": bool(growth_pegged_low),
    }


# ═══════════════════════════════════════════════════════════════
# IMPLIED ASSUMPTIONS — "what does the market expect?" framing
# ═══════════════════════════════════════════════════════════════
#
# AlphaSpread does this well: rather than show a single implied
# growth number, frame it as a comparison vs. analyst consensus AND
# vs. the trailing realized history, then label the gap so a reader
# can answer "is the market betting on something the company has
# actually delivered, or on something extrapolated past it?".
#
# This block layers richer framing on top of `compute_reverse_dcf`.
# It does NOT replace it — the upstream solver remains the source
# of truth for the raw implied number. Everything below is
# DERIVED from already-computed inputs (implied growth, consensus,
# trailing CAGR, optional margin expansion / wacc) and is therefore:
#
#   * cheap to compute (no extra solver passes)
#   * additive at the API surface (Optional dict on AnalysisResponse)
#   * legacy-safe (None on pre-PR cached payloads → frontend hides
#     the card cleanly).
# ═══════════════════════════════════════════════════════════════

# Plausibility scoring bands. Symmetric around historical growth.
# Tuned to mirror AlphaSpread's qualitative bins: "in line" (~within
# ~2pp), "stretched" (~2-5pp), "aggressive" (~5-10pp), "extreme"
# (>10pp). Exposed as constants so tests + the frontend tooltip can
# refer back to the same numbers.
PLAUSIBILITY_BAND_IN_LINE_PP = 2.0
PLAUSIBILITY_BAND_STRETCHED_PP = 5.0
PLAUSIBILITY_BAND_AGGRESSIVE_PP = 10.0

# Market-expectation label thresholds (absolute implied growth %).
# Used when no historical anchor is present so the label degrades
# gracefully from "we can compare to history" to "we can only
# describe the absolute level".
EXPECTATION_MODEST_PCT = 5.0
EXPECTATION_MODERATE_PCT = 12.0
EXPECTATION_AGGRESSIVE_PCT = 20.0


@dataclass
class ImpliedAssumptionsResult:
    """Rich framing wrapper for "what does the market expect?".

    Every numeric field is a percent unless suffixed with _bps or
    _pp. The headline string is the one-line callout the frontend
    renders inside the card; `market_expectation_label` is the
    chip-tone driver. None on any field is a structural signal that
    the corresponding sub-question was unanswerable (missing
    consensus, missing history, etc.) — the frontend must handle
    None per-field rather than hiding the whole card.
    """
    implied_revenue_cagr_pct: float
    implied_terminal_growth_pct: float
    implied_margin_expansion_bps: Optional[float]
    implied_wacc_pct: Optional[float]

    consensus_revenue_cagr_pct: Optional[float]
    growth_gap_pp: Optional[float]

    market_expectation_label: str  # modest | moderate | aggressive | extreme
    plausibility_score: int        # 0-100

    headline: str


def classify_market_expectation(
    implied_growth_pct: float,
    historical_growth_pct: Optional[float],
) -> str:
    """Bin the implied-growth signal into one of four ordinal labels.

    Comparison logic:
      * If a historical anchor is provided, use the gap (implied -
        historical) — captures "the market is asking for materially
        more than the company has actually delivered".
      * Otherwise fall back to absolute implied growth so the label
        still degrades gracefully when history is missing.

    Returns one of: "modest", "moderate", "aggressive", "extreme".
    """
    if historical_growth_pct is not None and math.isfinite(historical_growth_pct):
        gap = float(implied_growth_pct) - float(historical_growth_pct)
        abs_gap = abs(gap)
        if abs_gap <= PLAUSIBILITY_BAND_IN_LINE_PP:
            return "modest"
        if abs_gap <= PLAUSIBILITY_BAND_STRETCHED_PP:
            return "moderate"
        if abs_gap <= PLAUSIBILITY_BAND_AGGRESSIVE_PP:
            return "aggressive"
        return "extreme"

    abs_g = abs(float(implied_growth_pct))
    if abs_g <= EXPECTATION_MODEST_PCT:
        return "modest"
    if abs_g <= EXPECTATION_MODERATE_PCT:
        return "moderate"
    if abs_g <= EXPECTATION_AGGRESSIVE_PCT:
        return "aggressive"
    return "extreme"


# Sector-norm soft-correction: certain sectors structurally support
# above-trailing growth windows (early-stage SaaS, defensive franchise
# brands re-rating after a margin reset, etc.). The default uplift is
# a small +5 / -5 score adjustment depending on whether the implied
# growth direction is consistent with the sector's typical trajectory.
# Sectors not in the map fall through with no adjustment. Keep this
# map intentionally tight — broad sector lookups belong in
# backend/services/analysis/constants.py, not here.
_SECTOR_PLAUSIBILITY_TILT_PP: dict[str, float] = {
    # Sector slug → directional tilt applied to the gap BEFORE binning.
    # Positive value softens the penalty for above-history growth
    # (i.e. the sector is structurally growthy), negative tilts the
    # other way (cyclical-trough / commodity sectors penalised harder
    # when implied growth runs hot).
    "it_services": -0.5,         # mature sector — extrapolating past history is suspect
    "fmcg": -0.5,                # ditto
    "pharma": 0.0,
    "financials": 0.0,
    "banks": 0.0,
    "nbfc": 0.0,
    "auto_oem": -1.0,            # cyclical
    "capital_goods": -1.0,       # cyclical
    "cement": -1.0,              # cyclical
    "steel": -1.5,               # deep cyclical
    "oil_gas": -1.5,             # deep cyclical
    "utilities": 0.0,
    "reit": 0.0,
}


def compute_plausibility_score(
    implied_growth_pct: float,
    historical_growth_pct: Optional[float],
    sector: Optional[str] = None,
) -> int:
    """Score the implied growth's plausibility on a 0-100 scale.

    The task spec gives a five-band table keyed on the gap between
    implied and historical growth:

      | gap (pp) above history | score |
      |------------------------|-------|
      | within ±2              | 90    |
      | 2-5                    | 70    |
      | 5-10                   | 50    |
      | 10-20                  | 30    |
      | >20                    | 10    |

    The inverse symmetry handles "the market is implying LESS growth
    than the company has delivered" — that's also low plausibility
    but for a different reason (signals expected reversion / a thesis
    break), so we keep the magnitude-based mapping symmetric.

    `sector` (optional) applies a small directional tilt before the
    binning so cyclical sectors are penalised more heavily for hot
    implied growth at the trough. Sectors not in the tilt map have
    no adjustment.

    Missing or non-finite history → defaults to 50 (uninformative
    midpoint). Callers can decide to suppress the score in that case.
    """
    if historical_growth_pct is None or not math.isfinite(historical_growth_pct):
        return 50

    gap = float(implied_growth_pct) - float(historical_growth_pct)

    if sector:
        tilt = _SECTOR_PLAUSIBILITY_TILT_PP.get(
            str(sector).strip().lower().replace("-", "_"),
            0.0,
        )
        # Tilt is applied as: a NEGATIVE tilt for cyclicals INCREASES
        # the effective gap when implied > historical (i.e. penalises
        # extrapolating past history harder), but does not flip sign
        # when implied < historical (so cyclicals don't get a free
        # pass for low implied growth — that's a separate signal).
        if gap > 0:
            gap = gap - tilt  # tilt<0 → gap grows → harsher score

    abs_gap = abs(gap)
    if abs_gap <= 2.0:
        return 90
    if abs_gap <= 5.0:
        return 70
    if abs_gap <= 10.0:
        return 50
    if abs_gap <= 20.0:
        return 30
    return 10


def _format_headline(
    implied_growth_pct: float,
    consensus_pct: Optional[float],
    historical_pct: Optional[float],
    label: str,
) -> str:
    """One-line headline string for the frontend card.

    Mirrors AlphaSpread's "Current price implies X% CAGR vs
    consensus Y% — <label>" formulation. When consensus is missing
    we fall back to the historical anchor; when both are missing we
    state only the implied growth.
    """
    impl_str = f"{implied_growth_pct:.1f}%"
    if consensus_pct is not None and math.isfinite(consensus_pct):
        return (
            f"Current price implies {impl_str} CAGR vs consensus "
            f"{consensus_pct:.1f}% -- {label}"
        )
    if historical_pct is not None and math.isfinite(historical_pct):
        return (
            f"Current price implies {impl_str} CAGR vs trailing "
            f"{historical_pct:.1f}% -- {label}"
        )
    return f"Current price implies {impl_str} CAGR -- {label}"


def compute_implied_assumptions(
    current_price: float,
    base_fcf: float,
    shares: float,
    historical_revenue_cagr_3y: float,
    consensus_revenue_cagr: Optional[float] = None,
    wacc: float = 0.115,
    terminal_growth: float = 0.04,
    current_margin: Optional[float] = None,
    historical_margin: Optional[float] = None,
    sector: Optional[str] = None,
    total_debt: float = 0.0,
    total_cash: float = 0.0,
    current_revenue: Optional[float] = None,
    ticker: str = "",
) -> Optional[ImpliedAssumptionsResult]:
    """Compute the rich-framing implied-assumptions wrapper.

    Reuses the same lattice as `compute_reverse_dcf` so the implied
    growth number reported here is byte-identical to the existing
    `implied_growth_pct` field on the reverse-DCF response. The
    rest of the fields (consensus gap, plausibility, headline) are
    framing-only — they never feed back into FV or the verdict gate.

    Returns None when the inputs are insufficient (caller should
    hide the card surface in that case).
    """
    # ── Validate inputs ──────────────────────────────────────────
    if not _is_finite_positive(current_price):
        return None
    if not _is_finite_positive(shares):
        return None
    if not _is_finite_positive(base_fcf):
        return None
    if not (0.05 <= wacc <= 0.25):
        return None
    if terminal_growth >= wacc:
        terminal_growth = max(wacc - 0.02, 0.0)

    # ── Solve for implied growth ────────────────────────────────
    # Pure delegation to the same _binary_search + _dcf_per_share
    # used by compute_reverse_dcf so the answer is consistent with
    # the existing surface. The optional revenue path is exposed via
    # `current_revenue` purely for the margin-expansion framing; the
    # growth solver always uses fcf-as-anchor for parity.
    def f_growth(g: float) -> float:
        return _dcf_per_share(
            fcf_base=float(base_fcf),
            growth_rate=g,
            wacc=wacc,
            terminal_g=terminal_growth,
            years=DEFAULT_YEARS,
            total_debt=float(total_debt or 0.0),
            total_cash=float(total_cash or 0.0),
            shares=float(shares),
        )

    implied_growth, _converged = _binary_search(
        f_growth, float(current_price), SEARCH_MIN_GROWTH, SEARCH_MAX_GROWTH
    )
    implied_growth = max(SEARCH_MIN_GROWTH, min(SEARCH_MAX_GROWTH, implied_growth))
    implied_growth_pct = implied_growth * 100.0

    # ── Consensus comparison ────────────────────────────────────
    consensus_pct: Optional[float] = None
    growth_gap_pp: Optional[float] = None
    if consensus_revenue_cagr is not None and math.isfinite(consensus_revenue_cagr):
        consensus_pct = float(consensus_revenue_cagr) * 100.0
        growth_gap_pp = implied_growth_pct - consensus_pct

    # ── Historical-anchor framing ───────────────────────────────
    historical_pct: Optional[float] = None
    if (
        historical_revenue_cagr_3y is not None
        and math.isfinite(historical_revenue_cagr_3y)
    ):
        historical_pct = float(historical_revenue_cagr_3y) * 100.0

    # ── Margin-expansion framing (bps vs current) ───────────────
    # Only meaningful when we have BOTH a current and historical
    # margin anchor — otherwise the bps gap is unidentified. We do
    # not infer a "consensus margin" here because none of the
    # upstream data paths carry one consistently; the corresponding
    # implied-margin axis lives in compute_reverse_dcf already.
    implied_margin_expansion_bps: Optional[float] = None
    if (
        current_margin is not None
        and historical_margin is not None
        and math.isfinite(current_margin)
        and math.isfinite(historical_margin)
    ):
        implied_margin_expansion_bps = (
            float(current_margin) - float(historical_margin)
        ) * 10_000.0

    # ── Implied WACC echo ───────────────────────────────────────
    # The solver doesn't re-derive WACC — we surface the WACC used
    # for the solve so the frontend can show "at WACC = 11.5%". This
    # keeps the rich card self-describing without a second solve.
    implied_wacc_pct: Optional[float] = float(wacc) * 100.0

    # ── Label + score ───────────────────────────────────────────
    label = classify_market_expectation(implied_growth_pct, historical_pct)
    score = compute_plausibility_score(implied_growth_pct, historical_pct, sector)

    headline = _format_headline(implied_growth_pct, consensus_pct, historical_pct, label)

    return ImpliedAssumptionsResult(
        implied_revenue_cagr_pct=float(implied_growth_pct),
        implied_terminal_growth_pct=float(terminal_growth) * 100.0,
        implied_margin_expansion_bps=implied_margin_expansion_bps,
        implied_wacc_pct=implied_wacc_pct,
        consensus_revenue_cagr_pct=consensus_pct,
        growth_gap_pp=growth_gap_pp,
        market_expectation_label=label,
        plausibility_score=int(score),
        headline=headline,
    )


def implied_assumptions_to_dict(
    result: Optional[ImpliedAssumptionsResult],
) -> Optional[dict]:
    """Shallow JSON-safe projection for the AnalysisResponse field.

    Mirrors the convention used elsewhere in the analysis payload
    (every nested service result lands as a plain dict so Pydantic
    can serialise without bespoke encoders). None passes through so
    the caller can chain ``implied_assumptions_to_dict(maybe_None)``.
    """
    if result is None:
        return None
    return asdict(result)
