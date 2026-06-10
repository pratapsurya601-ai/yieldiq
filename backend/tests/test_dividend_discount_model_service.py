# backend/tests/test_dividend_discount_model_service.py
"""
Tests for the standalone DDM service (T2.1 Phase A).

Coverage:
    - Gordon Growth: hand-computed inputs, divergent inputs (g >= k),
      degenerate inputs (dividend <= 0, missing cost of equity).
    - Two-stage DDM: hand-computed reference value, missing high_growth.
    - H-model: formula verification, inverted (g_h < g_t) warning path.
    - select_and_compute: FMCG / IT / utility / bank sector routing,
      sector-keyword exclusions.
    - is_ddm_applicable: HUL-shaped success, TATAMOTORS-shaped payout
      fail, ZOMATO-shaped no-dividend fail, sector exclusion.
    - to_dict shape.
"""
from __future__ import annotations

import math

import pytest

from backend.services.dividend_discount_model_service import (
    DDMInputs,
    DDMResult,
    gordon_growth,
    h_model,
    is_ddm_applicable,
    select_and_compute,
    to_dict,
    two_stage_ddm,
)


# ─────────────────────────────────────────────────────────────────
# Gordon Growth
# ─────────────────────────────────────────────────────────────────

class TestGordonGrowth:
    def test_known_inputs_hand_computed(self):
        """D=10, k=0.11, g=0.05 -> FV = 10 * 1.05 / (0.11 - 0.05) = 175.0."""
        result = gordon_growth(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.11, stable_growth=0.05)
        )
        assert result.method == "gordon"
        assert result.fair_value is not None
        assert math.isclose(result.fair_value, 175.0, rel_tol=1e-6)
        assert result.sanity_warnings == []

    def test_g_equals_k_returns_none(self):
        """g == k makes the perpetuity diverge; return None + warning."""
        result = gordon_growth(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.10, stable_growth=0.10)
        )
        assert result.fair_value is None
        assert result.method == "gordon"
        assert any("g >= k" in w for w in result.sanity_warnings)

    def test_g_greater_than_k_returns_none(self):
        """g > k is mathematically invalid; return None."""
        result = gordon_growth(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.10, stable_growth=0.12)
        )
        assert result.fair_value is None
        assert any("g >= k" in w for w in result.sanity_warnings)

    def test_negative_dividend_returns_none(self):
        """Negative dividend is degenerate; return None + warning."""
        result = gordon_growth(
            DDMInputs(current_dividend=-5.0, cost_of_equity=0.11, stable_growth=0.05)
        )
        assert result.fair_value is None
        assert any("dividend" in w for w in result.sanity_warnings)

    def test_zero_dividend_returns_none(self):
        """Zero dividend is degenerate; return None + warning."""
        result = gordon_growth(
            DDMInputs(current_dividend=0.0, cost_of_equity=0.11, stable_growth=0.05)
        )
        assert result.fair_value is None
        assert any("dividend" in w for w in result.sanity_warnings)

    def test_tight_spread_returns_none(self):
        """k - g < 50bps is numerically unstable; return None."""
        result = gordon_growth(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.11, stable_growth=0.108)
        )
        assert result.fair_value is None
        assert any("unstable" in w for w in result.sanity_warnings)

    def test_zero_cost_of_equity_returns_none(self):
        """k = 0 is degenerate."""
        result = gordon_growth(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.0, stable_growth=0.05)
        )
        assert result.fair_value is None
        assert any("cost_of_equity" in w for w in result.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# Two-Stage DDM
# ─────────────────────────────────────────────────────────────────

class TestTwoStageDDM:
    def test_hand_computed_reference(self):
        """High-growth 10% for 5y, then stable 5% forever, k=11%, D_0=10.

        Hand-compute the explicit dividend forecast:
            D_1 = 10 * 1.10 = 11.0
            D_2 = 12.1
            D_3 = 13.31
            D_4 = 14.641
            D_5 = 16.1051
        PV stage 1 discounted at 11%:
            PV = sum_{t=1..5} D_t / 1.11^t
               = 11/1.11 + 12.1/1.2321 + 13.31/1.367631 +
                 14.641/1.51807041 + 16.1051/1.685058
        Computing each term exactly using the same formulas:
            t=1: 9.9099099099...
            t=2: 9.8189640...
            t=3: 9.7287325...
            t=4: 9.6418234...
            t=5: 9.5562072...
        Sum ~ 48.6556370
        D_6 = D_5 * 1.05 = 16.910355
        TV at year 5 = D_6 / (0.11 - 0.05) = 281.83925
        PV of TV = 281.83925 / 1.685058 = 167.2580...
        Total ~ 215.9136

        We re-derive in-test to avoid silent drift.
        """
        d0 = 10.0
        k = 0.11
        g_h = 0.10
        g_t = 0.05
        n = 5

        expected = 0.0
        d_t = d0
        for t in range(1, n + 1):
            d_t = d_t * (1 + g_h)
            expected += d_t / ((1 + k) ** t)
        d_n_plus_1 = d_t * (1 + g_t)
        tv = d_n_plus_1 / (k - g_t)
        expected += tv / ((1 + k) ** n)

        result = two_stage_ddm(
            DDMInputs(
                current_dividend=d0,
                cost_of_equity=k,
                stable_growth=g_t,
                high_growth=g_h,
                high_growth_years=n,
            )
        )
        assert result.method == "two_stage"
        assert result.fair_value is not None
        assert math.isclose(result.fair_value, round(expected, 2), rel_tol=1e-4)

    def test_missing_high_growth_returns_none(self):
        result = two_stage_ddm(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.11, stable_growth=0.05)
        )
        assert result.fair_value is None
        assert any("high_growth" in w for w in result.sanity_warnings)

    def test_terminal_g_geq_k_returns_none(self):
        """g_t >= k makes terminal perpetuity diverge."""
        result = two_stage_ddm(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.10,
                stable_growth=0.10,
                high_growth=0.05,
                high_growth_years=5,
            )
        )
        assert result.fair_value is None
        assert any("g_t >= k" in w for w in result.sanity_warnings)

    def test_high_growth_above_k_warns_but_computes(self):
        """g_h > k is informational; finite stage 1 sum still works."""
        result = two_stage_ddm(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.10,
                stable_growth=0.04,
                high_growth=0.15,  # above k
                high_growth_years=3,
            )
        )
        assert result.fair_value is not None
        assert any(
            "g_h >= k" in w or "high-growth above" in w
            for w in result.sanity_warnings
        )

    def test_zero_high_growth_years_returns_none(self):
        result = two_stage_ddm(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.11,
                stable_growth=0.05,
                high_growth=0.10,
                high_growth_years=0,
            )
        )
        assert result.fair_value is None
        assert any(
            "high_growth_years" in w for w in result.sanity_warnings
        )


