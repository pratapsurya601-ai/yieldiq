# backend/tests/test_t4_normalizations.py
"""Unit tests for the T4-batch accounting normalizations.

Covers the four helpers added in
``backend/services/financials_service.py``:

    T4.2  _ifrs16_lease_adjustment
    T4.3  _capitalized_rd_adjustment
    T4.4  _excess_cash_adjustment
    T4.9  _litigation_provisions_adjustment

Each test class is one normalization. Material / negligible / boundary
cases, sector routing, and defensive paths (None / NaN / negative)
are exercised so an upstream regression that breaks the helpers'
return-shape contract is caught immediately.
"""
from __future__ import annotations

from datetime import date

import math

import pytest

from backend.services.financials_service import (
    _Row,
    _capitalized_rd_adjustment,
    _excess_cash_adjustment,
    _ifrs16_lease_adjustment,
    _litigation_provisions_adjustment,
    _t4_batch_period_keys,
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
# T4.2 — IFRS-16 lease adjustment
# ──────────────────────────────────────────────────────────────────
class TestIFRS16LeaseAdjustment:
    def test_negligible_small_leases(self) -> None:
        # leases / (debt + leases) = 10 / 510 = ~2 % → negligible
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=10.0), "RELIANCE"
        )
        assert adj_ev == 510.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # 50 / (500 + 50) = ~9.1 % → moderate
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=50.0), "RELIANCE"
        )
        assert adj_ev == 550.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # 100 / (500 + 100) = 16.7 % → material
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=100.0), "RELIANCE"
        )
        assert adj_ev == 600.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # 500 / (500 + 500) = 50 % → heavy
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=500.0), "RELIANCE"
        )
        assert adj_ev == 1000.0
        assert label == "heavy"

    def test_lease_heavy_ticker_promotes_moderate_to_material(self) -> None:
        # Same numbers as test_moderate_band but for DMART (lease-heavy
        # retail) — gets promoted from moderate → material.
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=50.0), "DMART"
        )
        assert adj_ev == 550.0
        assert label == "material"

    def test_lease_heavy_ticker_does_not_demote_negligible(self) -> None:
        # < 5 % stays negligible even for DMART — we only promote
        # moderate → material, not negligible → moderate.
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=10.0), "DMART"
        )
        assert label == "negligible"

    def test_missing_leases_returns_unavailable(self) -> None:
        adj_ev, label = _ifrs16_lease_adjustment(_row(), "RELIANCE")
        assert adj_ev is None
        assert label == "unavailable"

    def test_negative_leases_treated_as_unavailable(self) -> None:
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=-50.0), "RELIANCE"
        )
        assert adj_ev is None
        assert label == "unavailable"

    def test_zero_debt_zero_leases_does_not_divide_by_zero(self) -> None:
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(total_debt=0.0, operating_lease_liabilities=0.0),
            "RELIANCE",
        )
        assert adj_ev == 0.0
        assert label == "negligible"

    def test_negative_debt_clamped_to_zero(self) -> None:
        # Defensive: pathological negative debt → treated as 0.
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(total_debt=-100.0, operating_lease_liabilities=100.0),
            "RELIANCE",
        )
        # debt clamps to 0, so adj_ev = 0 + 100 = 100
        assert adj_ev == 100.0
        # 100 / 100 = 100 % → heavy
        assert label == "heavy"


