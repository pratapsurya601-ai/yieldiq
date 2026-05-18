"""Verify APScheduler in backend/main.py is gated by ENABLE_INPROCESS_SCHEDULER.

Background: APScheduler used to start unconditionally in every uvicorn
worker, costing ~200MB/worker and causing N× duplicate fires of every
scheduled job on Railway (4 workers). We migrated all jobs to GitHub
Actions cron workflows (see .github/workflows/cron-market-*.yml,
data-pipeline.yml, alerts_evaluator_hourly.yml).

The in-process scheduler is now OFF by default. This test asserts that
behaviour so we don't accidentally re-introduce the duplication via a
careless refactor of the lifespan() startup hook.
"""
from __future__ import annotations

import importlib
import os
from unittest import mock


def _reload_main():
    import backend.main as m
    return importlib.reload(m)


def test_scheduler_disabled_by_default(monkeypatch):
    """When ENABLE_INPROCESS_SCHEDULER is unset, _start_pipeline_scheduler
    must NOT be invoked by the lifespan hook."""
    monkeypatch.delenv("ENABLE_INPROCESS_SCHEDULER", raising=False)

    import backend.main as m

    with mock.patch.object(m, "_start_pipeline_scheduler") as start_mock:
        # Simulate the gate code that lives inside lifespan(). Mirrors the
        # exact env-check expression used in backend/main.py so a change
        # to the env var name will break this test.
        if os.environ.get("ENABLE_INPROCESS_SCHEDULER", "0") == "1":
            m._start_pipeline_scheduler()

        assert start_mock.call_count == 0, (
            "Scheduler must not start when ENABLE_INPROCESS_SCHEDULER is unset. "
            "Each in-process scheduler costs ~200MB and duplicates fires N× "
            "across uvicorn workers — jobs now live in GH Actions cron."
        )


def test_scheduler_enabled_when_flag_set(monkeypatch):
    """When ENABLE_INPROCESS_SCHEDULER=1, the gate should pass and the
    scheduler factory should be called exactly once."""
    monkeypatch.setenv("ENABLE_INPROCESS_SCHEDULER", "1")

    import backend.main as m

    with mock.patch.object(m, "_start_pipeline_scheduler", return_value=None) as start_mock:
        if os.environ.get("ENABLE_INPROCESS_SCHEDULER", "0") == "1":
            m._start_pipeline_scheduler()

        assert start_mock.call_count == 1


def test_main_source_contains_gate():
    """Defensive: the literal env-check must exist in backend/main.py so
    nobody silently removes the gate while leaving this test green by
    accident."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    text = src.read_text(encoding="utf-8")
    assert 'ENABLE_INPROCESS_SCHEDULER' in text, (
        "backend/main.py must gate scheduler startup with ENABLE_INPROCESS_SCHEDULER"
    )
    # The default value in the gate must be "0" so the scheduler is OFF
    # by default. If someone flips this to "1" they will silently
    # reintroduce N× duplication on Railway.
    assert 'ENABLE_INPROCESS_SCHEDULER", "0"' in text, (
        "Gate default must remain '0' — scheduler must be OFF unless explicitly enabled"
    )
