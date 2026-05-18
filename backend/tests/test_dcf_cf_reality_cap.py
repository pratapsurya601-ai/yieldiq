"""
Cash-flow reality sanity gate in ``models/forecaster._compute_fcf_base``.

Bug origin (2026-05-18, DRREDDY.NS):
    Production /reverse-dcf for DRREDDY surfaced
    ``normalized_fcf=2.43e+16`` (i.e. ₹2.43 × 10^9 Cr), which fed
    forward into the main DCF and produced uncapped FV ≈ ₹4,698 vs
    consensus ₹1,200-1,500 (current price ₹1,333). cf_df from
    yfinance for DRREDDY contained perfectly normal positive FCFs
    (~₹4,000 Cr peak), so the absurd base could only come from one of
    the revenue-scaled candidates (nopat_proxy, pharma_rd_adjusted,
    hist_p75_margin) being polluted by an upstream
    ``latest_revenue`` unit mismatch — most plausibly the XBRL TTM
    ladder in ``backend/services/quarterly_results_service.py``
    returning ``revenue_ttm`` in ₹Cr (~32553) while the rest of the
    pipeline expects raw rupees (~3.25e11).

Defense:
    After all candidate selection runs, anchor a hard ceiling on the
    cf_df-derived ``max_recent_fcf`` and ``latest`` positive FCF
    values (yfinance native rupee units — immune to the upstream
    Cr↔rupee unit drift). If ``base`` exceeds ``2.5 × cf_anchor``,
    pull it back to ``cf_anchor`` and label the method
    ``cf_reality_cap(<prior method>)`` so the trace surfaces the
    intervention.

These tests pin the gate behaviour and the no-op promise for
healthy data shapes.
"""
from __future__ import annotations

import logging

import pandas as pd

from models.forecaster import _compute_fcf_base


def _drreddy_clean_enriched(latest_revenue: float) -> dict:
    """DRREDDY-shaped enriched dict with clean cf_df / income_df from
    yfinance and a parameterised ``latest_revenue`` so the test can
    inject the buggy 1e7 inflation independently of the cf_df values.
    """
    cf_df = pd.DataFrame({
        "year":  [2022, 2023, 2024, 2025],
        "fcf":   [9.059e9, 4.0009e10, 1.7998e10, 1.203e10],
        "cfo":   [2.8108e10, 5.8875e10, 4.5433e10, 4.6428e10],
        "capex": [-1.9049e10, -1.8866e10, -2.7435e10, -3.4398e10],
    })
    income_df = pd.DataFrame({
        "year":             [2022, 2023, 2024, 2025],
        "revenue":          [2.14391e11, 2.45879e11, 2.79164e11, 3.25535e11],
        "operating_income": [3.5919e10, 5.9054e10, 6.5308e10, 7.2014e10],
        "net_income":       [2.3568e10, 4.5067e10, 5.5684e10, 5.6544e10],
        "op_margin":        [3.5919e10 / 2.14391e11, 5.9054e10 / 2.45879e11,
                             6.5308e10 / 2.79164e11, 7.2014e10 / 3.25535e11],
    })
    return {
        "ticker": "DRREDDY.NS",
        "latest_fcf": 3.11e10,   # post-_get_adjusted_fcf PAT-floored value
        "latest_revenue": latest_revenue,
        "op_margin": 7.2014e10 / 3.25535e11,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "pharma",
        "industry": "",
    }


def test_clean_drreddy_does_not_trigger_cf_reality_cap():
    """With correct rupee-unit latest_revenue (₹3.25e11 = ₹32,553 Cr),
    the DRREDDY pipeline should produce a ₹4,001 Cr base from the
    cf_df ``max_recent_fcf`` candidate and the cap MUST NOT fire."""
    enriched = _drreddy_clean_enriched(latest_revenue=3.25535e11)

    base, method = _compute_fcf_base(enriched)

    assert "cf_reality_cap" not in method, (
        f"cap should NOT fire on clean DRREDDY data (got method={method})"
    )
    # Sanity: base lands in the ₹3,500 - ₹6,000 Cr corridor (cf_df-anchored).
    assert 3.5e10 <= base <= 6.0e10, (
        f"clean DRREDDY base should be in ₹3,500-6,000 Cr; got ₹{base/1e7:,.0f}Cr"
    )