# ──────────────────────────────────────────────────────────────────
# T4.3 — R&D capitalization
# ──────────────────────────────────────────────────────────────────
class TestCapitalizedRDAdjustment:
    def test_pharma_material(self) -> None:
        # SUNPHARMA: 5y life. rd/rev = 700/10000 = 7 % → material.
        # addback = 700 * (1 - 1/5) = 560
        # adjusted_ni = 1000 + 560 = 1560
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=700.0), "SUNPHARMA"
        )
        assert adj == 1560.0
        assert label == "material"

    def test_pharma_heavy(self) -> None:
        # rd 1200 on 10000 rev = 12 % → heavy
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=1200.0), "DRREDDY"
        )
        # addback = 1200 * 0.8 = 960; adjusted_ni = 1960
        assert adj == 1960.0
        assert label == "heavy"

    def test_it_services_3y_life(self) -> None:
        # INFY: 3y life. rd 300 on 10000 = 3 % → moderate
        # addback = 300 * (1 - 1/3) = 300 * 0.6667 = 200
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=300.0), "INFY"
        )
        assert adj == pytest.approx(1200.0, rel=1e-3)
        assert label == "moderate"

    def test_auto_5y_life(self) -> None:
        # MARUTI: 5y life. rd 250 on 10000 = 2.5 % → moderate
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=250.0), "MARUTI"
        )
        # addback = 250 * 0.8 = 200
        assert adj == 1200.0
        assert label == "moderate"

    def test_non_sector_ticker_biased_down(self) -> None:
        # RELIANCE not in pharma/IT/auto buckets — even at material
        # raw pct (7 %), the label is downbiased to moderate.
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=700.0), "RELIANCE"
        )
        # Adjusted value calc still uses the default 4y life.
        # addback = 700 * (1 - 1/4) = 525; adjusted_ni = 1525
        assert adj == 1525.0
        # raw pct 7 % → would be material; downbiased → moderate
        assert label == "moderate"

    def test_negligible_low_rd(self) -> None:
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=50.0), "SUNPHARMA"
        )
        # addback = 50 * 0.8 = 40; adjusted_ni = 1040
        assert adj == 1040.0
        assert label == "negligible"

    def test_missing_rd_returns_unavailable(self) -> None:
        adj, label = _capitalized_rd_adjustment(_row(), "SUNPHARMA")
        assert adj is None
        assert label == "unavailable"

    def test_missing_net_income_returns_unavailable(self) -> None:
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=500.0, pat=None), "SUNPHARMA"
        )
        assert adj is None
        assert label == "unavailable"

    def test_negative_rd_returns_unavailable(self) -> None:
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=-10.0), "SUNPHARMA"
        )
        assert adj is None
        assert label == "unavailable"

    def test_missing_revenue_surfaces_value_with_unavailable_label(self) -> None:
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=100.0, revenue=None), "SUNPHARMA"
        )
        # adj still computed (1000 + 100*0.8 = 1080) but no intensity.
        assert adj == 1080.0
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# T4.4 — Excess cash adjustment
# ──────────────────────────────────────────────────────────────────
class TestExcessCashAdjustment:
    def test_negligible_no_excess(self) -> None:
        # opex 7000 → operating_need = 1750. cash 1000 < need → excess = 0
        adj_ev, label = _excess_cash_adjustment(_row(), "RELIANCE")
        # adj_ev = debt - 0 = 500
        assert adj_ev == 500.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # opex 1000 → need = 250. cash 600 → excess = 350.
        # 350 / 10000 = 3.5 % → moderate
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=1000.0, cash_and_equivalents=600.0),
            "RELIANCE",
        )
        # adj_ev = 500 - 350 = 150
        assert adj_ev == 150.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # opex 1000 → need 250. cash 1200 → excess 950.
        # 950 / 10000 = 9.5 % → material
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=1000.0, cash_and_equivalents=1200.0),
            "RELIANCE",
        )
        assert adj_ev == -450.0  # debt 500 - excess 950
        assert label == "material"

    def test_heavy_band(self) -> None:
        # excess 2000 on revenue 10000 = 20 % → heavy
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=1000.0, cash_and_equivalents=2250.0),
            "RELIANCE",
        )
        # need = 250; excess = 2000; 20 % → heavy
        assert label == "heavy"

    def test_it_services_promotes_moderate_to_material(self) -> None:
        # TCS — moderate raw becomes material. opex 1000, cash 600 →
        # excess 350 = 3.5 % → moderate raw → material for TCS.
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=1000.0, cash_and_equivalents=600.0),
            "TCS",
        )
        assert label == "material"

    def test_it_services_does_not_promote_negligible(self) -> None:
        # No excess → still negligible even for INFY.
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=7000.0, cash_and_equivalents=1000.0),
            "INFY",
        )
        assert label == "negligible"

    def test_revenue_fallback_when_opex_missing(self) -> None:
        # opex None → uses revenue * 0.7 as proxy opex.
        # need = 3/12 * 10000 * 0.7 = 1750; cash 1000 < need → excess 0
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=None, cash_and_equivalents=1000.0),
            "RELIANCE",
        )
        assert label == "negligible"
        assert adj_ev == 500.0

    def test_no_revenue_no_opex_returns_unavailable(self) -> None:
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=None, revenue=None,
                 cash_and_equivalents=1000.0),
            "RELIANCE",
        )
        assert adj_ev is None
        assert label == "unavailable"

    def test_missing_cash_returns_unavailable(self) -> None:
        adj_ev, label = _excess_cash_adjustment(
            _row(cash_and_equivalents=None), "RELIANCE"
        )
        assert adj_ev is None
        assert label == "unavailable"

    def test_negative_cash_returns_unavailable(self) -> None:
        adj_ev, label = _excess_cash_adjustment(
            _row(cash_and_equivalents=-100.0), "RELIANCE"
        )
        assert adj_ev is None
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# T4.9 — Litigation provisions adjustment
# ──────────────────────────────────────────────────────────────────
class TestLitigationProvisionsAdjustment:
    def test_negligible_small_contingent(self) -> None:
        # 100 / 5000 = 2 % → negligible
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=100.0), "RELIANCE"
        )
        assert adj_debt == 600.0
        assert label == "negligible"

    def test_moderate_band(self) -> None:
        # 500 / 5000 = 10 % → moderate
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=500.0), "RELIANCE"
        )
        assert adj_debt == 1000.0
        assert label == "moderate"

    def test_material_band(self) -> None:
        # 1100 / 5000 = 22 % → material
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=1100.0), "RELIANCE"
        )
        assert adj_debt == 1600.0
        assert label == "material"

    def test_heavy_band(self) -> None:
        # 2000 / 5000 = 40 % → heavy
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=2000.0), "RELIANCE"
        )
        assert adj_debt == 2500.0
        assert label == "heavy"

    def test_pharma_promotes_negligible_when_disclosed(self) -> None:
        # SUNPHARMA: any disclosed contingent > 0 in the "negligible"
        # raw bucket promotes to moderate (litigation-prone sector).
        # 100 / 5000 = 2 % → negligible raw → moderate for SUNPHARMA
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=100.0), "SUNPHARMA"
        )
        assert label == "moderate"

    def test_telecom_agr_promotion(self) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=50.0), "BHARTIARTL"
        )
        # 50 / 5000 = 1 % → negligible raw → moderate
        assert label == "moderate"

    def test_pharma_does_not_promote_when_zero(self) -> None:
        # Zero disclosed contingent — even for SUNPHARMA stays negligible.
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=0.0), "SUNPHARMA"
        )
        assert label == "negligible"

    def test_missing_contingent_returns_unavailable(self) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(), "SUNPHARMA"
        )
        assert adj_debt is None
        assert label == "unavailable"

    def test_negative_contingent_returns_unavailable(self) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=-50.0), "SUNPHARMA"
        )
        assert adj_debt is None
        assert label == "unavailable"

    def test_missing_equity_surfaces_value_with_unavailable_label(self) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=100.0, total_equity=None),
            "RELIANCE",
        )
        # Adjusted-debt arithmetic still resolves (500 + 100 = 600)
        # but intensity bucket cannot be derived → "unavailable".
        assert adj_debt == 600.0
        assert label == "unavailable"

    def test_zero_equity_returns_unavailable_label(self) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=100.0, total_equity=0.0),
            "RELIANCE",
        )
        assert adj_debt == 600.0
        assert label == "unavailable"


