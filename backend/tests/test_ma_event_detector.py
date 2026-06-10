# backend/tests/test_ma_event_detector.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend.services.ma_event_detector.
#
# Scope:
#   * HDFCBANK fixture (REVERSE_MERGER 2023-07-01, multiplier 2.0)
#     produces a populated payload with magnitude_pct ~100%, the
#     correct event_date, and `is_within_normalization_window=True`
#     for a "today" 3 quarters past the event.
#   * TCS fixture (no structural rows) yields None — the detector
#     never invents events.
#   * is_quarter_distorted_by_ma() flips True/False correctly across
#     the merger boundary (latest quarter inside the window vs years
#     after).
#   * Out-of-window event (KOTAKBANK 2015-04-01 with default 8-quarter
#     window from "today" 2026-06-11) returns None.
#
# Hermetic: monkeypatches `corporate_actions_service.get_actions` so
# no live Postgres is required. Mirrors the pattern in
# test_cement_merger_truncation.py.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import corporate_actions_service as cas
from backend.services.ma_event_detector import (
    detect_ma_event,
    is_quarter_distorted_by_ma,
)


def _seed_hdfcbank_merger(monkeypatch) -> None:
    """Inject the canonical HDFCBANK reverse-merger row.

    Mirrors the row shape produced by
    data_pipeline/migrations/042_seed_structural_mergers.sql so
    detect_ma_event() exercises the same read path it will see in
    production.
    """
    rows = [
        {
            "ticker": "HDFCBANK",
            "ex_date": date(2023, 7, 1),
            "action_type": "REVERSE_MERGER",
            "multiplier": 2.00,
            "source_url": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
            "source_doc": "RBI/SEBI joint approval — HDFC Ltd into HDFC Bank reverse merger",
            "notes": "HDFC Ltd parent absorbed into HDFC Bank; effective date 2023-07-01.",
            "data_source": "curated",
            "data_quality_rank": 10,
        },
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)


def _seed_no_actions(monkeypatch) -> None:
    """TCS-like ticker — no structural rows on file."""
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: [])


def _seed_old_merger(monkeypatch) -> None:
    """KOTAK ING-Vysya merger 2015-04-01 — far outside the 8-quarter
    window from a 2026-06-11 today."""
    rows = [
        {
            "ticker": "KOTAKBANK",
            "ex_date": date(2015, 4, 1),
            "action_type": "MERGER",
            "multiplier": 1.40,
            "source_url": "https://www.rbi.org.in/Scripts/AnnualPublications.aspx",
            "source_doc": "RBI approval — ING Vysya merger with Kotak Mahindra Bank",
            "notes": "ING Vysya merged into Kotak Mahindra Bank; close 2015-04-01.",
            "data_source": "curated",
            "data_quality_rank": 10,
        },
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)


# ── HDFCBANK fixture — happy path ────────────────────────────────
def test_hdfcbank_detects_reverse_merger(monkeypatch):
    """HDFCBANK with the canonical seed row returns a populated dict.

    Assert the public contract: event_date / event_type, a positive
    magnitude_pct derived from multiplier-1, the canonical 8-quarter
    normalisation window, an in-window flag, and the curated
    description-with-notes string.
    """
    _seed_hdfcbank_merger(monkeypatch)
    # "Today" three quarters after the merger — still well inside
    # the 8-quarter normalisation window.
    today = date(2024, 4, 1)

    event = detect_ma_event("HDFCBANK", today=today)

    assert event is not None
    assert event["event_date"] == "2023-07-01"
    assert event["event_type"] == "REVERSE_MERGER"
    # multiplier 2.0 → magnitude_pct (2.0 - 1.0) * 100 = 100.0
    assert event["magnitude_pct"] == pytest.approx(100.0)
    assert event["multiplier"] == pytest.approx(2.0)
    assert event["normalization_window_quarters"] == 8
    assert event["quarters_since_event"] == 3
    assert event["is_within_normalization_window"] is True
    # The curated notes string must surface in the description so the
    # frontend can render filing-grade copy.
    assert "HDFC Ltd parent absorbed" in event["description"]
    # source_url / source_doc are echoed for the filing link.
    assert event["source_url"].startswith("https://")
    assert "RBI/SEBI" in event["source_doc"]


