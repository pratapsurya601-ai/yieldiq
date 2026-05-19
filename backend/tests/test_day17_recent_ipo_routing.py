"""Day-17 (2026-05-20): regression guards for the QSR/hospitality +
HFC/SME-finance routing fixes.

Locks in:
  1. ITCHOTELS + ABLBL route to "Retail" sector via TICKER_SECTOR_OVERRIDES
  2. FIVESTAR + AADHARHFC + CANHLIFE pass is_bank_like() / financial
     routing -> never fall through to generic DCF
  3. FIVESTAR is in lending_nbfc peer group; AADHARHFC is in premium_hfc;
     CANHLIFE is in life_insurance
  4. Hospitality / hotels sector strings resolve to the "retail" Tier-2
     peer cohort
  5. _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR has retail + consumer cyclical
     at 48 months (was silently 36)
"""
from __future__ import annotations

import pytest


# ── Sector overrides ─────────────────────────────────────────────


def test_itchotels_and_ablbl_pinned_to_retail():
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES
    assert TICKER_SECTOR_OVERRIDES.get("ITCHOTELS") == "Retail", (
        "ITCHOTELS must route to Retail for Tier-2 peer-cohort anchoring. "
        "Without this it surfaces as 'Hotels' / 'Hospitality' and falls "
        "through to plain DCF (FV ~7% of consensus on Day-13 scan)."
    )
    assert TICKER_SECTOR_OVERRIDES.get("ABLBL") == "Retail", (
        "ABLBL (Aditya Birla Lifestyle Brands) must route to Retail."
    )


def test_existing_qsr_overrides_unchanged():
    """Regression guard against accidental edits to the surrounding
    QSR overrides Day-3 / Day-17 entries."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES
    for t in ("WESTLIFE", "JUBLFOOD", "DEVYANI", "SAPPHIRE"):
        assert TICKER_SECTOR_OVERRIDES.get(t) == "Retail", t


# ── Bank-like routing (_NBFC_INSURANCE_BANKLIKE) ────────────────


def test_fivestar_aadharhfc_canhlife_in_banklike_set():
    from backend.services.analysis.constants import (
        _NBFC_INSURANCE_BANKLIKE,
        FINANCIAL_COMPANIES,
    )
    for t in ("FIVESTAR", "AADHARHFC", "CANHLIFE"):
        assert t in _NBFC_INSURANCE_BANKLIKE, (
            f"{t} must be in _NBFC_INSURANCE_BANKLIKE so is_bank_like() "
            f"returns True. Without this, financial_valuation_service "
            f"is bypassed and the ticker routes through generic DCF."
        )
        assert t in FINANCIAL_COMPANIES, (
            f"{t} must also be in FINANCIAL_COMPANIES (legacy set still "
            f"queried by some hex-pipeline paths)."
        )


def test_is_bank_like_returns_true_for_each():
    from backend.services.analysis.constants import is_bank_like
    assert is_bank_like("FIVESTAR", "Financial Services", None) is True
    assert is_bank_like("AADHARHFC", "Financial Services", None) is True
    assert is_bank_like("CANHLIFE", "Financial Services", None) is True


# ── Peer-group membership ───────────────────────────────────────


def test_fivestar_in_lending_nbfc_peer_group():
    from backend.services.financial_valuation_service import (
        FINANCIAL_PEER_GROUPS,
    )
    assert "FIVESTAR" in FINANCIAL_PEER_GROUPS["lending_nbfc"], (
        "FIVESTAR (SME-finance NBFC) belongs in lending_nbfc — same "
        "P/BV cohort as SHRIRAMFIN, SUNDARMFIN, CHOLAFIN."
    )


def test_aadharhfc_in_premium_hfc_peer_group():
    from backend.services.financial_valuation_service import (
        FINANCIAL_PEER_GROUPS,
    )
    assert "AADHARHFC" in FINANCIAL_PEER_GROUPS["premium_hfc"], (
        "AADHARHFC (affordable-housing specialist) belongs in premium_hfc "
        "alongside AAVAS / HOMEFIRST / CANFINHOME."
    )


def test_canhlife_in_life_insurance_peer_group():
    from backend.services.financial_valuation_service import (
        FINANCIAL_PEER_GROUPS,
    )
    assert "CANHLIFE" in FINANCIAL_PEER_GROUPS["life_insurance"], (
        "CANHLIFE (Canara HSBC Life Insurance) belongs in life_insurance "
        "alongside LICI / HDFCLIFE / SBILIFE / ICICIPRULI."
    )


def test_get_peer_group_resolves_each():
    """The actual lookup the financial-valuation engine uses must
    return the right group for each new ticker."""
    from backend.services.financial_valuation_service import get_peer_group
    assert get_peer_group("FIVESTAR") == "lending_nbfc"
    assert get_peer_group("FIVESTAR.NS") == "lending_nbfc"  # suffix-tolerant
    assert get_peer_group("AADHARHFC") == "premium_hfc"
    assert get_peer_group("CANHLIFE") == "life_insurance"
    # Negative: CANHLIFE must NOT collide with CANFINHOME's group
    assert get_peer_group("CANFINHOME") == "premium_hfc"  # unchanged


# ── Tier-2 hospitality cohort resolution ────────────────────────


def test_hospitality_sector_resolves_to_retail():
    from backend.services.tier2_peer_lookup import _resolve_sector_key
    for s in ("Hospitality", "hospitality", "Hotels", "hotels", "Hotel",
              "Hotel Chains", "Lodging", "lodging"):
        result = _resolve_sector_key(s)
        assert result == "retail", (
            f"Sector '{s}' must resolve to retail cohort. Got: {result}"
        )


def test_existing_sector_resolutions_unchanged():
    """Pin the existing mappings that share the retail / healthcare
    cohorts so a future edit doesn't accidentally drop them."""
    from backend.services.tier2_peer_lookup import _resolve_sector_key
    assert _resolve_sector_key("Retail") == "retail"
    assert _resolve_sector_key("Healthcare") == "healthcare"
    assert _resolve_sector_key("Pharma") == "pharma"


# ── IPO window widening ─────────────────────────────────────────


def test_consumer_cyclical_ipo_window_widened():
    from backend.services.analysis.ipo_framework import (
        _RECENT_IPO_WINDOW_MONTHS,
        _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR,
        _window_months_for_sector,
    )
    # Default unchanged
    assert _RECENT_IPO_WINDOW_MONTHS == 36
    # New sector keys present
    assert _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR.get("retail") == 48
    assert _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR.get("consumer cyclical") == 48
    # _window_months_for_sector resolves correctly (case + whitespace)
    assert _window_months_for_sector("Retail") == 48
    assert _window_months_for_sector("CONSUMER CYCLICAL") == 48
    assert _window_months_for_sector("  retail  ") == 48
    # Pharma still 60
    assert _window_months_for_sector("pharma") == 60
    # Unknown sector falls back to default 36
    assert _window_months_for_sector("FMCG") == 36
    assert _window_months_for_sector(None) == 36
