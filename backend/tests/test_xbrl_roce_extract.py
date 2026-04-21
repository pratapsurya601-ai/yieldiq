# backend/tests/test_xbrl_roce_extract.py
"""
Tests for the NSE XBRL parser's new ROCE-relevant field extraction.

Feeds a small but realistic XBRL fragment to the parser and asserts that
total_assets, current_liabilities and ebit all emerge on the canonical
row dict. Mock-free, no network — the XBRL bytes are inlined.

Background: ROCE on the analysis page was rendering 0% for top tickers
because the financials row lacked current_liabilities. The parser had
no tags for it. This test locks in the fix.
"""
from __future__ import annotations

from datetime import date

import pytest

from data_pipeline.sources.nse_xbrl_fundamentals import (
    _FIELD_TAGS,
    _extract_contexts,
    _extract_facts,
    parse_nse_xbrl,
)


# ── Canned XBRL fragment ────────────────────────────────────────
#
# A minimal Ind-AS-shaped filing: one duration context (FY), one
# instant context (period end), revenue + PBT + PAT + finance cost +
# depreciation + total assets + current liabilities + borrowings +
# equity. Numbers are in raw rupees so they exercise the scale
# normaliser — revenue 5e12 should pick scale=1e7 (Cr).
_XBRL_BYTES = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in-bse-fin="https://www.bseindia.com/xbrl/fin">
  <context id="D_FY">
    <period>
      <startDate>2023-04-01</startDate>
      <endDate>2024-03-31</endDate>
    </period>
  </context>
  <context id="I_FYE">
    <period>
      <instant>2024-03-31</instant>
    </period>
  </context>

  <!-- Income statement -->
  <in-bse-fin:RevenueFromOperations contextRef="D_FY" unitRef="INR" decimals="0">5000000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitBeforeTax contextRef="D_FY" unitRef="INR" decimals="0">800000000000</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:ProfitLossForPeriod contextRef="D_FY" unitRef="INR" decimals="0">600000000000</in-bse-fin:ProfitLossForPeriod>
  <in-bse-fin:FinanceCosts contextRef="D_FY" unitRef="INR" decimals="0">50000000000</in-bse-fin:FinanceCosts>
  <in-bse-fin:DepreciationAndAmortisationExpense contextRef="D_FY" unitRef="INR" decimals="0">200000000000</in-bse-fin:DepreciationAndAmortisationExpense>
  <in-bse-fin:ProfitFromOperations contextRef="D_FY" unitRef="INR" decimals="0">850000000000</in-bse-fin:ProfitFromOperations>

  <!-- Balance sheet (instant) -->
  <in-bse-fin:Assets contextRef="I_FYE" unitRef="INR" decimals="0">10000000000000</in-bse-fin:Assets>
  <in-bse-fin:CurrentLiabilities contextRef="I_FYE" unitRef="INR" decimals="0">3000000000000</in-bse-fin:CurrentLiabilities>
  <in-bse-fin:Borrowings contextRef="I_FYE" unitRef="INR" decimals="0">2500000000000</in-bse-fin:Borrowings>
  <in-bse-fin:Equity contextRef="I_FYE" unitRef="INR" decimals="0">4500000000000</in-bse-fin:Equity>
  <in-bse-fin:CashAndCashEquivalents contextRef="I_FYE" unitRef="INR" decimals="0">100000000000</in-bse-fin:CashAndCashEquivalents>
