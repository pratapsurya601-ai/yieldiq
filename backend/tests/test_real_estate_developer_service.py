# backend/tests/test_real_estate_developer_service.py
"""Unit tests for the RE developer cap-rate / NAV engine (T3.4 Phase A)."""
from __future__ import annotations

import math

import pytest

from backend.services.real_estate_developer_service import (
    RE_DEVELOPER_TICKERS,
    REDeveloperInputs,
    REDeveloperResult,
    compute_developer_nav,
    get_segment_cap_rate,
    is_re_developer_applicable,
    to_dict,
)


# ──────────────────────────────────────────────────────────────────
# Segment cap-rate lookup
# ──────────────────────────────────────────────────────────────────
class TestSegmentCapRate:
    def test_residential(self) -> None:
        assert get_segment_cap_rate("residential") == 7.0

    def test_commercial(self) -> None:
        assert get_segment_cap_rate("commercial") == 8.0

    def test_mixed(self) -> None:
        assert get_segment_cap_rate("mixed") == 7.5

    def test_luxury(self) -> None:
        assert get_segment_cap_rate("luxury") == 6.0

    def test_unknown_falls_back_to_residential(self) -> None:
        assert get_segment_cap_rate("retail") == 7.0

    def test_case_insensitive(self) -> None:
        assert get_segment_cap_rate("LUXURY") == 6.0
        assert get_segment_cap_rate("Mixed") == 7.5

    def test_none_falls_back_to_residential(self) -> None:
        assert get_segment_cap_rate(None) == 7.0  # type: ignore[arg-type]

    def test_empty_string_falls_back_to_residential(self) -> None:
        assert get_segment_cap_rate("") == 7.0

    def test_whitespace_handled(self) -> None:
        assert get_segment_cap_rate("  luxury  ") == 6.0


