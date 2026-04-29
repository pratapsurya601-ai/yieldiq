"""
Defense-in-depth tests for the 2026-04-29 INFY launch-day incident.

Bug: For Indian-primary, ADR-cross-listed tickers (INFY/HCLTECH/WIPRO),
when the annual CFO/FCF/capex columns were NULL in the DB, the merge
in ``backend/services/data_service.get_stock_data`` overwrote with
yfinance's ADR ``freeCashflow`` field, which yfinance returns in raw
USD for these tickers. The USD value (3.14e9) was treated as raw
rupees → /1e7 → 314 Cr → /415 Cr shares → ~Rs.0.76/share → DCF terminal
multiple → FV=Rs.16.85 vs price Rs.1,167.5 (MoS -98.6%).

Two guards added:

  Patch 1 — ``models/forecaster._compute_fcf_base``: reject ``latest_fcf``
            candidate when ``latest_fcf / latest_revenue < 0.5%`` on a
            profitable large-cap (revenue > Rs.1,000 Cr). Forces fallback
            to ``nopat_proxy`` / ``median_recent_fcf``.

  Patch 2 — ``backend/services/data_service.get_stock_data``: for
            money-magnitude keys (freeCashflow, totalRevenue, etc.),
            an explicit NULL in DB stays NULL — do NOT pull from yfinance
            (which would leak USD-as-rupees for ADR cross-listings).

These tests pin the guard behaviour so the same regression cannot ship
again.
"""
from __future__ import annotations

import logging

import pandas as pd

from models.forecaster import _compute_fcf_base
from backend.services.data_service import _prefer_db, _MONEY_KEYS


# ─────────────────────────────────────────────────────────────────
# Patch 1 — _compute_fcf_base FCF/revenue ratio sanity guard
# ─────────────────────────────────────────────────────────────────

def _infy_like_enriched(latest_fcf: float, latest_revenue: float) -> dict:
    """Construct an enriched dict that mimics the INFY pipeline shape:
    healthy revenue/op_margin, multi-year cf/income history so that the
    nopat_proxy and median_recent_fcf candidates are still available
    even when latest_fcf is rejected."""
    # Build a multi-year cf_df with realistic positive FCFs so that the
    # max/median candidates exist and the function returns a non-zero base.
    healthy_fcf = latest_revenue * 0.18  # 18% FCF margin — INFY-like
    cf_df = pd.DataFrame({
        "year": [2021, 2022, 2023, 2024],
        "fcf":  [healthy_fcf * 0.9, healthy_fcf, healthy_fcf * 1.05, healthy_fcf * 1.1],
    })
    income_df = pd.DataFrame({
        "year":      [2021, 2022, 2023, 2024],
        "revenue":   [latest_revenue * 0.85, latest_revenue * 0.9,
                      latest_revenue * 0.95, latest_revenue],
        "op_margin": [0.24, 0.25, 0.24, 0.25],
    })
    return {
        "ticker": "INFY",
        "latest_fcf": latest_fcf,
        "latest_revenue": latest_revenue,
        "op_margin": 0.25,         # INFY-like 25% op margin
        "cf_df": cf_df,
        "income_df": income_df,
        "sector": "it_services",
    }


def test_compute_fcf_base_rejects_usd_as_rupees_leak(caplog):
    """The exact INFY incident shape: latest_fcf=3.14e9 (raw-USD leaked),
    latest_revenue=1.63e12 (Rs.1.63 Lakh Cr). Ratio is 0.19% — well below
    the 0.5% threshold. The candidate must be rejected, the function must
    still return a non-zero base from the nopat_proxy/median_recent_fcf
    fallback paths, and a warning must be logged."""
    enriched = _infy_like_enriched(latest_fcf=3.14e9, latest_revenue=1.63e12)

    with caplog.at_level(logging.WARNING):
        base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "latest_fcf" not in cands, (
        f"latest_fcf must be rejected when ratio<0.5% (got candidates={cands})"
    )
    # Other candidates should still drive the base.
    assert base > 0, "fallback candidates must produce a non-zero FCF base"
    assert any("rejecting suspicious latest_fcf" in r.getMessage() for r in caplog.records), (
        "expected a WARNING log for the rejected latest_fcf candidate"
    )


def test_compute_fcf_base_accepts_healthy_large_cap_ratio():
    """Healthy case: latest_fcf=2.5e11, latest_revenue=1.63e12 → 15.3% FCF
    margin. The candidate must be present in the candidates dict."""
    enriched = _infy_like_enriched(latest_fcf=2.5e11, latest_revenue=1.63e12)

    base, method = _compute_fcf_base(enriched)

    cands = enriched.get("_fcf_candidates", {})
    assert "latest_fcf" in cands, (
        f"latest_fcf must be kept on a healthy 15% FCF margin (got candidates={cands})"
    )
    assert cands["latest_fcf"] == 2.5e11
    assert base > 0


# ─────────────────────────────────────────────────────────────────
# Patch 2 — data_service NULL-prefer merge guard
# ─────────────────────────────────────────────────────────────────

def test_prefer_db_keeps_null_for_money_keys():
    """An explicit NULL in DB for a money-magnitude key must NOT fall
    back to yfinance — that's how ADR raw-USD freeCashflow leaked into
    rupee pipelines for INFY."""
    assert "freeCashflow" in _MONEY_KEYS

    # The exact INFY case: DB has revenue but NULL freeCashflow; yfinance
    # offers a raw-USD freeCashflow that must be discarded.
    db   = {"freeCashflow": None, "totalRevenue": 1.6e12}
    yf   = {"freeCashflow": 3.14e9, "totalRevenue": 1.6e10}  # yf in USD

    merged = {
        k: _prefer_db(k, db.get(k), yf.get(k))
        for k in set(yf) | set(db)
    }

    assert merged["freeCashflow"] is None, (
        "money-magnitude NULL in DB must stay NULL (not pull yfinance USD value)"
    )
    # totalRevenue is also a money key — DB value wins.
    assert merged["totalRevenue"] == 1.6e12


def test_prefer_db_falls_back_for_non_money_keys():
    """Non-money keys (e.g. sector/exchange/longName) should still fall
    back to yfinance when DB is None — only money fields are protected."""
    assert "sector" not in _MONEY_KEYS

    assert _prefer_db("sector", None, "Technology") == "Technology"
    assert _prefer_db("sector", "IT Services", "Technology") == "IT Services"
    # Money key with a real DB value passes through.
    assert _prefer_db("freeCashflow", 1.5e11, 3.14e9) == 1.5e11
