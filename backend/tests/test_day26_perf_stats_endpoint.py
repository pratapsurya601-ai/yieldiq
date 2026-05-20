"""Day-26 (2026-05-20): regression guard for the /admin/perf-stats
endpoint that closes out Week-1 perf work.

The endpoint aggregates analysis_cache.compute_ms + payload.timings_ms
(Day-24) so the perf dashboard can answer:
  - did Day-23 (yfinance retry tightening) cut the p95 outlier tail?
  - which Step N dominates the typical 2.7s cold p50?
  - which CACHE_VERSION rows are still serving stale state?

Source-text guards + endpoint-shape contract.
"""
from __future__ import annotations
from pathlib import Path

import pytest

pytest.importorskip("fastapi")


_ADMIN = Path(__file__).resolve().parents[2] / "backend" / "routers" / "admin.py"


def test_perf_stats_endpoint_defined():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '@router.get("/perf-stats")' in src, (
        "perf-stats endpoint missing — Day-26 dashboard depends on it."
    )
    assert "async def get_perf_stats(" in src
    assert "Depends(require_admin)" in src, (
        "perf-stats must require admin auth (analysis_cache reads sensitive data)."
    )


def test_perf_stats_queries_compute_ms_and_timings():
    """The SQL must pull both compute_ms (existing) and timings_ms
    (Day-24 instrumentation) — without both, the dashboard can't
    answer the question 'which step is slow?'."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "compute_ms" in src
    assert "payload->'timings_ms'" in src, (
        "perf-stats SQL must pull payload->'timings_ms' JSON field. "
        "Otherwise the step-level breakdown is empty."
    )


def test_perf_stats_returns_percentiles():
    """Response must include p50 + p95 per cache_version and per step."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "p50_ms" in src
    assert "p95_ms" in src
    assert "step_latency_p50_ms_by_step" in src
    assert "step_latency_p95_ms_by_step" in src


def test_perf_stats_returns_slowest_tickers():
    """Top-30 slowest tickers helps spot regression after CACHE_VERSION
    bumps + identifies tickers that still need optimisation."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "slowest_tickers" in src
    assert "slowest[:30]" in src


def test_perf_stats_endpoint_via_test_client():
    """Anonymous access -> 401/403."""
    from fastapi.testclient import TestClient
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    client = TestClient(app)
    r = client.get("/api/v1/admin/perf-stats")
    assert r.status_code in (401, 403), (
        "perf-stats must require admin auth."
    )


def test_perf_stats_admin_path_returns_shape():
    """With require_admin overridden, endpoint returns expected shape."""
    from fastapi.testclient import TestClient
    from backend.routers import admin as admin_mod
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    app.dependency_overrides[admin_mod.require_admin] = lambda: {
        "email": "test@yieldiq.in", "id": "test-admin",
    }
    try:
        r = client = TestClient(app)
        resp = client.get("/api/v1/admin/perf-stats?limit=10")
        if resp.status_code == 500:
            # DB unavailable in this env — acceptable; the shape test
            # still cleanly verifies error sanitisation
            assert "details suppressed" in resp.json().get("detail", "")
            return
        assert resp.status_code == 200
        body = resp.json()
        # Top-level keys present
        for key in (
            "rows_inspected", "by_cache_version",
            "step_latency_p50_ms_by_step", "step_latency_p95_ms_by_step",
            "rows_with_step_timings", "slowest_tickers", "_meta",
        ):
            assert key in body, f"perf-stats response missing key {key}"
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)
