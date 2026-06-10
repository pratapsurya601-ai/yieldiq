# backend/tests/test_sbc_dilution_service.py
"""Unit tests for the SBC dilution service (T4.1 Phase A)."""
from __future__ import annotations

import math

import pytest

from backend.services.sbc_dilution_service import (
    SBC_HEAVY_TICKERS,
    SBCAdjustedFinancials,
    SBCInputs,
    classify_sbc_intensity,
    compute_sbc_adjustment,
    is_sbc_adjustment_meaningful,
    to_dict,
)


# ──────────────────────────────────────────────────────────────────
# Intensity classification — boundary cases
# ──────────────────────────────────────────────────────────────────
class TestClassifyIntensity:
    @pytest.mark.parametrize("pct", [-50.0, -1.0, 0.0, 0.5, 1.99, 2.0])
    def test_negligible(self, pct: float) -> None:
        assert classify_sbc_intensity(pct) == "negligible"

    @pytest.mark.parametrize("pct", [2.01, 3.0, 4.5, 5.0])
    def test_moderate(self, pct: float) -> None:
        assert classify_sbc_intensity(pct) == "moderate"

    @pytest.mark.parametrize("pct", [5.01, 10.0, 14.9, 15.0])
    def test_material(self, pct: float) -> None:
        assert classify_sbc_intensity(pct) == "material"

    @pytest.mark.parametrize("pct", [15.01, 20.0, 50.0, 200.0])
    def test_heavy(self, pct: float) -> None:
        assert classify_sbc_intensity(pct) == "heavy"

    def test_nan_buckets_negligible(self) -> None:
        assert classify_sbc_intensity(float("nan")) == "negligible"

    def test_non_numeric_buckets_negligible(self) -> None:
        # type: ignore-able — defensive path for upstream malformed
        # dict lookup that returns a string by mistake.
        assert classify_sbc_intensity("not a number") == "negligible"  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────
# Core compute — the headline scenarios called out in the brief
# ──────────────────────────────────────────────────────────────────
class TestComputeSBCAdjustment:
    def test_heavy_case_500cr_fcf_100cr_sbc(self) -> None:
        """Brief example #1: reported FCF 500Cr, SBC 100Cr → heavy."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=100.0,
            reported_shares_outstanding=10.0,    # 10 Cr shares
            current_price=1000.0,
        ))
        assert result.reported_fcf == 500.0
        assert result.sbc_adjusted_fcf == 400.0
        assert result.sbc_as_pct_of_fcf == 20.0
        assert result.sbc_intensity_label == "heavy"
        assert result.sanity_warnings == []

    def test_moderate_case_1000cr_fcf_30cr_sbc(self) -> None:
        """Brief example #2: FCF 1000Cr, SBC 30Cr → 3% → moderate."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=1000.0,
            sbc_expense_inr_cr=30.0,
            reported_shares_outstanding=50.0,
            current_price=500.0,
        ))
        assert result.reported_fcf == 1000.0
        assert result.sbc_adjusted_fcf == 970.0
        assert result.sbc_as_pct_of_fcf == 3.0
        assert result.sbc_intensity_label == "moderate"

    def test_negligible_case_10000cr_fcf_50cr_sbc(self) -> None:
        """Brief example #3: FCF 10000Cr, SBC 50Cr → 0.5% → negligible."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=10000.0,
            sbc_expense_inr_cr=50.0,
            reported_shares_outstanding=400.0,
            current_price=3500.0,
        ))
        assert result.reported_fcf == 10000.0
        assert result.sbc_adjusted_fcf == 9950.0
        assert result.sbc_as_pct_of_fcf == 0.5
        assert result.sbc_intensity_label == "negligible"

    def test_material_case_boundary(self) -> None:
        """1000Cr / 80Cr = 8% — squarely material."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=1000.0,
            sbc_expense_inr_cr=80.0,
            reported_shares_outstanding=50.0,
            current_price=200.0,
        ))
        assert result.sbc_adjusted_fcf == 920.0
        assert result.sbc_as_pct_of_fcf == 8.0
        assert result.sbc_intensity_label == "material"


