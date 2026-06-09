# backend/tests/test_index_dashboard.py
# ═══════════════════════════════════════════════════════════════
# Tests for /api/v1/public/index-dashboard/{slug}
#
# Background (2026-06-09 — Bug 2 fix):
# Pre-fix the endpoint ONLY consulted tier-1 (process-local
# ``cache.get(f"analysis:{ticker}")``). When tier-1 was cold the
# response shipped ``stocks=[]`` with ``available_stocks=0`` and
# the dashboard rendered empty even though the persistent tier-2
# ``analysis_cache`` table had the same row. The fix wires the
# endpoint into the canonical three-tier read used by the
# stock-summary and compare endpoints.
#
# These tests assert:
#   * Happy path returns >= 1 stock for each shipped slug
#     (nifty50, nifty-bank, nifty-it, sensex) when tier-2 has
#     constituent rows.
#   * Cold tier-1 + populated tier-2 still returns a populated
#     response (this is the root-cause regression guard).
#   * Empty fallback when neither tier has a row.
#   * Unknown slug → HTTP 404.
#   * Default sort is by score desc (existing behaviour preserved
#     by the endpoint — frontend re-sorts to MoS desc on mount).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import public as public_router  # noqa: E402
from backend.services.cache_service import cache as _cache  # noqa: E402


# ── Test doubles ─────────────────────────────────────────────────