# ──────────────────────────────────────────────────────────────────
# Headline ticker-shape scenarios (DLF, GODREJPROP, OBEROIRLTY)
# ──────────────────────────────────────────────────────────────────
class TestHeadlineScenarios:
    def test_dlf_shape_mixed_developer(self) -> None:
        """DLF-shape: 50 msf land, 5000 Cr forward sales, mixed segment.

        Land bank: 50e6 * (8000-3000) * 0.25 / 1e7 = 6250 Cr
        Forward:   5000 * 0.25 = 1250 Cr
        Rental:    50e6 * 8000 / 1e7 * 0.075 / 0.075 = 40000 Cr
        Net debt:  -2000 Cr (DLF is net cash; bumps NAV up)
        Total:     6250 + 1250 + 40000 + 2000 = 49500 Cr
        Per share: 49500e7 / 2.48e9 = ~199.6
        """
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=50.0,
            realization_per_sf_inr=8000.0,
            construction_cost_per_sf_inr=3000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=7.5,
            forward_sales_pipeline_inr_cr=5000.0,
            completed_rental_yield_pct=7.5,
            net_debt_inr_cr=-2000.0,
            shares_outstanding=2.48e9,
            segment="mixed",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        assert result.nav_per_share > 0
        # Land bank + forward + rental + net cash positive
        assert result.components["land_bank_value"] == pytest.approx(6250.0, rel=0.01)
        assert result.components["forward_sales_value"] == pytest.approx(1250.0, rel=0.01)
        assert result.components["rental_perpetuity"] == pytest.approx(40000.0, rel=0.01)
        assert result.components["net_debt"] == pytest.approx(-2000.0, rel=0.01)
        # Per share ≈ 49500 * 1e7 / 2.48e9 ≈ 199.6
        assert 150.0 <= result.nav_per_share <= 250.0
        assert result.sanity_warnings == []

    def test_godrejprop_shape_residential(self) -> None:
        """GODREJPROP: residential developer, 30 msf, 3000 Cr forward sales."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=30.0,
            realization_per_sf_inr=9500.0,
            construction_cost_per_sf_inr=3500.0,
            operating_margin_pct=22.0,
            cap_rate_pct=7.0,
            forward_sales_pipeline_inr_cr=3000.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=500.0,
            shares_outstanding=2.78e8,
            segment="residential",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        assert result.nav_per_share > 0
        # land = 30e6 * 6000 * 0.22 / 1e7 = 3960 Cr
        assert result.components["land_bank_value"] == pytest.approx(3960.0, rel=0.01)
        # forward = 3000 * 0.22 = 660
        assert result.components["forward_sales_value"] == pytest.approx(660.0, rel=0.01)
        assert result.components["net_debt"] == pytest.approx(500.0, rel=0.01)

    def test_oberoirlty_shape_luxury_lower_cap_rate(self) -> None:
        """OBEROIRLTY-shape: luxury developer, 10 msf, premium realization,
        LOWER cap rate (6%) yields HIGHER rental perpetuity multiple.
        """
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=20000.0,
            construction_cost_per_sf_inr=6000.0,
            operating_margin_pct=30.0,
            cap_rate_pct=6.0,
            forward_sales_pipeline_inr_cr=2500.0,
            completed_rental_yield_pct=8.0,
            net_debt_inr_cr=-1500.0,
            shares_outstanding=3.64e8,
            segment="luxury",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        # Luxury cap rate (6%) inflates rental capitalisation:
        # gross_sale = 10e6 * 20000 / 1e7 = 20000 Cr
        # annuity = 20000 * 0.08 = 1600 Cr
        # cap = 1600 / 0.06 = 26666.67 Cr
        assert result.components["rental_perpetuity"] == pytest.approx(26666.67, rel=0.01)

    def test_phoenixltd_shape_commercial(self) -> None:
        """PHOENIXLTD: commercial-heavy (malls), 8% cap rate."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=15.0,
            realization_per_sf_inr=14000.0,
            construction_cost_per_sf_inr=5000.0,
            operating_margin_pct=28.0,
            cap_rate_pct=8.0,
            forward_sales_pipeline_inr_cr=1000.0,
            completed_rental_yield_pct=10.0,  # commercial annuity-heavy
            net_debt_inr_cr=3000.0,
            shares_outstanding=1.79e8,
            segment="commercial",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        assert result.nav_per_share > 0

    def test_sobha_shape_residential_low_pipeline(self) -> None:
        """SOBHA: residential, modest forward-sales pipeline."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=20.0,
            realization_per_sf_inr=8500.0,
            construction_cost_per_sf_inr=4500.0,
            operating_margin_pct=20.0,
            cap_rate_pct=7.0,
            forward_sales_pipeline_inr_cr=1500.0,
            completed_rental_yield_pct=3.0,
            net_debt_inr_cr=1200.0,
            shares_outstanding=9.49e7,
            segment="residential",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        assert result.nav_per_share > 0


# ──────────────────────────────────────────────────────────────────
# Component-math correctness
# ──────────────────────────────────────────────────────────────────
class TestComponentMath:
    def test_land_bank_value_formula(self) -> None:
        """land_bank_value = msf * 1e6 * spread * margin/100 / 1e7"""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=20.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=0.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
            segment="residential",
        ))
        # 10e6 * 6000 * 0.20 / 1e7 = 1200 Cr
        assert result.components["land_bank_value"] == pytest.approx(1200.0, rel=0.001)

    def test_forward_sales_value_formula(self) -> None:
        """forward_sales_value = pipeline_cr * margin/100"""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=0.001,  # tiny so dominant component is forward
            forward_sales_pipeline_inr_cr=10000.0,
            operating_margin_pct=30.0,
            completed_rental_yield_pct=0.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        ))
        # 10000 * 0.30 = 3000 Cr
        assert result.components["forward_sales_value"] == pytest.approx(3000.0, rel=0.001)

    def test_rental_perpetuity_lower_cap_rate_larger(self) -> None:
        """Lower cap rate ⇒ bigger rental perpetuity (1/cap multiplier)."""
        base = REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=10000.0,  # spread=0, isolates rental
            operating_margin_pct=25.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        )
        # cap=8 vs cap=6
        r8 = compute_developer_nav(REDeveloperInputs(**{**base.__dict__, "cap_rate_pct": 8.0, "segment": "commercial"}))
        r6 = compute_developer_nav(REDeveloperInputs(**{**base.__dict__, "cap_rate_pct": 6.0, "segment": "luxury"}))
        # rental(6) / rental(8) = 8/6 ≈ 1.333
        ratio = r6.components["rental_perpetuity"] / r8.components["rental_perpetuity"]
        assert ratio == pytest.approx(8.0 / 6.0, rel=0.001)

    def test_net_debt_subtracted(self) -> None:
        """Positive net debt subtracts; negative (net cash) adds."""
        base = REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=25.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=0.0,
            shares_outstanding=1.0e8,
        )
        r_debt = compute_developer_nav(REDeveloperInputs(**{**base.__dict__, "net_debt_inr_cr": 500.0}))
        r_cash = compute_developer_nav(REDeveloperInputs(**{**base.__dict__, "net_debt_inr_cr": -500.0}))
        assert r_debt.nav_per_share is not None
        assert r_cash.nav_per_share is not None
        # Net cash NAV exceeds net debt NAV by 1000 Cr / shares * 1e7
        diff = r_cash.nav_per_share - r_debt.nav_per_share
        expected_diff = (1000.0 * 1e7) / 1.0e8
        assert diff == pytest.approx(expected_diff, rel=0.001)

    def test_per_share_division(self) -> None:
        """nav_per_share = nav_cr * 1e7 / shares."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=25.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=0.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        ))
        # land_bank = 10e6 * 6000 * 0.25 / 1e7 = 1500 Cr
        nav_cr = 1500.0
        expected = nav_cr * 1e7 / 1.0e8
        assert result.nav_per_share == pytest.approx(expected, rel=0.001)


