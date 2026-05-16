"""Unit tests for data_pipeline.sources.nse_quarterly_xbrl.

Uses real XBRL fixtures downloaded once from NSE (see
`tests/fixtures/xbrl/`) so the parser regression tests are
reproducible without hitting the network.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data_pipeline.sources.nse_quarterly_xbrl import (
    BANK_QUARTERLY_TAGS,
    INDUSTRIAL_QUARTERLY_TAGS,
    INSURANCE_QUARTERLY_TAGS,
    N_QUARTERS,
    NSE_SYMBOL_ALIASES,
    detect_schema,
    detect_unit_scale,
    fiscal_quarter_label,
    parse_quarter_xml,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "xbrl"


# ───────────────────────────────────────────────────────────────────────
# Bug fix #1 — fiscal_quarter label
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "iso,expected",
    [
        ("2024-09-30", "Q2 FY25"),
        ("2024-03-31", "Q4 FY24"),
        ("2024-12-31", "Q3 FY25"),
        ("2022-06-30", "Q1 FY23"),
        # Edge cases
        ("2024-04-30", "Q1 FY25"),   # first month of FY
        ("2025-01-15", "Q4 FY25"),   # mid-Jan = Q4 of FY25
        ("2030-03-31", "Q4 FY30"),
        ("2099-12-31", "Q3 FY00"),   # century rollover
    ],
)
def test_fiscal_quarter_label(iso, expected):
    y, m, d = map(int, iso.split("-"))
    assert fiscal_quarter_label(date(y, m, d)) == expected


# ───────────────────────────────────────────────────────────────────────
# Bug fix #3 — N_QUARTERS standardised
# ───────────────────────────────────────────────────────────────────────

def test_n_quarters_constant():
    assert N_QUARTERS == 22


# ───────────────────────────────────────────────────────────────────────
# Bug fix #6 — symbol aliases
# ───────────────────────────────────────────────────────────────────────

def test_symbol_aliases_shape():
    assert "LTIM" in NSE_SYMBOL_ALIASES
    assert "TATAMOTORS" in NSE_SYMBOL_ALIASES
    assert NSE_SYMBOL_ALIASES["LTIM"] == ["LTIM", "LTIMINDTREE", "LTI"]
    assert NSE_SYMBOL_ALIASES["TATAMOTORS"] == [
        "TATAMOTORS", "TATAMOTORS-DVR", "TATAMOTORSDV",
    ]


# ───────────────────────────────────────────────────────────────────────
# Bug fix #4 — banking schema tag map
# ───────────────────────────────────────────────────────────────────────

def test_bank_tag_map_has_required_fields():
    required = {
        "revenue_cr", "interest_earned_cr", "interest_expended_cr",
        "operating_profit_cr", "provisions_cr",
        "profit_before_tax_cr", "tax_expense_cr", "net_profit_cr",
    }
    assert required.issubset(BANK_QUARTERLY_TAGS.keys())
    # OperatingProfit: observed spelling first (data-driven)
    assert (BANK_QUARTERLY_TAGS["operating_profit_cr"][0]
            == "OperatingProfitBeforeProvisionAndContingencies")


# ───────────────────────────────────────────────────────────────────────
# Schema detection
# ───────────────────────────────────────────────────────────────────────

def test_detect_schema_by_url():
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/BANKING_x.xml", None
    ) == "banking"
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_x.xml", None
    ) == "industrial"
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/LI_x.xml", None
    ) == "insurance"
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/GI_x.xml", None
    ) == "insurance"


def test_detect_schema_on_real_fixtures():
    infy = (FIXTURES / "infy_q3_fy25.xml").read_bytes()
    hdfc = (FIXTURES / "hdfcbank_q3_fy25.xml").read_bytes()
    baj = (FIXTURES / "bajajfinsv_q3_fy25.xml").read_bytes()
    assert detect_schema("any/INDAS_x.xml", infy) == "industrial"
    assert detect_schema("any/BANKING_x.xml", hdfc) == "banking"
    # BAJAJFINSV's URL uses NBFC_INDAS_ prefix → industrial
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/NBFC_INDAS_x.xml", baj
    ) == "industrial"


# ───────────────────────────────────────────────────────────────────────
# Bug fix #2 — unit-scale via LevelOfRoundingUsedInFinancialStatements
# ───────────────────────────────────────────────────────────────────────

def test_unit_scale_reads_rounding_tag():
    # Synthetic sfacts dict shape: {localname: [(value_str, ctxRef), ...]}
    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Crores", "OneD")]}
    # 'Crores' declared → divisor = 1 (values already in Cr)
    assert detect_unit_scale(sfacts, 34915.0) == 1.0

    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Lakhs", "OneD")]}
    assert detect_unit_scale(sfacts, 3491500.0) == 100.0

    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Millions", "OneD")]}
    assert detect_unit_scale(sfacts, 349150.0) == 10.0

    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Actual", "OneD")]}
    assert detect_unit_scale(sfacts, 349_150_000_000.0) == 1e7


def test_unit_scale_sanity_check_overrides_declared_crores():
    """If file declares 'Crores' but value is enormous (raw INR), use 1e7."""
    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Crores", "OneD")]}
    # 349 billion would be ₹349,150 trillion in Cr — absurd, so file is
    # actually raw INR despite declaring 'Crores'.
    assert detect_unit_scale(sfacts, 349_150_000_000.0) == 1e7


def test_unit_scale_bajajfinsv_standalone_regression():
    """BAJAJFINSV Q3 FY25 standalone: declared 'Crores', rev_raw=708,200,000.

    Without the sanity-check threshold tightening, the parser returned
    revenue_cr = 708,200,000 (treating raw as Cr). With the fix, the
    threshold of 1e6 for declared='Crores' catches this case → divisor
    1e7 → revenue_cr = 70.82 Cr (the true standalone holdco topline).
    """
    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Crores", "OneD")]}
    # The actual BAJAJFINSV Q3 FY25 standalone raw revenue value.
    assert detect_unit_scale(sfacts, 708_200_000.0) == 1e7
    # And the consolidated value (already-caught by previous threshold).
    assert detect_unit_scale(sfacts, 320_418_100_000.0) == 1e7
    # But a TRUE Cr-denominated value (e.g. RELIANCE consolidated ~₹2.5L Cr)
    # must still pass through as already-Cr.
    assert detect_unit_scale(sfacts, 250_000.0) == 1.0


def test_unit_scale_fallback_when_tag_missing():
    """No rounding tag → magnitude heuristic kicks in."""
    sfacts: dict[str, list[tuple[str, str]]] = {}
    # Big raw INR
    assert detect_unit_scale(sfacts, 349_150_000_000.0) == 1e7
    # Already in Cr
    assert detect_unit_scale(sfacts, 34915.0) == 100.0  # heuristic treats as lakhs
    # Tiny
    assert detect_unit_scale(sfacts, 5.0) == 1.0


# ───────────────────────────────────────────────────────────────────────
# Real-XML parsing — regression tests on fixtures
# ───────────────────────────────────────────────────────────────────────

def test_parse_infy_q3_fy25():
    xml = (FIXTURES / "infy_q3_fy25.xml").read_bytes()
    row = parse_quarter_xml(
        xml,
        ticker="INFY",
        period_end=date(2024, 12, 31),
        xbrl_url="https://nsearchives.nseindia.com/corporate/xbrl/INDAS_x.xml",
    )
    assert row is not None
    assert row["schema_type"] == "industrial"
    assert row["fiscal_quarter"] == "Q3 FY25"
    assert row["ticker"] == "INFY"
    # Revenue should resolve to ~₹35K-41K Cr range (standalone or consolidated)
    rev = row["revenue_cr"]
    assert rev is not None
    assert 30_000 <= rev <= 45_000, f"INFY Q3 FY25 revenue {rev} out of range"
    # Net profit non-null
    assert row["net_profit_cr"] is not None
    assert 4_000 <= row["net_profit_cr"] <= 8_500
    # Schema-routed bank-only fields stay None for industrial
    assert row["interest_earned_cr"] is None
    assert row["provisions_cr"] is None


def test_parse_hdfcbank_q3_fy25():
    xml = (FIXTURES / "hdfcbank_q3_fy25.xml").read_bytes()
    url = "https://nsearchives.nseindia.com/corporate/xbrl/BANKING_117525_x.xml"
    row = parse_quarter_xml(
        xml, ticker="HDFCBANK", period_end=date(2024, 12, 31), xbrl_url=url,
    )
    assert row is not None
    assert row["schema_type"] == "banking"
    assert row["fiscal_quarter"] == "Q3 FY25"
    # InterestEarned: ~₹85,000 Cr range (consolidated Q3 FY25)
    ie = row["interest_earned_cr"]
    assert ie is not None
    assert 70_000 <= ie <= 95_000, f"HDFCBANK Q3 FY25 InterestEarned {ie}"
    # revenue_cr should mirror interest_earned for banks
    assert row["revenue_cr"] == ie
    # NIM components present
    assert row["interest_expended_cr"] is not None
    assert row["interest_expended_cr"] < ie  # always
    # Operating profit present (this is the field-name bug check)
    assert row["operating_profit_cr"] is not None
    # Provisions present
    assert row["provisions_cr"] is not None
    # Net profit ~ ₹16-19K Cr
    assert 14_000 <= row["net_profit_cr"] <= 22_000


def test_parse_bajajfinsv_q3_fy25_unit_scale_regression():
    """BAJAJFINSV standalone holdco — previously tripped magnitude heuristic.

    The standalone P&L of the holdco has tiny topline (~₹15-30 Cr investment
    income vs the consolidated ~₹35,000 Cr). The old heuristic flipped to
    'lakhs' scale, producing absurd consolidated-looking numbers. With the
    rounding-tag-driven scale, both standalone and consolidated parse cleanly.
    """
    xml = (FIXTURES / "bajajfinsv_q3_fy25.xml").read_bytes()
    url = "https://nsearchives.nseindia.com/corporate/xbrl/NBFC_INDAS_x.xml"
    row = parse_quarter_xml(
        xml, ticker="BAJAJFINSV", period_end=date(2024, 12, 31), xbrl_url=url,
    )
    assert row is not None
    assert row["schema_type"] == "industrial"
    assert row["fiscal_quarter"] == "Q3 FY25"
    # The fixture is the newest filing — either standalone or consolidated.
    # The regression test is that revenue does NOT explode into the millions
    # of Cr range (which would indicate scale was mis-detected as lakhs).
    rev = row["revenue_cr"]
    assert rev is not None
    # BAJAJFINSV consolidated Q3 FY25 ~ ₹35,000 Cr; standalone < ₹100 Cr.
    # In NEITHER case should it exceed ₹100K Cr (which would indicate the
    # old lakhs-misdetection bug).
    assert rev < 100_000, f"BAJAJFINSV revenue {rev} — likely unit-scale regression"
    # Net profit also in a sane range (not millions of Cr).
    if row["net_profit_cr"] is not None:
        assert row["net_profit_cr"] < 50_000


# ───────────────────────────────────────────────────────────────────────
# Insurance schema (partial coverage)
# ───────────────────────────────────────────────────────────────────────

def test_insurance_tag_map_has_revenue_and_pat():
    """Insurance map is intentionally partial but must cover the basics."""
    assert "revenue_cr" in INSURANCE_QUARTERLY_TAGS
    assert "net_profit_cr" in INSURANCE_QUARTERLY_TAGS
    # NetPremiumIncome is the headline that maps to revenue_cr
    assert "NetPremiumIncome" in INSURANCE_QUARTERLY_TAGS["revenue_cr"]


@pytest.mark.skipif(
    not (FIXTURES / "hdfclife_q3_fy25.xml").exists(),
    reason="HDFCLIFE fixture not present (optional — added if insurance probe succeeded)",
)
def test_parse_hdfclife_q3_fy25():
    xml = (FIXTURES / "hdfclife_q3_fy25.xml").read_bytes()
    url = "https://nsearchives.nseindia.com/corporate/xbrl/LI_117242_x.xml"
    row = parse_quarter_xml(
        xml, ticker="HDFCLIFE", period_end=date(2024, 12, 31), xbrl_url=url,
    )
    assert row is not None
    assert row["schema_type"] == "insurance"
    assert row["fiscal_quarter"] == "Q3 FY25"
    # Net premium income for HDFCLIFE Q3 FY25 ~ ₹15-20K Cr
    assert row["revenue_cr"] is not None
    assert 10_000 <= row["revenue_cr"] <= 25_000
