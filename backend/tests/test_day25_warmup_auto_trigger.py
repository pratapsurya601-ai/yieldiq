"""Day-25 (2026-05-20): regression guard — cache_warmup_top500.yml
must auto-trigger on push to main when cache_service.py changes.

Days 14-21 bumped CACHE_VERSION 7 times. Each bump invalidates the
warm-cache. Without an auto-trigger, the next scheduled warmup (3x
weekday) can be 4-12h away — all top-500 tickers serve cold-compute
during that window (~2.7s p50).
"""
from __future__ import annotations
from pathlib import Path


_WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github" / "workflows" / "cache_warmup_top500.yml"
)


def test_warmup_has_push_trigger():
    """The workflow must include a `push` trigger so it fires when
    CACHE_VERSION bumps land on main."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in src, (
        "cache_warmup_top500.yml missing `push` trigger. Day-25 fix."
    )


def test_warmup_push_trigger_filtered_to_cache_service():
    """The push trigger must filter to cache_service.py — otherwise
    EVERY merge to main would fire a 21-minute warmup (wasteful)."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "paths:" in src
    assert "backend/services/cache_service.py" in src, (
        "Push trigger path-filter missing or wrong file. Must be "
        "backend/services/cache_service.py (the file that holds "
        "CACHE_VERSION)."
    )


def test_warmup_push_trigger_branches_main():
    """Only main pushes (not feature branches) should trigger warmup."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in src or "branches:\n      - main" in src, (
        "Push trigger should filter to branches: [main] only."
    )


def test_warmup_schedule_trigger_preserved():
    """The 3x weekday schedule must still be present alongside the
    new push trigger — both are needed (push catches CACHE_VERSION
    bumps; schedule catches data-pipeline drift)."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    # All 3 cron entries should still be present
    assert 'cron: "45 2 * * 1-5"' in src
    assert 'cron: "30 7 * * 1-5"' in src
    assert 'cron: "15 11 * * 1-5"' in src


def test_warmup_workflow_dispatch_preserved():
    """The manual trigger must still work (we used it during Day-22
    debugging via gh run rerun)."""
    src = _WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in src
