# backend/tests/test_financial_valuation.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for the sector-appropriate financial valuation path.
# Peer medians are patched to avoid DB dependency.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest

from backend.services import financial_valuation_service as fvs
from backend.services.financial_valuation_service import (
    FINANCIAL_PEER_GROUPS,
    compute_financial_fair_value,
    get_peer_group,
)


@pytest.fixture(autouse=True)
def _clear_peer_cache():
    """Each test starts with a clean peer cache."""
    fvs._PEER_CACHE.clear()
    yield
    fvs._PEER_CACHE.clear()


@pytest.fixture
def patch_medians(monkeypatch):
    """Patch _fetch_peer_medians_from_db to return None → hits fallbacks.

    Helper returns a closure to let individual tests override medians.
    """
    def _set(medians_by_group: dict | None = None):
        medians_by_group = medians_by_group or {}

        def _stub(group_key: str):
            return medians_by_group.get(group_key)

        monkeypatch.setattr(fvs, "_fetch_peer_medians_from_db", _stub)

    return _set


# ── Peer group detection ─────────────────────────────────────────

def test_peer_groups_expected_keys():
    assert set(FINANCIAL_PEER_GROUPS.keys()) == {
        "psu_banks", "private_banks", "growth_nbfc", "govt_nbfc",
        "life_insurance", "general_insurance", "housing_finance",
        "asset_mgmt",
    }


def test_get_peer_group_handles_suffix():
    assert get_peer_group("SBIN.NS") == "psu_banks"
    assert get_peer_group("HDFCBANK.NS") == "private_banks"
    assert get_peer_group("BAJFINANCE") == "growth_nbfc"
    assert get_peer_group("PFC.NS") == "govt_nbfc"
    assert get_peer_group("ICICIGI") == "general_insurance"
    assert get_peer_group("LICI") == "life_insurance"


def test_get_peer_group_returns_none_for_non_financial():
    assert get_peer_group("RELIANCE.NS") is None
    assert get_peer_group("TCS") is None


# ── SBIN — PSU bank, P/BV path ───────────────────────────────────

def test_sbin_pbv_peer_valuation(patch_medians):
    # Realistic FY25 snapshot: book value ~₹500, peer median P/BV ~0.9,
    # peer median ROE ~16%, SBIN ROE ~15% → slight downward adjustment.
    patch_medians({
        "psu_banks": {
            "median_pb": 0.9, "median_roe": 0.16,
            "n_pb": 5, "n_pe": 5, "n_roe": 5,
        }
    })
    result = compute_financial_fair_value(
        ticker="SBIN.NS",
        company_info={"current_price": 820.0, "shares": 8.93e9},
        financials={
            "total_equity": 4.47e12,  # ~₹500 BVPS
            "roe": 0.15,
        },
        shareholding=None,
    )
    assert result is not None
    assert result["method"] == "p_bv_peer"
    # BVPS ≈ 500, fair P/BV ≈ 0.9 × (0.15/0.16) ≈ 0.844, IV ≈ ₹422
    assert 380 <= result["fair_value"] <= 460
    assert result["bear_case"] < result["base_case"] < result["bull_case"]
    # CMP 820 vs fair ~420 → overvalued
    assert result["verdict"] == "overvalued"
    assert 40 <= result["confidence_score"] <= 90


# ── HDFCBANK — private bank, higher ROE justifies premium ────────

def test_hdfcbank_pbv_with_roe_premium(patch_medians):
    patch_medians({
        "private_banks": {
            "median_pb": 2.4, "median_roe": 0.16,
            "n_pb": 5, "n_pe": 5, "n_roe": 5,
        }
    })
    # HDFCBANK: BVPS ~₹600, ROE ~17% (above peer median)
    result = compute_financial_fair_value(
        ticker="HDFCBANK.NS",
        company_info={"current_price": 1650.0, "shares": 7.6e9},
        financials={
            "priceToBook": 2.75,  # → BVPS ≈ 600
            "roe": 0.17,
        },
        shareholding=None,
    )
    assert result is not None
    assert result["method"] == "p_bv_peer"
    # Fair P/BV ≈ 2.4 × (0.17/0.16) = 2.55. IV ≈ 600 × 2.55 ≈ 1530.
    assert 1400 <= result["fair_value"] <= 1700
    # Within ±15% of CMP → fairly valued
    assert result["verdict"] == "fairly_valued"


# ── BAJFINANCE — growth NBFC, P/E path ───────────────────────────

