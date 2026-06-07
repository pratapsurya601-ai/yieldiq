"""Free-tier annual financials cap is 5y (Issue #205).

Pre-fix: the free tier was capped at 3 annual periods. With only 3 data
points the ``revenue_cagr_3y`` computation in ``_compute_summary``
cannot land a real 3-year CAGR (needs latest + 3 prior = 4 points), so
the "Show 3Y CAGR" UI badge was perpetually NULL for anonymous users.

Issue #205 raises the cap to 5 so the badge populates while leaving a
quarterly-history delta for paid tiers.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def _fake_financials_payload(years: int) -> dict:
    """Build a minimal financials payload echoing ``years_available`` so
    we can assert the cap on the wire shape without a real DB."""
    return {
        "ticker": "HDFCBANK",
        "currency": "INR",
        "currency_unit": "Cr",
        "period": "annual",
        "years_available": years,
        "has_quarterly": False,
        "data_source": "db",
        "income": [{"year": f"FY{2025 - i}"} for i in range(years)],
        "balance_sheet": [{"year": f"FY{2025 - i}"} for i in range(years)],
        "cash_flow": [{"year": f"FY{2025 - i}"} for i in range(years)],
        "summary": {
            "revenue_cagr_3y": 12.3,
            "avg_net_margin": None,
            "avg_fcf_margin": None,
            "latest_roe": None,
        },
    }


def _make_svc_capturing_years(captured: dict):
    """Return a fake FinancialsService whose get_financials records the
    ``years`` argument it was called with."""

    class _FakeSvc:
        def get_financials(self, ticker, period="annual", years=5):
            captured["ticker"] = ticker
            captured["period"] = period
            captured["years"] = years
            return _fake_financials_payload(years)

    return _FakeSvc


def _bypass_caches(monkeypatch):
    """Force both cache tiers to miss so the request reaches the service."""
    from backend.routers import analysis as analysis_router
    monkeypatch.setattr(analysis_router.cache, "get", lambda _k: None)
    monkeypatch.setattr(analysis_router.cache, "set", lambda *a, **kw: None)
    # Stub the endpoint cache module the router imports lazily.
    import backend.services.endpoint_cache_service as ecs
    monkeypatch.setattr(ecs, "get", lambda _k: None)
    monkeypatch.setattr(ecs, "set", lambda *a, **kw: None)


def test_anon_user_annual_request_caps_at_5_years(monkeypatch):
    """Anon user (no Authorization header) → free tier → 5y cap.

    Pre-fix: years would have been clamped to 3.
    """
    _bypass_caches(monkeypatch)
    captured: dict = {}
    fake_cls = _make_svc_capturing_years(captured)
    with patch(
        "backend.services.financials_service.FinancialsService", fake_cls,
    ):
        r = client.get("/api/v1/analysis/HDFCBANK/financials?years=10&period=annual")

    assert r.status_code == 200, r.text
    body = r.json()
    # Service got 5 (the new cap), NOT 3 (the old cap), NOT 10 (the raw
    # request). The bump to 5 unblocks the 3y CAGR computation.
    assert captured["years"] == 5, (
        f"expected free-tier annual cap of 5y, got {captured['years']}"
    )
    assert body["years_available"] == 5
    # The free-tier flag is still surfaced so the UI can keep the upsell
    # affordance — the cap moved, the tier semantics did not.
    assert body["tier_limited"] is True
    assert body["tier"] == "free"


def test_anon_user_request_for_fewer_years_is_not_padded(monkeypatch):
    """Cap is a max, not a floor. A request for 3y from an anon user
    must still return 3y — we never invent rows the user didn't ask for."""
    _bypass_caches(monkeypatch)
    captured: dict = {}
    fake_cls = _make_svc_capturing_years(captured)
    with patch(
        "backend.services.financials_service.FinancialsService", fake_cls,
    ):
        r = client.get("/api/v1/analysis/HDFCBANK/financials?years=3&period=annual")

    assert r.status_code == 200
    assert captured["years"] == 3
    assert r.json()["years_available"] == 3


def test_quarterly_path_is_unaffected_by_annual_cap_change(monkeypatch):
    """Quarterly limits are independent of the annual cap; the Issue #205
    change must not perturb the quarterly slice."""
    _bypass_caches(monkeypatch)
    captured: dict = {}
    fake_cls = _make_svc_capturing_years(captured)
    with patch(
        "backend.services.financials_service.FinancialsService", fake_cls,
    ):
        r = client.get("/api/v1/analysis/HDFCBANK/financials?years=10&period=quarterly")

    assert r.status_code == 200
    # period=quarterly skips the cap branch entirely; the service receives
    # whatever the Query validator clamped (max 10 per the route signature).
    assert captured["period"] == "quarterly"
    assert captured["years"] == 10
