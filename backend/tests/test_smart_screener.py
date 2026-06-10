# backend/tests/test_smart_screener.py
# Smart Screener (composite criteria) — unit tests.
#
# We test the pure functions in backend.routers.screener directly so
# the suite doesn't need a live Postgres or analysis_cache. The two
# concerns under test:
#
#   1. _row_matches honours every (field, op, value) combo correctly,
#      including the multi-path lookups for dividend_streak_years and
#      sbc_intensity_label.
#   2. _validate_criteria rejects malformed input with HTTP 400 so the
#      handler never reaches the universe scan with a bad criterion.
#
# Both axes were the bug surface in the legacy /screener DSL endpoint
# (filter wired to a non-existent column → empty result set with no
# diagnostic). The same shape of bug here would silently match "0
# names" — these tests pin both that and the inverse (matching the
# wrong rows).
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
from fastapi import HTTPException

from backend.routers.screener import (
    SMART_FIELDS,
    SmartCriterion,
    _coerce_number,
    _match_numeric,
    _match_string,
    _read_path,
    _row_matches,
    _sort_matches,
    _summary_stats,
    _summarize_match,
    _validate_criteria,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

FMCG_PAYLOAD = {
    "ticker": "ITC.NS",
    "sector": "FMCG",
    "valuation": {
        "margin_of_safety": 22.5,
        "fair_value_ratio": 1.29,
        "pe_ratio": 18.4,
        "pb_ratio": 5.1,
        "verdict": "undervalued",
        "sbc_intensity_label": "negligible",
    },
    "quality": {
        "yieldiq_score": 71,
        "roe": 26.1,
        "roce": 30.4,
        "de_ratio": 0.05,
        "moat": "Wide",
        "revenue_cagr_3y": 0.11,
        # dividend streak NOT mirrored here — should fall back to
        # the dividend block below.
    },
    "dividend": {"consecutive_years": 12},
}

IT_PAYLOAD = {
    "ticker": "TCS.NS",
    "sector": "Technology",
    "valuation": {
        "margin_of_safety": 5.0,
        "fair_value_ratio": 1.05,
        "pe_ratio": 28.0,
        "pb_ratio": 11.0,
        "verdict": "fair",
        "sbc_intensity_label": "moderate",
    },
    "quality": {
        "yieldiq_score": 78,
        "roe": 42.0,
        "roce": 55.0,
        "de_ratio": 0.0,
        "moat": "Wide",
        "revenue_cagr_3y": 0.07,
        "dividend_streak_years": 18,
    },
}

PLATFORM_PAYLOAD = {
    "ticker": "PAYTM.NS",
    "sector": "Fintech",
    "valuation": {
        "margin_of_safety": -15.0,
        "fair_value_ratio": 0.85,
        "pe_ratio": None,
        "pb_ratio": 3.0,
        "verdict": "overvalued",
        "sbc_intensity_label": "heavy",
    },
    "quality": {
        "yieldiq_score": 38,
        "roe": -10.0,
        "moat": "None",
    },
}


# ─────────────────────────────────────────────────────────────────
# _read_path — multi-path fallbacks
# ─────────────────────────────────────────────────────────────────

def test_read_path_single_dotted():
    assert _read_path(FMCG_PAYLOAD, "valuation.margin_of_safety") == 22.5


def test_read_path_missing_segment_returns_none():
    assert _read_path(FMCG_PAYLOAD, "valuation.nonexistent") is None
    assert _read_path(FMCG_PAYLOAD, "nonexistent.anything") is None


def test_read_path_falls_back_through_list():
    # FMCG payload has consecutive_years but not quality.dividend_streak_years
    paths = ["dividend.consecutive_years", "quality.dividend_streak_years"]
    assert _read_path(FMCG_PAYLOAD, paths) == 12
    # IT payload has the mirror; resolve order should still walk the
    # first non-null path.
    assert _read_path(IT_PAYLOAD, paths) == 18


def test_read_path_none_payload():
    assert _read_path(None, "anything") is None  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# _match_numeric / _match_string
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "actual,op,target,expected",
    [
        (22.5, ">", 20.0, True),
        (22.5, ">=", 22.5, True),
        (22.5, "<", 20.0, False),
        (22.5, "<=", 22.5, True),
        (22.5, "=", 22.5, True),
        (22.5, "!=", 22.5, False),
        (None, ">", 20.0, False),  # None always fails closed
    ],
)
def test_match_numeric(actual, op, target, expected):
    assert _match_numeric(actual, op, target) is expected


