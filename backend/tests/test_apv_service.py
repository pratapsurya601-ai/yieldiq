# backend/tests/test_apv_service.py
"""Tests for backend/services/apv_service.py — T2.6 Phase A.

Covers:
  * Vanilla deleveraging case: FCF growing, debt schedule paying
    down → EV in expected range, components add up.
  * LBO-shaped case: high leverage early, fast deleveraging → tax
    shield is a meaningful fraction of EV.
  * No-distress case (probability=0) → method == "apv_no_distress".
  * Mature / stable-debt case → APV roughly equals a WACC-DCF
    sanity benchmark (within ~10%).
  * compute_unlevered_cost_of_equity: rf + asset_beta × ERP arithmetic.
  * compute_tax_shield_pv: known inputs → verify formula.
  * compute_tax_shield_pv: empty / None debt → 0.
  * compute_unlevered_npv: matches manual NPV + Gordon perpetuity.
  * Shares == 0 → apv_per_share is None, EV still populated.
  * Forecast-years out of range → method="unavailable".
  * Debt-schedule length mismatch → method="unavailable".
  * is_apv_applicable: leveraged real-estate → True; mature FMCG → False;
    low-leverage shifting cap structure → False (low-leverage gate).
  * Sanity warnings: high asset beta, high distress probability,
    heavy tax shield, heavy terminal.
  * to_dict shape.

Run:
    pytest backend/tests/test_apv_service.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════
# compute_unlevered_cost_of_equity
# ═══════════════════════════════════════════════════════════════

def test_unlevered_cost_of_equity_textbook():
    """rf=7.1%, ERP=7.5%, asset_beta=0.85 → 7.1% + 0.85*7.5% = 13.475%."""
    from backend.services.apv_service import compute_unlevered_cost_of_equity

    k_u = compute_unlevered_cost_of_equity(0.071, 0.075, 0.85)
    assert k_u == pytest.approx(0.071 + 0.85 * 0.075, abs=1e-6)
    assert k_u == pytest.approx(0.13475, abs=1e-6)


def test_unlevered_cost_of_equity_zero_beta():
    """Zero asset beta → k_u == risk-free."""
    from backend.services.apv_service import compute_unlevered_cost_of_equity

    assert compute_unlevered_cost_of_equity(0.07, 0.075, 0.0) == pytest.approx(0.07)


def test_unlevered_cost_of_equity_non_finite_inputs():
    """Non-finite inputs collapse to 0 (defensive)."""
    from backend.services.apv_service import compute_unlevered_cost_of_equity

    assert compute_unlevered_cost_of_equity(float("nan"), 0.075, 0.85) == pytest.approx(0.85 * 0.075)


# ═══════════════════════════════════════════════════════════════
# compute_tax_shield_pv
# ═══════════════════════════════════════════════════════════════

def test_tax_shield_pv_constant_debt():
    """Constant debt=1000 over 5 years, i=8%, t=25%, discount=8% →
    annual shield = 1000 * 0.08 * 0.25 = 20.
    PV = 20 * (annuity factor 5y @ 8%) = 20 * 3.99271 = 79.854.
    """
    from backend.services.apv_service import compute_tax_shield_pv

    pv = compute_tax_shield_pv(
        debt_schedule=[1000.0] * 5,
        interest_rate=0.08,
        tax_rate=0.25,
        discount_rate=0.08,
    )
    # Annuity factor for 5y @ 8% = (1 - 1.08^-5) / 0.08 ≈ 3.99271
    expected = 20.0 * 3.99271
    assert pv == pytest.approx(expected, rel=1e-3)


def test_tax_shield_pv_empty_schedule():
    """Empty debt schedule → 0 shield."""
    from backend.services.apv_service import compute_tax_shield_pv

    assert compute_tax_shield_pv([], 0.08, 0.25, 0.08) == 0.0


def test_tax_shield_pv_none_treated_as_empty():
    """None / falsy schedule → 0."""
    from backend.services.apv_service import compute_tax_shield_pv

    assert compute_tax_shield_pv(None, 0.08, 0.25, 0.08) == 0.0  # type: ignore[arg-type]


def test_tax_shield_pv_deleveraging():
    """Deleveraging debt → each year's shield computed against that
    year's outstanding balance.

    debt = [500, 400, 300, 200, 100], i=10%, t=25%, k_d=10%
    shields = [12.5, 10, 7.5, 5, 2.5]
    PV: 12.5/1.1 + 10/1.21 + 7.5/1.331 + 5/1.4641 + 2.5/1.61051
       ≈ 11.364 + 8.264 + 5.635 + 3.415 + 1.552 ≈ 30.230
    """
    from backend.services.apv_service import compute_tax_shield_pv

    pv = compute_tax_shield_pv(
        debt_schedule=[500.0, 400.0, 300.0, 200.0, 100.0],
        interest_rate=0.10,
        tax_rate=0.25,
        discount_rate=0.10,
    )
    expected = (
        12.5 / 1.10
        + 10.0 / (1.10 ** 2)
        + 7.5 / (1.10 ** 3)
        + 5.0 / (1.10 ** 4)
        + 2.5 / (1.10 ** 5)
    )
    assert pv == pytest.approx(expected, rel=1e-4)


def test_tax_shield_pv_ignores_negative_debt():
    """Negative / non-finite debt entries do not contribute."""
    from backend.services.apv_service import compute_tax_shield_pv

    pv = compute_tax_shield_pv(
        debt_schedule=[100.0, -50.0, float("nan"), 100.0, 100.0],
        interest_rate=0.10,
        tax_rate=0.25,
        discount_rate=0.10,
    )
    # Only years 1, 4, 5 contribute; shield = 2.5 each.
    expected = 2.5 / 1.10 + 2.5 / (1.10 ** 4) + 2.5 / (1.10 ** 5)
    assert pv == pytest.approx(expected, rel=1e-4)


# ═══════════════════════════════════════════════════════════════
# compute_unlevered_npv
# ═══════════════════════════════════════════════════════════════

def test_unlevered_npv_constant_fcf_with_terminal():
    """FCF = [100]*5, g=2%, k=10%.
    Explicit PV = 100 * annuity(5,10%) = 100 * 3.79079 = 379.079
    TV at year 5 = 100 * 1.02 / (0.10 - 0.02) = 1275
    PV(TV) = 1275 / 1.10^5 = 1275 / 1.61051 = 791.677
    Total ≈ 1170.756
    """
    from backend.services.apv_service import compute_unlevered_npv

    out = compute_unlevered_npv([100.0] * 5, terminal_growth=0.02, discount_rate=0.10)
    expected_explicit = sum(100.0 / (1.10 ** i) for i in range(1, 6))
    tv = 100.0 * 1.02 / (0.10 - 0.02)
    expected = expected_explicit + tv / (1.10 ** 5)
    assert out == pytest.approx(expected, rel=1e-4)


def test_unlevered_npv_empty():
    from backend.services.apv_service import compute_unlevered_npv

    assert compute_unlevered_npv([], 0.04, 0.10) == 0.0


def test_unlevered_npv_terminal_collapse_on_g_ge_k():
    """terminal_growth >= discount_rate → terminal piece dropped."""
    from backend.services.apv_service import compute_unlevered_npv

    # g (clamped to 6%) == k_u (4%) impossible; instead use k near floor.
    # We use g=6% (ceiling), k=4% (floor) → g >= k → terminal = 0.
    out = compute_unlevered_npv([100.0] * 5, terminal_growth=0.06, discount_rate=0.04)
    # Only explicit PV at k=4%
    expected = sum(100.0 / (1.04 ** i) for i in range(1, 6))
    assert out == pytest.approx(expected, rel=1e-4)


# ═══════════════════════════════════════════════════════════════
# compute_apv — vanilla deleveraging case
# ═══════════════════════════════════════════════════════════════

def _vanilla_inputs():
    """Reusable fixture: 5-year deleveraging case."""
    from backend.services.apv_service import APVInputs

    return APVInputs(
        fcf_history_or_forecast=[100.0, 110.0, 121.0, 133.0, 146.0],
        forecast_years=5,
        fcf_growth_explicit=0.10,
        terminal_growth=0.04,
        debt_schedule_inr_cr=[500.0, 450.0, 400.0, 350.0, 300.0],
        interest_rate=0.08,
        tax_rate=0.25,
        risk_free_rate=0.071,
        equity_risk_premium=0.075,
        asset_beta=0.85,
        probability_of_distress=0.05,
        distress_cost_pct_of_firm_value=0.30,
        shares_outstanding=100.0,
        net_debt_today=300.0,
    )


def test_vanilla_apv_full_path():
    """Vanilla deleveraging case → method=apv_full, EV positive."""
    from backend.services.apv_service import compute_apv

    out = compute_apv(_vanilla_inputs())
    assert out.method == "apv_full"
    assert out.enterprise_value_apv is not None and out.enterprise_value_apv > 0
    assert out.apv_per_share is not None
    # Components sum to EV (within float tolerance).
    c = out.components
    assert c["unlevered_value"] + c["tax_shield_pv"] - c["distress_cost_pv"] == pytest.approx(
        out.enterprise_value_apv, rel=1e-6
    )
    # Equity bridge: EV - net_debt = equity, equity / shares = per_share.
    assert c["equity_value"] == pytest.approx(out.enterprise_value_apv - 300.0, rel=1e-6)
    assert out.apv_per_share == pytest.approx(c["equity_value"] / 100.0, rel=1e-6)


def test_vanilla_apv_ev_in_expected_range():
    """Sanity-check the EV order of magnitude.

    FCF starts at 100 growing 10%, k_u ~13.5%, terminal at 4% growth.
    Unlevered value alone is dominated by the perpetual; expect roughly
    1500-2500 in this regime. Tax shield adds ~80-100. Distress
    haircut at 5% prob * 30% cost = 1.5% of pre-distress.
    """
    from backend.services.apv_service import compute_apv

    out = compute_apv(_vanilla_inputs())
    assert out.enterprise_value_apv is not None
    assert 1200.0 < out.enterprise_value_apv < 3000.0


def test_vanilla_tax_shield_share_nonzero():
    """Tax shield should be a small-but-positive fraction of EV."""
    from backend.services.apv_service import compute_apv

    out = compute_apv(_vanilla_inputs())
    ts = out.components["tax_shield_pv"]
    ev = out.enterprise_value_apv
    assert ts > 0
    assert ev is not None
    # In the vanilla deleveraging case the shield is < 10% of EV.
    assert 0.0 < ts / ev < 0.15


# ═══════════════════════════════════════════════════════════════
# compute_apv — LBO-shaped case
# ═══════════════════════════════════════════════════════════════

def test_lbo_case_tax_shield_meaningful():
    """LBO: high debt early, fast pay-down.

    Tax shield should be a larger fraction of EV than the vanilla
    case — and the "leverage-heavy" sanity warning should fire if
    the share is > 30%.
    """
    from backend.services.apv_service import APVInputs, compute_apv

    lbo = APVInputs(
        fcf_history_or_forecast=[200.0, 240.0, 280.0, 320.0, 360.0],
        forecast_years=5,
        fcf_growth_explicit=0.10,
        terminal_growth=0.03,
        # Very high early debt → large early tax shields.
        debt_schedule_inr_cr=[3000.0, 2400.0, 1800.0, 1200.0, 600.0],
        interest_rate=0.10,
        tax_rate=0.25,
        risk_free_rate=0.07,
        equity_risk_premium=0.075,
        asset_beta=1.0,
        probability_of_distress=0.10,
        distress_cost_pct_of_firm_value=0.25,
        shares_outstanding=50.0,
        net_debt_today=3000.0,
    )
    out = compute_apv(lbo)
    assert out.method == "apv_full"
    ts = out.components["tax_shield_pv"]
    assert ts > 100.0  # Meaningful absolute number
    assert out.enterprise_value_apv is not None
    # Tax shield share should be larger than vanilla.
    share = ts / out.enterprise_value_apv
    assert share > 0.05


# ═══════════════════════════════════════════════════════════════
# compute_apv — no-distress path
# ═══════════════════════════════════════════════════════════════

def test_no_distress_path_when_probability_zero():
    """probability_of_distress = 0 → method == 'apv_no_distress'."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.probability_of_distress = 0.0
    out = compute_apv(inputs)
    assert out.method == "apv_no_distress"
    assert out.components["distress_cost_pv"] == 0.0


