# backend/tests/test_insurance_ev_vnb.py
#
# T3.3 — Embedded Value + Value of New Business appraisal math.
#
# Tests the additive EV/VNB API extension to
# backend/services/insurance_appraisal_service.py:
#
#   - compute_ev_vnb_appraisal (EV + VNB × multiple, with EV-only
#     fallback, sanity warnings, optional per-share derivation)
#   - select_vnb_multiple (per-insurer default with growth +
#     market-share adjustments; sentinel 0.0 for general/health)
#   - is_ev_vnb_applicable (LIFE_INSURERS membership gate)
#   - LIFE_INSURERS / GENERAL_HEALTH_INSURERS frozensets
#
# These tests do NOT touch the existing Gordon-style
# compute_appraisal_fair_value / load_latest_appraisal_inputs /
# get_appraisal_fair_value_for_ticker pipeline — that surface is
# covered by test_insurance_appraisal.py and is unchanged by this
# extension (Phase A delivery: additive, no routing wired in).
#
# Run: pytest backend/tests/test_insurance_ev_vnb.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────────
# Tickers — coverage of the LIFE_INSURERS frozenset
# ─────────────────────────────────────────────────────────────────
def test_life_insurers_frozenset_contents():
    """The five listed Indian life insurers must be in LIFE_INSURERS."""
    from backend.services.insurance_appraisal_service import LIFE_INSURERS
    expected = {"HDFCLIFE", "ICICIPRULI", "SBILIFE", "MAXFIN", "LICI"}
    assert LIFE_INSURERS == expected, (
        f"LIFE_INSURERS must contain exactly the 5 listed life insurers; "
        f"got {sorted(LIFE_INSURERS)}"
    )


def test_general_health_insurers_disjoint_from_life():
    """The two cohorts must not overlap — different valuation frame."""
    from backend.services.insurance_appraisal_service import (
        LIFE_INSURERS, GENERAL_HEALTH_INSURERS,
    )
    overlap = LIFE_INSURERS & GENERAL_HEALTH_INSURERS
    assert not overlap, (
        f"LIFE and GENERAL/HEALTH insurer sets must be disjoint; "
        f"overlap={overlap}"
    )


def test_general_health_insurers_includes_known_listed_names():
    from backend.services.insurance_appraisal_service import (
        GENERAL_HEALTH_INSURERS,
    )
    for t in ("ICICIGI", "STARHEALTH", "NIVABUPA"):
        assert t in GENERAL_HEALTH_INSURERS, (
            f"{t} (general / health insurer) must be in "
            f"GENERAL_HEALTH_INSURERS — different valuation framework"
        )


# ─────────────────────────────────────────────────────────────────
# is_ev_vnb_applicable
# ─────────────────────────────────────────────────────────────────
def test_is_ev_vnb_applicable_life_insurers_true():
    from backend.services.insurance_appraisal_service import (
        is_ev_vnb_applicable,
    )
    for t in ("HDFCLIFE", "ICICIPRULI", "SBILIFE", "MAXFIN", "LICI"):
        assert is_ev_vnb_applicable(t) is True, (
            f"{t} should be EV/VNB-applicable (listed life insurer)"
        )


def test_is_ev_vnb_applicable_handles_exchange_suffix():
    """HDFCLIFE.NS / HDFCLIFE.BO should resolve identically to bare."""
    from backend.services.insurance_appraisal_service import (
        is_ev_vnb_applicable,
    )
    assert is_ev_vnb_applicable("HDFCLIFE.NS") is True
    assert is_ev_vnb_applicable("HDFCLIFE.BO") is True
    assert is_ev_vnb_applicable("hdfclife") is True


def test_is_ev_vnb_applicable_general_health_false():
    from backend.services.insurance_appraisal_service import (
        is_ev_vnb_applicable,
    )
    for t in ("ICICIGI", "STARHEALTH", "NIVABUPA", "GICRE", "NIACL"):
        assert is_ev_vnb_applicable(t) is False, (
            f"{t} is general/health insurer — EV/VNB framework not "
            f"applicable (no EV/VNB disclosure)"
        )


def test_is_ev_vnb_applicable_unrelated_tickers_false():
    """Non-insurer tickers must return False."""
    from backend.services.insurance_appraisal_service import (
        is_ev_vnb_applicable,
    )
    for t in ("RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC", ""):
        assert is_ev_vnb_applicable(t) is False, (
            f"{t} is not a life insurer — must return False"
        )


