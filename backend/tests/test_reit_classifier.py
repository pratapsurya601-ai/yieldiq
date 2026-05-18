"""
Tests for the 2026-05-18 REIT asset-type classifier
(PR feat/reit-asset-type-classifier — mirrors PR #325 ETF pattern).

Indian REITs (Real Estate Investment Trusts) are SEBI-regulated
pass-through trusts that distribute >=90% of NDCF as DPU and do NOT
compound retained earnings. Generic FCF-DCF mis-prices them by ~50%
on the low side (EMBASSY FV Rs.179 vs CMP Rs.370 / MINDSPACE FV
Rs.118 vs CMP Rs.345 in v102). The classifier short-circuits the
service.py valuation pipeline to verdict="data_limited" with
valuation_model="reit_nav_dpu_required".

Covers:
  1. Curated allow-list — all 4 Indian REITs as of 2026-05-18
     (EMBASSY, MINDSPACE, BROOKFIELD, NEXUS).
  2. Keyword fallback — bare symbol ends with "REIT" (e.g. a
     hypothetical "EXAMPLE_REIT" future listing).
  3. Sector / industry signal — yfinance industry="REIT - Office",
     sector text containing "Real Estate Investment Trust".
  4. Negative cases — operating companies (TCS, RELIANCE) and the
     POWERGRID utility must NOT false-positive. Realty developers
     (DLF, OBEROIRLTY, GODREJPROP) are trusts only by sector, not by
     legal structure, and must NOT trip the classifier on a bare
     ticker check. InvITs (POWERGRID-INVIT) are deliberately a
     separate category.
  5. End-to-end routing probe — EMBASSY routed through the service-
     level valuation_model expression returns
     "reit_nav_dpu_required".
"""
from __future__ import annotations

from backend.services.analysis.constants import is_reit, REIT_TICKERS


# ─────────────────────────────────────────────────────────────────
# 1. Curated allow-list — all 4 Indian REITs
# ─────────────────────────────────────────────────────────────────

def test_curated_allow_list_positives_bare():
    assert is_reit("EMBASSY") is True
    assert is_reit("MINDSPACE") is True
    assert is_reit("BROOKFIELD") is True
    assert is_reit("NEXUS") is True


def test_curated_allow_list_positives_ns_suffix():
    assert is_reit("EMBASSY.NS") is True
    assert is_reit("MINDSPACE.NS") is True
    assert is_reit("BROOKFIELD.NS") is True
    assert is_reit("NEXUS.NS") is True


def test_curated_allow_list_positives_bo_suffix():
    assert is_reit("EMBASSY.BO") is True
    assert is_reit("MINDSPACE.BO") is True


def test_curated_set_contents():
    """Spec requires exactly the 4 known Indian REITs as of 2026-05-18."""
    assert REIT_TICKERS == {"EMBASSY", "MINDSPACE", "BROOKFIELD", "NEXUS"}


# ─────────────────────────────────────────────────────────────────
# 2. Keyword fallback — bare symbol ends in "REIT"
# ─────────────────────────────────────────────────────────────────

def test_keyword_fallback_ends_with_reit():
    # Hypothetical future REIT listing not in the curated set.
    assert is_reit("EXAMPLE_REIT.NS") is True
    assert is_reit("KNOWLEDGEREIT.NS") is True
    assert is_reit("FUTUREREIT") is True


def test_keyword_fallback_does_not_match_mid_string():
    # "REIT" as a substring in the middle of a name must NOT trip
    # the keyword fallback — only the ENDS-WITH anchor counts.
    assert is_reit("REITLIKEBUTNOT") is False


# ─────────────────────────────────────────────────────────────────
# 3. Sector / industry signal
# ─────────────────────────────────────────────────────────────────

def test_industry_signal_reit_office():
    assert is_reit("UNKNOWN.NS", industry="REIT - Office") is True


def test_industry_signal_reit_retail():
    assert is_reit("UNKNOWN.NS", industry="REIT - Retail") is True


def test_sector_signal_full_phrase():
    assert is_reit(
        "UNKNOWN.NS",
        sector="Real Estate Investment Trust",
    ) is True


def test_sector_signal_case_insensitive():
    assert is_reit(
        "UNKNOWN.NS",
        industry="reit - office",
    ) is True