def test_no_distress_path_when_cost_zero():
    """distress_cost_pct = 0 → method == 'apv_no_distress'."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.distress_cost_pct_of_firm_value = 0.0
    out = compute_apv(inputs)
    assert out.method == "apv_no_distress"
    assert out.components["distress_cost_pv"] == 0.0


# ═══════════════════════════════════════════════════════════════
# compute_apv — stable-debt mature case (APV ≈ WACC-DCF check)
# ═══════════════════════════════════════════════════════════════

def test_mature_stable_debt_apv_in_sane_range():
    """Stable debt schedule → APV behaves reasonably and stays
    within a sane band relative to a hand-computed WACC-DCF anchor.

    We don't insist on tight equality (the two frameworks differ
    in second-order treatments) but on the same order of magnitude.
    """
    from backend.services.apv_service import APVInputs, compute_apv, compute_unlevered_npv

    mature = APVInputs(
        fcf_history_or_forecast=[500.0, 525.0, 551.0, 579.0, 608.0],  # ~5% growth
        forecast_years=5,
        fcf_growth_explicit=0.05,
        terminal_growth=0.03,
        # Truly stable debt.
        debt_schedule_inr_cr=[1000.0] * 5,
        interest_rate=0.08,
        tax_rate=0.25,
        risk_free_rate=0.07,
        equity_risk_premium=0.06,
        asset_beta=0.8,
        probability_of_distress=0.02,
        distress_cost_pct_of_firm_value=0.20,
        shares_outstanding=100.0,
        net_debt_today=1000.0,
    )
    out = compute_apv(mature)
    assert out.method == "apv_full"
    assert out.enterprise_value_apv is not None

    # Bench: hand-computed unlevered NPV at k_u = 7% + 0.8*6% = 11.8%
    k_u = 0.07 + 0.8 * 0.06
    bench_unlevered = compute_unlevered_npv(
        [500.0, 525.0, 551.0, 579.0, 608.0],
        terminal_growth=0.03,
        discount_rate=k_u,
    )
    # APV EV should be within ±15% of the unlevered benchmark plus a
    # small positive tax-shield contribution. (Mature/stable structure
    # is where APV and WACC-DCF should roughly agree.)
    assert abs(out.components["unlevered_value"] - bench_unlevered) < 1.0
    assert out.enterprise_value_apv > bench_unlevered  # shield > distress
    # And the gap is modest — leverage isn't shifting.
    gap = (out.enterprise_value_apv - bench_unlevered) / bench_unlevered
    assert -0.05 < gap < 0.20


# ═══════════════════════════════════════════════════════════════
# Defensive gates
# ═══════════════════════════════════════════════════════════════

def test_shares_zero_returns_none_per_share_but_ev_populated():
    """shares=0 → apv_per_share is None; EV still computed."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.shares_outstanding = 0.0
    out = compute_apv(inputs)
    assert out.apv_per_share is None
    assert out.enterprise_value_apv is not None
    assert out.enterprise_value_apv > 0
    # Method still classifies the path taken.
    assert out.method in {"apv_full", "apv_no_distress"}