def test_match_string_equality_case_insensitive():
    assert _match_string("Wide", "=", "wide") is True
    assert _match_string("Wide", "!=", "narrow") is True
    assert _match_string(None, "=", "wide") is False


def test_match_string_in_comma_list():
    assert _match_string("wide", "in", "wide,narrow") is True
    assert _match_string("wide", "in", ["wide", "narrow"]) is True
    assert _match_string("none", "in", "wide,narrow") is False
    assert _match_string("none", "not_in", "wide,narrow") is True


# ─────────────────────────────────────────────────────────────────
# _row_matches — composite-criteria semantics (logical AND)
# ─────────────────────────────────────────────────────────────────

def test_row_matches_composite_fmcg_brief():
    """Brief example: FMCG names with MoS > 20%, ROE > 15%, dividend
    streak > 5 years, low SBC dilution."""
    crits = [
        SmartCriterion(field="mos", op=">", value=20),
        SmartCriterion(field="roe", op=">", value=15),
        SmartCriterion(field="dividend_streak_years", op=">", value=5),
        SmartCriterion(field="sbc_intensity_label", op="=", value="negligible"),
    ]
    assert _row_matches(FMCG_PAYLOAD, "FMCG", crits) is True


def test_row_matches_rejects_on_sector_mismatch():
    crits = [SmartCriterion(field="mos", op=">", value=20)]
    # Asking for FMCG but row is Technology — should not match.
    assert _row_matches(IT_PAYLOAD, "FMCG", crits) is False


def test_row_matches_rejects_on_single_failed_criterion():
    crits = [
        SmartCriterion(field="mos", op=">", value=20),
        SmartCriterion(field="sbc_intensity_label", op="=", value="negligible"),
    ]
    # PAYTM has heavy SBC; even though MoS isn't the failing axis,
    # the AND semantics should reject the row.
    assert _row_matches(PLATFORM_PAYLOAD, None, crits) is False


def test_row_matches_unknown_field_fails_closed():
    crits = [SmartCriterion(field="not_a_real_field", op=">", value=0)]
    assert _row_matches(FMCG_PAYLOAD, None, crits) is False


def test_row_matches_handles_missing_streak_mirror():
    # FMCG payload only carries dividend.consecutive_years (not the
    # quality.dividend_streak_years mirror). _read_path multi-path
    # fallback should still surface the 12-year streak.
    crits = [SmartCriterion(field="dividend_streak_years", op=">", value=5)]
    assert _row_matches(FMCG_PAYLOAD, None, crits) is True


def test_row_matches_moat_string_in_op():
    crits = [SmartCriterion(field="moat", op="in", value="Wide,Narrow")]
    assert _row_matches(FMCG_PAYLOAD, None, crits) is True
    assert _row_matches(PLATFORM_PAYLOAD, None, crits) is False


# ─────────────────────────────────────────────────────────────────
# _validate_criteria — 400-on-malformed contract
# ─────────────────────────────────────────────────────────────────

def test_validate_rejects_unknown_field():
    with pytest.raises(HTTPException) as exc:
        _validate_criteria([SmartCriterion(field="bogus", op=">", value=1)])
    assert exc.value.status_code == 400
    assert "unknown field" in str(exc.value.detail)


def test_validate_rejects_op_type_mismatch():
    # mos is numeric — `in` is a string-only op.
    with pytest.raises(HTTPException) as exc:
        _validate_criteria([SmartCriterion(field="mos", op="in", value=20)])
    assert exc.value.status_code == 400


