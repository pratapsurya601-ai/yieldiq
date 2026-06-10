# backend/tests/test_replacement_value_service.py
#
# Covers the T2.3 Phase A replacement-value service. Tests are
# organised by the public surface:
#
#   1. Sector inflation factor — each documented sector returns the
#      expected multiplier; unknown sectors fall back to default.
#   2. compute_replacement_value — representative shapes:
#      TATASTEEL (asset-heavy, Metals), HUL (FMCG, brand-heavy with
#      and without explicit brand cost), Tobin's Q narrative bands,
#      negative-equity distress, no-shares short-circuit.
#   3. is_replacement_value_meaningful — TCS / HDFCBANK excluded,
#      asset-heavy passes, asset-light PP&E ratio flagged.
#   4. to_dict shape — all expected keys, JSON-safe scalars.
#
# Run: pytest backend/tests/test_replacement_value_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.replacement_value_service import (
    ReplacementValueInputs,
    ReplacementValueResult,
    compute_replacement_value,
    get_sector_inflation_factor,
    is_replacement_value_meaningful,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# 1. Sector inflation factor table
# ─────────────────────────────────────────────────────────────────

class TestSectorInflationFactor:
    def test_cement_metals_returns_1_6(self):
        assert get_sector_inflation_factor("Cement") == pytest.approx(1.6)
        assert get_sector_inflation_factor("Metals") == pytest.approx(1.6)
        assert get_sector_inflation_factor("Mining") == pytest.approx(1.6)
        assert get_sector_inflation_factor("Construction Materials") == pytest.approx(1.6)

    def test_auto_returns_1_3(self):
        assert get_sector_inflation_factor("Auto") == pytest.approx(1.3)
        assert get_sector_inflation_factor("Automobile") == pytest.approx(1.3)
        assert get_sector_inflation_factor("Auto Components") == pytest.approx(1.3)

    def test_fmcg_returns_1_4(self):
        assert get_sector_inflation_factor("FMCG") == pytest.approx(1.4)
        assert get_sector_inflation_factor("Consumer Goods") == pytest.approx(1.4)

    def test_pharma_returns_1_5(self):
        assert get_sector_inflation_factor("Pharma") == pytest.approx(1.5)
        assert get_sector_inflation_factor("Pharmaceuticals") == pytest.approx(1.5)
        assert get_sector_inflation_factor("Healthcare") == pytest.approx(1.5)

    def test_it_services_returns_1_2(self):
        assert get_sector_inflation_factor("IT") == pytest.approx(1.2)
        assert get_sector_inflation_factor("IT Services") == pytest.approx(1.2)
        assert get_sector_inflation_factor("Software") == pytest.approx(1.2)
        assert get_sector_inflation_factor("Technology") == pytest.approx(1.2)

    def test_real_estate_returns_1_0(self):
        # The asset IS the value — no inflation multiplier by default.
        assert get_sector_inflation_factor("Real Estate") == pytest.approx(1.0)
        assert get_sector_inflation_factor("Realty") == pytest.approx(1.0)

    def test_hotels_returns_1_5(self):
        assert get_sector_inflation_factor("Hotels") == pytest.approx(1.5)
        assert get_sector_inflation_factor("Hospitality") == pytest.approx(1.5)

    def test_telecom_returns_1_3(self):
        assert get_sector_inflation_factor("Telecom") == pytest.approx(1.3)

    def test_utilities_power_returns_1_5(self):
        assert get_sector_inflation_factor("Utilities") == pytest.approx(1.5)
        assert get_sector_inflation_factor("Power") == pytest.approx(1.5)
        assert get_sector_inflation_factor("Oil & Gas") == pytest.approx(1.5)

    def test_unknown_sector_returns_default_1_4(self):
        assert get_sector_inflation_factor("Unknown") == pytest.approx(1.4)
        assert get_sector_inflation_factor(None) == pytest.approx(1.4)
        assert get_sector_inflation_factor("") == pytest.approx(1.4)

    def test_case_insensitive_and_whitespace_tolerant(self):
        assert get_sector_inflation_factor("  cement  ") == pytest.approx(1.6)
        assert get_sector_inflation_factor("REAL ESTATE") == pytest.approx(1.0)
        assert get_sector_inflation_factor("It Services") == pytest.approx(1.2)


# ─────────────────────────────────────────────────────────────────
# 2. compute_replacement_value — representative shapes
# ─────────────────────────────────────────────────────────────────