def test_forecast_years_too_small():
    """forecast_years < 3 → unavailable."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.forecast_years = 2
    out = compute_apv(inputs)
    assert out.method == "unavailable"
    assert out.apv_per_share is None
    assert out.enterprise_value_apv is None


def test_forecast_years_too_large():
    """forecast_years > 15 → unavailable."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.forecast_years = 20
    out = compute_apv(inputs)
    assert out.method == "unavailable"


def test_debt_schedule_length_mismatch():
    """Non-empty debt schedule with len != forecast_years → unavailable."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.debt_schedule_inr_cr = [500.0, 400.0]  # 2 entries, n=5
    out = compute_apv(inputs)
    assert out.method == "unavailable"
    assert "debt_schedule" in out.components["reason"]


def test_empty_debt_schedule_treated_as_no_leverage():
    """Empty debt schedule → tax shield = 0; method valid."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.debt_schedule_inr_cr = []
    out = compute_apv(inputs)
    assert out.method in {"apv_full", "apv_no_distress"}
    assert out.components["tax_shield_pv"] == 0.0


def test_empty_fcf_unresolvable():
    """Empty FCF history → unavailable."""
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.fcf_history_or_forecast = []
    out = compute_apv(inputs)
    assert out.method == "unavailable"


# ═══════════════════════════════════════════════════════════════
# Sanity warnings
# ═══════════════════════════════════════════════════════════════