# ─────────────────────────────────────────────────────────────────
# H-Model
# ─────────────────────────────────────────────────────────────────

class TestHModel:
    def test_hand_computed_formula(self):
        """g_h=0.10, g_t=0.04, H=5, D_0=10, k=0.11.

        P = D_0 * [(1 + g_t) + H * (g_h - g_t)] / (k - g_t)
          = 10 * [1.04 + 5 * 0.06] / 0.07
          = 10 * [1.04 + 0.30] / 0.07
          = 10 * 1.34 / 0.07
          = 191.42857...
        """
        result = h_model(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.11,
                stable_growth=0.04,
                high_growth=0.10,
                high_growth_years=5,
            )
        )
        assert result.method == "h_model"
        assert result.fair_value is not None
        assert math.isclose(result.fair_value, 191.43, rel_tol=1e-3)

    def test_missing_high_growth_returns_none(self):
        result = h_model(
            DDMInputs(current_dividend=10.0, cost_of_equity=0.11, stable_growth=0.04)
        )
        assert result.fair_value is None
        assert any("high_growth" in w for w in result.sanity_warnings)

    def test_terminal_g_geq_k_returns_none(self):
        result = h_model(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.05,
                stable_growth=0.05,
                high_growth=0.08,
                high_growth_years=5,
            )
        )
        assert result.fair_value is None
        assert any("g_t >= k" in w for w in result.sanity_warnings)

    def test_inverted_growth_warns_but_computes(self):
        """g_h < g_t flips the H-model intent; it still produces a
        number but emits a warning so the caller sees the math."""
        result = h_model(
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.11,
                stable_growth=0.06,
                high_growth=0.03,  # below g_t
                high_growth_years=5,
            )
        )
        assert result.fair_value is not None
        assert any("taper" in w for w in result.sanity_warnings)


# ─────────────────────────────────────────────────────────────────
# select_and_compute (routing)
# ─────────────────────────────────────────────────────────────────

