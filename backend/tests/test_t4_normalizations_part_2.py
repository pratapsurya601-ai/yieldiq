# backend/tests/test_t4_normalizations_part_2.py
"""Unit tests for the T4-batch-part-2 accounting normalizations.

Covers the five helpers added in
``backend/services/financials_service.py`` for the part-2 PR:

    T4.5   _nci_adjustment
    T4.6   _working_capital_normalization
    T4.7   _effective_tax_rate_normalization
    T4.8   _pension_obligations_adjustment
    T4.10  _fx_translation_adjustment

Each test class is one normalization. Material / negligible / boundary
cases, sector routing, and defensive paths (None / NaN / negative)
are exercised so an upstream regression that breaks the helpers'
return-shape contract is caught immediately. A sixth test class
exercises ``_t4_batch_part_2_period_keys`` to lock in the 10-key
return shape that ``_build_year`` dict-spreads.
"""
from __future__ import annotations

from datetime import date

import math

import pytest

from backend.services.financials_service import (
    _Row,
    _effective_tax_rate_normalization,
    _fx_translation_adjustment,
    _nci_adjustment,
    _pension_obligations_adjustment,
    _t4_batch_part_2_period_keys,
    _working_capital_normalization,
)


def _row(**overrides) -> _Row:
    """Build a minimal _Row with sensible defaults; override per test."""
    base = dict(
        period_end=date(2025, 3, 31),
        period_type="annual",
        revenue=10000.0,
        pat=1000.0,
        total_debt=500.0,
        total_equity=5000.0,
        cash_and_equivalents=1000.0,
        operating_expenses=7000.0,
    )
    base.update(overrides)
    return _Row(**base)


# ──────────────────────────────────────────────────────────────────
# T4.5 — NCI / minority interest adjustment
# ──────────────────────────────────────────────────────────────────
class TestNCIAdjustment:
    def test_negligible_small_nci(self) -> None:
        # nci / eq = 100 / 5000 = 2 % → negligible
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=100.0), "RELIANCE"
        )
        # adjusted_ev = debt + equity - nci = 500 + 5000 - 100 = 5400
        assert adj_ev == 5400.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # 350 / 5000 = 7 % → moderate
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=350.0), "RELIANCE"
        )
        assert adj_ev == 5150.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # 750 / 5000 = 15 % → material
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=750.0), "RELIANCE"
        )
        assert adj_ev == 4750.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # 1500 / 5000 = 30 % → heavy
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=1500.0), "RELIANCE"
        )
        assert adj_ev == 4000.0
        assert label == "heavy"

    def test_missing_nci_returns_unavailable(self) -> None:
        adj_ev, label = _nci_adjustment(_row(), "RELIANCE")
        assert adj_ev is None
        assert label == "unavailable"

    def test_negative_nci_treated_as_unavailable(self) -> None:
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=-50.0), "RELIANCE"
        )
        assert adj_ev is None
        assert label == "unavailable"

    def test_missing_equity_returns_unavailable(self) -> None:
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=100.0, total_equity=None), "RELIANCE"
        )
        assert adj_ev is None
        assert label == "unavailable"

    def test_negative_equity_floors_and_marks_unavailable(self) -> None:
        # Negative equity is pathological; helper surfaces a floored
        # number and marks unavailable so the FE suppresses the chip.
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=100.0, total_equity=-2000.0),
            "RELIANCE",
        )
        assert adj_ev == 0.0  # max(0, 500 + (-2000) - 100) = 0
        assert label == "unavailable"

    def test_negative_debt_clamped_to_zero(self) -> None:
        adj_ev, label = _nci_adjustment(
            _row(minority_interest=100.0, total_debt=-50.0),
            "RELIANCE",
        )
        # debt clamps to 0, adj_ev = 0 + 5000 - 100 = 4900
        assert adj_ev == 4900.0
        assert label == "negligible"