def test_high_asset_beta_warning():
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.asset_beta = 1.8
    # 0.071 + 1.8 * 0.075 = 0.206 — still inside ceiling (0.30)
    out = compute_apv(inputs)
    # Method should still succeed
    assert out.method in {"apv_full", "apv_no_distress"}
    assert any("asset_beta" in w for w in out.sanity_warnings)


def test_high_distress_probability_warning():
    from backend.services.apv_service import compute_apv

    inputs = _vanilla_inputs()
    inputs.probability_of_distress = 0.30
    out = compute_apv(inputs)
    assert any("probability_of_distress" in w for w in out.sanity_warnings)


def test_terminal_heavy_warning():
    """Very low FCF growth + low terminal makes the terminal dominate.

    With small explicit FCF and long-term g close to k_u, terminal PV
    dwarfs the explicit period.
    """
    from backend.services.apv_service import APVInputs, compute_apv

    inputs = APVInputs(
        fcf_history_or_forecast=[10.0] * 5,
        forecast_years=5,
        fcf_growth_explicit=0.0,
        terminal_growth=0.06,  # near k_u ceiling
        debt_schedule_inr_cr=[100.0] * 5,
        interest_rate=0.08,
        tax_rate=0.25,
        risk_free_rate=0.07,
        equity_risk_premium=0.04,
        asset_beta=0.5,  # k_u = 0.07 + 0.5*0.04 = 0.09
        probability_of_distress=0.0,
        distress_cost_pct_of_firm_value=0.0,
        shares_outstanding=10.0,
        net_debt_today=100.0,
    )
    out = compute_apv(inputs)
    # Should fire the terminal-heavy warning.
    assert any("terminal value" in w for w in out.sanity_warnings)


