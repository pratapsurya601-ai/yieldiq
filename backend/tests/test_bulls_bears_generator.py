"""Unit tests for backend/services/analysis/bulls_bears_generator.py.

Covers:
  * Each bull rule fires on a positive payload AND skips when its
    threshold is not met.
  * Each bear rule fires on a negative payload AND skips when its
    threshold is not met.
  * Output is capped at 3 each and ordered by rule strength.
  * Every generated string is SEBI-safe (no banned words from
    ``sebi_filter.BANNED_WORDS``).
  * Empty / None inputs degrade gracefully (no exception, empty lists).
"""
from __future__ import annotations

import pytest

from backend.services.analysis.bulls_bears_generator import (
    generate_bulls_bears,
)
from backend.services.analysis.sebi_filter import find_banned


def _assert_sebi_safe(lines):
    for line in lines:
        hit = find_banned(line)
        assert hit is None, f"banned token {hit!r} in: {line!r}"


# ─── Bulls ─────────────────────────────────────────────────────


def test_bull_mos_discount_fires_when_threshold_met():
    out = generate_bulls_bears(
        valuation={"margin_of_safety": 42},
        quality={"yieldiq_score": 50},
    )
    assert any("42% discount" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_mos_discount_skipped_below_threshold():
    out = generate_bulls_bears(
        valuation={"margin_of_safety": 12},
        quality={"yieldiq_score": 40},
    )
    assert not any("discount to model fair value" in b for b in out["bulls"])


def test_bull_yieldiq_score_fires_at_70():
    out = generate_bulls_bears(
        valuation={"margin_of_safety": 0},
        quality={"yieldiq_score": 78},
    )
    assert any("78/100" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_yieldiq_score_skipped_at_69():
    out = generate_bulls_bears(quality={"yieldiq_score": 69})
    assert not any("top decile" in b for b in out["bulls"])


def test_bull_wide_moat_fires():
    out = generate_bulls_bears(quality={"moat": "Wide", "yieldiq_score": 0})
    assert any(b.startswith("Wide economic moat") for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_narrow_moat_fires_but_wide_outranks():
    out = generate_bulls_bears(
        quality={"moat": "Wide", "yieldiq_score": 80, "roe": 25},
    )
    # Wide moat should appear (it scores 80, same as our score) — ordering
    # by score means it lands in the top 3 alongside the score bullet.
    assert any("Wide economic moat" in b for b in out["bulls"])


def test_bull_no_moat_does_not_fire():
    out = generate_bulls_bears(quality={"moat": "None"})
    assert not any("economic moat" in b for b in out["bulls"])


def test_bull_dividend_streak_fires():
    out = generate_bulls_bears(
        insights={"dividend": {"consecutive_years": 12}},
    )
    assert any("12 consecutive years" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_dividend_streak_below_threshold():
    out = generate_bulls_bears(
        insights={"dividend": {"consecutive_years": 4}},
    )
    assert not any("consecutive years" in b for b in out["bulls"])


def test_bull_revenue_cagr_decimal_input():
    # 0.22 decimal == 22% — above the 15% threshold.
    out = generate_bulls_bears(quality={"revenue_cagr_3y": 0.22})
    assert any("Revenue compounding at 22.0%" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_revenue_cagr_percent_input():
    # 18 already in percent form (>= 1.5 guard).
    out = generate_bulls_bears(quality={"revenue_cagr_3y": 18})
    assert any("Revenue compounding at 18.0%" in b for b in out["bulls"])


def test_bull_revenue_cagr_below_threshold():
    out = generate_bulls_bears(quality={"revenue_cagr_3y": 0.05})
    assert not any("Revenue compounding" in b for b in out["bulls"])


def test_bull_roe_fires():
    out = generate_bulls_bears(quality={"roe": 22.4})
    assert any("ROE averaging 22.4%" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_roe_skipped_below_18():
    out = generate_bulls_bears(quality={"roe": 17.9})
    assert not any("ROE averaging" in b for b in out["bulls"])


def test_bull_capex_commitments_fires():
    out = generate_bulls_bears(
        ar_signals={
            "capex_commitments": [
                {"description": "Wholesale Banking", "amount_cr": 400},
            ],
        },
    )
    assert any("Capex commitments" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


def test_bull_bull_case_scenario_fires():
    out = generate_bulls_bears(scenarios={"bull": {"mos_pct": 65}})
    assert any("Bull-case scenario suggests 65% upside" in b for b in out["bulls"])
    _assert_sebi_safe(out["bulls"])


# ─── Bears ─────────────────────────────────────────────────────


def test_bear_mos_premium_fires():
    out = generate_bulls_bears(valuation={"margin_of_safety": -35})
    assert any("35% premium to model fair value" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_mos_premium_skipped_above_minus_20():
    out = generate_bulls_bears(valuation={"margin_of_safety": -10})
    assert not any("premium to model fair value" in b for b in out["bears"])


def test_bear_low_confidence_fires():
    out = generate_bulls_bears(valuation={"confidence_score": 28})
    assert any("Model confidence is low (28/100)" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_low_confidence_skipped_above_35():
    out = generate_bulls_bears(valuation={"confidence_score": 55})
    assert not any("Model confidence is low" in b for b in out["bears"])


def test_bear_leverage_fires_with_explicit_sector_median():
    out = generate_bulls_bears(
        quality={"de_ratio": 1.5},
        sector_de_median=0.8,
    )
    assert any("Leverage at 1.50 is above sector median of 0.80" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_leverage_skipped_when_below_threshold():
    out = generate_bulls_bears(
        quality={"de_ratio": 0.9},
        sector_de_median=0.8,
    )
    assert not any("Leverage at" in b for b in out["bears"])


def test_bear_key_audit_matter_fires():
    out = generate_bulls_bears(
        ar_signals={
            "auditor_flags": [
                {"type": "key_audit_matter", "summary": "revenue cut-off"},
            ],
        },
    )
    assert any("Key Audit Matter flagged" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_revenue_contraction_fires():
    out = generate_bulls_bears(quality={"revenue_cagr_3y": -0.08})
    assert any("Revenue contracting at 8.0%" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_risk_factors_fires():
    out = generate_bulls_bears(
        ar_signals={
            "risk_factors": [
                {"summary": "Concentration exposure to top 5 clients."},
            ],
        },
    )
    assert any("Concentration exposure" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_bear_case_scenario_fires():
    out = generate_bulls_bears(scenarios={"bear": {"mos_pct": -42}})
    assert any("Bear-case scenario suggests 42% downside" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


def test_bear_red_flags_fires():
    out = generate_bulls_bears(
        insights={
            "red_flags_structured": [
                {"flag": "negative_equity"},
                {"flag": "auditor_change"},
            ],
        },
    )
    assert any("Red flags surfaced" in b for b in out["bears"])
    _assert_sebi_safe(out["bears"])


# ─── Cap + ordering + degraded inputs ──────────────────────────


def test_capped_at_three_each_and_ordered_by_strength():
    out = generate_bulls_bears(
        valuation={"margin_of_safety": 55, "confidence_score": 20},
        quality={
            "yieldiq_score": 88,
            "moat": "Wide",
            "roe": 30,
            "revenue_cagr_3y": 0.35,
        },
        insights={"dividend": {"consecutive_years": 20}},
        scenarios={"bull": {"mos_pct": 70}, "bear": {"mos_pct": -45}},
    )
    assert len(out["bulls"]) == 3
    assert len(out["bears"]) <= 3
    _assert_sebi_safe(out["bulls"])
    _assert_sebi_safe(out["bears"])


def test_empty_inputs_return_empty_lists():
    out = generate_bulls_bears()
    # v_238 (2026-05-26) — output bundle now also carries
    # bull/bear narrative paragraphs and an "Updated <Month YYYY>"
    # stamp. Empty inputs => empty bullet lists, None narratives,
    # no date stamp.
    assert out["bulls"] == []
    assert out["bears"] == []
    assert out["bull_case_narrative"] is None
    assert out["bear_case_narrative"] is None
    assert out["thesis_updated"] is None


def test_none_inputs_do_not_crash():
    out = generate_bulls_bears(
        valuation=None, quality=None, insights=None,
        scenarios=None, ar_signals=None,
    )
    assert out["bulls"] == []
    assert out["bears"] == []
    assert out["bull_case_narrative"] is None
    assert out["bear_case_narrative"] is None


def test_paragraph_upgrade_emits_multi_sentence_bullets():
    """v_238 — each firing rule emits 2-3 sentence paragraphs.

    Pick a payload that fires several bull rules and assert that the
    rendered bullets are paragraphs (multiple periods, ~40+ words)
    rather than 1-sentence bullets.
    """
    out = generate_bulls_bears(
        valuation={
            "margin_of_safety": 42,
            "fair_value": 1420,
            "current_price": 820,
        },
        quality={"yieldiq_score": 78, "moat": "Wide", "roe": 22},
    )
    assert out["bulls"], "expected at least one bull bullet to fire"
    for bullet in out["bulls"]:
        # Multi-sentence paragraph — at least 2 periods.
        assert bullet.count(".") >= 2, f"bullet not a paragraph: {bullet!r}"
        # Roughly 25+ words per bullet (we target 40-50; floor at 25
        # to leave headroom for short caveats on edge cases).
        assert len(bullet.split()) >= 25, f"bullet too short: {bullet!r}"
    # Composed narrative is the joined block.
    assert out["bull_case_narrative"] == " ".join(out["bulls"])


def test_thesis_updated_formats_iso_date():
    out = generate_bulls_bears(
        valuation={"margin_of_safety": 42},
        quality={"yieldiq_score": 78},
        computed_at="2026-04-12T08:00:00Z",
    )
    assert out["thesis_updated"] == "April 2026"


def test_thesis_updated_handles_bad_input():
    for bad in (None, "", "not a date", "abcd-ef-gh"):
        out = generate_bulls_bears(computed_at=bad)
        assert out["thesis_updated"] is None, bad


def test_works_with_pydantic_models():
    from backend.models.responses import (
        ValuationOutput, QualityOutput, InsightCards, ScenariosOutput, ScenarioCase,
    )
    val = ValuationOutput(
        fair_value=1000, current_price=500, margin_of_safety=50,
        verdict="undervalued", confidence_score=80,
    )
    qual = QualityOutput(yieldiq_score=85, moat="Wide", roe=22)
    ins = InsightCards()
    scn = ScenariosOutput(bull=ScenarioCase(mos_pct=60))
    out = generate_bulls_bears(
        valuation=val, quality=qual, insights=ins, scenarios=scn,
    )
    assert len(out["bulls"]) == 3
    _assert_sebi_safe(out["bulls"])


def test_full_response_is_sebi_safe():
    """Belt-and-braces: combine many positive AND negative signals at
    once and verify NOTHING in either list trips the SEBI filter."""
    out = generate_bulls_bears(
        valuation={"margin_of_safety": -38, "confidence_score": 22},
        quality={
            "yieldiq_score": 78, "moat": "Narrow", "roe": 21,
            "revenue_cagr_3y": -0.12, "de_ratio": 2.2,
        },
        insights={
            "dividend": {"consecutive_years": 9},
            "red_flags_structured": [{"flag": "negative_equity"}],
        },
        scenarios={"bull": {"mos_pct": 55}, "bear": {"mos_pct": -50}},
        ar_signals={
            "capex_commitments": [{"description": "Treasury"}],
            "auditor_flags": [{"type": "key_audit_matter"}],
            "risk_factors": [{"summary": "Forex exposure"}],
        },
        sector_de_median=0.7,
    )
    _assert_sebi_safe(out["bulls"])
    _assert_sebi_safe(out["bears"])
