"""Audit#6: backend mirror of frontend PR #499 overvalued bear-side gate.

Background
----------
PR #499 added the asymmetric bear-side bypass to
``frontend/src/lib/utils.ts::shouldGateVerdict``. It corrected four
audit-universe tickers (SUNPHARMA mos -33%, MARUTI -31%, SBIN -31%,
ASIANPAINT -47%) that the symmetric Day-91 / Layer-3 gate had
collapsed to ``fairly_valued`` despite the model clearly flagging a
material premium to fair value.

The frontend fix did not propagate to:

* ``/api/v1/public/stock-summary`` consumers (API users)
* og-data path (shared helper, but reads backend ``verdict``)
* push-notification copy for ``verdict_change`` alerts
* email-alerts service
* any analytics service keying off ``verdict``

This test pins the symmetric backend behaviour so the API payload
agrees with the UI label.

Pinned rule (mirror of frontend constants):

* ``BEAR_OVERVALUED_BYPASS_MOS = -25.0``
* ``BEAR_OVERVALUED_BYPASS_CONFIDENCE = 40``
* ``BEAR_NOTABLY_OVERVALUED_MOS = -40.0``

When ``mos_pct <= -25 AND model_confidence >= 40`` and the input
verdict is in the overvalued band, the Layer-3 intensity cap does NOT
fire and the gate returns the engine's overvalued / notably_overvalued
label unchanged (re-derived from MoS so it tracks the frontend
``verdictFromMos`` boundaries).
"""

from __future__ import annotations

from backend.services.confidence_service import (
    BEAR_NOTABLY_OVERVALUED_MOS,
    BEAR_OVERVALUED_BYPASS_CONFIDENCE,
    BEAR_OVERVALUED_BYPASS_MOS,
    _apply_confidence_verdict_gate,
)


# ── Constant pinning — these are the frontend contract ────────────
def test_bear_overvalued_bypass_constants_match_frontend() -> None:
    """Constants must match frontend/src/lib/utils.ts exactly. If
    these drift, the API payload and the rendered pill will disagree
    on a subset of bear-side tickers (the exact bug Audit#6 closed)."""
    assert BEAR_OVERVALUED_BYPASS_MOS == -25.0
    assert BEAR_OVERVALUED_BYPASS_CONFIDENCE == 40
    assert BEAR_NOTABLY_OVERVALUED_MOS == -40.0


