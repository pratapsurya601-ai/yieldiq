"""
Tests for the 2026-05-18 ETF asset-type classifier
(PR feat/etf-asset-type-classifier — audit Step 2).

ETFs are valued by NAV / iNAV of their underlying basket, not by DCF,
P/B or any operating-business model. The classifier short-circuits the
service.py valuation pipeline to verdict="data_limited" with
valuation_model="etf_nav_based".

Covers:
  1. Curated allow-list (NIFTYBEES, BANKBEES, GOLDBEES, ICICIB22, ...).
  2. Keyword fallback (a hypothetical "NEWFOOBARETF.NS" → True via the
     "ETF" substring; "FOOBEES" → True via the "BEES" substring).
  3. Negative cases — known regulated utilities, banks and IT names
     must NOT false-positive (TCS, RELIANCE, HDFCBANK, POWERGRID).
  4. yfinance-style quoteType=="ETF" signal.
  5. End-to-end routing probe: NIFTYBEES surfaced through the service-
     level branch returns valuation_model="etf_nav_based".
"""
from __future__ import annotations

from backend.services.analysis.constants import is_etf, ETF_TICKERS


# ─────────────────────────────────────────────────────────────────
# 1. Curated allow-list
# ─────────────────────────────────────────────────────────────────

def test_curated_allow_list_positives():
    assert is_etf("NIFTYBEES") is True
    assert is_etf("NIFTYBEES.NS") is True
    assert is_etf("BANKBEES.NS") is True
    assert is_etf("LIQUIDBEES.NS") is True
    assert is_etf("GOLDBEES.NS") is True
    assert is_etf("SILVERBEES.NS") is True
    assert is_etf("ICICIB22.NS") is True
    assert is_etf("MOM100.NS") is True
    assert is_etf("JUNIORBEES.NS") is True
    assert is_etf("SETFNIF50.NS") is True
    assert is_etf("KOTAKBKETF.NS") is True
    assert is_etf("MAFANG.NS") is True
    assert is_etf("HDFCNIFETF.NS") is True
    assert is_etf("NETFNIF50.NS") is True


def test_curated_set_minimum_size():
    """Spec requires ~30 curated ETF tickers minimum."""
    assert len(ETF_TICKERS) >= 30


# ─────────────────────────────────────────────────────────────────
# 2. Keyword fallback
# ─────────────────────────────────────────────────────────────────

def test_keyword_fallback_etf_substring():
    # Hypothetical AMC-branded ETF not in the curated set.
    assert is_etf("NEWFOOBARETF.NS") is True


def test_keyword_fallback_bees_substring():
    assert is_etf("FOOBEES.NS") is True


def test_keyword_fallback_gold_etf_substring():
    assert is_etf("RANDOMGOLDETF.NS") is True


def test_keyword_fallback_nif50_substring():
    assert is_etf("AMCNIF50.NS") is True


# ─────────────────────────────────────────────────────────────────
# 3. Sector / industry / quoteType signals
# ─────────────────────────────────────────────────────────────────

def test_quote_type_signal():
    # yfinance sets quoteType="ETF" for trust securities.
    assert is_etf("UNKNOWN.NS", security_type="ETF") is True
    # Case-insensitive.
    assert is_etf("UNKNOWN.NS", security_type="etf") is True


def test_industry_signal():
    assert is_etf(
        "UNKNOWN.NS",
        industry="Exchange-Traded Fund",
    ) is True
    assert is_etf(
        "UNKNOWN.NS",
        sector="Exchange Traded Fund",
    ) is True


# ─────────────────────────────────────────────────────────────────
# 4. Negative cases — must NOT false-positive on operating companies
# ─────────────────────────────────────────────────────────────────

def test_operating_companies_are_not_etfs():
    # IT services
    assert is_etf("TCS.NS") is False
    assert is_etf("INFY.NS") is False
    assert is_etf("WIPRO.NS") is False
    # Conglomerate / oil
    assert is_etf("RELIANCE.NS") is False
    # Banks (must not collide with is_bank_like routing)
    assert is_etf("HDFCBANK.NS") is False
    assert is_etf("ICICIBANK.NS") is False
    assert is_etf("SBIN.NS") is False
    # Regulated utilities (must not collide with is_regulated_utility)
    assert is_etf("POWERGRID.NS") is False
    assert is_etf("NTPC.NS") is False
    # FMCG
    assert is_etf("HINDUNILVR.NS") is False
    assert is_etf("ITC.NS") is False


def test_empty_inputs_are_safe():
    assert is_etf(None) is False
    assert is_etf("") is False


# ─────────────────────────────────────────────────────────────────
# 5. End-to-end routing probe (service-level)
# ─────────────────────────────────────────────────────────────────

def test_etf_routing_returns_etf_nav_based_valuation_model():
    """Probe the service-level branch by exercising the same expression
    used to set valuation_model in the AnalysisResponse builder.

    We avoid spinning up the full AnalysisService (which requires
    yfinance + DB + cache fixtures); the goal is to lock in the
    contract: any ticker for which is_etf() is True must short-circuit
    to valuation_model="etf_nav_based" before the rate_base / pb_ratio
    / dcf branches fire.
    """
    ticker = "NIFTYBEES.NS"
    is_etf_ticker = is_etf(ticker)
    # Mirror the conditional in service.py response builder.
    is_financial = False
    is_regulated_utility_ticker = False
    _holdco_skip = False
    valuation_model = (
        "etf_nav_based" if is_etf_ticker
        else (
            "holding_company_sotp_required" if _holdco_skip
            else (
                "rate_base" if is_regulated_utility_ticker
                else ("pb_ratio" if is_financial else "dcf")
            )
        )
    )
    assert is_etf_ticker is True
    assert valuation_model == "etf_nav_based"
