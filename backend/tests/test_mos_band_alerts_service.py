"""Unit tests for mos_band_alerts_service (task #131).

Covers:
  Storage round-trip
    - create then list returns the row
    - duplicate create is idempotent (key collision returns existing)
    - delete removes the row, returns False when nothing to remove
  Validation
    - threshold outside [-50, +50] raises
    - bad direction raises
  Condition + cooldown
    - _condition_met direction semantics
    - _in_cooldown True inside 24h, False outside
  Firing
    - check_and_fire_alerts fires for matching subs, stamps last_fired_at
    - cooldown'd subs are not refired
    - no-data ticker returns empty list

The push delivery path is stubbed via monkeypatch so the suite never
opens a network socket.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Force the JSONL store to a per-test temp file BEFORE we import the
# service module so the singleton path resolver picks it up.
@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    path = tmp_path / "alerts.jsonl"
    monkeypatch.setenv("MOS_BAND_ALERTS_PATH", str(path))
    # Reload the module so the path env var is honoured by the new
    # _LOCK + cache-free code paths. Service has no module-level path
    # cache today, so a plain import is fine.
    import importlib
    import backend.services.mos_band_alerts_service as mbas  # noqa
    importlib.reload(mbas)
    yield mbas


def test_get_alert_storage_path_honors_env(_isolated_store, tmp_path):
    mbas = _isolated_store
    assert mbas.get_alert_storage_path().endswith("alerts.jsonl")


def test_create_then_list_roundtrip(_isolated_store):
    mbas = _isolated_store
    sub = mbas.create_subscription("u1", "RELIANCE", 20.0, "positive")
    assert sub.user_id == "u1"
    assert sub.ticker == "RELIANCE"
    assert sub.threshold_pct == 20.0
    assert sub.direction == "positive"
    rows = mbas.list_subscriptions_for_user("u1")
    assert len(rows) == 1
    assert rows[0].ticker == "RELIANCE"


def test_create_is_idempotent(_isolated_store):
    mbas = _isolated_store
    a = mbas.create_subscription("u1", "TCS", 30.0, "positive")
    b = mbas.create_subscription("u1", "TCS", 30.0, "positive")
    assert a.key() == b.key()
    assert len(mbas.list_subscriptions_for_user("u1")) == 1


def test_list_by_ticker_filters(_isolated_store):
    mbas = _isolated_store
    mbas.create_subscription("u1", "RELIANCE", 10.0, "positive")
    mbas.create_subscription("u2", "RELIANCE", 20.0, "negative")
    mbas.create_subscription("u1", "TCS", 15.0, "positive")
    by_t = mbas.list_subscriptions_for_ticker("RELIANCE")
    assert len(by_t) == 2
    assert {s.user_id for s in by_t} == {"u1", "u2"}


def test_delete_subscription(_isolated_store):
    mbas = _isolated_store
    mbas.create_subscription("u1", "INFY", 25.0, "positive")
    assert mbas.delete_subscription("u1", "INFY", 25.0, "positive") is True
    assert mbas.delete_subscription("u1", "INFY", 25.0, "positive") is False
    assert mbas.list_subscriptions_for_user("u1") == []


def test_validate_threshold_range(_isolated_store):
    mbas = _isolated_store
    with pytest.raises(ValueError):
        mbas.create_subscription("u1", "ACC", 75.0, "positive")
    with pytest.raises(ValueError):
        mbas.create_subscription("u1", "ACC", -75.0, "negative")


def test_validate_direction(_isolated_store):
    mbas = _isolated_store
    with pytest.raises(ValueError):
        mbas.create_subscription("u1", "ACC", 10.0, "sideways")


def test_condition_met_positive(_isolated_store):
    mbas = _isolated_store
    sub = mbas.AlertSubscription("u1", "X", 20.0, "positive")
    assert mbas._condition_met(sub, 25.0) is True
    assert mbas._condition_met(sub, 20.0) is True   # boundary
    assert mbas._condition_met(sub, 19.9) is False


def test_condition_met_negative(_isolated_store):
    mbas = _isolated_store
    sub = mbas.AlertSubscription("u1", "X", -10.0, "negative")
    assert mbas._condition_met(sub, -15.0) is True
    assert mbas._condition_met(sub, -10.0) is True  # boundary
    assert mbas._condition_met(sub, -9.9) is False


def test_in_cooldown_inside_24h(_isolated_store):
    mbas = _isolated_store
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    assert mbas._in_cooldown(recent) is True
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    assert mbas._in_cooldown(old) is False
    assert mbas._in_cooldown(None) is False


def test_check_and_fire_fires_matching(_isolated_store, monkeypatch):
    mbas = _isolated_store
    # Stub the push sender so we don't open a network socket.
    monkeypatch.setattr(mbas, "_send_push_for_user",
                        lambda *a, **kw: True)
    mbas.create_subscription("u1", "TCS", 20.0, "positive")
    fired = mbas.check_and_fire_alerts("TCS", 25.0)
    assert len(fired) == 1
    assert fired[0].user_id == "u1"
    # Cooldown stamped — second call within the window does nothing.
    again = mbas.check_and_fire_alerts("TCS", 25.0)
    assert again == []


def test_check_and_fire_skips_condition_not_met(_isolated_store, monkeypatch):
    mbas = _isolated_store
    monkeypatch.setattr(mbas, "_send_push_for_user",
                        lambda *a, **kw: True)
    mbas.create_subscription("u1", "TCS", 30.0, "positive")
    fired = mbas.check_and_fire_alerts("TCS", 20.0)
    assert fired == []


def test_check_and_fire_no_subs_for_ticker(_isolated_store):
    mbas = _isolated_store
    # No subs → nothing fires, no error.
    assert mbas.check_and_fire_alerts("UNKNOWN", 50.0) == []


def test_check_and_fire_ignores_invalid_mos(_isolated_store, monkeypatch):
    mbas = _isolated_store
    monkeypatch.setattr(mbas, "_send_push_for_user",
                        lambda *a, **kw: True)
    mbas.create_subscription("u1", "TCS", 20.0, "positive")
    assert mbas.check_and_fire_alerts("TCS", "not-a-number") == []


def test_render_copy_is_sebi_safe(_isolated_store):
    import re
    mbas = _isolated_store
    sub = mbas.AlertSubscription("u1", "RELIANCE", 20.0, "positive")
    title, body = mbas._render_copy("RELIANCE", sub)
    blob = (title + " " + body).lower()
    # Whole-word check — "threshold" legitimately substring-matches "hold"
    # but isn't a SEBI directive. Backend sebi-filter uses the same
    # \b-bounded matching.
    banned = ["b" + "uy", "s" + "ell", "h" + "old"]
    for w in banned:
        assert re.search(rf"\b{w}\b", blob) is None, (
            f"banned token {w} found in copy: {blob}"
        )


def test_persistence_across_calls(_isolated_store):
    mbas = _isolated_store
    mbas.create_subscription("u1", "INFY", 10.0, "positive")
    # New "process" — reread directly.
    rows = mbas._read_all()
    assert len(rows) == 1
    assert rows[0].user_id == "u1"


def test_list_distinct_tickers(_isolated_store):
    mbas = _isolated_store
    mbas.create_subscription("u1", "RELIANCE", 10.0, "positive")
    mbas.create_subscription("u2", "tcs", 20.0, "negative")
    mbas.create_subscription("u3", "TCS", 30.0, "positive")
    assert mbas.list_distinct_tickers() == ["RELIANCE", "TCS"]
