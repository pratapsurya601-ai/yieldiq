"""
Tests for backend/services/earnings_impact_service.py — the
heuristic that bridges a fresh quarterly result to a rough sense
of how the next nightly fair-value recompute may move.

Hermetic: the function under test is pure, so the tests just feed
synthetic quarterly rows and assert on the math.
"""
from __future__ import annotations

from datetime import date

from backend.services.earnings_impact_service import (
    estimate_earnings_impact,
)


def _row(period_end: date, revenue_cr: float,
         net_profit_cr: float | None = None) -> dict:
    """Minimal row matching `company_quarterly_results` shape."""
    return {
        "period_end": period_end,
        "revenue_cr": revenue_cr,
        "net_profit_cr": net_profit_cr,
    }


# ── Latest = Q2 (Sep). Synthetic INFY-like rows, newest first.
# YoY same-month (Sep one year earlier) is present in the window.
def _yoy_window() -> list[dict]:
    return [
        _row(date(2025, 9, 30), revenue_cr=44_000.0, net_profit_cr=6_500.0),  # latest
        _row(date(2025, 6, 30), revenue_cr=42_000.0, net_profit_cr=6_100.0),
        _row(date(2025, 3, 31), revenue_cr=41_000.0, net_profit_cr=6_000.0),
        _row(date(2024, 12, 31), revenue_cr=40_000.0, net_profit_cr=5_900.0),
        _row(date(2024, 9, 30), revenue_cr=39_000.0, net_profit_cr=5_700.0),   # YoY baseline
    ]


# ── Only 2 quarters present; YoY row is absent → QoQ fallback.
def _qoq_only_window() -> list[dict]:
    return [
        _row(date(2025, 9, 30), revenue_cr=44_000.0),
        _row(date(2025, 6, 30), revenue_cr=42_000.0),
    ]


# ─────────────────────────────────────────────────────────────────
# Core math
# ─────────────────────────────────────────────────────────────────

def test_yoy_beat_produces_positive_dampened_fv_delta():
    """Latest 44_000, YoY 39_000, growth 0.10:
       expected = 39_000 * 1.10 = 42_900
       surprise = (44_000 - 42_900) / 42_900 = +2.564%
       fv_delta = 2.564% * 1.2 (IT Services) * 0.3 = +0.923%
    """
    out = estimate_earnings_impact(
        _yoy_window(),
        implied_growth=0.10,
        sector="IT Services",
    )
    assert out is not None
    assert out["baseline"]["kind"] == "yoy"
    assert abs(out["expected_revenue_cr"] - 42_900.0) < 1e-6
    assert abs(out["surprise_pct"] - (44_000.0 - 42_900.0) / 42_900.0) < 1e-9
    expected_delta = ((44_000.0 - 42_900.0) / 42_900.0) * 1.2 * 0.3
    assert abs(out["fv_delta_estimate"] - expected_delta) < 1e-9
    assert out["sector_multiplier"] == 1.2
    assert out["implied_growth_used"] == 0.10
    assert out["is_heuristic"] is True
    assert out["method"] == "heuristic_v1"
    # Range bounds the point estimate.
    assert out["fv_delta_range"]["low"] <= out["fv_delta_estimate"]
    assert out["fv_delta_range"]["high"] >= out["fv_delta_estimate"]


def test_miss_produces_negative_fv_delta():
    """A revenue miss must produce a negative (not absolute) delta —
    'buy on the dip' framing depends on getting the sign right."""
    rows = [
        _row(date(2025, 9, 30), revenue_cr=38_000.0),  # MISS vs expected ~42_900
        _row(date(2025, 6, 30), revenue_cr=42_000.0),
        _row(date(2025, 3, 31), revenue_cr=41_000.0),
        _row(date(2024, 12, 31), revenue_cr=40_000.0),
        _row(date(2024, 9, 30), revenue_cr=39_000.0),
    ]
    out = estimate_earnings_impact(rows, implied_growth=0.10, sector="Pharma")
    assert out is not None
    assert out["surprise_pct"] < 0
    assert out["fv_delta_estimate"] < 0
    assert out["fv_delta_range"]["high"] < 0 or out["fv_delta_range"]["low"] < 0


# ─────────────────────────────────────────────────────────────────
# Baseline selection
# ─────────────────────────────────────────────────────────────────

def test_yoy_preferred_over_qoq_when_both_available():
    out = estimate_earnings_impact(
        _yoy_window(),
        implied_growth=0.10,
        sector="IT Services",
    )
    assert out is not None
    assert out["baseline"]["kind"] == "yoy"
    assert out["baseline"]["period_end"] == "2024-09-30"
    assert "baseline_qoq_used_yoy_absent" not in out["notes"]


def test_qoq_used_when_yoy_absent():
    """Only 2 quarters in the window → no YoY match → QoQ fallback,
    with the `baseline_qoq_used_yoy_absent` note tagged."""
    out = estimate_earnings_impact(
        _qoq_only_window(),
        implied_growth=0.10,
        sector="IT Services",
    )
    assert out is not None
    assert out["baseline"]["kind"] == "qoq"
    assert "baseline_qoq_used_yoy_absent" in out["notes"]
    # QoQ: 42_000 * (1 + 0.10/4) = 43_050
    assert abs(out["expected_revenue_cr"] - 43_050.0) < 1e-6


# ─────────────────────────────────────────────────────────────────
# Sector multiplier
# ─────────────────────────────────────────────────────────────────

