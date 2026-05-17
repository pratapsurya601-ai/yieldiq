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


def test_parse_gayahws_consolidated_q2_fy26_e2e_cfo_scale():
    """GAYAHWS Q2 FY26 consolidated — real-XML end-to-end regression.

    The fixture is a SEBI 2025 integrated-filing-results XBRL that:
      * Declares <in-capmkt:LevelOfRounding>Lakhs</in-capmkt:LevelOfRounding>
      * Carries values with decimals="-3" (precision-to-nearest-thousand)
        in raw rupees (the declared 'Lakhs' is metadata-only — values are
        actually raw INR, a known SEBI 2025 template inconsistency)
      * Has RevenueFromOperations=0 (SPV holdco with no operating revenue)

    Before this fix the parser:
      1. Saw declared='Lakhs' → divisor=100
      2. revenue_raw=0 so all sanity bypasses (which need rev > 1e8) failed
      3. cfo_raw = -7,375,888,000 / 100 = -73,758,880 Cr (₹73 million Cr —
         absurd, 100,000× NSE market cap)

    With the fix:
      1. The probe magnitude widens to include CFO/CFI/CFF raw values, so
         the 'Lakhs declared but raw INR' bypass (probe > 1e8) triggers
         and divisor flips to 1e7. PLUS a post-divide guard re-scales any
         value > 1e6 Cr to raw-INR semantics as a last-resort safety net.
      2. cfo_cr resolves to ~-737 Cr (consolidated H1 YTD including
         intra-group cash transfers — CFO+CFI+CFF ≈ 0, internally
         consistent for an SPV with no net cash change).
    """
    xml = (FIXTURES / "gayahws_integrated_q2_fy26.xml").read_bytes()
    row = parse_quarter_xml(
        xml,
        ticker="GAYAHWS",
        period_end=date(2025, 9, 30),
        xbrl_url=(
            "https://nsearchives.nseindia.com/corporate/xbrl/"
            "INTEGRATED_FILING_RESULTS_x.xml"
        ),
    )
    assert row is not None
    assert row["fiscal_quarter"] == "Q2 FY26"
    assert row["is_consolidated"] is True
    # cfo_cr MUST land in the plausible-Indian-filing range (no Indian SPV
    # quarter is anywhere near 1e6 Cr). Specifically: anything > 5,000 Cr
    # absolute for a ~₹61 Cr-market-cap SPV indicates the unit-scale bug
    # has regressed.
    assert row["cfo_cr"] is not None
    assert abs(row["cfo_cr"]) < 5_000, (
        f"GAYAHWS consolidated cfo_cr {row['cfo_cr']} indicates raw-rupee "
        f"scale bug regression (expected absolute value < 5000 Cr)."
    )
    # Net profit must be tiny for an SPV.
    assert row["net_profit_cr"] is not None
    assert abs(row["net_profit_cr"]) < 50, (
        f"GAYAHWS consolidated net_profit_cr {row['net_profit_cr']} out of "
        f"plausible SPV range (±50 Cr)."
    )
    # Internal consistency: CFO + CFI + CFF ≈ 0 (no net cash change)
    # within ~100 Cr is the H1 reality for this holdco.
    assert row["cfi_cr"] is not None and row["cff_cr"] is not None
    net_cash = row["cfo_cr"] + row["cfi_cr"] + row["cff_cr"]
    assert abs(net_cash) < 100, (
        f"GAYAHWS net cash change {net_cash} Cr — unit-scale inconsistency "
        f"across the three CF sections."
    )


def test_parse_gayahws_standalone_q2_fy26_e2e_cfo_scale():
    """GAYAHWS Q2 FY26 standalone — companion real-XML regression.

    Standalone CFO is the SPV's own operating cash flow (no subsidiary
    consolidation). For a ~₹61 Cr-market-cap holding company we expect
    cfo_cr in the ±20 Cr band; the raw value is -54,493,000 rupees =
    -5.45 Cr, which is the post-fix expected output.
    """
    xml = (FIXTURES / "gayahws_standalone_q2_fy26.xml").read_bytes()
    row = parse_quarter_xml(
        xml,
        ticker="GAYAHWS",
        period_end=date(2025, 9, 30),
        xbrl_url=(
            "https://nsearchives.nseindia.com/corporate/xbrl/"
            "INTEGRATED_FILING_RESULTS_x.xml"
        ),
    )
    assert row is not None
    assert row["fiscal_quarter"] == "Q2 FY26"
    assert row["is_consolidated"] is False
    assert row["cfo_cr"] is not None
    assert -20 <= row["cfo_cr"] <= 20, (
        f"GAYAHWS standalone cfo_cr {row['cfo_cr']} out of plausible "
        f"±20 Cr SPV range — likely scale-detection regression."
    )
    # Net profit standalone ~ -5.09 Cr (per fixture).
    assert row["net_profit_cr"] is not None
    assert abs(row["net_profit_cr"]) < 20


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


# ───────────────────────────────────────────────────────────────────────
# 2026-05 — Integrated Filing migration
# ───────────────────────────────────────────────────────────────────────

import json  # noqa: E402

from data_pipeline.sources.nse_quarterly_xbrl import (  # noqa: E402
    _adapt_integrated_filing,
    _fetch_integrated_filings,
)

INTEGRATED_FIXTURES = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
)


def test_detect_schema_integrated_filing_urls():
    # New URL prefixes — INTEGRATED_FILING_BANKING_ must route to 'banking'
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/"
        "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml",
        None,
    ) == "banking"
    # INTEGRATED_FILING_INDAS_ must route to 'industrial' (default — it
    # contains neither BANKING_ nor INSURANCE_ tokens)
    assert detect_schema(
        "https://nsearchives.nseindia.com/corporate/xbrl/"
        "INTEGRATED_FILING_INDAS_1658776_24042026105714_WEB.xml",
        None,
    ) == "industrial"


