"""Lock-in tests for the 12-month score history sparkline pipeline.

Regression guard for fix/score-history-12m-pipeline (2026-04-23).

History: every Nifty 50 stock rendered "Insufficient history" on the
analysis page because ``_score_history_12m`` required >=3 monthly
buckets AND queried fair_value_history with only the canonical
".NS"-suffixed ticker. When historical rows had been written under
the bare form (TITAN) or the table had only 2 months of populated
data, the UI saw an empty array and fell back to the gated state.

These tests lock in:
  1. The threshold is 2 buckets (matches the frontend Sparkline
     ``points.length < 2`` gate).
  2. Both canonical (TITAN.NS) and bare (TITAN) ticker rows are
     folded into the same bucket series.
  3. The returned shape is ``list[int]`` sized <= 12, oldest first.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from backend.services import prism_service


class _FakeSession:
    """Minimal stand-in for a SQLAlchemy session. Records the IN-list
    tickers so we can assert suffix handling without needing an actual DB."""

    def __init__(self, rows):
        self._rows = rows
        self.captured_tickers: list = []

    def execute(self, stmt, params):
        self.captured_tickers = list(params.get("tickers", []))
        return self

    def fetchall(self):
        return self._rows


def _patch_session(rows):
    """Patch the module-level ``_get_session`` and ``_safe_close`` to
    return our fake. Returns the fake for inspection."""
    fake = _FakeSession(rows)
    return fake, patch.object(prism_service, "_get_session", return_value=fake), \
        patch.object(prism_service, "_safe_close", lambda s: None)


def test_score_history_12m_returns_non_empty_with_two_buckets():
    """With exactly 2 monthly buckets we must return a 2-point series
    (not []). This is the key fix — earlier threshold was 3 buckets."""
    today = date.today()
    rows = [
        (today - timedelta(days=45), 12.0, 70),  # month -1
        (today - timedelta(days=15), 18.0, 75),  # current month
    ]
    fake, p1, p2 = _patch_session(rows)
    with p1, p2:
        out = prism_service._score_history_12m("TITAN.NS")
    assert isinstance(out, list)
    assert len(out) >= 2, f"Expected >=2 datapoints, got {out!r}"
    for v in out:
        assert isinstance(v, int)
        assert 0 <= v <= 100


def test_score_history_12m_returns_empty_on_single_bucket():
    """1 bucket is still insufficient — the frontend Sparkline needs 2
    points to draw a line. Degrading to the 'insufficient history'
    label is correct here."""
    today = date.today()
    rows = [
        (today - timedelta(days=5), 10.0, 60),
    ]
    fake, p1, p2 = _patch_session(rows)
    with p1, p2:
        out = prism_service._score_history_12m("TITAN.NS")
    assert out == []


def test_score_history_12m_queries_both_ticker_forms():
    """The SQL IN-list must contain both the canonical and bare form so
    historical rows written under either convention are picked up."""
    fake, p1, p2 = _patch_session([])
    with p1, p2:
        prism_service._score_history_12m("TITAN.NS")
    assert "TITAN.NS" in fake.captured_tickers
    assert "TITAN" in fake.captured_tickers


def test_score_history_12m_caps_at_12_points():
    """Even with >12 months of data, we return at most the trailing 12."""
    today = date.today()
    rows = []
    # 14 distinct months, one row per month
    for i in range(14):
        d = date(today.year, 1, 1) - timedelta(days=i * 31)
        rows.append((d, float(i), 50))
    rows.sort(key=lambda r: r[0])
    fake, p1, p2 = _patch_session(rows)
    with p1, p2:
        out = prism_service._score_history_12m("RELIANCE.NS")
    assert len(out) <= 12
    assert len(out) >= 2
