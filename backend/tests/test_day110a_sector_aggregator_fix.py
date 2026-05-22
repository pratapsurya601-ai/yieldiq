"""Day-110a (2026-05-23) — Sector aggregator manifest-bypass tests.

Bug being fixed:
    The Day-108c sector landing page aggregator
    (backend/routers/public.py::_sector_page_aggregate) called
    analysis_cache_service.get_cached(symbol) without fields_needed=.
    Per the Day-94 manifest matcher (_field_in_scope), an empty
    fields_needed is treated as "everything" — which matches the
    v_init_2026_05_22 wildcard entry and invalidates every cached row
    written before 2026-05-22T23:00 UTC. Effect: every sector landing
    page returned ticker_count=0 even though analysis_cache had rows
    for the cohort tickers.

Fix (Option B):
    Added analysis_cache_service.get_cached_latest(ticker) which
    returns the most recent cached row regardless of manifest
    validation. The sector aggregator now uses this. Documented as
    a stale-tolerant read path — DO NOT use on freshness-critical
    surfaces.

These tests pin:
    1. get_cached_latest returns a row even when the manifest says
       the row is invalid for get_cached().
    2. get_cached_latest returns None for a ticker with no cached row.
    3. _sector_page_aggregate populates `tickers` when the cache has
       rows (regression test for the empty-cohort bug).
    4. _sector_page_aggregate gracefully skips tickers with no row.
    5. The manifest semantics for the regular get_cached() are
       UNCHANGED by this PR (no regression on the freshness gate).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ─── Fixtures ────────────────────────────────────────────────────


def _payload(ticker: str, *, fv=4000.0, price=3800.0,
             verdict="fairly_valued", score=70, mos=5.0,
             pe=25.0, roe=20.0, name=None) -> dict:
    return {
        "ticker": ticker,
        "company": {"company_name": name or ticker.split(".")[0]},
        "valuation": {
            "fair_value": fv,
            "base_case": fv,
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


# ─── 1. get_cached_latest bypasses the manifest ───────────────────


def test_get_cached_latest_returns_row_even_when_manifest_invalidates():
    """The v_init_2026_05_22 wildcard manifest entry invalidates any
    row computed before 2026-05-22T23:00Z. get_cached_latest must
    ignore that and serve the row anyway.

    We simulate this by patching the underlying session to return a
    payload with a pre-anchor computed_at and asserting:
      - get_cached_latest() returns the payload (manifest bypassed)
    """
    from backend.services import analysis_cache_service

    pre_anchor_dt = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    fake_payload = _payload("TCS.NS")

    class _FakeSess:
        def execute(self, *args, **kwargs):
            class _Res:
                @staticmethod
                def fetchone():
                    return (fake_payload, pre_anchor_dt)
            return _Res()

        def close(self):
            pass

    with patch.object(
        analysis_cache_service, "_get_session", return_value=_FakeSess()
    ):
        out = analysis_cache_service.get_cached_latest("TCS.NS")

    assert out is not None
    assert out["ticker"] == "TCS.NS"
    assert out["valuation"]["fair_value"] == 4000.0


# ─── 2. get_cached_latest returns None on no row ─────────────────


def test_get_cached_latest_returns_none_when_no_row():
    """If the DB has no row for the ticker, get_cached_latest must
    return None (it doesn't synthesize anything)."""
    from backend.services import analysis_cache_service

    class _EmptySess:
        def execute(self, *args, **kwargs):
            class _Res:
                @staticmethod
                def fetchone():
                    return None
            return _Res()

        def close(self):
            pass

    with patch.object(
        analysis_cache_service, "_get_session", return_value=_EmptySess()
    ):
        out = analysis_cache_service.get_cached_latest("NONEXISTENT.NS")

    assert out is None


def test_get_cached_latest_returns_none_when_no_session():
    """When DATABASE_URL is unset (_get_session returns None),
    get_cached_latest must degrade to None — never raise."""
    from backend.services import analysis_cache_service

    with patch.object(
        analysis_cache_service, "_get_session", return_value=None
    ):
        out = analysis_cache_service.get_cached_latest("TCS.NS")

    assert out is None


# ─── 3. Aggregator populates rows post-fix ────────────────────────


def test_sector_aggregator_populates_tickers_when_cache_has_rows(client):
    """Regression test for the Day-110a empty-cohort bug.

    With the IT-services cohort fully populated in
    analysis_cache_service.get_cached_latest, the endpoint must
    return ticker_count=5 (not 0). Pre-fix this returned 0 because
    the aggregator called get_cached() with no fields_needed and
    the wildcard manifest entry invalidated every cohort row."""
    from backend.services.cache_service import cache as _cache
    _cache.delete("public:sector-page:v1:it-services")

    fake_cache = {
        "TCS.NS":     _payload("TCS.NS",     fv=4200, price=3850),
        "INFY.NS":    _payload("INFY.NS",    fv=1800, price=1600),
        "WIPRO.NS":   _payload("WIPRO.NS",   fv=550,  price=520),
        "HCLTECH.NS": _payload("HCLTECH.NS", fv=1700, price=1600),
        "TECHM.NS":   _payload("TECHM.NS",   fv=1600, price=1700),
    }

    def _fake(ticker, **_kw):
        return fake_cache.get(ticker)

    with patch(
        "backend.services.analysis_cache_service.get_cached_latest",
        side_effect=_fake,
    ):
        res = client.get("/api/v1/public/sector/it-services")

    assert res.status_code == 200
    body = res.json()
    assert body["aggregates"]["ticker_count"] == 5, body
    assert len(body["tickers"]) == 5


# ─── 4. Aggregator skips tickers with no row, doesn't break ───────


def test_sector_aggregator_skips_tickers_with_no_row(client):
    """Partial cohort: 3 of 5 tickers have cache rows, 2 don't.
    The aggregator should serve a 3-row payload, not crash, not
    return 0."""
    from backend.services.cache_service import cache as _cache
    _cache.delete("public:sector-page:v1:it-services")

    fake_cache = {
        "TCS.NS":   _payload("TCS.NS",   fv=4200, price=3850),
        "INFY.NS":  _payload("INFY.NS",  fv=1800, price=1600),
        "WIPRO.NS": _payload("WIPRO.NS", fv=550,  price=520),
        # HCLTECH.NS, TECHM.NS intentionally omitted.
    }

    def _fake(ticker, **_kw):
        return fake_cache.get(ticker)

    with patch(
        "backend.services.analysis_cache_service.get_cached_latest",
        side_effect=_fake,
    ):
        res = client.get("/api/v1/public/sector/it-services")

    assert res.status_code == 200
    body = res.json()
    assert body["aggregates"]["ticker_count"] == 3
    assert len(body["tickers"]) == 3
    # Cohort tickers list still shows all 5 (intended).
    assert len(body["cohort_tickers"]) == 5


# ─── 5. Manifest semantics for regular get_cached unchanged ───────


def test_regular_get_cached_still_respects_manifest():
    """Sanity: the Day-110a PR did NOT change is_row_valid_per_manifest
    behavior. A pre-anchor row passed to get_cached() with no
    fields_needed must still be treated as invalid (manifest match)."""
    from backend.services.cache_invalidation_manifest import (
        is_row_valid_per_manifest,
    )

    pre_anchor = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    # No fields_needed → worst-case (any field matters) → wildcard
    # entry applies → row is invalid.
    assert is_row_valid_per_manifest(
        ticker="TCS.NS", computed_at=pre_anchor, fields_needed=None,
    ) is False


def test_get_cached_latest_in_module_exports():
    """get_cached_latest must be in __all__ so callers can import it
    cleanly without reaching into the module."""
    from backend.services import analysis_cache_service
    assert "get_cached_latest" in analysis_cache_service.__all__