def test_is_ev_vnb_applicable_sector_arg_does_not_break():
    """Sector arg is accepted for API symmetry; must not change result."""
    from backend.services.insurance_appraisal_service import (
        is_ev_vnb_applicable,
    )
    assert is_ev_vnb_applicable("HDFCLIFE", sector="Insurance") is True
    assert is_ev_vnb_applicable("RELIANCE", sector="Energy") is False


# ─────────────────────────────────────────────────────────────────
# compute_ev_vnb_appraisal — happy paths
# ─────────────────────────────────────────────────────────────────
def test_hdfc_life_shaped_appraisal():
    """HDFC-Life-shape: EV 80,000 Cr + VNB 3,500 Cr × 22 = 157,000 Cr.

    Per-share at 2.15 billion shares (entered as 215 Cr units to
    match the Cr-aggregate convention): 157,000 / 215 = ~730/share.
    """
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=80000.0,           # Cr
        new_business_value=3500.0,        # Cr
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=215.0)
    assert out.method == "ev_plus_vnb_capitalized"
    assert out.appraisal_value == pytest.approx(157000.0, abs=1.0)
    assert out.appraisal_per_share == pytest.approx(730.23, abs=1.0)
    assert out.components["ev"] == pytest.approx(80000.0)
    assert out.components["vnb_capitalized"] == pytest.approx(77000.0)
    assert out.components["vnb_multiple"] == pytest.approx(22.0)
    assert out.sanity_warnings == []


def test_icici_pru_shaped_appraisal():
    """ICICI-Pru-shape: EV 42,000 Cr + VNB 2,400 Cr × 20 = 90,000 Cr."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=42000.0,
        new_business_value=2400.0,
        vnb_multiple=20.0,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=144.0)
    assert out.method == "ev_plus_vnb_capitalized"
    assert out.appraisal_value == pytest.approx(90000.0, abs=1.0)
    # 90,000 Cr / 144 Cr shares = ~625/share
    assert out.appraisal_per_share == pytest.approx(625.0, abs=1.0)


def test_lici_shaped_appraisal_with_low_multiple():
    """LICI-shape: massive EV 5.6 lakh Cr + VNB 9,500 Cr × 12 = 6.74L Cr.

    Tests the sub-15x multiplier code path (LICI legitimately
    trades below the [15, 30] floor — sovereign mix + lower growth).
    """
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=560000.0,
        new_business_value=9500.0,
        vnb_multiple=12.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "ev_plus_vnb_capitalized"
    assert out.appraisal_value == pytest.approx(674000.0, abs=1.0)
    # Sub-floor multiplier → expect a sanity warning, not a rejection.
    assert any("below the typical" in w.lower() for w in out.sanity_warnings), (
        f"Expected sub-floor multiplier warning; got {out.sanity_warnings}"
    )
    assert out.appraisal_per_share is None  # shares not provided


# ─────────────────────────────────────────────────────────────────
# compute_ev_vnb_appraisal — degenerate paths
# ─────────────────────────────────────────────────────────────────
def test_zero_vnb_falls_back_to_ev_only():
    """Zero VNB → method='ev_only', appraisal=EV, warning fires."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=50000.0,
        new_business_value=0.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "ev_only"
    assert out.appraisal_value == pytest.approx(50000.0)
    assert out.components["vnb_capitalized"] == 0.0
    assert any("non-positive" in w.lower() for w in out.sanity_warnings)


def test_negative_vnb_falls_back_to_ev_only():
    """Negative VNB (rare but possible during product-mix transitions)."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=50000.0,
        new_business_value=-500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "ev_only"
    assert out.appraisal_value == pytest.approx(50000.0)


def test_zero_ev_returns_unavailable():
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=0.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "unavailable"
    assert out.appraisal_value is None
    assert out.appraisal_per_share is None
    assert out.sanity_warnings  # at least one warning


def test_negative_ev_returns_unavailable():
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=-100.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "unavailable"


def test_missing_shares_returns_aggregate_only():
    """shares_outstanding=None → appraisal_per_share is None."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=80000.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=None)
    assert out.appraisal_value == pytest.approx(157000.0)
    assert out.appraisal_per_share is None


