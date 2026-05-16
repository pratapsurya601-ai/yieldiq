"""Tests for the analysis_cache write-time poison guard.

Pins the contract introduced after the 2026-05-17 MPHASIS/COFORGE/
PERSISTENT incident: ``save_cached`` must refuse to overwrite an
existing healthy cache row with a poisoned payload
(``market_cap=0`` + ``data_issues``). Without this guard, a single
miscalled refresh script can flip flagship tickers to
``data_limited`` on the live site for hours.
"""
from __future__ import annotations

import json

import pytest


_HEALTHY = {
    "valuation": {
        "fair_value": 2800.0,
        "current_price": 2750.0,
        "market_cap_inr": 524_000.0,
        "verdict": "fairly_valued",
    },
    "data_issues": [],
}

_POISONED = {
    "valuation": {
        "fair_value": 0.0,
        "current_price": 0.0,
        "market_cap_inr": 0,
        "verdict": "data_limited",
    },
    "data_issues": [{"code": "MARKET_CAP_MISSING", "severity": "high"}],
}


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeSess:
    """Records SQL params; serves a configurable existing row on SELECT."""

    def __init__(self, existing_row=None):
        self.existing_row = existing_row
        self.executed: list[tuple[str, dict]] = []

    def execute(self, sql, params):
        sql_text = str(sql)
        self.executed.append((sql_text, params))
        if "SELECT" in sql_text.upper():
            return _FakeResult(self.existing_row)
        return _FakeResult(None)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _patch(monkeypatch, sess):
    from backend.services import analysis_cache_service as svc
    monkeypatch.setattr(svc, "_get_session", lambda: sess)
    monkeypatch.setattr(svc, "_canonical_cache_key", lambda t: t)
    monkeypatch.setattr(svc, "_fire_revalidate", lambda _t: None)
    return svc


def test_poisoned_payload_skipped_when_healthy_row_exists(monkeypatch):
    # Existing row is healthy; poisoned write must be refused.
    sess = _FakeSess(existing_row=(json.dumps(_HEALTHY),))
    svc = _patch(monkeypatch, sess)

    svc.save_cached("MPHASIS.NS", _POISONED, 50)

    # No INSERT statement should have been executed.
    inserts = [s for s, _ in sess.executed if "INSERT" in s.upper()]
    assert inserts == [], "save_cached must not overwrite a healthy row"


def test_healthy_payload_writes_through(monkeypatch):
    sess = _FakeSess(existing_row=(json.dumps(_HEALTHY),))
    svc = _patch(monkeypatch, sess)

    svc.save_cached("MPHASIS.NS", _HEALTHY, 50)

    inserts = [s for s, _ in sess.executed if "INSERT" in s.upper()]
    assert len(inserts) == 1


def test_first_time_poisoned_write_allowed_when_no_prior_row(monkeypatch):
    # No existing row: a poisoned payload still lands so data_limited
    # tickers on first compute don't get silently dropped.
    sess = _FakeSess(existing_row=None)
    svc = _patch(monkeypatch, sess)

    svc.save_cached("NEWTICKER.NS", _POISONED, 50)

    inserts = [s for s, _ in sess.executed if "INSERT" in s.upper()]
    assert len(inserts) == 1


def test_genuine_low_market_cap_without_data_issues_passes(monkeypatch):
    # market_cap_inr=0 alone is not enough — must also have data_issues.
    payload = {
        "valuation": {"fair_value": 10.0, "market_cap_inr": 0},
        "data_issues": [],
    }
    sess = _FakeSess(existing_row=(json.dumps(_HEALTHY),))
    svc = _patch(monkeypatch, sess)
    svc.save_cached("SMALLCAP.NS", payload, 50)
    inserts = [s for s, _ in sess.executed if "INSERT" in s.upper()]
    assert len(inserts) == 1


def test_is_poisoned_payload_unit():
    from backend.services.analysis_cache_service import _is_poisoned_payload
    assert _is_poisoned_payload(_POISONED) is True
    assert _is_poisoned_payload(_HEALTHY) is False
    assert _is_poisoned_payload({}) is False
    assert _is_poisoned_payload({"data_issues": [{"x": 1}]}) is False
    # market_cap at the root level also triggers
    assert _is_poisoned_payload({
        "market_cap": 0,
        "data_issues": [{"code": "X"}],
    }) is True