# ──────────────────────────────────────────────────────────────────
# Segment routing
# ──────────────────────────────────────────────────────────────────
class TestSegmentRouting:
    def test_luxury_segment_default_cap_rate(self) -> None:
        """When cap_rate=0 (invalid), luxury falls back to 6%."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=5.0,
            realization_per_sf_inr=15000.0,
            construction_cost_per_sf_inr=5000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=0.0,  # invalid → segment fallback
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
            segment="luxury",
        ))
        # gross_sale = 5e6 * 15000 / 1e7 = 7500 Cr
        # annuity = 7500 * 0.05 = 375
        # cap @ 6% = 375 / 0.06 = 6250
        assert result.components["rental_perpetuity"] == pytest.approx(6250.0, rel=0.001)
        assert any("segment default" in w for w in result.sanity_warnings)

    def test_commercial_segment_default_cap_rate(self) -> None:
        """When cap_rate=0, commercial falls back to 8%."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=5.0,
            realization_per_sf_inr=15000.0,
            construction_cost_per_sf_inr=5000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=0.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
            segment="commercial",
        ))
        # cap @ 8% = 375 / 0.08 = 4687.5
        assert result.components["rental_perpetuity"] == pytest.approx(4687.5, rel=0.001)


# ──────────────────────────────────────────────────────────────────
# Defensive paths
# ──────────────────────────────────────────────────────────────────
class TestDefensivePaths:
    def test_zero_shares_returns_unavailable(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=50.0,
            shares_outstanding=0.0,
        ))
        assert result.method == "unavailable"
        assert result.nav_per_share is None
        assert any("shares_outstanding" in w for w in result.sanity_warnings)

    def test_negative_shares_returns_unavailable(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=50.0,
            shares_outstanding=-1000.0,
        ))
        assert result.method == "unavailable"
        assert result.nav_per_share is None

    def test_nan_shares_returns_unavailable(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=50.0,
            shares_outstanding=float("nan"),
        ))
        assert result.method == "unavailable"
        assert result.nav_per_share is None

    def test_negative_land_bank_clamped(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=-10.0,
            forward_sales_pipeline_inr_cr=1000.0,
            shares_outstanding=1.0e8,
        ))
        # Forward sales alone keeps NAV positive
        assert result.method == "nav_developer"
        assert result.components["land_bank_value"] == 0.0
        assert any("land_bank_msf" in w and "0" in w for w in result.sanity_warnings)

    def test_inverted_spread_clamped(self) -> None:
        """construction > realization ⇒ spread clamped to 0, NAV from
        rental + forward only."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=3000.0,
            construction_cost_per_sf_inr=5000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=8.0,
            forward_sales_pipeline_inr_cr=2000.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
            segment="residential",
        ))
        assert result.components["land_bank_value"] == 0.0
        assert any("exceeds" in w for w in result.sanity_warnings)
        # forward + rental keep NAV positive
        assert result.nav_per_share is not None
        assert result.nav_per_share > 0

    def test_negative_nav_returns_unavailable(self) -> None:
        """Net debt eating the whole asset stack ⇒ NAV framework
        not applicable."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=1.0,
            realization_per_sf_inr=5000.0,
            construction_cost_per_sf_inr=3000.0,
            operating_margin_pct=10.0,
            forward_sales_pipeline_inr_cr=100.0,
            completed_rental_yield_pct=2.0,
            cap_rate_pct=8.0,
            net_debt_inr_cr=1_000_000.0,  # cosmic net debt
            shares_outstanding=1.0e8,
        ))
        assert result.method == "unavailable"
        assert result.nav_per_share is None
        assert any("non-positive" in w for w in result.sanity_warnings)

    def test_nan_inputs_default(self) -> None:
        """NaN per-sf, margin, cap → all default, NAV still computed."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=float("nan"),
            construction_cost_per_sf_inr=float("nan"),
            operating_margin_pct=float("nan"),
            cap_rate_pct=float("nan"),
            forward_sales_pipeline_inr_cr=float("nan"),
            completed_rental_yield_pct=float("nan"),
            net_debt_inr_cr=float("nan"),
            shares_outstanding=1.0e8,
            segment="residential",
        ))
        assert result.method == "nav_developer"
        assert result.nav_per_share is not None
        # Many warnings fired
        assert len(result.sanity_warnings) >= 5

    def test_margin_above_100_clamped(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=150.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=0.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        ))
        # margin clamped to 100 — land bank = 10e6 * 6000 * 1.0 / 1e7 = 6000 Cr
        assert result.components["land_bank_value"] == pytest.approx(6000.0, rel=0.001)
        assert any("operating_margin_pct" in w for w in result.sanity_warnings)

    def test_extreme_cap_rate_clamped(self) -> None:
        """cap_rate=50% (extreme) is clamped to 20% upper band."""
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=50.0,
            forward_sales_pipeline_inr_cr=0.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        ))
        # cap clamped to 20%; gross_sale = 10000 Cr; annuity = 500; cap = 2500
        assert result.components["rental_perpetuity"] == pytest.approx(2500.0, rel=0.001)
        assert any("cap_rate_pct" in w for w in result.sanity_warnings)

    def test_negative_forward_sales_clamped(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=25.0,
            forward_sales_pipeline_inr_cr=-500.0,
            completed_rental_yield_pct=0.0,
            net_debt_inr_cr=0.0,
            shares_outstanding=1.0e8,
        ))
        assert result.components["forward_sales_value"] == 0.0


# ──────────────────────────────────────────────────────────────────
# Applicability gate
# ──────────────────────────────────────────────────────────────────
class TestApplicability:
    def test_all_ten_dev_tickers_applicable(self) -> None:
        for ticker in [
            "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE",
            "PHOENIXLTD", "BRIGADE", "SOBHA", "MAHLIFE",
            "SUNTECK", "LODHA",
        ]:
            ok, reason = is_re_developer_applicable(ticker)
            assert ok, f"{ticker} should be applicable: {reason}"

    def test_ns_suffix_stripped(self) -> None:
        ok, _ = is_re_developer_applicable("DLF.NS")
        assert ok

    def test_bo_suffix_stripped(self) -> None:
        ok, _ = is_re_developer_applicable("OBEROIRLTY.BO")
        assert ok

    def test_lowercase_normalized(self) -> None:
        ok, _ = is_re_developer_applicable("dlf")
        assert ok

    def test_reit_not_routed_here(self) -> None:
        """REITs (EMBASSY, MINDSPACE) must NOT route through this
        engine — they have their own realty_valuation_service."""
        for reit in ["EMBASSY", "MINDSPACE", "BROOKFIELD"]:
            ok, _ = is_re_developer_applicable(reit, sector="Realty")
            assert not ok, f"REIT {reit} should NOT be applicable"

    def test_unrelated_ticker_not_applicable(self) -> None:
        ok, reason = is_re_developer_applicable("TCS", sector="IT")
        assert not ok
        assert "TCS" in reason

    def test_empty_ticker_not_applicable(self) -> None:
        ok, _ = is_re_developer_applicable("")
        assert not ok

    def test_none_ticker_not_applicable(self) -> None:
        ok, _ = is_re_developer_applicable(None)  # type: ignore[arg-type]
        assert not ok

    def test_non_string_ticker_not_applicable(self) -> None:
        ok, _ = is_re_developer_applicable(123)  # type: ignore[arg-type]
        assert not ok


# ──────────────────────────────────────────────────────────────────
# Universe registry invariants
# ──────────────────────────────────────────────────────────────────
class TestUniverse:
    def test_universe_has_ten_tickers(self) -> None:
        assert len(RE_DEVELOPER_TICKERS) == 10

    def test_all_segments_are_valid_literals(self) -> None:
        valid = {"residential", "commercial", "mixed", "luxury"}
        for ticker, seg in RE_DEVELOPER_TICKERS.items():
            assert seg in valid, f"{ticker} has invalid segment {seg!r}"

    def test_universe_keys_are_uppercase(self) -> None:
        for ticker in RE_DEVELOPER_TICKERS:
            assert ticker == ticker.upper()


# ──────────────────────────────────────────────────────────────────
# to_dict JSON-safe projection
# ──────────────────────────────────────────────────────────────────
class TestToDict:
    def test_to_dict_shape_on_success(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            realization_per_sf_inr=10000.0,
            construction_cost_per_sf_inr=4000.0,
            operating_margin_pct=25.0,
            cap_rate_pct=7.5,
            forward_sales_pipeline_inr_cr=1000.0,
            completed_rental_yield_pct=5.0,
            net_debt_inr_cr=200.0,
            shares_outstanding=1.0e8,
            segment="mixed",
        ))
        d = to_dict(result)
        assert set(d.keys()) == {"nav_per_share", "components", "method", "sanity_warnings"}
        assert isinstance(d["components"], dict)
        assert set(d["components"].keys()) == {
            "land_bank_value", "forward_sales_value",
            "rental_perpetuity", "net_debt",
        }
        assert isinstance(d["sanity_warnings"], list)
        assert d["method"] == "nav_developer"

    def test_to_dict_shape_on_unavailable(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            shares_outstanding=0.0,
        ))
        d = to_dict(result)
        assert d["nav_per_share"] is None
        assert d["method"] == "unavailable"
        assert isinstance(d["sanity_warnings"], list)
        assert len(d["sanity_warnings"]) >= 1

    def test_to_dict_components_are_floats(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            shares_outstanding=1.0e8,
        ))
        d = to_dict(result)
        for k, v in d["components"].items():
            assert isinstance(v, (int, float)), f"{k}={v!r} not numeric"

    def test_to_dict_warnings_are_strings(self) -> None:
        result = compute_developer_nav(REDeveloperInputs(
            land_bank_msf=10.0,
            operating_margin_pct=float("nan"),
            shares_outstanding=1.0e8,
        ))
        d = to_dict(result)
        for w in d["sanity_warnings"]:
            assert isinstance(w, str)
