"""Tests for backend/routers/public_stats.py.

Covers:

* Endpoint returns 200 + omits keys when the underlying counter
  cannot be resolved (a missing key is the "hide that tile" signal
  the frontend depends on — never emit 0).
* When all sources are populated, every documented key is present
  and is the correct shape (int counts, list of strings for sources,
  ISO-8601 string for timestamps, 0-100 int for percent).
* Cache hit on second call returns the same payload and the
  X-Cache header flips MISS -> HIT.
* Manifest read picks the MAX applied_at across entries (not the
  first or last in source order).

Uses a minimal stub for the SQLAlchemy session so the test never
needs Aiven. The manifest read is exercised against the real
backend.services.cache_invalidation_manifest module — we only
monkeypatch when asserting the max-selection invariant.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import public_stats  # noqa: E402
from backend.services.cache_service import cache as _cache  # noqa: E402


# ── Test doubles ─────────────────────────────────────────────────

class _StubResult:
    def __init__(self, value: Any):
        self._value = value

    def fetchone(self):
        if self._value is None:
            return None
        return (self._value,)


class _StubSession:
    """In-memory replacement for the SQLAlchemy pipeline session.

    `responses` is an ORDERED dict of substring → scalar value. The
    FIRST matching substring wins, so unique substrings (e.g.
    "COUNT(DISTINCT sector)") must precede broader ones (e.g.
    "FROM stocks") to avoid ambiguous matches.
    """

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.closed = False

    def execute(self, statement):
        sql = str(statement)
        for needle, value in self.responses.items():
            if needle in sql:
                return _StubResult(value)
        return _StubResult(None)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_cache():
    """Endpoint memoises into the process-wide cache singleton; clear
    it between tests so cache_hit doesn't leak across cases."""
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
    app.include_router(public_stats.router)
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────


def test_endpoint_returns_200_and_omits_missing_counters(
    client, monkeypatch
):
    """When the DB session can't be acquired AND the logo dir is
    inaccessible, the endpoint must still respond 200 with the
    keys that can be produced from in-process data (manifest +
    data_sources + as_of). NO key may be emitted with a 0 / null
    placeholder — missing-means-hide is the contract."""
    monkeypatch.setattr(
        public_stats, "_get_pipeline_session", lambda: None
    )
    monkeypatch.setattr(
        public_stats, "_logo_coverage_pct", lambda: None
    )

    r = client.get("/api/v1/public/coverage-stats")
    assert r.status_code == 200, r.text
    body = r.json()

    # Always-present keys.
    assert "as_of" in body
    assert body["data_sources"] == ["BSE XBRL", "NSE", "yfinance"]

    # DB-sourced keys must be absent (NOT zero) when the session is down.
    assert "stocks_covered" not in body
    assert "dcf_valuations_generated" not in body
    assert "sectors_covered" not in body
    assert "bank_quarters_backfilled" not in body
    assert "nifty500_logo_coverage_pct" not in body


def test_endpoint_returns_all_keys_when_sources_populated(
    client, monkeypatch
):
    """Happy path — every counter resolves, response carries every
    documented key with the right type."""
    # NOTE: order matters — more-specific patterns first.
    stub = _StubSession({
        "COUNT(DISTINCT sector) FROM stocks":             18,
        "COUNT(*) FROM stocks WHERE is_active = TRUE":    5247,
        "FROM analysis_cache":                            12483,
        "FROM financials WHERE period_type = 'quarterly'": 174,
    })
    monkeypatch.setattr(
        public_stats, "_get_pipeline_session", lambda: stub
    )
    monkeypatch.setattr(public_stats, "_logo_coverage_pct", lambda: 95)
    monkeypatch.setattr(
        public_stats, "_latest_manifest_applied_at",
        lambda: "2026-06-07T12:00:00+00:00",
    )

    r = client.get("/api/v1/public/coverage-stats")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["stocks_covered"] == 5247
    assert body["dcf_valuations_generated"] == 12483
    assert body["sectors_covered"] == 18
    assert body["bank_quarters_backfilled"] == 174
    assert body["nifty500_logo_coverage_pct"] == 95
    assert body["last_engine_update"] == "2026-06-07T12:00:00+00:00"
    assert body["data_sources"] == ["BSE XBRL", "NSE", "yfinance"]

    # Types — these are what the TypeScript client expects.
    assert isinstance(body["stocks_covered"], int)
    assert isinstance(body["nifty500_logo_coverage_pct"], int)
    assert 0 <= body["nifty500_logo_coverage_pct"] <= 100
    assert isinstance(body["data_sources"], list)
    # session must have been closed
    assert stub.closed is True


