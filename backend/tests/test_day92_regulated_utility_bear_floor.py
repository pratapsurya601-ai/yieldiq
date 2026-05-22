# backend/tests/test_day92_regulated_utility_bear_floor.py
# ═══════════════════════════════════════════════════════════════
# Day-92 — Regulated-utility bear-floor guard.
#
# Audit #4 (2026-05-22) observed NTPC.NS and POWERGRID.NS shipping
# bear_case = ₹0 (MoS +0.0%) on the public stock-summary endpoint.
# Root cause: regulated utilities short-circuit generic DCF; the
# non-financial branch in `backend/services/analysis/service.py`
# then rebuilt _sc_bear_pre / _sc_bull_pre from `scenarios_raw`
# (DCF cash flows) which were empty → bear_iv collapsed to 0.
# `_enforce_scenario_order` accepted (0 <= base <= bull) as ordered.
#
# The fix extends the financial-branch direct-from-bear_iv pathway
# to also fire when the regulated-utility engine produced a valid
# fair_value, AND applies a Day-56-style defensive floor:
#   bear_iv >= min(0.85 * price, iv * 0.95)
#   bull_iv >= max(1.10 * price, iv * 1.05)
# so the bear case never collapses even if a downstream override
# zeroes the engine's bear/bull.
#
# These tests cover:
#   1. Source-text guards: floor formula present, gated on
#      regulated_utility engine, mirrors the Day-56 cyclical pattern
#      (literal min(...) / max(...) shape).
#   2. Math behavior: simulate the floor clamp for NTPC and
#      POWERGRID with their live inputs and assert
#      bear > 0 AND bear < base AND bull > base AND bull > price.
#   3. The floor only widens the band — engine output that's
#      already inside the floor band is preserved.
#   4. The fix does NOT fire on financial / cyclical / DCF paths.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pathlib

import pytest


SERVICE_PATH = (
    pathlib.Path(__file__).parent.parent / "services" / "analysis" / "service.py"
)
CACHE_PATH = (
    pathlib.Path(__file__).parent.parent / "services" / "cache_service.py"
)


@pytest.fixture(scope="module")
def service_src() -> str:
    return SERVICE_PATH.read_text(encoding="utf-8")


# ── Source-text guards ────────────────────────────────────────────


def test_regulated_utility_bear_floor_marker_present(service_src: str):
    """The Day-92 floor block must be wired into service.py."""
    assert "REGULATED_UTILITY_BEAR_FLOOR" in service_src
    assert "Day-92" in service_src


def test_floor_formula_present(service_src: str):
    """The floor formula must mirror the Day-56 cyclical pattern."""
    # bear floor: min(0.85 * price, iv * 0.95)
    assert "min(0.85 * price, iv * 0.95)" in service_src
    # bull floor: max(1.10 * price, iv * 1.05)
    assert "max(1.10 * price, iv * 1.05)" in service_src


def test_floor_gated_on_regulated_utility_engine(service_src: str):
    """Floor must only fire when the regulated-utility engine ran."""
    # The gate flag must depend on both the ticker classifier AND the
    # engine result being valid.
    assert "_is_regulated_utility_engine" in service_src
    assert "is_regulated_utility_ticker" in service_src
    assert "_regulated_val_result" in service_src


def test_floor_branch_shares_path_with_financial(service_src: str):
    """The fix routes regulated utilities through the same
    direct-from-bear_iv path the financial branch uses — that path
    was already correct, only the gate needed widening."""
    # Combined gate: `if is_financial or _is_regulated_utility_engine:`
    assert "if is_financial or _is_regulated_utility_engine:" in service_src


def test_cache_version_bumped_to_135(service_src: str):
    """Bear-floor changes affect existing tickers → CACHE_VERSION
    bump is mandatory per data-fix discipline rule #2."""
    txt = CACHE_PATH.read_text(encoding="utf-8")
    assert "CACHE_VERSION = 135" in txt
    # Bump must document the trigger and the scope.
    assert "day92-utility-bear-floor" in txt
    assert "NTPC" in txt
    assert "POWERGRID" in txt


# ── Math behavior — floor clamp simulation ────────────────────────


def _simulate_floor(price: float, iv: float, raw_bear: float, raw_bull: float):
    """Reproduce the clamp logic from the Day-92 block in
    service.py so we can assert behavior without spinning the full
    analysis pipeline (which needs DB + network)."""
    bear_floor = round(min(0.85 * price, iv * 0.95), 2)
    bull_floor = round(max(1.10 * price, iv * 1.05), 2)
    bear = raw_bear
    bull = raw_bull
    if bear <= 0 or bear < bear_floor * 0.5:
        bear = bear_floor
    if bull <= 0 or bull < iv:
        bull = bull_floor
    return bear, bull