class TestComputeReplacementValueAssetHeavy:
    """TATASTEEL-shaped: heavy long-life PP&E, working capital,
    meaningful debt. Replacement value dominates equity."""

    def _tatasteel_inputs(self) -> ReplacementValueInputs:
        return ReplacementValueInputs(
            ppe_gross=80000.0,                # ₹80,000 Cr at historical cost
            working_capital_required=25000.0,
            cash_required_for_ops=2000.0,
            total_debt=35000.0,
            shares_outstanding=1200.0,        # ~120 Cr shares (1,200 Cr units? scale agnostic)
            sector="Metals",
        )

    def test_aggregate_matches_formula(self):
        inputs = self._tatasteel_inputs()
        result = compute_replacement_value(inputs)
        # PP&E_replaced = 80000 × 1.6 = 128000
        # asset_total   = 128000 + 25000 + 2000 = 155000
        # equity_rv     = 155000 − 35000 = 120000
        assert result.components["ppe_replaced"] == pytest.approx(128000.0)
        assert result.components["asset_replacement_total"] == pytest.approx(155000.0)
        assert result.replacement_value_aggregate == pytest.approx(120000.0)

    def test_method_is_replacement_full(self):
        result = compute_replacement_value(self._tatasteel_inputs())
        assert result.method == "replacement_full"

    def test_per_share_computed(self):
        result = compute_replacement_value(self._tatasteel_inputs())
        assert result.replacement_value_per_share == pytest.approx(100.0)  # 120000 / 1200

    def test_sector_factor_overrides_default(self):
        # User passes inflation_factor_ppe=1.4 but sector="Metals"
        # so the engine should use 1.6, not 1.4.
        inputs = self._tatasteel_inputs()
        inputs.inflation_factor_ppe = 1.4
        result = compute_replacement_value(inputs)
        assert result.components["inflation_factor_applied"] == pytest.approx(1.6)


class TestComputeReplacementValueBrandHeavy:
    """HUL-shaped: small PP&E, large book intangibles (acquired
    brands). Without an explicit brand_replacement_cost the result
    understates and the brand-omission warning must fire."""

    def _hul_inputs(self) -> ReplacementValueInputs:
        return ReplacementValueInputs(
            ppe_gross=4000.0,
            intangibles_book=8000.0,
            goodwill=2000.0,
            working_capital_required=3000.0,
            cash_required_for_ops=500.0,
            total_debt=200.0,
            shares_outstanding=235.0,
            sector="FMCG",
        )

    def test_brand_omitted_warning_fires_without_explicit_brand(self):
        result = compute_replacement_value(self._hul_inputs())
        assert "brand_value_omitted_material" in result.sanity_warnings

    def test_intangibles_excluded_from_aggregate_when_brand_not_supplied(self):
        result = compute_replacement_value(self._hul_inputs())
        # PP&E_replaced = 4000 × 1.4 = 5600
        # asset_total   = 5600 + 3000 + 500 = 9100
        # equity_rv     = 9100 − 200 = 8900
        # Intangibles + goodwill (10000) NOT included.
        assert result.components["ppe_replaced"] == pytest.approx(5600.0)
        assert result.replacement_value_aggregate == pytest.approx(8900.0)
        assert result.components["intangibles_book_omitted"] == pytest.approx(8000.0)
        assert result.components["goodwill_book_omitted"] == pytest.approx(2000.0)

    def test_explicit_brand_cost_included_and_warning_does_not_fire(self):
        inputs = self._hul_inputs()
        inputs.brand_replacement_cost = 30000.0
        result = compute_replacement_value(inputs)
        # Now asset_total = 5600 + 3000 + 500 + 30000 = 39100
        # equity_rv      = 39100 − 200 = 38900
        assert result.replacement_value_aggregate == pytest.approx(38900.0)
        assert "brand_value_omitted_material" not in result.sanity_warnings
        assert result.components["brand_replacement_cost"] == pytest.approx(30000.0)

    def test_technology_replacement_cost_included(self):
        inputs = self._hul_inputs()
        inputs.brand_replacement_cost = 30000.0
        inputs.technology_replacement_cost = 1500.0
        result = compute_replacement_value(inputs)
        # asset_total = 5600 + 3000 + 500 + 30000 + 1500 = 40600
        # equity_rv   = 40600 − 200 = 40400
        assert result.replacement_value_aggregate == pytest.approx(40400.0)


# ─────────────────────────────────────────────────────────────────
# 3. Tobin's Q narrative bands
# ─────────────────────────────────────────────────────────────────

