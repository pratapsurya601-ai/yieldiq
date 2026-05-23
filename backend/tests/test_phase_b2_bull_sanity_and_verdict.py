"""Phase B.2 (2026-05-24): bull_case sanity gate + Day-111c verdict tune.

Two coupled fixes, one test module:

1. ``clamp_inflated_scenarios`` in ``dcf_collapse_safety_net.py`` —
   when bull > 5x current_price, the DCF has almost certainly been
   broken by a too-low WACC (Day-107a IT-services cohort dropped WACC
   from 0.1114 → 0.098 and ballooned WIPRO/HCLTECH/TECHM bulls to
   ~33x CMP). Pre-clamp all three scenario values back to a sane band
   so the safety net's iv/price ratio gate doesn't strand the ticker
   in `data_limited`.

2. ``BULL_UNDERVALUED_BYPASS_MOS`` lowered 50 → 40 in
   ``confidence_service.py`` — HDFCBANK landed at +43.1% MoS with
   model_confidence=90 but the original 50% bar kept Layer-3 capping
   the verdict to 'fairly_valued'. 40% at confidence >= 30 is genuinely
   undervalued territory.

See ``docs/diagnostics/phase-b-cache-paths-2026-05-24.md`` for the
root-cause analysis that motivated this fix.
"""

from __future__ import annotations

from backend.services.confidence_service import (
    BULL_NOTABLY_UNDERVALUED_MOS,
    BULL_UNDERVALUED_BYPASS_CONFIDENCE,
    BULL_UNDERVALUED_BYPASS_MOS,
    _apply_confidence_verdict_gate,
)
from backend.services.dcf_collapse_safety_net import (
    BULL_SANITY_MULTIPLIER,
    clamp_inflated_scenarios,
)


# ─────────────────────────────────────────────────────────────────
# Fix 1: bull_case sanity gate
# ─────────────────────────────────────────────────────────────────

def test_bull_sanity_multiplier_pin() -> None:
    """Pin the threshold — drift here would silently expand or
    shrink the scope of clamp coverage."""
    assert BULL_SANITY_MULTIPLIER == 5.0


def test_wipro_shape_bull_clamped_base_pulled_down() -> None:
    """WIPRO live (2026-05-23): base=858, bull=6734, bear=687,
    price=203 (bull = 33.2x price). Expect bull → 1015 (= 5*203),
    base pulled down so the iv/price ratio gate at L208 no longer
    fires (and the data_limited fallout is avoided)."""
    result = clamp_inflated_scenarios(
        base_fv=858.0, bull_fv=6734.0, bear_fv=687.0, current_price=203.0,
    )
    assert result is not None
    base_c, bull_c, bear_c, reason = result
    assert bull_c == 1015.0  # 5 * 203
    # base must be <= bull and base/price must NOT trigger
    # INFLATED_RATIO_HI=3.5 — i.e. base must land at <= 3.5 * 203 = 710.5.
    # Our impl scales base by clamp_ratio (1015/6734 ≈ 0.1508), so
    # 858 * 0.1508 ≈ 129; we floor at 0.8 * bull_c = 812. Either way
    # the ratio stays well below 3.5x.
    assert base_c <= bull_c
    assert base_c / 203.0 < 3.5
    assert bear_c > 0
    assert bear_c <= base_c
    assert "bull_case_clamped_from_implausible_multiple" in reason


def test_techm_shape_bull_clamped() -> None:
    """TECHM live (2026-05-23): base=5685, bull=46788, bear=4548,
    price=1422 (bull = 32.9x price). Same shape as WIPRO."""
    result = clamp_inflated_scenarios(
        base_fv=5685.0, bull_fv=46788.0, bear_fv=4548.0, current_price=1422.0,
    )
    assert result is not None
    base_c, bull_c, bear_c, _ = result
    assert bull_c == 7110.0  # 5 * 1422
    assert base_c <= bull_c
    assert base_c / 1422.0 < 3.5


def test_hcltech_shape_bull_clamped() -> None:
    """HCLTECH live (2026-05-23): base=1623, bull=1877, bear=904,
    price=1164 (bull = 1.61x). DOES NOT clamp — bull is sane.
    Verifies the gate is conservative."""
    result = clamp_inflated_scenarios(
        base_fv=1623.0, bull_fv=1877.0, bear_fv=904.0, current_price=1164.0,
    )
    # HCLTECH actually has sane bull/base ratios despite being
    # tagged data_limited — its data_limited comes from a different
    # path (probably the confidence-score gate, not the safety net).
    # The clamp correctly stays out of the way.
    assert result is None


def test_tcs_sane_bull_no_clamp() -> None:
    """TCS live (2026-05-23): base=3436, bull=3977, bear=1911,
    price=2317 (bull = 1.72x). No clamp — bull is sane."""
    result = clamp_inflated_scenarios(
        base_fv=3436.0, bull_fv=3977.0, bear_fv=1911.0, current_price=2317.0,
    )
    assert result is None


def test_infy_sane_bull_no_clamp() -> None:
    """INFY live (2026-05-23): base=1846, bull=2215, bear=1068,
    price=1175 (bull = 1.89x). No clamp."""
    result = clamp_inflated_scenarios(
        base_fv=1846.0, bull_fv=2215.0, bear_fv=1068.0, current_price=1175.0,
    )
    assert result is None