class TestSelectAndCompute:
    def test_fmcg_routes_to_gordon(self):
        """HUL-shaped: FMCG sector, high payout -> Gordon single-stage."""
        result = select_and_compute(
            ticker="HINDUNILVR",
            sector="FMCG",
            inputs=DDMInputs(
                current_dividend=42.0,
                cost_of_equity=0.105,
                stable_growth=0.055,
                expected_payout_ratio=0.85,
            ),
        )
        assert result.method == "gordon"
        assert result.fair_value is not None

    def test_it_services_routes_to_gordon(self):
        """TCS-shaped: IT services, ~60% payout -> Gordon."""
        result = select_and_compute(
            ticker="TCS",
            sector="IT Services",
            inputs=DDMInputs(
                current_dividend=120.0,
                cost_of_equity=0.115,
                stable_growth=0.055,
                expected_payout_ratio=0.60,
            ),
        )
        assert result.method == "gordon"
        assert result.fair_value is not None

    def test_utility_routes_to_gordon(self):
        """NTPC-shaped: utility -> Gordon."""
        result = select_and_compute(
            ticker="NTPC",
            sector="Power Generation",
            inputs=DDMInputs(
                current_dividend=7.0,
                cost_of_equity=0.11,
                stable_growth=0.04,
                expected_payout_ratio=0.45,
            ),
        )
        assert result.method == "gordon"
        assert result.fair_value is not None

    def test_bank_routes_to_gordon(self):
        """Bank sector keyword -> Gordon."""
        result = select_and_compute(
            ticker="HDFCBANK",
            sector="Banking",
            inputs=DDMInputs(
                current_dividend=19.5,
                cost_of_equity=0.13,
                stable_growth=0.06,
                expected_payout_ratio=0.30,
            ),
        )
        assert result.method == "gordon"
        assert result.fair_value is not None

    def test_unknown_sector_with_high_growth_routes_to_h_model(self):
        """Generic sector + high_growth supplied -> H-model."""
        result = select_and_compute(
            ticker="GENERICCO",
            sector="Specialty Chemicals",
            inputs=DDMInputs(
                current_dividend=8.0,
                cost_of_equity=0.12,
                stable_growth=0.05,
                high_growth=0.09,
                high_growth_years=6,
            ),
        )
        assert result.method == "h_model"
        assert result.fair_value is not None

    def test_no_sector_falls_back_to_gordon(self):
        """sector=None + no high_growth -> Gordon."""
        result = select_and_compute(
            ticker="UNKNOWN",
            sector=None,
            inputs=DDMInputs(
                current_dividend=5.0,
                cost_of_equity=0.10,
                stable_growth=0.04,
            ),
        )
        assert result.method == "gordon"
        assert result.fair_value is not None

    def test_missing_dividend_returns_unavailable(self):
        result = select_and_compute(
            ticker="HINDUNILVR",
            sector="FMCG",
            inputs=DDMInputs(
                current_dividend=0.0,
                cost_of_equity=0.11,
                stable_growth=0.05,
            ),
        )
        assert result.method == "unavailable"
        assert result.fair_value is None

    def test_none_inputs_returns_unavailable(self):
        result = select_and_compute(
            ticker="ANY", sector="FMCG", inputs=None  # type: ignore[arg-type]
        )
        assert result.method == "unavailable"
        assert result.fair_value is None


# ─────────────────────────────────────────────────────────────────
# is_ddm_applicable
# ─────────────────────────────────────────────────────────────────

class TestIsDdmApplicable:
    def test_hul_high_payout_long_streak_applicable(self):
        """HUL-shaped: FMCG, payout 0.85, 20y streak -> applicable."""
        applicable, reason = is_ddm_applicable(
            ticker="HINDUNILVR",
            sector="FMCG",
            payout_ratio=0.85,
            dividend_streak_years=20,
        )
        assert applicable is True
        assert reason == "applicable"

    def test_tatamotors_low_payout_not_applicable(self):
        """TATAMOTORS-shaped: payout 0.10 -> not applicable; reason cites payout."""
        applicable, reason = is_ddm_applicable(
            ticker="TATAMOTORS",
            sector="Auto",
            payout_ratio=0.10,
            dividend_streak_years=3,
        )
        assert applicable is False
        assert "payout" in reason.lower()

    def test_zomato_no_dividend_not_applicable(self):
        """ZOMATO-shaped: no dividend (None payout) -> not applicable."""
        applicable, reason = is_ddm_applicable(
            ticker="ZOMATO",
            sector="Internet",
            payout_ratio=None,
            dividend_streak_years=None,
        )
        assert applicable is False
        assert "payout" in reason.lower()

    def test_short_streak_not_applicable(self):
        """High payout but only 2y streak -> not applicable (speculative growth)."""
        applicable, reason = is_ddm_applicable(
            ticker="RECENTPAYER",
            sector="FMCG",
            payout_ratio=0.50,
            dividend_streak_years=2,
        )
        assert applicable is False
        assert "streak" in reason.lower() or "5y" in reason

    def test_biotech_sector_excluded(self):
        """Biotech sector excluded regardless of payout / streak."""
        applicable, reason = is_ddm_applicable(
            ticker="BIOTECH",
            sector="Biotech",
            payout_ratio=0.40,
            dividend_streak_years=8,
        )
        assert applicable is False
        assert "biotech" in reason.lower()

    def test_holdco_sector_excluded(self):
        """Holdco sector excluded — fair value is sum-of-parts."""
        applicable, reason = is_ddm_applicable(
            ticker="BAJAJHLDNG",
            sector="Holding Company",
            payout_ratio=0.40,
            dividend_streak_years=10,
        )
        assert applicable is False
        assert "holdco" in reason.lower() or "holding" in reason.lower()

    def test_empty_ticker_not_applicable(self):
        applicable, reason = is_ddm_applicable(
            ticker="",
            sector="FMCG",
            payout_ratio=0.85,
            dividend_streak_years=20,
        )
        assert applicable is False

    def test_payout_at_threshold(self):
        """payout = 0.30 exactly -> applicable (boundary inclusive)."""
        applicable, _ = is_ddm_applicable(
            ticker="ANY",
            sector="FMCG",
            payout_ratio=0.30,
            dividend_streak_years=5,
        )
        assert applicable is True

    def test_streak_at_threshold(self):
        """streak = 5 exactly -> applicable (boundary inclusive)."""
        applicable, _ = is_ddm_applicable(
            ticker="ANY",
            sector="FMCG",
            payout_ratio=0.40,
            dividend_streak_years=5,
        )
        assert applicable is True


