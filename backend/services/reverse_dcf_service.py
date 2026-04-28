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
    def f_growth(g: float) -> float:
        return _dcf_per_share(
            fcf_base=current_fcf,
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
        },
    }
