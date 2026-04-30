# backend/tests/test_compounder_dcf.py
# ─────────────────────────────────────────────────────────────────
# Tests for the wide-moat compounder DCF horizon extension.
#
# Covers:
#   1. is_wide_moat_compounder() classifier — allow-list + Wide moat,
#      with bank-like and capex super-cyclical exclusions.
#   2. _projection_horizons() returns (10, 5, -0.005) for compounders
#      and (5, 5, 0.0) for everyone else.
#   3. End-to-end FCFForecaster.predict() — a NESTLEIND-shaped
#      enriched dict produces a higher terminal_fcf_norm than an
#      identically-shaped non-compounder peer because the compounder
#      gets 5 extra explicit-growth years before fade.
#   4. Bank-like (HDFCBANK with Wide moat) is excluded.
#   5. Cyclical (TATASTEEL with Wide moat) is excluded.
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations

import pandas as pd
import pytest

from backend.services.analysis.constants import (
    is_wide_moat_compounder,
    is_capex_super_cyclical,
)
from models.forecaster import _projection_horizons, FCFForecaster


# ── 1. Classifier ────────────────────────────────────────────────
def test_classifier_consumer_compounders_true():
    assert is_wide_moat_compounder("NESTLEIND.NS") is True
    assert is_wide_moat_compounder("ASIANPAINT.NS") is True
    assert is_wide_moat_compounder("HUL.NS") is True
    assert is_wide_moat_compounder("TITAN.NS") is True
    assert is_wide_moat_compounder("PIDILITIND.NS") is True


def test_classifier_it_services_compounders_true():
    # TCS / INFY / HCLTECH / WIPRO via allow-list
    assert is_wide_moat_compounder("TCS.NS") is True
    assert is_wide_moat_compounder("INFY.NS") is True
    # Wide moat alone (without allow-list membership) must also pass
    assert is_wide_moat_compounder(
        "RANDOMIT.NS", sector="IT", moat_grade="Wide"
    ) is True


def test_classifier_cyclical_excluded():
    # TATASTEEL is a capex super-cyclical — even with Wide moat the
    # 15y compounding assumption is wrong, so the compounder gate
    # must return False.
    assert is_capex_super_cyclical("TATASTEEL.NS") is True
    assert is_wide_moat_compounder(
        "TATASTEEL.NS", moat_grade="Wide"
    ) is False
    # Reliance (cyclical conglomerate) likewise excluded
    assert is_wide_moat_compounder(
        "RELIANCE.NS", moat_grade="Wide"
    ) is False


def test_classifier_bank_like_excluded():
    # HDFCBANK is in the documented compounder set BUT bank-like
    # gate fires first — banks route through P/B, not DCF.
    assert is_wide_moat_compounder(
        "HDFCBANK.NS", moat_grade="Wide"
    ) is False
    # Same for BAJFINANCE / SBILIFE
    assert is_wide_moat_compounder("BAJFINANCE.NS") is False
    assert is_wide_moat_compounder("SBILIFE.NS") is False


def test_classifier_unknown_no_moat_false():
    # Random ticker with no moat info defaults to False
    assert is_wide_moat_compounder("UNKNOWNCO.NS") is False
    assert is_wide_moat_compounder(
        "UNKNOWNCO.NS", moat_grade="Moderate"
    ) is False


# ── 2. _projection_horizons ──────────────────────────────────────
def test_horizons_default():
    expl, fade, adj = _projection_horizons("UNKNOWNCO.NS")
    assert (expl, fade, adj) == (5, 5, 0.0)


def test_horizons_compounder():
    expl, fade, adj = _projection_horizons("NESTLEIND.NS")
    assert expl == 10
    assert fade == 5
    assert adj == pytest.approx(-0.005)


def test_horizons_bank_falls_back_to_default():
    expl, fade, adj = _projection_horizons(
        "HDFCBANK.NS", moat_grade="Wide"
    )
    # Bank-like → default horizon (compounder DCF doesn't apply)
    assert (expl, fade, adj) == (5, 5, 0.0)


