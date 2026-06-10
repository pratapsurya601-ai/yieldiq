"""Sector Heatmap Mini endpoint tests (2026-06-10).

Pins these behaviours for /api/v1/public/sector-heatmap/{ticker}:

  1. Route is registered on the public router and reachable via
     TestClient at the documented URL.
  2. Endpoint shape: emits {ticker, sector, subject_ticker, tiles,
     tile_count, caption} with each tile carrying the documented
     fields (ticker, name, market_cap_cr, mos_pct, fair_value,
     current_price, verdict, industry, is_subject).
  3. When the subject ticker is not in the top-N cohort rows, the
     endpoint still injects a subject tile so the frontend can
     highlight it.
  4. Returns the data-unavailable 503 shape when the pipeline DB
     session can't be obtained (mirrors other public endpoints).
  5. Manifest carries the v_sector_heatmap_2026_06_10 entry with
     scope.tickers="*" and scope.fields=[] so downstream cache
     gates don't invalidate anything as a side effect of this PR.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    from backend.main import app
    return TestClient(app)


class _FakeDBSession:
    """Tiny db-session fake exposing the .execute(...) / .first() /
    .fetchall() / .close() shape the endpoint reads. Each test
    instantiates with a queue of result rows in execute order."""

    def __init__(self, *, subject_row: Any, cohort_rows: list[Any]) -> None:
        self._subject_row = subject_row
        self._cohort_rows = cohort_rows
        self._call = 0

    def execute(self, _stmt, _params=None):
        self._call += 1
        if self._call == 1:
            # First execute = subject lookup (single row, .first()).
            return SimpleNamespace(first=lambda: self._subject_row)
        # Second execute = cohort query (.fetchall()).
        return SimpleNamespace(fetchall=lambda: self._cohort_rows)

    def close(self) -> None:
        pass


# ─── 1. Route registration ───────────────────────────────────────


def test_route_is_registered(client: TestClient) -> None:
    """The endpoint must show up in the FastAPI route table at the
    expected path. Catches the bog-standard typo where someone
    moves the @router.get above the prefix definition."""
    paths = {route.path for route in client.app.routes}  # type: ignore[attr-defined]
    assert "/api/v1/public/sector-heatmap/{ticker}" in paths


# ─── 2. Endpoint shape (happy path) ───────────────────────────────


def test_endpoint_returns_documented_shape(client: TestClient) -> None:
    """With a stubbed cohort (subject + 2 peers, varied MoS), the
    serializer must emit every documented field on every tile."""
    subject_row = ("Technology", "Computers - Software & Consulting", "IT Services")
    cohort_rows = [
        # (ticker, canonical_sector, sector, industry, market_cap_cr)
        ("TCS", "Technology", "Computers - Software & Consulting", "IT Services", 1_500_000.0),
        ("INFY", "Technology", "Computers - Software & Consulting", "IT Services", 720_000.0),
        ("WIPRO", "Technology", "Computers - Software & Consulting", "IT Services", 250_000.0),
    ]
    fake_db = _FakeDBSession(subject_row=subject_row, cohort_rows=cohort_rows)

    # Patch the cache so the cached path never short-circuits, and
    # patch the analysis_cache enricher so the endpoint runs without
    # a real analysis_cache_service.
    with patch("backend.routers.public._get_db_session", return_value=fake_db), \
         patch("backend.routers.public.cache") as cache_mock:
        cache_mock.get.return_value = None
        cache_mock.set.return_value = None
        resp = client.get("/api/v1/public/sector-heatmap/INFY")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["ticker"] == "INFY.NS"
    assert payload["sector"] == "Technology"
    assert payload["subject_ticker"] == "INFY"
    assert payload["tile_count"] == len(payload["tiles"])
    assert payload["tile_count"] >= 3
    assert payload["caption"] is not None

    documented_fields = {
        "ticker", "name", "market_cap_cr", "mos_pct",
        "fair_value", "current_price", "verdict",
        "industry", "is_subject",
    }
    for tile in payload["tiles"]:
        missing = documented_fields - set(tile.keys())
        assert not missing, f"tile missing fields {missing}: {tile}"

    # The subject ticker (INFY) must be exactly one tile flagged
    # is_subject=True.
    subjects = [t for t in payload["tiles"] if t.get("is_subject")]
    assert len(subjects) == 1
    assert subjects[0]["ticker"] == "INFY"


# ─── 3. Subject injection when off the top-N ──────────────────────


def test_subject_is_injected_when_not_in_top_n(client: TestClient) -> None:
    """If the cohort SQL returns only peers (subject not in the
    top-N by mcap), the endpoint must inject a minimal subject
    tile so the frontend can still highlight it."""
    subject_row = ("FMCG", "FMCG", "FMCG Cigarettes")
    cohort_rows = [
        # Subject DABUR intentionally not in the rows — only top
        # mega-caps surfaced via the SQL.
        ("HINDUNILVR", "FMCG", "FMCG", "FMCG Personal Care", 600_000.0),
        ("ITC", "FMCG", "FMCG", "FMCG Cigarettes", 540_000.0),
        ("NESTLEIND", "FMCG", "FMCG", "FMCG Food", 230_000.0),
    ]
    fake_db = _FakeDBSession(subject_row=subject_row, cohort_rows=cohort_rows)
    with patch("backend.routers.public._get_db_session", return_value=fake_db), \
         patch("backend.routers.public.cache") as cache_mock:
        cache_mock.get.return_value = None
        cache_mock.set.return_value = None
        resp = client.get("/api/v1/public/sector-heatmap/DABUR")

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    tickers = [t["ticker"] for t in payload["tiles"]]
    assert "DABUR" in tickers
    subjects = [t for t in payload["tiles"] if t.get("is_subject")]
    assert len(subjects) == 1
    assert subjects[0]["ticker"] == "DABUR"
    # The injected tile has null mcap (we never pretend to know it
    # without a row in market_metrics).
    assert subjects[0]["market_cap_cr"] is None


# ─── 4. DB unavailable → 503 with stable shape ────────────────────


def test_db_unavailable_returns_503(client: TestClient) -> None:
    """When _get_db_session returns None (Aiven Postgres down,
    connection-string missing in CI), the endpoint must return
    the documented 503 'data_not_populated' shape so the frontend
    can branch consistently."""
    with patch("backend.routers.public._get_db_session", return_value=None), \
         patch("backend.routers.public.cache") as cache_mock:
        cache_mock.get.return_value = None
        resp = client.get("/api/v1/public/sector-heatmap/INFY")
    assert resp.status_code == 503
    body = resp.json()
    assert body.get("status") == "data_not_populated"
    assert body.get("ticker") == "INFY.NS"
    assert body.get("reason") == "db_session_unavailable"


# ─── 5. Manifest entry present ────────────────────────────────────


def test_manifest_has_sector_heatmap_entry() -> None:
    from backend.services.cache_invalidation_manifest import MANIFEST
    ids = [e.get("version_id") for e in MANIFEST]
    assert "v_sector_heatmap_2026_06_10" in ids
    entry = next(
        e for e in MANIFEST
        if e["version_id"] == "v_sector_heatmap_2026_06_10"
    )
    # Read-only additive endpoint: scope.tickers="*" but scope.fields=[]
    # so the manifest gates DON'T invalidate any cached field.
    assert entry["scope"]["tickers"] == "*"
    assert entry["scope"]["fields"] == []


# ─── 6. Source-text guard — endpoint stays cache-wrapped ──────────


def test_source_uses_cache_helpers() -> None:
    """Belt-and-braces: the endpoint MUST go through cache.get +
    cache.set + _cached_json so its TTL and edge headers stay in
    line with the other public endpoints. A future refactor that
    drops these by accident would cause a Railway cost spike."""
    import backend.routers.public as pub_mod
    src = Path(pub_mod.__file__).read_text(encoding="utf-8")
    assert "/sector-heatmap/{ticker}" in src
    assert "public:sector-heatmap:" in src
    assert "_SECTOR_HEATMAP_CACHE_TTL" in src
