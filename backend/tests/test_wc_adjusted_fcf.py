"""
Tests for the working-capital-adjusted FCF base computation for
inventory-heavy businesses.

Background. For tickers like TITAN (jewellery), DMART (retail), VBL
(beverages), TRENT — reported FCF can swing wildly year-to-year as
inventory builds/depletes during expansion. The DCF using stored FCF
can over-correct on a single bad WC year (e.g. TITAN FY23 FCF
collapsed to ~Rs.200 Cr after a gold-stock build, vs a 3y average of
~Rs.1,500 Cr). The fix: smooth ΔWC by using a 3y median of
(CFO - |CapEx|) when computing the FCF base, and prioritise that
candidate over the volatile single-year `latest_fcf`.

This test file pins four behaviours:

  1. Classifier — TITAN/DMART True, RELIANCE/TCS False, sector="Retail" True.
  2. WC-smoothed dominates for inventory-heavy tickers — TITAN with a bad
     latest year + healthy prior 2y produces a base near the 3y median,
     not the bad latest.
  3. Non-inventory-heavy unaffected — TCS does not pick up a
     `wc_adjusted_3y` candidate.
  4. Negative average doesn't override — if the 3y median of CFO-|CapEx|
     is negative, the candidate is NOT added (don't artificially anchor
     on losses).
"""
from __future__ import annotations

import pandas as pd

from backend.services.analysis.constants import is_inventory_heavy
from models.forecaster import _compute_fcf_base


# ─────────────────────────────────────────────────────────────────
# 1. Classifier
# ─────────────────────────────────────────────────────────────────

def test_classifier_inventory_heavy_tickers():
    assert is_inventory_heavy("TITAN") is True
    assert is_inventory_heavy("TITAN.NS") is True
    assert is_inventory_heavy("DMART") is True
    assert is_inventory_heavy("DMART.NS") is True
    # Jewellery extension set
    assert is_inventory_heavy("KALYANKJIL") is True
    assert is_inventory_heavy("RAJESHEXPO") is True
    # Beverages
    assert is_inventory_heavy("VBL") is True


def test_classifier_non_inventory_heavy_tickers():
    assert is_inventory_heavy("RELIANCE") is False
    assert is_inventory_heavy("TCS") is False
    assert is_inventory_heavy("HDFCBANK") is False
    assert is_inventory_heavy("INFY") is False


def test_classifier_sector_signal():
    # Retail sector classifies a ticker that isn't on the curated list
    assert is_inventory_heavy("UNKNOWNCO", sector="Retail") is True
    assert is_inventory_heavy("UNKNOWNCO", sector="Apparel") is True
    # Generic sector doesn't fire
    assert is_inventory_heavy("UNKNOWNCO", sector="Technology") is False


def test_classifier_industry_keyword():
    assert is_inventory_heavy(
        "UNKNOWNCO", industry="Jewellery & Watches"
    ) is True
    assert is_inventory_heavy(
        "UNKNOWNCO", industry="Gems and Diamond"
    ) is True
    assert is_inventory_heavy(
        "UNKNOWNCO", industry="Retail Trade - Department Stores"
    ) is True
    assert is_inventory_heavy(
        "UNKNOWNCO", industry="Software - Application"
    ) is False


# ─────────────────────────────────────────────────────────────────
# 2. WC-smoothed dominates for inventory-heavy tickers
# ─────────────────────────────────────────────────────────────────

def _titan_like_enriched(
    cfo_series: list[float],
    capex_series: list[float],
    fcf_series: list[float],
    sector: str = "consumer_durable",
) -> dict:
    """Construct a TITAN-shaped enriched dict with a multi-year cf_df.

    All values in raw rupees. cfo, capex, and fcf are independently
    populated so we can simulate a bad WC year cleanly (latest_fcf low
    via inventory build, while 3y CFO-CapEx remains healthy).
    """
    n = len(cfo_series)
    years = list(range(2024 - n + 1, 2025))
    cf_df = pd.DataFrame({
        "year":  years,
        "cfo":   cfo_series,
        "ocf":   cfo_series,
        "capex": capex_series,
        "fcf":   fcf_series,
    })
    income_df = pd.DataFrame({
        "year":      years,
        "revenue":   [50_000e7] * n,            # Rs. 50,000 Cr
        "op_margin": [0.12] * n,
    })
    return {
        "ticker": "TITAN",
        "latest_fcf": fcf_series[-1],
        "latest_revenue": 50_000e7,
        "op_margin": 0.12,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": sector,
    }


