"""
Tests for the 2026-04-30 capex super-cyclical FCF base path (PR A).

Covers:
  1. The is_capex_super_cyclical classifier (allow-list + sector match,
     cement explicitly excluded).
  2. _compute_fcf_base routing super-cyclicals through the 10y signed-
     median window (vs the legacy 5y positive-only filter).
  3. The GRASIM-style fallback to revenue × 5% when the signed median
     is itself negative.
  4. Normal cyclicals (cement etc.) are unaffected — they keep the 5y
     positive-only filter.
"""
from __future__ import annotations

import pandas as pd

from backend.services.analysis.constants import is_capex_super_cyclical
from models.forecaster import _compute_fcf_base


# ─────────────────────────────────────────────────────────────────
# 1. Classifier
# ─────────────────────────────────────────────────────────────────

def test_is_capex_super_cyclical_classifier():
    """Allow-list + sector match. Cement explicitly excluded."""
    # Allow-list
    assert is_capex_super_cyclical("HINDALCO") is True
    assert is_capex_super_cyclical("HINDALCO.NS") is True
    assert is_capex_super_cyclical("GRASIM") is True
    assert is_capex_super_cyclical("TATASTEEL") is True
    assert is_capex_super_cyclical("JSWSTEEL") is True
    assert is_capex_super_cyclical("VEDL") is True
    assert is_capex_super_cyclical("NALCO") is True
    assert is_capex_super_cyclical("JINDALSTEL") is True
    assert is_capex_super_cyclical("SAIL") is True

    # Cement OUT (deliberate exclusion — see 2026-04-24 hotfix)
    assert is_capex_super_cyclical("ULTRACEMCO") is False
    assert is_capex_super_cyclical("SHREECEM") is False

    # Sector keyword match
    assert is_capex_super_cyclical("UNKNOWN", sector="Aluminium") is True
    assert is_capex_super_cyclical("UNKNOWN", sector="Non-Ferrous Metals") is True

    # Negatives
    assert is_capex_super_cyclical("UNKNOWN", sector="IT Services") is False
    assert is_capex_super_cyclical("TCS") is False
    assert is_capex_super_cyclical("INFY") is False
    assert is_capex_super_cyclical("HDFCBANK") is False


# ─────────────────────────────────────────────────────────────────
# 2. Super-cyclical path uses 10y signed median
# ─────────────────────────────────────────────────────────────────

def _hindalco_like_enriched(fcf_history, latest_revenue: float = 2.2e12):
    """Build a HINDALCO-shaped enriched dict with a custom FCF history."""
    years = list(range(2015, 2015 + len(fcf_history)))
    cf_df = pd.DataFrame({"year": years, "fcf": fcf_history})
    income_df = pd.DataFrame({
        "year":      years,
        "revenue":   [latest_revenue * 0.9] * len(years),
        "op_margin": [0.08] * len(years),
    })
    return {
        "ticker": "HINDALCO",
        "latest_fcf": fcf_history[-1] if fcf_history else 0,
        "latest_revenue": latest_revenue,
        "op_margin": 0.08,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "metals",
    }


def test_super_cyclical_uses_10y_signed_median():
    """For HINDALCO-like ticker with FCF history mixing positive and
    negative years, the candidate must include cyc_10y_median (signed
    over 10y), NOT cyc_5y_median (positive-only over 5y)."""
    # 10 years: mix of negative cycle bottoms and positive years.
    # Signed median over all 10 should be positive (~5e10 region).
    fcf_history = [
        -2e10,  # 2015 — capex peak
        -1e10,  # 2016
         3e10,  # 2017
         8e10,  # 2018
         5e10,  # 2019
        -5e9,   # 2020 — COVID
         4e10,  # 2021
         7e10,  # 2022
         8.3e10,# 2023 — FY24 anchor (8328 Cr)
         6e10,  # 2024
    ]
    enriched = _hindalco_like_enriched(fcf_history)
    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "cyc_10y_median" in cands, (
        f"super-cyclical must produce cyc_10y_median candidate (got {list(cands.keys())})"
    )
    assert "cyc_5y_median" not in cands, (
        f"super-cyclical must NOT use the 5y positive-only path "
        f"(got {list(cands.keys())})"
    )
    assert base > 0, "base must be positive when signed median is positive"


def test_super_cyclical_negative_signed_median_uses_revenue_x_5pct():
    """For GRASIM-style holdco where every recent year is negative or
    near-zero FCF (deep super-capex), the signed median is negative
    and the fallback must produce cyc_revenue_x_5pct = 5% × revenue."""
    # All negative or near-zero (GRASIM-like deep capex cycle).
    fcf_history = [
        -1.5e10, -2e10, -1.8e10, -3e10, -2.5e10,
        -2e10,   -3e10, -4e10,   -3.5e10, -2.8e10,
    ]
    latest_revenue = 1.3e12  # 1.3 lakh Cr
    enriched = _hindalco_like_enriched(fcf_history, latest_revenue=latest_revenue)
    enriched["ticker"] = "GRASIM"
    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "cyc_revenue_x_5pct" in cands, (
        f"all-negative signed median must trigger revenue × 5% fallback "
        f"(got {list(cands.keys())})"
    )
    assert cands["cyc_revenue_x_5pct"] == latest_revenue * 0.05
    # base must end up at cyc_revenue_x_5pct (the cap pins it there)
    assert base > 0
    assert base <= latest_revenue * 0.05 + 1.0  # allow rounding


# ─────────────────────────────────────────────────────────────────
# 3. Normal cyclicals unaffected
# ─────────────────────────────────────────────────────────────────

def test_normal_cyclical_unaffected():
    """ULTRACEMCO (cement, NOT super-cyclical) keeps the existing 5y
    positive-only filter and must NOT see cyc_10y_median."""
    fcf_history = [
        4e10, 4.5e10, 5e10, 5.5e10, 6e10,
        6.2e10, 6.5e10, 6.8e10, 7.2e10, 7.5e10,
    ]
    years = list(range(2015, 2025))
    cf_df = pd.DataFrame({"year": years, "fcf": fcf_history})
    income_df = pd.DataFrame({
        "year":      years,
        "revenue":   [6e11] * 10,
        "op_margin": [0.18] * 10,
    })
    enriched = {
        "ticker": "ULTRACEMCO",
        "latest_fcf": 7.5e10,
        "latest_revenue": 6e11,
        "op_margin": 0.18,
        "cf_df": cf_df,
        "income_df": income_df,
        # Set sector to one of the legacy _CYCLICAL_SECTORS so the
        # normal-cyclical path runs (cement was removed from that set,
        # so use 'chemicals' which IS in the set; ULTRACEMCO sector
        # tag is illustrative — the assertion is on the candidate
        # name, not on which path UltraCemCo would actually take in
        # prod).
        "sector": "chemicals",
    }
    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "cyc_5y_median" in cands, (
        f"normal cyclical must use 5y positive-only path "
        f"(got {list(cands.keys())})"
    )
    assert "cyc_10y_median" not in cands, (
        f"normal cyclical must NOT use the super-cyclical 10y path "
        f"(got {list(cands.keys())})"
    )
    assert "cyc_revenue_x_5pct" not in cands
    assert base > 0
