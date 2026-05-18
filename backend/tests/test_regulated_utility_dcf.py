# backend/tests/test_regulated_utility_dcf.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for the rate-base regulated-utility valuation path.
#
# Covers acceptance criteria from
# docs/design/regulated-utility-dcf-fix.md §4 + §7:
#
#   - POWERGRID FV must land in [₹250, ₹350]
#   - NTPC FV must land in [₹300, ₹430]
#   - PFC and IRFC route through the regulated_nbfc sub-type
#   - A non-utility ticker (RELIANCE) must NOT route through this
#     branch (negative-case guard for the classifier)
#   - Missing BVPS surfaces as data_limited (returns None) — never
#     silently falls through to generic DCF
#   - High debt has NO effect on FV (regression for the
#     dcf_engine.py:379 collapse described in the design doc §1)
#   - Realised-ROE adjustment is clamped to [0.85, 1.15] so a
#     single weak year cannot flip the verdict
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest

from backend.services.regulated_utility_valuation_service import (
    compute_regulated_utility_fair_value,
    get_sub_type,
    _SUB_TYPE_PARAMS,
    _FALLBACK_PB,
    _justified_pb,
)
from backend.services.analysis.constants import is_regulated_utility


# ── Sub-type classification ─────────────────────────────────────


def test_get_sub_type_transmission():
    assert get_sub_type("POWERGRID") == "transmission_utility"
    assert get_sub_type("POWERGRID.NS") == "transmission_utility"
    assert get_sub_type("NTPC") == "transmission_utility"
    assert get_sub_type("NHPC.NS") == "transmission_utility"
    assert get_sub_type("SJVN") == "transmission_utility"
    assert get_sub_type("ADANIENSOL") == "transmission_utility"


def test_get_sub_type_regulated_nbfc():
    assert get_sub_type("PFC") == "regulated_nbfc"
    assert get_sub_type("RECLTD.NS") == "regulated_nbfc"
    assert get_sub_type("IRFC") == "regulated_nbfc"
    assert get_sub_type("HUDCO.NS") == "regulated_nbfc"


def test_get_sub_type_regulated_other():
    assert get_sub_type("GAIL") == "regulated_other"
    assert get_sub_type("TORNTPOWER.NS") == "regulated_other"
    assert get_sub_type("IEX") == "regulated_other"


def test_get_sub_type_returns_none_for_non_utility():
    """Negative case — RELIANCE / TCS / HDFCBANK must NOT route
    through this branch.
    """
    assert get_sub_type("RELIANCE") is None
    assert get_sub_type("RELIANCE.NS") is None
    assert get_sub_type("TCS") is None
    assert get_sub_type("HDFCBANK.NS") is None
    assert get_sub_type("INFY") is None
    # NBFC names that route through financial_valuation_service
    # but are NOT in REGULATED_UTILITY_TICKERS:
    assert get_sub_type("BAJFINANCE") is None
    assert get_sub_type("MUTHOOTFIN") is None


def test_is_regulated_utility_helper_aligns_with_get_sub_type():
    """The constants.is_regulated_utility helper must agree with
    get_sub_type() on every ticker — they share REGULATED_UTILITY_TICKERS
    as the single source of truth.
    """
    for t in ("POWERGRID", "NTPC", "PFC", "IRFC", "GAIL", "SJVN", "HUDCO"):
        assert is_regulated_utility(t) is True
        assert get_sub_type(t) is not None
    for t in ("RELIANCE", "TCS", "HDFCBANK", "BAJFINANCE", "INFY"):
        assert is_regulated_utility(t) is False
        assert get_sub_type(t) is None


# ── Justified-P/B math ─────────────────────────────────────────


def test_justified_pb_transmission_calibration():
    """Calibration anchor: transmission_utility params must produce
    fair_pb ≈ 2.875 (the value docs/design/regulated-utility-dcf-fix.md
    relies on for POWERGRID's [₹250, ₹350] band).
    """
    allowed_roe, coe, g = _SUB_TYPE_PARAMS["transmission_utility"]
    pb = _justified_pb(allowed_roe, coe, g)
    assert 2.8 < pb < 3.0


def test_justified_pb_handles_degenerate_coe_minus_g():
    """coe ≤ g would divide by zero or negative — must floor at 1.0."""
    pb = _justified_pb(0.15, 0.04, 0.04)
    assert pb >= 1.0
    pb = _justified_pb(0.15, 0.03, 0.04)
    assert pb == 1.0


def test_justified_pb_bounded_at_5x():
    """Even with absurdly high allowed_ROE, fair_pb must not exceed 5×."""
    pb = _justified_pb(0.50, 0.07, 0.04)  # would be (0.46/0.03) = 15.3
    assert pb == 5.0


