# backend/tests/test_sector_wacc_tg_calibrated.py
# ═══════════════════════════════════════════════════════════════════
# T1.3 (2026-06-09) — per-sector calibrated WACC + terminal-growth.
#
# Mirrors the Day-107a / Day-107b / Day-109a / Day-110b cohort
# source-text + helper test patterns.
#
# Asserts the SSOT tables in
# backend/services/analysis/sector_overrides.py expose Damodaran-
# India-2026 anchored values via the two public helpers:
#   - get_calibrated_wacc(sector, sub_sector=None) -> Optional[float]
#   - get_calibrated_terminal_growth(sector, sub_sector=None)
#         -> Optional[float]
#
# Phase A scope: tables + helpers only. No DCF read-path wiring.
# When wiring lands in a follow-up PR, the
# ``test_calibrated_values_match_existing_cohort_constants`` guard
# below ensures the calibration stays consistent with the per-cohort
# WACC floors / TG lifts that already exist in service.py + forecaster.
# ═══════════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest

from backend.services.analysis.sector_overrides import (
    SECTOR_WACC_CALIBRATED,
    SECTOR_TERMINAL_GROWTH_CALIBRATED,
    SECTOR_WACC_CALIBRATED_BY_SUB,
    SECTOR_TERMINAL_GROWTH_CALIBRATED_BY_SUB,
    get_calibrated_wacc,
    get_calibrated_terminal_growth,
    FMCG_TG_TOP,
    FMCG_TG_TIER2,
    FMCG_TG_TIER3,
    FMCG_TG_ITC,
)


# ─────────────────────────────────────────────────────────────────
# 1. Sector-only WACC lookup
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sector,expected_wacc",
    [
        # Tier-1 IT (low beta, USD revenue mix)
        ("IT", 0.115),
        ("Information Technology", 0.115),
        # Financials
        ("Banking", 0.118),
        ("NBFC", 0.125),
        ("Insurance", 0.112),
        # Consumer / defensive
        ("FMCG", 0.105),
        ("Pharma", 0.120),
        # Cyclicals
        ("Automobiles", 0.135),
        ("Cement", 0.135),
        ("Metals & Mining", 0.145),
        ("Oil & Gas", 0.125),
        # Regulated / low-beta
        ("Power & Utilities", 0.095),
        ("Real Estate", 0.098),
        # High-beta
        ("Hotels & Tourism", 0.140),
        ("Aviation", 0.160),
        ("Media", 0.145),
        # Telco + caps
        ("Telecom", 0.110),
        ("Capital Goods", 0.130),
        ("Defense", 0.105),
    ],
)
def test_get_calibrated_wacc_known_sectors(sector, expected_wacc):
    """Every canonical sector label in the T1.3 table returns its
    Damodaran-India-2026 anchored WACC."""
    got = get_calibrated_wacc(sector)
    assert got is not None, f"{sector!r} must have a calibrated WACC"
    assert got == pytest.approx(expected_wacc, abs=1e-6), (
        f"{sector!r} WACC: got {got}, expected {expected_wacc}"
    )


# ─────────────────────────────────────────────────────────────────
# 2. Sector-only Terminal Growth lookup
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sector,expected_tg",
    [
        ("IT", 0.050),
        ("Information Technology", 0.050),
        ("Banking", 0.055),
        ("NBFC", 0.055),
        ("Insurance", 0.060),
        # FMCG default = staples (5.5%); tobacco sub_sector overrides → 3.0%
        ("FMCG", 0.055),
        # Pharma default = chronic+branded (5.5%); generic-US sub_sector → 4.0%
        ("Pharma", 0.055),
        ("Automobiles", 0.045),
        ("Cement", 0.040),
        ("Metals & Mining", 0.030),
        ("Oil & Gas", 0.025),
        ("Power & Utilities", 0.045),
        ("Real Estate", 0.045),
        ("Telecom", 0.040),
        ("Capital Goods", 0.045),
        ("Hotels & Tourism", 0.050),
        ("Aviation", 0.035),
        ("Defense", 0.055),
    ],
)
def test_get_calibrated_terminal_growth_known_sectors(sector, expected_tg):
    """Every canonical sector label in the T1.3 table returns its
    calibrated terminal growth."""
    got = get_calibrated_terminal_growth(sector)
    assert got is not None, f"{sector!r} must have a calibrated TG"
    assert got == pytest.approx(expected_tg, abs=1e-6), (
        f"{sector!r} TG: got {got}, expected {expected_tg}"
    )