def test_wc_smoothed_dominates_for_titan():
    """TITAN: latest year had a big inventory build → FCF=200 Cr.
    Prior 2y were healthy at 1,500 Cr. The DCF base must come from
    the 3y WC-smoothed candidate, not the volatile latest_fcf."""
    bad_latest_fcf = 200e7      # Rs. 200 Cr
    healthy_fcf    = 1_500e7    # Rs. 1,500 Cr
    cfo            = 1_500e7    # Rs. 1,500 Cr (steady operating cash)
    capex          = 100e7      # Rs. 100 Cr
    enriched = _titan_like_enriched(
        # CFO is ~steady — the 3y median of CFO-|CapEx| ≈ 1,400 Cr
        cfo_series=[cfo, cfo, cfo],
        capex_series=[capex, capex, capex],
        # but reported FCF for the latest year crashes due to WC drag
        fcf_series=[healthy_fcf, healthy_fcf, bad_latest_fcf],
    )

    base, method = _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})

    assert "wc_adjusted_3y" in cands, (
        f"TITAN should produce a wc_adjusted_3y candidate; got {cands}"
    )
    wc_val = cands["wc_adjusted_3y"]
    assert 1_300e7 <= wc_val <= 1_500e7, (
        f"wc_adjusted_3y should be ~CFO-CapEx median ≈ Rs.1,400 Cr; got Rs.{wc_val/1e7:.0f} Cr"
    )
    # The selected base must be far above the bad latest_fcf — within 30%
    # of the wc-smoothed value, not the Rs. 200 Cr volatile reading.
    assert base >= 1_000e7, (
        f"selected base should reflect the 3y WC-smoothed value, not the "
        f"bad-WC-year latest_fcf=Rs.200 Cr; got Rs.{base/1e7:.0f} Cr ({method})"
    )


# ─────────────────────────────────────────────────────────────────
# 3. Non-inventory-heavy unaffected
# ─────────────────────────────────────────────────────────────────

def test_non_inventory_heavy_does_not_get_wc_candidate():
    """TCS — pure IT services, asset-light. _compute_fcf_base must NOT
    add a wc_adjusted_3y candidate even though cfo/capex columns exist."""
    cf_df = pd.DataFrame({
        "year":  [2022, 2023, 2024],
        "cfo":   [40_000e7, 42_000e7, 44_000e7],
        "ocf":   [40_000e7, 42_000e7, 44_000e7],
        "capex": [2_000e7, 2_500e7, 3_000e7],
        "fcf":   [38_000e7, 39_500e7, 41_000e7],
    })
    income_df = pd.DataFrame({
        "year":      [2022, 2023, 2024],
        "revenue":   [200_000e7, 215_000e7, 230_000e7],
        "op_margin": [0.25, 0.25, 0.25],
    })
    enriched = {
        "ticker": "TCS",
        "latest_fcf": 41_000e7,
        "latest_revenue": 230_000e7,
        "op_margin": 0.25,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "it_services",
    }

    base, method = _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})

    assert "wc_adjusted_3y" not in cands, (
        f"non-inventory-heavy ticker (TCS) must NOT produce a wc_adjusted_3y "
        f"candidate; got {cands}"
    )
    assert base > 0


# ─────────────────────────────────────────────────────────────────
# 4. Negative 3y median doesn't override
# ─────────────────────────────────────────────────────────────────

def test_negative_wc_smoothed_not_added_as_candidate():
    """If the 3y median of CFO-|CapEx| is negative, the wc_adjusted_3y
    candidate must NOT be added — never anchor the DCF on losses."""
    # CFO < CapEx every year — a structurally cash-burning expansion phase
    enriched = _titan_like_enriched(
        cfo_series=[300e7, 300e7, 300e7],     # Rs. 300 Cr
        capex_series=[800e7, 800e7, 800e7],   # Rs. 800 Cr — heavier
        fcf_series=[-500e7, -500e7, -500e7],
    )

    _ = _compute_fcf_base(enriched)
    cands = enriched.get("_fcf_candidates", {})

    assert "wc_adjusted_3y" not in cands, (
        f"negative 3y CFO-CapEx must NOT produce a wc_adjusted_3y "
        f"candidate; got {cands}"
    )
