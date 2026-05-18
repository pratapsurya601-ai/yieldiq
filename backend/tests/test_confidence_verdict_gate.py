"""Tests for backend.services.confidence_service.apply_confidence_verdict_gate
(Layer C, PR 2 — verdict-intensity gating).

Pure-function tests. The three scenarios in the task spec:
  - High confidence + MoS +30%       -> 'undervalued' preserved
  - Low confidence + MoS +30%        -> capped to 'fairly_valued'
  - Very low confidence + MoS +30%   -> forced to 'under_review'

The gate operates on (verdict, dq, mc, vs, data_issues). MoS is
informational only — the gate itself never reads it; the caller has
already produced ``verdict`` from MoS upstream.
"""

from __future__ import annotations

from backend.services.confidence_service import apply_confidence_verdict_gate


# ───────────────────────────────────────────────────────────────────
# Tier 1 — all scores >= 70: verdict unchanged
# ───────────────────────────────────────────────────────────────────
def test_high_confidence_preserves_undervalued():
    v, issues = apply_confidence_verdict_gate(
        "undervalued", data_quality=90, model_confidence=88, valuation_stability=85
    )
    assert v == "undervalued"
    assert all("confidence_gate" not in i for i in issues)


def test_high_confidence_preserves_overvalued():
    v, issues = apply_confidence_verdict_gate(
        "overvalued", data_quality=85, model_confidence=80, valuation_stability=82
    )
    assert v == "overvalued"
    assert not issues


def test_tier1_threshold_boundary():
    # All exactly 80 - still tier-1 (>=80)
    v, _ = apply_confidence_verdict_gate("undervalued", 80, 80, 80)
    assert v == "undervalued"
    # All exactly 70 - still tier-2 (>=70), unchanged
    v, _ = apply_confidence_verdict_gate("undervalued", 70, 70, 70)
    assert v == "undervalued"


# ───────────────────────────────────────────────────────────────────
# Tier 2 — any score < 70: intensity verdicts cap to fairly_valued
# ───────────────────────────────────────────────────────────────────
def test_low_confidence_caps_undervalued_to_fairly_valued():
    v, issues = apply_confidence_verdict_gate(
        "undervalued", data_quality=65, model_confidence=80, valuation_stability=80,
        data_issues=["pre-existing"],
    )
    assert v == "fairly_valued"
    # caveat appended; pre-existing issue preserved
    assert any("confidence_gate" in i for i in issues)
    assert "pre-existing" in issues


def test_low_confidence_caps_overvalued_to_fairly_valued():
    v, issues = apply_confidence_verdict_gate(
        "overvalued", 80, 60, 80
    )
    assert v == "fairly_valued"
    assert any("capped to 'fairly_valued'" in i for i in issues)


def test_low_confidence_leaves_fairly_valued_alone():
    v, issues = apply_confidence_verdict_gate("fairly_valued", 60, 80, 80)
    assert v == "fairly_valued"
    assert not issues  # no caveat — gate didn't actually narrow


# ───────────────────────────────────────────────────────────────────
# Tier 3 — all scores < 50: force under_review
# ───────────────────────────────────────────────────────────────────
def test_triple_low_forces_under_review():
    v, issues = apply_confidence_verdict_gate(
        "undervalued", data_quality=40, model_confidence=30, valuation_stability=20
    )
    assert v == "under_review"
    assert any("forced to under_review" in i for i in issues)


def test_triple_low_overrules_overvalued():
    v, _ = apply_confidence_verdict_gate("overvalued", 10, 20, 30)
    assert v == "under_review"


def test_triple_low_overrules_fairly_valued():
    # The audit's policy: triple-low forces under_review regardless of
    # incoming verdict (except pass-throughs). fairly_valued is NOT a
    # pass-through.
    v, _ = apply_confidence_verdict_gate("fairly_valued", 10, 20, 30)
    assert v == "under_review"


def test_two_low_one_ok_still_caps_not_forces():
    # Only 2 of 3 below 50: lands in tier 2, NOT tier 3
    v, _ = apply_confidence_verdict_gate("undervalued", 40, 40, 75)
    assert v == "fairly_valued"


# ───────────────────────────────────────────────────────────────────
# Pass-through verdicts
# ───────────────────────────────────────────────────────────────────
def test_data_limited_passes_through():
    v, issues = apply_confidence_verdict_gate("data_limited", 10, 10, 10)
    assert v == "data_limited"
    assert not issues


def test_under_review_passes_through():
    v, _ = apply_confidence_verdict_gate("under_review", 90, 90, 90)
    assert v == "under_review"


def test_avoid_passes_through():
    # avoid is its own thing — don't escalate or downgrade
    v, _ = apply_confidence_verdict_gate("avoid", 90, 90, 90)
    assert v == "avoid"
    v, _ = apply_confidence_verdict_gate("avoid", 10, 10, 10)
    assert v == "avoid"


def test_unavailable_passes_through():
    v, _ = apply_confidence_verdict_gate("unavailable", 10, 10, 10)
    assert v == "unavailable"


# ───────────────────────────────────────────────────────────────────
# None / missing scores
# ───────────────────────────────────────────────────────────────────
def test_all_none_scores_preserves_verdict():
    # None means "we couldn't compute" — treat as no signal, not as low
    v, _ = apply_confidence_verdict_gate("undervalued", None, None, None)
    assert v == "undervalued"


def test_partial_none_with_one_below_70_still_caps():
    v, _ = apply_confidence_verdict_gate("undervalued", None, 50, None)
    assert v == "fairly_valued"


# ───────────────────────────────────────────────────────────────────
# Spec scenarios (verbatim from task prompt)
# ───────────────────────────────────────────────────────────────────
def test_spec_high_confidence_mos_30pct_undervalued_preserved():
    # MoS +30% is encoded in `verdict='undervalued'` upstream.
    v, _ = apply_confidence_verdict_gate("undervalued", 90, 85, 82)
    assert v == "undervalued"


def test_spec_low_confidence_mos_30pct_caps_to_fairly_valued():
    v, issues = apply_confidence_verdict_gate("undervalued", 60, 80, 80)
    assert v == "fairly_valued"
    assert any("capped" in i for i in issues)


def test_spec_very_low_confidence_mos_30pct_forces_under_review():
    v, issues = apply_confidence_verdict_gate("undervalued", 30, 40, 25)
    assert v == "under_review"
    assert any("forced to under_review" in i for i in issues)