# ─────────────────────────────────────────────────────────────────
# to_dict serialization
# ─────────────────────────────────────────────────────────────────

class TestToDict:
    def test_shape(self):
        """to_dict returns flat fv + method + nested inputs + warnings."""
        inp = DDMInputs(
            current_dividend=10.0,
            cost_of_equity=0.11,
            stable_growth=0.05,
            high_growth=0.08,
            high_growth_years=5,
            expected_payout_ratio=0.65,
        )
        result = gordon_growth(inp)
        d = to_dict(result)

        assert set(d.keys()) == {
            "fair_value",
            "method",
            "inputs",
            "sanity_warnings",
        }
        assert d["method"] == "gordon"
        assert d["fair_value"] == result.fair_value
        assert isinstance(d["inputs"], dict)
        assert d["inputs"]["current_dividend"] == 10.0
        assert d["inputs"]["cost_of_equity"] == 0.11
        assert d["inputs"]["stable_growth"] == 0.05
        assert d["inputs"]["high_growth"] == 0.08
        assert d["inputs"]["high_growth_years"] == 5
        assert d["inputs"]["expected_payout_ratio"] == 0.65
        assert isinstance(d["sanity_warnings"], list)

    def test_none_result(self):
        """to_dict handles None gracefully."""
        d = to_dict(None)  # type: ignore[arg-type]
        assert d["fair_value"] is None
        assert d["method"] == "unavailable"
        assert d["inputs"] is None
        assert isinstance(d["sanity_warnings"], list)

    def test_unavailable_result(self):
        """Unavailable result still serializes cleanly."""
        result = select_and_compute(
            ticker="X",
            sector="FMCG",
            inputs=DDMInputs(
                current_dividend=0.0,
                cost_of_equity=0.0,
                stable_growth=0.05,
            ),
        )
        d = to_dict(result)
        assert d["method"] == "unavailable"
        assert d["fair_value"] is None
        assert d["inputs"] is not None  # inputs still echoed


# ─────────────────────────────────────────────────────────────────
# Defensive / never-raises invariant
# ─────────────────────────────────────────────────────────────────

class TestDefensive:
    @pytest.mark.parametrize(
        "inputs",
        [
            DDMInputs(current_dividend=10.0, cost_of_equity=0.11, stable_growth=0.05),
            DDMInputs(current_dividend=-1.0, cost_of_equity=0.11, stable_growth=0.05),
            DDMInputs(current_dividend=10.0, cost_of_equity=-0.01, stable_growth=0.05),
            DDMInputs(current_dividend=10.0, cost_of_equity=0.05, stable_growth=0.10),
            DDMInputs(
                current_dividend=10.0,
                cost_of_equity=0.11,
                stable_growth=0.05,
                high_growth=0.50,  # extreme g_h
                high_growth_years=50,  # beyond clamp
            ),
        ],
    )
    def test_never_raises(self, inputs):
        """No DDM variant raises on any input. Returns DDMResult."""
        assert isinstance(gordon_growth(inputs), DDMResult)
        assert isinstance(two_stage_ddm(inputs), DDMResult)
        assert isinstance(h_model(inputs), DDMResult)
        assert isinstance(
            select_and_compute("X", "FMCG", inputs), DDMResult
        )