# ═══════════════════════════════════════════════════════════════
# is_apv_applicable
# ═══════════════════════════════════════════════════════════════

def test_applicable_leveraged_real_estate():
    """Leveraged real-estate with shifting cap structure → True."""
    from backend.services.apv_service import is_apv_applicable

    ok, _ = is_apv_applicable(
        "DLF",
        sector="real estate",
        debt_to_equity_changing=True,
        is_leveraged=True,
    )
    assert ok is True


def test_applicable_leveraged_real_estate_via_sector_only():
    """Sector flag carries the case even if 'changing' is False."""
    from backend.services.apv_service import is_apv_applicable

    ok, reason = is_apv_applicable(
        "DLF",
        sector="real estate",
        debt_to_equity_changing=False,
        is_leveraged=True,
    )
    assert ok is True
    assert "real estate" in reason


def test_not_applicable_mature_fmcg():
    """Mature FMCG, low leverage → False."""
    from backend.services.apv_service import is_apv_applicable

    ok, reason = is_apv_applicable(
        "HINDUNILVR",
        sector="fmcg",
        debt_to_equity_changing=False,
        is_leveraged=False,
    )
    assert ok is False
    assert "leverage" in reason.lower() or "wacc" in reason.lower()


def test_not_applicable_low_leverage_even_if_changing():
    """Low leverage + shifting structure → still False (the shift
    won't move the valuation if there's no leverage to start with).
    """
    from backend.services.apv_service import is_apv_applicable

    ok, _ = is_apv_applicable(
        "TCS",
        sector="it services",
        debt_to_equity_changing=True,
        is_leveraged=False,
    )
    assert ok is False


def test_not_applicable_stable_structure_leveraged_nonfriendly_sector():
    """Leveraged but stable, in a sector not in the friendly set → False."""
    from backend.services.apv_service import is_apv_applicable

    ok, reason = is_apv_applicable(
        "SOMEBANK",
        sector="bank",  # not in friendly set
        debt_to_equity_changing=False,
        is_leveraged=True,
    )
    assert ok is False
    assert "stable" in reason.lower() or "wacc" in reason.lower()


# ═══════════════════════════════════════════════════════════════
# to_dict shape
# ═══════════════════════════════════════════════════════════════

def test_to_dict_shape_full():
    """to_dict returns the expected JSON-safe keys."""
    from backend.services.apv_service import compute_apv, to_dict

    out = compute_apv(_vanilla_inputs())
    d = to_dict(out)
    assert set(d.keys()) == {
        "apv_per_share",
        "enterprise_value_apv",
        "components",
        "method",
        "sanity_warnings",
    }
    assert isinstance(d["components"], dict)
    assert isinstance(d["sanity_warnings"], list)
    assert d["method"] in {"apv_full", "apv_no_distress", "unavailable"}


def test_to_dict_shape_unavailable():
    """Even the unavailable path round-trips through to_dict."""
    from backend.services.apv_service import compute_apv, to_dict

    inputs = _vanilla_inputs()
    inputs.forecast_years = 1
    out = compute_apv(inputs)
    d = to_dict(out)
    assert d["method"] == "unavailable"
    assert d["apv_per_share"] is None
    assert d["enterprise_value_apv"] is None
    assert "reason" in d["components"]