def test_zero_shares_returns_aggregate_only():
    """shares_outstanding=0 must NOT raise ZeroDivisionError."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=80000.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=0)
    assert out.appraisal_value == pytest.approx(157000.0)
    assert out.appraisal_per_share is None


# ─────────────────────────────────────────────────────────────────
# compute_ev_vnb_appraisal — sanity warnings on out-of-band inputs
# ─────────────────────────────────────────────────────────────────
def test_over_ceiling_multiplier_warns():
    """Multiplier > 30 should warn but still honour the caller's value."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=10000.0,
        new_business_value=500.0,
        vnb_multiple=35.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.method == "ev_plus_vnb_capitalized"
    assert out.appraisal_value == pytest.approx(10000.0 + 500.0 * 35.0)
    assert any("exceeds the typical" in w.lower() for w in out.sanity_warnings)


def test_extreme_growth_warns():
    """new_business_growth > 30% triggers a sanity warning."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=50000.0,
        new_business_value=3000.0,
        vnb_multiple=22.0,
        new_business_growth=0.40,
        forward_years=5,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert any("unusually high" in w.lower() for w in out.sanity_warnings)
    assert out.components["forward_growth"] == pytest.approx(0.40)


def test_sharply_negative_growth_warns():
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=50000.0,
        new_business_value=3000.0,
        vnb_multiple=22.0,
        new_business_growth=-0.25,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert any("sharply negative" in w.lower() for w in out.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# select_vnb_multiple
# ─────────────────────────────────────────────────────────────────
def test_select_vnb_multiple_life_per_ticker_defaults():
    """Per-insurer defaults should match the calibrated table."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    assert select_vnb_multiple("life", ticker="HDFCLIFE") == pytest.approx(22.0)
    assert select_vnb_multiple("life", ticker="ICICIPRULI") == pytest.approx(20.0)
    assert select_vnb_multiple("life", ticker="SBILIFE") == pytest.approx(24.0)
    assert select_vnb_multiple("life", ticker="MAXFIN") == pytest.approx(18.0)
    # LICI: per-ticker 12x is below the 15x floor — must NOT be clamped up.
    assert select_vnb_multiple("life", ticker="LICI") == pytest.approx(12.0)


def test_select_vnb_multiple_general_returns_sentinel():
    """General insurer → 0.0 sentinel (different valuation framework)."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    assert select_vnb_multiple("general", ticker="ICICIGI") == 0.0
    assert select_vnb_multiple("health", ticker="STARHEALTH") == 0.0
    assert select_vnb_multiple("reinsurance", ticker="GICRE") == 0.0


def test_select_vnb_multiple_growth_adjustment_up():
    """High growth (>=25%) should boost the multiple by +2x."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    base = select_vnb_multiple("life", ticker="HDFCLIFE")
    boosted = select_vnb_multiple(
        "life", ticker="HDFCLIFE", new_business_growth=0.30,
    )
    assert boosted == pytest.approx(base + 2.0)


def test_select_vnb_multiple_growth_adjustment_down():
    """Low growth (<=5%) should penalise the multiple by -2x."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    base = select_vnb_multiple("life", ticker="HDFCLIFE")
    penalised = select_vnb_multiple(
        "life", ticker="HDFCLIFE", new_business_growth=0.03,
    )
    assert penalised == pytest.approx(base - 2.0)


def test_select_vnb_multiple_market_share_gainer():
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    base = select_vnb_multiple("life", ticker="ICICIPRULI")
    gainer = select_vnb_multiple(
        "life", ticker="ICICIPRULI", market_share_trend="gaining",
    )
    assert gainer == pytest.approx(base + 2.5)


def test_select_vnb_multiple_market_share_loser():
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    base = select_vnb_multiple("life", ticker="ICICIPRULI")
    loser = select_vnb_multiple(
        "life", ticker="ICICIPRULI", market_share_trend="losing",
    )
    assert loser == pytest.approx(base - 4.0)


def test_select_vnb_multiple_clamped_to_band_for_non_sovereign():
    """Adjustments must not push HDFCLIFE / SBILIFE beyond [15, 30].

    Under the current adjustment scheme the maximum positive
    perturbation is +2.5 (market-share gainer) + 2.0 (growth
    above 25%) = +4.5, so even SBILIFE (24x base) tops out at
    28.5x — comfortably inside the ceiling. The clamp is a
    defence-in-depth invariant for future calibration changes.
    On the downside, HDFCLIFE (22x base) at -4.0 (losing) -2.0
    (low growth) = 16x is in-band, but the clamp guarantees we
    never fall below 15x for a non-sovereign-mix insurer.
    """
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    # SBILIFE base = 24; max positive push = 28.5 → still in band.
    pushed_high = select_vnb_multiple(
        "life", ticker="SBILIFE",
        new_business_growth=0.30, market_share_trend="gaining",
    )
    assert 15.0 <= pushed_high <= 30.0
    assert pushed_high == pytest.approx(28.5)

    # Maximum negative push for HDFCLIFE: 22 - 4 - 2 = 16 → in band.
    pushed_low = select_vnb_multiple(
        "life", ticker="HDFCLIFE",
        new_business_growth=0.03, market_share_trend="losing",
    )
    assert 15.0 <= pushed_low <= 30.0
    assert pushed_low == pytest.approx(16.0)

    # Maximum negative push for MAXFIN: 18 - 4 - 2 = 12 → clamps to 15.
    extreme_low = select_vnb_multiple(
        "life", ticker="MAXFIN",
        new_business_growth=0.03, market_share_trend="losing",
    )
    assert extreme_low == pytest.approx(15.0)


def test_select_vnb_multiple_lici_low_floor_preserved():
    """LICI sovereign-mix default (12x) must survive adjustments without
    being clamped back up to 15x — it is intentionally sub-floor."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    base = select_vnb_multiple("life", ticker="LICI")
    # Mild positive adjustment should still leave the result below 15x.
    adj = select_vnb_multiple(
        "life", ticker="LICI", market_share_trend="stable",
    )
    assert base == pytest.approx(12.0)
    assert adj == pytest.approx(12.0)