class TestTobinsQ:
    """PP&E=100, sector=None (so default 1.4 applies), no debt,
    10 shares. Replacement = 140; per_share = 14."""

    def _baseline(self) -> ReplacementValueInputs:
        return ReplacementValueInputs(
            ppe_gross=100.0,
            shares_outstanding=10.0,
            inflation_factor_ppe=1.4,
            # sector left None so the caller-supplied 1.4 is used
        )

    def test_high_q_fires_warning(self):
        # market_cap=420, replacement=140 → Q = 3.0; threshold is
        # strictly > 3.0 so we bump market cap a touch.
        result = compute_replacement_value(self._baseline(), market_cap_inr_cr=450.0)
        assert result.tobins_q == pytest.approx(450.0 / 140.0, abs=1e-3)
        assert result.tobins_q > 3.0
        assert "high_tobins_q" in result.sanity_warnings

    def test_low_q_fires_warning(self):
        # market_cap=50, replacement=140 → Q ≈ 0.357 < 0.5.
        # Engine rounds to 4 decimals so use abs=1e-3 tolerance.
        result = compute_replacement_value(self._baseline(), market_cap_inr_cr=50.0)
        assert result.tobins_q == pytest.approx(50.0 / 140.0, abs=1e-3)
        assert result.tobins_q < 0.5
        assert "low_tobins_q" in result.sanity_warnings

    def test_q_in_neutral_band_emits_no_warning(self):
        # market_cap=140 → Q = 1.0
        result = compute_replacement_value(self._baseline(), market_cap_inr_cr=140.0)
        assert result.tobins_q == pytest.approx(1.0)
        assert "high_tobins_q" not in result.sanity_warnings
        assert "low_tobins_q" not in result.sanity_warnings

    def test_tobins_q_is_none_when_market_cap_not_supplied(self):
        result = compute_replacement_value(self._baseline())
        assert result.tobins_q is None

    def test_tobins_q_is_none_when_replacement_value_non_positive(self):
        # If equity replacement value is zero / negative we can't
        # form Q meaningfully.
        distressed = ReplacementValueInputs(
            ppe_gross=10.0,
            inflation_factor_ppe=1.4,
            total_debt=1000.0,
            shares_outstanding=1.0,
        )
        result = compute_replacement_value(distressed, market_cap_inr_cr=500.0)
        assert result.tobins_q is None


# ─────────────────────────────────────────────────────────────────
# 4. Distress / degenerate inputs
# ─────────────────────────────────────────────────────────────────

