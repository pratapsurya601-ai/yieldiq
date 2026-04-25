# backend/tests/test_valuation_precision_lock.py
# ═══════════════════════════════════════════════════════════════
# Regression lock for the 2026-04-25 DRREDDY public-vs-authed
# precision drift (PR follow-up to #70).
#
# Symptom on PR #70 canary:
#     DRREDDY.fair_value: public=2038.39 authed=2038.73
#     DRREDDY.bear_case:  public=1209.68 authed=1209.8671239771572
#     DRREDDY.base_case:  public=2038.39 authed=2038.73
#     DRREDDY.bull_case:  public=2798.39 authed=2798.8726118621125
#
# Root cause: the authed `/api/v1/analysis/{ticker}` endpoint
# returns `AnalysisResponse` directly, so Pydantic streams raw
# 64-bit floats. The public `/api/v1/public/analysis/{ticker}`
# endpoint passes through `_extract_analysis_summary` which
# `round(x, 2)`s every scalar. The two endpoints disagreed on
# precision, which the canary's strict diff flagged as a
# correctness violation.
#
# Fix: `field_serializer`s on `ValuationOutput` round monetary
# fields to 2 decimals and MoS fields to 1 decimal at the JSON
# boundary. Internal arithmetic still uses full precision.
#
# These tests assert that:
#   1. `model_dump()` of a ValuationOutput rounds money to 2dp.
#   2. MoS fields round to 1dp.
#   3. The drifty DRREDDY-shaped values produce identical output
#      to what the public endpoint's `_extract_analysis_summary`
#      already emits.
# ═══════════════════════════════════════════════════════════════
from backend.models.responses import ValuationOutput


def _drreddy_shaped() -> ValuationOutput:
    """Build a ValuationOutput with the exact float values that
    triggered the PR #70 canary violation."""
    return ValuationOutput(
        fair_value=2038.7300000001,
        current_price=1224.55,
        margin_of_safety=66.6987654321,
        verdict="undervalued",
        bear_case=1209.8671239771572,
        base_case=2038.7300000001,
        bull_case=2798.8726118621125,
        wacc=0.098,
        terminal_growth=0.04,
        fcf_growth_rate=0.07,
        confidence_score=70,
        margin_of_safety_display=66.6987654321,
    )


def test_money_fields_round_to_two_decimals():
    v = _drreddy_shaped()
    dumped = v.model_dump()
    assert dumped["fair_value"] == 2038.73
    assert dumped["current_price"] == 1224.55
    assert dumped["bear_case"] == 1209.87
    assert dumped["base_case"] == 2038.73
    assert dumped["bull_case"] == 2798.87


def test_mos_fields_round_to_one_decimal():
    v = _drreddy_shaped()
    dumped = v.model_dump()
    assert dumped["margin_of_safety"] == 66.7
    assert dumped["margin_of_safety_display"] == 66.7


def test_internal_attributes_keep_full_precision():
    """field_serializer only fires at dump-time. Direct attribute
    access must still return the raw float so internal callers
    (clamp logic, score formulas) operate on the precise value."""
    v = _drreddy_shaped()
    assert v.bear_case == 1209.8671239771572
    assert v.bull_case == 2798.8726118621125


def test_public_authed_serialization_parity():
    """Lock the contract: model_dump() output for monetary fields
    matches what `_extract_analysis_summary` produces from the same
    object. Without this, the public/authed canary diff drifts."""
    v = _drreddy_shaped()
    dumped = v.model_dump()
    # Mirror what backend/routers/public.py:_extract_analysis_summary does.
    public_view = {
        "fair_value": round(v.fair_value, 2),
        "bear_case": round(v.bear_case, 2),
        "base_case": round(v.base_case, 2),
        "bull_case": round(v.bull_case, 2),
        "current_price": round(v.current_price, 2),
        "mos": round(v.margin_of_safety, 1),
    }
    assert dumped["fair_value"] == public_view["fair_value"]
    assert dumped["bear_case"] == public_view["bear_case"]
    assert dumped["base_case"] == public_view["base_case"]
    assert dumped["bull_case"] == public_view["bull_case"]
    assert dumped["current_price"] == public_view["current_price"]
    assert dumped["margin_of_safety"] == public_view["mos"]


def test_none_safe_for_optional_floats():
    """Defensive: ValuationOutput has no Optional float fields today,
    but the helper must not crash if a future schema change makes
    one Optional."""
    from backend.models.responses import _round2
    assert _round2(None) is None
    assert _round2(1.234567) == 1.23
    assert _round2(0) == 0.0