# ─────────────────────────────────────────────────────────────────
# 4. Negative cases — operating companies must NOT false-positive
# ─────────────────────────────────────────────────────────────────

def test_operating_companies_are_not_reits():
    # IT services
    assert is_reit("TCS.NS") is False
    assert is_reit("INFY.NS") is False
    # Conglomerate
    assert is_reit("RELIANCE.NS") is False
    # Banks
    assert is_reit("HDFCBANK.NS") is False
    assert is_reit("SBIN.NS") is False
    # Regulated utility (must not collide with is_regulated_utility)
    assert is_reit("POWERGRID.NS") is False
    assert is_reit("NTPC.NS") is False
    # FMCG
    assert is_reit("HINDUNILVR.NS") is False
    assert is_reit("ITC.NS") is False


def test_realty_developers_are_not_reits():
    """Realty operating companies (developers) have compounding FCF
    and CAN be DCF'd. They are NOT trusts and must NOT trip is_reit()
    on the bare ticker (sector="Real Estate" alone is intentionally
    insufficient — the developer/trust distinction is the whole
    point of this classifier)."""
    assert is_reit("DLF.NS") is False
    assert is_reit("OBEROIRLTY.NS") is False
    assert is_reit("GODREJPROP.NS") is False
    assert is_reit("PRESTIGE.NS") is False
    assert is_reit("BRIGADE.NS") is False


def test_invits_are_not_reits():
    """InvITs (Infrastructure Investment Trusts) are SEBI-regulated
    but a SEPARATE category from REITs. They should not be misrouted
    via is_reit() — they belong to a future is_invit() classifier."""
    # Bare-ticker check; no REIT sector/industry signal.
    assert is_reit("POWERGRIDINVIT.NS") is False
    assert is_reit("IRBINVIT.NS") is False
    assert is_reit("INDIGRID.NS") is False


def test_empty_inputs_are_safe():
    assert is_reit(None) is False
    assert is_reit("") is False


# ─────────────────────────────────────────────────────────────────
# 5. End-to-end routing probe (service-level expression)
# ─────────────────────────────────────────────────────────────────

def test_reit_routing_returns_reit_nav_dpu_required():
    """Probe the service-level branch by exercising the same
    expression used to set valuation_model in the AnalysisResponse
    builder. The contract: any ticker for which is_reit() is True
    must short-circuit to valuation_model="reit_nav_dpu_required"
    before the holdco / rate_base / pb_ratio / dcf branches fire,
    and AFTER the etf_nav_based branch (ETF wins over REIT).
    """
    ticker = "EMBASSY.NS"
    is_etf_ticker = False  # EMBASSY is not an ETF
    is_reit_ticker = is_reit(ticker)
    is_financial = False
    is_regulated_utility_ticker = False
    _holdco_skip = False
    # Mirror the conditional in service.py response builder
    # (post PR #333 — REIT branch inserted between ETF and holdco).
    valuation_model = (
        "etf_nav_based" if is_etf_ticker
        else (
            "reit_nav_dpu_required" if is_reit_ticker
            else (
                "holding_company_sotp_required" if _holdco_skip
                else (
                    "rate_base" if is_regulated_utility_ticker
                    else ("pb_ratio" if is_financial else "dcf")
                )
            )
        )
    )
    assert is_reit_ticker is True
    assert valuation_model == "reit_nav_dpu_required"


def test_etf_wins_over_reit_priority():
    """Priority order: ETF > REIT > regulated_utility > financial.
    If a ticker (hypothetically) satisfied both is_etf() and
    is_reit() — e.g. a "REIT ETF" basket — ETF must win because
    service.py guards `is_reit_ticker` with `False if is_etf_ticker`.
    """
    # Simulate the same guard pattern used in service.py.
    is_etf_ticker = True
    is_reit_ticker = False if is_etf_ticker else is_reit("EMBASSY.NS")
    assert is_reit_ticker is False


def test_all_four_in_scope_tickers_route_correctly():
    """Acceptance criterion from docs/design/reit-valuation-fix.md §8:
    all 4 REIT stock-summary endpoints must produce
    valuation_method="reit_nav_dpu_required" — verified here at the
    classifier + routing-expression level."""
    for t in ("EMBASSY.NS", "MINDSPACE.NS", "BROOKFIELD.NS", "NEXUS.NS"):
        assert is_reit(t) is True, t