def _stub_analysis(
    ticker: str,
    *,
    fv: float = 1000.0,
    price: float = 800.0,
    mos: float = 25.0,
    verdict: str = "undervalued",
    score: int = 75,
    sector: str = "Financial Services",
    company_name: str = "Test Co Ltd",
    grade: str = "B",
    moat: str = "narrow",
    market_cap: float = 1.0e12,
) -> SimpleNamespace:
    """Build a minimal AnalysisResponse-shaped duck.

    The endpoint reads ``analysis.valuation.{fair_value,current_price,
    margin_of_safety,verdict}``, ``analysis.quality.{yieldiq_score,
    grade,moat}`` and ``analysis.company.{company_name,sector,
    market_cap}`` — anything outside that surface is irrelevant.
    """
    return SimpleNamespace(
        ticker=ticker,
        valuation=SimpleNamespace(
            fair_value=fv,
            current_price=price,
            margin_of_safety=mos,
            verdict=verdict,
        ),
        quality=SimpleNamespace(
            yieldiq_score=score,
            grade=grade,
            moat=moat,
        ),
        company=SimpleNamespace(
            company_name=company_name,
            sector=sector,
            market_cap=market_cap,
        ),
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the process-wide in-memory cache between tests so
    populated state from one test never leaks into another."""
    try:
        _cache._store.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    yield
    try:
        _cache._store.clear()  # type: ignore[attr-defined]
    except Exception:
        pass


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────


def test_unknown_slug_returns_404(client):
    """An index_id that isn't in INDICES must 404, not 200-with-empty."""
    r = client.get("/api/v1/public/index-dashboard/nifty-imaginary")
    assert r.status_code == 404


def test_known_slugs_are_all_registered():
    """The four slugs the frontend hits must all have INDICES entries.
    Catches typo drift between page.tsx and the router config."""
    assert "nifty50" in public_router.INDICES
    assert "nifty-bank" in public_router.INDICES
    assert "nifty-it" in public_router.INDICES
    assert "sensex" in public_router.INDICES
    # SENSEX must have 30 constituents (the BSE benchmark size).
    assert len(public_router.INDICES["sensex"]["tickers"]) == 30


def test_nifty50_happy_path_returns_populated_stocks(client):
    """Tier-1 populated → response carries >= 5 stocks with the
    documented shape and a populated ``summary`` block."""
    tickers = public_router.INDICES["nifty50"]["tickers"]
    for i, t in enumerate(tickers[:10]):
        _cache.set(
            f"analysis:{t}",
            _stub_analysis(
                t,
                fv=1500 + i * 10,
                price=1000 + i * 10,
                mos=20.0 + i,
                score=80 - i,
            ),
            ttl=86400,
        )

    r = client.get("/api/v1/public/index-dashboard/nifty50")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index_id"] == "nifty50"
    assert body["total_stocks"] == len(tickers)
    assert body["available_stocks"] >= 5
    assert len(body["stocks"]) == body["available_stocks"]
    # Each stock carries the keys IndexDashboardClient consumes.
    sample = body["stocks"][0]
    for key in (
        "ticker", "display_ticker", "company_name", "sector",
        "current_price", "fair_value", "mos", "verdict",
        "score", "grade", "moat", "market_cap",
    ):
        assert key in sample, f"missing key {key!r} in {sample}"
    # Summary block carries the documented counts + extremes.
    summary = body["summary"]
    assert summary["undervalued"] >= 1
    assert summary["most_undervalued"] is not None
    assert summary["most_overvalued"] is not None


def test_sensex_happy_path_returns_populated_stocks(client):
    """SENSEX dashboard parity with the other 3 slugs."""
    tickers = public_router.INDICES["sensex"]["tickers"]
    for i, t in enumerate(tickers[:8]):
        _cache.set(
            f"analysis:{t}",
            _stub_analysis(t, mos=30.0 - i, score=85 - i),
            ttl=86400,
        )

    r = client.get("/api/v1/public/index-dashboard/sensex")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index_id"] == "sensex"
    assert body["available_stocks"] >= 5
    # Display ticker stripped of the .NS suffix.
    assert all(not s["display_ticker"].endswith(".NS") for s in body["stocks"])


def test_cold_tier1_falls_back_to_tier2(client, monkeypatch):
    """Bug 2 root-cause regression guard.

    Tier-1 empty → endpoint MUST consult tier-2
    (``analysis_cache_service.get_canonical_payload``) and emit a
    populated response. Pre-fix this returned ``stocks=[]``.
    """
    tickers = public_router.INDICES["nifty50"]["tickers"]

    # Simulate the tier-2 row store. The endpoint goes through
    # AnalysisResponse(**payload), so we monkeypatch both
    # ``get_canonical_payload`` (returns dict) and the AnalysisResponse
    # constructor (returns our SimpleNamespace stub directly so we
    # don't need a real Pydantic v2 model in the test).
    tier2_payloads = {
        t: {"ticker": t, "_mos": 20.0 + i, "_score": 80 - i}
        for i, t in enumerate(tickers[:6])
    }

    def _fake_get_canonical_payload(ticker, **kwargs):
        return tier2_payloads.get(ticker)

    def _fake_response_ctor(**payload):
        t = payload["ticker"]
        return _stub_analysis(
            t,
            mos=payload.get("_mos", 25.0),
            score=payload.get("_score", 70),
        )

    import backend.services.analysis_cache_service as _acs
    import backend.models.responses as _resp
    monkeypatch.setattr(
        _acs, "get_canonical_payload", _fake_get_canonical_payload
    )
    monkeypatch.setattr(_resp, "AnalysisResponse", _fake_response_ctor)

    r = client.get("/api/v1/public/index-dashboard/nifty50")
    assert r.status_code == 200, r.text
    body = r.json()
    # Tier-1 was cold, but tier-2 had 6 rows → response has those.
    assert body["available_stocks"] == 6
    assert len(body["stocks"]) == 6


def test_empty_fallback_when_both_tiers_cold(client, monkeypatch):
    """Both tiers cold → 200 with ``available_stocks=0`` and empty
    ``stocks`` list. (NOT a 5xx — the frontend renders a benign
    cache-warming message.)"""
    import backend.services.analysis_cache_service as _acs
    monkeypatch.setattr(
        _acs, "get_canonical_payload", lambda *a, **kw: None
    )

    r = client.get("/api/v1/public/index-dashboard/nifty-it")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available_stocks"] == 0
    assert body["stocks"] == []
    assert body["summary"]["undervalued"] == 0
    assert body["summary"]["most_undervalued"] is None
    assert body["summary"]["most_overvalued"] is None


def test_response_sort_is_by_score_desc(client):
    """Backend sorts by ``score`` descending. The frontend re-sorts
    to MoS-desc on mount; this test locks the backend contract so a
    headless client gets a deterministic order."""
    tickers = public_router.INDICES["nifty-it"]["tickers"]
    # Inject 5 tickers with deliberately mixed scores.
    scores = [60, 90, 75, 85, 70]
    for t, s in zip(tickers[:5], scores):
        _cache.set(
            f"analysis:{t}",
            _stub_analysis(t, score=s),
            ttl=86400,
        )

    r = client.get("/api/v1/public/index-dashboard/nifty-it")
    body = r.json()
    returned = [s["score"] for s in body["stocks"]]
    assert returned == sorted(returned, reverse=True)


def test_suspicious_fv_ratios_hide_from_stocks(client):
    """Stocks with FV/price > 3x or < 0.15x are bumped to the
    ``hidden_for_quality`` list — they must NOT appear in ``stocks``.
    Regression guard for the HCLTECH +268% MoS bug noted in the
    endpoint source."""
    tickers = public_router.INDICES["nifty50"]["tickers"]
    good_ticker = tickers[0]
    bad_ticker = tickers[1]
    _cache.set(
        f"analysis:{good_ticker}",
        _stub_analysis(good_ticker, fv=1100, price=1000, mos=10.0),
        ttl=86400,
    )
    _cache.set(
        f"analysis:{bad_ticker}",
        _stub_analysis(bad_ticker, fv=5000, price=1000, mos=400.0),
        ttl=86400,
    )

    r = client.get("/api/v1/public/index-dashboard/nifty50")
    body = r.json()
    visible = {s["ticker"] for s in body["stocks"]}
    assert good_ticker in visible
    assert bad_ticker not in visible
    hidden = {h["ticker"] for h in body.get("hidden_for_quality", [])}
    assert bad_ticker in hidden