# ──────────────────────────────────────────────────────────────────
# T4.6 — Working capital normalization
# ──────────────────────────────────────────────────────────────────
class TestWorkingCapitalNormalization:
    def test_negligible_small_deviation(self) -> None:
        # current_wc = 1000 - 800 = 200; median = 250; deviation = 50
        # 50 / 10000 = 0.5 % → negligible
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1000.0,
                current_liabilities=800.0,
                working_capital_5y_median=250.0,
            ),
            "RELIANCE",
        )
        assert adj == 250.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # current_wc = 500; median = 800; deviation = 300
        # 300 / 10000 = 3 % → moderate.
        # Use a non-cyclical ticker (HDFCBANK) so the cyclical
        # promotion doesn't lift this from moderate → material.
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1500.0,
                current_liabilities=1000.0,
                working_capital_5y_median=800.0,
            ),
            "HDFCBANK",
        )
        assert adj == 800.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # current_wc = 200; median = 900; deviation = 700
        # 700 / 10000 = 7 % → material
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1200.0,
                current_liabilities=1000.0,
                working_capital_5y_median=900.0,
            ),
            "RELIANCE",
        )
        assert adj == 900.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # current_wc = 0; median = 1500; deviation = 1500
        # 1500 / 10000 = 15 % → heavy
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1000.0,
                current_liabilities=1000.0,
                working_capital_5y_median=1500.0,
            ),
            "RELIANCE",
        )
        assert adj == 1500.0
        assert label == "heavy"

    def test_cyclical_ticker_promotes_moderate_to_material(self) -> None:
        # Same deviation as moderate band but for TATASTEEL (cyclical).
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1500.0,
                current_liabilities=1000.0,
                working_capital_5y_median=800.0,
            ),
            "TATASTEEL",
        )
        assert adj == 800.0
        assert label == "material"

    def test_cyclical_does_not_demote_negligible(self) -> None:
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1000.0,
                current_liabilities=800.0,
                working_capital_5y_median=250.0,
            ),
            "TATASTEEL",
        )
        assert label == "negligible"

    def test_missing_median_returns_unavailable(self) -> None:
        adj, label = _working_capital_normalization(
            _row(current_assets=1000.0, current_liabilities=800.0),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_current_assets_returns_unavailable(self) -> None:
        adj, label = _working_capital_normalization(
            _row(current_liabilities=800.0, working_capital_5y_median=200.0),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_revenue_surfaces_median_with_unavailable(self) -> None:
        adj, label = _working_capital_normalization(
            _row(
                current_assets=1000.0,
                current_liabilities=800.0,
                working_capital_5y_median=250.0,
                revenue=None,
            ),
            "RELIANCE",
        )
        assert adj == 250.0
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# T4.7 — Effective tax rate normalization
# ──────────────────────────────────────────────────────────────────
class TestEffectiveTaxRateNormalization:
    def test_negligible_reported_matches_median(self) -> None:
        # PBT = 1300; PAT = 1000; reported_etr = (300/1300)*100 = ~23.08 %
        # median = 25 → clamped = 25; deviation = ~1.92 pp → negligible
        # adjusted_pat = 1300 * (1 - 0.25) = 975
        adj, label = _effective_tax_rate_normalization(
            _row(profit_before_tax=1300.0, effective_tax_rate_5y_median=25.0),
            "RELIANCE",
        )
        assert adj == 975.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # PBT = 1300; PAT = 1200; reported_etr = ~7.69 %
        # median = 18; clamped = 18; deviation = ~10.31 pp → moderate
        adj, label = _effective_tax_rate_normalization(
            _row(
                pat=1200.0,
                profit_before_tax=1300.0,
                effective_tax_rate_5y_median=18.0,
            ),
            "RELIANCE",
        )
        # adjusted_pat = 1300 * (1 - 0.18) = 1066
        assert adj == 1066.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # PBT = 1300; PAT = 1250; reported_etr = ~3.85 %
        # median = 25; clamped = 25; deviation = ~21.15 pp → material
        adj, label = _effective_tax_rate_normalization(
            _row(
                pat=1250.0,
                profit_before_tax=1300.0,
                effective_tax_rate_5y_median=25.0,
            ),
            "RELIANCE",
        )
        assert adj == 975.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # PBT = 1000; PAT = 980; reported_etr = 2 %
        # median = 35; clamped = 35; deviation = 33 pp → heavy
        adj, label = _effective_tax_rate_normalization(
            _row(
                pat=980.0,
                profit_before_tax=1000.0,
                effective_tax_rate_5y_median=35.0,
            ),
            "RELIANCE",
        )
        # adjusted_pat = 1000 * (1 - 0.35) = 650
        assert adj == 650.0
        assert label == "heavy"

    def test_median_above_ceiling_is_clamped(self) -> None:
        # median = 50 % → clamped to 35 % ceiling
        # PBT = 1000, expected adjusted_pat = 1000 * (1 - 0.35) = 650
        adj, label = _effective_tax_rate_normalization(
            _row(
                profit_before_tax=1000.0,
                effective_tax_rate_5y_median=50.0,
            ),
            "RELIANCE",
        )
        assert adj == 650.0

    def test_median_below_floor_is_clamped(self) -> None:
        # median = 2 % → clamped up to 10 % floor
        # PBT = 1000, expected adjusted_pat = 1000 * (1 - 0.10) = 900
        adj, label = _effective_tax_rate_normalization(
            _row(
                profit_before_tax=1000.0,
                effective_tax_rate_5y_median=2.0,
            ),
            "RELIANCE",
        )
        assert adj == 900.0

    def test_missing_pbt_returns_unavailable(self) -> None:
        adj, label = _effective_tax_rate_normalization(
            _row(effective_tax_rate_5y_median=25.0), "RELIANCE"
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_median_returns_unavailable(self) -> None:
        adj, label = _effective_tax_rate_normalization(
            _row(profit_before_tax=1000.0), "RELIANCE"
        )
        assert adj is None
        assert label == "unavailable"

    def test_zero_pbt_returns_unavailable(self) -> None:
        adj, label = _effective_tax_rate_normalization(
            _row(
                profit_before_tax=0.0,
                effective_tax_rate_5y_median=25.0,
            ),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_pat_surfaces_adjusted_pat_with_unavailable(
        self,
    ) -> None:
        adj, label = _effective_tax_rate_normalization(
            _row(
                pat=None,
                profit_before_tax=1000.0,
                effective_tax_rate_5y_median=25.0,
            ),
            "RELIANCE",
        )
        assert adj == 750.0
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# T4.8 — Pension obligations adjustment
# ──────────────────────────────────────────────────────────────────
class TestPensionObligationsAdjustment:
    def test_negligible_small_pension(self) -> None:
        # 50 / 5000 = 1 % → negligible
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=50.0), "RELIANCE"
        )
        assert adj == 550.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # 200 / 5000 = 4 % → moderate
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=200.0), "RELIANCE"
        )
        assert adj == 700.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # 400 / 5000 = 8 % → material
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=400.0), "RELIANCE"
        )
        assert adj == 900.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # 800 / 5000 = 16 % → heavy
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=800.0), "RELIANCE"
        )
        assert adj == 1300.0
        assert label == "heavy"

    def test_psu_defense_promotes_negligible_to_moderate(self) -> None:
        # 50 / 5000 = 1 % → negligible normally; BEL promotes to moderate.
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=50.0), "BEL"
        )
        assert label == "moderate"

    def test_legacy_it_promotes_negligible_to_moderate(self) -> None:
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=50.0), "TCS"
        )
        assert label == "moderate"

    def test_psu_defense_zero_pension_stays_negligible(self) -> None:
        # The promotion only fires on positive unfunded; zero stays
        # at the raw bucket (negligible) regardless of sector.
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=0.0), "BEL"
        )
        assert label == "negligible"

    def test_missing_pension_returns_unavailable(self) -> None:
        adj, label = _pension_obligations_adjustment(
            _row(), "RELIANCE"
        )
        assert adj is None
        assert label == "unavailable"

    def test_negative_pension_treated_as_unavailable(self) -> None:
        adj, label = _pension_obligations_adjustment(
            _row(unfunded_pension_obligations=-50.0), "RELIANCE"
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_equity_surfaces_adjusted_debt_with_unavailable(
        self,
    ) -> None:
        adj, label = _pension_obligations_adjustment(
            _row(
                unfunded_pension_obligations=200.0,
                total_equity=None,
            ),
            "RELIANCE",
        )
        assert adj == 700.0
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# T4.10 — FX translation adjustment
# ──────────────────────────────────────────────────────────────────
class TestFXTranslationAdjustment:
    def test_negligible_small_fx_swing(self) -> None:
        # 30 % foreign rev, avg_rate=80, median=80.5 (~0.6 % stronger).
        # domestic = 7000; foreign = 3000;
        # foreign_normalized = 3000 * (80.5/80) = 3018.75
        # adjusted = 10018.75; deviation = 18.75 / 10000 = 0.19 % → negligible
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=30.0,
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=80.5,
            ),
            "RELIANCE",
        )
        assert adj == pytest.approx(10018.75, rel=1e-3)
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # 40 % foreign rev, avg=85, median=80. INR weaker than median →
        # restated foreign rev shrinks.
        # foreign_normalized = 4000 * (80/85) = 3764.71
        # adjusted = 6000 + 3764.71 = 9764.71; deviation = 235.29 / 10000 = 2.35 %
        # → moderate
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=40.0,
                usd_inr_avg_period=85.0,
                usd_inr_3y_median=80.0,
            ),
            "RELIANCE",
        )
        assert adj == pytest.approx(9764.71, rel=1e-3)
        assert label == "moderate"

    def test_material_band(self) -> None:
        # 60 % foreign rev, avg=88, median=80. Big swing.
        # foreign_normalized = 6000 * (80/88) = 5454.55
        # adjusted = 4000 + 5454.55 = 9454.55; deviation = 545.45 / 10000 = 5.45 %
        # → material
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=60.0,
                usd_inr_avg_period=88.0,
                usd_inr_3y_median=80.0,
            ),
            "RELIANCE",
        )
        assert adj == pytest.approx(9454.55, rel=1e-3)
        assert label == "material"

    def test_heavy_band(self) -> None:
        # 90 % foreign rev, avg=88, median=78. Huge swing.
        # foreign_normalized = 9000 * (78/88) = 7977.27
        # adjusted = 1000 + 7977.27 = 8977.27; deviation = 1022.73 / 10000 = 10.23 %
        # → heavy
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=90.0,
                usd_inr_avg_period=88.0,
                usd_inr_3y_median=78.0,
            ),
            "RELIANCE",
        )
        assert adj == pytest.approx(8977.27, rel=1e-3)
        assert label == "heavy"

    def test_it_services_promotes_moderate_to_material(self) -> None:
        # Same numbers as moderate band but for INFY (FX-exposed).
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=40.0,
                usd_inr_avg_period=85.0,
                usd_inr_3y_median=80.0,
            ),
            "INFY",
        )
        assert label == "material"

    def test_pharma_promotes_moderate_to_material(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=40.0,
                usd_inr_avg_period=85.0,
                usd_inr_3y_median=80.0,
            ),
            "SUNPHARMA",
        )
        assert label == "material"

    def test_it_services_does_not_demote_negligible(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=30.0,
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=80.5,
            ),
            "INFY",
        )
        assert label == "negligible"

    def test_missing_foreign_pct_returns_unavailable(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=80.5,
            ),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_avg_rate_returns_unavailable(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=40.0,
                usd_inr_3y_median=80.0,
            ),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_zero_avg_rate_returns_unavailable(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=40.0,
                usd_inr_avg_period=0.0,
                usd_inr_3y_median=80.0,
            ),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_out_of_range_foreign_pct_returns_unavailable(self) -> None:
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=120.0,
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=82.0,
            ),
            "RELIANCE",
        )
        assert adj is None
        assert label == "unavailable"

    def test_zero_foreign_pct_negligible(self) -> None:
        # No foreign rev — adjusted == reported, deviation = 0 → negligible.
        adj, label = _fx_translation_adjustment(
            _row(
                foreign_revenue_pct=0.0,
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=82.0,
            ),
            "RELIANCE",
        )
        assert adj == 10000.0
        assert label == "negligible"