# ──────────────────────────────────────────────────────────────────
# Forward-dilution leg
# ──────────────────────────────────────────────────────────────────
class TestForwardDilution:
    def test_forward_dilution_100cr_sbc_at_1000_price(self) -> None:
        """Brief example: SBC 100Cr / price 1000 = 0.1Cr shares added."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=100.0,
            reported_shares_outstanding=10.0,
            current_price=1000.0,
        ))
        assert result.forward_dilution_shares_added == 0.1
        assert result.dilution_adjusted_shares == 10.1

    def test_forward_dilution_zero_when_sbc_zero(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=0.0,
            reported_shares_outstanding=10.0,
            current_price=1000.0,
        ))
        assert result.forward_dilution_shares_added == 0.0
        assert result.dilution_adjusted_shares == 10.0


# ──────────────────────────────────────────────────────────────────
# Defensive paths — these are the ones that prevent prod crashes
# ──────────────────────────────────────────────────────────────────
class TestDefensivePaths:
    def test_negative_fcf_returns_reported_with_warning(self) -> None:
        """Loss-making companies — adjustment still produced (so the
        analyst can see the cash drain) but intensity is unknown."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=-200.0,
            sbc_expense_inr_cr=50.0,
            reported_shares_outstanding=10.0,
            current_price=100.0,
        ))
        assert result.reported_fcf == -200.0
        # FCF arithmetic still happens (caller may want to show it).
        assert result.sbc_adjusted_fcf == -250.0
        # But the intensity bucket is unknown — pct is undefined.
        assert result.sbc_intensity_label == "negligible"
        assert result.sbc_as_pct_of_fcf == 0.0
        assert "reported_fcf_non_positive_intensity_unknown" \
            in result.sanity_warnings

    def test_zero_shares_skips_dilution_leg(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=10.0,
            reported_shares_outstanding=0.0,
            current_price=100.0,
        ))
        assert result.forward_dilution_shares_added == 0.0
        assert result.dilution_adjusted_shares == 0.0
        assert "reported_shares_zero_or_invalid" \
            in result.sanity_warnings
        # FCF leg still works.
        assert result.sbc_adjusted_fcf == 490.0

    def test_zero_price_skips_dilution_added_only(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=10.0,
            reported_shares_outstanding=10.0,
            current_price=0.0,
        ))
        assert result.forward_dilution_shares_added == 0.0
        # When price is unknown we keep the reported share count.
        assert result.dilution_adjusted_shares == 10.0
        assert "current_price_zero_or_invalid" \
            in result.sanity_warnings

    def test_missing_sbc_treated_as_zero(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=float("nan"),
            reported_shares_outstanding=10.0,
            current_price=100.0,
        ))
        assert result.sbc_adjusted_fcf == 500.0
        assert result.sbc_intensity_label == "negligible"
        assert "sbc_expense_missing" in result.sanity_warnings

    def test_negative_sbc_clamped(self) -> None:
        """SBC reported negative (e.g. forfeitures > grants) — should
        not produce a negative adjustment that flatters reported FCF."""
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=-20.0,
            reported_shares_outstanding=10.0,
            current_price=100.0,
        ))
        assert result.sbc_adjusted_fcf == 500.0
        assert "sbc_expense_negative_clamped_to_zero" \
            in result.sanity_warnings

    def test_nan_fcf_returns_safe_shape(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=float("nan"),
            sbc_expense_inr_cr=10.0,
            reported_shares_outstanding=10.0,
            current_price=100.0,
        ))
        assert isinstance(result, SBCAdjustedFinancials)
        assert result.reported_fcf == 0.0
        assert result.sbc_adjusted_fcf == 0.0
        assert result.sbc_intensity_label == "negligible"
        assert "reported_fcf_non_finite" in result.sanity_warnings