# ─────────────────────────────────────────────────────────────────
# 3. Sub-sector precedence — sub takes priority over sector
# ─────────────────────────────────────────────────────────────────

def test_sub_sector_overrides_fmcg_tobacco_terminal_growth():
    """FMCG default TG is 5.5% (staples); the tobacco sub_sector
    drops it to 3.0% to price in the cigarette regulatory headwind.
    This directly addresses the audit gap from issue #229."""
    sector_only = get_calibrated_terminal_growth("FMCG")
    assert sector_only == pytest.approx(0.055), "FMCG default = staples"

    staples = get_calibrated_terminal_growth("FMCG", "staples")
    assert staples == pytest.approx(0.055), "FMCG staples explicit"

    tobacco = get_calibrated_terminal_growth("FMCG", "tobacco")
    assert tobacco == pytest.approx(0.030), (
        "FMCG tobacco must drop to 3.0% (regulatory headwind)"
    )


def test_sub_sector_overrides_pharma_generic_us_terminal_growth():
    """Pharma default TG is 5.5% (chronic+branded); the
    generic-US sub_sector drops it to 4.0% (price erosion)."""
    sector_only = get_calibrated_terminal_growth("Pharma")
    assert sector_only == pytest.approx(0.055)

    generic_us = get_calibrated_terminal_growth("Pharma", "generic_us")
    assert generic_us == pytest.approx(0.040), (
        "Pharma generic-US must drop to 4.0% (US price erosion)"
    )

    chronic = get_calibrated_terminal_growth("Pharma", "chronic")
    assert chronic == pytest.approx(0.055)


def test_sub_sector_overrides_power_renewable_terminal_growth():
    """Power & Utilities default TG is 4.5% (regulated); renewable
    sub_sector lifts it to 6.0% (demand tailwind)."""
    sector_only = get_calibrated_terminal_growth("Power & Utilities")
    assert sector_only == pytest.approx(0.045)

    regulated = get_calibrated_terminal_growth("Power & Utilities", "regulated")
    assert regulated == pytest.approx(0.045)

    renewable = get_calibrated_terminal_growth("Power & Utilities", "renewable")
    assert renewable == pytest.approx(0.060)


def test_sub_sector_overrides_pharma_generic_us_wacc():
    """Pharma generic-US WACC is 13.0% (higher beta on US price
    erosion exposure) vs 12.0% sector default."""
    sector_only = get_calibrated_wacc("Pharma")
    assert sector_only == pytest.approx(0.120)

    generic_us = get_calibrated_wacc("Pharma", "generic_us")
    assert generic_us == pytest.approx(0.130)


def test_sub_sector_overrides_power_renewable_wacc():
    """Power & Utilities WACC 9.5% (regulated); renewable 10.5%
    (higher commodity / off-take risk)."""
    regulated = get_calibrated_wacc("Power & Utilities", "regulated")
    assert regulated == pytest.approx(0.095)

    renewable = get_calibrated_wacc("Power & Utilities", "renewable")
    assert renewable == pytest.approx(0.105)


def test_sub_sector_overrides_automobiles_segment_wacc():
    """Auto WACC tightens by segment: 2W (13.0%) < 4W (13.5%) < CV (14.0%)
    matching the structural cycle-beta gradient already coded into
    forecaster.py + service.py Day-107c blocks."""
    assert get_calibrated_wacc("Automobiles", "2w") == pytest.approx(0.130)
    assert get_calibrated_wacc("Automobiles", "4w") == pytest.approx(0.135)
    assert get_calibrated_wacc("Automobiles", "cv") == pytest.approx(0.140)


def test_sub_sector_overrides_automobiles_segment_terminal_growth():
    """Auto TG also tracks segment: 2W (5.0%) > 4W (4.5%) > CV (4.0%).
    Matches the per-segment TG lifts already in service.py L1664-1695."""
    assert get_calibrated_terminal_growth("Automobiles", "2w") == pytest.approx(0.050)
    assert get_calibrated_terminal_growth("Automobiles", "4w") == pytest.approx(0.045)
    assert get_calibrated_terminal_growth("Automobiles", "cv") == pytest.approx(0.040)


