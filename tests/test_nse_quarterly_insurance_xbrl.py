"""Tests for the insurance XBRL schema extension (migration 038).

Pins the live-discovered tag spellings + the `insurance_metrics` JSONB
payload shape across three real integrated-filing Q4 FY26 fixtures:

    HDFCLIFE  — life insurer (private)   — `INTEGRATED_FILING_LI_*`
    SBILIFE   — life insurer (PSU-promoter) — `INTEGRATED_FILING_LI_*`
    ICICIGI   — general insurer (private)  — `INTEGRATED_FILING_GI_*`

These three issuers were chosen to cover the life-vs-general split AND
the two life-specific filing variants (private and PSU-promoter).

A regression that drops a tag fallback, renames a key, or scales a
ratio through the Cr divisor will be caught by the value-bound asserts.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from data_pipeline.sources.nse_quarterly_xbrl import (
    INSURANCE_QUARTERLY_TAGS,
    INSURANCE_QUARTERLY_MONEY_TAGS,
    INSURANCE_QUARTERLY_RATIO_TAGS,
    detect_schema,
    parse_quarter_xml,
)

_FIX = Path(__file__).parent / "fixtures" / "xbrl"

_HDFCLIFE = _FIX / "hdfclife_integrated_q4_fy26.xml"
_SBILIFE = _FIX / "sbilife_integrated_q4_fy26.xml"
_ICICIGI = _FIX / "icicigi_integrated_q4_fy26.xml"

_HDFCLIFE_URL = (
    "https://nsearchives.nseindia.com/corporate/xbrl/"
    "INTEGRATED_FILING_LI_1652667_16042026072910_WEB.xml"
)
_SBILIFE_URL = (
    "https://nsearchives.nseindia.com/corporate/xbrl/"
    "INTEGRATED_FILING_LI_1657299_22042026060213_WEB.xml"
)
_ICICIGI_URL = (
    "https://nsearchives.nseindia.com/corporate/xbrl/"
    "INTEGRATED_FILING_GI_1651776_15042026105416_WEB.xml"
)


# ────────────────────────────────────────────────────────────────────
# Tag-map regression locks
# ────────────────────────────────────────────────────────────────────

def test_insurance_tag_map_covers_life_and_general():
    # Life premium tags (HDFCLIFE/SBILIFE)
    assert "NetPremiumIncome" in INSURANCE_QUARTERLY_TAGS["revenue_cr"]
    assert "GrossPremiumIncome" in INSURANCE_QUARTERLY_TAGS["revenue_cr"]
    # General premium tags (ICICIGI)
    assert "PremiumEarned" in INSURANCE_QUARTERLY_TAGS["revenue_cr"]
    assert "NetPremiumWritten" in INSURANCE_QUARTERLY_TAGS["revenue_cr"]
    # PBT spellings — both life and general variants
    assert "ProfitLossBeforeTax" in INSURANCE_QUARTERLY_TAGS["profit_before_tax_cr"]
    assert "ProfitOrLossBeforeTax" in INSURANCE_QUARTERLY_TAGS["profit_before_tax_cr"]
    # PAT — general schema lacks the Extraordinary suffix
    assert "ProfitLossAfterTax" in INSURANCE_QUARTERLY_TAGS["net_profit_cr"]


def test_insurance_money_and_ratio_maps_keyed_as_documented():
    # Money tags discovered in life fixtures
    assert "gross_premium_income_cr" in INSURANCE_QUARTERLY_MONEY_TAGS
    assert "benefits_paid_net_cr" in INSURANCE_QUARTERLY_MONEY_TAGS
    assert "first_year_premium_cr" in INSURANCE_QUARTERLY_MONEY_TAGS
    # Money tags discovered in general fixture
    assert "combined_ratio" in INSURANCE_QUARTERLY_RATIO_TAGS
    assert "underwriting_profit_cr" in INSURANCE_QUARTERLY_MONEY_TAGS
    assert "claims_paid_cr" in INSURANCE_QUARTERLY_MONEY_TAGS
    # Ratios (unitless) MUST live in the ratio dict, not money
    assert "solvency_ratio" in INSURANCE_QUARTERLY_RATIO_TAGS
    assert "persistency_13" in INSURANCE_QUARTERLY_RATIO_TAGS
    assert "persistency_61" in INSURANCE_QUARTERLY_RATIO_TAGS


# ────────────────────────────────────────────────────────────────────
# Schema-detection pins
# ────────────────────────────────────────────────────────────────────

def test_detect_schema_integrated_life_and_general():
    # The new INTEGRATED_FILING_LI_/GI_ URL prefixes must both detect
    # as 'insurance' so parse_quarter_xml routes them to the insurance
    # tag map instead of falling through to 'industrial'.
    assert detect_schema(_HDFCLIFE_URL, None) == "insurance"
    assert detect_schema(_SBILIFE_URL, None) == "insurance"
    assert detect_schema(_ICICIGI_URL, None) == "insurance"


# ────────────────────────────────────────────────────────────────────
# End-to-end parse on the three live fixtures
# ────────────────────────────────────────────────────────────────────

def _parse(path: Path, ticker: str, period_end: date, url: str) -> dict:
    row = parse_quarter_xml(path.read_bytes(), ticker, period_end, url)
    assert row is not None, f"parser returned None for {ticker}"
    assert row["schema_type"] == "insurance", (
        f"{ticker} mis-routed to schema={row['schema_type']!r}"
    )
    return row


def test_hdfclife_q4_fy26_core_pl_populated():
    row = _parse(_HDFCLIFE, "HDFCLIFE", date(2026, 3, 31), _HDFCLIFE_URL)
    # Core P&L
    assert row["revenue_cr"] is not None and row["revenue_cr"] > 1000
    assert row["net_profit_cr"] is not None and row["net_profit_cr"] > 0
    assert row["profit_before_tax_cr"] is not None
    # Insurance-native JSONB blob
    im = row["insurance_metrics"]
    assert im is not None, "HDFCLIFE life filer must carry insurance_metrics"
    # Solvency ratio: IRDAI floor 1.50; HDFCLIFE typically 1.8-2.0
    assert "solvency_ratio" in im
    assert 1.4 <= im["solvency_ratio"] <= 2.5, (
        f"solvency_ratio out of band: {im['solvency_ratio']}"
    )
    # Persistency: 13M typically 85-90% for HDFCLIFE
    assert "persistency_13" in im
    assert 50.0 <= im["persistency_13"] <= 100.0
    # Life-specific premium splits populated
    assert "first_year_premium_cr" in im or "gross_premium_income_cr" in im


def test_sbilife_q4_fy26_core_pl_populated():
    row = _parse(_SBILIFE, "SBILIFE", date(2026, 3, 31), _SBILIFE_URL)
    assert row["revenue_cr"] is not None and row["revenue_cr"] > 1000
    assert row["net_profit_cr"] is not None and row["net_profit_cr"] > 0
    im = row["insurance_metrics"]
    assert im is not None
    assert "solvency_ratio" in im
    assert 1.4 <= im["solvency_ratio"] <= 2.6
    # Persistency available
    assert "persistency_13" in im
    assert 50.0 <= im["persistency_13"] <= 100.0


def test_icicigi_q4_fy26_general_insurer_metrics():
    row = _parse(_ICICIGI, "ICICIGI", date(2026, 3, 31), _ICICIGI_URL)
    # Core P&L — general insurer
    assert row["revenue_cr"] is not None and row["revenue_cr"] > 100
    assert row["net_profit_cr"] is not None and row["net_profit_cr"] > 0
    assert row["profit_before_tax_cr"] is not None
    im = row["insurance_metrics"]
    assert im is not None, "ICICIGI general filer must carry insurance_metrics"
    # General-specific ratios
    assert "solvency_ratio" in im
    assert 1.4 <= im["solvency_ratio"] <= 3.0
    assert "combined_ratio" in im
    # Combined ratio in % — typical general insurer 95-115%
    assert 70.0 <= im["combined_ratio"] <= 150.0, (
        f"combined_ratio out of band: {im['combined_ratio']}"
    )
    # General insurer must NOT carry life-only persistency keys
    assert "persistency_13" not in im or im["persistency_13"] is None


def test_industrial_row_has_no_insurance_metrics():
    """Non-insurance schemas must leave insurance_metrics = None."""
    industrial_fix = _FIX / "infy_q4_fy24.xml"
    if not industrial_fix.exists():
        return
    row = parse_quarter_xml(
        industrial_fix.read_bytes(), "INFY", date(2024, 3, 31),
        "https://nsearchives.nseindia.com/corporate/xbrl/INFY_Q4_FY24.xml",
    )
    assert row is not None
    assert row.get("insurance_metrics") is None
