# backend/tests/test_telecom_terminal_g.py
# ─────────────────────────────────────────────────────────────────
# Tests for the Day-141 telecom Tier-1 terminal-g lift
# (backend/services/analysis/service.py, the terminal-g chain).
#
# Background
# ----------
# BHARTIARTL surfaced FV ₹801 "Avoid" vs price ₹1,845 — a MODEL
# ARTIFACT, not a genuine call. Telecom routes through the generic
# FCF-DCF and was the conspicuous gap in the engine's sector
# remediation: pharma / hospital / auto / IT / FMCG all received a
# terminal-g lift in the terminal-g chain, but telecom got the bare
# default `terminal_g = 0.025`. The depressed terminal value,
# compounded by the levered FCF-DCF equity bridge (net-debt
# subtraction of Airtel's ~₹140k cr debt), crushes the FV. The
# engine's own bull leg already returns ₹2,852, proving it can value
# Airtel sanely.
#
# The fix ADDS a curated telecom Tier-1 terminal-g lift block
# (`_TELECOM_TIER1_TICKERS_INLINE = {"BHARTIARTL"}`) that lifts
# `terminal_g` toward 0.045, mirroring the Day-107a IT-services
# block, guarded by the existing `terminal_g < wacc - 0.02` clamp.
#
# Isolation note
# --------------
# The lift block itself lives deep inside
# `AnalysisService._get_full_analysis_inner` and CANNOT be exercised
# end-to-end without prod data (it needs a fully-enriched ticker
# payload + the upstream forecaster + DB). What CAN be exercised in
# isolation is:
#   (a) the DCF math the lifted `terminal_g` feeds — the real
#       `screener.dcf_engine.DCFEngine` (terminal_value + equity
#       bridge + per-share IV) — driven with a telecom-like profile
#       (high debt, BHARTIARTL's revenue series, WACC ~9.8%). We
#       assert the lift RAISES both the terminal value and the
#       resulting per-share FV vs the un-lifted baseline. This is the
#       deterministic core of the fix.
#   (b) the gate/guard LOGIC of the lift block, replicated as a pure
#       helper, proving the curated-set membership + the
#       `terminal_g < 0.045` lift gate + the `wacc - 0.02` safety
#       clamp all behave as the service.py block does — including the
#       negative cases (non-telecom untouched, near-WACC clamp holds).
#
# Engine clamp caveat (documented, asserted): the DCFEngine
# constructor caps `g` at `MAX_TERMINAL_GROWTH = 0.04`. So a lift to
# 0.045 reaches the engine as an EFFECTIVE 0.040 — exactly as every
# other 0.045-target cohort (IT-services / pharma-CDMO / auto-4W /
# FMCG-tier2) already does. The lift 0.025 → 0.040 is still a large
# TV increase that materially raises FV; the test asserts on that.
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations

import pytest

from screener.dcf_engine import (
    DCFEngine,
    upside_pct,
    assign_signal,
    MAX_TERMINAL_GROWTH,
)


CR = 1e7  # 1 crore in rupees — engine works in absolute ₹.

# Default + lifted terminal-g (mirrors service.py: default 0.025,
# telecom Tier-1 lift target 0.045).
TG_DEFAULT = 0.025
TG_TELECOM_LIFT = 0.045

# BHARTIARTL-like equity-bridge inputs (order-of-magnitude realistic).
BHARTI_PRICE = 1845.0
BHARTI_WACC = 0.098            # ~9.8%, per the diagnosis
BHARTI_SHARES = 600 * CR       # ~6.0bn shares
BHARTI_TOTAL_DEBT = 140000 * CR  # ~₹1.4 lakh cr net debt (levered telecom)
BHARTI_TOTAL_CASH = 5000 * CR


def _bharti_projection() -> list[float]:
    """A telecom-like 10y FCF projection.

    Anchored loosely on BHARTIARTL's clean revenue series FY21-24
    (₹ cr): 100,615 → 116,546 → 139,144 → 149,982 (~14% CAGR). Airtel
    converts only a modest slice of revenue to FCF (heavy 5G capex),
    so we model an FCF base of ~₹19k cr growing ~10%/yr as capex
    intensity eases — the profile that makes the generic DCF's
    terminal value the dominant, terminal-g-sensitive component.
    """
    base_fcf = 19000 * CR
    return [base_fcf * (1.10 ** (i + 1)) for i in range(10)]


def _run_dcf(terminal_g: float) -> dict:
    """Drive the real DCFEngine with the BHARTIARTL-like profile and
    a given terminal_g, returning the full result dict."""
    proj = _bharti_projection()
    terminal_norm = sum(proj[-3:]) / 3
    engine = DCFEngine(
        discount_rate=BHARTI_WACC,
        terminal_growth=terminal_g,
        ticker="BHARTIARTL",
    )
    return engine.intrinsic_value_per_share(
        projected_fcfs=proj,
        terminal_fcf_norm=terminal_norm,
        total_debt=BHARTI_TOTAL_DEBT,
        total_cash=BHARTI_TOTAL_CASH,
        shares_outstanding=BHARTI_SHARES,
        current_price=BHARTI_PRICE,
        ticker="BHARTIARTL",
    )


