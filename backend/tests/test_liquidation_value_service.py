# backend/tests/test_liquidation_value_service.py
#
# Covers the T2.8 Phase A liquidation-value service. Tests are
# organised by the public surface:
#
#   1. Sector PP&E recovery — each documented sector returns
#      the expected rate; unknown sectors fall back to default.
#   2. compute_liquidation_value — happy path on representative
#      tickers (TATASTEEL asset-heavy, HUL asset-light), inventory
#      sub-breakdown vs blended, distress / negative cases, no-
#      shares-outstanding short-circuit, floor_safety_margin.
#   3. is_liquidation_meaningful — banks excluded, IT services
#      flagged, asset-light low-PP&E flagged, asset-heavy passes.
#   4. to_dict shape — all expected keys, JSON-safe scalars.
#
# Run: pytest backend/tests/test_liquidation_value_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.liquidation_value_service import (
    LiquidationInputs,
    LiquidationRecoveryRates,
    LiquidationResult,
    compute_liquidation_value,
    get_sector_ppe_recovery,
    is_liquidation_meaningful,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# 1. Sector PP&E recovery table
# ─────────────────────────────────────────────────────────────────

class TestSectorPpeRecovery:
    def test_auto_capital_goods_returns_0_45(self):
        assert get_sector_ppe_recovery("Auto") == pytest.approx(0.45)
        assert get_sector_ppe_recovery("Capital Goods") == pytest.approx(0.45)
        assert get_sector_ppe_recovery("Engineering") == pytest.approx(0.45)

    def test_fmcg_pharma_returns_0_30(self):
        assert get_sector_ppe_recovery("FMCG") == pytest.approx(0.30)
        assert get_sector_ppe_recovery("Pharma") == pytest.approx(0.30)
        assert get_sector_ppe_recovery("Consumer Goods") == pytest.approx(0.30)

    def test_real_estate_returns_0_70(self):
        assert get_sector_ppe_recovery("Real Estate") == pytest.approx(0.70)
        assert get_sector_ppe_recovery("Realty") == pytest.approx(0.70)

    def test_hotels_returns_0_50(self):
        assert get_sector_ppe_recovery("Hotels") == pytest.approx(0.50)
        assert get_sector_ppe_recovery("Hospitality") == pytest.approx(0.50)

    def test_metals_cement_returns_0_55(self):
        assert get_sector_ppe_recovery("Metals") == pytest.approx(0.55)
        assert get_sector_ppe_recovery("Cement") == pytest.approx(0.55)
        assert get_sector_ppe_recovery("Mining") == pytest.approx(0.55)

    def test_it_services_returns_0_20(self):
        assert get_sector_ppe_recovery("IT") == pytest.approx(0.20)
        assert get_sector_ppe_recovery("IT Services") == pytest.approx(0.20)
        assert get_sector_ppe_recovery("Software") == pytest.approx(0.20)

    def test_unknown_sector_returns_default_0_40(self):
        assert get_sector_ppe_recovery("Unknown") == pytest.approx(0.40)
        assert get_sector_ppe_recovery(None) == pytest.approx(0.40)
        assert get_sector_ppe_recovery("") == pytest.approx(0.40)

    def test_case_insensitive_and_whitespace_tolerant(self):
        assert get_sector_ppe_recovery("  fmcg  ") == pytest.approx(0.30)
        assert get_sector_ppe_recovery("REAL ESTATE") == pytest.approx(0.70)

    def test_substring_fallback(self):
        # "Auto Components" should land on auto rate even though it's
        # not the exact key — substring match keeps it in the right
        # bucket.
        assert get_sector_ppe_recovery("Auto Components") == pytest.approx(0.45)


# ─────────────────────────────────────────────────────────────────
# 2. compute_liquidation_value happy path + edge cases
# ─────────────────────────────────────────────────────────────────