def test_zero_counters_are_omitted_not_emitted_as_zero(
    client, monkeypatch
):
    """If a COUNT returns 0 (table exists but is empty), the field
    is omitted. A "0 stocks covered" tile would look broken on the
    landing page; the frontend strip hides any tile whose value is
    missing."""
    stub = _StubSession({
        "COUNT(DISTINCT sector) FROM stocks":             0,
        "COUNT(*) FROM stocks WHERE is_active = TRUE":    0,
        "FROM analysis_cache":                            0,
        "FROM financials WHERE period_type = 'quarterly'": 0,
    })
    monkeypatch.setattr(
        public_stats, "_get_pipeline_session", lambda: stub
    )
    monkeypatch.setattr(public_stats, "_logo_coverage_pct", lambda: 0)
    monkeypatch.setattr(
        public_stats, "_latest_manifest_applied_at", lambda: None
    )

    r = client.get("/api/v1/public/coverage-stats")
    body = r.json()
    assert "stocks_covered" not in body
    assert "dcf_valuations_generated" not in body
    assert "sectors_covered" not in body
    assert "bank_quarters_backfilled" not in body
    assert "nifty500_logo_coverage_pct" not in body
    assert "last_engine_update" not in body


def test_cache_hit_short_circuits_second_call(client, monkeypatch):
    """Second call within TTL must read from cache (X-Cache: HIT) and
    must NOT re-open a DB session."""
    call_count = {"n": 0}

    def _counting_session():
        call_count["n"] += 1
        return _StubSession({
            "FROM stocks WHERE is_active = TRUE": 100,
        })

    monkeypatch.setattr(
        public_stats, "_get_pipeline_session", _counting_session
    )
    monkeypatch.setattr(public_stats, "_logo_coverage_pct", lambda: 90)
    monkeypatch.setattr(
        public_stats, "_latest_manifest_applied_at",
        lambda: "2026-06-07T12:00:00+00:00",
    )

    r1 = client.get("/api/v1/public/coverage-stats")
    assert r1.headers.get("x-cache") == "MISS"
    assert call_count["n"] == 1

    r2 = client.get("/api/v1/public/coverage-stats")
    assert r2.headers.get("x-cache") == "HIT"
    # No new DB session opened on the cached path.
    assert call_count["n"] == 1
    # Payload identity preserved.
    assert r2.json() == r1.json()


def test_latest_manifest_applied_at_picks_max(monkeypatch):
    """The helper must return the latest applied_at across all
    entries — not the first, not the last in source-order."""
    from backend.services import cache_invalidation_manifest as m

    fake = [
        {"applied_at": datetime(2024, 1, 1, tzinfo=timezone.utc)},
        {"applied_at": datetime(2026, 6, 7, 12, tzinfo=timezone.utc)},
        {"applied_at": datetime(2025, 5, 1, tzinfo=timezone.utc)},
    ]
    monkeypatch.setattr(m, "MANIFEST", fake)
    out = public_stats._latest_manifest_applied_at()
    assert out is not None
    assert "2026-06-07" in out


def test_manifest_handles_missing_entries(monkeypatch):
    """Empty manifest list → None; the endpoint will omit the key."""
    from backend.services import cache_invalidation_manifest as m
    monkeypatch.setattr(m, "MANIFEST", [])
    assert public_stats._latest_manifest_applied_at() is None


def test_logo_coverage_returns_none_when_data_absent(tmp_path, monkeypatch):
    """If the curated JSON is missing, helper returns None — never 0 —
    so the frontend hides the logo tile instead of showing 0%."""
    # Force a path that doesn't exist by chdir-ing into an isolated tmp.
    monkeypatch.setattr(
        public_stats.os.path, "exists", lambda p: False
    )
    assert public_stats._logo_coverage_pct() is None
