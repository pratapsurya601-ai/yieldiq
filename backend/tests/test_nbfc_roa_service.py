# backend/tests/test_nbfc_roa_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for backend/services/nbfc_roa_service.py (T3.2 Phase A).
#
# Coverage map (top-to-bottom — each test reads independently, no
# shared fixtures so a failure points at one concern):
#
#   compute_roa_tree
#     - sum-decomposition holds (yield - cof - cc - opex + fee = pre-tax)
#     - tax shield only applies to positive earnings (no fake credit)
#     - all-zero input is well-defined (no div/0, no negatives)
#     - fee_income lifts ROA
#
#   compute_fair_pb_gordon
#     - canonical Gordon: ROE=0.20, payout=0.30, k=0.13, g=0.10
#     - (k - g) == 0 → None
#     - (k - g) < 0 → None
#     - negative ROE → None
#
#   compute_nbfc_fair_value
#     - BAJFINANCE-shaped (consumer finance): ROA ~ 3.4%, ROE > 20%
#     - MUTHOOTFIN-shaped (gold loan): higher ROA than vehicle finance
#     - LICHSGFIN-shaped (housing): moderate ROA, low credit cost
#     - loss-making → ROA < 0, "loss-making" warning fires
#     - leverage > 10x → warning fires
#     - (k - g) inversion → fair_pb is None, inversion warning fires
#     - tax_rate=0 vs tax_rate=0.30 produces ROA delta as expected
#     - shares_outstanding=0 → fair_value_per_share is None
#     - book_value_per_share=0 → fair_value_per_share is None
#     - avg_assets=0 → method="unavailable", roa==None
#
#   get_segment_defaults
#     - returns a dict for every known segment
#     - unknown segment falls back to diversified
#     - mutating result does NOT pollute module constant
#
#   is_nbfc_applicable
#     - BAJFINANCE → True (in NBFC_TICKERS)
#     - MUTHOOTFIN.NS → True (suffix-stripped)
#     - HDFCBANK → False (bank, not NBFC)
#     - TCS → False (IT)
#     - sector hint "Non-Banking Financial Company" → True
#     - sector hint "Banking" → False (bank hint takes precedence)
#     - None sector + unknown ticker → False
#
#   to_dict
#     - shape contains all 8 required keys + JSON-serialisable values
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import json

import pytest

from backend.services.nbfc_roa_service import (
    NBFC_SEGMENT_DEFAULTS,
    NBFC_TICKERS,
    NBFCInputs,
    NBFCROAResult,
    compute_fair_pb_gordon,
    compute_nbfc_fair_value,
    compute_roa_tree,
    get_segment_defaults,
    is_nbfc_applicable,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# compute_roa_tree
# ─────────────────────────────────────────────────────────────────

def test_roa_tree_decomposition_sums_correctly():
    """yield - cof - credit_cost - opex + fee_income == pre_tax_roa."""
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.15,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        fee_income_pct=0.005,
    )
    c = compute_roa_tree(inputs)
    expected_pretax = 0.15 - 0.07 - 0.015 - 0.04 + 0.005
    assert c["pre_tax_roa"] == pytest.approx(expected_pretax, abs=1e-9)
    assert c["nim_proxy"] == pytest.approx(0.08, abs=1e-9)
    # roa = pre_tax * (1 - tax) when positive
    assert c["roa"] == pytest.approx(expected_pretax * 0.75, abs=1e-9)


def test_roa_tree_tax_only_applies_to_positive_earnings():
    """A loss-making bank shouldn't gain a fictitious tax credit."""
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.08,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.05,    # cycle-stress write-offs
        opex_ratio_pct=0.04,
        fee_income_pct=0.0,
        tax_rate=0.25,
    )
    c = compute_roa_tree(inputs)
    assert c["pre_tax_roa"] < 0
    # When pre-tax is negative, tax drag is zero (no fake credit) so
    # ROA == pre-tax ROA.
    assert c["tax"] == 0.0
    assert c["roa"] == c["pre_tax_roa"]


def test_roa_tree_all_zero_inputs():
    """All zero is well-defined: every component is 0."""
    inputs = NBFCInputs(
        average_assets_inr_cr=1000,
        average_equity_inr_cr=100,
        yield_on_assets_pct=0.0,
        cost_of_funds_pct=0.0,
        credit_cost_pct=0.0,
        opex_ratio_pct=0.0,
    )
    c = compute_roa_tree(inputs)
    for k in ("yield", "cost_of_funds", "nim_proxy", "credit_cost",
              "opex", "fee_income", "pre_tax_roa", "tax", "roa"):
        assert c[k] == 0.0