class TestTataSteelShapedAssetHeavy:
    """TATASTEEL-shaped metals balance sheet (figures in Rs Cr).

    Cash      8,000   * 1.00  = 8,000
    Recv     15,000   * 0.80  = 12,000
    Inv      25,000   * 0.50  = 12,500
    PP&E     80,000   * 0.55  = 44,000   (metals)
    LTI      10,000   * 0.80  =  8,000
    Total assets recovered = 84,500

    Liabilities (must be paid):
      Debt     35,000
      AP        8,000
      Other     5,000
    Total liabilities = 48,000

    Aggregate liquidation = 84,500 − 48,000 = 36,500 Cr
    Shares = 1,250 Cr → per share = 29.20
    """

    def _inputs(self) -> LiquidationInputs:
        return LiquidationInputs(
            cash_and_equivalents=8000.0,
            short_term_investments=0.0,
            receivables=15000.0,
            inventory=25000.0,
            ppe_net=80000.0,
            long_term_investments=10000.0,
            short_term_debt=5000.0,
            long_term_debt=30000.0,
            accounts_payable=8000.0,
            other_liabilities=5000.0,
            shares_outstanding=1250.0,
            sector="Metals",
        )

    def test_aggregate_value_matches_hand_math(self):
        result = compute_liquidation_value(self._inputs())
        assert result.method == "liquidation_full"
        assert result.liquidation_value_aggregate == pytest.approx(36500.0, abs=1.0)

    def test_per_share_matches_hand_math(self):
        result = compute_liquidation_value(self._inputs())
        assert result.liquidation_per_share == pytest.approx(29.20, abs=0.05)

    def test_ppe_recovery_rate_is_metals_0_55(self):
        result = compute_liquidation_value(self._inputs())
        assert result.asset_recoveries["_ppe_recovery_rate"] == pytest.approx(0.55)

    def test_total_liabilities_sums_to_48000(self):
        result = compute_liquidation_value(self._inputs())
        assert result.total_liabilities == pytest.approx(48000.0, abs=1.0)

    def test_no_distress_warning(self):
        result = compute_liquidation_value(self._inputs())
        assert "negative_liquidation_value" not in result.sanity_warnings
        assert "negative_per_share" not in result.sanity_warnings


class TestHulShapedAssetLight:
    """HUL-shaped FMCG balance sheet — brand value dominates.

    Goodwill + intangibles >> PP&E, so the
    "intangibles_dominate_assets" warning must fire.
    """

    def _inputs(self) -> LiquidationInputs:
        return LiquidationInputs(
            cash_and_equivalents=5000.0,
            short_term_investments=2000.0,
            receivables=3000.0,
            inventory=4000.0,
            ppe_net=8000.0,
            intangibles=15000.0,
            goodwill=25000.0,
            short_term_debt=500.0,
            long_term_debt=1500.0,
            accounts_payable=4000.0,
            other_liabilities=2000.0,
            shares_outstanding=235.0,
            sector="FMCG",
        )

    def test_intangibles_dominance_warning_fired(self):
        result = compute_liquidation_value(self._inputs())
        assert "intangibles_dominate_assets" in result.sanity_warnings

    def test_intangibles_and_goodwill_contribute_zero(self):
        result = compute_liquidation_value(self._inputs())
        assert result.asset_recoveries["intangibles"] == pytest.approx(0.0)
        assert result.asset_recoveries["goodwill"] == pytest.approx(0.0)

    def test_fmcg_uses_lower_ppe_recovery(self):
        result = compute_liquidation_value(self._inputs())
        assert result.asset_recoveries["_ppe_recovery_rate"] == pytest.approx(0.30)


class TestInventorySubBreakdown:
    """When raw/WIP/finished sub-breakdown is provided, individual
    rates must apply instead of the blended 0.50."""

    def test_uses_individual_rates_when_sub_breakdown_provided(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=1000.0,
            inventory_raw_materials=400.0,   # × 0.60 = 240
            inventory_wip=300.0,             # × 0.30 = 90
            inventory_finished=300.0,        # × 0.50 = 150
            ppe_net=0.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs)
        assert result.asset_recoveries["inventory"] == pytest.approx(
            240.0 + 90.0 + 150.0, abs=0.5,
        )
        assert result.asset_recoveries["_inventory_mode"] == "sub_breakdown"

    def test_falls_back_to_blended_when_sub_breakdown_absent(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=1000.0,
            ppe_net=0.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs)
        assert result.asset_recoveries["inventory"] == pytest.approx(500.0, abs=0.5)
        assert result.asset_recoveries["_inventory_mode"] == "blended"


class TestDistressNegativeLiquidation:
    """Liabilities exceed even full-recovery assets — distress."""

    def test_negative_aggregate_triggers_distress_warning(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=500.0,
            short_term_investments=0.0,
            receivables=200.0,
            inventory=300.0,
            ppe_net=1000.0,
            short_term_debt=2000.0,
            long_term_debt=5000.0,    # debt swamps assets
            accounts_payable=1000.0,
            other_liabilities=500.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs)
        assert result.liquidation_value_aggregate is not None
        assert result.liquidation_value_aggregate < 0.0
        assert "negative_liquidation_value" in result.sanity_warnings

    def test_negative_per_share_implied_by_negative_aggregate(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=100.0,
            short_term_investments=0.0,
            receivables=100.0,
            inventory=100.0,
            ppe_net=100.0,
            short_term_debt=10000.0,
            long_term_debt=0.0,
            accounts_payable=0.0,
            other_liabilities=0.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs)
        assert result.liquidation_per_share is not None
        assert result.liquidation_per_share < 0.0