def test_fmcg_multiplier_is_lower_than_it_services():
    fmcg = estimate_earnings_impact(
        _yoy_window(), implied_growth=0.10, sector="FMCG",
    )
    it = estimate_earnings_impact(
        _yoy_window(), implied_growth=0.10, sector="IT Services",
    )
    assert fmcg is not None and it is not None
    assert fmcg["sector_multiplier"] == 0.7
    assert it["sector_multiplier"] == 1.2
    # Same surprise direction, FMCG move smaller in absolute terms.
    assert abs(fmcg["fv_delta_estimate"]) < abs(it["fv_delta_estimate"])


def test_unknown_sector_falls_back_to_neutral_multiplier():
    out = estimate_earnings_impact(
        _yoy_window(),
        implied_growth=0.10,
        sector="Unobtanium Mining",
    )
    assert out is not None
    assert out["sector_multiplier"] == 1.0


def test_none_sector_falls_back_to_neutral_multiplier():
    out = estimate_earnings_impact(
        _yoy_window(), implied_growth=0.10, sector=None,
    )
    assert out is not None
    assert out["sector_multiplier"] == 1.0


# ─────────────────────────────────────────────────────────────────
# Implied-growth handling
# ─────────────────────────────────────────────────────────────────

def test_missing_growth_falls_back_to_10pct_and_notes_it():
    out = estimate_earnings_impact(
        _yoy_window(), implied_growth=None, sector="IT Services",
    )
    assert out is not None
    assert out["implied_growth_used"] == 0.10
    assert "implied_growth_missing_fallback_10pct" in out["notes"]


def test_corrupt_growth_is_clamped():
    out = estimate_earnings_impact(
        _yoy_window(), implied_growth=-5.0, sector="IT Services",
    )
    assert out is not None
    assert out["implied_growth_used"] == -0.5
    assert "implied_growth_clamped_low" in out["notes"]

    out_hi = estimate_earnings_impact(
        _yoy_window(), implied_growth=10.0, sector="IT Services",
    )
    assert out_hi is not None
    assert out_hi["implied_growth_used"] == 1.0
    assert "implied_growth_clamped_high" in out_hi["notes"]


# ─────────────────────────────────────────────────────────────────
# Range + clamp
# ─────────────────────────────────────────────────────────────────

def test_extreme_beat_clamps_to_15pct_range():
    """A 100% revenue beat would otherwise give fv_delta = 1.0 * 1.2 *
    0.3 = +36%. The clamp must hold the displayed values to +/- 15%
    and tag the note."""
    rows = [
        _row(date(2025, 9, 30), revenue_cr=80_000.0),  # huge beat
        _row(date(2025, 6, 30), revenue_cr=42_000.0),
        _row(date(2024, 9, 30), revenue_cr=39_000.0),
    ]
    out = estimate_earnings_impact(rows, implied_growth=0.10, sector="IT Services")
    assert out is not None
    assert out["fv_delta_estimate"] == 0.15
    assert out["fv_delta_range"]["high"] == 0.15
    assert "fv_delta_clamped" in out["notes"]


def test_range_brackets_point_estimate_within_2pp():
    out = estimate_earnings_impact(
        _yoy_window(), implied_growth=0.10, sector="Pharma",
    )
    assert out is not None
    # Default ±2pp around the point estimate (when not clamped).
    assert abs(
        (out["fv_delta_range"]["high"] - out["fv_delta_range"]["low"]) - 0.04
    ) < 1e-9


# ─────────────────────────────────────────────────────────────────
# Discipline: heuristic flag must always be present
# ─────────────────────────────────────────────────────────────────

def test_is_heuristic_flag_is_always_true_and_explicit():
    """The is_heuristic flag is contractual — every caller depends
    on it to label the surface correctly. Making sure no future
    refactor lets it slip to False or absent."""
    out = estimate_earnings_impact(
        _yoy_window(), implied_growth=0.10, sector="IT Services",
    )
    assert out is not None
    assert "is_heuristic" in out
    assert out["is_heuristic"] is True
    assert out["method"] == "heuristic_v1"


# ─────────────────────────────────────────────────────────────────
# None / insufficient-input paths
# ─────────────────────────────────────────────────────────────────

def test_empty_rows_returns_none():
    assert estimate_earnings_impact(
        [], implied_growth=0.10, sector="Auto",
    ) is None


def test_latest_revenue_zero_returns_none():
    rows = [
        _row(date(2025, 9, 30), revenue_cr=0.0),
        _row(date(2024, 9, 30), revenue_cr=39_000.0),
    ]
    assert estimate_earnings_impact(
        rows, implied_growth=0.10, sector="Auto",
    ) is None


def test_single_row_with_no_baseline_returns_none():
    rows = [_row(date(2025, 9, 30), revenue_cr=44_000.0)]
    assert estimate_earnings_impact(
        rows, implied_growth=0.10, sector="Auto",
    ) is None


def test_baseline_with_zero_revenue_skips_yoy():
    """A YoY row carrying revenue_cr=0 must not produce a div-by-
    zero; the function must fall through to the QoQ baseline."""
    rows = [
        _row(date(2025, 9, 30), revenue_cr=44_000.0),
        _row(date(2025, 6, 30), revenue_cr=42_000.0),
        _row(date(2024, 9, 30), revenue_cr=0.0),  # poisoned YoY row
    ]
    out = estimate_earnings_impact(
        rows, implied_growth=0.10, sector="Auto",
    )
    assert out is not None
    assert out["baseline"]["kind"] == "qoq"
