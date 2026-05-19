"""Tests for the extreme-FV/price-ratio override layer of
``_apply_confidence_verdict_gate`` (Layer C extension, 2026-05-19).

Background: PR #340/#342 shipped Layer C with three 0-100 scores and
a verdict-intensity cap. The post-Layer-C reconciliation report
(2026-05-19) still surfaced 338 outliers — many shipping as
"Notably Undervalued" / "Notably Overvalued" despite a borderline
model_confidence in the 50-70 band (above the triple-low force-
under_review floor). The extreme-ratio override catches these:
when FV is more than 5x off price in either direction AND any
confidence pillar is below 70, force `under_review` regardless of
the intensity-cap branch.

These tests pin the spec'd cases from the agent brief.
"""

from __future__ import annotations

import pytest

from backend.services.confidence_service import (
    _apply_confidence_verdict_gate,
    apply_confidence_verdict_gate,
)


# ───────────────────────────────────────────────────────────────────
# Extreme-ratio override — fires
# ───────────────────────────────────────────────────────────────────
def test_indiacem_shape_forced_under_review():
    """FV=0.77 at CMP=405, model_conf=50 -> ratio 0.0019 << 0.2 and
    confidence below 70: must force under_review."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"
    assert any("FV/price ratio" in i and "extreme" in i for i in issues)


def test_tmpv_shape_high_ratio_forced_under_review():
    """FV=2000 at CMP=400, model_conf=50 -> ratio 5.0 (boundary high,
    > 5.0 trips). Use 2001/400 to be safely above threshold."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_overvalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=2001.0,
        current_price=400.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"
    assert any("FV/price ratio" in i for i in issues)


def test_paytm_shape_forced_under_review():
    """FV=41 at CMP=1400 -> ratio ~0.029, model_conf=50: forced."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=55,
        model_confidence=50,
        valuation_stability=65,
        data_issues=[],
        fair_value=41.0,
        current_price=1400.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"


def test_data_quality_below_floor_also_trips_override():
    """The override is gated on model_conf < 70 OR data_quality < 70.
    Even with model_conf at 75, low dq must still fire."""
    verdict, _ = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=55,
        model_confidence=75,
        valuation_stability=80,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"


# ───────────────────────────────────────────────────────────────────
# Extreme-ratio override — does NOT fire
# ───────────────────────────────────────────────────────────────────
def test_modest_ratio_passes_through():
    """FV=500 at CMP=600 -> ratio 0.83, well within [0.2, 5.0].
    Even with low confidence the override must not fire (the
    intensity-cap layer below may still rewrite, but not to
    under_review)."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=500.0,
        current_price=600.0,
        valuation_model="dcf",
    )
    # Must NOT be under_review from the ratio path.
    # (Intensity cap may have downgraded to fairly_valued, which is
    # the correct old behavior — that's fine.)
    assert verdict != "under_review"
    # Sanity: no extreme-ratio caveat present.
    assert not any("FV/price ratio" in i and "extreme" in i for i in issues)


def test_high_confidence_extreme_ratio_unchanged():
    """FV=0.77 at CMP=405, model_conf=90, dq=85, vs=85: ratio is
    extreme but the model is highly confident. Leave the verdict
    alone — if the engine is sure, trust it."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=85,
        model_confidence=90,
        valuation_stability=85,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == "notably_undervalued"
    assert not any("FV/price ratio" in i for i in issues)


# ───────────────────────────────────────────────────────────────────
# Carve-outs — engines where wide ratios are legitimate
# ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("model", [
    "rate_base",
    "appraisal_value",
    "reit_nav_dpu_required",
    "holding_company_sotp_required",
    "etf_nav_based",
])
def test_carveout_models_skip_extreme_ratio_override(model):
    """Regulated utilities (rate_base), insurance (appraisal_value),
    REITs, holdcos and ETFs legitimately produce wide FV ratios.
    The override must not fire for them."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model=model,
    )
    # Carved out -> override skipped. Intensity-cap layer (below)
    # would still cap the "notably_*" verdict to fairly_valued
    # because mc=50, but it MUST NOT be under_review.
    assert verdict != "under_review"
    assert not any("FV/price ratio" in i and "Manual review" in i for i in issues)


# ───────────────────────────────────────────────────────────────────
# Pass-through verdicts — never modified
# ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("verdict_in", [
    "data_limited", "unavailable", "under_review", "avoid",
])
def test_passthrough_verdicts_immune_to_override(verdict_in):
    verdict, issues = _apply_confidence_verdict_gate(
        verdict=verdict_in,
        data_quality=10,
        model_confidence=10,
        valuation_stability=10,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == verdict_in
    assert issues == []


# ───────────────────────────────────────────────────────────────────
# Existing intensity-cap behavior must still work after the extension
# ───────────────────────────────────────────────────────────────────
def test_triple_low_still_forces_under_review_when_ratio_normal():
    """Triple-low confidence with a normal FV/price ratio still
    routes via the original PR #342 force-under_review path."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=40,
        model_confidence=40,
        valuation_stability=40,
        data_issues=[],
        fair_value=500.0,
        current_price=600.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"
    assert any("confidence_gate" in i for i in issues)


def test_intensity_cap_normal_ratio_low_one_pillar():
    """One score < 70, ratio normal: intensity-cap layer rewrites
    `notably_undervalued` -> `fairly_valued` (PR #342 spec)."""
    verdict, _ = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=80,
        valuation_stability=80,
        data_issues=[],
        fair_value=500.0,
        current_price=600.0,
        valuation_model="dcf",
    )
    assert verdict == "fairly_valued"


def test_all_high_unchanged():
    verdict, _ = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=85,
        model_confidence=85,
        valuation_stability=85,
        data_issues=[],
        fair_value=500.0,
        current_price=600.0,
        valuation_model="dcf",
    )
    assert verdict == "notably_undervalued"


# Public alias must point at the same function.
def test_public_alias_matches():
    assert apply_confidence_verdict_gate is _apply_confidence_verdict_gate
