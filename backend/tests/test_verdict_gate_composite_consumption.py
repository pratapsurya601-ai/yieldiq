# backend/tests/test_verdict_gate_composite_consumption.py
# ═══════════════════════════════════════════════════════════════
# Phase C (2026-06-10) — contract pin for the verdict gate's FV input.
#
# This PR (Phase C.1) ships the COMPOSITE WEIGHT CHANGE only. The
# verdict gate continues to read `valuation.fair_value` (DCF-only)
# as its FV input — same posture as pre-Phase-C. The follow-up PR
# (Phase C.2) flips the gate to prefer `composite_intrinsic_value`
# when present and fall back to `fair_value` when None.
#
# Why split: switching the gate's FV input in the same PR as the
# composite weight change made it impossible to attribute any verdict
# flips to a single cause when canary-diff lit up. By landing weight
# first, we get a clean before/after on the composite value (and the
# canary signature) before the gate's behaviour shifts.
#
# This file pins TWO contracts that the Phase C.2 PR will edit:
#   1. The gate function accepts `fair_value=` keyword and uses it
#      for the FV/price ratio override + the MoS-based bull/bear
#      bypass logic. (Stable today; will stay stable in Phase C.2.)
#   2. When called with composite=None, the gate's behaviour is
#      IDENTICAL to today. The "fallback to fair_value when composite
#      is None" branch in Phase C.2 must preserve this.
#
# Test cases for the actual composite-consumption switch live alongside
# the Phase C.2 PR; this file is the bridge contract.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.services.confidence_service import (
    BEAR_OVERVALUED_BYPASS_CONFIDENCE,
    BEAR_OVERVALUED_BYPASS_MOS,
    BULL_UNDERVALUED_BYPASS_CONFIDENCE,
    BULL_UNDERVALUED_BYPASS_MOS,
    _apply_confidence_verdict_gate,
)


class TestGateAcceptsFairValueKwarg:
    """Contract: the gate's signature must keep `fair_value=` as a
    keyword-only argument so callers can switch the source of FV
    without changing the call shape."""

    def test_fair_value_keyword_accepted_with_passthrough_verdict(self):
        # data_limited is a passthrough verdict — gate returns unchanged.
        out_verdict, out_issues = _apply_confidence_verdict_gate(
            verdict="data_limited",
            data_quality=80,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=1000.0,
            current_price=900.0,
            valuation_model="dcf",
        )
        assert out_verdict == "data_limited"
        assert out_issues == []

    def test_fair_value_none_passes_gate_safely(self):
        # Phase C.2 will call this branch when composite_intrinsic_value
        # is None AND valuation.fair_value is None. The gate must not
        # crash on a fully-None FV input.
        out_verdict, out_issues = _apply_confidence_verdict_gate(
            verdict="fairly_valued",
            data_quality=80,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=None,
            current_price=None,
            valuation_model="dcf",
        )
        # Without FV/price the ratio override skips and the intensity cap
        # has no extreme verdict to act on — fairly_valued passes through.
        assert out_verdict == "fairly_valued"


