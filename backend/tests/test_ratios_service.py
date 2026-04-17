# backend/tests/test_ratios_service.py
from __future__ import annotations

import pytest

from backend.services.ratios_service import (
    compute_asset_turnover,
    compute_current_ratio,
    compute_debt_to_ebitda,
    compute_ev_ebitda,
    compute_interest_coverage,
    compute_revenue_cagr,
    compute_roce,
)


# ── ROCE ─────────────────────────────────────────────────────


def test_roce_basic_percent_output():
    # EBIT 10k, TA 100k, CL 20k -> cap employed 80k -> 10000/80000 = 0.125 = 12.5%
    assert compute_roce(10_000, 100_000, 20_000) == 12.5


def test_roce_zero_capital_employed_returns_none():
    assert compute_roce(1000, 500, 500) is None


def test_roce_bank_like_negative_cap_employed_none():
    # Banks have CL > TA in simple BS form — bail
    assert compute_roce(500, 100, 200) is None


def test_roce_handles_none_inputs():
    assert compute_roce(None, 100, 20) is None
    assert compute_roce(10, None, 20) is None


# ── EV / EBITDA ──────────────────────────────────────────────


def test_ev_ebitda_basic():
    # EV = 1000 + 200 - 100 = 1100; EV/EBITDA = 1100/100 = 11.0
    assert compute_ev_ebitda(1000, 200, 100, 100) == 11.0


def test_ev_ebitda_negative_ebitda_returns_none():
    assert compute_ev_ebitda(1000, 0, 0, -50) is None


def test_ev_ebitda_zero_debt_zero_cash_defaults():
    # Even with debt/cash None, computes from mcap
    assert compute_ev_ebitda(500, None, None, 50) == 10.0


# ── Debt / EBITDA ────────────────────────────────────────────


def test_debt_to_ebitda_basic():
    assert compute_debt_to_ebitda(400, 100) == 4.0


def test_debt_to_ebitda_ebitda_zero_returns_none():
    assert compute_debt_to_ebitda(400, 0) is None


# ── Interest coverage ────────────────────────────────────────


def test_interest_coverage_basic():
    assert compute_interest_coverage(2800, 100) == 28.0


def test_interest_coverage_zero_interest_returns_none():
    # No interest to cover -> undefined ratio (infinity); return None
    assert compute_interest_coverage(500, 0) is None


# ── Current ratio ────────────────────────────────────────────


def test_current_ratio_basic():
    assert compute_current_ratio(2100, 1000) == 2.1


def test_current_ratio_negative_cl_none():
    assert compute_current_ratio(1000, -5) is None


# ── Asset turnover ───────────────────────────────────────────


def test_asset_turnover_basic():
    assert compute_asset_turnover(850, 1000) == 0.85


def test_asset_turnover_zero_assets_none():
    assert compute_asset_turnover(500, 0) is None


# ── Revenue CAGR ─────────────────────────────────────────────


def test_revenue_cagr_3y_basic():
    # 4 values: start=100, end=133.1. CAGR over 3 years = 10%.
    cagr = compute_revenue_cagr([100, 110, 121, 133.1], 3)
    assert cagr == pytest.approx(0.1, abs=1e-3)


def test_revenue_cagr_insufficient_data_none():
    # 3 values can only support 2-year CAGR, not 3
    assert compute_revenue_cagr([100, 110, 121], 3) is None


def test_revenue_cagr_zero_start_none():
    assert compute_revenue_cagr([0, 100, 110, 121], 3) is None


def test_revenue_cagr_5y_basic():
    # 100 -> 161.05 over 5 years ~= 10% CAGR
    series = [100, 110, 121, 133.1, 146.41, 161.05]
    cagr = compute_revenue_cagr(series, 5)
    assert cagr == pytest.approx(0.1, abs=1e-3)


def test_revenue_cagr_handles_nones_in_series():
    cagr = compute_revenue_cagr([100, None, 121, 133.1], 3)
    # None values filtered; series becomes [100, 121, 133.1], len=3, insufficient for 3y
    assert cagr is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
