"""
Tests for ``backend/services/analysis/tier1_universe.py``.

Covers the four cases called out in the Layer B Week-1 PR 2 task brief
plus a handful of regression cases for the suffix stripper and the
predicate's null-handling.
"""
from __future__ import annotations

from backend.services.analysis.tier1_universe import (
    TIER1_TICKERS,
    is_tier1,
    is_tier1_eligible,
    strip_suffix,
)


# ── Curated-set membership ───────────────────────────────────────
def test_is_tier1_tcs_curated():
    """TCS.NS is in the curated list (canonical Tier 1 case)."""
    assert is_tier1("TCS.NS") is True


def test_is_tier1_mankind_excluded_recent_ipo():
    """MANKIND was deliberately excluded — recent IPO, Tier-2 case."""
    assert is_tier1("MANKIND.NS") is False


def test_is_tier1_embassy_excluded_reit():
    """REITs route to Tier 3 skip and are NOT in the Tier 1 set."""
    assert is_tier1("EMBASSY.NS") is False


def test_is_tier1_handles_bse_suffix():
    assert is_tier1("RELIANCE.BO") is True


def test_is_tier1_handles_bare_ticker():
    assert is_tier1("INFY") is True


def test_is_tier1_unknown_ticker():
    assert is_tier1("FAKETICKER.NS") is False


def test_is_tier1_none_safe():
    assert is_tier1(None) is False  # type: ignore[arg-type]


def test_strip_suffix_variants():
    assert strip_suffix("TCS.NS") == "TCS"
    assert strip_suffix("tcs.ns") == "TCS"
    assert strip_suffix("  TCS.BO  ") == "TCS"
    assert strip_suffix("TCS") == "TCS"
    assert strip_suffix("") == ""
    assert strip_suffix(None) == ""  # type: ignore[arg-type]


def test_tier1_set_is_frozen_and_reasonable_size():
    """Defensive: the curated list should be a frozenset of ~50–200 names."""
    assert isinstance(TIER1_TICKERS, frozenset)
    assert 50 <= len(TIER1_TICKERS) <= 250


def test_tier1_set_bare_tickers_only():
    """No accidental ``.NS`` / ``.BO`` suffix in the curated list."""
    for t in TIER1_TICKERS:
        assert "." not in t, f"Suffix leaked into TIER1 set: {t!r}"
        assert t == t.upper(), f"Non-uppercase ticker in TIER1 set: {t!r}"


# ── Eligibility predicate ────────────────────────────────────────
def _mock_tcs_financials() -> dict:
    """A 'healthy large-cap' fixture modelled loosely on TCS."""
    return {
        "market_cap_cr": 1_350_000.0,   # ~₹13.5 lakh Cr
        "revenue_cagr_5y": 0.11,        # 11 %
        "fcf_5y": [40_000, 42_000, 45_000, 41_000, 47_000],
        "roce_5y": [0.45, 0.46, 0.42, 0.43, 0.48],
        "sector": "IT Services",
        "listed_years": 21.0,
    }


def test_eligible_with_healthy_largecap():
    assert is_tier1_eligible("TCS.NS", _mock_tcs_financials()) is True


def test_ineligible_when_revenue_cagr_null():
    fin = _mock_tcs_financials()
    fin["revenue_cagr_5y"] = None
    assert is_tier1_eligible("TCS.NS", fin) is False


def test_ineligible_when_revenue_cagr_above_30pct():
    fin = _mock_tcs_financials()
    fin["revenue_cagr_5y"] = 0.42        # hyper-growth → Tier 2 cohort
    assert is_tier1_eligible("TCS.NS", fin) is False


def test_ineligible_when_market_cap_below_floor():
    fin = _mock_tcs_financials()
    fin["market_cap_cr"] = 18_000.0      # below ₹50,000 Cr floor
    assert is_tier1_eligible("SMALL.NS", fin) is False


def test_ineligible_when_fcf_median_negative():
    fin = _mock_tcs_financials()
    fin["fcf_5y"] = [-1_000, -500, 800, -2_000, -1_500]
    assert is_tier1_eligible("CYCLE.NS", fin) is False


def test_ineligible_when_fcf_series_too_short():
    fin = _mock_tcs_financials()
    fin["fcf_5y"] = [40_000, 42_000]
    assert is_tier1_eligible("NEW.NS", fin) is False


def test_ineligible_when_roce_below_threshold():
    fin = _mock_tcs_financials()
    fin["roce_5y"] = [0.08, 0.09, 0.10, 0.11, 0.10]   # 10 % median
    assert is_tier1_eligible("WEAKROCE.NS", fin) is False


def test_ineligible_when_sector_blocked_reit():
    fin = _mock_tcs_financials()
    fin["sector"] = "REIT"
    assert is_tier1_eligible("EMBASSY.NS", fin) is False


def test_ineligible_when_sector_blocked_insurance():
    fin = _mock_tcs_financials()
    fin["sector"] = "Insurance"
    assert is_tier1_eligible("HDFCLIFE.NS", fin) is False


def test_ineligible_when_recent_ipo():
    fin = _mock_tcs_financials()
    fin["listed_years"] = 1.5
    assert is_tier1_eligible("MANKIND.NS", fin) is False


def test_ineligible_when_financials_is_none():
    assert is_tier1_eligible("TCS.NS", None) is False


def test_ineligible_when_financials_is_empty():
    assert is_tier1_eligible("TCS.NS", {}) is False


def test_nan_values_treated_as_missing():
    fin = _mock_tcs_financials()
    fin["revenue_cagr_5y"] = float("nan")
    assert is_tier1_eligible("TCS.NS", fin) is False