def test_select_vnb_multiple_unknown_life_ticker_uses_default():
    """Life insurer with no per-ticker entry → mid-point default."""
    from backend.services.insurance_appraisal_service import (
        select_vnb_multiple,
    )
    assert select_vnb_multiple("life", ticker="UNKNOWN_LIFE") == pytest.approx(20.0)


# ─────────────────────────────────────────────────────────────────
# EVVNBResult.to_dict — shape contract
# ─────────────────────────────────────────────────────────────────
def test_to_dict_shape():
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=80000.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=215.0)
    d = out.to_dict()
    assert set(d.keys()) == {
        "appraisal_value",
        "appraisal_per_share",
        "components",
        "method",
        "sanity_warnings",
    }
    assert isinstance(d["components"], dict)
    assert isinstance(d["sanity_warnings"], list)
    # Components must include the canonical three keys for the
    # transparency panel — frontend reads them by name.
    for k in ("ev", "vnb_capitalized", "vnb_multiple"):
        assert k in d["components"], f"components must include {k!r}"


def test_to_dict_unavailable_shape():
    """Even on unavailable, to_dict must be safe to serialise."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal,
    )
    inputs = EVVNBInputs(
        embedded_value=0.0,
        new_business_value=3500.0,
        vnb_multiple=22.0,
    )
    out = compute_ev_vnb_appraisal(inputs)
    d = out.to_dict()
    assert d["appraisal_value"] is None
    assert d["appraisal_per_share"] is None
    assert d["method"] == "unavailable"


# ─────────────────────────────────────────────────────────────────
# Integration sanity — selector + computer interplay
# ─────────────────────────────────────────────────────────────────
def test_selector_to_computer_roundtrip_hdfc():
    """End-to-end: select multiple → feed compute → verify shape."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal, select_vnb_multiple,
    )
    mult = select_vnb_multiple("life", ticker="HDFCLIFE")
    inputs = EVVNBInputs(
        embedded_value=80000.0,
        new_business_value=3500.0,
        vnb_multiple=mult,
    )
    out = compute_ev_vnb_appraisal(inputs, shares_outstanding=215.0)
    assert out.method == "ev_plus_vnb_capitalized"
    assert out.appraisal_value == pytest.approx(80000.0 + 3500.0 * 22.0)
    assert out.sanity_warnings == []  # 22x is in-band; no warnings


def test_selector_to_computer_roundtrip_lici_emits_band_warning():
    """LICI selector returns 12x → compute should warn 'below band'."""
    from backend.services.insurance_appraisal_service import (
        EVVNBInputs, compute_ev_vnb_appraisal, select_vnb_multiple,
    )
    mult = select_vnb_multiple("life", ticker="LICI")
    inputs = EVVNBInputs(
        embedded_value=560000.0,
        new_business_value=9500.0,
        vnb_multiple=mult,
    )
    out = compute_ev_vnb_appraisal(inputs)
    assert out.appraisal_value == pytest.approx(560000.0 + 9500.0 * 12.0)
    # The "below the typical [15, 30] band" warning is expected because
    # 12x is intentionally sub-floor for LICI's sovereign-mix profile.
    assert any("below the typical" in w.lower() for w in out.sanity_warnings)
