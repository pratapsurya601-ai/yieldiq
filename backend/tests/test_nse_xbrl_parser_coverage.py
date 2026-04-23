# backend/tests/test_nse_xbrl_parser_coverage.py
"""
Tests for PR A — NSE XBRL parser coverage extensions.

Covers three new behaviours:
1. `_FIELD_TAGS` picks up the PSU-oil / Ind-AS-2020 variants for
   capex + cfo + depreciation that the previous tag list missed.
2. `_detect_period_type_from_contexts` overrides the endpoint-based
   hint when the XBRL duration disagrees (e.g. a Q4+FY combined
   filing served under the Annual endpoint).
3. `_filing_is_consolidated` classifies NSE filing-index entries.

No network — XBRL bytes and filing dicts are inlined.
"""
from __future__ import annotations

from datetime import date

import pytest

from data_pipeline.sources.nse_xbrl_fundamentals import (
    _FIELD_TAGS,
    _detect_period_type_from_contexts,
    _extract_contexts,
    _extract_facts,
    _filing_is_consolidated,
    parse_nse_xbrl,
)


# ── Fixture 1: PSU oil-marketer annual filing shape ──────────────
#
# Models BPCL/HPCL/IOC — capex hidden under the combined
# "PropertyPlantAndEquipmentAndIntangibleAssets" tag, CFO under the
# "NetCashFromUsedInOperatingActivities" wording. Previous parser
# yielded capex=None, cfo=None for these; new tag list picks them up.
_PSU_OIL_XBRL = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in-bse-fin="https://www.bseindia.com/xbrl/fin">
  <context id="D_FY24">
    <period>
      <startDate>2023-04-01</startDate>
      <endDate>2024-03-31</endDate>
    </period>
  </context>
  <context id="I_FYE24">
    <period>
      <instant>2024-03-31</instant>
    </period>
  </context>

  <in-bse-fin:RevenueFromOperations contextRef="D_FY24" unitRef="INR" decimals="0">4500000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitBeforeTax contextRef="D_FY24" unitRef="INR" decimals="0">350000000000</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:ProfitLossForPeriod contextRef="D_FY24" unitRef="INR" decimals="0">260000000000</in-bse-fin:ProfitLossForPeriod>
  <in-bse-fin:FinanceCosts contextRef="D_FY24" unitRef="INR" decimals="0">40000000000</in-bse-fin:FinanceCosts>
  <in-bse-fin:DepreciationAndAmortisationExpense contextRef="D_FY24" unitRef="INR" decimals="0">80000000000</in-bse-fin:DepreciationAndAmortisationExpense>

  <!-- New capex variant: PPE + intangibles combined -->
  <in-bse-fin:PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets contextRef="D_FY24" unitRef="INR" decimals="0">120000000000</in-bse-fin:PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets>

  <!-- New CFO variant -->
  <in-bse-fin:NetCashFromUsedInOperatingActivities contextRef="D_FY24" unitRef="INR" decimals="0">300000000000</in-bse-fin:NetCashFromUsedInOperatingActivities>

  <in-bse-fin:Assets contextRef="I_FYE24" unitRef="INR" decimals="0">2000000000000</in-bse-fin:Assets>
  <in-bse-fin:CurrentLiabilities contextRef="I_FYE24" unitRef="INR" decimals="0">800000000000</in-bse-fin:CurrentLiabilities>
  <in-bse-fin:Borrowings contextRef="I_FYE24" unitRef="INR" decimals="0">500000000000</in-bse-fin:Borrowings>
  <in-bse-fin:Equity contextRef="I_FYE24" unitRef="INR" decimals="0">700000000000</in-bse-fin:Equity>
