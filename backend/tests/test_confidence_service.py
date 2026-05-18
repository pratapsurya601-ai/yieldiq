"""Tests for backend.services.confidence_service (Layer C, PR 1).

Pure-function tests — no DB / network. Each fixture mimics the
``enriched`` / ``raw`` shapes that ``_get_full_analysis_inner``
hands to the scoring service. The expected ranges in the asserts
encode the design intent (TCS-shape > 80, MANKIND-shape < 60, etc).
"""

from __future__ import annotations

import datetime as _dt

import pytest

from backend.services.confidence_service import (
    TIER1_TICKERS,
    compute_all_scores,
    compute_data_quality_score,
    compute_model_confidence_score,
    compute_valuation_stability_score,
)


# ───────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────
TODAY = _dt.date.today()


def _tcs_shape() -> dict:
    """Stable large-cap IT — clean data, full history."""
    return {
        "latest_period_end": (TODAY - _dt.timedelta(days=120)).isoformat(),
        "annual_rows": 8,
        "quarterly_rows": 12,
        "currency": "INR",
        "current_price": 3500.0,
        "shares_outstanding": 3_620_000_000,
        "dcf_reliable": True,
        "data_issues": [],
        "sector": "Information Technology",
    }


def _mankind_shape() -> dict:
    """Recent IPO — full data but engine fit is weak."""
    return {
        "latest_period_end": (TODAY - _dt.timedelta(days=180)).isoformat(),
        "annual_rows": 3,
        "quarterly_rows": 6,
        "currency": "INR",
        "current_price": 2200.0,
        "shares_outstanding": 400_000_000,
        "dcf_reliable": True,
        "data_issues": [],
        "sector": "Pharma",
    }


def _siemens_shape() -> dict:
    """Capital-goods cyclical — data is fine, FV swings hard."""
    return {
        "latest_period_end": (TODAY - _dt.timedelta(days=90)).isoformat(),
        "annual_rows": 10,
        "quarterly_rows": 16,
        "currency": "INR",
        "current_price": 7000.0,
        "shares_outstanding": 355_000_000,
        "dcf_reliable": True,
        "data_issues": [],
        "sector": "Capital Goods",
    }


def _nivabupa_shape() -> dict:
    """Sparse data — missing currency, stale filings, few rows."""
    return {
        "latest_period_end": None,
        "annual_rows": 1,
        "quarterly_rows": 1,
        "currency": "",
        "current_price": None,
        "shares_outstanding": None,
        "dcf_reliable": False,
        "data_issues": ["incomplete_pl", "missing_balance_sheet"],
        "sector": "Insurance",
    }


def _etf_shape() -> dict:
    """ETF — verdict is data_limited but scores still computed."""
    return {
        "latest_period_end": (TODAY - _dt.timedelta(days=30)).isoformat(),
        "annual_rows": 0,
        "quarterly_rows": 0,
        "currency": "INR",
        "current_price": 250.0,
        "shares_outstanding": 100_000_000,
        "dcf_reliable": False,
        "data_issues": [],
        "sector": "ETF",
    }


# ───────────────────────────────────────────────────────────────────
# data_quality_score
# ───────────────────────────────────────────────────────────────────
def test_dq_tcs_shape_above_80():
    assert compute_data_quality_score(_tcs_shape()) > 80


def test_dq_nivabupa_shape_below_50():
    assert compute_data_quality_score(_nivabupa_shape()) < 50


def test_dq_none_input_is_zero():
    assert compute_data_quality_score(None) == 0


def test_dq_stale_filing_deducts():
    enriched = _tcs_shape()
    enriched["latest_period_end"] = (TODAY - _dt.timedelta(days=400)).isoformat()
    stale = compute_data_quality_score(enriched)
    fresh = compute_data_quality_score(_tcs_shape())
    assert stale < fresh


# ───────────────────────────────────────────────────────────────────
# model_confidence_score
# ───────────────────────────────────────────────────────────────────
def test_mc_tier1_starts_at_90():
    assert "TCS" in TIER1_TICKERS
    score = compute_model_confidence_score(
        "TCS", valuation_method="dcf", sector="Information Technology"
    )
    assert score == 90


