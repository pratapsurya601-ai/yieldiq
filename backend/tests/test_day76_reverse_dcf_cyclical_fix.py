"""
Day-76 regression suite — reverse-DCF cyclical / merger normalization
(audit 2026-05-20 P5).

Covers three layered fixes shipped on branch
`day76-reverse-dcf-cyclical-fix`:

1. Bank-skip gate at /api/v1/public/reverse-dcf/{ticker} — banks /
   NBFCs / insurers return a structured {applicable: False, ...}
   payload instead of attempting a meaningless FCF-DCF inversion.
   HDFCBANK was the audit's reference failure ("Market is pricing
   in -5% growth" = SEARCH_MIN_GROWTH peg from post-merger balance-
   sheet distortion).

2. Router-level cyclical fallback — when the upstream
   QualityOutput.normalized_fcf_cr stash is null on legacy / pre-
   v131 cached payloads, the router synthesises
       normalized_fcf := current_revenue * fcf_margin_5y
   so the reverse-DCF solver still has a mid-cycle anchor.
   RELIANCE was the audit's reference cyclical ("Market is pricing
   in 50% growth" = SEARCH_MAX_GROWTH peg).

3. Service-level boundary-peg telemetry — when the bisector pegs
   at SEARCH_MIN_GROWTH / SEARCH_MAX_GROWTH without convergence,
   the response carries growth_off_scale=True and the plain-English
   summary becomes a >= / <= bound, not a point estimate.

These are SOURCE-TEXT guards plus a few BEHAVIOUR tests against
compute_reverse_dcf — kept self-contained to avoid pulling in the
full analyse pipeline.
"""

from __future__ import annotations

from pathlib import Path