</xbrl>
"""
)


def test_psu_oil_capex_and_cfo_parse_with_new_tags():
    row = parse_nse_xbrl(
        _PSU_OIL_XBRL, ticker="BPCL", period_end=date(2024, 3, 31),
        period_type="annual",
    )
    assert row is not None
    # Revenue 4.5e12 → scale=1e7 → 450_000 Cr
    assert row["revenue"] == pytest.approx(450_000, rel=1e-6)
    # Capex parsed from the PPE+intangibles combined tag → 12_000 Cr
    assert row["capex"] == pytest.approx(12_000, rel=1e-6), (
        "capex should now parse via PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets"
    )
    # CFO parsed from the "NetCashFromUsedInOperatingActivities" wording
    assert row["cfo"] == pytest.approx(30_000, rel=1e-6), (
        "cfo should now parse via NetCashFromUsedInOperatingActivities"
    )


def test_new_tag_variants_present_in_field_tags():
    """Explicit regression guard on the tag additions for PR A."""
    # Capex variants that PSU oil majors use.
    for t in (
        "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets",
        "PaymentsForPropertyPlantAndEquipment",
        "CashOutflowOnPurchaseOfPropertyPlantAndEquipment",
        "CapitalExpenditure",
    ):
        assert t in _FIELD_TAGS["capex"], f"missing capex tag variant: {t}"
    # CFO variants.
    for t in (
        "NetCashFromUsedInOperatingActivities",
        "CashGeneratedFromOperations",
    ):
        assert t in _FIELD_TAGS["cfo"], f"missing cfo tag variant: {t}"
    # PAT Ind-AS 2020 variant.
    assert "ProfitLossAfterTax" in _FIELD_TAGS["pat"]


# ── Fixture 2: Q4+FY combined filing tagged under Annual endpoint ──
#
# A filing the endpoint labels "Annual" but whose duration context is
# a 90-day Q4 window. Context duration must win.
_Q4_WITH_ANNUAL_HINT = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in-bse-fin="https://www.bseindia.com/xbrl/fin">
  <context id="D_Q4">
    <period>
      <startDate>2024-01-01</startDate>
      <endDate>2024-03-31</endDate>
    </period>
  </context>
  <in-bse-fin:RevenueFromOperations contextRef="D_Q4" unitRef="INR" decimals="0">1200000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitBeforeTax contextRef="D_Q4" unitRef="INR" decimals="0">180000000000</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:ProfitLossForPeriod contextRef="D_Q4" unitRef="INR" decimals="0">140000000000</in-bse-fin:ProfitLossForPeriod>
</xbrl>
"""
)


def test_context_duration_overrides_endpoint_hint_q4_as_quarterly():
    contexts = _extract_contexts(_Q4_WITH_ANNUAL_HINT)
    inferred = _detect_period_type_from_contexts(contexts, date(2024, 3, 31))
    assert inferred == "quarterly"

    row = parse_nse_xbrl(
        _Q4_WITH_ANNUAL_HINT, ticker="TESTCO", period_end=date(2024, 3, 31),
        period_type="annual",  # endpoint says annual, but context says Q4
    )
    assert row is not None
    assert row["period_type"] == "quarterly", (
        "context duration (90 days) should override endpoint hint 'annual'"
    )


def test_context_duration_detects_annual_from_fy_duration():
    contexts = _extract_contexts(_PSU_OIL_XBRL)
    inferred = _detect_period_type_from_contexts(contexts, date(2024, 3, 31))
    assert inferred == "annual"


def test_context_duration_returns_none_when_no_matching_end():
    contexts = _extract_contexts(_PSU_OIL_XBRL)
    # Period end not present in any duration context.
    inferred = _detect_period_type_from_contexts(contexts, date(2020, 3, 31))
    assert inferred is None


# ── Filing-index consolidation classification ────────────────────


def test_filing_is_consolidated_recognises_common_labels():
    assert _filing_is_consolidated({"consolidated": "Consolidated"}) is True
    assert _filing_is_consolidated({"consolidated": "Standalone"}) is False
    assert _filing_is_consolidated({"consolidated": "Non-Consolidated"}) is False
    assert _filing_is_consolidated({"relatingTo": "Consolidated Financial Results"}) is True
    assert _filing_is_consolidated({"relatingTo": "Standalone Financial Results"}) is False


def test_filing_is_consolidated_none_when_no_label():
    assert _filing_is_consolidated({"toDate": "31-Mar-2024", "xbrl": "http://x"}) is None
    assert _filing_is_consolidated({"consolidated": ""}) is None