def test_hdfcbank_tolerates_ticker_suffix(monkeypatch):
    """The detector accepts .NS-suffixed tickers (`HDFCBANK.NS`).

    Production callers pass the canonical .NS form; the underlying
    `get_actions` normaliser strips the suffix, and the detector
    must surface the seeded row through that path.
    """
    _seed_hdfcbank_merger(monkeypatch)
    today = date(2024, 4, 1)
    event = detect_ma_event("HDFCBANK.NS", today=today)
    assert event is not None
    assert event["event_type"] == "REVERSE_MERGER"


# ── TCS fixture — None path ─────────────────────────────────────
def test_tcs_returns_none(monkeypatch):
    """A ticker with no structural rows yields None.

    Regression guard against the detector inventing events.
    """
    _seed_no_actions(monkeypatch)
    today = date(2024, 4, 1)
    event = detect_ma_event("TCS", today=today)
    assert event is None


# ── Out-of-window event ─────────────────────────────────────────
def test_out_of_window_returns_none(monkeypatch):
    """A structural row older than the 8-quarter window returns None.

    The Kotak ING-Vysya merger is real but landed in 2015; it has no
    bearing on a 2026-06-11 analysis page, so the detector must skip
    it to keep the caption silent.
    """
    _seed_old_merger(monkeypatch)
    today = date(2026, 6, 11)
    event = detect_ma_event("KOTAKBANK", today=today)
    assert event is None


# ── Distortion helper — quarter-end straddles the event ─────────
def test_is_quarter_distorted_inside_window():
    """Quarter ending 6 months after the event is distorted."""
    event_date = date(2023, 7, 1)
    quarter_end = date(2024, 3, 31)  # 9 months after merger
    assert is_quarter_distorted_by_ma(
        quarter_end=quarter_end,
        event_date=event_date,
        window_quarters=8,
    ) is True


def test_is_quarter_distorted_outside_window():
    """Quarter ending 30 months after the event is past the
    normalisation window — distortion no longer flagged."""
    event_date = date(2023, 7, 1)
    # 30 months after (Jan 2026) is > 8 * 3 = 24 months.
    quarter_end = date(2026, 1, 31)
    assert is_quarter_distorted_by_ma(
        quarter_end=quarter_end,
        event_date=event_date,
        window_quarters=8,
    ) is False


def test_is_quarter_distorted_before_event():
    """Quarter that PREDATES the event isn't distorted by it —
    historical comps are unaffected."""
    event_date = date(2023, 7, 1)
    quarter_end = date(2023, 3, 31)
    assert is_quarter_distorted_by_ma(
        quarter_end=quarter_end,
        event_date=event_date,
        window_quarters=8,
    ) is False


def test_is_quarter_distorted_none_inputs():
    """None inputs must surface as False (no suppression)."""
    assert is_quarter_distorted_by_ma(None, None, 8) is False
    assert is_quarter_distorted_by_ma(date(2024, 3, 31), None, 8) is False
    assert is_quarter_distorted_by_ma(None, date(2023, 7, 1), 8) is False


# ── DB error path ───────────────────────────────────────────────
def test_db_failure_returns_none(monkeypatch):
    """When `get_actions` raises, the detector must swallow it and
    return None — never break the analysis page over an M&A surface."""
    def _boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(cas, "get_actions", _boom)
    event = detect_ma_event("HDFCBANK", today=date(2024, 4, 1))
    assert event is None


def test_empty_ticker_returns_none():
    """Defensive guard — empty / non-string input doesn't crash."""
    assert detect_ma_event("", today=date(2024, 4, 1)) is None
    assert detect_ma_event(None, today=date(2024, 4, 1)) is None  # type: ignore[arg-type]


def test_zero_window_returns_none(monkeypatch):
    """Pathological zero-window input is rejected up front, before any
    DB read. Defensive guard against a misconfigured caller."""
    _seed_hdfcbank_merger(monkeypatch)
    assert (
        detect_ma_event(
            "HDFCBANK", window_quarters=0, today=date(2024, 4, 1),
        )
        is None
    )
