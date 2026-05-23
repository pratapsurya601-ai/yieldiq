"""Day-111c: bull-side symmetric undervalued bypass.

Background
----------
The Day-111 top-100 audit found 19 tickers where the Layer-3
confidence cap in
``backend/services/confidence_service.py::_apply_confidence_verdict_gate``
collapsed the engine's bull-side intensity verdict
("undervalued"/"notably_undervalued") down to "fairly_valued"
because ANY of the three confidence scores sat below 70. Most
egregious: LICI at +95.3% MoS with moderate model_confidence read
as "fairly_valued" in the public API — a credibility-breaking
mismatch with the engine's own headline.

The fix mirrors the bear-side Audit#6 / PR #503 logic onto the
bull tail: when ``mos_pct >= BULL_UNDERVALUED_BYPASS_MOS`` (+50%)
AND ``model_confidence >= BULL_UNDERVALUED_BYPASS_CONFIDENCE`` (30),
the Layer-3 cap does NOT fire. The output is clamped to the valid
``ValuationOutput.verdict`` literal "undervalued" with an
intensity_hint of "notably_undervalued" when mos_pct >= 80%
surfaced in ``data_issues`` for analytics (same pattern the bear
branch uses after the Audit#7 P0 ValidationError fix).

The bypass NEVER overrides data_limited / unavailable / under_review
/ avoid — those need stronger gates than just MoS. Layer-1
(extreme FV/price ratio) and Layer-2 (triple-low under_review)
still fire first.
"""

from __future__ import annotations

from backend.services.confidence_service import (
    BEAR_NOTABLY_OVERVALUED_MOS,
    BEAR_OVERVALUED_BYPASS_CONFIDENCE,
    BEAR_OVERVALUED_BYPASS_MOS,
    BULL_NOTABLY_UNDERVALUED_MOS,
    BULL_UNDERVALUED_BYPASS_CONFIDENCE,
    BULL_UNDERVALUED_BYPASS_MOS,
    _apply_confidence_verdict_gate,
)


# ── Constant pinning ─────────────────────────────────────────────
def test_bull_undervalued_bypass_constants() -> None:
    """Pin the constants — drift here means the API and the
    frontend pill can disagree on a subset of bull-side tickers."""
    assert BULL_UNDERVALUED_BYPASS_MOS == 50.0
    assert BULL_UNDERVALUED_BYPASS_CONFIDENCE == 30
    assert BULL_NOTABLY_UNDERVALUED_MOS == 80.0


# ── Helper: invoke the gate with a (mos_pct, mc) pair ────────────
def _gate(
    verdict: str,
    mos_pct: float,
    model_confidence: int | None,
    *,
    data_quality: int | None = 65,
    valuation_stability: int | None = 65,
    valuation_model: str = "dcf",
) -> tuple[str, list[str]]:
    """Mirror of test_audit6_backend_overvalued_mirror._gate.

    Anchors at price=100; fair_value = 100 * (1 + mos_pct/100).
    """
    price = 100.0
    fair_value = price * (1.0 + mos_pct / 100.0)
    return _apply_confidence_verdict_gate(
        verdict,
        data_quality,
        model_confidence,
        valuation_stability,
        [],
        fair_value=fair_value,
        current_price=price,
        valuation_model=valuation_model,
    )


# ── Core regression: LICI shape ──────────────────────────────────
def test_lici_shape_returns_undervalued_with_notably_intensity_hint() -> None:
    """LICI: mos=+95.3%, mc=55. Pre-Day-111c: "fairly_valued".
    Post-Day-111c: "undervalued" (clamped from notably_undervalued
    to a valid ValuationOutput.verdict literal) with the deeper
    intensity surfaced via intensity_hint in issues."""
    verdict, issues = _gate("notably_undervalued", mos_pct=95.3, model_confidence=55)
    assert verdict == "undervalued"
    assert any("Bull-side bypass" in i for i in issues)
    assert any("intensity_hint='notably_undervalued'" in i for i in issues)


def test_mos60_conf40_undervalued() -> None:
    """mos=+60%, conf=40 — clears both thresholds, plain
    'undervalued' (intensity_hint='undervalued' since < 80%)."""
    verdict, issues = _gate("undervalued", mos_pct=60.0, model_confidence=40)
    assert verdict == "undervalued"
    assert any("intensity_hint='undervalued'" in i for i in issues)


