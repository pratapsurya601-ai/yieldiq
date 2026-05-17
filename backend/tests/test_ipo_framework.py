"""Phase 0 scaffold tests for the IPO-aware framework.

Covers:
  1. is_recent_ipo() — True for 12-month-old listing, False for 30-month-
     old listing, False when listing_date is None.
  2. ipo_caveat() — non-empty string with months_since substituted.

No DCF routing is exercised here; that lands in a later phase once
verified DRHP financials are populated in IPO_PROSPECTUS_FINANCIALS.
"""
from __future__ import annotations

from datetime import date

from backend.services.analysis.ipo_framework import (
    IPO_PROSPECTUS_FINANCIALS,
    ipo_caveat,
    is_recent_ipo,
)


def _iso_months_ago(months: int) -> str:
    """Stdlib-only month subtraction (avoids dateutil dependency)."""
    today = date.today()
    total_month_index = today.year * 12 + (today.month - 1) - months
    new_year, new_month0 = divmod(total_month_index, 12)
    new_month = new_month0 + 1
    # Clamp day to 28 to dodge month-end edge cases (e.g. Mar 31 - 1mo).
    return date(new_year, new_month, min(today.day, 28)).isoformat()


# ─────────────────────────────────────────────────────────────────
# 1. is_recent_ipo gate
# ─────────────────────────────────────────────────────────────────

def test_is_recent_ipo_true_for_12_months_ago():
    assert is_recent_ipo("NEWCO", _iso_months_ago(12)) is True


def test_is_recent_ipo_true_for_30_months_ago_under_36mo_window():
    # feat/recent-ipo-sector-relative-valuation widened the window
    # from 24 → 36 months. 30 months ago is still inside the new window.
    assert is_recent_ipo("RECENTCO", _iso_months_ago(30)) is True


def test_is_recent_ipo_false_for_48_months_ago():
    assert is_recent_ipo("OLDCO", _iso_months_ago(48)) is False


def test_is_recent_ipo_false_for_none():
    assert is_recent_ipo("NOLIST", None) is False


# ─────────────────────────────────────────────────────────────────
# 3. compute_sector_relative_fv — sector P/E path + verdict thresholds
# ─────────────────────────────────────────────────────────────────

def test_sector_relative_fv_sector_pe_path_undervalued():
    """WAAREEINDO-class case: profitable IPO with cohort P/E peers."""
    from backend.services.analysis.ipo_framework import (
        compute_sector_relative_fv,
    )
    cohort = [
        {"pe_ratio": 28.0, "pb_ratio": 4.0},
        {"pe_ratio": 32.0, "pb_ratio": 4.5},
        {"pe_ratio": 25.0, "pb_ratio": 3.8},
    ]
    out = compute_sector_relative_fv(
        eps_ttm=50.0,
        revenue_per_share=400.0,
        cohort=cohort,
        price=1000.0,
    )
    # median P/E = 28 → FV = 28 * 50 = 1400 → +40% vs price 1000 → undervalued
    assert out["method"] == "sector_pe"
    assert out["fair_value"] == 1400.0
    assert out["median_pe"] == 28.0
    assert out["n_peers"] == 3
    assert out["verdict_hint"] == "undervalued"


def test_sector_relative_fv_within_30pct_band_returns_data_limited():
    from backend.services.analysis.ipo_framework import (
        compute_sector_relative_fv,
    )
    cohort = [{"pe_ratio": 20.0}, {"pe_ratio": 20.0}, {"pe_ratio": 20.0}]
    # FV = 20 * 50 = 1000, price = 1100 → -9% → within ±30%
    out = compute_sector_relative_fv(
        eps_ttm=50.0, revenue_per_share=None, cohort=cohort, price=1100.0,
    )
    assert out["verdict_hint"] == "data_limited"


def test_sector_relative_fv_preprofit_falls_back_to_sector_ps():
    """ETERNAL/Zomato-class case: pre-profit IPO with no positive EPS."""
    from backend.services.analysis.ipo_framework import (
        compute_sector_relative_fv,
    )
    cohort = [{"pe_ratio": 50.0}, {"pe_ratio": 60.0}, {"pe_ratio": 70.0}]
    out = compute_sector_relative_fv(
        eps_ttm=-2.0,           # loss-making
        revenue_per_share=30.0,
        cohort=cohort,
        price=250.0,
    )
    # FV = median_pe(60) * rev_ps(30) * 0.10 = 180 → -28% vs 250 → within band
    assert out["method"] == "sector_ps"
    assert out["fair_value"] == 180.0
    assert out["verdict_hint"] == "data_limited"


def test_sector_relative_fv_empty_cohort_returns_none():
    from backend.services.analysis.ipo_framework import (
        compute_sector_relative_fv,
    )
    out = compute_sector_relative_fv(
        eps_ttm=10.0, revenue_per_share=100.0, cohort=[], price=200.0,
    )
    assert out["fair_value"] is None
    assert out["method"] == "none"
    assert out["verdict_hint"] == "data_limited"


def test_min_annual_reports_constant_is_three():
    from backend.services.analysis.ipo_framework import (
        MIN_ANNUAL_REPORTS_FOR_DCF,
    )
    assert MIN_ANNUAL_REPORTS_FOR_DCF == 3


# ─────────────────────────────────────────────────────────────────
# 2. ipo_caveat string
# ─────────────────────────────────────────────────────────────────

def test_ipo_caveat_returns_non_empty_with_months_substituted():
    listing = _iso_months_ago(8)
    msg = ipo_caveat("NEWCO", listing)
    assert isinstance(msg, str) and msg.strip(), "caveat must be non-empty"
    # months_since (8) should appear in the rendered string
    assert "8 months" in msg, f"expected '8 months' substring in: {msg!r}"


# ─────────────────────────────────────────────────────────────────
# 3. Scaffold safety — prospectus dict starts empty
# ─────────────────────────────────────────────────────────────────

def test_prospectus_financials_is_empty_scaffold():
    """Phase 0 must NOT seed any synthetic prospectus data."""
    assert IPO_PROSPECTUS_FINANCIALS == {}