# ──────────────────────────────────────────────────────────────────
# Surfacing gate
# ──────────────────────────────────────────────────────────────────
class TestIsAdjustmentMeaningful:
    def test_zomato_in_heavy_set(self) -> None:
        """ZOMATO is in SBC_HEAVY_TICKERS so meaningful even at low
        latest-FY ratio — the curated set catches noisy single years."""
        assert "ZOMATO" in SBC_HEAVY_TICKERS
        # Even with negligible single-FY intensity, the heavy-set
        # membership flips this True.
        assert is_sbc_adjustment_meaningful("ZOMATO", 0.5) is True

    def test_zomato_heavy_intensity_also_true(self) -> None:
        assert is_sbc_adjustment_meaningful("ZOMATO", 20.0) is True

    def test_tcs_below_threshold_false(self) -> None:
        """TCS not in heavy set and < 2% — meaningfulness gate must
        be False so we don't over-surface for the big IT bucket."""
        assert "TCS" not in SBC_HEAVY_TICKERS
        assert is_sbc_adjustment_meaningful("TCS", 1.0) is False

    def test_tcs_material_intensity_true(self) -> None:
        """Even TCS becomes meaningful if its SBC ratio spikes."""
        assert is_sbc_adjustment_meaningful("TCS", 8.0) is True

    def test_paytm_in_heavy_set(self) -> None:
        assert "PAYTM" in SBC_HEAVY_TICKERS
        assert is_sbc_adjustment_meaningful("PAYTM", 0.0) is True

    def test_empty_ticker_falls_back_to_intensity_only(self) -> None:
        assert is_sbc_adjustment_meaningful("", 20.0) is True
        assert is_sbc_adjustment_meaningful("", 1.0) is False

    def test_ticker_normalisation_handles_suffix(self) -> None:
        assert is_sbc_adjustment_meaningful("ZOMATO.NS", 0.5) is True
        assert is_sbc_adjustment_meaningful("zomato", 0.5) is True


# ──────────────────────────────────────────────────────────────────
# Serialization shape
# ──────────────────────────────────────────────────────────────────
class TestToDict:
    def test_shape_matches_dataclass(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=100.0,
            reported_shares_outstanding=10.0,
            current_price=1000.0,
        ))
        d = to_dict(result)
        expected_keys = {
            "reported_fcf",
            "sbc_adjusted_fcf",
            "sbc_as_pct_of_fcf",
            "reported_shares",
            "forward_dilution_shares_added",
            "dilution_adjusted_shares",
            "sbc_intensity_label",
            "sanity_warnings",
        }
        assert set(d.keys()) == expected_keys
        assert d["sbc_adjusted_fcf"] == 400.0
        assert d["sbc_intensity_label"] == "heavy"
        assert isinstance(d["sanity_warnings"], list)

    def test_to_dict_is_json_safe(self) -> None:
        import json
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=500.0,
            sbc_expense_inr_cr=100.0,
            reported_shares_outstanding=10.0,
            current_price=1000.0,
        ))
        # Must round-trip through JSON without errors.
        s = json.dumps(to_dict(result))
        round_tripped = json.loads(s)
        assert round_tripped["sbc_intensity_label"] == "heavy"

    def test_warnings_propagated(self) -> None:
        result = compute_sbc_adjustment(SBCInputs(
            reported_fcf=-100.0,
            sbc_expense_inr_cr=10.0,
            reported_shares_outstanding=10.0,
            current_price=100.0,
        ))
        d = to_dict(result)
        assert "reported_fcf_non_positive_intensity_unknown" \
            in d["sanity_warnings"]


# ──────────────────────────────────────────────────────────────────
# Sanity: heavy-ticker set hygiene
# ──────────────────────────────────────────────────────────────────
def test_heavy_set_excludes_big_it_services() -> None:
    """Anti-regression: TCS / INFY / WIPRO etc must NOT be in the
    heavy set (their SBC < 2% and classification handles them)."""
    for ticker in ("TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"):
        assert ticker not in SBC_HEAVY_TICKERS

    # And the curated set is non-empty.
    assert len(SBC_HEAVY_TICKERS) >= 10


def test_heavy_set_contains_platform_ipos() -> None:
    """Documentary: the names we expect to be flagged are flagged."""
    for ticker in ("ZOMATO", "NYKAA", "PAYTM"):
        assert ticker in SBC_HEAVY_TICKERS


def test_compute_returns_finite_values_for_typical_inputs() -> None:
    """Smoke: no NaN / inf leaks into the result for plausible inputs."""
    result = compute_sbc_adjustment(SBCInputs(
        reported_fcf=1234.5,
        sbc_expense_inr_cr=67.8,
        reported_shares_outstanding=42.0,
        current_price=987.6,
    ))
    for v in (
        result.reported_fcf,
        result.sbc_adjusted_fcf,
        result.sbc_as_pct_of_fcf,
        result.reported_shares,
        result.forward_dilution_shares_added,
        result.dilution_adjusted_shares,
    ):
        assert isinstance(v, float)
        assert not math.isnan(v)
        assert not math.isinf(v)
