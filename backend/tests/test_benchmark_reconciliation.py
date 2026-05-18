"""Tests for the Benchmark Reconciliation Gate (Layer A).

Covers:

1. The pure ``compute_outliers_from_records`` classifier — no DB.
   - threshold honoured
   - min_analysts honoured
   - direction filter ("over" / "under" / "both")
   - sort order is by |delta_pct| desc
   - SIEMENS-style regression (FV -55% vs consensus) flags as outlier
2. ``CaveatInfo`` shape:
   - flagged=False → caveat_text returns None
   - flagged=True  → returns the generic string with the abs delta only
   - **never** exposes the consensus number or the direction
3. ``is_ticker_flagged`` against a stub SQLAlchemy session — confirms
   the DB-backed wrapper degrades to ``not_flagged`` when:
   - session is None
   - the join returns no row (no consensus coverage)
   - analyst_count below the floor
4. The admin response shape — outliers serialize to the documented
   JSON shape (ticker/sector/our_fv/consensus_fv/delta_pct/direction/
   analyst_count/source/fetched_at).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services import benchmark_reconciliation_service as brs


# ── 1. Pure classifier ──────────────────────────────────────────────


def _rec(ticker, our_fv, consensus_fv, analysts=10, source="finnhub",
         fetched_at="2026-05-18T00:00:00Z", sector="Industrials",
         computed_at="2026-05-17T05:00:00Z"):
    return {
        "ticker": ticker, "our_fv": our_fv, "consensus_fv": consensus_fv,
        "analyst_count": analysts, "source": source,
        "fetched_at": fetched_at, "sector": sector, "computed_at": computed_at,
    }


def test_classifier_threshold_filters_close_matches():
    # 5% delta — well within the 30% threshold → not flagged.
    rows = brs.compute_outliers_from_records([_rec("FOO", 105.0, 100.0)])
    assert rows == []


def test_classifier_flags_above_threshold():
    # 50% over → flagged.
    rows = brs.compute_outliers_from_records([_rec("BAR", 150.0, 100.0)])
    assert len(rows) == 1
    assert rows[0].ticker == "BAR"
    assert rows[0].direction == "over"
    assert rows[0].delta_pct == pytest.approx(0.50)


def test_classifier_siemens_regression_flags_under():
    """Acceptance: a SIEMENS-style FV regression (we say -55% vs
    consensus) must flag in the outlier list. This is the load-bearing
    case that motivated the framework — PR #337 shipped a capital-goods
    engine that did exactly this and only surfaced via user reports."""
    # consensus ₹5000, our model says ₹2250 → delta -55%
    rows = brs.compute_outliers_from_records([
        _rec("SIEMENS", 2250.0, 5000.0, analysts=18, source="finnhub"),
    ])
    assert len(rows) == 1
    r = rows[0]
    assert r.ticker == "SIEMENS"
    assert r.direction == "under"
    assert r.delta_pct == pytest.approx(-0.55, abs=0.01)
    assert r.analyst_count == 18


def test_classifier_min_analysts_floor():
    # 50% delta but only 2 analysts → skipped (low signal).
    rows = brs.compute_outliers_from_records(
        [_rec("THINLY", 150.0, 100.0, analysts=2)],
        min_analysts=3,
    )
    assert rows == []


def test_classifier_direction_filter_under():
    records = [
        _rec("OVER1", 200.0, 100.0),    # +100%, over
        _rec("UNDER1", 30.0, 100.0),    # -70%, under
        _rec("CLOSE", 105.0, 100.0),    # +5%, not flagged
    ]
    rows = brs.compute_outliers_from_records(records, direction="under")
    assert [r.ticker for r in rows] == ["UNDER1"]


def test_classifier_direction_filter_over():
    records = [
        _rec("OVER1", 200.0, 100.0),
        _rec("UNDER1", 30.0, 100.0),
    ]
    rows = brs.compute_outliers_from_records(records, direction="over")
    assert [r.ticker for r in rows] == ["OVER1"]


def test_classifier_sorted_by_abs_delta_desc():
    records = [
        _rec("SMALL", 145.0, 100.0),    # +45%
        _rec("HUGE",  10.0, 100.0),     # -90%
        _rec("MEDIUM", 60.0, 100.0),    # -40%
    ]
    rows = brs.compute_outliers_from_records(records)
    assert [r.ticker for r in rows] == ["HUGE", "SMALL", "MEDIUM"]


def test_classifier_limit_caps_results():
    records = [_rec(f"T{i}", 100.0 + i * 10, 50.0, analysts=10) for i in range(20)]
    rows = brs.compute_outliers_from_records(records, limit=5)
    assert len(rows) == 5


def test_classifier_skips_non_positive_inputs():
    records = [
        _rec("ZERO_CONS", 100.0, 0.0),
        _rec("NEG_FV", -10.0, 100.0),
        _rec("NONE_FV", None, 100.0),
    ]
    assert brs.compute_outliers_from_records(records) == []


# ── 2. CaveatInfo / caveat_text ──────────────────────────────────────


def test_caveat_text_returns_none_when_not_flagged():
    assert brs.caveat_text(brs.CaveatInfo.not_flagged()) is None


def test_caveat_text_returns_string_with_abs_delta_only():
    info = brs.CaveatInfo(flagged=True, abs_delta_pct=55,
                          analyst_count=18, direction="under")
    text = brs.caveat_text(info)
    assert text is not None
    assert "55%" in text
    # The generic copy MUST NOT leak the consensus value or the direction
    # of the disagreement (per design §6.3 — no analyst-target leakage,
    # no "buy/sell" signal embedded in the caveat).
    assert "under" not in text.lower()
    assert "over" not in text.lower()
    assert "consensus" in text  # the word, fine; the number, no
    # No rupee sign, no decimal points other than the integer pct
    assert "₹" not in text


# ── 3. is_ticker_flagged DB wrapper ─────────────────────────────────


class _StubResult:
    """Minimal stand-in for the sqlalchemy Result `.mappings().first()`."""
    def __init__(self, row):
        self._row = row
    def mappings(self):
        return self
    def first(self):
        return self._row
    def all(self):
        return [self._row] if self._row else []


class _StubSession:
    def __init__(self, row):
        self._row = row
        self.executed = []
    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return _StubResult(self._row)
    def close(self):
        pass


def test_is_ticker_flagged_returns_not_flagged_when_no_session(monkeypatch):
    monkeypatch.setattr(brs, "_get_session", lambda: None)
    info = brs.is_ticker_flagged("SIEMENS")
    assert info.flagged is False


def test_is_ticker_flagged_returns_not_flagged_when_no_row():
    sess = _StubSession(row=None)
    info = brs.is_ticker_flagged("SMALLCAP", session=sess)
    assert info.flagged is False


def test_is_ticker_flagged_returns_not_flagged_when_within_threshold():
    sess = _StubSession(row={
        "our_fv": 102.0, "consensus_fv": 100.0,
        "analyst_count": 10, "source": "finnhub",
        "fetched_at": "2026-05-18T00:00:00Z",
    })
    info = brs.is_ticker_flagged("RELIANCE", session=sess)
    assert info.flagged is False


def test_is_ticker_flagged_flags_siemens_regression():
    """End-to-end: SIEMENS analysis_cache says ₹2250, consensus says
    ₹5000 (18 analysts) → flag with abs_delta_pct = 55."""
    sess = _StubSession(row={
        "our_fv": 2250.0, "consensus_fv": 5000.0,
        "analyst_count": 18, "source": "finnhub",
        "fetched_at": "2026-05-18T00:00:00Z",
    })
    info = brs.is_ticker_flagged("SIEMENS", session=sess)
    assert info.flagged is True
    assert info.abs_delta_pct == 55
    assert info.analyst_count == 18
    assert info.direction == "under"
    text = brs.caveat_text(info)
    assert text and "55%" in text


def test_is_ticker_flagged_respects_min_analysts():
    sess = _StubSession(row={
        "our_fv": 2250.0, "consensus_fv": 5000.0,
        "analyst_count": 1, "source": "yfinance",
        "fetched_at": "2026-05-18T00:00:00Z",
    })
    info = brs.is_ticker_flagged("THINLY", session=sess, min_analysts=3)
    assert info.flagged is False


# ── 4. OutlierRow / admin shape ─────────────────────────────────────


def test_outlier_row_serialization_keys():
    rows = brs.compute_outliers_from_records([
        _rec("POWERGRID", 59.0, 305.0, analysts=24, source="finnhub",
             sector="Utilities"),
    ])
    assert len(rows) == 1
    d = rows[0].to_dict()
    expected = {
        "ticker", "sector", "our_fv", "consensus_fv", "delta_pct",
        "direction", "analyst_count", "source", "fetched_at", "computed_at",
    }
    assert expected.issubset(set(d.keys()))
    assert d["ticker"] == "POWERGRID"
    assert d["direction"] == "under"
    assert d["delta_pct"] < -0.30
