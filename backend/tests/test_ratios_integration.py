# backend/tests/test_ratios_integration.py
# Mirrors the exact ratios-block code path in analysis_service.py::_get_full_analysis_inner
# to prove the new Phase 2.1 fields populate correctly when enriched data has the
# expected shape. Runs without a live DB or yfinance connection.
from __future__ import annotations

import pandas as pd
import pytest

from backend.services.ratios_service import (
    compute_asset_turnover as _at,
    compute_current_ratio as _cr,
    compute_revenue_cagr as _rcagr,
)


def _compute_new_ratios_block(enriched: dict, total_assets: float) -> dict:
    """
    Verbatim replica of the Phase 2.1 block in
    backend/services/analysis_service.py lines 1845-1872. Any drift
    here means this test no longer guards the real code path.
    """
    current_ratio = _cr(
        enriched.get("current_assets"),
        enriched.get("current_liabilities"),
    )
    asset_turnover = _at(
        enriched.get("latest_revenue") or enriched.get("revenue"),
        total_assets,
    )
    rev_cagr_3y = None
    rev_cagr_5y = None
    try:
        _inc = enriched.get("income_df")
        if _inc is not None and hasattr(_inc, "empty") and not _inc.empty \
                and "revenue" in _inc.columns:
            rev_series = _inc["revenue"].dropna().tolist()
            rev_cagr_3y = _rcagr(rev_series, 3)
            rev_cagr_5y = _rcagr(rev_series, 5)
    except Exception:
        pass
    return {
        "current_ratio": current_ratio,
        "asset_turnover": asset_turnover,
        "revenue_cagr_3y": rev_cagr_3y,
        "revenue_cagr_5y": rev_cagr_5y,
    }


def test_realistic_tcs_like_enriched_populates_all_fields():
    """TCS-like: all fields available, expect non-None outputs."""
    # 6 years of 10% compounding revenue, latest last
    revenue_history = [100_000, 110_000, 121_000, 133_100, 146_410, 161_051]
    enriched = {
        "current_assets": 85_000,
        "current_liabilities": 40_000,
        "latest_revenue": 161_051,
        "income_df": pd.DataFrame({"revenue": revenue_history}),
    }
    total_assets = 200_000

    out = _compute_new_ratios_block(enriched, total_assets)

    assert out["current_ratio"] == pytest.approx(2.13, abs=1e-2)
    assert out["asset_turnover"] == pytest.approx(0.81, abs=1e-2)
    assert out["revenue_cagr_3y"] == pytest.approx(0.1, abs=1e-3)
    assert out["revenue_cagr_5y"] == pytest.approx(0.1, abs=1e-3)


def test_missing_current_ratio_inputs_degrades_to_none():
    """Bank-like: current_assets / current_liabilities not provided."""
    enriched = {
        "latest_revenue": 500_000,
        "income_df": pd.DataFrame({"revenue": [100, 110, 121, 133.1]}),
    }
    out = _compute_new_ratios_block(enriched, total_assets=1_000_000)

    assert out["current_ratio"] is None
    assert out["asset_turnover"] == pytest.approx(0.5, abs=1e-3)
    assert out["revenue_cagr_3y"] == pytest.approx(0.1, abs=1e-3)
    # Only 4 years, insufficient for 5y CAGR
    assert out["revenue_cagr_5y"] is None


def test_no_income_df_leaves_cagr_none_without_crash():
    """Stocks where we never loaded income history — must not crash."""
    enriched = {
        "current_assets": 100,
        "current_liabilities": 50,
        "latest_revenue": 1000,
        # no income_df key at all
    }
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    assert out["current_ratio"] == 2.0
    assert out["asset_turnover"] == 0.1
    assert out["revenue_cagr_3y"] is None
    assert out["revenue_cagr_5y"] is None


def test_empty_income_df_leaves_cagr_none():
    """DataFrame present but empty — guard clause exercise."""
    enriched = {
        "current_assets": 100,
        "current_liabilities": 50,
        "latest_revenue": 1000,
        "income_df": pd.DataFrame(),
    }
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    assert out["revenue_cagr_3y"] is None
    assert out["revenue_cagr_5y"] is None


def test_zero_total_assets_gives_none_asset_turnover():
    """Edge: total_assets=0 from a fresh IPO / placeholder."""
    enriched = {"latest_revenue": 1000}
    out = _compute_new_ratios_block(enriched, total_assets=0)
    assert out["asset_turnover"] is None


def test_revenue_fallback_when_latest_revenue_missing():
    """`enriched.get('latest_revenue') or enriched.get('revenue')` fallback."""
    enriched = {"revenue": 5_000}
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    assert out["asset_turnover"] == 0.5


def test_negative_current_liabilities_gracefully_none():
    """Malformed balance sheet with CL <= 0 -> None, don't crash."""
    enriched = {
        "current_assets": 1000,
        "current_liabilities": 0,  # will trigger None
    }
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    assert out["current_ratio"] is None


def test_pandas_na_values_handled():
    """NaN revenues get dropped; only numeric values flow to CAGR."""
    import numpy as np
    enriched = {
        "income_df": pd.DataFrame({"revenue": [100, np.nan, 121, 133.1]}),
    }
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    # After dropna: [100, 121, 133.1] -> len=3, insufficient for 3y (needs 4+)
    assert out["revenue_cagr_3y"] is None
    assert out["revenue_cagr_5y"] is None


def test_realistic_nan_heavy_income_still_populates_when_enough_clean():
    """Real data often has leading NaNs; ensure non-NaN tail still produces CAGR."""
    import numpy as np
    enriched = {
        "income_df": pd.DataFrame({
            "revenue": [np.nan, np.nan, 100, 110, 121, 133.1]
        }),
    }
    out = _compute_new_ratios_block(enriched, total_assets=10_000)
    # After dropna -> [100,110,121,133.1], 4 values, supports 3y CAGR
    assert out["revenue_cagr_3y"] == pytest.approx(0.1, abs=1e-3)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
