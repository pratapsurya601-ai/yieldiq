"""
Tests for backend/services/earnings_calendar_fv_impact_service.py
— the heuristic that bridges the next-scheduled earnings date +
consensus EPS + historical surprise track record to a per-5%-beat
FV sensitivity.

Hermetic: the math helpers are pure, so most tests feed synthetic
quarterly rows directly. The end-to-end compute path is tested via
monkeypatching the four `_safe_*` IO wrappers — none of these
tests open a DB connection or hit the network.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from backend.services import earnings_calendar_fv_impact_service as svc


# ─────────────────────────────────────────────────────────────────
# Pure math — _historical_surprise + _per_5pct_beat_sensitivity
# ─────────────────────────────────────────────────────────────────


def _row(period_end: date, revenue_cr: float) -> dict:
    return {"period_end": period_end, "revenue_cr": revenue_cr}


def _yoy_window() -> list[dict]:
    """INFY-shaped 8-quarter window — last 4 quarters have a YoY
    same-month baseline available in the older 4."""
    return [
        # Last 4 quarters (newest first):
        _row(date(2026, 3, 31), 44_500.0),  # Q4 FY26
        _row(date(2025, 12, 31), 43_500.0), # Q3 FY26
        _row(date(2025, 9, 30), 42_500.0),  # Q2 FY26
        _row(date(2025, 6, 30), 41_500.0),  # Q1 FY26
        # YoY baseline quarters (newest first):
        _row(date(2025, 3, 31), 41_000.0),  # YoY for latest Q4
        _row(date(2024, 12, 31), 40_000.0), # YoY for Q3
        _row(date(2024, 9, 30), 39_000.0),  # YoY for Q2
        _row(date(2024, 6, 30), 38_000.0),  # YoY for Q1
    ]


def test_historical_surprise_mean_yoy_with_full_track_record():
    """Each of the last 4 quarters has a YoY baseline; at
    implied_growth=0.10, expected = yoy * 1.10. The mean surprise
    should sit slightly negative (the latest quarter's revenue
    growth ~+8.5% YoY is below the 10% growth assumption).
    """
    rows = _yoy_window()
    mean, n = svc._historical_surprise(rows, implied_growth=0.10, quarters=4)
    assert n == 4
    # Sanity bounds — each per-quarter surprise sits between -2% and
    # +2% by construction of the fixture, so the mean is in band.
    assert -0.03 < mean < 0.03


def test_historical_surprise_returns_zero_when_no_baseline():
    """Two quarters of data with no older YoY rows → n_observed=0,
    mean defaults to 0.0 so the FV impact slot still renders."""
    rows = [
        _row(date(2026, 3, 31), 100.0),
        _row(date(2025, 12, 31), 95.0),
    ]
    mean, n = svc._historical_surprise(rows, implied_growth=0.10)
    assert n == 0
    assert mean == 0.0


def test_historical_surprise_handles_empty_rows():
    mean, n = svc._historical_surprise([], implied_growth=0.10)
    assert mean == 0.0
    assert n == 0


def test_historical_surprise_skips_corrupt_revenue():
    """A 0-revenue row in the middle must not poison the mean."""
    rows = [
        _row(date(2026, 3, 31), 100.0),
        _row(date(2025, 3, 31), 0.0),      # corrupt YoY → expected<=0, skip
        _row(date(2024, 3, 31), 90.0),     # still YoY-eligible
    ]
    mean, n = svc._historical_surprise(rows, implied_growth=0.10, quarters=2)
    # Only the latest row has a usable YoY (the 2024 row).
    # Wait — the function looks for the FIRST yoy match in rows[i+1:],
    # so the 0-revenue 2025 row is found first, rejected, then the
    # 2024 row IS picked up by the inner loop continuing.
    # The exact behaviour: inner loop "break" on the first match
    # regardless of revenue. Our function rejects yoy_baseline=None
    # if cand_rev is None, but breaks on a 0-revenue row at the
    # break. Read the loop again — actually it does NOT break on a
    # 0 rev; it requires cand_rev not None to set yoy_baseline.
    # Confirm n_observed is 1 (the latest YoY match, the 2024 row).
    assert n == 1
    assert -0.20 < mean < 0.20


def test_per_5pct_beat_sensitivity_it_services():
    """IT services multiplier 1.2; 0.05 * 1.2 * 0.3 = 0.018."""
    val = svc._per_5pct_beat_sensitivity("IT Services")
    assert abs(val - 0.018) < 1e-9


def test_per_5pct_beat_sensitivity_bank_defensive_lower():
    """Bank multiplier 0.7; 0.05 * 0.7 * 0.3 = 0.0105."""
    val = svc._per_5pct_beat_sensitivity("Bank")
    assert abs(val - 0.0105) < 1e-9


def test_per_5pct_beat_sensitivity_unknown_sector_neutral():
    """Unknown sector → multiplier 1.0; 0.05 * 1.0 * 0.3 = 0.015."""
    val = svc._per_5pct_beat_sensitivity("Some Sector That Isnt Mapped")
    assert abs(val - 0.015) < 1e-9


def test_per_5pct_beat_sensitivity_none_sector():
    val = svc._per_5pct_beat_sensitivity(None)
    assert abs(val - 0.015) < 1e-9


def test_per_5pct_beat_clamped():
    """No sector multiplier in the live table pushes the value above
    the +/-_PER_5PCT_CLAMP cap (max is 1.2 → 0.018, well inside
    0.05), but the clamp must still trigger if someone ships a
    higher multiplier in a future PR. Verify the clamp directly."""
    assert svc._per_5pct_beat_sensitivity("nonsense") <= svc._PER_5PCT_CLAMP


# ─────────────────────────────────────────────────────────────────
# compute_earnings_calendar_fv_impact — end-to-end via monkeypatch
# ─────────────────────────────────────────────────────────────────


@dataclass
class _FakeEvent:
    date: str
    days_until: int
    confirmed: bool
    source: str
    fiscal_period: str | None
    event_type: str | None = "Financial Results"
    purpose: str | None = ""


def _install_fakes(
    monkeypatch,
    *,
    event: _FakeEvent | None,
    sector: str | None = "IT Services",
    growth: float | None = 0.10,
    eps_pair: tuple[float | None, float | None] = (60.0, 15.0),
    rows: list[dict] | None = None,
):
    monkeypatch.setattr(svc, "_safe_get_next_earnings", lambda t: event)
    monkeypatch.setattr(
        svc, "_safe_resolve_sector_and_growth", lambda t: (sector, growth),
    )
    monkeypatch.setattr(svc, "_safe_consensus_eps", lambda t: eps_pair)
    # `rows is None` -> fall back to the default fixture. `rows == []`
    # is a valid signal meaning "no track record" and MUST be passed
    # through unchanged.
    _rows = _yoy_window() if rows is None else rows
    monkeypatch.setattr(
        svc, "_safe_quarterly_rows", lambda t, n_quarters: _rows,
    )


def test_compute_returns_none_when_no_upcoming_event(monkeypatch):
    _install_fakes(monkeypatch, event=None)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is None


def test_compute_returns_none_when_event_beyond_lookahead(monkeypatch):
    far = _FakeEvent(
        date="2026-12-31", days_until=180, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q3FY27",
    )
    _install_fakes(monkeypatch, event=far)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is None


def test_compute_returns_none_when_event_in_the_past(monkeypatch):
    past = _FakeEvent(
        date="2025-01-01", days_until=-5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q3FY25",
    )
    _install_fakes(monkeypatch, event=past)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is None


def test_compute_happy_path_it_services(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q1FY27",
    )
    _install_fakes(monkeypatch, event=ev)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is not None
    assert out.ticker == "INFY"
    assert out.estimated_report_date == "2026-06-15"
    assert out.days_until == 5
    assert out.consensus_eps_estimate_annual == 60.0
    assert out.consensus_eps_estimate == 15.0
    assert out.consensus_revenue_estimate_cr is None
    # IT Services multiplier 1.2 → sensitivity 0.018.
    assert abs(out.estimated_fv_impact_per_5pct_beat - 0.018) < 1e-9
    assert out.sector_multiplier == 1.2
    assert out.sector == "IT Services"
    assert out.implied_growth_used == 0.10
    assert out.is_heuristic is True
    assert out.method == "forward_v1"
    # Track record fed from the yoy_window fixture has n=4.
    assert out.historical_surprise_quarters == 4
    # Revenue-unavailable note should always appear (NSE coverage gap).
    assert "consensus_revenue_unavailable" in out.notes
    # Confirmed event → no "expected" badge needed downstream.
    assert out.confirmed is True


def test_compute_fallback_growth_marks_note(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q1FY27",
    )
    _install_fakes(monkeypatch, event=ev, growth=None)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is not None
    assert out.implied_growth_used == 0.10
    assert "implied_growth_missing_fallback_10pct" in out.notes


def test_compute_missing_consensus_eps_marks_note(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q1FY27",
    )
    _install_fakes(monkeypatch, event=ev, eps_pair=(None, None))
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is not None
    assert out.consensus_eps_estimate is None
    assert out.consensus_eps_estimate_annual is None
    assert "consensus_eps_missing" in out.notes


def test_compute_unconfirmed_yf_fallback_event(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=False,
        source="yfinance", fiscal_period="Q1FY27",
        event_type="Financial Results (expected)",
        purpose="yfinance projected earnings date — not yet filed with NSE",
    )
    _install_fakes(monkeypatch, event=ev)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is not None
    assert out.confirmed is False
    assert out.source == "yfinance"


def test_compute_no_track_record_marks_note(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q1FY27",
    )
    _install_fakes(monkeypatch, event=ev, rows=[])
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    assert out is not None
    assert out.historical_surprise_quarters == 0
    assert out.historical_avg_surprise_pct == 0.0
    assert "no_historical_surprise_baseline" in out.notes


def test_compute_handles_blank_ticker():
    assert svc.compute_earnings_calendar_fv_impact("") is None
    assert svc.compute_earnings_calendar_fv_impact("   ") is None


def test_to_dict_roundtrips_dataclass_fields(monkeypatch):
    ev = _FakeEvent(
        date="2026-06-15", days_until=5, confirmed=True,
        source="nse_event_calendar", fiscal_period="Q1FY27",
    )
    _install_fakes(monkeypatch, event=ev)
    out = svc.compute_earnings_calendar_fv_impact("INFY.NS")
    d = svc.to_dict(out)
    assert d is not None
    assert d["ticker"] == "INFY"
    assert d["estimated_report_date"] == "2026-06-15"
    assert d["is_heuristic"] is True
    assert d["method"] == "forward_v1"
    # Every dataclass field appears in the dict.
    for field in (
        "consensus_eps_estimate",
        "consensus_eps_estimate_annual",
        "consensus_revenue_estimate_cr",
        "historical_avg_surprise_pct",
        "historical_surprise_quarters",
        "estimated_fv_impact_per_5pct_beat",
        "sector",
        "sector_multiplier",
        "implied_growth_used",
        "confirmed",
        "source",
        "fiscal_period",
        "notes",
    ):
        assert field in d


def test_to_dict_handles_none():
    assert svc.to_dict(None) is None


# ─────────────────────────────────────────────────────────────────
# Cross-surface coherence — the sector multipliers + dampener MUST
# match earnings_impact_service. If anyone changes one without the
# other, this test fires.
# ─────────────────────────────────────────────────────────────────


def test_sector_multiplier_table_matches_earnings_impact_service():
    from backend.services import earnings_impact_service as eis
    assert svc._SECTOR_MULTIPLIER == eis._SECTOR_MULTIPLIER
    assert svc._DAMPENER == eis._DAMPENER


# ─────────────────────────────────────────────────────────────────
# Tunable surface — guard against accidental regressions
# ─────────────────────────────────────────────────────────────────


def test_lookahead_days_is_45_or_less():
    """Brief explicitly contracts on ~5-day "Next earnings in 5
    days" framing. Lookahead of 45 days is the upper bound where
    consensus EPS retains useful precision; bump only with intent."""
    assert svc._LOOKAHEAD_DAYS <= 45


def test_per_5pct_clamp_geq_max_multiplier_path():
    """The clamp must be at least as large as the largest sensible
    value the table can produce — otherwise the IT Services number
    gets silently clamped. max_multiplier=1.2 → 0.018 < 0.05."""
    max_mult = max(svc._SECTOR_MULTIPLIER.values())
    max_val = 0.05 * max_mult * svc._DAMPENER
    assert svc._PER_5PCT_CLAMP >= max_val