</xbrl>
"""
)

_PERIOD_END = date(2024, 3, 31)


# ── Low-level: facts + contexts extract as expected ─────────────


def test_extract_facts_picks_up_new_local_names():
    facts = _extract_facts(_XBRL_BYTES)
    # The canonical tags we added must be present as local-names.
    assert "Assets" in facts
    assert "CurrentLiabilities" in facts
    assert "ProfitFromOperations" in facts


def test_extract_contexts_resolves_instant_and_duration():
    contexts = _extract_contexts(_XBRL_BYTES)
    assert contexts["D_FY"]["start"] == "2023-04-01"
    assert contexts["D_FY"]["end"] == "2024-03-31"
    assert contexts["I_FYE"]["instant"] == "2024-03-31"


# ── High-level: parse_nse_xbrl returns ROCE-ready fields ────────


def test_parse_nse_xbrl_populates_ebit_total_assets_current_liabilities():
    row = parse_nse_xbrl(
        _XBRL_BYTES, ticker="TESTCO", period_end=_PERIOD_END,
        period_type="annual",
    )
    assert row is not None, "parser returned None — fact extraction broken"

    # Revenue 5e12 rupees ⇒ scale=1e7 ⇒ 5e5 Cr
    assert row["revenue"] == pytest.approx(500_000, rel=1e-6)
    # Total assets 1e13 rupees ⇒ 1e6 Cr
    assert row["total_assets"] == pytest.approx(1_000_000, rel=1e-6)
    # Current liabilities 3e12 rupees ⇒ 3e5 Cr
    assert row["current_liabilities"] == pytest.approx(300_000, rel=1e-6)
    # EBIT from ProfitFromOperations 8.5e11 rupees ⇒ 85_000 Cr
    assert row["ebit"] == pytest.approx(85_000, rel=1e-6)
    # EBITDA = PBT + depreciation + finance_cost
    # = (8e11 + 2e11 + 5e10) = 1.05e12 rupees ⇒ 105_000 Cr
    assert row["ebitda"] == pytest.approx(105_000, rel=1e-6)


def test_parse_nse_xbrl_ebit_derives_from_pbt_when_operating_profit_missing():
    """If the filing lacks ProfitFromOperations, EBIT = PBT + finance_cost."""
    xbrl_no_opprofit = _XBRL_BYTES.replace(
        b"<in-bse-fin:ProfitFromOperations contextRef=\"D_FY\""
        b" unitRef=\"INR\" decimals=\"0\">850000000000"
        b"</in-bse-fin:ProfitFromOperations>\n",
        b"",
    )
    row = parse_nse_xbrl(
        xbrl_no_opprofit, ticker="TESTCO", period_end=_PERIOD_END,
        period_type="annual",
    )
    assert row is not None
    # PBT 8e11 + finance 5e10 = 8.5e11 rupees ⇒ 85_000 Cr
    assert row["ebit"] == pytest.approx(85_000, rel=1e-6)


def test_parse_nse_xbrl_ebit_none_when_no_pbt_and_no_opprofit():
    """Graceful degradation: EBIT should be None, not a crash."""
    # Strip BOTH ProfitFromOperations and ProfitBeforeTax.
    xbrl_stripped = _XBRL_BYTES
    for tag in (
        b"ProfitFromOperations",
        b"ProfitBeforeTax",
    ):
        # crude but adequate for test bytes — remove one opening tag line
        start = xbrl_stripped.find(b"<in-bse-fin:" + tag)
        if start == -1:
            continue
        end = xbrl_stripped.find(b"</in-bse-fin:" + tag + b">", start)
        if end == -1:
            continue
        end += len(b"</in-bse-fin:" + tag + b">")
        xbrl_stripped = xbrl_stripped[:start] + xbrl_stripped[end:]

    row = parse_nse_xbrl(
        xbrl_stripped, ticker="TESTCO", period_end=_PERIOD_END,
        period_type="annual",
    )
    assert row is not None
    assert row["ebit"] is None


def test_field_tags_include_all_three_new_canonical_fields():
    """Defensive: if someone renames these keys upstream we want to know."""
    assert "total_assets" in _FIELD_TAGS
    assert "current_liabilities" in _FIELD_TAGS
    assert "operating_profit" in _FIELD_TAGS
    # Spot-check a key tag under each — regression guard on the
    # public shape of the dict.
    assert "Assets" in _FIELD_TAGS["total_assets"]
    assert "CurrentLiabilities" in _FIELD_TAGS["current_liabilities"]
    assert "ProfitFromOperations" in _FIELD_TAGS["operating_profit"]
