"""Tests for the Portfolio Prism aggregator (Phase 1, 2026-05-03).

Covers:
  - Value-weighted Prism pillar math on a 50/50 portfolio of two
    known-cached tickers
  - Composite (yieldiq_score) value-weighting
  - Sector concentration percentages
  - Valuation skew bucketing
  - Piotroski distribution bucketing
  - 25-holding cap enforcement at the router layer
  - data_limited handling when a ticker is not in the cache

Both `analysis_cache_service.get_cached` and the in-memory `cache.get`
(for `prism:{T}:raw`) are monkey-patched so the suite never touches
real Postgres or Redis.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.services import portfolio_aggregator as agg
from backend.services import analysis_cache_service


# ── Fixture payloads ────────────────────────────────────────────
# Two synthetic tickers with deliberately different per-pillar
# scores so the value-weighted average is easy to verify.
#
# Holding A: 10 shares @ ₹100 → value 1,000  (50% weight in 50/50 fixture below)
# Holding B: 20 shares @ ₹50  → value 1,000  (50% weight)

_A_PAYLOAD = {
    "company": {"sector": "IT Services"},
    "valuation": {"current_price": 100.0, "verdict": "undervalued"},
    "quality": {"piotroski_score": 8, "yieldiq_score": 80},
}
_B_PAYLOAD = {
    "company": {"sector": "Banking"},
    "valuation": {"current_price": 50.0, "verdict": "overvalued"},
    "quality": {"piotroski_score": 5, "yieldiq_score": 60},
}

# Prism axes 0..10. Aggregator converts to 0..100 by multiplying by 10.
_A_PRISM = {
    "hex": {
        "axes": {
            "value":   {"score": 8.0},
            "quality": {"score": 9.0},
            "growth":  {"score": 7.0},
            "moat":    {"score": 6.0},
            "safety":  {"score": 8.0},
            "pulse":   {"score": 5.0},
        }
    }
}
_B_PRISM = {
    "hex": {
        "axes": {
            "value":   {"score": 4.0},
            "quality": {"score": 5.0},
            "growth":  {"score": 3.0},
            "moat":    {"score": 4.0},
            "safety":  {"score": 6.0},
            "pulse":   {"score": 7.0},
        }
    }
}


def _patch_caches(monkeypatch, analysis_map: dict, prism_map: dict):
    """Replace get_cached + in-memory cache.get with deterministic stubs."""
    def fake_get_cached(ticker: str, max_age_hours: int = 24):
        return analysis_map.get(ticker)

    monkeypatch.setattr(
        analysis_cache_service, "get_cached", fake_get_cached
    )
    # The aggregator imports analysis_cache_service as a module-level
    # symbol, so patching the attribute on the imported module is
    # enough — but be defensive and patch through the aggregator too.
    monkeypatch.setattr(
        agg.analysis_cache_service, "get_cached", fake_get_cached, raising=True
    )

    def fake_cache_get(key: str):
        return prism_map.get(key)

    monkeypatch.setattr(agg.cache, "get", fake_cache_get, raising=True)


def test_weighted_prism_5050_portfolio(monkeypatch):
    """50/50 INFY + HDFCBANK by value → per-pillar = simple average."""
    analysis_map = {
        "INFY.NS": _A_PAYLOAD,
        "HDFCBANK.NS": _B_PAYLOAD,
    }
    prism_map = {
        "prism:INFY.NS:raw": _A_PRISM,
        "prism:HDFCBANK.NS:raw": _B_PRISM,
    }
    _patch_caches(monkeypatch, analysis_map, prism_map)

    holdings = [
        {"ticker": "INFY", "shares": 10},      # value 1000
        {"ticker": "HDFCBANK", "shares": 20},  # value 1000
    ]
    result = agg.aggregate_portfolio(holdings)

    summary = result["summary"]
    assert summary["holding_count"] == 2
    assert summary["total_value"] == pytest.approx(2000.0)
    assert summary["data_limited_count"] == 0

    # Composite: (80 + 60) / 2 = 70
    assert summary["composite_score"] == pytest.approx(70.0)

    # Per-pillar average × 10 (axes are 0..10, output is 0..100):
    expected_pillars = {
        "value":   ((8.0 + 4.0) / 2) * 10,  # 60
        "quality": ((9.0 + 5.0) / 2) * 10,  # 70
        "growth":  ((7.0 + 3.0) / 2) * 10,  # 50
        "moat":    ((6.0 + 4.0) / 2) * 10,  # 50
        "safety":  ((8.0 + 6.0) / 2) * 10,  # 70
        "pulse":   ((5.0 + 7.0) / 2) * 10,  # 60
    }
    for p, exp in expected_pillars.items():
        assert result["prism_pillars"][p] == pytest.approx(exp), (
            f"pillar {p}: got {result['prism_pillars'][p]}, want {exp}"
        )


def test_sector_concentration_50_50(monkeypatch):
    analysis_map = {"INFY.NS": _A_PAYLOAD, "HDFCBANK.NS": _B_PAYLOAD}
    _patch_caches(monkeypatch, analysis_map, {})

    holdings = [
        {"ticker": "INFY", "shares": 10},
        {"ticker": "HDFCBANK", "shares": 20},
    ]
    result = agg.aggregate_portfolio(holdings)
    sectors = {row["sector"]: row["pct"] for row in result["sector_concentration"]}
    assert sectors == {"IT Services": pytest.approx(50.0), "Banking": pytest.approx(50.0)}


def test_valuation_skew_50_50(monkeypatch):
    analysis_map = {"INFY.NS": _A_PAYLOAD, "HDFCBANK.NS": _B_PAYLOAD}
    _patch_caches(monkeypatch, analysis_map, {})
    holdings = [
        {"ticker": "INFY", "shares": 10},
        {"ticker": "HDFCBANK", "shares": 20},
    ]
    skew = agg.aggregate_portfolio(holdings)["valuation_skew"]
    assert skew["undervalued"] == pytest.approx(50.0)
    assert skew["overvalued"] == pytest.approx(50.0)
    assert skew["fairly_valued"] == pytest.approx(0.0)
    assert skew["other"] == pytest.approx(0.0)


def test_piotroski_distribution(monkeypatch):
    """Strong (>=7), moderate (4-6), weak (<4) bucket counts."""
    analysis_map = {
        "AAA.NS": {**_A_PAYLOAD, "quality": {**_A_PAYLOAD["quality"], "piotroski_score": 9}},
        "BBB.NS": {**_A_PAYLOAD, "quality": {**_A_PAYLOAD["quality"], "piotroski_score": 7}},
        "CCC.NS": {**_A_PAYLOAD, "quality": {**_A_PAYLOAD["quality"], "piotroski_score": 5}},
        "DDD.NS": {**_A_PAYLOAD, "quality": {**_A_PAYLOAD["quality"], "piotroski_score": 2}},
    }
    _patch_caches(monkeypatch, analysis_map, {})
    holdings = [
        {"ticker": "AAA", "shares": 1},
        {"ticker": "BBB", "shares": 1},
        {"ticker": "CCC", "shares": 1},
        {"ticker": "DDD", "shares": 1},
    ]
    dist = agg.aggregate_portfolio(holdings)["piotroski_distribution"]
    assert dist["strong"] == 2     # 9, 7
    assert dist["moderate"] == 1   # 5
    assert dist["weak"] == 1       # 2
    assert dist["unknown"] == 0


def test_data_limited_when_cache_miss(monkeypatch):
    """Tickers absent from cache must be reported, not cause a 500."""
    _patch_caches(monkeypatch, {"INFY.NS": _A_PAYLOAD}, {})
    holdings = [
        {"ticker": "INFY", "shares": 10},
        {"ticker": "MISSING", "shares": 5},
    ]
    result = agg.aggregate_portfolio(holdings)
    assert "MISSING.NS" in result["summary"]["data_limited_tickers"]
    assert result["summary"]["data_limited_count"] == 1
    # Total value = INFY only (1000)
    assert result["summary"]["total_value"] == pytest.approx(1000.0)


def test_router_rejects_over_25_holdings(monkeypatch):
    """The router must 400 on >25 holdings — caller never sees the agg."""
    from fastapi import HTTPException
    from backend.routers import portfolio as portfolio_router

    req = portfolio_router.PrismAnalyzeRequest(
        holdings=[
            portfolio_router.PrismHolding(ticker=f"T{i}", shares=1)
            for i in range(26)
        ]
    )

    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            portfolio_router.analyze_portfolio(
                req, user={"email": "u@example.com", "tier": "free"}
            )
        )
    assert ei.value.status_code == 400
    assert "25" in str(ei.value.detail)


def test_router_rejects_empty(monkeypatch):
    from fastapi import HTTPException
    from backend.routers import portfolio as portfolio_router

    req = portfolio_router.PrismAnalyzeRequest(holdings=[])
    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            portfolio_router.analyze_portfolio(
                req, user={"email": "u@example.com"}
            )
        )
    assert ei.value.status_code == 400


def test_router_rejects_zero_shares(monkeypatch):
    from fastapi import HTTPException
    from backend.routers import portfolio as portfolio_router

    req = portfolio_router.PrismAnalyzeRequest(
        holdings=[portfolio_router.PrismHolding(ticker="INFY", shares=0)]
    )
    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            portfolio_router.analyze_portfolio(
                req, user={"email": "u@example.com"}
            )
        )
    assert ei.value.status_code == 400