def test_mos45_conf80_existing_cap_preserved() -> None:
    """mos=+45%, conf=80 — but valuation_stability=65 still trips
    the Layer-3 'any score below 70' cap. mos_pct is below the
    BULL_UNDERVALUED_BYPASS_MOS=50 threshold, so the bypass does
    NOT fire and the existing 'fairly_valued' cap holds."""
    verdict, issues = _gate(
        "undervalued",
        mos_pct=45.0,
        model_confidence=80,
        data_quality=65,
    )
    assert verdict == "fairly_valued"
    assert any("Confidence below threshold" in i for i in issues)


def test_mos85_conf20_data_limited_inbound_preserved() -> None:
    """Inbound 'data_limited' is a pass-through verdict. No bypass
    fires regardless of MoS — data_limited needs stronger gates
    than just MoS."""
    verdict, issues = _gate("data_limited", mos_pct=85.0, model_confidence=20)
    assert verdict == "data_limited"
    # No bypass / no cap message expected
    assert not any("Bull-side bypass" in i for i in issues)


def test_mos85_conf20_triple_low_forces_under_review() -> None:
    """mos=+85%, mc=20, dq=20, vs=20 — Layer-2 triple-low fires
    BEFORE the Layer-3 bull bypass. under_review wins."""
    verdict, issues = _gate(
        "undervalued",
        mos_pct=85.0,
        model_confidence=20,
        data_quality=20,
        valuation_stability=20,
    )
    assert verdict == "under_review"


def test_mos85_conf_below_floor_caps_to_fairly_valued() -> None:
    """mos=+85% but confidence=25 (below the BULL_UNDERVALUED_BYPASS_
    CONFIDENCE=30 floor). The bypass does NOT fire; Layer-3 cap
    holds and the verdict collapses to 'fairly_valued'. This is
    the explicit asymmetry baked into the spec: a confidence floor
    on the bull side still exists, just lower than the bear side."""
    verdict, _ = _gate("notably_undervalued", mos_pct=85.0, model_confidence=25)
    assert verdict == "fairly_valued"


def test_mos80_exact_threshold_notably_intensity_hint() -> None:
    """At exactly mos=80% the intensity_hint deepens to
    'notably_undervalued' (the >= boundary)."""
    _, issues = _gate("notably_undervalued", mos_pct=80.0, model_confidence=50)
    assert any("intensity_hint='notably_undervalued'" in i for i in issues)


def test_mos50_exact_threshold_fires_bypass() -> None:
    """At exactly mos=50% the bypass fires (>= boundary)."""
    verdict, _ = _gate("undervalued", mos_pct=50.0, model_confidence=30)
    assert verdict == "undervalued"


def test_all_scores_high_no_gating() -> None:
    """All three scores >= 70 — Layer-3 cap never fires, so the
    bull bypass is irrelevant. Verdict passes through unchanged
    (the engine's original 'notably_undervalued' would be returned
    by _apply_confidence_verdict_gate verbatim; consumers that
    can't render that literal handle the clamp at their own layer)."""
    verdict, _ = _gate(
        "notably_undervalued",
        mos_pct=95.0,
        model_confidence=80,
        data_quality=80,
        valuation_stability=80,
    )
    assert verdict == "notably_undervalued"


# ── Symmetry check: existing bear-side cases unchanged ───────────
def test_bear_sunpharma_unchanged() -> None:
    """SUNPHARMA-shape (mos=-33, mc=55) still returns 'overvalued'
    via the bear-side bypass — Day-111c must not regress Audit#6."""
    verdict, issues = _gate("overvalued", mos_pct=-33.0, model_confidence=55)
    assert verdict == "overvalued"
    assert any("Bear-side bypass" in i for i in issues)


def test_bear_asianpaint_unchanged() -> None:
    """ASIANPAINT-shape (mos=-47, mc=55) still returns 'overvalued'
    (clamped from notably_overvalued per Audit#7 P0) with
    intensity_hint='notably_overvalued'."""
    verdict, issues = _gate("notably_overvalued", mos_pct=-47.0, model_confidence=55)
    assert verdict == "overvalued"
    assert any("intensity_hint='notably_overvalued'" in i for i in issues)


def test_bear_bypass_constants_still_pinned() -> None:
    """Sanity: bear-side constants unchanged by Day-111c."""
    assert BEAR_OVERVALUED_BYPASS_MOS == -25.0
    assert BEAR_OVERVALUED_BYPASS_CONFIDENCE == 40
    assert BEAR_NOTABLY_OVERVALUED_MOS == -40.0
