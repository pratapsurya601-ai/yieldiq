"""
Tests for backend.services.analysis.compute_for_date.

DB-free: stub out the SQLAlchemy session and AnalysisService to verify
the wiring (historical price lookup → MoS reprojection → output dict
shape) without hitting Postgres or yfinance.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeRow:
    def __init__(self, value):
        self._v = value

    def __getitem__(self, idx):
        return self._v


class _FakeSession:
    """Minimal SQLAlchemy-like session that returns a configured close_price."""
    def __init__(self, close_price):
        self._cp = close_price
        self.closed = False

    def execute(self, sql, params):
        class _Result:
            def __init__(self, cp):
                self._cp = cp
            def fetchone(self):
                if self._cp is None:
                    return None
                return _FakeRow(self._cp)
        return _Result(self._cp)

    def close(self):
        self.closed = True


def _fake_analysis_response(fv=120.0, score=72, grade="B", verdict="undervalued"):
    return SimpleNamespace(
        valuation=SimpleNamespace(fair_value=fv, verdict=verdict),
        quality=SimpleNamespace(yieldiq_score=score, grade=grade),
    )


def test_returns_none_when_price_missing():
    from backend.services.analysis.compute_for_date import compute_for_date
    sess = _FakeSession(close_price=None)
    out = compute_for_date("RELIANCE.NS", date(2026, 4, 1), session=sess)
    assert out is None


def test_returns_none_when_price_zero():
    from backend.services.analysis.compute_for_date import compute_for_date
    sess = _FakeSession(close_price=0)
    out = compute_for_date("RELIANCE.NS", date(2026, 4, 1), session=sess)
    assert out is None


def test_reprojects_mos_against_historical_price():
    from backend.services.analysis.compute_for_date import compute_for_date

    sess = _FakeSession(close_price=100.0)
    fake = _fake_analysis_response(fv=130.0, score=70, grade="B", verdict="undervalued")

    with patch("backend.services.analysis.service.AnalysisService") as MockSvc, \
         patch("backend.services.cache_service.CACHE_VERSION", 67):
        instance = MockSvc.return_value
        instance.get_full_analysis.return_value = fake

        out = compute_for_date("TCS.NS", date(2026, 3, 28), session=sess)

    assert out is not None
    assert out.ticker == "TCS.NS"
    assert out.as_of_date == date(2026, 3, 28)
    assert out.current_price == 100.0
    assert out.fair_value == 130.0
    # MoS = (130 - 100) / 100 * 100 = 30.0
    assert out.margin_of_safety_pct == 30.0
    assert out.yieldiq_score == 70
    assert out.grade == "B"
    assert out.verdict == "undervalued"
    assert out.cache_version == 67


def test_handles_ticker_not_found():
    from backend.services.analysis.compute_for_date import compute_for_date
    from backend.services.analysis.service import TickerNotFoundError

    sess = _FakeSession(close_price=100.0)
    with patch("backend.services.analysis.service.AnalysisService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_full_analysis.side_effect = TickerNotFoundError("UNKNOWN.NS")
        out = compute_for_date("UNKNOWN.NS", date(2026, 4, 1), session=sess)
    assert out is None


def test_negative_mos_when_overvalued():
    from backend.services.analysis.compute_for_date import compute_for_date

    sess = _FakeSession(close_price=200.0)
    fake = _fake_analysis_response(fv=150.0, verdict="overvalued")

    with patch("backend.services.analysis.service.AnalysisService") as MockSvc:
        instance = MockSvc.return_value
        instance.get_full_analysis.return_value = fake
        out = compute_for_date("XYZ.NS", date(2026, 4, 1), session=sess)

    assert out is not None
    # (150 - 200) / 200 * 100 = -25.0
    assert out.margin_of_safety_pct == -25.0
    assert out.verdict == "overvalued"


def test_strips_ticker_suffix_in_price_lookup():
    """The SQL parameter for ticker must use the bare NSE symbol."""
    from backend.services.analysis.compute_for_date import _historical_close

    captured = {}

    class _CapturingSession:
        def execute(self, sql, params):
            captured.update(params)
            class _R:
                def fetchone(self):
                    return _FakeRow(99.5)
            return _R()

    px = _historical_close(_CapturingSession(), "RELIANCE.NS", date(2026, 4, 1))
    assert px == 99.5
    assert captured["ticker"] == "RELIANCE"
    assert captured["as_of"] == date(2026, 4, 1)


if __name__ == "__main__":
    import unittest
    test_returns_none_when_price_missing()
    test_returns_none_when_price_zero()
    test_reprojects_mos_against_historical_price()
    test_handles_ticker_not_found()
    test_negative_mos_when_overvalued()
    test_strips_ticker_suffix_in_price_lookup()
    print("OK — 6 tests passed")
