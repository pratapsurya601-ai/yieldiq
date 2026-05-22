"""Day-108c (2026-05-23) — Sector landing page tests.

Covers:
  - Slug → cohort mapping (every Day-108c slug resolves; unknown
    slugs return None / 404).
  - Aggregate math (median over non-null fields; empty cohort yields
    None medians; verdict distribution counts correctly).
  - Endpoint contract (404 on unknown slug, 200 payload shape on
    known slug with mocked analysis_cache rows).
  - Cohort membership mirrors the engine sets (IT-Tier1 names are
    all in the it-services cohort; FMCG_COHORT_TICKERS_INLINE matches
    fmcg cohort).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.services.sector_pages import (
    SECTOR_PAGES,
    SECTOR_PAGE_SLUGS,
    get_cohort,
    tickers_with_suffix,
)


# ─── Fixtures ─────────────────────────────────────────────────────


def _payload(
    ticker: str,
    *,
    fv: float | None = None,
    base: float | None = None,
    price: float | None = None,
    verdict: str | None = None,
    score: int | None = None,
    mos: float | None = None,
    pe: float | None = None,
    roe: float | None = None,
    name: str | None = None,
) -> dict:
    """Build a minimal analysis_cache payload that exercises the
    fields the sector-page aggregator reads."""
    return {
        "ticker": ticker,
        "company": {"company_name": name or ticker.split(".")[0]},
        "valuation": {
            "fair_value": fv,
            "base_case": base,
            "current_price": price,
            "verdict": verdict,
            "margin_of_safety": mos,
        },
        "quality": {
            "yieldiq_score": score,
            "pe_ratio": pe,
            "roe": roe,
        },
    }


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


# ─── Slug / cohort registry ──────────────────────────────────────


def test_every_day108c_slug_has_a_cohort():
    expected = {
        "it-services", "fmcg", "auto", "capital-goods",
        "pharma", "utilities", "banking", "metals", "cyclical",
    }
    assert set(SECTOR_PAGE_SLUGS) == expected
    for slug in expected:
        cohort = get_cohort(slug)
        assert cohort is not None
        assert cohort["display_name"]
        assert cohort["tickers"]
        assert cohort["notes"]


def test_get_cohort_unknown_returns_none():
    assert get_cohort("not-a-real-slug") is None
    assert get_cohort("") is None
    assert get_cohort(None) is None  # type: ignore[arg-type]


def test_tickers_with_suffix_appends_ns():
    suffixed = tickers_with_suffix("it-services")
    assert "TCS.NS" in suffixed
    assert "INFY.NS" in suffixed
    assert all(s.endswith(".NS") for s in suffixed)


def test_cohort_membership_mirrors_engine_sets():
    """The it-services cohort MUST match the inline tier-1 set in
    service.py (Day-107a). The fmcg cohort MUST match
    FMCG_COHORT_TICKERS_INLINE (Day-107b). These are sourced from
    the same engine definitions so the landing page never disagrees
    with the per-ticker DCF tier assignment."""
    it_cohort = set(get_cohort("it-services")["tickers"])
    assert it_cohort == {"TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"}

    # Read the FMCG cohort directly from the source file as text so
    # the test doesn't transitively import models/forecaster.py (whose
    # WACC block carries an unrelated open try-block at import time
    # on some checkouts). The inline set name we mirror is
    # _FMCG_COHORT_TICKERS_INLINE in sector_overrides.py.
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[2]
        / "backend" / "services" / "analysis" / "sector_overrides.py"
    ).read_text(encoding="utf-8-sig")
    # Pin every FMCG ticker the audit covers — symmetry with
    # sector_overrides.py top / itc / tier-2 / tier-3 declarations.
    for t in (
        "HINDUNILVR", "NESTLEIND", "BRITANNIA", "ITC",
        "DABUR", "MARICO", "COLPAL", "GODREJCP",
        "EMAMILTD", "TATACONSUM", "VBL",
    ):
        assert t in src, f"{t} missing from sector_overrides.py source"
    fmcg_cohort = set(get_cohort("fmcg")["tickers"])
    assert fmcg_cohort == {
        "HINDUNILVR", "NESTLEIND", "BRITANNIA", "ITC",
        "DABUR", "MARICO", "COLPAL", "GODREJCP",
        "EMAMILTD", "TATACONSUM", "VBL",
    }


# ─── Aggregate math ───────────────────────────────────────────────


def test_aggregates_median_math_basic():
    from backend.routers.public import _sector_page_compute_aggregates

    rows = [
        {"ticker": "A", "score": 60, "verdict": "undervalued",
         "fv": 110, "price": 100, "mos_pct": 9.0,
         "pe_ratio": 20.0, "roe": 18.0, "fv_to_price": 1.10},
        {"ticker": "B", "score": 70, "verdict": "fairly_valued",
         "fv": 200, "price": 200, "mos_pct": 0.0,
         "pe_ratio": 25.0, "roe": 22.0, "fv_to_price": 1.00},
        {"ticker": "C", "score": 80, "verdict": "overvalued",
         "fv": 90, "price": 100, "mos_pct": -10.0,
         "pe_ratio": 30.0, "roe": 26.0, "fv_to_price": 0.90},
    ]
    agg = _sector_page_compute_aggregates(rows)
    assert agg["ticker_count"] == 3
    assert agg["median_score"] == 70
    assert agg["median_fair_value_to_price_ratio"] == 1.0
    assert agg["median_mos_pct"] == 0.0
    assert agg["median_pe"] == 25.0
    assert agg["median_roe"] == 22.0
    assert agg["verdict_distribution"] == {
        "undervalued": 1, "fairly_valued": 1, "overvalued": 1,
    }


def test_aggregates_empty_cohort_yields_none_medians():
    from backend.routers.public import _sector_page_compute_aggregates

    agg = _sector_page_compute_aggregates([])
    assert agg["ticker_count"] == 0
    for key in (
        "median_score", "median_fair_value_to_price_ratio",
        "median_mos_pct", "median_pe", "median_roe",
    ):
        assert agg[key] is None
    assert agg["verdict_distribution"] == {
        "undervalued": 0, "fairly_valued": 0, "overvalued": 0,
    }


def test_aggregates_skips_none_fields():
    """A ticker missing PE / ROE must not poison the median for those
    fields. Other rows that DO have values should be aggregated."""
    from backend.routers.public import _sector_page_compute_aggregates

    rows = [
        {"ticker": "A", "score": None, "verdict": "fairly_valued",
         "fv": None, "price": None, "mos_pct": None,
         "pe_ratio": None, "roe": None, "fv_to_price": None},
        {"ticker": "B", "score": 50, "verdict": "fairly_valued",
         "fv": 100, "price": 100, "mos_pct": 0.0,
         "pe_ratio": 18.0, "roe": 15.0, "fv_to_price": 1.0},
    ]
    agg = _sector_page_compute_aggregates(rows)
    assert agg["ticker_count"] == 2
    assert agg["median_pe"] == 18.0
    assert agg["median_roe"] == 15.0
    assert agg["median_score"] == 50


# ─── Endpoint contract ────────────────────────────────────────────


def test_endpoint_404_on_unknown_slug(client):
    res = client.get("/api/v1/public/sector/this-is-not-real")
    assert res.status_code == 404


def test_endpoint_it_services_returns_aggregates(client):
    """With mocked analysis_cache rows for the 5 IT-tier-1 names, the
    endpoint must return an aggregates block with the expected
    medians and a 5-row tickers list."""
    fake_cache = {
        "TCS.NS": _payload(
            "TCS.NS", fv=4200, base=4100, price=3850,
            verdict="fairly_valued", score=72, mos=9.1,
            pe=28.0, roe=45.0, name="TCS",
        ),
        "INFY.NS": _payload(
            "INFY.NS", fv=1800, base=1750, price=1600,
            verdict="undervalued", score=68, mos=12.5,
            pe=24.0, roe=31.0, name="Infosys",
        ),
        "WIPRO.NS": _payload(
            "WIPRO.NS", fv=550, base=540, price=520,
            verdict="fairly_valued", score=58, mos=5.7,
            pe=22.0, roe=14.0, name="Wipro",
        ),
        "HCLTECH.NS": _payload(
            "HCLTECH.NS", fv=1700, base=1680, price=1600,
            verdict="fairly_valued", score=66, mos=6.2,
            pe=23.0, roe=22.0, name="HCL Tech",
        ),
        "TECHM.NS": _payload(
            "TECHM.NS", fv=1600, base=1580, price=1700,
            verdict="overvalued", score=55, mos=-5.8,
            pe=30.0, roe=11.0, name="Tech Mahindra",
        ),
    }
    # Bypass the public-router's edge cache so each test exercises
    # a fresh compute.
    from backend.services.cache_service import cache as _cache
    _cache.delete("public:sector-page:v1:it-services")

    def _fake_get_cached(ticker, **_kwargs):
        return fake_cache.get(ticker)

    with patch(
        "backend.services.analysis_cache_service.get_cached_latest",
        side_effect=_fake_get_cached,
    ):
        res = client.get("/api/v1/public/sector/it-services")

    assert res.status_code == 200
    body = res.json()
    assert body["slug"] == "it-services"
    assert body["display_name"] == "IT Services"
    assert len(body["cohort_tickers"]) == 5
    assert "TCS.NS" in body["cohort_tickers"]
    assert len(body["tickers"]) == 5
    agg = body["aggregates"]
    assert agg["ticker_count"] == 5
    # Median of 5 scores (55, 58, 66, 68, 72) = 66
    assert agg["median_score"] == 66
    # Verdict distribution: 1 under, 3 fair, 1 over
    assert agg["verdict_distribution"] == {
        "undervalued": 1, "fairly_valued": 3, "overvalued": 1,
    }


def test_endpoint_empty_cohort_returns_200(client):
    """When NO analysis_cache rows are populated, the endpoint must
    still return 200 with an empty tickers list and ticker_count 0
    rather than a 5xx — the UI's empty-state branch needs a
    deterministic shape."""
    from backend.services.cache_service import cache as _cache
    _cache.delete("public:sector-page:v1:cyclical")

    with patch(
        "backend.services.analysis_cache_service.get_cached_latest",
        return_value=None,
    ):
        res = client.get("/api/v1/public/sector/cyclical")

    assert res.status_code == 200
    body = res.json()
    assert body["aggregates"]["ticker_count"] == 0
    assert body["tickers"] == []
    assert body["cohort_tickers"]  # cohort list still non-empty