# ── 1. Core mechanism: the lift RAISES terminal value and FV ──────
def test_telecom_lift_raises_fair_value():
    """The telecom terminal-g lift (0.025 → 0.045) must raise the
    DCF terminal value AND the resulting per-share fair value vs the
    un-lifted baseline. This is the deterministic core of the fix —
    the depressed terminal value is exactly what crushed BHARTIARTL's
    FV through the levered equity bridge."""
    base = _run_dcf(TG_DEFAULT)
    lifted = _run_dcf(TG_TELECOM_LIFT)

    fv_base = base["intrinsic_value_per_share"]
    fv_lifted = lifted["intrinsic_value_per_share"]

    # Sanity: both runs are reliable and not suspicious/capped — so
    # the comparison reflects the terminal-g lever, not a clamp.
    assert base["dcf_reliable"] is True
    assert lifted["dcf_reliable"] is True
    assert base["suspicious"] is False
    assert lifted["suspicious"] is False

    # Terminal value strictly increases with the higher g.
    assert lifted["terminal_value"] > base["terminal_value"]

    # Per-share fair value strictly increases — and by a material
    # margin (the TV dominates EV for a long-duration telecom, so the
    # lift moves the headline FV meaningfully, not marginally).
    assert fv_lifted > fv_base
    assert fv_lifted >= fv_base * 1.10  # ≥10% FV uplift


def test_telecom_lift_narrows_gap_to_price():
    """The lift must move the verdict band UPWARD (closer to fair
    value) — i.e. the (negative) upside-% improves toward zero. We do
    NOT assert it fully clears the 'Overvalued' band here: that
    depends on BHARTIARTL's exact prod FCF inputs (the engine's bull
    leg already reaches ₹2,852 on richer cash flows than this
    deliberately conservative synthetic profile), which are not
    available to a local unit test. The directional improvement is
    the falsifiable, prod-independent claim."""
    base = _run_dcf(TG_DEFAULT)
    lifted = _run_dcf(TG_TELECOM_LIFT)

    mos_base = upside_pct(base["intrinsic_value_per_share"], BHARTI_PRICE)
    mos_lifted = upside_pct(lifted["intrinsic_value_per_share"], BHARTI_PRICE)

    # Upside-% strictly improves (less negative) after the lift.
    assert mos_lifted > mos_base

    # Both verdicts are well-formed strings from the real signal fn
    # (smoke check that the lift doesn't break verdict assignment).
    for res, mos in ((base, mos_base), (lifted, mos_lifted)):
        sig = assign_signal(
            mos,
            suspicious=res["suspicious"],
            reliable=res["dcf_reliable"],
            reliability_score=res.get("reliability_score", 100),
        )
        assert isinstance(sig, str) and len(sig) > 0


def test_engine_clamps_lift_to_max_terminal_growth():
    """Document + pin the engine-level clamp: DCFEngine caps g at
    MAX_TERMINAL_GROWTH (0.04). The telecom lift target is 0.045, so
    the EFFECTIVE terminal g reaching the Gordon TV is 0.040 — the
    same effective ceiling every other 0.045-target cohort hits. If
    MAX_TERMINAL_GROWTH ever changes, this test flags the assumption
    behind the lift magnitude."""
    assert MAX_TERMINAL_GROWTH == pytest.approx(0.04)
    engine = DCFEngine(
        discount_rate=BHARTI_WACC,
        terminal_growth=TG_TELECOM_LIFT,
        ticker="BHARTIARTL",
    )
    # g clamped down to MAX_TERMINAL_GROWTH, still safely below WACC.
    assert engine.g == pytest.approx(MAX_TERMINAL_GROWTH)
    assert engine.g < BHARTI_WACC - 0.02


# ── 2. Gate/guard logic of the service.py lift block (replicated) ──
# Pure replication of the decision the service.py telecom block makes,
# so the curated-set membership + lift gate + safety clamp are covered
# without needing the prod-only enclosing pipeline.
_TELECOM_TIER1_TICKERS = {"BHARTIARTL"}


def _apply_telecom_lift(bare_ticker: str, terminal_g: float, wacc: float) -> float:
    """Mirror of the service.py telecom Tier-1 block's decision:
    lift terminal_g to 0.045 for curated telecom tickers, guarded by
    the `_tg_proposed < wacc - 0.02` safety clamp and the
    `terminal_g < 0.045` only-lift gate."""
    if bare_ticker in _TELECOM_TIER1_TICKERS and terminal_g < 0.045:
        proposed = 0.045
        if proposed < wacc - 0.02:
            return proposed
    return terminal_g


def test_gate_lifts_curated_telecom_ticker():
    # BHARTIARTL with a comfortable WACC (0.098) gets lifted 0.025→0.045.
    assert _apply_telecom_lift("BHARTIARTL", TG_DEFAULT, 0.098) == pytest.approx(0.045)


def test_gate_does_not_touch_non_telecom():
    # A non-curated ticker is never lifted, whatever its terminal_g.
    assert _apply_telecom_lift("TCS", TG_DEFAULT, 0.098) == pytest.approx(TG_DEFAULT)
    assert _apply_telecom_lift("RELIANCE", TG_DEFAULT, 0.098) == pytest.approx(TG_DEFAULT)


def test_gate_only_lifts_never_cuts():
    # If terminal_g already exceeds the 0.045 target (e.g. a richer
    # per-ticker override), the lift gate is a no-op — never cuts.
    assert _apply_telecom_lift("BHARTIARTL", 0.05, 0.098) == pytest.approx(0.05)


def test_gate_safety_clamp_blocks_lift_near_wacc():
    # With a low WACC, lifting to 0.045 would violate the
    # `g < wacc - 0.02` invariant, so the clamp BLOCKS the lift and
    # terminal_g is left untouched (the Gordon model can never blow up).
    low_wacc = 0.06  # 0.045 is NOT < 0.06 - 0.02 = 0.04 → blocked
    assert _apply_telecom_lift("BHARTIARTL", TG_DEFAULT, low_wacc) == pytest.approx(TG_DEFAULT)