def test_bajfinance_pe_peer_valuation(patch_medians):
    patch_medians({
        "growth_nbfc": {
            "median_pb": 4.0, "median_roe": 0.20,
            "median_pe": 25.0,
            "n_pb": 5, "n_pe": 5, "n_roe": 5,
        }
    })
    result = compute_financial_fair_value(
        ticker="BAJFINANCE.NS",
        company_info={"current_price": 7500.0, "shares": 6.2e8},
        financials={
            "trailingEps": 280.0,
            "roe": 0.22,
        },
        shareholding=None,
    )
    assert result is not None
    assert result["method"] == "p_e_peer"
    # IV ≈ 280 × 25 = 7000
    assert 6500 <= result["fair_value"] <= 7500
    assert result["verdict"] in ("fairly_valued", "overvalued")


# ── PFC — govt NBFC, P/BV path (the key bug fix) ────────────────

def test_pfc_pbv_fallback_to_default_medians(patch_medians):
    # Simulate the real-world scenario that breaks today:
    # DB lookup fails → should use hardcoded fallback, not None.
    patch_medians(None)  # empty dict → no group returns data
    result = compute_financial_fair_value(
        ticker="PFC.NS",
        company_info={"current_price": 420.0, "shares": 3.3e9},
        financials={
            "total_equity": 8.25e11,  # BVPS ≈ ₹250
            "roe": 0.22,  # PFC has high ROE
        },
        shareholding=None,
    )
    assert result is not None
    assert result["method"] == "p_bv_peer"
    # Fallback median_pb=1.2, median_roe=0.18.
    # Adj = min(1.4, 0.22/0.18) = 1.22. Fair P/BV ≈ 1.46. IV ≈ 366.
    assert 300 <= result["fair_value"] <= 450
    # CMP 420 close to fair → fairly_valued or overvalued
    assert result["verdict"] in ("fairly_valued", "overvalued", "undervalued")
    # Most critical: it produces a non-None, non-zero fair value.
    assert result["fair_value"] > 0


# ── ICICIGI — general insurance, P/BV path ──────────────────────

def test_icicigi_pbv_peer_valuation(patch_medians):
    patch_medians({
        "general_insurance": {
            "median_pb": 3.0, "median_roe": 0.15,
            "n_pb": 2, "n_pe": 2, "n_roe": 2,
        }
    })
    result = compute_financial_fair_value(
        ticker="ICICIGI.NS",
        company_info={"current_price": 1800.0, "shares": 4.9e8},
        financials={
            "priceToBook": 6.0,  # → BVPS = 300
            "roe": 0.16,
        },
        shareholding=None,
    )
    assert result is not None
    assert result["method"] == "p_bv_peer"
    # BVPS=300, fair P/BV ≈ 3.0 × (0.16/0.15) = 3.2. IV ≈ 960.
    # CMP 1800 vs ~960 → overvalued
    assert result["verdict"] == "overvalued"
    assert 800 <= result["fair_value"] <= 1100


# ── Missing-data handling ────────────────────────────────────────

def test_returns_none_when_no_bvps_or_eps(patch_medians):
    patch_medians({
        "private_banks": {
            "median_pb": 2.4, "median_roe": 0.16,
            "n_pb": 5, "n_pe": 5, "n_roe": 5,
        }
    })
    result = compute_financial_fair_value(
        ticker="HDFCBANK.NS",
        company_info={"current_price": 1600.0},
        financials={},  # no equity, no shares, no EPS
        shareholding=None,
    )
    assert result is None


def test_returns_none_for_non_financial_ticker():
    assert compute_financial_fair_value(
        ticker="RELIANCE.NS",
        company_info={"current_price": 2800.0},
        financials={"total_equity": 1e13, "shares": 6.8e9},
        shareholding=None,
    ) is None


def test_returns_none_when_price_is_zero(patch_medians):
    patch_medians({
        "psu_banks": {
            "median_pb": 0.9, "median_roe": 0.16,
            "n_pb": 5, "n_pe": 0, "n_roe": 5,
        }
    })
    result = compute_financial_fair_value(
        ticker="SBIN.NS",
        company_info={"current_price": 0},
        financials={"total_equity": 4e12, "shares": 8.9e9},
        shareholding=None,
    )
    assert result is None


# ── Peer-cache TTL behaviour ─────────────────────────────────────

def test_peer_medians_are_cached(monkeypatch):
    call_count = {"n": 0}

    def _stub(group_key):
        call_count["n"] += 1
        return {
            "median_pb": 1.0, "median_roe": 0.15,
            "n_pb": 3, "n_pe": 3, "n_roe": 3,
        }

    monkeypatch.setattr(fvs, "_fetch_peer_medians_from_db", _stub)

    fvs.get_peer_medians("psu_banks")
    fvs.get_peer_medians("psu_banks")
    fvs.get_peer_medians("psu_banks")

    # Three calls, one DB fetch (because of 1h TTL)
    assert call_count["n"] == 1