# ─────────────────────────────────────────────────────────────────
# 4. Unknown sector / None / empty → returns None (no crash)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sector",
    [None, "", "  ", "Unknown Sector", "garbage-string", "Crypto"],
)
def test_get_calibrated_wacc_unknown_returns_none(sector):
    """Unknown / missing sector returns None so the caller falls back
    to CAPM / country default."""
    assert get_calibrated_wacc(sector) is None


@pytest.mark.parametrize(
    "sector",
    [None, "", "  ", "Unknown Sector", "garbage-string", "Crypto"],
)
def test_get_calibrated_terminal_growth_unknown_returns_none(sector):
    assert get_calibrated_terminal_growth(sector) is None


def test_unknown_sub_sector_falls_back_to_sector_value():
    """If sub_sector is provided but no sub-key match exists,
    the helper falls back to the sector-only value (does not
    return None)."""
    # FMCG has no "premium" sub_sector — fall back to FMCG sector default
    fallback_wacc = get_calibrated_wacc("FMCG", "premium")
    assert fallback_wacc == pytest.approx(0.105)

    fallback_tg = get_calibrated_terminal_growth("FMCG", "premium")
    assert fallback_tg == pytest.approx(0.055)


def test_unknown_sector_with_sub_returns_none():
    """If neither sector nor (sector, sub_sector) is in either table,
    returns None — guards against silent matches on garbage input."""
    assert get_calibrated_wacc("Crypto", "btc") is None
    assert get_calibrated_terminal_growth("Crypto", "btc") is None


# ─────────────────────────────────────────────────────────────────
# 5. Table-shape invariants
# ─────────────────────────────────────────────────────────────────

def test_wacc_table_values_in_plausible_band():
    """Every WACC entry sits in the [5%, 20%] band — guard against
    a unit-error (e.g. 11.5 instead of 0.115) sneaking in."""
    for sector, wacc in SECTOR_WACC_CALIBRATED.items():
        assert 0.05 <= wacc <= 0.20, (
            f"{sector!r} WACC {wacc} outside plausible [0.05, 0.20] band"
        )
    for key, wacc in SECTOR_WACC_CALIBRATED_BY_SUB.items():
        assert 0.05 <= wacc <= 0.20, (
            f"sub-key {key!r} WACC {wacc} outside plausible band"
        )


def test_terminal_growth_table_values_in_plausible_band():
    """Every TG entry sits in [1%, 7%] — well below India long-run
    nominal GDP (~9-10%) since TG is a steady-state cap.
    Guards against unit / sign errors."""
    for sector, tg in SECTOR_TERMINAL_GROWTH_CALIBRATED.items():
        assert 0.01 <= tg <= 0.07, (
            f"{sector!r} TG {tg} outside plausible [0.01, 0.07] band"
        )
    for key, tg in SECTOR_TERMINAL_GROWTH_CALIBRATED_BY_SUB.items():
        assert 0.01 <= tg <= 0.07, (
            f"sub-key {key!r} TG {tg} outside plausible band"
        )


def test_terminal_growth_strictly_below_wacc_per_sector():
    """For every sector with both WACC and TG calibrated, the
    Gordon model requires TG < WACC. We tighten to TG < WACC - 2%
    so the DCF safety guard does not need to clamp at run-time."""
    for sector in SECTOR_WACC_CALIBRATED.keys() & SECTOR_TERMINAL_GROWTH_CALIBRATED.keys():
        wacc = SECTOR_WACC_CALIBRATED[sector]
        tg = SECTOR_TERMINAL_GROWTH_CALIBRATED[sector]
        assert tg < wacc - 0.02, (
            f"{sector!r}: TG {tg} not at least 200bps below WACC {wacc}"
        )