class TestExtremeRatioOverride:
    """Layer 1 — when FV/price ratio is extreme AND confidence is low,
    the gate forces under_review. This is exactly the surface Phase C.2
    will redirect: feeding composite vs DCF here changes which tickers
    trip this gate."""

    def test_extreme_ratio_low_confidence_forces_under_review(self):
        # FV=200, price=1000 → ratio=0.2 (right at low threshold);
        # FV=100 → ratio=0.1 → well below. Use 0.1 to ensure trigger.
        out_verdict, out_issues = _apply_confidence_verdict_gate(
            verdict="notably_overvalued",
            data_quality=60,  # < 70 trips the low-conf gate
            model_confidence=60,
            valuation_stability=60,
            data_issues=[],
            fair_value=100.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        assert out_verdict == "under_review"
        assert any("FV/price ratio" in s for s in out_issues)

    def test_extreme_ratio_high_confidence_does_not_override(self):
        # Same extreme ratio, but high confidence — gate leaves verdict alone.
        out_verdict, _ = _apply_confidence_verdict_gate(
            verdict="overvalued",
            data_quality=85,
            model_confidence=85,
            valuation_stability=85,
            data_issues=[],
            fair_value=100.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        assert out_verdict == "overvalued"

    def test_rate_base_carveout_skips_ratio_override(self):
        # Rate-base utilities are in _RATIO_OVERRIDE_CARVEOUTS — even
        # extreme ratio + low confidence doesn't force under_review.
        # We pick FV=100 / price=1000 → ratio 0.1 (extreme) but
        # MoS = -90% so the bear-side bypass would normally fire under
        # the intensity-cap branch. The carveout we care about here is
        # Layer 1: ratio override SHOULD NOT fire because rate_base is
        # carved out. Test by confirming we did NOT get under_review.
        out_verdict, _ = _apply_confidence_verdict_gate(
            verdict="overvalued",
            data_quality=60,
            model_confidence=60,
            valuation_stability=60,
            data_issues=[],
            fair_value=100.0,
            current_price=1000.0,
            valuation_model="rate_base",
        )
        # The ratio override does NOT fire (else it would be
        # under_review). It returns SOME other verdict — the
        # intensity-cap branch may then downgrade or bypass; what we
        # assert here is purely "ratio override skipped for rate_base".
        assert out_verdict != "under_review"


class TestTripleLowConfidence:
    """Triple-low confidence (all three pillars < 50) forces under_review."""

    def test_all_three_below_50_forces_under_review(self):
        out_verdict, out_issues = _apply_confidence_verdict_gate(
            verdict="fairly_valued",
            data_quality=40,
            model_confidence=40,
            valuation_stability=40,
            data_issues=[],
            fair_value=900.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        assert out_verdict == "under_review"
        assert any("confidence_gate" in s for s in out_issues)


class TestIntensityCap:
    """Any pillar < 70 caps intensity verdicts down to fairly_valued
    (except for the bull/bear MoS bypass paths)."""

    def test_low_dq_caps_overvalued_to_fairly_valued(self):
        out_verdict, _ = _apply_confidence_verdict_gate(
            verdict="overvalued",
            data_quality=60,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=880.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        # MoS = (880-1000)/1000 = -12% — inside the neutral band, ABOVE the
        # -15 bear bypass (lowered from -25 in the 2026-06-14 calibration
        # audit), so the Layer-3 intensity cap fires. (At -20 the bypass
        # would now correctly keep "overvalued".)
        assert out_verdict == "fairly_valued"

    def test_high_confidence_lets_overvalued_through(self):
        out_verdict, _ = _apply_confidence_verdict_gate(
            verdict="overvalued",
            data_quality=80,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=800.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        assert out_verdict == "overvalued"


class TestBullBearBypassUsesFV:
    """The bull/bear bypass paths re-derive MoS from `fair_value` and
    `current_price`. This is exactly the math Phase C.2 will redirect
    to use `composite_intrinsic_value` instead."""

    def test_bear_bypass_at_extreme_negative_mos_with_high_mc(self):
        # MoS = (300-1000)/1000 = -70% → far below BEAR_OVERVALUED_BYPASS_MOS.
        # mc >= BEAR_OVERVALUED_BYPASS_CONFIDENCE allows the bypass.
        out_verdict, out_issues = _apply_confidence_verdict_gate(
            verdict="overvalued",
            data_quality=60,  # < 70 to enter the intensity cap branch
            model_confidence=BEAR_OVERVALUED_BYPASS_CONFIDENCE,
            valuation_stability=60,
            data_issues=[],
            fair_value=300.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        # The bear bypass should return a verdict in the overvalued family
        # (the exact string depends on the intensity rules — but it
        # should NOT have been capped down to fairly_valued).
        assert out_verdict != "fairly_valued"

    def test_bull_bypass_at_extreme_positive_mos_with_high_mc(self):
        # MoS = (3000-1000)/1000 = 200% → well above BULL_UNDERVALUED_BYPASS_MOS.
        out_verdict, _ = _apply_confidence_verdict_gate(
            verdict="undervalued",
            data_quality=60,  # < 70 to enter the intensity cap branch
            model_confidence=BULL_UNDERVALUED_BYPASS_CONFIDENCE,
            valuation_stability=60,
            data_issues=[],
            fair_value=3000.0,
            current_price=1000.0,
            valuation_model="dcf",
        )
        assert out_verdict != "fairly_valued"


class TestPhaseC2ContractBridge:
    """The follow-up Phase C.2 PR will:
      1. Read `composite_intrinsic_value` first; fall back to
         `valuation.fair_value` when None.
      2. Pass whichever value won as `fair_value=` to this gate.
      3. Recompute MoS off the same value.

    This file documents the contract the gate exposes to that switch.
    The gate itself does NOT need to know which IV source the caller
    used — `fair_value=` is the only input it acts on.
    """

    def test_gate_signature_uses_fair_value_keyword_for_iv(self):
        # If a future PR renames `fair_value=` to anything else, this
        # test fires loudly so the call sites get updated together.
        import inspect

        sig = inspect.signature(_apply_confidence_verdict_gate)
        assert "fair_value" in sig.parameters
        assert sig.parameters["fair_value"].kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    def test_gate_treats_composite_or_dcf_input_uniformly(self):
        # Two calls — one with the "DCF" FV (1000), one with the
        # "composite" FV (900). The gate output depends only on the
        # FV/price ratio + the MoS math; same shape, different number.
        out_dcf, _ = _apply_confidence_verdict_gate(
            verdict="fairly_valued",
            data_quality=80,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=1000.0,
            current_price=950.0,
            valuation_model="dcf",
        )
        out_composite, _ = _apply_confidence_verdict_gate(
            verdict="fairly_valued",
            data_quality=80,
            model_confidence=80,
            valuation_stability=80,
            data_issues=[],
            fair_value=900.0,
            current_price=950.0,
            valuation_model="dcf",
        )
        # With high confidence + reasonable ratios, both pass through.
        assert out_dcf == "fairly_valued"
        assert out_composite == "fairly_valued"
