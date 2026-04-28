"""Unit tests for scripts/audit_ratio_history.py.

Synthetic-only — no live DB. Drives the pure ``evaluate_row`` function
with hand-crafted input rows that mirror the four bug classes the
audit is meant to flag, plus a clean control set.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Resolve repo root + scripts dir for direct module import — the
# repo conftest.py already pins repo root to sys.path[0], but
# scripts/ is not a package so we add it explicitly here.
_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import audit_ratio_history as ara  # type: ignore[import-not-found]


TODAY = date(2026, 4, 27)
RECENT_PERIOD = TODAY - timedelta(days=30)
STALE_PERIOD = TODAY - timedelta(days=200)


# ──────────────────────────────────────────────────────────────────────
# Bug-class fixtures
# ──────────────────────────────────────────────────────────────────────
def test_null_pe_flagged():
    """JUSTDIAL-class: pe_ratio is NULL but other ratios populated."""
    r = ara.evaluate_row(
        ticker="JUSTDIAL",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=None,
        ev_ebitda=12.5,
        pb_ratio=2.1,
        roe=18.0,
        roce=22.0,
        today=TODAY,
    )
    assert "null_pe" in r.flags
    assert "rebuild from financials" in r.remediation


def test_sub_one_pe_flagged():
    """HCLTECH/WIPRO/TECHM-class: pre-#126 _normalize_pct artifact."""
    r = ara.evaluate_row(
        ticker="HCLTECH",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=0.30,
        ev_ebitda=15.0,
        pb_ratio=4.5,
        roe=22.0,
        roce=28.0,
        today=TODAY,
    )
    assert "sub_one_pe" in r.flags
    assert "_normalize_pct" in r.remediation


def test_hyper_roe_flagged():
    """ROE accidentally multiplied — sits above 100%."""
    r = ara.evaluate_row(
        ticker="EXAMPLE",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=18.0,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=235.0,   # 2.35 (decimal) double-multiplied
        roce=22.0,
        today=TODAY,
    )
    assert "hyper_roe" in r.flags
    assert "decimal multiplied by 100" in r.remediation


def test_hyper_roce_flagged():
    r = ara.evaluate_row(
        ticker="EXAMPLE2",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=18.0,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=22.0,
        roce=350.0,
        today=TODAY,
    )
    assert "hyper_roce" in r.flags


def test_stale_flagged():
    r = ara.evaluate_row(
        ticker="STALE",
        latest_period_end=STALE_PERIOD,
        pe_ratio=18.0,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=15.0,
        roce=18.0,
        today=TODAY,
    )
    assert "stale" in r.flags
    assert r.days_stale is not None and r.days_stale > ara.STALE_DAYS


def test_missing_period_end_flagged_as_missing():
    """No rows at all → missing flag, not stale."""
    r = ara.evaluate_row(
        ticker="MISSING",
        latest_period_end=None,
        pe_ratio=None,
        ev_ebitda=None,
        pb_ratio=None,
        roe=None,
        roce=None,
        today=TODAY,
    )
    assert "missing" in r.flags
    assert "stale" not in r.flags
    # All-None: should NOT also fire null_pe (avoid double-counting).
    assert "null_pe" not in r.flags


# ──────────────────────────────────────────────────────────────────────
# Clean controls
# ──────────────────────────────────────────────────────────────────────
def test_clean_row_unflagged():
    """RELIANCE-style healthy row passes audit."""
    r = ara.evaluate_row(
        ticker="RELIANCE",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=22.5,
        ev_ebitda=14.2,
        pb_ratio=2.1,
        roe=12.0,
        roce=11.5,
        today=TODAY,
    )
    assert r.flags == []
    assert r.remediation == ""