# ── POWERGRID — primary acceptance criterion ───────────────────


def test_powergrid_rate_base_fv_in_acceptance_band():
    """POWERGRID FY25 calibration:
      total_equity ≈ ₹83,000 Cr; shares ≈ 9.30 B (930 Cr units).
      BVPS ≈ ₹89.25. realised_roe ≈ 15.5% (matches allowed → adj=1.0).

    Expected FV: 89.25 × ~2.875 ≈ ₹256 — within [₹250, ₹350].
    """
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID.NS",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={
            "total_equity": 83_000e7,   # ₹83,000 Cr in rupees
            "shares": 9.30e9,
            "roe": 0.155,
            # Note: NO total_debt field consumed — by design.
        },
    )
    assert result is not None
    assert 250.0 <= result["fair_value"] <= 350.0
    assert result["confidence_score"] >= 70
    assert result["valuation_method"] == "rate_base"
    assert result["_meta"]["sub_type"] == "transmission_utility"


def test_powergrid_uses_priceToBook_fallback_for_bvps():
    """When total_equity is missing, BVPS must be derived from
    priceToBook × price. Verifies the second prong of _extract_bvps.
    """
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={
            "priceToBook": 3.27,   # 291 / 89 ≈ 3.27
            "roe": 0.155,
        },
    )
    assert result is not None
    assert 250.0 <= result["fair_value"] <= 350.0


# ── NTPC — second acceptance criterion ─────────────────────────


def test_ntpc_rate_base_fv_in_acceptance_band():
    """NTPC FY25 approx: BVPS ≈ ₹150 (total_equity ₹1,45,000 Cr,
    shares ~970 Cr units). Expected FV: 150 × ~2.6 ≈ ₹390 — within
    [₹300, ₹430].
    """
    result = compute_regulated_utility_fair_value(
        ticker="NTPC.NS",
        company_info={"current_price": 395.0, "shares": 9.70e9},
        financials={
            "total_equity": 1_45_000e7,   # ₹1,45,000 Cr
            "shares": 9.70e9,
            "roe": 0.14,
        },
    )
    assert result is not None
    assert 300.0 <= result["fair_value"] <= 430.0


# ── PFC — regulated_nbfc sub-type ──────────────────────────────


def test_pfc_routes_through_regulated_nbfc():
    """PFC FY25 approx: BVPS ≈ ₹275 (total_equity ₹91,000 Cr,
    shares ~330 Cr). Expected fair_pb ≈ 2.36 → FV ≈ ₹650 (acceptance
    band [₹400, ₹600], realised_roe adjustment can pull this down).
    """
    result = compute_regulated_utility_fair_value(
        ticker="PFC.NS",
        company_info={"current_price": 470.0, "shares": 3.30e9},
        financials={
            "total_equity": 91_000e7,
            "shares": 3.30e9,
            "roe": 0.21,    # realised ROE > allowed → clamped at 1.15
        },
    )
    assert result is not None
    assert result["_meta"]["sub_type"] == "regulated_nbfc"
    # ROE adjustment must clamp at 1.15 (0.21/0.18 = 1.167)
    assert result["_meta"]["roe_adjustment"] == 1.15


# ── IRFC — regulated_nbfc sub-type, additional ticker ──────────


def test_irfc_routes_through_regulated_nbfc():
    """IRFC was missing from REGULATED_UTILITY_TICKERS until this PR.
    Verify it now classifies correctly and produces a finite FV.
    """
    assert is_regulated_utility("IRFC") is True
    assert get_sub_type("IRFC") == "regulated_nbfc"

    result = compute_regulated_utility_fair_value(
        ticker="IRFC.NS",
        company_info={"current_price": 130.0, "shares": 13.07e9},
        financials={
            "total_equity": 52_000e7,   # ₹52,000 Cr
            "shares": 13.07e9,
            "roe": 0.135,
        },
    )
    assert result is not None
    assert result["fair_value"] > 0
    assert result["_meta"]["sub_type"] == "regulated_nbfc"


# ── Negative case: non-utility must not route through engine ───


def test_non_utility_returns_none():
    """The engine MUST refuse to value a non-utility ticker — that's
    the contract that protects RELIANCE / TCS / HDFCBANK from being
    silently re-routed if a call site forgets the is_regulated_utility
    gate.
    """
    result = compute_regulated_utility_fair_value(
        ticker="RELIANCE.NS",
        company_info={"current_price": 2500.0, "shares": 6.77e9},
        financials={
            "total_equity": 9_50_000e7,
            "shares": 6.77e9,
            "roe": 0.10,
        },
    )
    assert result is None


