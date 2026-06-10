"""Smoke tests for backend.jobs.check_alerts_cron (task #131).

The DB-bound _resolve_mos_for_ticker hop is stubbed via monkeypatch
so the suite exercises the run() control flow without touching Neon
or pywebpush.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def cron_module(monkeypatch, tmp_path):
    """Reload service + cron under an isolated JSONL store."""
    monkeypatch.setenv(
        "MOS_BAND_ALERTS_PATH", str(tmp_path / "alerts.jsonl"),
    )
    import backend.services.mos_band_alerts_service as mbas
    import backend.jobs.check_alerts_cron as cron
    importlib.reload(mbas)
    importlib.reload(cron)
    # Stub the push sender so no socket is opened.
    monkeypatch.setattr(mbas, "_send_push_for_user", lambda *a, **kw: True)
    return cron, mbas


def test_cron_no_subs_is_clean(cron_module):
    cron, _mbas = cron_module
    summary = cron.run(dry_run=False)
    assert summary["tickers_checked"] == 0
    assert summary["fired_count"] == 0


def test_cron_dry_run_does_not_mutate(cron_module, monkeypatch):
    cron, mbas = cron_module
    mbas.create_subscription("u1", "TCS", 20.0, "positive")
    monkeypatch.setattr(cron, "_resolve_mos_for_ticker",
                        lambda t: 30.0)
    summary = cron.run(dry_run=True)
    assert summary["tickers_checked"] == 1
    assert summary["fired_count"] == 1
    # last_fired_at MUST stay None — dry_run is non-mutating.
    rows = mbas.list_subscriptions_for_user("u1")
    assert rows[0].last_fired_at is None


def test_cron_fires_when_condition_met(cron_module, monkeypatch):
    cron, mbas = cron_module
    mbas.create_subscription("u1", "RELIANCE", 20.0, "positive")
    monkeypatch.setattr(cron, "_resolve_mos_for_ticker",
                        lambda t: 25.0)
    summary = cron.run(dry_run=False)
    assert summary["fired_count"] == 1
    rows = mbas.list_subscriptions_for_user("u1")
    assert rows[0].last_fired_at is not None


def test_cron_skip_when_no_mos(cron_module, monkeypatch):
    cron, mbas = cron_module
    mbas.create_subscription("u1", "FOO", 10.0, "positive")
    monkeypatch.setattr(cron, "_resolve_mos_for_ticker", lambda t: None)
    summary = cron.run(dry_run=False)
    assert summary["tickers_no_data"] == 1
    assert summary["fired_count"] == 0


def test_cron_only_filter(cron_module, monkeypatch):
    cron, mbas = cron_module
    mbas.create_subscription("u1", "TCS", 10.0, "positive")
    mbas.create_subscription("u1", "INFY", 10.0, "positive")
    monkeypatch.setattr(cron, "_resolve_mos_for_ticker", lambda t: 20.0)
    summary = cron.run(dry_run=False, only=["TCS"])
    assert summary["tickers_checked"] == 1
    assert summary["fired_count"] == 1
    fired_tickers = {r["ticker"] for r in summary["fired"]}
    assert fired_tickers == {"TCS"}
