"""Backend tests for P0 #2 / P0 #5 (2026-05-25):

  - GET /api/v1/portfolio/sum-of-parts
  - POST /api/v1/analysis/fv-history/batch

Both endpoints are READ-ONLY against existing tables — these tests
patch the underlying service / pipeline layer instead of hitting a
live DB so they're cheap to run in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.main import app  # noqa: E402
from backend.middleware.auth import (  # noqa: E402
    get_current_user,
    get_current_user_optional,
)


AUTH_USER = {"email": "test@yieldiq.com", "tier": "pro"}


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    app.dependency_overrides[get_current_user_optional] = lambda: AUTH_USER
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_user_optional, None)


def _live_payload(holdings):
    return {
        "holdings": holdings,
        "summary": {
            "total_invested": 0,
            "total_current_value": 0,
            "total_pnl_abs": 0,
            "total_pnl_pct": 0,
            "winners": 0,
            "losers": 0,
            "count": len(holdings),
        },
    }


# ── /portfolio/sum-of-parts ─────────────────────────────────────


def test_sop_requires_auth():
    """Without the override the endpoint must reject anonymous callers."""
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    r = client.get("/api/v1/portfolio/sum-of-parts")
    assert r.status_code in (401, 403)


def test_sop_undervalued_verdict():
    """IV > MV by >20% should label the portfolio Undervalued."""
    holdings = [
        # qty=10 @ cp=100, fv=140 → mv=1000, iv=1400, gap = +40%
        {"ticker": "A.NS", "quantity": 10, "current_price": 100.0, "fair_value": 140.0},
    ]
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload(holdings),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["market_value"] == 1000.0
    assert body["intrinsic_value"] == 1400.0
    assert body["verdict_label"] == "Undervalued"
    assert body["gap_pct"] == 40.0
    assert body["holdings_with_fv_count"] == 1
    assert body["holdings_without_fv_count"] == 0
    assert body["total_holdings"] == 1


def test_sop_overvalued_verdict():
    holdings = [
        {"ticker": "A.NS", "quantity": 10, "current_price": 100.0, "fair_value": 60.0},
    ]
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload(holdings),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    body = r.json()
    assert body["verdict_label"] == "Overvalued"
    assert body["gap_pct"] == -40.0


def test_sop_fairly_valued_verdict():
    """Gap within [-20%, +20%] should be Fairly Valued."""
    holdings = [
        {"ticker": "A.NS", "quantity": 10, "current_price": 100.0, "fair_value": 110.0},
    ]
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload(holdings),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    body = r.json()
    assert body["verdict_label"] == "Fairly Valued"
    assert body["gap_pct"] == 10.0


def test_sop_partial_coverage_counts_missing_fv():
    """Holdings without a cached FV must be counted but not aggregated."""
    holdings = [
        {"ticker": "A.NS", "quantity": 10, "current_price": 100.0, "fair_value": 130.0},
        # No FV — should be reported in holdings_without_fv_count.
        {"ticker": "B.NS", "quantity": 5, "current_price": 50.0, "fair_value": None},
        # FV=0 also counts as "without FV" (cache miss surrogate).
        {"ticker": "C.NS", "quantity": 2, "current_price": 200.0, "fair_value": 0},
    ]
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload(holdings),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    body = r.json()
    assert body["holdings_with_fv_count"] == 1
    assert body["holdings_without_fv_count"] == 2
    assert body["total_holdings"] == 3
    # IV is computed from only the 1 priced holding → 10 × 130 = 1300
    assert body["intrinsic_value"] == 1300.0


def test_sop_empty_when_no_fv_coverage():
    """Zero cached FVs → intrinsic_value/verdict_label are None."""
    holdings = [
        {"ticker": "A.NS", "quantity": 10, "current_price": 100.0, "fair_value": None},
    ]
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload(holdings),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    body = r.json()
    assert body["intrinsic_value"] is None
    assert body["verdict_label"] is None
    assert body["holdings_with_fv_count"] == 0
    assert body["holdings_without_fv_count"] == 1


def test_sop_empty_holdings():
    """Zero holdings → all-zero totals, no verdict."""
    with patch(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        return_value=_live_payload([]),
    ):
        client = TestClient(app)
        r = client.get("/api/v1/portfolio/sum-of-parts")
    body = r.json()
    assert body["market_value"] == 0.0
    assert body["intrinsic_value"] is None
    assert body["total_holdings"] == 0


# ── /analysis/fv-history/batch ──────────────────────────────────


def test_fv_history_batch_empty_request_returns_empty_dict():
    client = TestClient(app)
    r = client.post("/api/v1/analysis/fv-history/batch", json={"tickers": []})
    assert r.status_code == 200
    assert r.json() == {}


def test_fv_history_batch_cap_at_50():
    client = TestClient(app)
    tickers = [f"T{i}.NS" for i in range(51)]
    r = client.post("/api/v1/analysis/fv-history/batch", json={"tickers": tickers})
    assert r.status_code == 400


def test_fv_history_batch_serves_from_cache():
    """When the cache is warm we must never touch the DB."""
    from backend.services.cache_service import cache as _c

    cached_payload = {
        "ticker": "RELIANCE.NS",
        "has_data": True,
        "years_returned": 1,
        "data": [
            {"date": "2025-06-01", "price": 100.0, "fair_value": 110.0},
            {"date": "2025-06-02", "price": 101.0, "fair_value": 111.0},
        ],
        "summary": {"has_data": True, "total_points": 2},
    }
    _c.set("fv-history:RELIANCE.NS:1", cached_payload, ttl=3600)
    try:
        client = TestClient(app)
        r = client.post(
            "/api/v1/analysis/fv-history/batch",
            json={"tickers": ["reliance.ns"], "years": 1},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "RELIANCE.NS" in body
        assert body["RELIANCE.NS"]["has_data"] is True
        assert len(body["RELIANCE.NS"]["data"]) == 2
    finally:
        _c.delete("fv-history:RELIANCE.NS:1")