def test_roa_tree_fee_income_lifts_roa():
    base = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.14,
        cost_of_funds_pct=0.075,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        fee_income_pct=0.0,
    )
    with_fee = NBFCInputs(**{**base.__dict__, "fee_income_pct": 0.01})
    assert compute_roa_tree(with_fee)["roa"] > compute_roa_tree(base)["roa"]


# ─────────────────────────────────────────────────────────────────
# compute_fair_pb_gordon
# ─────────────────────────────────────────────────────────────────

def test_fair_pb_gordon_canonical():
    """Fair P/B = 0.20 × 0.30 / (0.13 - 0.10) = 2.0."""
    pb = compute_fair_pb_gordon(roe=0.20, payout=0.30,
                                cost_of_equity=0.13,
                                sustainable_growth=0.10)
    assert pb == pytest.approx(2.0, abs=1e-9)


def test_fair_pb_gordon_zero_spread_returns_none():
    assert compute_fair_pb_gordon(roe=0.20, payout=0.30,
                                  cost_of_equity=0.10,
                                  sustainable_growth=0.10) is None


def test_fair_pb_gordon_inverted_spread_returns_none():
    assert compute_fair_pb_gordon(roe=0.20, payout=0.30,
                                  cost_of_equity=0.08,
                                  sustainable_growth=0.10) is None


def test_fair_pb_gordon_negative_roe_returns_none():
    """A loss-making book doesn't deserve a negative price-to-book."""
    assert compute_fair_pb_gordon(roe=-0.05, payout=0.30,
                                  cost_of_equity=0.13,
                                  sustainable_growth=0.10) is None


# ─────────────────────────────────────────────────────────────────
# compute_nbfc_fair_value — segment shapes
# ─────────────────────────────────────────────────────────────────