# ──────────────────────────────────────────────────────────────────
# Combined wiring — the per-period builder must emit all 8 keys
# ──────────────────────────────────────────────────────────────────
class TestT4BatchPeriodKeys:
    def test_emits_all_eight_keys_even_when_unavailable(self) -> None:
        keys = _t4_batch_period_keys(_row(), "RELIANCE")
        expected = {
            "ifrs16_adjusted_ev", "ifrs16_intensity_label",
            "rd_capitalized_value", "rd_intensity_label",
            "excess_cash_subtracted", "excess_cash_intensity_label",
            "litigation_adjusted_debt", "litigation_intensity_label",
        }
        assert set(keys.keys()) == expected

    def test_intensity_labels_are_strings(self) -> None:
        keys = _t4_batch_period_keys(
            _row(
                operating_lease_liabilities=10.0,
                rd_expense=50.0,
                contingent_liabilities=100.0,
            ),
            "SUNPHARMA",
        )
        for k in (
            "ifrs16_intensity_label",
            "rd_intensity_label",
            "excess_cash_intensity_label",
            "litigation_intensity_label",
        ):
            assert isinstance(keys[k], str)
            assert keys[k] in {
                "negligible", "moderate", "material", "heavy", "unavailable",
            }

    def test_unavailable_when_all_source_columns_missing(self) -> None:
        # Default _row() leaves all four source columns None except
        # cash + opex (excess-cash can still report negligible).
        keys = _t4_batch_period_keys(_row(), "RELIANCE")
        assert keys["ifrs16_adjusted_ev"] is None
        assert keys["ifrs16_intensity_label"] == "unavailable"
        assert keys["rd_capitalized_value"] is None
        assert keys["rd_intensity_label"] == "unavailable"
        # excess cash can still compute (cash + opex available)
        assert keys["excess_cash_intensity_label"] == "negligible"
        assert keys["litigation_adjusted_debt"] is None
        assert keys["litigation_intensity_label"] == "unavailable"

    def test_does_not_raise_on_pathological_row(self) -> None:
        # Every numeric field zero or negative — must not raise.
        weird = _Row(
            period_end=date(2025, 3, 31),
            period_type="annual",
            revenue=0.0,
            pat=0.0,
            total_debt=0.0,
            total_equity=0.0,
            cash_and_equivalents=0.0,
            operating_expenses=0.0,
            operating_lease_liabilities=0.0,
            rd_expense=0.0,
            contingent_liabilities=0.0,
        )
        keys = _t4_batch_period_keys(weird, "RELIANCE")
        # All four labels populated, all values finite or None.
        for k in (
            "ifrs16_intensity_label",
            "rd_intensity_label",
            "excess_cash_intensity_label",
            "litigation_intensity_label",
        ):
            assert keys[k] is not None
        for k in (
            "ifrs16_adjusted_ev",
            "rd_capitalized_value",
            "excess_cash_subtracted",
            "litigation_adjusted_debt",
        ):
            v = keys[k]
            assert v is None or (isinstance(v, float) and not math.isnan(v))