def test_mc_non_tier1_starts_at_70():
    score = compute_model_confidence_score(
        "RANDOMCO", valuation_method="dcf", sector="Pharma"
    )
    assert score == 70


def test_mc_recent_ipo_drops_below_60():
    score = compute_model_confidence_score(
        "MANKIND",
        valuation_method="sector_relative_recent_ipo",
        sector="Pharma",
        is_recent_ipo=True,
    )
    # base 70 - 20 (low-confidence method) - 25 (recent_ipo) = 25
    assert score < 60


def test_mc_cyclical_deducts():
    base = compute_model_confidence_score("RANDOMCO", valuation_method="dcf", sector="IT")
    cyc = compute_model_confidence_score(
        "RANDOMCO", valuation_method="dcf", sector="Capital Goods"
    )
    assert cyc < base


def test_mc_clamps_at_zero():
    score = compute_model_confidence_score(
        "RANDOMCO",
        valuation_method="sector_relative_recent_ipo",
        sector="Capital Goods",
        is_recent_ipo=True,
        extra_flags={
            "analyst_opinion_required": True,
            "data_limited": True,
            "dcf_unreliable": True,
        },
    )
    assert score >= 0


# ───────────────────────────────────────────────────────────────────
# valuation_stability_score
# ───────────────────────────────────────────────────────────────────
def test_vs_stable_series_high():
    # ±1% noise
    fv = [100.0, 101.0, 99.5, 100.5]
    assert compute_valuation_stability_score("TCS", fv_history=fv) >= 85


def test_vs_whippy_series_low():
    # Capital-goods style swings — also floor-capped by sector
    fv = [80.0, 120.0, 95.0, 140.0]
    assert compute_valuation_stability_score(
        "SIEMENS", fv_history=fv, sector="Capital Goods"
    ) < 50


def test_vs_cyclical_floor_cap():
    # Calm window for a cyclical — should still be capped at 70
    fv = [100.0, 100.5, 99.8, 100.2]
    score = compute_valuation_stability_score(
        "SIEMENS", fv_history=fv, sector="Capital Goods"
    )
    assert score <= 70


def test_vs_no_history_is_neutral():
    assert compute_valuation_stability_score("TCS", fv_history=None) == 70
    assert compute_valuation_stability_score("TCS", fv_history=[]) == 70


# ───────────────────────────────────────────────────────────────────
# Composite scenarios (the table in the task spec)
# ───────────────────────────────────────────────────────────────────
def test_tcs_all_above_80():
    s = compute_all_scores(
        "TCS",
        enriched=_tcs_shape(),
        valuation_method="dcf",
        sector="Information Technology",
        fv_history=[3500.0, 3520.0, 3490.0, 3510.0],
    )
    assert s["data_quality"] > 80
    assert s["model_confidence"] > 80
    assert s["valuation_stability"] > 80


def test_mankind_model_confidence_below_60():
    s = compute_all_scores(
        "MANKIND",
        enriched=_mankind_shape(),
        valuation_method="sector_relative_recent_ipo",
        sector="Pharma",
        is_recent_ipo=True,
        fv_history=[2200.0, 2150.0, 2250.0, 2180.0],
    )
    assert s["model_confidence"] < 60


def test_siemens_valuation_stability_below_50():
    s = compute_all_scores(
        "SIEMENS",
        enriched=_siemens_shape(),
        valuation_method="dcf",
        sector="Capital Goods",
        fv_history=[6000.0, 9000.0, 7500.0, 11000.0],
    )
    assert s["valuation_stability"] < 50


def test_nivabupa_data_quality_below_50():
    s = compute_all_scores(
        "NIVABUPA",
        enriched=_nivabupa_shape(),
        valuation_method="pb_ratio",
        sector="Insurance",
    )
    assert s["data_quality"] < 50


def test_etf_scores_still_computed():
    """ETFs have verdict=data_limited but we still emit all 3 scores
    for UI consistency. They should be present (int) — not None."""
    s = compute_all_scores(
        "NIFTYBEES",
        enriched=_etf_shape(),
        valuation_method="etf_nav_based",
        sector="ETF",
        extra_flags={"data_limited": True, "dcf_unreliable": True},
    )
    for k in ("data_quality", "model_confidence", "valuation_stability"):
        assert isinstance(s[k], int)
        assert 0 <= s[k] <= 100
