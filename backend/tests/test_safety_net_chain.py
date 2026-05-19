"""Integration tests for the DCF-collapse safety-net rescue chain.

The chain is:
    Tier 2 cohort (P/E)
      ↓ None
    Platform P/S engine
      ↓ None
    Story-DCF engine
      ↓ None
    data_limited (verdict-gate suppression)

These tests verify the chain orchestration in
`backend/services/dcf_collapse_safety_net.attempt_tier2_fallback`,
NOT the individual engines (which have their own unit-test files).
The goal is to lock in the rung-by-rung fallback contract so future
refactors don't silently break the rescue ladder.
"""
from __future__ import annotations

import pytest

from backend.services.dcf_collapse_safety_net import (
    attempt_tier2_fallback,
    is_fv_unreasonable,
    COLLAPSED_RATIO_LO,
    INFLATED_RATIO_HI,
    SECTOR_ENGINE_AUTHORITATIVE,
)


# ── Trigger condition: is_fv_unreasonable ─────────────────────


def test_fv_zero_is_treated_as_unreasonable():
    """Day-5 fix: FV=0 must trigger safety net, not skip it as
    'uncomputable'. Platform stocks routinely produce DCF=0."""
    assert is_fv_unreasonable(0, 100) is True
    assert is_fv_unreasonable(-50, 100) is True


def test_fv_in_acceptable_band_no_trigger():
    """0.30 ≤ ratio ≤ 3.5 → safety net stays out."""
    assert is_fv_unreasonable(50, 100) is False    # 0.5 — fine
    assert is_fv_unreasonable(150, 100) is False   # 1.5 — fine
    assert is_fv_unreasonable(300, 100) is False   # 3.0 — fine


def test_fv_below_lo_triggers():
    """ratio < 0.30 → safety net triggers (Day-4 widening)."""
    assert is_fv_unreasonable(25, 100) is True   # 0.25
    assert is_fv_unreasonable(15, 100) is True   # 0.15
    assert is_fv_unreasonable(1, 100) is True    # 0.01


def test_fv_above_hi_triggers():
    """ratio > 3.5 → safety net triggers."""
    assert is_fv_unreasonable(400, 100) is True  # 4.0
    assert is_fv_unreasonable(1000, 100) is True


def test_zero_price_blocks_trigger():
    """Without price we can't compute ratio — return False so caller
    runs its own None-handling path."""
    assert is_fv_unreasonable(50, 0) is False
    assert is_fv_unreasonable(50, None) is False


# ── Guard rails: never override dedicated engines ─────────────


def test_sector_engine_authoritative_blocks_fallback():
    """If sector_engine_used is one of the authoritative engines
    (rate_base, pb_ratio, appraisal_value, etc.), safety net stays
    out. Tier-1 engines own their cohort."""
    result = attempt_tier2_fallback(
        ticker="POWERGRID.NS",
        current_fv=10.0,
        current_price=300.0,
        sector="Power",
        sector_engine_used="rate_base",  # authoritative
        peers=[],
    )
    assert result is None


def test_cyclical_trough_sector_blocks_fallback():
    """Metals/Oil at trough are handled by the trough anchor in
    service.py, not by Tier 2."""
    result = attempt_tier2_fallback(
        ticker="JSWSTEEL.NS",
        current_fv=10.0,
        current_price=500.0,
        sector="metals & mining",
        sector_engine_used="dcf",
        peers=[],
    )
    assert result is None


# ── Rescue chain ordering ─────────────────────────────────


def test_no_peers_returns_none_after_all_rungs(monkeypatch):
    """With empty peers, Tier 2 + Platform P/S can't fire. Story DCF
    might still fire IF sector matches AND financials provided.
    Without financials → None."""
    result = attempt_tier2_fallback(
        ticker="UNKNOWN_TICKER.NS",
        current_fv=10.0,
        current_price=500.0,
        sector="cement",       # known sector, but no peers passed
        sector_engine_used="dcf",
        peers=[],
        financials={},
    )
    # No peers + no rich financials → all three rungs return None
    assert result is None


def test_story_dcf_rung_fires_for_platform_with_no_peers():
    """Even when peers=[] (Tier 2 + Platform P/S can't fire), story-
    DCF can rescue an internet_platform / fintech_broker sector
    ticker using industry defaults from INDUSTRY_STORY_DEFAULTS.

    Financials shape: revenue large enough that the story-DCF FV
    lands ABOVE the safety-net rescue band (>= 0.30 × CMP). With
    revenue=₹30,000 Cr × shares=20 Cr × ecommerce defaults, the
    discounted FCFF + TV produces a per-share FV well above 0.30 ×
    1000 = ₹300 threshold."""
    result = attempt_tier2_fallback(
        ticker="UNKNOWNPLATFORM.NS",
        current_fv=0.0,            # DCF=0 — trigger condition (FV=0)
        current_price=1000.0,
        sector="Internet Platform",
        sector_engine_used="dcf",
        peers=[],                  # no peers for tier 2 / platform P/S
        financials={
            "revenue": 30_000e7,   # ₹30,000 Cr — large enough
            "shares": 20e7,        # 20 Cr shares
            "current_price": 1000.0,
        },
    )
    # Story-DCF should produce a finite FV from ecommerce default
    assert result is not None
    fv, source = result
    assert fv > 0
    assert source == "story_dcf_after_dcf_collapse"


def test_unreasonable_post_rescue_fv_refused():
    """If story-DCF produces an FV that's still in the unreasonable
    band (e.g. due to bad operator-curated story params), the rescue
    refuses it — data_limited is better than shipping another broken
    FV."""
    # Build a hypothetical case where story-DCF produces FV close to
    # zero (e.g. low revenue + heavy reinvestment). The safety net
    # must catch this and return None rather than ship it.
    result = attempt_tier2_fallback(
        ticker="TINY_PLATFORM.NS",
        current_fv=0.0,
        current_price=1000.0,
        sector="Internet Platform",
        sector_engine_used="dcf",
        peers=[],
        financials={
            "revenue": 10e7,       # very small revenue
            "shares": 1e9,         # massive shares
            "current_price": 1000.0,
        },
    )
    # Either the story-DCF produces None (insufficient inputs) or
    # produces something so small it's caught as still-unreasonable
    # → return None either way. The key is: never ship a rescue FV
    # that itself is broken.
    if result is not None:
        fv, _ = result
        # If a result IS returned, it must NOT itself be unreasonable
        assert not is_fv_unreasonable(fv, 1000.0)


# ── Constants sanity ────────────────────────────────────────


def test_safety_net_constants():
    """Lock in the threshold values so they can't drift accidentally."""
    assert COLLAPSED_RATIO_LO == 0.30
    assert INFLATED_RATIO_HI == 3.5


def test_authoritative_engines_set():
    """The engines that own their cohort and should never be
    overridden by safety net."""
    expected = {
        "rate_base", "appraisal_value", "pb_plus_land_bank",
        "reit_nav_dpu_required", "etf_nav_based",
        "holding_company_sotp_required",
        "pb_ratio", "pb_residual_income",
        "sector_relative_recent_ipo",
    }
    assert expected.issubset(SECTOR_ENGINE_AUTHORITATIVE)
