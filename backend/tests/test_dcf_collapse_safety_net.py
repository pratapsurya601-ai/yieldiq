"""
Tests for backend.services.dcf_collapse_safety_net.

Coverage (per the PR acceptance criteria):
  1. Collapsed FV (₹0.77 vs ₹405) → safety net engages, Tier 2
     fallback produces a sensible FV.
  2. Normal FV (₹500 vs ₹600) → safety net stays out of the way.
  3. Inflated FV (₹2000 vs ₹400) → safety net engages on the "over"
     side too.
  4. Cyclical-trough sector (e.g. "Steel") → safety net does NOT
     fire (the trough anchor owns that case).
  5. Sector engine already fired (e.g. rate_base for POWERGRID) →
     safety net does NOT fire (engine is authoritative).
  6. Tier 2 also fails → fallback returns None, caller is expected
     to set verdict=data_limited.
  7. is_fv_unreasonable() boundary cases (None / 0 / exact LO / HI).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest

# Make `backend.…` importable when tests are run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.services import dcf_collapse_safety_net as sn
from backend.services.dcf_collapse_safety_net import (
    COLLAPSED_RATIO_LO,
    INFLATED_RATIO_HI,
    SECTOR_ENGINE_AUTHORITATIVE,
    CYCLICAL_SECTORS_TROUGH_ALLOWED,
    attempt_tier2_fallback,
    is_fv_unreasonable,
)


# ──────────────────────────────────────────────────────────────────
# Helpers — stub Tier 2 so the safety-net tests do not depend on
# the real cohort engine (which needs DB-backed peer rows).
# ──────────────────────────────────────────────────────────────────

def _install_tier2_stub(monkeypatch, return_value):
    """Replace compute_tier2_fair_value with a stub that returns
    `return_value` regardless of inputs. Lets us drive each branch.
    """
    fake_mod = ModuleType("backend.services.tier2_cohort_valuation_service")

    def _fake_compute(ticker, sector, financials, peers):
        return return_value

    fake_mod.compute_tier2_fair_value = _fake_compute  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "backend.services.tier2_cohort_valuation_service",
        fake_mod,
    )


# ──────────────────────────────────────────────────────────────────
# 1. is_fv_unreasonable — pure heuristic, no Tier 2 dependency
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "fv,price,expected",
    [
        # Collapsed cases (the bug we're fixing)
        (0.77, 405.0, True),   # INDIACEM-shape: ratio 0.0019
        (15.60, 245.0, True),  # ratio 0.064
        (19.25, 304.0, True),  # ratio 0.063
        # Inflated cases (37 "over" outliers in day-1 reconciliation)
        (2000.0, 400.0, False),# ratio 5.0 — exactly at HI is "reasonable" (> not >=)
        (2400.0, 400.0, True), # ratio 6.0 — above HI
        (2001.0, 400.0, True), # ratio 5.0025 — just above HI
        # Normal cases — stay out of the way
        (500.0, 600.0, False), # ratio 0.83
        (450.0, 400.0, False), # ratio 1.125 (slightly above CMP)
        (300.0, 400.0, False), # ratio 0.75
        (40.0, 400.0, False),  # ratio 0.10 — exactly at LO is "reasonable" (< not <=)
        # Boundary just below LO
        (39.0, 400.0, True),   # ratio 0.0975
        # Garbage inputs
        (0.0, 400.0, False),
        (-50.0, 400.0, False),
        (100.0, 0.0, False),
        (None, 400.0, False),
        (100.0, None, False),
    ],
)
def test_is_fv_unreasonable(fv, price, expected):
    assert is_fv_unreasonable(fv, price) is expected


def test_thresholds_are_documented_values():
    # Belt-and-braces: if someone retunes the bands, the test fails
    # so the PR description and design discipline get updated too.
    assert COLLAPSED_RATIO_LO == 0.1
    assert INFLATED_RATIO_HI == 5.0


# ──────────────────────────────────────────────────────────────────
# 2. Collapsed FV → Tier 2 fallback engages
# ──────────────────────────────────────────────────────────────────

def test_collapsed_fv_triggers_tier2_fallback(monkeypatch):
    """INDIACEM-shape: DCF emits ₹0.77 vs CMP ₹405. Tier 2 returns
    a sensible ₹350. Safety net should swap in ₹350 with the
    `tier2_fallback_after_dcf_collapse` source label."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 350.0})

    out = attempt_tier2_fallback(
        ticker="INDIACEM",
        current_fv=0.77,
        current_price=405.0,
        sector="Cement",
        sector_engine_used="dcf",
        financials={"eps": 12.0, "roce": 8.0, "piotroski": 4,
                    "market_cap_cr": 12000.0},
        peers=[{"ticker": "ULTRACEMCO", "pe": 30}],
    )
    assert out is not None
    new_fv, source = out
    assert new_fv == 350.0
    assert source == "tier2_fallback_after_dcf_collapse"


def test_inflated_fv_triggers_tier2_fallback(monkeypatch):
    """Over-case: DCF emits ₹2,000 on a ₹400 stock. Safety net
    engages on the inflated side too — Tier 2 returns ₹450."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 450.0})

    out = attempt_tier2_fallback(
        ticker="SOMEOVER",
        current_fv=2400.0,  # ratio 6.0 — definitively above HI=5.0
        current_price=400.0,
        sector="Capital Goods",
        sector_engine_used="dcf",
    )
    assert out is not None
    new_fv, source = out
    assert new_fv == 450.0
    assert source == "tier2_fallback_after_dcf_collapse"


# ──────────────────────────────────────────────────────────────────
# 3. Normal FV → safety net never fires
# ──────────────────────────────────────────────────────────────────

def test_normal_fv_no_trigger(monkeypatch):
    """When DCF is within band, the safety net is a no-op. Note that
    we install a Tier 2 stub that WOULD return a value — proving the
    no-op is happening at the `is_fv_unreasonable` guard, not because
    Tier 2 failed."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 999.0})

    out = attempt_tier2_fallback(
        ticker="TCS",
        current_fv=4200.0,
        current_price=3800.0,
        sector="IT",
        sector_engine_used="dcf",
    )
    assert out is None


