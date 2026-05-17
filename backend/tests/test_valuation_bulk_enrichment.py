"""Tests for the bulk FV/MoS enrichment helper used by the home
dashboard v2 portfolio + watchlist rails.

`analysis_cache_service.get_valuation_bulk` must:
  - Issue ONE SQL query, not N (verified by counting Session.execute calls)
  - Return values for tickers present in the cache
  - Omit tickers with no cache row (caller renders dashes)
  - Compute buffett_mos_pct from the cached current_price snapshot
  - Degrade to an empty dict on any DB failure (never raise)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services import analysis_cache_service as acs


class _FakeSession:
    """Minimal SQLAlchemy session stub: records execute() calls and
    returns a canned row set."""

    def __init__(self, rows):
        self._rows = rows
        self.execute_calls = 0
        self.closed = False

    def execute(self, stmt, params=None):
        self.execute_calls += 1
        self._last_params = params
        result = MagicMock()
        result.fetchall.return_value = self._rows
        return result

    def close(self):
        self.closed = True


def _patch_session(monkeypatch, sess):
    monkeypatch.setattr(acs, "_get_session", lambda: sess)
    # Skip canonicalization side-effects: identity map keeps the test
    # focused on the SQL + merge logic, not the bare-ticker rules.
    monkeypatch.setattr(acs, "_canonical_cache_key", lambda t: (t or "").upper())


def test_get_valuation_bulk_returns_values_for_cached_tickers(monkeypatch):
    rows = [
        ("TCS.NS",        4000.0, 12.5, 3500.0, "undervalued"),
        ("INFY.NS",       1500.0, -8.0, 1650.0, "overvalued"),
        ("RELIANCE.NS",   2800.0,  None, None, "fairly_valued"),
    ]
    sess = _FakeSession(rows)
    _patch_session(monkeypatch, sess)

    out = acs.get_valuation_bulk(
        ["TCS.NS", "INFY.NS", "RELIANCE.NS", "MISSINGCO.NS"]
    )

    # Exactly ONE SQL query for all 4 tickers — no N+1.
    assert sess.execute_calls == 1
    assert sess.closed is True

    # Present tickers are populated.
    assert out["TCS.NS"]["fair_value"] == 4000.0
    assert out["TCS.NS"]["mos_pct"] == 12.5
    assert out["TCS.NS"]["verdict"] == "undervalued"
    # buffett_mos_pct = (4000 - 3500) / 4000 * 100 = 12.5
    assert out["TCS.NS"]["buffett_mos_pct"] == 12.5

    # Overvalued: FV < cached price.
    assert out["INFY.NS"]["fair_value"] == 1500.0
    assert out["INFY.NS"]["buffett_mos_pct"] == round((1500.0 - 1650.0) / 1500.0 * 100, 2)

    # Missing cached_current_price → buffett_mos_pct stays None.
    assert out["RELIANCE.NS"]["buffett_mos_pct"] is None

    # Tickers with no cache row are simply absent (caller renders "—").
    assert "MISSINGCO.NS" not in out


def test_get_valuation_bulk_empty_input_no_query(monkeypatch):
    sess = _FakeSession([])
    _patch_session(monkeypatch, sess)
    assert acs.get_valuation_bulk([]) == {}
    assert sess.execute_calls == 0


def test_get_valuation_bulk_db_failure_degrades_open(monkeypatch):
    class _BoomSession(_FakeSession):
        def execute(self, stmt, params=None):
            raise RuntimeError("connection reset")

    sess = _BoomSession([])
    _patch_session(monkeypatch, sess)
    # Must never raise — list endpoints stay up even when Aiven is down.
    assert acs.get_valuation_bulk(["TCS.NS"]) == {}


def test_get_valuation_bulk_single_query_for_50_tickers(monkeypatch):
    """Performance contract: 50-ticker portfolio = 1 query, not 50."""
    tickers = [f"T{i}.NS" for i in range(50)]
    rows = [(t, 100.0, 5.0, 95.0, "undervalued") for t in tickers]
    sess = _FakeSession(rows)
    _patch_session(monkeypatch, sess)

    out = acs.get_valuation_bulk(tickers)

    assert sess.execute_calls == 1
    assert len(out) == 50
    # And the SQL was parameterized with ANY(:tickers), so the canonical
    # set was passed in a single bind variable.
    assert "tickers" in sess._last_params
    assert len(sess._last_params["tickers"]) == 50
