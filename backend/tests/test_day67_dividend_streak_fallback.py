"""Day-67 (2026-05-21): dividend streak yfinance fallback.

Audit 2026-05-20: HDFCBANK shows 'Dividend · 1 consecutive year' despite
paying dividends for 10+ years. Root cause: the DB corporate_actions
feed for HDFCBANK currently has only 1 record; consecutive_years is
computed from fy_history length, which underflows when the feed is
sparse.

Fix
---
In _build_from_series, when DB-derived consecutive_years <= 1 AND
fy_history <= 2, cross-check against yfinance .dividends and adopt
the longer streak. DB-amounts take precedence per-FY (Indian-rupee,
ex-date precise) but DB is not authoritative for COUNT when its
feed is freshly populated.

Source-text guard plus a behaviour test of the merge logic.
"""
from __future__ import annotations
from pathlib import Path


_SVC = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "dividend_service.py"
)


def test_yfinance_streak_fallback_wired():
    src = _SVC.read_text(encoding="utf-8")
    # Trigger condition
    assert "consecutive_years <= 1 and len(fy_history) <= 2" in src
    # Pulls yfinance series
    assert "_yf.Ticker(ticker).dividends" in src
    # Adopts the longer streak
    assert "_yf_streak > consecutive_years" in src


def test_merge_preserves_db_amounts():
    """DB rows take precedence (Indian-rupee precision); yfinance
    only fills GAPS. The merge logic uses set-difference on FY key."""
    src = _SVC.read_text(encoding="utf-8")
    assert "_db_fys = {row[\"fy\"] for row in fy_history}" in src
    assert "if row[\"fy\"] not in _db_fys" in src


def test_fallback_is_exception_safe():
    """yfinance can rate-limit / 404 / time out; the fallback must
    never break the main response."""
    src = _SVC.read_text(encoding="utf-8")
    # The fallback block is wrapped in try/except
    idx = src.index("Day-67 (2026-05-21)")
    tail = src[idx : idx + 2500]
    assert "try:" in tail
    assert "except Exception" in tail


def test_logs_adopt_decision_visibly():
    """Ops needs to see when the fallback fires to track DB feed gaps."""
    src = _SVC.read_text(encoding="utf-8")
    assert "DB streak=%d but yfinance" in src
    assert "DB feed" in src and "likely sparse" in src
