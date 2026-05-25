"""Unit tests for the Portfolio Updates Feed template engine (P0 #1).

Pure-function tests — no DB, no network, no LLM. Each test asserts:
  - the headline/detail are non-empty strings
  - the headline matches the spec pattern
  - SEBI-forbidden words (buy/sell/hold/recommend/target) never appear
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from backend.services.updates_feed.templates import (
    CATEGORIES,
    render,
    render_dividends,
    render_earnings,
    render_insider_trading,
    render_intrinsic_updates,
    render_other,
    render_risk_legal,
    render_valuations,
)


SEBI_FORBIDDEN = ("buy", "sell", "hold", "recommend", "target", "buy/sell")


def _assert_safe(out: dict) -> None:
    """Every rendered headline+detail must be a non-empty string and
    must NOT contain SEBI-forbidden advisory words (case-insensitive)."""
    assert isinstance(out, dict)
    assert isinstance(out.get("headline"), str) and out["headline"].strip()
    assert isinstance(out.get("detail"), str) and out["detail"].strip()
    blob = (out["headline"] + " " + out["detail"]).lower()
    for word in SEBI_FORBIDDEN:
        # Match as a whole word — "buying" should be allowed if it ever
        # appears, but "buy" alone must not.
        assert (
            f" {word} " not in f" {blob} "
            and not blob.startswith(f"{word} ")
            and not blob.endswith(f" {word}")
        ), f"forbidden word '{word}' in: {blob!r}"


def test_categories_exposed():
    assert "earnings" in CATEGORIES
    assert "valuations" in CATEGORIES
    assert "intrinsic_updates" in CATEGORIES
    assert "dividends" in CATEGORIES
    assert "insider_trading" in CATEGORIES
    assert "risk_legal" in CATEGORIES
    assert "other" in CATEGORIES


def test_earnings_beat_template():
    out = render_earnings({
        "period": "Q4 FY25",
        "prior_period": "Q4 FY24",
        "eps": 24.5,
        "eps_prior": 19.0,
        "revenue": 18_500_00_00_000.0,  # ₹18,500 Cr
        "revenue_prior": 16_000_00_00_000.0,
    })
    _assert_safe(out)
    assert "Q4 FY25" in out["headline"]
    assert "ahead of" in out["headline"]
    assert "EPS" in out["detail"]
    assert "Revenue" in out["detail"]


def test_earnings_miss_template():
    out = render_earnings({
        "period": "Q1 FY26",
        "prior_period": "Q1 FY25",
        "eps": 10.0,
        "eps_prior": 15.0,
    })
    _assert_safe(out)
    assert "below" in out["headline"]


def test_earnings_handles_missing_fields():
    out = render_earnings({})
    _assert_safe(out)


def test_valuations_template():
    out = render_valuations({"old_fv": 1500.0, "new_fv": 1650.0, "reason": "WACC refresh"})
    _assert_safe(out)
    assert "→" in out["headline"]
    assert "+10.0%" in out["headline"]


def test_valuations_downgrade_pct():
    out = render_valuations({"old_fv": 2000.0, "new_fv": 1600.0})
    _assert_safe(out)
    assert "-20.0%" in out["headline"]


def test_intrinsic_updates_template():
    out = render_intrinsic_updates({"old_fv": 1000, "new_fv": 1100, "reason": "DCF refresh"})
    _assert_safe(out)
    assert out["headline"].startswith("Intrinsic value updated:")


def test_dividends_template():
    out = render_dividends({
        "period": "FY25 Final",
        "amount": 19.5,
        "ex_date": date(2026, 6, 14),
    })
    _assert_safe(out)
    assert "FY25 Final" in out["headline"]
    assert "ex-date" in out["headline"]


def test_insider_buy_template():
    out = render_insider_trading({
        "acquirer_name": "Anand Mahindra",
        "acquirer_category": "Promoter",
        "buy_qty": 12_500,
        "transaction_value_cr": 3.45,
        "filing_date": date(2026, 5, 22),
    })
    _assert_safe(out)
    assert "Anand Mahindra" in out["headline"]
    # The headline uses the SEBI-safe verb "acquired" (not "bought").
    assert "acquired" in out["headline"]
    assert "12,500" in out["headline"]


def test_insider_sell_uses_disposed_of_verb():
    out = render_insider_trading({
        "acquirer_name": "An Insider",
        "sell_qty": 5_000,
        "filing_date": date(2026, 5, 22),
    })
    _assert_safe(out)
    # Must NOT include the literal "sold" / "sell" verb — SEBI safety.
    assert "disposed of" in out["headline"]


def test_risk_legal_template():
    out = render_risk_legal({
        "flag": "Auditor change",
        "description": "Statutory auditor was changed mid-cycle.",
        "as_of": datetime(2026, 5, 1, tzinfo=timezone.utc),
    })
    _assert_safe(out)
    assert "Risk flag noted" in out["headline"]


def test_other_template_falls_back_safely():
    out = render_other({})
    _assert_safe(out)


def test_render_dispatch_unknown_category_falls_back_to_other():
    out = render("not_a_real_category", {"headline": "x", "detail": "y"})
    _assert_safe(out)


@pytest.mark.parametrize("cat", list(CATEGORIES))
def test_render_dispatch_all_categories_smoke(cat):
    out = render(cat, {
        "period": "Q4 FY25",
        "prior_period": "Q3 FY25",
        "eps": 1.0,
        "eps_prior": 1.0,
        "old_fv": 100,
        "new_fv": 110,
        "amount": 5.0,
        "ex_date": date(2026, 1, 1),
        "acquirer_name": "Name",
        "buy_qty": 1,
        "filing_date": date(2026, 1, 1),
        "flag": "Flag",
        "description": "desc",
    })
    _assert_safe(out)
