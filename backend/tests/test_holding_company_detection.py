# backend/tests/test_holding_company_detection.py
# ─────────────────────────────────────────────────────────────────────
# Tests for is_holding_company() in backend.services.analysis.constants.
#
# Structural data-quality fix #4 (2026-05-17): holding companies / SPVs
# / pure investment vehicles have revenue~0 and CFO/FCF driven by
# intermittent dividend receipts. DCF on these names produces absurd
# FVs (GAYAHWS cfo_cr=7.37bn pre-fix). We detect them and skip DCF.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import pytest

from backend.services.analysis.constants import (
    HOLDING_COMPANIES,
    is_holding_company,
)


class TestCuratedAllowList:
    """Curated tickers detect on ticker alone — no other signal needed."""

    @pytest.mark.parametrize("ticker", [
        "BAJAJHLDNG", "TATAINVEST", "MCLEODRUSS", "NDTV", "NETWORK18",
        "GAYAHWS", "MOIL", "PILANIINVS", "WILLIAMAGR", "SUMMITSEC",
        "KAMAHOLD", "MAHSCOOTER",
    ])
    def test_curated_ticker_detected_bare(self, ticker):
        assert is_holding_company(ticker) is True

    @pytest.mark.parametrize("ticker", [
        "BAJAJHLDNG.NS", "TATAINVEST.NS", "GAYAHWS.NS", "MOIL.BO",
    ])
    def test_curated_ticker_detected_with_suffix(self, ticker):
        assert is_holding_company(ticker) is True

    def test_curated_seed_list_contents(self):
        # Regression guard against accidental removals from the seed.
        for must_have in (
            "BAJAJHLDNG", "TATAINVEST", "MCLEODRUSS",
            "NDTV", "NETWORK18", "GAYAHWS", "MOIL",
        ):
            assert must_have in HOLDING_COMPANIES


class TestAutoDetection:
    """Auto-detect requires ALL of: revenue<100, mcap>100, kw match."""

    def test_gayahws_detected_when_curated(self):
        # GAYAHWS is in HOLDING_COMPANIES; ticker-membership wins
        # before any auto-detect signals run.
        assert is_holding_company("GAYAHWS") is True

    def test_auto_detect_classic_holdco_profile(self):
        # Unknown ticker but classic holdco fingerprint:
        # revenue ~30 Cr, mcap 5,000 Cr, industry contains "holding".
        assert is_holding_company(
            "UNKNOWNCO",
            sector="Financial Services",
            industry="Holding Companies",
            revenue_cr=30.0,
            market_cap_cr=5000.0,
        ) is True

    def test_auto_detect_diversified_keyword(self):
        assert is_holding_company(
            "UNKNOWNCO2",
            sector="Diversified",
            industry=None,
            revenue_cr=50.0,
            market_cap_cr=2000.0,
        ) is True

    def test_auto_detect_nic_code_64200(self):
        assert is_holding_company(
            "UNKNOWNCO3",
            sector="Financial Services",
            industry="Other Financial",
            revenue_cr=10.0,
            market_cap_cr=1500.0,
            nic_code="64200",
        ) is True

    def test_auto_detect_fails_when_revenue_too_high(self):
        # Real operating company that happens to have "Investment" in
        # its industry label — revenue >100 Cr means it's operating.
        assert is_holding_company(
            "REALCO",
            sector="Financial Services",
            industry="Investment Banking",
            revenue_cr=5000.0,
            market_cap_cr=10000.0,
        ) is False

    def test_auto_detect_fails_when_mcap_too_small(self):
        # Defunct shell — low revenue AND low mcap, not a real holdco.
        assert is_holding_company(
            "SHELLCO",
            sector="Diversified",
            industry="Holding",
            revenue_cr=2.0,
            market_cap_cr=50.0,
        ) is False

    def test_auto_detect_fails_when_no_keyword(self):
        # Low revenue, decent mcap, but neither sector nor industry
        # nor NIC code matches a holdco keyword. Could be a real
        # micro-cap operating company — don't tag it.
        assert is_holding_company(
            "MICROCAPCO",
            sector="Consumer Defensive",
            industry="Packaged Foods",
            revenue_cr=20.0,
            market_cap_cr=500.0,
        ) is False

    def test_auto_detect_fails_with_missing_inputs(self):
        # Conservative: if either revenue or mcap is missing, do NOT
        # tag. The curated allow-list is the safety net.
        assert is_holding_company(
            "UNKNOWNCO",
            sector="Diversified",
            industry="Holding",
            revenue_cr=None,
            market_cap_cr=5000.0,
        ) is False
        assert is_holding_company(
            "UNKNOWNCO",
            sector="Diversified",
            industry="Holding",
            revenue_cr=10.0,
            market_cap_cr=None,
        ) is False


class TestNonHoldcoOperatingCompanies:
    """Real operating companies must NEVER be flagged."""

    def test_tcs_not_detected(self):
        assert is_holding_company(
            "TCS",
            sector="Technology",
            industry="Information Technology Services",
            revenue_cr=240_000.0,
            market_cap_cr=14_00_000.0,
        ) is False
        assert is_holding_company("TCS.NS") is False

    def test_hdfcbank_not_detected(self):
        assert is_holding_company(
            "HDFCBANK",
            sector="Financial Services",
            industry="Banks",
            revenue_cr=150_000.0,
            market_cap_cr=12_00_000.0,
        ) is False

    def test_reit_not_detected(self):
        # REITs are a separate category (already handled elsewhere);
        # they have real rental revenue and should NOT trip holdco.
        assert is_holding_company(
            "EMBASSY",
            sector="Real Estate",
            industry="REIT - Office",
            revenue_cr=3500.0,
            market_cap_cr=35_000.0,
        ) is False

    def test_reliance_not_detected(self):
        # Conglomerate but not a holdco — runs operating businesses.
        assert is_holding_company(
            "RELIANCE",
            sector="Energy",
            industry="Oil & Gas Refining & Marketing",
            revenue_cr=9_00_000.0,
            market_cap_cr=18_00_000.0,
        ) is False
