"""ROOT CAUSE #12 — fair_value_history WRITE-TIME sanity gate.

Covers `should_persist_fv_row`:

* First-row case (prev_fv=None) — always persists.
* Within-band Δ (≤ 25 %) — persists, no corroboration required.
* Large Δ + manifest entry — persists, corroboration label
  attached.
* Large Δ + no corroboration — quarantined.
* Manifest matching honours ticker scope (wildcard, list, single).
* Manifest matching honours the ±3-day window.
* Degenerate inputs (today_fv None / <= 0) — quarantined.
* The 106.5% HDFCBANK 30-Apr-2026 reference case — quarantined
  when no manifest / corporate action / concall on the date.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for p in (_BACKEND, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend.services.fair_value_history_writer import (  # noqa: E402
    MAX_DAILY_FV_DELTA_PCT,
    WriteGateDecision,
    manifest_corroborates,
    should_persist_fv_row,
)


# ---------- happy path ------------------------------------------------------

def test_first_row_for_ticker_always_persists():
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=1700.0,
        prev_fv=None,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert d.persist is True
    assert d.reason == "first_row_for_ticker"


def test_within_band_delta_persists_without_corroboration():
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=1100.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert d.persist is True
    assert d.reason == "within_daily_delta_band"
    assert d.delta_pct == pytest.approx(10.0)


def test_large_delta_with_matching_manifest_persists():
    manifest = [
        {
            "version_id": "v_test_2026_04_30",
            "applied_at": datetime(2026, 4, 30, 10, tzinfo=timezone.utc),
            "scope": {"tickers": "*"},
        }
    ]
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=2000.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=manifest,
    )
    assert d.persist is True
    assert d.reason == "corroborated_by_manifest"
    assert d.corroboration == "v_test_2026_04_30"


def test_large_delta_with_no_corroboration_quarantined():
    """The HDFCBANK 30-Apr-2026 reference — 106.5 % single-day FV
    revision with no manifest / corporate action / concall is the
    exact write that this gate must reject.
    """
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=2065.0,  # 106.5% jump from 1000
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert d.persist is False
    assert d.reason.startswith("uncorroborated_large_delta")
    assert d.delta_pct == pytest.approx(106.5, abs=0.1)


def test_106_5_pct_hdfcbank_reference_quarantine_with_far_manifest():
    """A manifest entry from 3 weeks earlier does NOT corroborate
    a write today (window is ±3 days by default).
    """
    manifest = [
        {
            "version_id": "v_stale_2026_04_01",
            "applied_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "scope": {"tickers": "*"},
        }
    ]
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=2065.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=manifest,
    )
    assert d.persist is False


# ---------- ticker-scope matching -------------------------------------------

def test_manifest_wildcard_ticker_matches():
    out = manifest_corroborates(
        [{
            "version_id": "v_wild",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc),
            "scope": {"tickers": "*"},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out == "v_wild"


def test_manifest_explicit_ticker_matches():
    out = manifest_corroborates(
        [{
            "version_id": "v_explicit",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc),
            "scope": {"tickers": "HDFCBANK"},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out == "v_explicit"


def test_manifest_explicit_other_ticker_does_not_match():
    out = manifest_corroborates(
        [{
            "version_id": "v_other",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc),
            "scope": {"tickers": "RELIANCE"},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out is None


def test_manifest_ticker_list_matches():
    out = manifest_corroborates(
        [{
            "version_id": "v_list",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc),
            "scope": {"tickers": ["RELIANCE", "HDFCBANK"]},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out == "v_list"


# ---------- window boundaries -----------------------------------------------

@pytest.mark.parametrize("offset_days", [-3, -1, 0, 1, 3])
def test_manifest_within_3_day_window_corroborates(offset_days: int):
    out = manifest_corroborates(
        [{
            "version_id": "v_in_window",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc)
            + timedelta(days=offset_days),
            "scope": {"tickers": "*"},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out == "v_in_window"


@pytest.mark.parametrize("offset_days", [-4, -7, 4, 10])
def test_manifest_outside_3_day_window_does_not_corroborate(offset_days: int):
    out = manifest_corroborates(
        [{
            "version_id": "v_far",
            "applied_at": datetime(2026, 4, 30, tzinfo=timezone.utc)
            + timedelta(days=offset_days),
            "scope": {"tickers": "*"},
        }],
        ticker="HDFCBANK",
        write_date=date(2026, 4, 30),
    )
    assert out is None


# ---------- degenerate inputs ----------------------------------------------

def test_zero_fv_input_quarantined():
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=0.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert d.persist is False
    assert "degenerate_input" in d.reason


def test_negative_fv_input_quarantined():
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=-100.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert d.persist is False
    assert "degenerate_input" in d.reason


def test_default_threshold_constant_is_25_pct():
    """If anyone bumps the threshold, the regression test forces a
    conscious decision rather than a silent loosening."""
    assert MAX_DAILY_FV_DELTA_PCT == 25.0


# ---------- decision dataclass shape ---------------------------------------

def test_decision_records_delta_pct_when_computed():
    d = should_persist_fv_row(
        ticker="HDFCBANK",
        today_fv=1150.0,
        prev_fv=1000.0,
        write_date=date(2026, 4, 30),
        manifest_entries=[],
    )
    assert isinstance(d, WriteGateDecision)
    assert d.delta_pct == pytest.approx(15.0)
    assert d.prev_fv == pytest.approx(1000.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
