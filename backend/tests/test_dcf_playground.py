"""Tests for the Reverse-DCF Playground service.

Covers the pure-function layer (``backend.services.analysis.dcf_playground``)
so the test suite stays fast and deterministic without spinning up FastAPI
or a Postgres session. The router-level integration is exercised via the
sample request in the PR description.

Sanity gates:
  1. Base inputs round-trip through the playground without raising.
  2. Higher WACC monotonically reduces FV at fixed other inputs.
  3. The bear/bull band brackets the base FV (bear <= base <= bull).
  4. Reverse-engineer returns a sensible implied WACC for a market
     price below the base FV (implied WACC should be > base WACC).
  5. Tax-rate slider at the BASE_TAX_RATE default is a no-op
     vs the same call without an explicit tax_rate.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def fake_enriched():
    """Realistic enriched-data shape for a profitable Indian large-cap.

    Loosely modelled on HDFCBANK's published numbers so the math
    lands in a plausible fair-value range without requiring DB or
    network. Anchored to:
      - revenue  ~ Rs 2,40,000 cr (= 2.4e12)
      - latest_fcf ~ Rs 60,000 cr (= 6e11)
      - shares ~ 760 cr (= 7.6e9)
      - price ~ Rs 1,650
    """
    return {
        "price": 1650.0,
        "shares": 7.6e9,
        "total_debt": 0.0,
        "total_cash": 1.5e12,
        "latest_fcf": 6.0e11,
        "latest_revenue": 2.4e12,
        "op_margin": 0.25,
        "operating_margin": 0.25,
        "fcf_margin": 0.25,
        "net_margin": 0.20,
        "sector": "Banking",
        "sub_sector": "Private Bank",
    }


def _patch_loader(fake):
    return patch(
        "backend.services.analysis.recompute._load_enriched",
        return_value=fake,
    )


def test_playground_runs_without_error(fake_enriched):
    from backend.services.analysis.dcf_playground import run_playground_dcf

    with _patch_loader(fake_enriched):
        result = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.12,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
            tax_rate=0.25,
        )
    assert "error" not in result, result
    assert float(result["fair_value"]) > 0


def test_higher_wacc_lowers_fv(fake_enriched):
    from backend.services.analysis.dcf_playground import run_playground_dcf

    with _patch_loader(fake_enriched):
        low = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.08,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
        high = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.14,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
    assert float(low["fair_value"]) > float(high["fair_value"])


def test_band_brackets_base(fake_enriched):
    from backend.services.analysis.dcf_playground import run_playground_with_band

    with _patch_loader(fake_enriched):
        band = run_playground_with_band(
            ticker="HDFCBANK.NS",
            wacc=0.11,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
    base = float(band["fair_value"])
    bear = float(band["bear_fv"])
    bull = float(band["bull_fv"])
    assert bear <= base <= bull, (bear, base, bull)
    assert band["inputs_echo"]["wacc"] == 0.11


def test_reverse_engineer_implied_wacc_sensible(fake_enriched):
    """When the market price is below the base FV, the implied WACC
    that justifies the market price must be HIGHER than the base
    WACC (a more pessimistic discount rate explains the discount)."""
    from backend.services.analysis.dcf_playground import (
        run_playground_dcf,
        reverse_engineer_inputs,
    )

    with _patch_loader(fake_enriched):
        base = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.11,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
        base_fv = float(base["fair_value"])
        # Pick a market price clearly below base FV
        market_px = base_fv * 0.70
        rev = reverse_engineer_inputs(
            ticker="HDFCBANK.NS",
            market_price=market_px,
            base_wacc=0.11,
            base_terminal_growth=0.04,
            base_revenue_cagr=0.10,
            base_operating_margin=0.25,
        )
    assert "error" not in rev, rev
    # Implied WACC should be higher than the base WACC (FV is lower
    # at higher WACC, so we need more discounting to reach the
    # below-base market price).
    assert rev["implied_wacc"] > 0.11
    # And bounded by the slider max
    assert rev["implied_wacc"] <= 0.15 + 1e-6


def test_tax_rate_default_is_noop(fake_enriched):
    """tax_rate at BASE_TAX_RATE must not change the FV vs
    omitting it entirely (default)."""
    from backend.services.analysis.dcf_playground import (
        run_playground_dcf,
        BASE_TAX_RATE,
    )

    with _patch_loader(fake_enriched):
        without = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.11,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
        with_default = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.11,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
            tax_rate=BASE_TAX_RATE,
        )
    assert float(without["fair_value"]) == pytest.approx(
        float(with_default["fair_value"]), rel=1e-6
    )


def test_input_clamping(fake_enriched):
    """Out-of-bounds inputs are clamped, not rejected — the
    playground service is permissive so the router's Pydantic
    validation is the single source of truth for shape errors."""
    from backend.services.analysis.dcf_playground import run_playground_dcf

    with _patch_loader(fake_enriched):
        # WACC well above max should clamp to WACC_MAX (0.15)
        result = run_playground_dcf(
            ticker="HDFCBANK.NS",
            wacc=0.99,
            terminal_growth=0.04,
            revenue_cagr_yr1_5=0.10,
            operating_margin=0.25,
        )
    assert "error" not in result
    assert float(result["fair_value"]) > 0