def test_detect_schema_integrated_uri_fallback():
    """If URL is missing, namespace URI substring must resolve schema."""
    hdfc = (FIXTURES / "hdfcbank_integrated_q4_fy26.xml").read_bytes()
    rel = (FIXTURES / "reliance_integrated_q4_fy26.xml").read_bytes()
    # Pass None as URL → must fall back to URI inspection.
    assert detect_schema(None, hdfc) == "banking"
    assert detect_schema(None, rel) == "industrial"


def test_adapt_integrated_filing_normalizes_keys():
    rec = {
        "seq_Id": "152826",
        "symbol": "RELIANCE",
        "type": "Integrated Filing- Financials",
        "qe_Date": "31-MAR-2026",
        "xbrl": "https://x/INTEGRATED_FILING_INDAS_x.xml",
        "broadcast_Date": "24-Apr-2026 22:57:12",
        "audited": "Audited",
        "consolidated": "Consolidated",
    }
    adapted = _adapt_integrated_filing(rec)
    assert adapted["toDate"] == "31-MAR-2026"
    assert adapted["broadcastDate"] == "24-Apr-2026 22:57:12"
    assert adapted["xbrl"] == rec["xbrl"]
    assert adapted["consolidated"] is True
    assert adapted["audited"] is True

    rec2 = dict(rec, consolidated="Standalone", audited="Unaudited")
    adapted2 = _adapt_integrated_filing(rec2)
    assert adapted2["consolidated"] is False
    assert adapted2["audited"] is False


def test_fetch_integrated_filings_uses_fixture(monkeypatch):
    """Drive _fetch_integrated_filings off the saved JSON envelope.

    We monkeypatch the session.get to return the fixture payload, then
    assert pagination terminates and Governance rows are filtered out.
    """
    payload = json.loads(
        (INTEGRATED_FIXTURES / "nse_integrated_filings_reliance.json").read_text()
    )
    assert payload["totalCount"] == len(payload["data"])

    class FakeResp:
        status_code = 200
        def __init__(self, p): self._p = p
        def json(self): return self._p

    class FakeSession:
        def __init__(self): self.calls = []
        def get(self, url, **kw):
            self.calls.append(url)
            # Return the full envelope on the first listing call; empty
            # rows on subsequent pages so pagination terminates.
            if "integrated-filing-results" in url:
                if "page=1" in url or "page=" not in url:
                    return FakeResp(payload)
                return FakeResp({"data": [], "totalCount": payload["totalCount"]})
            return FakeResp({})

    fake = FakeSession()
    out = _fetch_integrated_filings("RELIANCE", session=fake)
    # All financial filings retained, all governance filtered.
    fin_count = sum(
        1 for r in payload["data"]
        if r.get("type") == "Integrated Filing- Financials"
    )
    gov_count = sum(
        1 for r in payload["data"]
        if r.get("type") == "Integrated Filing- Governance"
    )
    assert gov_count > 0  # sanity — fixture must contain some
    assert len(out) == fin_count
    # All returned rows are adapted (have legacy keys).
    for r in out:
        assert "toDate" in r and "broadcastDate" in r and "xbrl" in r
        assert r["type"] == "Integrated Filing- Financials"


def test_parse_reliance_integrated_q4_fy26():
    xml = (FIXTURES / "reliance_integrated_q4_fy26.xml").read_bytes()
    url = (
        "https://nsearchives.nseindia.com/corporate/xbrl/"
        "INTEGRATED_FILING_INDAS_1658776_24042026105714_WEB.xml"
    )
    row = parse_quarter_xml(
        xml, ticker="RELIANCE", period_end=date(2026, 3, 31), xbrl_url=url,
    )
    assert row is not None
    assert row["schema_type"] == "industrial"
    assert row["fiscal_quarter"] == "Q4 FY26"
    # Reliance Q4 FY26 consolidated revenue ~ ₹2.5-3.0 lakh Cr
    assert row["revenue_cr"] is not None
    assert 200_000 <= row["revenue_cr"] <= 350_000
    # Net profit ~ ₹18-22K Cr
    assert row["net_profit_cr"] is not None
    assert 15_000 <= row["net_profit_cr"] <= 25_000
    assert row["basic_eps"] is not None
    # Bank-only fields stay None
    assert row["interest_earned_cr"] is None
    assert row["is_consolidated"] is True


def test_parse_hdfcbank_integrated_q4_fy26():
    xml = (FIXTURES / "hdfcbank_integrated_q4_fy26.xml").read_bytes()
    url = (
        "https://nsearchives.nseindia.com/corporate/xbrl/"
        "INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml"
    )
    row = parse_quarter_xml(
        xml, ticker="HDFCBANK", period_end=date(2026, 3, 31), xbrl_url=url,
    )
    assert row is not None
    assert row["schema_type"] == "banking"
    assert row["fiscal_quarter"] == "Q4 FY26"
    # Interest earned ~ ₹80-95K Cr for the quarter (consolidated)
    assert row["interest_earned_cr"] is not None
    assert 70_000 <= row["interest_earned_cr"] <= 100_000
    assert row["revenue_cr"] == row["interest_earned_cr"]
    assert row["interest_expended_cr"] is not None
    assert row["operating_profit_cr"] is not None
    assert row["provisions_cr"] is not None
    # Net profit ~ ₹16-25K Cr range
    assert row["net_profit_cr"] is not None
    assert 14_000 <= row["net_profit_cr"] <= 28_000