class TestFloorSafetyMargin:
    """floor_safety_margin = current_price − liquidation_per_share.

    Positive means market price sits above the asset floor (safety
    margin to the floor). Negative means the market is pricing
    equity below asset coverage (deep-value).
    """

    def test_safety_margin_positive_when_price_above_floor(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=10000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
            short_term_debt=0.0,
            long_term_debt=0.0,
            accounts_payable=0.0,
            other_liabilities=0.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        # liquidation_per_share = 10000 / 100 = 100
        result = compute_liquidation_value(inputs, current_price=200.0)
        assert result.liquidation_per_share == pytest.approx(100.0, abs=0.1)
        assert result.floor_safety_margin == pytest.approx(100.0, abs=0.1)

    def test_safety_margin_negative_when_price_below_floor(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=10000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
            short_term_debt=0.0,
            long_term_debt=0.0,
            accounts_payable=0.0,
            other_liabilities=0.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs, current_price=50.0)
        assert result.floor_safety_margin == pytest.approx(-50.0, abs=0.1)

    def test_safety_margin_none_when_price_not_provided(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs, current_price=None)
        assert result.floor_safety_margin is None


class TestNoSharesOutstanding:
    """shares_outstanding=0 → per_share is None, aggregate still valid."""

    def test_zero_shares_returns_none_per_share(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=500.0,
            inventory=500.0,
            ppe_net=1000.0,
            shares_outstanding=0.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs)
        assert result.liquidation_per_share is None
        assert result.liquidation_value_aggregate is not None
        assert "no_shares_outstanding" in result.sanity_warnings

    def test_zero_shares_safety_margin_is_none(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
            shares_outstanding=0.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs, current_price=100.0)
        assert result.floor_safety_margin is None


class TestPpeNetPreferredOverGross:
    """ppe_net should be used when present; ppe_gross is the fallback."""

    def test_net_preferred(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=0.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_gross=20000.0,
            ppe_net=10000.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs)
        # default ppe recovery 0.40 × 10000 = 4000
        assert result.asset_recoveries["ppe"] == pytest.approx(4000.0, abs=1.0)

    def test_falls_back_to_gross_when_net_missing(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=0.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_gross=20000.0,
            ppe_net=0.0,
            shares_outstanding=100.0,
            sector=None,
        )
        result = compute_liquidation_value(inputs)
        assert result.asset_recoveries["ppe"] == pytest.approx(8000.0, abs=1.0)


class TestDefensiveEdgeCases:
    def test_null_inputs_returns_unavailable(self):
        result = compute_liquidation_value(None)  # type: ignore[arg-type]
        assert result.method == "unavailable"
        assert "null_inputs" in result.sanity_warnings

    def test_all_zero_returns_unavailable(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=0.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
        )
        result = compute_liquidation_value(inputs)
        assert result.method == "unavailable"

    def test_partial_inputs_method_classification(self):
        # Cash only — no inventory, no PP&E, no receivables.
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=0.0,
            shares_outstanding=100.0,
        )
        result = compute_liquidation_value(inputs)
        assert result.method == "liquidation_partial_inputs"

    def test_negative_field_clamped_to_zero(self):
        # Bad-data input — a negative cash value should not produce a
        # negative recovery contribution.
        inputs = LiquidationInputs(
            cash_and_equivalents=-500.0,
            short_term_investments=0.0,
            receivables=0.0,
            inventory=0.0,
            ppe_net=1000.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs)
        assert result.asset_recoveries["cash_and_equivalents"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────
# 3. is_liquidation_meaningful
# ─────────────────────────────────────────────────────────────────

class TestIsLiquidationMeaningful:
    def test_banks_return_false_with_reason(self):
        ok, reason = is_liquidation_meaningful("HDFCBANK", "Banking", None)
        assert ok is False
        assert "capital-adequacy" in reason.lower() or "capital adequacy" in reason.lower()

    def test_nbfc_returns_false(self):
        ok, _ = is_liquidation_meaningful("BAJFINANCE", "NBFC", None)
        assert ok is False

    def test_insurance_returns_false(self):
        ok, _ = is_liquidation_meaningful("HDFCLIFE", "Insurance", None)
        assert ok is False

    def test_it_services_returns_false_with_reason(self):
        ok, reason = is_liquidation_meaningful("TCS", "IT Services", None)
        assert ok is False
        assert "PP&E" in reason or "asset-light" in reason.lower() or "franchise" in reason.lower()

    def test_low_ppe_ratio_returns_false(self):
        # 5% PP&E — asset-light by ratio even without sector context.
        ok, reason = is_liquidation_meaningful("ANY", "Some Sector", 0.05)
        assert ok is False
        assert "PP&E" in reason or "asset-light" in reason.lower()

    def test_asset_heavy_metals_returns_true(self):
        ok, reason = is_liquidation_meaningful("TATASTEEL", "Metals", 0.45)
        assert ok is True
        assert "asset-heavy" in reason.lower() or "informative" in reason.lower()

    def test_asset_heavy_real_estate_returns_true(self):
        ok, _ = is_liquidation_meaningful("DLF", "Real Estate", 0.65)
        assert ok is True

    def test_unknown_sector_with_no_ratio_returns_true(self):
        ok, _ = is_liquidation_meaningful("XYZ", None, None)
        assert ok is True

    def test_invalid_ppe_ratio_does_not_crash(self):
        # Non-numeric ratio falls through without raising.
        ok, _ = is_liquidation_meaningful("XYZ", "Metals", "not a number")  # type: ignore[arg-type]
        assert ok is True


# ─────────────────────────────────────────────────────────────────
# 4. to_dict projection shape
# ─────────────────────────────────────────────────────────────────

class TestToDictShape:
    def test_to_dict_returns_expected_keys(self):
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=500.0,
            inventory=500.0,
            ppe_net=1000.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs, current_price=50.0)
        out = to_dict(result)
        for key in (
            "liquidation_value_aggregate",
            "liquidation_per_share",
            "asset_recoveries",
            "total_liabilities",
            "method",
            "sanity_warnings",
            "floor_safety_margin",
        ):
            assert key in out, f"missing key {key!r} in to_dict output"

    def test_to_dict_is_json_safe(self):
        import json
        inputs = LiquidationInputs(
            cash_and_equivalents=1000.0,
            short_term_investments=0.0,
            receivables=500.0,
            inventory=500.0,
            ppe_net=1000.0,
            shares_outstanding=100.0,
            sector="Metals",
        )
        result = compute_liquidation_value(inputs, current_price=50.0)
        out = to_dict(result)
        # Must serialise without raising — asserts no datetime / set /
        # other non-JSON types leaked through.
        encoded = json.dumps(out)
        assert "liquidation_value_aggregate" in encoded

    def test_to_dict_handles_none_result(self):
        out = to_dict(None)  # type: ignore[arg-type]
        assert out["method"] == "unavailable"
        assert out["liquidation_value_aggregate"] is None
        assert out["liquidation_per_share"] is None
        assert "null_result" in out["sanity_warnings"]