# ──────────────────────────────────────────────────────────────────
# Wiring — _t4_batch_part_2_period_keys aggregator
# ──────────────────────────────────────────────────────────────────
class TestT4BatchPart2PeriodKeys:
    EXPECTED_KEYS = {
        "nci_adjusted_ev",
        "nci_intensity_label",
        "wc_normalized_value",
        "wc_intensity_label",
        "etr_normalized_pat",
        "etr_intensity_label",
        "pension_adjusted_debt",
        "pension_intensity_label",
        "fx_normalized_revenue",
        "fx_intensity_label",
    }

    def test_empty_row_returns_all_unavailable(self) -> None:
        keys = _t4_batch_part_2_period_keys(_row(), "RELIANCE")
        assert set(keys.keys()) == self.EXPECTED_KEYS
        # Adjusted values are None when source columns aren't populated.
        assert keys["nci_adjusted_ev"] is None
        assert keys["wc_normalized_value"] is None
        assert keys["etr_normalized_pat"] is None
        assert keys["pension_adjusted_debt"] is None
        assert keys["fx_normalized_revenue"] is None
        # All labels are unavailable.
        assert keys["nci_intensity_label"] == "unavailable"
        assert keys["wc_intensity_label"] == "unavailable"
        assert keys["etr_intensity_label"] == "unavailable"
        assert keys["pension_intensity_label"] == "unavailable"
        assert keys["fx_intensity_label"] == "unavailable"

    def test_fully_populated_row_emits_real_values(self) -> None:
        row = _row(
            minority_interest=750.0,
            current_assets=1200.0,
            current_liabilities=1000.0,
            working_capital_5y_median=900.0,
            profit_before_tax=1300.0,
            effective_tax_rate_5y_median=25.0,
            unfunded_pension_obligations=400.0,
            foreign_revenue_pct=60.0,
            usd_inr_avg_period=88.0,
            usd_inr_3y_median=80.0,
        )
        keys = _t4_batch_part_2_period_keys(row, "RELIANCE")
        # NCI material
        assert keys["nci_adjusted_ev"] == 4750.0
        assert keys["nci_intensity_label"] == "material"
        # WC material
        assert keys["wc_normalized_value"] == 900.0
        assert keys["wc_intensity_label"] == "material"
        # ETR — PBT=1300 + PAT=1000 (default) => reported_etr = ~23.08 %,
        # median clamped to 25 % => deviation = ~1.92 pp => negligible.
        # adjusted_pat = 1300 * (1 - 0.25) = 975
        assert keys["etr_normalized_pat"] == 975.0
        assert keys["etr_intensity_label"] == "negligible"
        # Pension material
        assert keys["pension_adjusted_debt"] == 900.0
        assert keys["pension_intensity_label"] == "material"
        # FX material
        assert keys["fx_normalized_revenue"] == pytest.approx(9454.55, rel=1e-3)
        assert keys["fx_intensity_label"] == "material"

    def test_none_ticker_does_not_crash(self) -> None:
        keys = _t4_batch_part_2_period_keys(
            _row(
                minority_interest=100.0,
                current_assets=1000.0,
                current_liabilities=800.0,
                working_capital_5y_median=250.0,
                profit_before_tax=1300.0,
                effective_tax_rate_5y_median=25.0,
                unfunded_pension_obligations=50.0,
                foreign_revenue_pct=30.0,
                usd_inr_avg_period=80.0,
                usd_inr_3y_median=80.5,
            ),
            None,
        )
        assert set(keys.keys()) == self.EXPECTED_KEYS
        # Sanity — every label is a string from the documented set.
        valid_labels = {
            "negligible", "moderate", "material", "heavy", "unavailable",
        }
        for k in (
            "nci_intensity_label",
            "wc_intensity_label",
            "etr_intensity_label",
            "pension_intensity_label",
            "fx_intensity_label",
        ):
            assert keys[k] in valid_labels

    def test_empty_string_ticker_does_not_crash(self) -> None:
        keys = _t4_batch_part_2_period_keys(_row(), "")
        assert set(keys.keys()) == self.EXPECTED_KEYS

    def test_nan_inputs_route_to_unavailable(self) -> None:
        keys = _t4_batch_part_2_period_keys(
            _row(
                minority_interest=float("nan"),
                unfunded_pension_obligations=float("nan"),
            ),
            "RELIANCE",
        )
        # _safe_float strips NaN → None, helpers see None → unavailable.
        assert keys["nci_adjusted_ev"] is None
        assert keys["nci_intensity_label"] == "unavailable"
        assert keys["pension_adjusted_debt"] is None
        assert keys["pension_intensity_label"] == "unavailable"
