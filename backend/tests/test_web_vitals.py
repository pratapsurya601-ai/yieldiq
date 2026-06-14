"""Real-user Core Web Vitals (RUM) ingest + summary (2026-06-14).

Locks the contract on the web-vitals beacon endpoints:

  1. POST /api/v1/telemetry/web-vital accepts a batch of metrics and
     returns {"ok": true}. It is fire-and-forget from sendBeacon, so it
     must never 500 — garbage / NaN / out-of-range values are dropped in
     persistence, not surfaced as an error.
  2. The metric-name whitelist is enforced by Pydantic's Literal: an
     unknown metric name 422s before it can reach the table.
  3. The pure helpers — band classification against Google's p75
     thresholds, path sanitization, device bucketing — behave as the
     /admin/web-vitals summary depends on.

No DB is configured under test, so _get_session() returns None and the
persist path is a verified no-op; we assert the public contract and the
helpers rather than round-tripping rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import telemetry as telemetry_router  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(telemetry_router.router)
    return TestClient(app)


# ── POST /web-vital contract ─────────────────────────────────────


def test_valid_batch_accepted(client: TestClient) -> None:
    r = client.post(
        "/api/v1/telemetry/web-vital",
        json={
            "metrics": [
                {"name": "LCP", "value": 1234.5, "rating": "good"},
                {"name": "CLS", "value": 0.02, "rating": "good"},
                {"name": "INP", "value": 180, "rating": "good"},
                {"name": "TTFB", "value": 45.2, "rating": "good"},
                {"name": "FCP", "value": 900, "rating": "good"},
            ],
            "path": "/analysis/[ticker]",
            "nav_type": "navigate",
            "conn": "4g",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_empty_batch_accepted(client: TestClient) -> None:
    # A page hidden before any metric resolved still beacons {metrics:[]}.
    r = client.post("/api/v1/telemetry/web-vital", json={"metrics": []})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_unknown_metric_name_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/telemetry/web-vital",
        json={"metrics": [{"name": "GARBAGE", "value": 1.0}]},
    )
    assert r.status_code == 422


def test_garbage_values_do_not_500(client: TestClient) -> None:
    # Negative, absurd, and NaN-ish values are dropped in persistence; the
    # endpoint still acknowledges so a hostile client can't break unload.
    r = client.post(
        "/api/v1/telemetry/web-vital",
        json={
            "metrics": [
                {"name": "LCP", "value": -5},
                {"name": "INP", "value": 1e12},
                {"name": "CLS", "value": 999},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_rating_optional(client: TestClient) -> None:
    r = client.post(
        "/api/v1/telemetry/web-vital",
        json={"metrics": [{"name": "LCP", "value": 1500}]},
    )
    assert r.status_code == 200


# ── pure helpers the admin summary relies on ─────────────────────


def test_cwv_band_thresholds() -> None:
    band = telemetry_router._cwv_band
    # LCP: good <= 2500, needs <= 4000, else poor.
    assert band("LCP", 2000) == "good"
    assert band("LCP", 2500) == "good"
    assert band("LCP", 3000) == "needs-improvement"
    assert band("LCP", 5000) == "poor"
    # CLS uses the unitless scale.
    assert band("CLS", 0.05) == "good"
    assert band("CLS", 0.2) == "needs-improvement"
    assert band("CLS", 0.5) == "poor"
    # Unknown metric / missing p75 -> None.
    assert band("LCP", None) is None
    assert band("NONSENSE", 1.0) is None


def test_sanitize_path_strips_query_and_caps() -> None:
    san = telemetry_router._sanitize_path
    assert san("/funds/[scheme]?q=hdfc") == "/funds/[scheme]"
    assert san("/analysis/[ticker]#hero") == "/analysis/[ticker]"
    assert san(None) is None
    assert san("") is None
    assert len(san("/" + "a" * 500)) == 120


def test_device_from_ua_buckets() -> None:
    dev = telemetry_router._device_from_ua
    assert dev("Mozilla/5.0 (iPhone; ... Mobile/15E148") == "mobile"
    assert dev("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "desktop"
    assert dev(None) == "desktop"


def test_persist_web_vitals_noop_without_db() -> None:
    # No DATABASE_URL under test -> _get_session() is None -> best-effort
    # persist returns without raising. This guards the never-raises promise.
    batch = telemetry_router.WebVitalsBatch(
        metrics=[telemetry_router.WebVitalItem(name="LCP", value=1200.0)]
    )
    telemetry_router._persist_web_vitals(batch, "desktop", None)
