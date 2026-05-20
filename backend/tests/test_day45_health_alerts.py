"""Day-45 (2026-05-20): /admin/health-alerts threshold checker +
hourly GH Actions cron."""
from __future__ import annotations
from pathlib import Path

import pytest


_ADMIN = Path(__file__).resolve().parents[2] / "backend" / "routers" / "admin.py"
_WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github" / "workflows" / "health_alerts_hourly.yml"
)


# ── Endpoint structure ──────────────────────────────────────


def test_health_alerts_endpoint_defined():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '@router.get("/health-alerts")' in src
    assert "async def get_health_alerts(" in src
    assert "Depends(require_admin)" in src


def test_health_alerts_reuses_health_stats():
    """No drift between the two endpoints — alerts builds on stats."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "stats = await get_health_stats(user=user)" in src


def test_thresholds_documented_in_comment_block():
    """The threshold table must be visible in source so any operator
    reading the code can see what's tracked + why."""
    src = _ADMIN.read_text(encoding="utf-8")
    threshold_block_idx = src.find("Day-45 (2026-05-20)")
    assert threshold_block_idx > 0
    block = src[threshold_block_idx:threshold_block_idx + 2000]
    # Each metric must be mentioned in the comment header
    assert "warm_coverage_pct" in block
    assert "p95_latency_ms" in block
    assert "drift_gt_30pct" in block
    assert "fv_eq_zero_now" in block
    assert "rescue_rate_24h" in block


def test_alert_levels_are_two_tier():
    """Each metric has TWO thresholds — warn + alert. Catches the
    regression where someone ships a single-threshold check that
    pages on every minor blip OR misses serious incidents."""
    src = _ADMIN.read_text(encoding="utf-8")
    # Warm coverage has both 0.20 (alert) and 0.50 (warn)
    assert "if wc < 0.20:" in src
    assert "elif wc < 0.50:" in src
    # Latency has 20000 (alert) and 8000 (warn)
    assert "if ms > 20000:" in src
    assert "elif ms > 8000:" in src
    # Story-DCF has 0.02 (alert) and 0.10 (warn)
    assert "if rescue < 0.02:" in src
    assert "elif rescue < 0.10:" in src


def test_overall_status_picks_highest_severity():
    """status should be 'alert' if ANY breach is alert-level,
    otherwise 'warn' if any breach is warn-level, otherwise 'ok'."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert 'status = "ok"' in src
    assert 'status = "alert"' in src
    assert 'status = "warn"' in src


# ── GH Actions workflow ─────────────────────────────────────


def test_workflow_runs_hourly():
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "0 * * * *"' in src, "Workflow should run every hour."


def test_workflow_manual_dispatch_enabled():
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src


def test_workflow_skips_when_token_missing():
    """The token-check step lets the workflow exit gracefully when
    SERVICE_WARMUP_TOKEN is unset (e.g. forks, local-only deploys)."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "SERVICE_WARMUP_TOKEN" in src
    assert "skip=true" in src


def test_workflow_emits_github_annotations_per_breach():
    """Operator sees each breach as a GH Actions error/warning
    annotation in the run log, not just a buried JSON dump."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "::error::" in src
    assert "::warning::" in src


def test_workflow_only_fails_on_alert_not_warn():
    """warns accumulate; we only page on alert. Otherwise on-call
    sleep would be ruined by any minor drift."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert 'if [ "$STATUS" = "alert" ]; then' in src
    assert "exit 1" in src