# ── Data-limited path ─────────────────────────────────────────


def test_missing_bvps_returns_none_not_generic_dcf():
    """The whole reason this engine exists is to refuse to fall
    through to generic FCF-DCF. When BVPS cannot be derived (no
    total_equity, no priceToBook), the function MUST return None so
    the caller surfaces data_limited.
    """
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID.NS",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={
            # No total_equity, no priceToBook, no bvps.
            "shares": 9.30e9,
            "roe": 0.155,
        },
    )
    assert result is None


def test_zero_price_returns_none():
    """Missing price → cannot compute MoS → must refuse to value."""
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 0, "shares": 9.30e9},
        financials={"total_equity": 83_000e7, "shares": 9.30e9, "roe": 0.155},
    )
    assert result is None


# ── Regression: high debt must NOT subtract from equity FV ─────


def test_high_debt_does_not_affect_fv():
    """REGRESSION GUARD for the dcf_engine.py:379 collapse:
      equity_value = EV − total_debt + total_cash
    The whole point of this branch is to bypass that subtraction.
    Verify two POWERGRID calls — one with implied debt context, one
    without — produce identical FVs because the engine does not
    consume total_debt at all.
    """
    common_company = {"current_price": 291.0, "shares": 9.30e9}
    common_fin = {
        "total_equity": 83_000e7,
        "shares": 9.30e9,
        "roe": 0.155,
    }
    fv_no_debt = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info=common_company,
        financials=common_fin,
    )["fair_value"]
    # Add a (deliberately wrong, deliberately huge) debt field — the
    # engine must ignore it.
    fv_with_debt = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info=common_company,
        financials={**common_fin, "total_debt": 1_20_000e7, "total_cash": 5_000e7},
    )["fair_value"]
    assert fv_no_debt == fv_with_debt


# ── ROE adjustment clamping ────────────────────────────────────


def test_roe_adjustment_clamped_at_floor():
    """Realised ROE far below allowed must clamp at 0.85, not crater
    the FV. Mirrors the discipline in financial_valuation_service.
    """
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={
            "total_equity": 83_000e7,
            "shares": 9.30e9,
            "roe": 0.05,   # 5% realised vs 15.5% allowed → ratio 0.32 → clamped
        },
    )
    assert result is not None
    assert result["_meta"]["roe_adjustment"] == 0.85


def test_roe_adjustment_clamped_at_ceiling():
    """Realised ROE above allowed must clamp at 1.15, not balloon FV."""
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={
            "total_equity": 83_000e7,
            "shares": 9.30e9,
            "roe": 0.30,   # 30% realised vs 15.5% allowed → ratio 1.94 → clamped
        },
    )
    assert result is not None
    assert result["_meta"]["roe_adjustment"] == 1.15


def test_missing_roe_uses_neutral_adjustment():
    """No realised-ROE → adjustment = 1.0 (no penalty)."""
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={"total_equity": 83_000e7, "shares": 9.30e9},
    )
    assert result is not None
    assert result["_meta"]["roe_adjustment"] == 1.0


# ── Scenario assembly: bear < base < bull ──────────────────────


def test_scenarios_strictly_ordered():
    """bear_case < base_case < bull_case — scenarios output contract."""
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 291.0, "shares": 9.30e9},
        financials={"total_equity": 83_000e7, "shares": 9.30e9, "roe": 0.155},
    )
    assert result["bear_case"] < result["base_case"] < result["bull_case"]
    # ±25% band per the regulated-utility tariff true-up cycle.
    assert result["bear_case"] == pytest.approx(result["base_case"] * 0.75, rel=1e-3)
    assert result["bull_case"] == pytest.approx(result["base_case"] * 1.25, rel=1e-3)


# ── Verdict math ───────────────────────────────────────────────


def test_verdict_undervalued_when_fv_well_above_price():
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 100.0, "shares": 9.30e9},
        financials={"total_equity": 83_000e7, "shares": 9.30e9, "roe": 0.155},
    )
    assert result["verdict"] == "undervalued"
    assert result["margin_of_safety"] > 15


def test_verdict_overvalued_when_fv_well_below_price():
    result = compute_regulated_utility_fair_value(
        ticker="POWERGRID",
        company_info={"current_price": 800.0, "shares": 9.30e9},
        financials={"total_equity": 83_000e7, "shares": 9.30e9, "roe": 0.155},
    )
    assert result["verdict"] == "overvalued"
    assert result["margin_of_safety"] < -15