def test_growth_stock_4x_bull_no_clamp() -> None:
    """A legitimate growth-stock bull at 4x price (between 3.5
    INFLATED_RATIO_HI and 5x BULL_SANITY_MULTIPLIER) survives —
    the clamp is deliberately wider than the safety-net iv gate so
    legitimate deep-bull narratives aren't squashed."""
    result = clamp_inflated_scenarios(
        base_fv=200.0, bull_fv=400.0, bear_fv=60.0, current_price=100.0,
    )
    assert result is None


def test_exactly_5x_no_clamp_boundary() -> None:
    """At exactly 5.0x the gate does NOT fire — boundary is strict >."""
    result = clamp_inflated_scenarios(
        base_fv=200.0, bull_fv=500.0, bear_fv=60.0, current_price=100.0,
    )
    assert result is None


def test_zero_or_negative_price_no_clamp() -> None:
    """Defensive: garbage price input returns None (caller's
    downstream logic handles missing-price separately)."""
    assert clamp_inflated_scenarios(100, 800, 60, 0) is None
    assert clamp_inflated_scenarios(100, 800, 60, -5) is None
    assert clamp_inflated_scenarios(100, 800, 60, None) is None


def test_zero_or_none_bull_no_clamp() -> None:
    """If bull was not produced (engine returned 0 / None) the gate
    has no signal to act on — return None so caller proceeds with
    whatever rescue path the missing bull triggers elsewhere."""
    assert clamp_inflated_scenarios(100, 0, 60, 50) is None
    assert clamp_inflated_scenarios(100, None, 60, 50) is None


def test_custom_multiplier_override() -> None:
    """Caller can pass a tighter multiplier (e.g. for unit tests).
    Verifies the parameter is honoured."""
    result = clamp_inflated_scenarios(
        base_fv=200.0, bull_fv=400.0, bear_fv=60.0, current_price=100.0,
        multiplier=3.0,
    )
    assert result is not None
    _, bull_c, _, _ = result
    assert bull_c == 300.0  # 3 * 100


# ─────────────────────────────────────────────────────────────────
# Fix 2: Day-111c bull-side threshold tune (50 → 40)
# ─────────────────────────────────────────────────────────────────

def _gate(
    verdict: str,
    mos_pct: float,
    model_confidence: int | None,
    *,
    data_quality: int | None = 65,
    valuation_stability: int | None = 65,
) -> tuple[str, list[str]]:
    """Mirror of the helper in test_day111c_bull_undervalued_bypass."""
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
        valuation_model="dcf",
    )


def test_bull_threshold_lowered_to_40() -> None:
    """Phase B.2 pin: BULL_UNDERVALUED_BYPASS_MOS lowered from 50 to 40."""
    assert BULL_UNDERVALUED_BYPASS_MOS == 40.0


def test_hdfcbank_shape_flips_to_undervalued_post_b2() -> None:
    """HDFCBANK live (2026-05-23): mos=+43.1%, confidence=90.
    Pre-B.2 (threshold=50): "fairly_valued" — credibility-breaking at
    a Wide-moat name with +43% MoS. Post-B.2 (threshold=40): bypass
    fires → "undervalued"."""
    verdict, issues = _gate(
        "undervalued", mos_pct=43.1, model_confidence=90, data_quality=65,
    )
    assert verdict == "undervalued"
    assert any("Bull-side bypass" in i for i in issues)


def test_just_below_40_still_fairly_valued() -> None:
    """mos=+39.9% (one tenth below the new boundary) stays at
    'fairly_valued' — the threshold is respected, not eroded."""
    verdict, _ = _gate(
        "undervalued", mos_pct=39.9, model_confidence=90, data_quality=65,
    )
    assert verdict == "fairly_valued"


def test_exactly_40_fires_bypass() -> None:
    """mos=+40.0% exactly clears the >= boundary."""
    verdict, _ = _gate(
        "undervalued", mos_pct=40.0, model_confidence=90, data_quality=65,
    )
    assert verdict == "undervalued"


def test_mos85_notably_intensity_unchanged() -> None:
    """The 'notably_undervalued' intensity_hint boundary (80%) is
    not touched by B.2. mos=+85% still surfaces the deeper hint."""
    _, issues = _gate(
        "notably_undervalued", mos_pct=85.0, model_confidence=50,
    )
    assert any("intensity_hint='notably_undervalued'" in i for i in issues)


def test_bull_conf_floor_still_30() -> None:
    """Asymmetry pin: B.2 lowered the MoS threshold but kept the
    confidence floor at 30 (still lower than the bear-side 40)."""
    assert BULL_UNDERVALUED_BYPASS_CONFIDENCE == 30


def test_bull_notably_threshold_pin() -> None:
    """B.2 did NOT change the notably_undervalued intensity boundary."""
    assert BULL_NOTABLY_UNDERVALUED_MOS == 80.0


def test_below_conf_floor_no_bypass_post_b2() -> None:
    """Even at +85% MoS, conf=25 (below the 30 floor) does NOT
    trigger the bypass — the floor is still enforced after B.2."""
    verdict, _ = _gate(
        "notably_undervalued", mos_pct=85.0, model_confidence=25,
    )
    assert verdict == "fairly_valued"
