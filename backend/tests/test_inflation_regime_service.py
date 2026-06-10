"""Unit tests for backend/services/inflation_regime_service.py.

Covers:
  - classify_inflation_regime band edges
  - compute_real_terms_dcf returns None on degenerate input
  - compute_real_terms_dcf produces a sensible real-terms FV when
    nominal inputs are reasonable
  - compute_regime_adjustment model_note matrix
  - to_dict serialises round-trip safely
"""
from __future__ import annotations

import math

import pytest

from backend.services.inflation_regime_service import (
    DEFAULT_HORIZON_YEARS,
    InflationRegimeResult,
    classify_inflation_regime,
    compute_real_terms_dcf,
    compute_regime_adjustment,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# classify_inflation_regime
# ─────────────────────────────────────────────────────────────────
class TestClassifyInflationRegime:
    def test_low_band(self):
        assert classify_inflation_regime(0.0) == "low"
        assert classify_inflation_regime(3.9) == "low"

    def test_normal_band(self):
        assert classify_inflation_regime(4.0) == "normal"
        assert classify_inflation_regime(5.0) == "normal"
        assert classify_inflation_regime(5.99) == "normal"

    def test_high_band(self):
        assert classify_inflation_regime(6.0) == "high"
        assert classify_inflation_regime(7.5) == "high"
        assert classify_inflation_regime(7.99) == "high"

    def test_extreme_band(self):
        assert classify_inflation_regime(8.0) == "extreme"
        assert classify_inflation_regime(12.0) == "extreme"
        assert classify_inflation_regime(50.0) == "extreme"

    def test_non_finite_defaults_to_normal(self):
        assert classify_inflation_regime(float("nan")) == "normal"
        assert classify_inflation_regime(float("inf")) == "normal"
        assert classify_inflation_regime(-1.0) == "normal"
        assert classify_inflation_regime("not a number") == "normal"  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# compute_real_terms_dcf
# ─────────────────────────────────────────────────────────────────
class TestComputeRealTermsDcf:
    def test_degenerate_returns_none(self):
        # base_fcf <= 0
        assert (
            compute_real_terms_dcf(
                base_fcf=0,
                nominal_wacc=12,
                nominal_growth=8,
                terminal_growth=5,
                current_cpi=5,
                shares=100,
                net_debt=0,
            )
            is None
        )
        # shares <= 0
        assert (
            compute_real_terms_dcf(
                base_fcf=100,
                nominal_wacc=12,
                nominal_growth=8,
                terminal_growth=5,
                current_cpi=5,
                shares=0,
                net_debt=0,
            )
            is None
        )

    def test_spread_floor_returns_none(self):
        # real WACC - real terminal growth below the MIN_TERMINAL_SPREAD
        # floor (1%). Real WACC = 5; real terminal growth = 4.5
        # -> spread 0.5% < 1%.
        out = compute_real_terms_dcf(
            base_fcf=100,
            nominal_wacc=10,
            nominal_growth=8,
            terminal_growth=9.5,
            current_cpi=5,
            shares=100,
            net_debt=0,
        )
        assert out is None

    def test_real_wacc_negative_returns_none(self):
        # nominal_wacc < cpi -> real_wacc negative
        out = compute_real_terms_dcf(
            base_fcf=100,
            nominal_wacc=4,
            nominal_growth=2,
            terminal_growth=1,
            current_cpi=6,
            shares=100,
            net_debt=0,
        )
        assert out is None

    def test_baseline_normal_regime_produces_positive_value(self):
        # Realistic mid-cap inputs: 12.5% nominal WACC, 9% nominal
        # growth, 5% terminal, 5% CPI, 100M shares, no debt.
        out = compute_real_terms_dcf(
            base_fcf=1000,
            nominal_wacc=12.5,
            nominal_growth=9,
            terminal_growth=5,
            current_cpi=5,
            shares=100,
            net_debt=0,
        )
        assert out is not None
        assert out > 0
        assert math.isfinite(out)

    def test_high_cpi_real_terms_differs_from_low_cpi(self):
        # Same engine inputs, different CPI — the real-terms FV must
        # diverge because the spread (r-g) shifts.
        baseline = compute_real_terms_dcf(
            base_fcf=1000,
            nominal_wacc=12,
            nominal_growth=10,
            terminal_growth=5,
            current_cpi=5,
            shares=100,
            net_debt=0,
        )
        stressed = compute_real_terms_dcf(
            base_fcf=1000,
            nominal_wacc=12,
            nominal_growth=10,
            terminal_growth=5,
            current_cpi=8,
            shares=100,
            net_debt=0,
        )
        # At least one must be defined; if both are, they should
        # differ materially. (Stressed may be None when the spread
        # floor trips, which is itself a valid signal.)
        assert baseline is not None
        if stressed is not None:
            assert abs(stressed - baseline) > 0.01

    def test_horizon_param_changes_value(self):
        a = compute_real_terms_dcf(
            base_fcf=1000,
            nominal_wacc=12,
            nominal_growth=8,
            terminal_growth=5,
            current_cpi=5,
            shares=100,
            net_debt=0,
            horizon_years=3,
        )
        b = compute_real_terms_dcf(
            base_fcf=1000,
            nominal_wacc=12,
            nominal_growth=8,
            terminal_growth=5,
            current_cpi=5,
            shares=100,
            net_debt=0,
            horizon_years=10,
        )
        assert a is not None and b is not None
        assert a != b


# ─────────────────────────────────────────────────────────────────
# compute_regime_adjustment
# ─────────────────────────────────────────────────────────────────
class TestComputeRegimeAdjustment:
    def _kwargs(self, **over):
        kw = dict(
            nominal_dcf=1000.0,
            base_fcf=1000.0,
            nominal_wacc=12.0,
            nominal_growth=9.0,
            terminal_growth=5.0,
            current_cpi=5.0,
            shares=100.0,
            net_debt=0.0,
        )
        kw.update(over)
        return kw

    def test_normal_regime_recommends_nominal(self):
        res = compute_regime_adjustment(**self._kwargs())
        assert res.regime == "normal"
        # Normal regime never flips to use_real even if distortion is
        # mathematically wide — the conservative default is nominal.
        assert res.model_note == "use_nominal"
        assert res.real_wacc_pct == pytest.approx(7.0, rel=1e-3)
        assert res.real_growth_pct == pytest.approx(4.0, rel=1e-3)

    def test_extreme_regime_classification(self):
        res = compute_regime_adjustment(**self._kwargs(current_cpi=10.0))
        assert res.regime == "extreme"
        assert res.current_cpi_pct == pytest.approx(10.0, rel=1e-3)

    def test_high_regime_recommends_real_when_distortion_wide(self):
        # Construct inputs where the nominal FV (passed in) diverges
        # from the recompute by >= 20%.
        res = compute_regime_adjustment(
            **self._kwargs(
                nominal_dcf=100.0,  # artificially low nominal forces a wide gap
                current_cpi=7.0,
            ),
        )
        assert res.regime == "high"
        if res.real_terms_fv is not None:
            assert res.model_note in ("use_real", "blended")

    def test_nominal_dcf_none_yields_zero_distortion(self):
        res = compute_regime_adjustment(**self._kwargs(nominal_dcf=None))
        assert res.nominal_fv is None
        assert res.fv_distortion_pct == 0.0
        assert res.model_note == "use_nominal"

    def test_real_fv_none_downgrades_model_note(self):
        # Force the real recompute to fail by collapsing the spread.
        # nominal_wacc=10, terminal_growth=9.5, cpi=5 -> real_wacc=5,
        # real_terminal=4.5 -> spread 0.5% < MIN_TERMINAL_SPREAD (1%).
        res = compute_regime_adjustment(
            **self._kwargs(
                nominal_wacc=10.0,
                nominal_growth=9.0,
                terminal_growth=9.5,
                current_cpi=5.0,
            ),
        )
        assert res.real_terms_fv is None
        # Cannot recommend use_real without a real_fv to anchor it.
        assert res.model_note != "use_real"


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────
class TestToDict:
    def test_round_trip(self):
        res = InflationRegimeResult(
            current_cpi_pct=5.0,
            regime="normal",
            real_wacc_pct=7.0,
            real_growth_pct=4.0,
            nominal_fv=1000.0,
            real_terms_fv=980.0,
            fv_distortion_pct=-2.0,
            model_note="use_nominal",
        )
        d = to_dict(res)
        assert d["regime"] == "normal"
        assert d["current_cpi_pct"] == 5.0
        assert d["real_terms_fv"] == 980.0
        assert set(d.keys()) == {
            "current_cpi_pct",
            "regime",
            "real_wacc_pct",
            "real_growth_pct",
            "nominal_fv",
            "real_terms_fv",
            "fv_distortion_pct",
            "model_note",
        }

    def test_to_dict_none_safe(self):
        assert to_dict(None) == {}  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────
# Module-level constants honoured
# ─────────────────────────────────────────────────────────────────
def test_default_horizon_is_5():
    assert DEFAULT_HORIZON_YEARS == 5
