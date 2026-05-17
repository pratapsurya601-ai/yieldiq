"""Tests for the manual promoter-holding override layer.

These cover the four ticker classes documented in the override JSON:
  * foreign_promoter  — ITC (BAT), HUL (Unilever)
  * no_promoter_bank  — HDFCBANK, ICICIBANK, AXISBANK
  * govt_promoter     — SBIN
  * unaffected stocks — TCS / RELIANCE / a made-up ticker pass through

The override layer is purely additive: it must never raise and it must
never invent values for tickers not present in the JSON.
"""
from __future__ import annotations

import pytest

from data_pipeline.sources.promoter_overrides import (
    apply_promoter_override,
    get_promoter_override,
    is_no_promoter_bank,
    list_overrides,
)


@pytest.mark.parametrize("ticker", ["ITC", "ITC.NS", "itc.bo"])
def test_itc_foreign_promoter(ticker):
    o = get_promoter_override(ticker)
    assert o is not None, "ITC must have an override (BAT economic promoter)"
    assert o["type"] == "foreign_promoter"
    assert o["promoter_pct"] == pytest.approx(24.2, abs=0.1)
    assert "BAT" in (o.get("entity") or "") or "British" in (o.get("entity") or "")


def test_hindunilvr_foreign_promoter():
    o = get_promoter_override("HINDUNILVR")
    assert o is not None
    assert o["type"] == "foreign_promoter"
    assert o["promoter_pct"] == pytest.approx(61.9, abs=0.1)
    assert "Unilever" in (o.get("entity") or "")


@pytest.mark.parametrize(
    "ticker", ["HDFCBANK", "ICICIBANK.NS", "AXISBANK", "FEDERALBNK"],
)
def test_private_banks_no_promoter(ticker):
    o = get_promoter_override(ticker)
    assert o is not None, f"{ticker} must be classified as no_promoter_bank"
    assert o["type"] == "no_promoter_bank"
    assert is_no_promoter_bank(ticker) is True
    # apply_promoter_override forces pct to None so the UI doesn't show
    # "0.0% — Low stake" for banks that legitimately have no promoter.
    merged = apply_promoter_override(ticker, {"promoter_pct": 0.0})
    assert merged["promoter_pct"] is None
    assert merged["promoter_holding_type"] == "no_promoter_bank"


def test_sbin_govt_promoter():
    o = get_promoter_override("SBIN")
    assert o is not None
    assert o["type"] == "govt_promoter"
    assert o["promoter_pct"] is not None and o["promoter_pct"] > 50


def test_unaffected_stocks_pass_through():
    # TCS / RELIANCE / PARADEEP are correct in the NSE feed and have
    # no override — the loader must return None and apply_* must leave
    # the input dict untouched.
    for ticker in ("TCS", "RELIANCE", "PARADEEP", "MADE_UP_TICKER"):
        assert get_promoter_override(ticker) is None
        assert is_no_promoter_bank(ticker) is False
        sh = {"promoter_pct": 71.8, "fii_pct": 12.0}
        merged = apply_promoter_override(ticker, sh)
        # Should be unmodified for non-overridden tickers.
        assert merged["promoter_pct"] == 71.8
        assert "promoter_holding_type" not in merged


def test_apply_foreign_overwrites_extractor_value():
    # Simulate the bug: NSE feed reports 0.0% for ITC.
    sh = {"promoter_pct": 0.0, "fii_pct": 30.0}
    merged = apply_promoter_override("ITC", sh)
    assert merged["promoter_pct"] == pytest.approx(24.2, abs=0.1)
    assert merged["promoter_holding_type"] == "foreign_promoter"
    assert merged.get("promoter_entity")


def test_apply_handles_none_dict():
    # Defensive: shareholding dict may be None upstream when the table
    # has no row yet.
    merged = apply_promoter_override("ITC", None)  # type: ignore[arg-type]
    assert merged.get("promoter_pct") == pytest.approx(24.2, abs=0.1)


def test_override_count_reasonable():
    # Guard against accidentally emptying the JSON in a refactor.
    table = list_overrides()
    assert len(table) >= 25, (
        "Expected at least 25 overrides covering foreign promoters + "
        "private/PSU banks"
    )
    # Spot-check known categories are represented.
    types = {row.get("type") for row in table.values()}
    assert "foreign_promoter" in types
    assert "no_promoter_bank" in types
    assert "govt_promoter" in types