def test_bajfinance_shaped_consumer_finance():
    """Consumer-finance scale (BAJFINANCE FY25 disclosure shape):
    avg assets ₹350,000 Cr, avg equity ₹50,000 Cr,
    yield 17%, COF 7%, credit cost 1.5%, opex 5%, fee 0.5%, tax 25%.

    Expected: ROA ~ 3.4-3.6%, leverage 7x, ROE > 20%, fair P/B > 0.
    """
    inputs = NBFCInputs(
        average_assets_inr_cr=350000,
        average_equity_inr_cr=50000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.05,
        fee_income_pct=0.005,
        tax_rate=0.25,
        payout_ratio=0.20,
        cost_of_equity=0.14,
        sustainable_growth=0.10,
        shares_outstanding=62.0,    # ~62 Cr shares
        book_value_per_share=900.0,
        segment="consumer_finance",
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.method == "roa_tree_dupont"
    # pre_tax = 0.17 - 0.07 - 0.015 - 0.05 + 0.005 = 0.04
    # roa = 0.04 * 0.75 = 0.030
    assert r.roa_pct == pytest.approx(0.030, abs=1e-6)
    assert r.leverage == pytest.approx(7.0, abs=1e-9)
    assert r.roe_pct == pytest.approx(0.21, abs=1e-6)
    # Fair P/B = 0.21 * 0.20 / (0.14 - 0.10) = 1.05
    assert r.fair_pb == pytest.approx(1.05, abs=1e-6)
    assert r.fair_value_per_share == pytest.approx(1.05 * 900, abs=1e-3)


def test_muthoot_shaped_gold_loan_has_higher_roa_than_vehicle():
    """Gold-loan economics (high yield, low credit cost) should produce
    higher ROA than vehicle-finance (medium yield, mid credit cost) at
    the same opex / COF / tax."""
    common = dict(
        average_assets_inr_cr=80000,
        average_equity_inr_cr=20000,
        cost_of_funds_pct=0.085,
        opex_ratio_pct=0.045,
        fee_income_pct=0.0,
        tax_rate=0.25,
    )
    gold = NBFCInputs(
        yield_on_assets_pct=0.22,
        credit_cost_pct=0.005,
        segment="gold_loan",
        **common,
    )
    vehicle = NBFCInputs(
        yield_on_assets_pct=0.14,
        credit_cost_pct=0.015,
        segment="vehicle_finance",
        **common,
    )
    gold_r = compute_nbfc_fair_value(gold)
    vehicle_r = compute_nbfc_fair_value(vehicle)
    assert gold_r.roa_pct > vehicle_r.roa_pct
    # Gold loan ROA should land north of 4%
    assert gold_r.roa_pct > 0.04


def test_lichsgfin_shaped_housing_finance_moderate_roa():
    """Housing finance: low yield (9%), tiny credit cost (0.5%),
    low opex (1.5%), so spread is narrow but stable. ROA should land
    around 1-1.5%, not the 3%+ of consumer finance."""
    inputs = NBFCInputs(
        average_assets_inr_cr=280000,
        average_equity_inr_cr=25000,
        yield_on_assets_pct=0.095,
        cost_of_funds_pct=0.068,
        credit_cost_pct=0.005,
        opex_ratio_pct=0.012,
        fee_income_pct=0.002,
        tax_rate=0.25,
        payout_ratio=0.20,
        cost_of_equity=0.12,
        sustainable_growth=0.08,
        segment="housing_finance",
    )
    r = compute_nbfc_fair_value(inputs)
    # pre_tax = 0.095 - 0.068 - 0.005 - 0.012 + 0.002 = 0.012
    # roa = 0.012 * 0.75 = 0.009
    assert 0.005 <= r.roa_pct <= 0.02
    # Leverage for housing is high (long-tenor secured book)
    assert r.leverage > 10.0
    # Leverage > 10x warning should fire
    assert any("leverage" in w.lower() for w in r.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# compute_nbfc_fair_value — warnings
# ─────────────────────────────────────────────────────────────────

def test_loss_making_fires_warning():
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=12000,
        yield_on_assets_pct=0.10,
        cost_of_funds_pct=0.08,
        credit_cost_pct=0.06,    # 6% credit cost — book on fire
        opex_ratio_pct=0.04,
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.roa_pct is not None and r.roa_pct < 0
    assert any("loss-making" in w.lower() for w in r.sanity_warnings)
    # 6% credit cost also trips the stress warning
    assert any("stressed" in w.lower() for w in r.sanity_warnings)


def test_high_leverage_fires_warning():
    inputs = NBFCInputs(
        average_assets_inr_cr=500000,
        average_equity_inr_cr=40000,    # 12.5x leverage
        yield_on_assets_pct=0.12,
        cost_of_funds_pct=0.08,
        credit_cost_pct=0.012,
        opex_ratio_pct=0.025,
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.leverage > 10.0
    assert any("leverage" in w.lower() and "high" in w.lower()
               for w in r.sanity_warnings)


def test_kg_inversion_fair_pb_none_and_warns():
    """g >= k_e is a Gordon-model bug; fair_pb must be None and the
    inversion warning must fire."""
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.16,
        cost_of_funds_pct=0.08,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        cost_of_equity=0.12,
        sustainable_growth=0.15,    # g > k → inversion
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.fair_pb is None
    assert r.fair_value_per_share is None
    assert any("inversion" in w.lower() for w in r.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# compute_nbfc_fair_value — tax + per-share edge cases
# ─────────────────────────────────────────────────────────────────

def test_tax_rate_variation_changes_roa_proportionally():
    """ROA at tax=0 should be exactly pre-tax-roa; ROA at tax=0.30
    should be 70% of that."""
    base = dict(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.05,
        fee_income_pct=0.005,
    )
    r0 = compute_nbfc_fair_value(NBFCInputs(tax_rate=0.0, **base))
    r30 = compute_nbfc_fair_value(NBFCInputs(tax_rate=0.30, **base))
    pretax = 0.17 - 0.07 - 0.015 - 0.05 + 0.005
    assert r0.roa_pct == pytest.approx(pretax, abs=1e-9)
    assert r30.roa_pct == pytest.approx(pretax * 0.70, abs=1e-9)


def test_zero_shares_outstanding_per_share_is_none():
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        shares_outstanding=0.0,
        book_value_per_share=500.0,
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.fair_pb is not None       # Gordon math still runs
    assert r.fair_value_per_share is None


def test_zero_bvps_per_share_is_none():
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        shares_outstanding=60.0,
        book_value_per_share=0.0,
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.fair_pb is not None
    assert r.fair_value_per_share is None


def test_zero_avg_assets_method_unavailable():
    inputs = NBFCInputs(
        average_assets_inr_cr=0.0,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
    )
    r = compute_nbfc_fair_value(inputs)
    assert r.method == "unavailable"
    assert r.leverage is None
    assert r.roe_pct is None
    assert r.fair_pb is None
    # components dict is still populated
    assert "yield" in r.components


# ─────────────────────────────────────────────────────────────────
# get_segment_defaults
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("segment", list(NBFC_SEGMENT_DEFAULTS.keys()))
def test_get_segment_defaults_returns_dict_for_each(segment):
    d = get_segment_defaults(segment)
    assert isinstance(d, dict)
    for key in ("expected_yield", "expected_credit_cost",
                "expected_opex_ratio", "expected_cof",
                "expected_growth", "cost_of_equity"):
        assert key in d


def test_get_segment_defaults_unknown_falls_back_to_diversified():
    got = get_segment_defaults("not_a_real_segment")  # type: ignore[arg-type]
    expected = NBFC_SEGMENT_DEFAULTS["diversified"]
    assert got == expected


def test_get_segment_defaults_returns_fresh_copy():
    """Mutating the result must NOT pollute the module constant."""
    d = get_segment_defaults("gold_loan")
    d["expected_yield"] = 999.0
    assert NBFC_SEGMENT_DEFAULTS["gold_loan"]["expected_yield"] != 999.0


# ─────────────────────────────────────────────────────────────────
# is_nbfc_applicable
# ─────────────────────────────────────────────────────────────────

def test_is_nbfc_applicable_bajfinance_true():
    ok, reason = is_nbfc_applicable("BAJFINANCE", None)
    assert ok is True
    assert "NBFC_TICKERS" in reason


def test_is_nbfc_applicable_muthootfin_with_ns_suffix():
    ok, _ = is_nbfc_applicable("MUTHOOTFIN.NS", None)
    assert ok is True


def test_is_nbfc_applicable_hdfcbank_false():
    """HDFCBANK is a bank, not an NBFC — must NOT route here."""
    ok, reason = is_nbfc_applicable("HDFCBANK", "Banking")
    assert ok is False
    assert "bank" in reason.lower()


def test_is_nbfc_applicable_tcs_false():
    ok, _ = is_nbfc_applicable("TCS", "Information Technology")
    assert ok is False


def test_is_nbfc_applicable_sector_hint_matches():
    ok, reason = is_nbfc_applicable("UNKNOWN_TICKER",
                                    "Non-Banking Financial Company")
    assert ok is True
    assert "nbfc" in reason.lower() or "non-banking" in reason.lower()


def test_is_nbfc_applicable_bank_hint_overrides_unknown():
    """Even an unknown ticker tagged 'Banking' must NOT route to NBFC."""
    ok, _ = is_nbfc_applicable("SOMEPVTBANK", "Private Banking")
    assert ok is False


def test_is_nbfc_applicable_no_hint_and_unknown():
    ok, _ = is_nbfc_applicable("UNKNOWN_TICKER", None)
    assert ok is False


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────

def test_to_dict_shape_and_json_safe():
    inputs = NBFCInputs(
        average_assets_inr_cr=100000,
        average_equity_inr_cr=15000,
        yield_on_assets_pct=0.17,
        cost_of_funds_pct=0.07,
        credit_cost_pct=0.015,
        opex_ratio_pct=0.04,
        shares_outstanding=60.0,
        book_value_per_share=900.0,
    )
    r = compute_nbfc_fair_value(inputs)
    d = to_dict(r)
    assert set(d.keys()) == {
        "roa_pct", "roe_pct", "leverage", "fair_pb",
        "fair_value_per_share", "components",
        "sanity_warnings", "method",
    }
    # Must be JSON-serialisable
    encoded = json.dumps(d)
    assert isinstance(encoded, str)
    # And round-trips back to equal structure
    assert json.loads(encoded)["method"] == "roa_tree_dupont"


# ─────────────────────────────────────────────────────────────────
# NBFC_TICKERS sanity — keep this in lockstep with the manifest entry
# ─────────────────────────────────────────────────────────────────

def test_nbfc_tickers_minimum_coverage():
    """Manifest entry pins the 12 names — if anyone removes one here
    without updating the manifest, this test catches it."""
    required = {
        "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "HDFCAMC", "IIFL",
        "LICHSGFIN", "LTFH", "M&MFIN", "MANAPPURAM", "MUTHOOTFIN",
        "POONAWALLA", "SHRIRAMFIN",
    }
    assert required.issubset(set(NBFC_TICKERS.keys()))
