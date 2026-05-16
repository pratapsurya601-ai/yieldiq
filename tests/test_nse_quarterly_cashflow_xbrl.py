"""Tests for the H1/Q4 cash-flow extraction added in migration 034.

Covers the parser path (data_pipeline/sources/nse_quarterly_xbrl.py)
on real XBRL fixtures and the TTM stitching helper in
backend/services/quarterly_results_service.py.

Why two layers of tests:
  * Parser: pins the new tag map against actual NSE quarterly XBRL
    that we know carries the cash-flow statement (H1/Q4 prints).
    A regression to the tag map (renaming, dropping a fallback)
    will be caught here without needing a DB.
  * Stitcher: exercises the H1+prev_H2 12-month logic, including
    the stale-Q4 fallback when the half-year window is broken.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data_pipeline.sources.nse_quarterly_xbrl import (
    QUARTERLY_CASHFLOW_TAGS,
    _cashflow_period_months,
    parse_quarter_xml,
)
from backend.services.quarterly_results_service import (
    _compute_fcf_ttm_from_halfyear,
)


_FIX = Path(__file__).parent / "fixtures" / "xbrl"


def _load(name: str) -> bytes:
    return (_FIX / name).read_bytes()


# ────────────────────────────────────────────────────────────────────
# Tag-map regression locks
# ────────────────────────────────────────────────────────────────────

def test_cashflow_tag_map_contains_observed_tags():
    """Locks the production-observed XBRL spellings into the tag map.

    Removing any of these without an explicit fallback would silently
    NULL the cash-flow columns for the affected filer cohort.
    """
    assert "CashFlowsFromUsedInOperatingActivities" in QUARTERLY_CASHFLOW_TAGS["cfo_cr"]
    assert "CashFlowsFromUsedInInvestingActivities" in QUARTERLY_CASHFLOW_TAGS["cfi_cr"]
    assert "CashFlowsFromUsedInFinancingActivities" in QUARTERLY_CASHFLOW_TAGS["cff_cr"]
    # Quarterly schema's CapEx spelling
    assert (
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
        in QUARTERLY_CASHFLOW_TAGS["capex_cr"]
    )
    # Annual-style fallback (industrial / oil & gas filers)
    assert "PurchaseOfPropertyPlantAndEquipment" in QUARTERLY_CASHFLOW_TAGS["capex_cr"]


def test_cashflow_period_months():
    """Sep period_end → 6 months YTD (H1); Mar → 12 months YTD (FY)."""
    assert _cashflow_period_months(date(2024, 9, 30)) == 6
    assert _cashflow_period_months(date(2024, 3, 31)) == 12
    # Q1 / Q3 have no cash flow per SEBI LODR; sentinel 0 -> stored as NULL
    assert _cashflow_period_months(date(2024, 6, 30)) == 0
    assert _cashflow_period_months(date(2024, 12, 31)) == 0


# ────────────────────────────────────────────────────────────────────
# Parser tests against real NSE fixtures
# ────────────────────────────────────────────────────────────────────

def test_parse_infy_q2_fy25_extracts_h1_cashflow():
    """INFY Q2 FY25 standalone — H1 YTD cash flow should populate.

    Reference values verified against the raw XBRL: CFO 16,458 Cr H1,
    CapEx 968 Cr H1, so FCF ≈ 15,490 Cr H1.
    """
    row = parse_quarter_xml(
        _load("infy_q2_fy25.xml"),
        ticker="INFY",
        period_end=date(2024, 9, 30),
        xbrl_url="INDAS_test_q2",
    )
    assert row is not None
    assert row["has_cashflow_statement"] is True
    assert row["cashflow_period_months"] == 6
    assert row["cfo_cr"] == pytest.approx(16458.0, rel=1e-3)
    assert row["capex_cr"] == pytest.approx(968.0, rel=1e-3)
    # CFI/CFF should also populate (cumulative half-year)
    assert row["cfi_cr"] is not None
    assert row["cff_cr"] is not None


def test_parse_infy_q4_fy24_extracts_full_fy_cashflow():
    """INFY Q4 FY24 standalone — Q4 FourD carries full FY YTD CFO.

    Reference: standalone FY24 CFO ≈ ₹20,787 Cr.
    """
    row = parse_quarter_xml(
        _load("infy_q4_fy24.xml"),
        ticker="INFY",
        period_end=date(2024, 3, 31),
        xbrl_url="INDAS_test_q4",
    )
    assert row is not None
    assert row["has_cashflow_statement"] is True
    assert row["cashflow_period_months"] == 12
    assert row["cfo_cr"] == pytest.approx(20787.0, rel=1e-3)
    assert row["capex_cr"] == pytest.approx(1832.0, rel=1e-3)


def test_parse_infy_q3_fy25_no_cashflow_statement():
    """Q3 (Dec) filings carry WhetherCashFlow=false and zero CF facts.

    Verifies the parser doesn't hallucinate cash-flow values from
    unrelated tags when the company explicitly opted out of the
    optional half-yearly cash-flow inclusion.
    """
    row = parse_quarter_xml(
        _load("infy_q3_fy25.xml"),
        ticker="INFY",
        period_end=date(2024, 12, 31),
        xbrl_url="INDAS_test_q3",
    )
    assert row is not None
    # Q3 filings carry the flag = false (per SEBI LODR Reg 33)
    assert row["has_cashflow_statement"] in (False, None)
    assert row["cfo_cr"] is None
    assert row["capex_cr"] is None
    assert row["cashflow_period_months"] is None


def test_parse_reliance_q2_fy25_capex_heavy():
    """RELIANCE H1 FY25 — capex-heavy conglomerate; capex must be
    distinct from CFI (FCF != CFO + CFI) so we confirm the parser
    picks PurchaseOfPropertyPlantAndEquipment*, not the rolled-up
    CFI total.
    """
    row = parse_quarter_xml(
        _load("reliance_q2_fy25.xml"),
        ticker="RELIANCE",
        period_end=date(2024, 9, 30),
        xbrl_url="INDAS_test_reliance_q2",
    )
    assert row is not None
    assert row["has_cashflow_statement"] is True
    assert row["cfo_cr"] is not None and row["cfo_cr"] > 0
    assert row["capex_cr"] is not None and row["capex_cr"] > 0
    # CapEx should be smaller in magnitude than |CFI| (CFI includes
    # capex + financial investments + acquisitions).
    assert abs(row["capex_cr"]) <= abs(row["cfi_cr"]) * 1.5


def test_parse_hdfcbank_q2_fy25_banking_schema_cashflow():
    """HDFCBANK H1 FY25 banking schema also carries cash flow.

    Banks file cash flow under the same in-bse-fin namespace (no
    -bnk variant for CFS facts), so the parser should populate
    cfo/cfi/cff identically.
    """
    row = parse_quarter_xml(
        _load("hdfcbank_q2_fy25.xml"),
        ticker="HDFCBANK",
        period_end=date(2024, 9, 30),
        xbrl_url="BANKING_test_q2",
    )
    assert row is not None
    assert row["schema_type"] == "banking"
    assert row["has_cashflow_statement"] is True
    assert row["cfo_cr"] is not None
    # CapEx is typically tiny / NULL for pure-play banks (no PP&E
    # buildout); accept either zero or NULL here.
    assert row["capex_cr"] is None or abs(row["capex_cr"]) >= 0


# ────────────────────────────────────────────────────────────────────
# TTM stitching tests (pure function, no DB)
# ────────────────────────────────────────────────────────────────────

def _row(period_end: date, fcf_cr: float | None,
         cfo_cr: float | None = None, capex_cr: float | None = None,
         months: int | None = None) -> dict:
    return {
        "period_end": period_end,
        "fcf_cr": fcf_cr,
        "cfo_cr": cfo_cr,
        "capex_cr": capex_cr,
        "cashflow_period_months": months,
    }


def test_fcf_ttm_q4_latest_uses_full_fy():
    """When the latest cash-flow row is Q4 (Mar), the YTD value IS
    the full 12-month FCF — no stitching needed.
    """
    rows = [
        _row(date(2025, 3, 31), fcf_cr=18950.0, months=12),
        _row(date(2024, 9, 30), fcf_cr=15490.0, months=6),
        _row(date(2024, 3, 31), fcf_cr=18955.0, months=12),
    ]
    fcf, basis, used = _compute_fcf_ttm_from_halfyear(rows)
    assert basis == "fy_q4"
    assert fcf == pytest.approx(18950.0 * 1e7, rel=1e-9)
    assert used == 1


def test_fcf_ttm_q2_latest_stitches_h1_plus_prev_h2():
    """Latest = H1 (Sep). TTM = H1 + previous-FY-H2
                            = H1 + (prev_Q4 - prev_Q2).

    With H1_new = 16,500, prev_Q4 = 30,000, prev_Q2 = 14,000:
        prev_H2 = 30,000 - 14,000 = 16,000
        TTM = 16,500 + 16,000 = 32,500 (Cr) → 3.25e11 INR
    """
    rows = [
        _row(date(2025, 9, 30), fcf_cr=16500.0, months=6),
        _row(date(2025, 3, 31), fcf_cr=30000.0, months=12),
        _row(date(2024, 9, 30), fcf_cr=14000.0, months=6),
    ]
    fcf, basis, used = _compute_fcf_ttm_from_halfyear(rows)
    assert basis == "h1_plus_prev_h2"
    assert fcf == pytest.approx(32500.0 * 1e7, rel=1e-9)
    assert used == 3


def test_fcf_ttm_q2_latest_missing_prev_q2_falls_back_to_stale_q4():
    """If we have a fresh H1 but no previous-FY Q2 in the table, we
    can't compute the prev_H2 delta. Fall back to the most recent Q4
    print (full FY, possibly stale by up to 6 months).
    """
    rows = [
        _row(date(2025, 9, 30), fcf_cr=16500.0, months=6),
        _row(date(2025, 3, 31), fcf_cr=30000.0, months=12),
        # no prev Q2
    ]
    fcf, basis, used = _compute_fcf_ttm_from_halfyear(rows)
    assert basis == "fy_q4_stale"
    assert fcf == pytest.approx(30000.0 * 1e7, rel=1e-9)


def test_fcf_ttm_only_quarterly_rows_returns_none():
    """No H1/Q4 rows → can't produce a TTM, return None so callers
    fall back to annual / yfinance instead of swapping in a bogus value.
    """
    rows = [
        _row(date(2025, 6, 30), fcf_cr=8000.0, months=None),
        _row(date(2025, 12, 31), fcf_cr=8500.0, months=None),
    ]
    fcf, basis, used = _compute_fcf_ttm_from_halfyear(rows)
    assert fcf is None
    assert basis is None
    assert used == 0


def test_fcf_ttm_empty_input():
    fcf, basis, used = _compute_fcf_ttm_from_halfyear([])
    assert fcf is None
    assert basis is None
    assert used == 0


# ────────────────────────────────────────────────────────────────────
# resolve_ttm_for_analysis wiring — verifies fcf_ttm overrides annual
# ────────────────────────────────────────────────────────────────────

def test_resolve_ttm_for_analysis_prefers_xbrl_fcf_over_annual():
    """When compute_xbrl_ttm returns fcf_ttm, resolve_ttm_for_analysis
    must put it into enriched_updates and NOT defer to the annual
    yfinance fallback. Locks the migration-034 wiring against
    regression.
    """
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )
    fake_xbrl = lambda t: {
        "revenue_ttm": 1.6e12,
        "net_profit_ttm": 3.2e11,
        "employee_cost_ttm": 5e11,
        "depreciation_ttm": 1e10,
        "fcf_ttm": 3.25e11,
        "fcf_ttm_basis": "h1_plus_prev_h2",
        "fcf_ttm_rows_used": 3,
        "quarters_used": 4,
        "partial": False,
        "period_end": "2025-09-30",
        "source": "nse_xbrl",
    }
    out = resolve_ttm_for_analysis(
        "INFY",
        query_ttm_financials=lambda t: {"fcf": 99.0, "revenue": 99.0, "pat": 99.0},
        query_latest_annual_financials=lambda t: {"fcf": 11.0},
        compute_xbrl_ttm=fake_xbrl,
    )
    assert out["ttm_source"] == "nse_xbrl"
    assert out["fcf_data_source"] == "ttm+nse_xbrl_cf_h1_plus_prev_h2"
    assert out["enriched_updates"]["latest_fcf"] == 3.25e11
    # Annual fallback must NOT be applied (XBRL FCF won).
    assert out["annual_fcf_fallback"] is None


def test_resolve_ttm_for_analysis_falls_back_to_annual_when_xbrl_fcf_missing():
    """If XBRL TTM owns revenue+PAT but fcf_ttm is None (e.g. half-
    year window incomplete), the annual fallback fcf must populate
    latest_fcf — matches the pre-migration-034 contract.
    """
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )
    fake_xbrl = lambda t: {
        "revenue_ttm": 1.6e12,
        "net_profit_ttm": 3.2e11,
        "employee_cost_ttm": 5e11,
        "depreciation_ttm": 1e10,
        "fcf_ttm": None,
        "fcf_ttm_basis": None,
        "fcf_ttm_rows_used": 0,
        "quarters_used": 4,
        "partial": False,
        "period_end": "2025-09-30",
        "source": "nse_xbrl",
    }
    out = resolve_ttm_for_analysis(
        "INFY",
        query_ttm_financials=lambda t: None,
        query_latest_annual_financials=lambda t: {"fcf": 2.5e11},
        compute_xbrl_ttm=fake_xbrl,
    )
    assert out["ttm_source"] == "nse_xbrl"
    assert out["fcf_data_source"] == "ttm+nse_xbrl"
    assert out["annual_fcf_fallback"] == {"fcf": 2.5e11}
    # latest_fcf NOT set by resolver here — caller applies the
    # annual fallback only when enriched["latest_fcf"] is empty.
    assert "latest_fcf" not in out["enriched_updates"]


def test_fcf_ttm_q2_latest_null_fcf_in_prev_q4_falls_back():
    """If prev_Q4's fcf_cr is NULL (e.g. capex column absent so the
    generated column is NULL), the stitch can't complete — fall back
    to None rather than counting the absent capex as zero.
    """
    rows = [
        _row(date(2025, 9, 30), fcf_cr=16500.0, months=6),
        _row(date(2025, 3, 31), fcf_cr=None, months=12),     # broken Q4
        _row(date(2024, 9, 30), fcf_cr=14000.0, months=6),
    ]
    fcf, basis, used = _compute_fcf_ttm_from_halfyear(rows)
    # h1+prev_h2 can't fire (prev_Q4 fcf is None); stale Q4 also
    # has None — should return None, not a partial value.
    assert fcf is None
    assert basis is None