# ──────────────────────────────────────────────────────────────────
# 4. Cyclical-trough sector → safety net stays out (anchor owns it)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sector", sorted(CYCLICAL_SECTORS_TROUGH_ALLOWED))
def test_cyclical_trough_sectors_skip(monkeypatch, sector):
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 999.0})

    out = attempt_tier2_fallback(
        ticker="TATASTEEL",
        current_fv=50.0,        # would otherwise trip is_fv_unreasonable
        current_price=160.0,    # ratio 0.31 (above LO=0.1 actually) — bump
        sector=sector,
        sector_engine_used="dcf",
    )
    # Even at a collapsed ratio, the cyclical veto kicks in BEFORE
    # we hit Tier 2, so the stub's 999 must never appear.
    assert out is None

    # And at a definitively collapsed ratio:
    out2 = attempt_tier2_fallback(
        ticker="TATASTEEL",
        current_fv=5.0,
        current_price=160.0,    # ratio 0.031 — below LO
        sector=sector,
        sector_engine_used="dcf",
    )
    assert out2 is None


# ──────────────────────────────────────────────────────────────────
# 5. Sector engine already fired → safety net stays out
# ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("engine", sorted(SECTOR_ENGINE_AUTHORITATIVE))
def test_sector_engine_authoritative_no_trigger(monkeypatch, engine):
    """POWERGRID (rate_base), HDFCBANK (pb_ratio), SBILIFE
    (appraisal_value), EMBASSY (reit_nav_dpu_required), etc.
    The dedicated engine is the right answer — safety net must
    never second-guess it, even if the engine's FV happens to be
    far from price (e.g. distressed bank at 0.3× book)."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 999.0})

    out = attempt_tier2_fallback(
        ticker="POWERGRID",
        current_fv=2.0,
        current_price=300.0,    # ratio 0.0067 — definitively collapsed
        sector="Utilities",
        sector_engine_used=engine,
    )
    assert out is None


# ──────────────────────────────────────────────────────────────────
# 6. Tier 2 also fails → caller must set data_limited
# ──────────────────────────────────────────────────────────────────

def test_tier2_returns_none_safety_net_returns_none(monkeypatch):
    """PAYTM / PINELABS shape: DCF collapses, AND Tier 2 cannot
    compute (loss-making EPS / no peer cohort). Safety net returns
    None — the wire-in code in service.py is expected to set
    verdict=data_limited in this case."""
    _install_tier2_stub(monkeypatch, return_value=None)

    out = attempt_tier2_fallback(
        ticker="PAYTM",
        current_fv=15.6,
        current_price=900.0,
        sector="Financial Services",
        sector_engine_used="dcf",
    )
    assert out is None


def test_tier2_returns_zero_or_negative_safety_net_returns_none(monkeypatch):
    """Defensive: Tier 2 should never emit non-positive FV, but if
    it does the safety net must not propagate it."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 0.0})

    out = attempt_tier2_fallback(
        ticker="WEIRD",
        current_fv=0.5,
        current_price=300.0,
        sector="IT",
        sector_engine_used="dcf",
    )
    assert out is None


def test_tier2_returns_unreasonable_fv_safety_net_declines(monkeypatch):
    """If Tier 2 ALSO produces a ratio outside [0.1, 5.0], we have
    two failing engines — honest answer is data_limited."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 5.0})

    out = attempt_tier2_fallback(
        ticker="BROKEN",
        current_fv=1.0,
        current_price=400.0,
        sector="IT",
        sector_engine_used="dcf",
    )
    assert out is None


def test_tier2_import_failure_safety_net_returns_none(monkeypatch):
    """If the tier2 module itself blows up on import, the safety
    net must degrade silently (NEVER break analysis)."""
    # Insert a broken module that raises on attribute access.
    broken = ModuleType("backend.services.tier2_cohort_valuation_service")

    def _raise(*a, **kw):
        raise RuntimeError("simulated tier2 outage")

    broken.compute_tier2_fair_value = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "backend.services.tier2_cohort_valuation_service",
        broken,
    )

    out = attempt_tier2_fallback(
        ticker="ANY",
        current_fv=0.5,
        current_price=400.0,
        sector="IT",
        sector_engine_used="dcf",
    )
    assert out is None


# ──────────────────────────────────────────────────────────────────
# 7. Misc input-edge cases
# ──────────────────────────────────────────────────────────────────

def test_empty_ticker_no_trigger():
    assert attempt_tier2_fallback(
        ticker="", current_fv=1.0, current_price=400.0,
        sector="IT", sector_engine_used="dcf",
    ) is None


def test_none_sector_engine_treated_as_generic_dcf(monkeypatch):
    """When sector_engine_used is None we should NOT treat the call as
    coming from an authoritative engine — it's just generic DCF that
    didn't tag itself. Safety net should still engage on collapse."""
    _install_tier2_stub(monkeypatch, return_value={"fair_value": 320.0})

    out = attempt_tier2_fallback(
        ticker="ANYGEN",
        current_fv=2.0,
        current_price=400.0,
        sector="IT",
        sector_engine_used=None,
    )
    assert out == (320.0, "tier2_fallback_after_dcf_collapse")