def test_clean_row_with_legitimate_high_pe_unflagged():
    """High but plausible P/E (e.g. growth stock) is NOT flagged."""
    r = ara.evaluate_row(
        ticker="DMART",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=85.0,
        ev_ebitda=22.0,
        pb_ratio=11.0,
        roe=18.0,
        roce=20.0,
        today=TODAY,
    )
    # > SUB_ONE_PE_MAX → no sub_one_pe flag. > 60 P/E is a different
    # warning (red-flag W5 in service.py); audit doesn't repeat it.
    assert "sub_one_pe" not in r.flags
    assert "null_pe" not in r.flags


def test_clean_row_at_pe_threshold():
    """P/E exactly at SUB_ONE_PE_MAX → not flagged (strict <)."""
    r = ara.evaluate_row(
        ticker="EDGE",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=ara.SUB_ONE_PE_MAX,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=15.0,
        roce=18.0,
        today=TODAY,
    )
    assert "sub_one_pe" not in r.flags


def test_clean_row_at_stale_threshold():
    """Exactly STALE_DAYS old → not stale (strict >)."""
    boundary = TODAY - timedelta(days=ara.STALE_DAYS)
    r = ara.evaluate_row(
        ticker="BOUNDARY",
        latest_period_end=boundary,
        pe_ratio=18.0,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=15.0,
        roce=18.0,
        today=TODAY,
    )
    assert "stale" not in r.flags


# ──────────────────────────────────────────────────────────────────────
# Multi-flag interactions
# ──────────────────────────────────────────────────────────────────────
def test_multiple_flags_on_one_row():
    """Pathological: stale AND sub-1 P/E AND hyper-ROE."""
    r = ara.evaluate_row(
        ticker="WORST",
        latest_period_end=STALE_PERIOD,
        pe_ratio=0.45,
        ev_ebitda=10.0,
        pb_ratio=2.0,
        roe=240.0,
        roce=18.0,
        today=TODAY,
    )
    assert "stale" in r.flags
    assert "sub_one_pe" in r.flags
    assert "hyper_roe" in r.flags
    # Remediation should chain hints
    assert "rebuild" in r.remediation


def test_csv_serialisation_shape():
    r = ara.evaluate_row(
        ticker="JUSTDIAL",
        latest_period_end=RECENT_PERIOD,
        pe_ratio=None,
        ev_ebitda=12.5,
        pb_ratio=2.1,
        roe=18.0,
        roce=22.0,
        today=TODAY,
    )
    row = r.as_csv_row()
    expected_keys = {
        "ticker", "flag", "latest_period_end", "pe_ratio", "ev_ebitda",
        "pb_ratio", "roe", "roce", "days_stale", "remediation_hint",
    }
    assert set(row.keys()) == expected_keys
    assert row["ticker"] == "JUSTDIAL"
    assert "null_pe" in row["flag"]
    assert row["latest_period_end"] == RECENT_PERIOD.isoformat()
    assert row["pe_ratio"] == ""  # None → empty string
    assert row["ev_ebitda"] == "12.5000"


# ──────────────────────────────────────────────────────────────────────
# Resolve-tickers helper (used by main())
# ──────────────────────────────────────────────────────────────────────
def test_known_outliers_includes_audit_universe():
    """Hard-coded set must include every ticker the brief called out."""
    expected = {
        "JUSTDIAL", "EMAMILTD", "NATCOPHARM",
        "SANOFI", "ZYDUSLIFE", "MAYURUNIQ",
        "HCLTECH", "WIPRO", "TECHM",
    }
    assert expected.issubset(set(ara.KNOWN_OUTLIERS))


def test_resolve_tickers_explicit_overrides_canary():
    args = type("A", (), {})()
    args.tickers = "FOO,BAR"
    args.include_canary = True
    out = ara._resolve_tickers(args, _ROOT)
    assert out == ["FOO", "BAR"]


def test_resolve_tickers_default_returns_outliers():
    args = type("A", (), {})()
    args.tickers = ""
    args.include_canary = False
    out = ara._resolve_tickers(args, _ROOT)
    assert out == list(ara.KNOWN_OUTLIERS)