def test_validate_rejects_non_numeric_for_numeric_field():
    with pytest.raises(HTTPException) as exc:
        _validate_criteria([SmartCriterion(field="mos", op=">", value="not-a-number")])
    assert exc.value.status_code == 400


def test_validate_accepts_string_value_for_numeric_field_when_castable():
    # The pydantic model takes Any for value — "20" should cast fine.
    _validate_criteria([SmartCriterion(field="mos", op=">", value="20")])


def test_validate_accepts_string_field_with_string_op():
    _validate_criteria(
        [SmartCriterion(field="moat", op="in", value="Wide,Narrow")]
    )


# ─────────────────────────────────────────────────────────────────
# _summarize_match / _sort_matches / _summary_stats
# ─────────────────────────────────────────────────────────────────

def test_summarize_match_projects_fields():
    out = _summarize_match("ITC", FMCG_PAYLOAD)
    assert out["ticker"] == "ITC.NS"  # bare → .NS suffixed
    assert out["mos"] == 22.5
    assert out["sector"] == "FMCG"
    assert out["fair_value_ratio"] == 1.29


def test_sort_matches_by_mos_desc_by_default():
    rows = [
        {"ticker": "A.NS", "mos": 10.0, "score": 60, "fair_value_ratio": 1.0, "pe_ratio": None, "roe": None, "sector": None, "verdict": None},
        {"ticker": "B.NS", "mos": 30.0, "score": 50, "fair_value_ratio": 1.0, "pe_ratio": None, "roe": None, "sector": None, "verdict": None},
        {"ticker": "C.NS", "mos": None, "score": 90, "fair_value_ratio": 1.0, "pe_ratio": None, "roe": None, "sector": None, "verdict": None},
    ]
    sorted_rows = _sort_matches(list(rows), "mos")
    # None-mos rows sink to the bottom even with desc=True; that
    # invariant is what _sort_matches' key tuple buys us.
    assert sorted_rows[0]["ticker"] == "B.NS"
    assert sorted_rows[1]["ticker"] == "A.NS"
    assert sorted_rows[2]["ticker"] == "C.NS"


def test_summary_stats_medians():
    rows = [
        {"mos": 10.0, "score": 60.0, "roe": 12.0},
        {"mos": 20.0, "score": 70.0, "roe": 18.0},
        {"mos": 30.0, "score": 80.0, "roe": 24.0},
    ]
    stats = _summary_stats(rows)
    assert stats["count"] == 3
    assert stats["median_mos"] == 20.0
    assert stats["median_score"] == 70.0
    assert stats["median_roe"] == 18.0


def test_summary_stats_handles_all_null_field():
    rows = [{"mos": None, "score": None, "roe": None}]
    stats = _summary_stats(rows)
    assert stats["count"] == 1
    assert stats["median_mos"] is None
    assert stats["median_score"] is None


# ─────────────────────────────────────────────────────────────────
# SMART_FIELDS contract — must cover every field the brief mentions
# ─────────────────────────────────────────────────────────────────

def test_smart_fields_cover_brief_set():
    """Pin the public field contract. Brief calls for: MoS,
    fair_value_ratio, ROE, ROCE, P/E, P/B, dividend_streak_years,
    debt_to_equity, sbc_intensity_label. Test breaks if any is
    silently dropped."""
    required = {
        "mos",
        "fair_value_ratio",
        "roe",
        "roce",
        "pe_ratio",
        "pb_ratio",
        "dividend_streak_years",
        "debt_to_equity",
        "sbc_intensity_label",
    }
    missing = required - set(SMART_FIELDS.keys())
    assert not missing, f"Smart screener missing fields: {missing}"


# ─────────────────────────────────────────────────────────────────
# _coerce_number — forgiving wire format
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        (12, 12.0),
        (12.5, 12.5),
        ("12.5", 12.5),
        ("12", 12.0),
        (None, None),
        ("not-a-number", None),
        ([], None),
    ],
)
def test_coerce_number(raw, expected):
    assert _coerce_number(raw) == expected