def test_drreddy_revenue_unit_corruption_triggers_cap(caplog):
    """Reproduce the prod failure: ``latest_revenue`` inflated by 1e7
    (i.e. ₹Cr value passed as if it were raw rupees, then re-multiplied
    by something upstream). pharma_rd_adjusted, nopat_proxy and
    hist_p75_margin all scale with this inflated revenue and would
    drive the base into the ₹10^9 Cr range without the cap. The cap
    must fire and pull the base back to the cf_df anchor (~₹4,001 Cr
    max_recent_fcf)."""
    bad_rev = 3.25535e11 * 1e7  # ₹3.25e18 — the bug shape
    enriched = _drreddy_clean_enriched(latest_revenue=bad_rev)

    with caplog.at_level(logging.WARNING):
        base, method = _compute_fcf_base(enriched)

    assert method.startswith("cf_reality_cap("), (
        f"cap label must wrap the prior method (got {method})"
    )
    # Pulled to the cf_df max_recent_fcf (₹4,001 Cr from the FY23
    # cf_df row above).
    assert abs(base - 4.0009e10) < 1e7, (
        f"base must be pulled to the cf_df max_recent_fcf ₹4,001 Cr; "
        f"got ₹{base/1e7:,.0f}Cr"
    )
    assert any("CF-reality cap fired" in r.getMessage() for r in caplog.records), (
        "expected a WARNING log on cap trigger"
    )


def test_legitimate_high_rd_pharma_within_2_5x_anchor_not_capped():
    """Legit high-R&D pharma where ``pharma_rd_adjusted`` is ~30% above
    ``max_recent_fcf`` (the design-intent lift R&D add-back gives an
    asset-light pharma name). Cap must NOT fire — the 2.5× headroom
    leaves plenty of room for the R&D candidate to vote."""
    # cf_df with max positive FCF ₹60 Cr → cap threshold = 2.5 × ₹60Cr = ₹150Cr
    cf_df = pd.DataFrame({
        "year":  [2022, 2023, 2024, 2025],
        "fcf":   [3e8, 4e8, 5e8, 6e8],
        "cfo":   [5e8, 6e8, 7e8, 8e8],
        "capex": [-2e8, -2e8, -2e8, -2e8],
    })
    income_df = pd.DataFrame({
        "year":             [2022, 2023, 2024, 2025],
        "revenue":          [1e10, 1e10, 1e10, 1e10],
        "operating_income": [2e9, 2.5e9, 3e9, 3.5e9],
        "net_income":       [1.5e9, 2e9, 2.5e9, 3e9],
        "op_margin":        [0.20, 0.25, 0.30, 0.35],
    })
    enriched = {
        "ticker": "SMALLPHARMA.NS",
        "latest_fcf": 6e8,
        "latest_revenue": 1e10,
        "op_margin": 0.35,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "pharma",
        "industry": "",
    }

    base, method = _compute_fcf_base(enriched)

    assert "cf_reality_cap" not in method, (
        f"cap should NOT fire when candidates are within 2.5× of cf_anchor "
        f"(got method={method}, base=₹{base/1e7:,.0f}Cr)"
    )


def test_cap_no_op_when_cf_df_is_empty():
    """When ``cf_df`` is empty (no positive FCFs to anchor against), the
    cap must silently no-op — we never tighten a base that has no
    reliable cash-flow reference to compare to."""
    cf_df = pd.DataFrame(columns=["year", "fcf"])
    income_df = pd.DataFrame({
        "year":             [2024, 2025],
        "revenue":          [1e11, 1.1e11],
        "operating_income": [2e10, 2.2e10],
        "net_income":       [1.5e10, 1.6e10],
        "op_margin":        [0.20, 0.20],
    })
    enriched = {
        "ticker": "NOCF.NS",
        "latest_fcf": 0,
        "latest_revenue": 1.1e11,
        "op_margin": 0.20,
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "pharma",
        "industry": "",
    }

    base, method = _compute_fcf_base(enriched)

    assert "cf_reality_cap" not in method, (
        f"cap must no-op when cf_df has no positive FCFs (got method={method})"
    )