# ── Helper: invoke the gate with a SUNPHARMA-shape call ───────────
def _gate(
    verdict: str,
    mos_pct: float,
    model_confidence: int | None,
    *,
    data_quality: int | None = 65,
    valuation_stability: int | None = 65,
    valuation_model: str = "dcf",
) -> tuple[str, list[str]]:
    """Call the gate with an FV/price pair that produces ``mos_pct``.

    Anchors at price=100; fair_value = 100 * (1 + mos_pct/100). This
    mirrors how the real wiring in
    ``backend/services/analysis/service.py`` calls the gate
    (``fair_value=iv, current_price=price, valuation_model=_cf_method``).
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


# ── Required scenarios from Audit#6 spec ──────────────────────────
def test_sunpharma_shape_overvalued_passes_through() -> None:
    """mos=-33, conf=55 -> overvalued (was: fairly_valued).

    Real ticker the audit caught: SUNPHARMA at mos=-33%, model
    confidence ~55. Before Audit#6 the Layer-3 cap collapsed this
    to fairly_valued. Post-fix it surfaces honestly.
    """
    verdict, issues = _gate("overvalued", mos_pct=-33.0, model_confidence=55)
    assert verdict == "overvalued"
    assert any("Bear-side bypass" in s for s in issues)


def test_asianpaint_shape_notably_overvalued_passes_through() -> None:
    """mos=-47, conf=55 -> notably_overvalued.

    Real ticker: ASIANPAINT at mos=-47% — below the
    BEAR_NOTABLY_OVERVALUED_MOS=-40 threshold so the gate deepens
    the label to notably_overvalued even if the engine emitted the
    coarser ``overvalued``. Matches frontend verdictFromMos.
    """
    verdict, _ = _gate("overvalued", mos_pct=-47.0, model_confidence=55)
    assert verdict == "notably_overvalued"


def test_just_above_threshold_still_caps_to_fairly_valued() -> None:
    """mos=-23 is ABOVE the -25 threshold so the bypass does not
    fire; Layer-3 intensity cap applies normally and the verdict
    collapses to fairly_valued."""
    verdict, _ = _gate("overvalued", mos_pct=-23.0, model_confidence=55)
    assert verdict == "fairly_valued"


def test_low_confidence_still_gates() -> None:
    """mos=-33, conf=25 — confidence is below the
    BEAR_OVERVALUED_BYPASS_CONFIDENCE floor so the bypass does NOT
    fire. The Layer-3 cap takes over and the verdict collapses.

    Confidence honesty: at mc=25 we genuinely do not know enough to
    surface a directional verdict; flattening to fairly_valued is
    the right read.
    """
    verdict, _ = _gate("overvalued", mos_pct=-33.0, model_confidence=25)
    assert verdict == "fairly_valued"


def test_bull_side_unchanged_high_mos_low_confidence() -> None:
    """mos=+48, conf=55 — bull side keeps the original symmetric
    cap. Notably_undervalued at moderate confidence collapses to
    fairly_valued so a noisy deep-value signal cannot mislead.

    Acting on a noisy "deep value" read is the larger trust risk
    on the bull side. Bear-side bypass is asymmetric on purpose.
    """
    verdict, _ = _gate(
        "notably_undervalued", mos_pct=48.0, model_confidence=55
    )
    assert verdict == "fairly_valued"


# ── Boundary + interaction with other layers ──────────────────────
def test_data_limited_passthrough_not_affected() -> None:
    """data_limited is a PASSTHROUGH verdict — the gate must never
    flip it to overvalued / notably_overvalued via the bypass.
    Frontend short-circuits on dataLimited === true; backend must
    match by simply not touching pass-through verdicts."""
    verdict, _ = _gate("data_limited", mos_pct=-33.0, model_confidence=55)
    assert verdict == "data_limited"


def test_triple_low_still_forces_under_review() -> None:
    """Layer 2 (all three scores < 50 -> under_review) takes
    precedence over the bear-side bypass. Genuine triple-low
    confidence is more important than the overvalued surfacing
    discipline — we will not surface a directional verdict when
    every pillar score signals untrustworthy data."""
    verdict, _ = _gate(
        "overvalued",
        mos_pct=-33.0,
        model_confidence=40,
        data_quality=30,
        valuation_stability=30,
    )
    # Layer 2 wins before Layer 3 / bypass runs.
    assert verdict == "under_review"


def test_extreme_ratio_under_review_still_fires() -> None:
    """Layer 1 (extreme FV/price ratio + low confidence ->
    under_review) takes precedence. At mos=-90 the ratio fv/price =
    0.10 trips the _RATIO_LOW=0.20 extreme threshold, and with
    mc=55 < _RATIO_OVERRIDE_CONF_FLOOR=70 the gate forces
    under_review regardless of the bear-side bypass."""
    verdict, _ = _gate("notably_overvalued", mos_pct=-90.0, model_confidence=55)
    assert verdict == "under_review"


def test_all_scores_high_no_gate_applied() -> None:
    """All three pillar scores >= 70 — neither Layer 1, 2, nor 3
    fires. The engine's verdict passes through unchanged.
    Confirms the bypass is a Layer-3 carve-out, not a new layer."""
    verdict, issues = _gate(
        "overvalued",
        mos_pct=-33.0,
        model_confidence=80,
        data_quality=80,
        valuation_stability=80,
    )
    assert verdict == "overvalued"
    assert not any("Bear-side bypass" in s for s in issues)