from backend.services.reverse_dcf_service import (
    compute_reverse_dcf,
    SEARCH_MAX_GROWTH,
    SEARCH_MIN_GROWTH,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PY = REPO_ROOT / "backend" / "routers" / "public.py"
SERVICE_PY = REPO_ROOT / "backend" / "services" / "reverse_dcf_service.py"
CACHE_PY = REPO_ROOT / "backend" / "services" / "cache_service.py"


# ─── Source-text guards ──────────────────────────────────────────


def test_bank_skip_gate_present_in_router():
    """The /reverse-dcf/{ticker} handler imports is_bank_like and
    returns a structured `applicable: False` payload with the
    MISS-NOT-APPLICABLE header. Without this gate HDFCBANK and
    every other bank-like ticker would fall through to the solver
    and surface the -5% peg the audit caught."""
    src = PUBLIC_PY.read_text(encoding="utf-8")
    assert "from backend.services.analysis.constants import is_bank_like" in src
    assert "if is_bank_like(ticker):" in src
    assert '"applicable": False' in src
    assert '"category": "bank_like"' in src
    assert "MISS-NOT-APPLICABLE" in src


def test_router_synthesises_normalized_fcf_for_legacy_payloads():
    """When QualityOutput.normalized_fcf_cr is null on a legacy
    cached payload, the router must synthesise the cyclical anchor
    from current_revenue × fcf_margin_5y so RELIANCE-class names do
    not peg the bisector at SEARCH_MAX_GROWTH."""
    src = PUBLIC_PY.read_text(encoding="utf-8")
    assert "Day-76 cyclical fallback" in src
    assert "normalized_fcf := current_revenue * historical_fcf_margin" in src or \
           "normalized_fcf := current_revenue × fcf_margin_5y" in src.replace("×", "x")
    assert "synthesized normalized_fcf" in src


def test_service_emits_growth_off_scale_flag():
    """compute_reverse_dcf must surface growth_off_scale /
    growth_pegged_high / growth_pegged_low so the frontend can
    render the implied-growth number as a bound rather than a
    spurious precise estimate."""
    src = SERVICE_PY.read_text(encoding="utf-8")
    assert "growth_off_scale" in src
    assert "growth_pegged_high" in src
    assert "growth_pegged_low" in src
    assert "Day-76 boundary-peg guard" in src


def test_cache_version_bumped_to_133():
    """CACHE_VERSION must bump from 132 -> 133 because the
    reverse_dcf_v1 payload shape gains three new fields and banks
    return a materially different payload."""
    src = CACHE_PY.read_text(encoding="utf-8")
    assert "CACHE_VERSION = 133" in src
    assert "day76-reverse-dcf-cyclical-fix" in src


# ─── Behaviour: boundary-peg telemetry ──────────────────────────


def _solver_inputs(**overrides):
    """Baseline inputs that solve at an interior growth — overrides
    let individual tests force boundary pegs."""
    base = dict(
        ticker="TEST.NS",
        current_price=2500.0,
        wacc=0.11,
        current_fcf=50_000e7,       # ₹50,000 Cr in raw rupees
        current_margin=0.10,
        current_revenue=500_000e7,  # ₹5,00,000 Cr in raw rupees
        total_debt=100_000e7,
        total_cash=20_000e7,
        shares=6.77e9,
        terminal_g=0.04,
    )
    base.update(overrides)
    return base


def test_growth_off_scale_false_for_interior_solve():
    """A well-behaved input should converge interior to the search
    band and NOT trip the off-scale flag."""
    out = compute_reverse_dcf(**_solver_inputs())
    assert out is not None
    assert out.get("growth_off_scale") is False
    assert out.get("growth_pegged_high") is False
    assert out.get("growth_pegged_low") is False
    # Summary should be the standard "Market is pricing in ..."
    # line, not the bound-qualified caveat.
    assert "Market is pricing in" in out["current_market_implied_summary"]


def test_growth_off_scale_high_when_price_demands_more_than_max():
    """Force an impossibly-rich price — the bisector should peg at
    SEARCH_MAX_GROWTH and growth_pegged_high must fire."""
    # 50x current price with a tiny FCF anchor → solver cannot reach
    # the target even at +50% growth.
    out = compute_reverse_dcf(**_solver_inputs(
        current_price=200_000.0,
        current_fcf=1_000e7,  # tiny anchor relative to market cap
    ))
    assert out is not None
    impl = out["implied_growth_pct"]
    assert abs(impl - SEARCH_MAX_GROWTH) < 1e-3
    assert out["growth_pegged_high"] is True
    assert out["growth_off_scale"] is True
    # Bound-qualified summary, not a precise number.
    summary = out["current_market_implied_summary"]
    assert ">=" in summary
    assert "solver pegged at the search bound" in summary


def test_growth_off_scale_low_when_price_is_below_floor():
    """An absurdly cheap price with a huge FCF anchor should peg
    the solver at SEARCH_MIN_GROWTH (the HDFCBANK shape)."""
    out = compute_reverse_dcf(**_solver_inputs(
        current_price=10.0,
        current_fcf=500_000e7,  # huge anchor relative to tiny price
    ))
    assert out is not None
    impl = out["implied_growth_pct"]
    assert abs(impl - SEARCH_MIN_GROWTH) < 1e-3
    assert out["growth_pegged_low"] is True
    assert out["growth_off_scale"] is True
    summary = out["current_market_implied_summary"]
    assert "<=" in summary


# ─── Behaviour: normalized_fcf anchor takes precedence ──────────


def test_normalized_fcf_anchor_shifts_implied_growth():
    """Same inputs, but supplying a mid-cycle normalized_fcf that
    is 2x the trailing current_fcf must lower the implied growth
    (less work needed to reach the same price)."""
    inputs = _solver_inputs(current_price=3000.0, current_fcf=30_000e7)
    out_no_norm = compute_reverse_dcf(**inputs)
    out_with_norm = compute_reverse_dcf(
        **inputs, normalized_fcf=60_000e7
    )
    assert out_no_norm is not None and out_with_norm is not None
    assert out_with_norm["implied_growth_pct"] < out_no_norm["implied_growth_pct"]
    assert out_with_norm["inputs"]["normalization_applied"] is True
    assert out_with_norm["inputs"]["fcf_anchor_used"] == 60_000e7


def test_normalized_fcf_ignored_when_non_finite():
    """Non-finite normalized_fcf must degrade silently to
    current_fcf — the existing v2 contract from the 2026-05-18
    Option-B patch."""
    inputs = _solver_inputs()
    out = compute_reverse_dcf(**inputs, normalized_fcf=float("nan"))
    assert out is not None
    assert out["inputs"]["fcf_anchor_used"] == inputs["current_fcf"]
    assert out["inputs"]["normalization_applied"] is False