def test_sub_sector_keys_are_normalized_lowercase():
    """The composed lookup key is lower-cased before lookup, so
    every key in the BY_SUB maps must already be lower-cased to
    match. Guards against a casing typo making a key unreachable."""
    for key in SECTOR_WACC_CALIBRATED_BY_SUB.keys():
        assert key == key.lower(), f"sub-key {key!r} must be lower-cased"
        assert "::" in key, f"sub-key {key!r} must use '::' separator"
    for key in SECTOR_TERMINAL_GROWTH_CALIBRATED_BY_SUB.keys():
        assert key == key.lower(), f"sub-key {key!r} must be lower-cased"
        assert "::" in key, f"sub-key {key!r} must use '::' separator"


# ─────────────────────────────────────────────────────────────────
# 6. Consistency with existing cohort constants (no regression)
# ─────────────────────────────────────────────────────────────────

def test_calibrated_values_match_existing_cohort_constants():
    """The T1.3 table values MUST be consistent with the per-cohort
    constants already wired into service.py + forecaster.py. If a
    future PR wires the table into the engine path, the existing
    cohort blocks remain authoritative and the table must agree.

    Specifically:
      - FMCG TG default (5.5%) matches the FMCG top-tier franchise
        lift (FMCG_TG_TOP = 5.0%) ROUNDED UP to the staples band;
        the cohort code uses tier-specific values, the table uses
        a single staples anchor since names outside the cohort hit
        the broader sector default.
      - FMCG ITC override (3.0% tobacco) is BELOW the cohort ITC TG
        (FMCG_TG_ITC = 4.5%) because the cohort code already prices
        in non-cigarette diversification at ITC; a pure-tobacco
        name (not in the cohort) gets the Damodaran 3.0%.
    """
    # FMCG-staples table (5.5%) >= FMCG_TG_TOP cohort (5.0%):
    #   table is the sector-wide anchor; cohort can be tighter for
    #   named franchise leaders. The "table must not be below the
    #   tightest cohort value" invariant is what we lock in.
    fmcg_staples_table = get_calibrated_terminal_growth("FMCG", "staples")
    assert fmcg_staples_table >= FMCG_TG_TOP - 1e-9, (
        f"FMCG staples table TG {fmcg_staples_table} cannot be below "
        f"the cohort FMCG_TG_TOP {FMCG_TG_TOP}"
    )

    # FMCG default table (5.5%) >= FMCG_TG_TIER2 (4.5%) and TIER3 (4.0%):
    #   sector default is the loosest band; tiered cohort code tightens
    #   downward from there for specific tier-2/tier-3 names.
    fmcg_default_table = get_calibrated_terminal_growth("FMCG")
    assert fmcg_default_table >= FMCG_TG_TIER2 - 1e-9
    assert fmcg_default_table >= FMCG_TG_TIER3 - 1e-9

    # FMCG tobacco (3.0%) is BELOW FMCG_TG_ITC cohort (4.5%) — this
    # is intentional: the cohort code already accounts for ITC's
    # non-cigarette diversification; a pure-tobacco future ticker
    # without diversification gets the harsher Damodaran anchor.
    fmcg_tobacco_table = get_calibrated_terminal_growth("FMCG", "tobacco")
    assert fmcg_tobacco_table < FMCG_TG_ITC, (
        "FMCG tobacco table TG must be strictly below the cohort "
        "FMCG_TG_ITC (ITC enjoys non-cigarette diversification that "
        "raises its TG above pure-tobacco)"
    )


def test_helper_does_not_crash_on_whitespace_or_case():
    """The canonicaliser strips whitespace before lookup; case is
    NOT auto-folded for sectors (canonical labels are case-sensitive
    in SECTOR_OVERRIDES), but trailing whitespace must not break."""
    # Exact canonical label with surrounding whitespace
    assert get_calibrated_wacc("  FMCG  ") == pytest.approx(0.105)
    assert get_calibrated_terminal_growth("  Banking  ") == pytest.approx(0.055)
    # Wrong-case sector returns None (intentional — caller must use
    # _resolve_sector to get the canonical label first)
    assert get_calibrated_wacc("fmcg") is None
    # But sub_sector lookup IS case-insensitive (the composed key
    # is lower-cased in _sub_key) — sector still must match canonical
    assert get_calibrated_terminal_growth("FMCG", "TOBACCO") == pytest.approx(0.030)
    assert get_calibrated_terminal_growth("FMCG", "Tobacco") == pytest.approx(0.030)
