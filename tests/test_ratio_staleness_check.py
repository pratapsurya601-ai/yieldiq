"""Unit tests for scripts/check_ratio_staleness.py.

Synthetic-only — exercises the pure ``evaluate`` helper.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_ratio_staleness as crs  # type: ignore[import-not-found]


def test_below_threshold_no_warn():
    warn, msg = crs.evaluate(stale_n=50, total_n=3000, threshold=100)
    assert warn is False
    assert "OK" in msg


def test_at_threshold_no_warn():
    """Exactly threshold = OK (strict greater-than)."""
    warn, _ = crs.evaluate(stale_n=100, total_n=3000, threshold=100)
    assert warn is False


def test_above_threshold_warns():
    warn, msg = crs.evaluate(stale_n=250, total_n=3000, threshold=100)
    assert warn is True
    assert "WARN" in msg
    assert "250" in msg
    assert "3000" in msg
    assert "ratio_history_weekly" in msg


def test_zero_total_no_division_error():
    """Empty universe shouldn't crash."""
    warn, msg = crs.evaluate(stale_n=0, total_n=0, threshold=100)
    assert warn is False
    assert "0.0%" in msg


def test_evaluate_message_includes_percent():
    warn, msg = crs.evaluate(stale_n=300, total_n=3000, threshold=100)
    assert warn is True
    assert "10.0%" in msg


def test_dry_db_main_returns_zero(monkeypatch, capsys):
    rc = crs.main(["--dry-db", "--threshold", "100"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out