# ─────────────────────────────────────────────────────────────────
# 5. Recovery-rate defaults — sanity-check the dataclass
# ─────────────────────────────────────────────────────────────────

class TestRecoveryRatesDefaults:
    def test_default_recovery_rates_match_graham_framework(self):
        rates = LiquidationRecoveryRates()
        assert rates.cash == pytest.approx(1.00)
        assert rates.receivables == pytest.approx(0.80)
        assert rates.inventory_raw == pytest.approx(0.60)
        assert rates.inventory_wip == pytest.approx(0.30)
        assert rates.inventory_finished == pytest.approx(0.50)
        assert rates.inventory_blended == pytest.approx(0.50)
        assert rates.intangibles == pytest.approx(0.00)
        assert rates.goodwill == pytest.approx(0.00)
        assert rates.long_term_investments == pytest.approx(0.80)
        assert rates.short_term_investments == pytest.approx(0.90)


# ─────────────────────────────────────────────────────────────────
# 6. LiquidationResult dataclass
# ─────────────────────────────────────────────────────────────────

class TestLiquidationResultDataclass:
    def test_result_fields_exposed(self):
        result = LiquidationResult(
            liquidation_value_aggregate=1000.0,
            liquidation_per_share=10.0,
            asset_recoveries={"cash_and_equivalents": 500.0},
            total_liabilities=200.0,
            method="liquidation_full",
            sanity_warnings=[],
            floor_safety_margin=5.0,
        )
        assert result.liquidation_value_aggregate == pytest.approx(1000.0)
        assert result.liquidation_per_share == pytest.approx(10.0)
        assert result.method == "liquidation_full"
