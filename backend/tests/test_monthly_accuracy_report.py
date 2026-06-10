"""Tests for backend.services.monthly_accuracy_report (T5.7).

Pure-function tests — no DB. Every test injects a list-returning
``data_provider`` so the compute layer can be exercised in
isolation.

Locks the contract that the cron + email + /calibration snapshot
depend on:

    - Empty month → fully-populated zero-metric report, no crash.
    - Direction-accuracy math matches fv_accuracy_service thresholds.
    - Per-sector + per-verdict aggregation.
    - Top-5 winners / misses sort by magnitude in the right direction.
    - Missing 30d-forward price → row excluded from accuracy stats
      but counted in coverage shortfall (i.e. counted in total).
    - to_dict shape (JSON-safe, dataclasses → dicts).
    - to_markdown is non-empty and contains the expected headers.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

import pytest

from backend.services.monthly_accuracy_report import (
    DIR_BELOW_THRESHOLD,
    MonthlyAccuracyReport,
    TickerAccuracyEntry,
    _month_bounds,
    compute_monthly_accuracy,
    to_dict,
    to_markdown,
)

# resolve_target_month lives in the cron module — import separately so
# the service-layer test file stays focused on compute behavior.
from backend.jobs.monthly_accuracy_cron import resolve_target_month


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _make_row(
    *,
    ticker: str,
    verdict: str,
    fair_value: float,
    price: float,
    price_30d_later: float | None,
    sector: str | None = "Banking",
    mos_pct: float | None = None,
    publish_date: date = date(2026, 5, 15),
) -> dict:
    if mos_pct is None:
        # Derive mos_pct from FV vs price so tests stay readable.
        mos_pct = round((fair_value - price) / price * 100.0, 2) if price > 0 else 0.0
    return {
        "ticker": ticker,
        "sector": sector,
        "verdict": verdict,
        "fair_value": fair_value,
        "price": price,
        "mos_pct": mos_pct,
        "publish_date": publish_date,
        "price_30d_later": price_30d_later,
    }


def _provider_returning(rows: list[dict]):
    """Construct a data_provider callable that ignores its date
    arguments and returns the given rows."""
    def _provider(_start, _end):
        return list(rows)

    return _provider


# ═════════════════════════════════════════════════════════════════
# _month_bounds
# ═════════════════════════════════════════════════════════════════
class TestMonthBounds:
    def test_january(self):
        start, end = _month_bounds("2026-01")
        assert start == date(2026, 1, 1)
        assert end == date(2026, 2, 1)

    def test_december_wraps_year(self):
        start, end = _month_bounds("2026-12")
        assert start == date(2026, 12, 1)
        assert end == date(2027, 1, 1)

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError):
            _month_bounds("2026-13")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError):
            _month_bounds("2026")


# ═════════════════════════════════════════════════════════════════
# resolve_target_month
# ═════════════════════════════════════════════════════════════════
class TestResolveTargetMonth:
    def test_first_of_month_resolves_to_previous_month(self):
        # On the 1st of June, anchor = May 25 → "2026-05"
        assert resolve_target_month(date(2026, 6, 1)) == "2026-05"

    def test_late_in_month_resolves_to_current_month(self):
        assert resolve_target_month(date(2026, 6, 20)) == "2026-06"

    def test_first_of_january_resolves_to_december_prev_year(self):
        assert resolve_target_month(date(2027, 1, 1)) == "2026-12"


# ═════════════════════════════════════════════════════════════════
# compute_monthly_accuracy — empty month
# ═════════════════════════════════════════════════════════════════
class TestEmptyMonth:
    def test_empty_provider_returns_zero_metric_report(self):
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning([]))

        assert isinstance(report, MonthlyAccuracyReport)
        assert report.report_month == "2026-05"
        assert report.total_verdicts_published == 0
        assert report.coverage_count == 0
        assert report.direction_accuracy_pct == 0.0
        assert report.median_abs_error_pct == 0.0
        assert report.top_5_winners == []
        assert report.top_5_misses == []
        assert report.by_sector_summary == {}
        assert report.by_verdict_summary == {}
        assert report.generated_at  # non-empty ISO string

    def test_empty_month_renders_to_markdown_cleanly(self):
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning([]))
        md = to_markdown(report)
        assert "Monthly Accuracy Report" in md
        assert "2026-05" in md
        assert "Verdicts published: **0**" in md
        # The empty-state callout fires.
        assert "No verdicts were published in this month" in md


# ═════════════════════════════════════════════════════════════════
# Direction-accuracy single-row sanity checks
# ═════════════════════════════════════════════════════════════════
class TestDirectionAccuracySingle:
    def test_one_correct_undervalued_call_is_100pct(self):
        # Price 100 → 120 (+20%), undervalued → correct.
        rows = [_make_row(
            ticker="RELIANCE", verdict="undervalued",
            fair_value=130.0, price=100.0, price_30d_later=120.0,
        )]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        assert report.total_verdicts_published == 1
        assert report.coverage_count == 1
        assert report.direction_accuracy_pct == 100.0

    def test_one_wrong_overvalued_call_is_0pct(self):
        # Overvalued but price went UP — direction wrong.
        rows = [_make_row(
            ticker="HDFCBANK", verdict="overvalued",
            fair_value=80.0, price=100.0, price_30d_later=115.0,
        )]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        assert report.direction_accuracy_pct == 0.0

    def test_fairly_valued_in_band_is_correct(self):
        # +3% return inside ±10 band → correct.
        rows = [_make_row(
            ticker="INFY", verdict="fairly_valued",
            fair_value=100.0, price=100.0, price_30d_later=103.0,
        )]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        assert report.direction_accuracy_pct == 100.0


# ═════════════════════════════════════════════════════════════════
# Mixed direction — aggregation
# ═════════════════════════════════════════════════════════════════
class TestMixedDirection:
    def test_three_tickers_one_correct(self):
        rows = [
            _make_row(
                ticker="A", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,  # +20 correct
            ),
            _make_row(
                ticker="B", verdict="undervalued",
                fair_value=120, price=100, price_30d_later=95,   # -5 wrong
            ),
            _make_row(
                ticker="C", verdict="overvalued",
                fair_value=80, price=100, price_30d_later=110,   # +10 wrong
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        assert report.total_verdicts_published == 3
        assert report.coverage_count == 3
        # 1 correct out of 3 scorable → 33.33%
        assert report.direction_accuracy_pct == pytest.approx(33.33, rel=0.01)


# ═════════════════════════════════════════════════════════════════
# Missing forward price — coverage counts, accuracy stats exclude
# ═════════════════════════════════════════════════════════════════
class TestMissingForwardPrice:
    def test_missing_price_excluded_from_accuracy_but_total_counts(self):
        rows = [
            _make_row(
                ticker="WITHFWD", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,  # +20 correct
            ),
            _make_row(
                ticker="NOFWD", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=None,  # delisted/gap
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        # Total = 2 (everyone published), coverage = 1 (only one had fwd).
        assert report.total_verdicts_published == 2
        assert report.coverage_count == 1
        # Direction accuracy denominator excludes the unscored row.
        assert report.direction_accuracy_pct == 100.0


# ═════════════════════════════════════════════════════════════════
# By-sector aggregation
# ═════════════════════════════════════════════════════════════════
class TestBySectorAggregation:
    def test_two_sectors_both_present(self):
        rows = [
            _make_row(
                ticker="BANK1", sector="Banking", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,
            ),
            _make_row(
                ticker="BANK2", sector="Banking", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=90,  # wrong
            ),
            _make_row(
                ticker="TECH1", sector="IT Services", verdict="overvalued",
                fair_value=80, price=100, price_30d_later=85,  # -15 correct
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        assert set(report.by_sector_summary.keys()) == {"Banking", "IT Services"}
        bank = report.by_sector_summary["Banking"]
        assert bank["total"] == 2
        assert bank["coverage"] == 2
        # 1 out of 2 correct.
        assert bank["direction_accuracy_pct"] == 50.0
        it = report.by_sector_summary["IT Services"]
        assert it["total"] == 1
        assert it["direction_accuracy_pct"] == 100.0

    def test_missing_sector_excluded_from_buckets(self):
        rows = [
            _make_row(
                ticker="UNK", sector=None, verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))
        # Total still counts the row but sector bucket is empty.
        assert report.total_verdicts_published == 1
        assert report.by_sector_summary == {}


# ═════════════════════════════════════════════════════════════════
# By-verdict aggregation
# ═════════════════════════════════════════════════════════════════
class TestByVerdictAggregation:
    def test_each_verdict_bucket_populated(self):
        rows = [
            _make_row(
                ticker="A", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,
            ),
            _make_row(
                ticker="B", verdict="overvalued",
                fair_value=80, price=100, price_30d_later=85,
            ),
            _make_row(
                ticker="C", verdict="fairly_valued",
                fair_value=100, price=100, price_30d_later=103,
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        bucket = report.by_verdict_summary
        assert set(bucket.keys()) == {"undervalued", "overvalued", "fairly_valued"}
        for v in ("undervalued", "overvalued", "fairly_valued"):
            assert bucket[v]["total"] == 1
            assert bucket[v]["direction_accuracy_pct"] == 100.0


# ═════════════════════════════════════════════════════════════════
# Top-5 winners + misses
# ═════════════════════════════════════════════════════════════════
class TestTopFive:
    def test_winners_are_correct_direction_and_sorted_by_magnitude(self):
        rows = [
            _make_row(
                ticker="SMALL", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=110,  # +10 correct
            ),
            _make_row(
                ticker="HUGE", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=150,  # +50 correct
            ),
            _make_row(
                ticker="MID", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=125,  # +25 correct
            ),
            _make_row(
                ticker="WRONG", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=90,   # -10 wrong
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        winners = report.top_5_winners
        assert len(winners) == 3  # only correct-direction calls
        assert [w.ticker for w in winners] == ["HUGE", "MID", "SMALL"]

    def test_misses_prioritize_wrong_direction(self):
        rows = [
            _make_row(
                ticker="BIGFV_ERR", verdict="undervalued",
                fair_value=200, price=100, price_30d_later=110,  # correct dir, big FV err
            ),
            _make_row(
                ticker="WRONGDIR", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=80,   # wrong direction
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))

        misses = report.top_5_misses
        # Wrong-direction row beats large-FV-error correct-direction row.
        assert misses[0].ticker == "WRONGDIR"


# ═════════════════════════════════════════════════════════════════
# Serialization
# ═════════════════════════════════════════════════════════════════
class TestSerialization:
    def test_to_dict_shape(self):
        rows = [
            _make_row(
                ticker="RELIANCE", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))
        d = to_dict(report)

        # Top-level shape contract — what the JSON snapshot file uses.
        assert d["report_month"] == "2026-05"
        assert d["total_verdicts_published"] == 1
        assert d["coverage_count"] == 1
        assert isinstance(d["top_5_winners"], list)
        assert isinstance(d["top_5_misses"], list)
        assert isinstance(d["by_sector_summary"], dict)
        assert isinstance(d["by_verdict_summary"], dict)
        # Entries are flat dicts after asdict.
        assert d["top_5_winners"][0]["ticker"] == "RELIANCE"
        assert d["top_5_winners"][0]["verdict_at_publish"] == "undervalued"

    def test_to_markdown_contains_expected_headers(self):
        rows = [
            _make_row(
                ticker="RELIANCE", verdict="undervalued",
                fair_value=130, price=100, price_30d_later=120,
            ),
            _make_row(
                ticker="HDFCBANK", verdict="overvalued",
                fair_value=80, price=100, price_30d_later=110,
                sector="Banking",
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))
        md = to_markdown(report)

        assert "Monthly Accuracy Report" in md
        assert "Headline" in md
        assert "By verdict" in md
        assert "By sector" in md
        assert "Top 5 correct-direction calls" in md
        assert "Top 5 misses" in md
        # The headline line carries the count.
        assert "Verdicts published: **2**" in md

    def test_to_markdown_is_non_empty_string(self):
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning([]))
        md = to_markdown(report)
        assert isinstance(md, str)
        assert len(md) > 100  # at minimum a header + headline block


# ═════════════════════════════════════════════════════════════════
# Defensive: unknown verdict strings don't crash
# ═════════════════════════════════════════════════════════════════
class TestDefensiveAgainstBadInput:
    def test_unknown_verdict_counts_but_doesnt_score(self):
        rows = [
            _make_row(
                ticker="WEIRD", verdict="data_limited",
                fair_value=100, price=100, price_30d_later=110,
            ),
        ]
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))
        # The row is published, has coverage, but isn't scorable.
        assert report.total_verdicts_published == 1
        assert report.coverage_count == 1
        # Denominator was zero → 0%.
        assert report.direction_accuracy_pct == 0.0

    def test_garbage_floats_dont_crash(self):
        rows = [
            {
                "ticker": "X",
                "sector": "Banking",
                "verdict": "undervalued",
                "fair_value": "not-a-number",
                "price": 100.0,
                "mos_pct": 30.0,
                "publish_date": date(2026, 5, 15),
                "price_30d_later": 120.0,
            },
        ]
        # Should not raise.
        report = compute_monthly_accuracy("2026-05", data_provider=_provider_returning(rows))
        assert report.total_verdicts_published == 1