# ──────────────────────────────────────────────────────────────────
# Empty / unknown ticker — none of the helpers should crash
# ──────────────────────────────────────────────────────────────────
class TestEmptyOrUnknownTicker:
    @pytest.mark.parametrize("t", [None, "", "UNKNOWN_TICKER_XYZ"])
    def test_ifrs16_unknown_ticker(self, t) -> None:
        adj_ev, label = _ifrs16_lease_adjustment(
            _row(operating_lease_liabilities=50.0), t
        )
        assert adj_ev == 550.0
        # No sector promotion → raw moderate stays moderate.
        assert label == "moderate"

    @pytest.mark.parametrize("t", [None, "", "UNKNOWN_TICKER_XYZ"])
    def test_rd_unknown_ticker_uses_default_life(self, t) -> None:
        # rd 250 on 10000 rev = 2.5 % → moderate raw → downbiased to
        # negligible because default bucket.
        adj, label = _capitalized_rd_adjustment(
            _row(rd_expense=250.0), t
        )
        # addback = 250 * (1 - 1/4) = 187.5; adjusted_ni = 1187.5
        assert adj == 1187.5
        assert label == "negligible"

    @pytest.mark.parametrize("t", [None, "", "UNKNOWN_TICKER_XYZ"])
    def test_excess_cash_unknown_ticker(self, t) -> None:
        adj_ev, label = _excess_cash_adjustment(
            _row(operating_expenses=1000.0, cash_and_equivalents=600.0),
            t,
        )
        # excess 350, 3.5 % → moderate; no IT promotion.
        assert label == "moderate"

    @pytest.mark.parametrize("t", [None, "", "UNKNOWN_TICKER_XYZ"])
    def test_litigation_unknown_ticker(self, t) -> None:
        adj_debt, label = _litigation_provisions_adjustment(
            _row(contingent_liabilities=100.0), t
        )
        # 2 % → negligible; no promotion.
        assert label == "negligible"
