"""Day-44 (2026-05-20): /admin/health-stats observability endpoint.

Single-glance ops dashboard JSON. Aggregates:
  - Cache warm-coverage at current CACHE_VERSION
  - p95 latency per engine (last 500 cold computes)
  - Outlier count (drift > 30% vs consensus + FV=0 count)
  - Story-DCF rescue rate over the last 24h
"""
from __future__ import annotations
from pathlib import Path

import pytest


_ADMIN = Path(__file__).resolve().parents[2] / "backend" / "routers" / "admin.py"


# ── Endpoint defined + auth-gated (source-grep — no fastapi needed) ──


def test_health_stats_endpoint_defined():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '@router.get("/health-stats")' in src
    assert "async def get_health_stats(" in src
    assert "Depends(require_admin)" in src


def test_health_stats_requires_auth_via_test_client():
    """Wire-up test — needs fastapi. Local skip OK; CI runs."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    client = TestClient(app)
    r = client.get("/api/v1/admin/health-stats")
    assert r.status_code in (401, 403)


# ── Response shape ───────────────────────────────────────────


def test_health_stats_response_has_required_top_level_keys():
    """Code-level check on the return dict structure — verifies
    all 5 top-level keys exist in the source."""
    src = _ADMIN.read_text(encoding="utf-8")
    # The return statement at the end of get_health_stats
    for key in ("as_of", "cache", "latency", "outliers", "story_dcf", "_meta"):
        assert f'"{key}":' in src, f"Response key '{key}' missing"


def test_health_stats_cache_block_includes_warm_coverage():
    """warm_coverage_pct is the key proxy metric for whether the
    Day-25 auto-trigger has done its job after a CACHE_VERSION bump."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert '"warm_coverage_pct"' in src
    assert "warm_coverage = round(current_v_rows / total_rows, 3)" in src


def test_health_stats_latency_groups_by_engine():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '"by_engine_p95_ms"' in src
    assert "valuation_engine_used" in src
    assert "_p95" in src


def test_health_stats_outliers_count_drift_and_fv_zero():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '"drift_gt_30pct_now"' in src
    assert '"fv_eq_zero_now"' in src
    # Joining with consensus_estimates to compute drift
    assert "consensus_estimates" in src
    assert "ABS(fv - cons) / cons > 0.30" in src


def test_health_stats_story_dcf_rescue_rate():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '"rescue_rate_24h"' in src
    assert "story_dcf_after_dcf_collapse" in src
    # Attempted = data_issues mentions dcf_collapse
    assert "dcf_collapse" in src


def test_health_stats_only_counts_current_cache_version():
    """Critical: outlier + latency stats must be SCOPED to the current
    CACHE_VERSION rows. Mixing old + new versions would muddy the
    post-bump validation. The endpoint queries with `cv_str` filter."""
    src = _ADMIN.read_text(encoding="utf-8")
    # Verify cv_str = str(CACHE_VERSION) is used as a parameter
    assert "cv_str = str(CACHE_VERSION)" in src
    # SQL queries use :cv parameter
    assert "WHERE cache_version = :cv" in src


def test_health_stats_exception_path_sanitized():
    """Any exception falls back to _sanitize_error so secrets in
    error messages don't leak."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "_sanitize_error(exc, 'health-stats')" in src