class TestDegenerateInputs:
    def test_negative_replacement_value_fires_warning(self):
        # Debt swamps the replaceable asset base.
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            total_debt=1000.0,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        # asset_total = 140; equity_rv = 140 − 1000 = -860
        assert result.replacement_value_aggregate == pytest.approx(-860.0)
        assert "negative_replacement_value" in result.sanity_warnings
        assert result.replacement_value_per_share == pytest.approx(-86.0)

    def test_zero_shares_outstanding_yields_none_per_share(self):
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=0.0,
        )
        result = compute_replacement_value(inputs)
        assert result.replacement_value_per_share is None
        assert "no_shares_outstanding" in result.sanity_warnings

    def test_null_inputs_returns_unavailable(self):
        result = compute_replacement_value(None)  # type: ignore[arg-type]
        assert result.method == "unavailable"
        assert result.replacement_value_aggregate is None
        assert result.replacement_value_per_share is None
        assert "null_inputs" in result.sanity_warnings

    def test_no_assets_at_all_yields_unavailable(self):
        inputs = ReplacementValueInputs(
            ppe_gross=0.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        assert result.method == "unavailable"
        assert result.replacement_value_aggregate is None

    def test_partial_method_when_ppe_only(self):
        # PP&E present, no working capital / cash for ops.
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        assert result.method == "replacement_partial"
        assert result.replacement_value_aggregate == pytest.approx(140.0)

    def test_negative_input_clamped_to_zero(self):
        # Defensive: a negative ppe_gross should not contribute a
        # negative number to the asset sum.
        inputs = ReplacementValueInputs(
            ppe_gross=-100.0,
            working_capital_required=50.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        assert result.components["ppe_replaced"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────
# 5. is_replacement_value_meaningful
# ─────────────────────────────────────────────────────────────────

class TestIsReplacementValueMeaningful:
    def test_tcs_it_services_not_meaningful(self):
        ok, reason = is_replacement_value_meaningful(
            "TCS", sector="IT Services", ppe_ratio=0.05
        )
        assert ok is False
        assert "headcount" in reason.lower() or "asset-light" in reason.lower()

    def test_hdfcbank_not_meaningful(self):
        ok, reason = is_replacement_value_meaningful(
            "HDFCBANK", sector="Banks", ppe_ratio=None
        )
        assert ok is False
        assert "capital" in reason.lower()

    def test_nbfc_not_meaningful(self):
        ok, _ = is_replacement_value_meaningful(
            "BAJFINANCE", sector="NBFC", ppe_ratio=None
        )
        assert ok is False

    def test_insurance_not_meaningful(self):
        ok, _ = is_replacement_value_meaningful(
            "SBILIFE", sector="Life Insurance", ppe_ratio=None
        )
        assert ok is False

    def test_holdco_not_meaningful(self):
        ok, reason = is_replacement_value_meaningful(
            "BAJAJHLDNG", sector="Holdco", ppe_ratio=None
        )
        assert ok is False
        assert "sotp" in reason.lower()

    def test_tatasteel_metals_meaningful(self):
        ok, reason = is_replacement_value_meaningful(
            "TATASTEEL", sector="Metals", ppe_ratio=0.55
        )
        assert ok is True
        assert "tobin" in reason.lower() or "asset" in reason.lower()

    def test_ultracemco_cement_meaningful(self):
        ok, _ = is_replacement_value_meaningful(
            "ULTRACEMCO", sector="Cement", ppe_ratio=0.45
        )
        assert ok is True

    def test_real_estate_meaningful(self):
        ok, _ = is_replacement_value_meaningful(
            "DLF", sector="Real Estate", ppe_ratio=0.40
        )
        assert ok is True

    def test_low_ppe_ratio_flags_not_meaningful(self):
        # Even if sector is "Other", a PP&E ratio under 10% means
        # asset coverage isn't the right framework.
        ok, reason = is_replacement_value_meaningful(
            "SOMECO", sector="Diversified", ppe_ratio=0.05
        )
        assert ok is False
        assert "asset-light" in reason.lower() or "5.0%" in reason

    def test_ppe_ratio_bad_value_does_not_raise(self):
        # Defensive: a non-numeric ppe_ratio shouldn't crash.
        ok, _ = is_replacement_value_meaningful(
            "TEST", sector="Metals", ppe_ratio="not-a-number"  # type: ignore[arg-type]
        )
        assert ok is True


# ─────────────────────────────────────────────────────────────────
# 6. to_dict JSON projection
# ─────────────────────────────────────────────────────────────────

class TestToDict:
    def test_keys_present(self):
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            working_capital_required=10.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs, market_cap_inr_cr=200.0)
        payload = to_dict(result)
        assert set(payload.keys()) == {
            "replacement_value_aggregate",
            "replacement_value_per_share",
            "components",
            "method",
            "tobins_q",
            "sanity_warnings",
        }

    def test_none_result_yields_safe_defaults(self):
        payload = to_dict(None)  # type: ignore[arg-type]
        assert payload["replacement_value_aggregate"] is None
        assert payload["replacement_value_per_share"] is None
        assert payload["components"] == {}
        assert payload["method"] == "unavailable"
        assert payload["tobins_q"] is None
        assert payload["sanity_warnings"] == ["null_result"]

    def test_components_is_a_fresh_dict_copy(self):
        # Mutating the to_dict payload must not mutate the
        # underlying result — defensive copy.
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        payload = to_dict(result)
        payload["components"]["new_key"] = "mutated"
        assert "new_key" not in result.components

    def test_sanity_warnings_is_a_fresh_list_copy(self):
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=0.0,  # triggers no_shares_outstanding
        )
        result = compute_replacement_value(inputs)
        payload = to_dict(result)
        payload["sanity_warnings"].append("injected")
        assert "injected" not in result.sanity_warnings


# ─────────────────────────────────────────────────────────────────
# 7. Result dataclass round-trip
# ─────────────────────────────────────────────────────────────────

class TestResultDataclass:
    def test_result_is_result_type(self):
        inputs = ReplacementValueInputs(
            ppe_gross=100.0,
            inflation_factor_ppe=1.4,
            shares_outstanding=10.0,
        )
        result = compute_replacement_value(inputs)
        assert isinstance(result, ReplacementValueResult)
        assert isinstance(result.components, dict)
        assert isinstance(result.sanity_warnings, list)