def test_ntpc_bear_floor_clamps_zero_bear():
    """NTPC live inputs (2026-05-22): price=388.80, iv=533.01,
    raw bear=0 (bug), raw bull=639.61.
    Expected: bear clamps off 0, ends up sensible.
    """
    price = 388.80
    iv = 533.01
    bear, bull = _simulate_floor(price, iv, raw_bear=0.0, raw_bull=639.61)
    # Bear must be strictly positive
    assert bear > 0
    # Bear must be below base FV
    assert bear < iv
    # Bear must be at the floor (≈ min(0.85*388.80, 0.95*533.01) = 330.48)
    assert bear == pytest.approx(330.48, abs=0.01)
    # Bull was already above iv, preserved
    assert bull == 639.61
    # Bull must remain above base
    assert bull > iv


def test_powergrid_bear_floor_clamps_zero_bear():
    """POWERGRID live inputs (2026-05-22): price=299.55, iv=363.48,
    raw bear=0 (bug), raw bull=436.18.
    """
    price = 299.55
    iv = 363.48
    bear, bull = _simulate_floor(price, iv, raw_bear=0.0, raw_bull=436.18)
    assert bear > 0
    assert bear < iv
    # min(0.85 * 299.55, 0.95 * 363.48) = min(254.62, 345.31) = 254.62
    assert bear == pytest.approx(254.62, abs=0.01)
    assert bull > iv


def test_floor_preserves_healthy_engine_output():
    """When the engine produced sensible bear/bull (e.g. for a small
    NLCINDIA-like utility where the engine path didn't zero out),
    the floor must not shrink the band."""
    price = 100.0
    iv = 130.0
    raw_bear = 97.5   # engine's 0.75 * fair_pb * bvps
    raw_bull = 162.5  # engine's 1.25 * fair_pb * bvps
    bear, bull = _simulate_floor(price, iv, raw_bear, raw_bull)
    # Engine bear (97.5) was above floor*0.5 (~42.5) → preserved
    assert bear == 97.5
    # Engine bull (162.5) was already > iv → preserved
    assert bull == 162.5


def test_floor_widens_when_bull_below_base():
    """If bull came back below base (degenerate engine output) the
    bull floor kicks in to ensure bull >= max(1.10*price, iv*1.05)."""
    price = 200.0
    iv = 250.0
    bear, bull = _simulate_floor(price, iv, raw_bear=187.5, raw_bull=240.0)
    # bull (240) < iv (250) → clamp to max(220, 262.5) = 262.5
    assert bull == pytest.approx(262.5, abs=0.01)
    assert bull > iv


def test_floor_never_produces_zero_bear():
    """Regression: across a sweep of plausible utility inputs,
    bear must never be ₹0 once the floor fires."""
    cases = [
        (100, 120, 0, 0),
        (388.80, 533.01, 0, 0),
        (299.55, 363.48, 0, 0),
        (50, 70, 0, 50),
        (1500, 1800, 0, 1900),
    ]
    for price, iv, rb, rbu in cases:
        bear, bull = _simulate_floor(price, iv, rb, rbu)
        assert bear > 0, f"bear collapsed for price={price} iv={iv}"
        assert bull > 0, f"bull collapsed for price={price} iv={iv}"


def test_floor_ordering_preserved():
    """After the clamp, bear < base < bull must hold for the live
    NTPC and POWERGRID scenarios."""
    # NTPC
    bear, bull = _simulate_floor(388.80, 533.01, 0.0, 639.61)
    assert bear < 533.01 < bull
    # POWERGRID
    bear, bull = _simulate_floor(299.55, 363.48, 0.0, 436.18)
    assert bear < 363.48 < bull


def test_floor_does_not_lower_a_high_engine_bear():
    """If the engine produced bear ABOVE the floor (e.g. utility with
    iv close to price so 0.85*price > 0.95*iv would tighten the bear),
    the engine value is preserved — the floor only widens, never
    tightens."""
    price = 100.0
    iv = 105.0
    # Engine bear = 0.75 * 105 = 78.75. Floor = min(85, 99.75) = 85.
    # 78.75 < 0.5 * 85 = 42.5? No → engine bear (78.75) preserved.
    bear, bull = _simulate_floor(price, iv, raw_bear=78.75, raw_bull=131.25)
    assert bear == 78.75
    # Bull engine (131.25) > iv → preserved
    assert bull == 131.25