# ── 3. End-to-end: compounder FV > peer FV with same inputs ──────
def _make_enriched(ticker: str, sector: str = "fmcg") -> dict:
    """Build a NESTLEIND-shaped enriched dict that survives every
    early-out in FCFForecaster.predict() / _compute_fcf_base()."""
    # Synthetic 4-year cash-flow / income history: stable 8% growth.
    years_idx = [2022, 2023, 2024, 2025]
    revenue = [16000e7, 17280e7, 18662e7, 20155e7]   # 8% YoY
    fcf = [3200e7, 3456e7, 3732e7, 4031e7]            # 8% YoY
    cf_df = pd.DataFrame({"year": years_idx, "fcf": fcf})
    income_df = pd.DataFrame({
        "year": years_idx,
        "revenue": revenue,
        "op_margin": [0.22, 0.22, 0.22, 0.22],
    })
    return {
        "ticker": ticker,
        "sector": sector,
        "sector_name": sector,
        "latest_fcf": 4031e7,
        "latest_revenue": 20155e7,
        "op_margin": 0.22,
        "fcf_margin": 0.20,
        "revenue_growth": 0.08,
        "fcf_growth": 0.08,
        "total_debt": 0,
        "total_cash": 1000e7,
        "market_cap": 200000e7,
        "cf_df": cf_df,
        "income_df": income_df,
        "dcf_reliable": True,
    }


def test_compounder_extends_projection_horizon():
    """A NESTLEIND-shaped compounder must produce a 15-element
    projection vector vs the 10-element default; and the year-15
    FCF must be materially higher than the year-10 FCF that a
    non-compounder peer with identical inputs produces."""
    forecaster = FCFForecaster()  # rule-based only (no training)

    # Compounder: NESTLEIND
    out_c = forecaster.predict(_make_enriched("NESTLEIND.NS"))
    assert len(out_c["projections"]) == 15
    assert out_c["reliable"] is True

    # Non-compounder peer with same inputs — random FMCG ticker not
    # in the allow-list and no Wide moat
    out_p = forecaster.predict(_make_enriched("RANDOMFMCG.NS"))
    assert len(out_p["projections"]) == 10

    # Compounder terminal_fcf_norm should be meaningfully higher
    # because of 5 extra explicit-growth years (offset partially by
    # the 50bps terminal-growth haircut — net should still be >5%
    # higher on a stable 8% growth base).
    assert out_c["terminal_fcf_norm"] > out_p["terminal_fcf_norm"] * 1.05


def test_compounder_growth_schedule_holds_explicit_then_fades():
    """In the compounder path, growth must be flat for years 1-10
    (explicit phase) and only start fading from year 11 onwards."""
    forecaster = FCFForecaster()
    out = forecaster.predict(_make_enriched("NESTLEIND.NS"))
    sched = out["growth_schedule"]
    assert len(sched) == 15
    # Years 1-10 must all equal base_growth (flat explicit phase)
    g0 = out["base_growth"]
    for yr_g in sched[:10]:
        assert yr_g == pytest.approx(g0, abs=1e-9)
    # Years 11-15 fade — strictly decreasing toward terminal
    for i in range(10, 14):
        assert sched[i] >= sched[i + 1] - 1e-9
    # Last year must be at or above the (terminal - 50bps) anchor
    # but strictly below the explicit base_growth.
    assert sched[-1] < g0


def test_bank_like_keeps_default_horizon():
    """HDFCBANK with Wide moat must NOT take the compounder path —
    bank-like gate fires first, so the projection length is 10."""
    enriched = _make_enriched("HDFCBANK.NS", sector="Banking")
    enriched["moat_grade"] = "Wide"
    forecaster = FCFForecaster()
    out = forecaster.predict(enriched)
    assert len(out["projections"]) == 10


def test_super_cyclical_keeps_default_horizon():
    """TATASTEEL with a Wide moat must NOT take the compounder path —
    capex super-cyclical gate fires first."""
    enriched = _make_enriched("TATASTEEL.NS", sector="Metals & Mining")
    enriched["moat_grade"] = "Wide"
    forecaster = FCFForecaster()
    out = forecaster.predict(enriched)
    assert len(out["projections"]) == 10
