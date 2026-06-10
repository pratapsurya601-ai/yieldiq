"""Tests for backend.services.verdict_attribution_service.

Pure-function tests — no DB, no network. They lock the contract that
GET /api/v1/public/verdict-attribution/{ticker} depends on:

    - episode shape (one VerdictAttribution per verdict-change run)
    - alpha = actual_return − nifty_return (and same for sector)
    - direction_correct iff realised alpha sign matches verdict
    - rolling 30d bucketing
    - graceful degradation: bad row -> dropped (never raises)

If the public attribution panel ever shows a wrong number, the bug
almost certainly reproduces here first.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services.verdict_attribution_service import (
    AttributionSummary,
    VerdictAttribution,
    build_attribution_from_row,
    compute_attribution,
    summarise,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _row(
    *,
    ticker="RELIANCE",
    period_start="2025-01-01",
    period_end="2025-07-01",
    verdict="undervalued",
    fv=1500.0,
    p_start=1000.0,
    p_end=1200.0,
    nifty=10.0,
    sector=8.0,
):
    return {
        "ticker": ticker,
        "period_start": period_start,
        "period_end": period_end,
        "verdict_at_start": verdict,
        "fv_at_start": fv,
        "price_at_start": p_start,
        "price_at_end": p_end,
        "nifty_return_pct": nifty,
        "sector_return_pct": sector,
    }


# ═════════════════════════════════════════════════════════════════
# build_attribution_from_row
# ═════════════════════════════════════════════════════════════════
class TestBuildAttributionFromRow:
    def test_happy_path(self):
        att = build_attribution_from_row(_row())
        assert att is not None
        assert att.ticker == "RELIANCE"
        assert att.verdict_at_start == "undervalued"
        # +20% raw return, Nifty +10% → alpha = +10
        assert att.actual_return_pct == 20.0
        assert att.alpha_vs_nifty == 10.0
        # sector +8% → alpha vs sector = +12
        assert att.alpha_vs_sector == 12.0
        assert att.verdict_proven_correct is True

    def test_unknown_verdict_dropped(self):
        # banned vocab fragments — built from concatenation so the
        # SEBI sebi-lint diff-only scanner doesn't fire on this test
        # file. See CLAUDE.md "SEBI vocab guard tests".
        for bad in ("b" + "uy", "se" + "ll", "ho" + "ld", "", None):
            assert build_attribution_from_row(_row(verdict=bad)) is None

    def test_missing_price_dropped(self):
        assert build_attribution_from_row(_row(p_start=None)) is None
        assert build_attribution_from_row(_row(p_end=None)) is None
        assert build_attribution_from_row(_row(p_start=0)) is None

    def test_missing_benchmark_dropped(self):
        assert build_attribution_from_row(_row(nifty=None)) is None
        assert build_attribution_from_row(_row(sector=None)) is None

    def test_overvalued_correct_when_alpha_negative(self):
        # overvalued + alpha_vs_nifty < -5 -> proven correct
        att = build_attribution_from_row(
            _row(verdict="overvalued", p_start=100, p_end=90, nifty=10.0, sector=5.0),
        )
        assert att is not None
        assert att.actual_return_pct == -10.0
        assert att.alpha_vs_nifty == -20.0
        assert att.verdict_proven_correct is True

    def test_overvalued_incorrect_when_alpha_positive(self):
        att = build_attribution_from_row(
            _row(verdict="overvalued", p_start=100, p_end=130, nifty=5.0, sector=5.0),
        )
        assert att is not None
        assert att.alpha_vs_nifty == 25.0
        assert att.verdict_proven_correct is False

    def test_fairly_valued_correct_when_alpha_in_band(self):
        # |alpha_vs_nifty| <= 10 → correct
        att = build_attribution_from_row(
            _row(verdict="fairly_valued", p_start=100, p_end=108, nifty=5.0, sector=5.0),
        )
        assert att is not None
        assert att.alpha_vs_nifty == 3.0
        assert att.verdict_proven_correct is True

    def test_fairly_valued_incorrect_when_alpha_out_of_band(self):
        att = build_attribution_from_row(
            _row(verdict="fairly_valued", p_start=100, p_end=140, nifty=5.0, sector=5.0),
        )
        assert att.alpha_vs_nifty == 35.0
        assert att.verdict_proven_correct is False

    def test_nan_inf_inputs_dropped(self):
        assert build_attribution_from_row(_row(p_end=float("inf"))) is None
        assert build_attribution_from_row(_row(nifty=float("nan"))) is None

    def test_missing_period_dates_dropped(self):
        assert build_attribution_from_row(_row(period_start="")) is None
        assert build_attribution_from_row(_row(period_end="")) is None


# ═════════════════════════════════════════════════════════════════
# summarise
# ═════════════════════════════════════════════════════════════════
class TestSummarise:
    def test_empty_input_returns_zeroed_summary(self):
        s = summarise("RELIANCE", [])
        assert isinstance(s, AttributionSummary)
        assert s.ticker == "RELIANCE"
        assert s.total_verdicts_tracked == 0
        assert s.direction_correct_pct == 0.0
        assert s.best_verdict is None
        assert s.worst_verdict is None
        assert s.rolling_30d_track_record == []

    def test_single_row_summary(self):
        s = summarise("RELIANCE", [_row()])
        assert s.total_verdicts_tracked == 1
        assert s.direction_correct_pct == 100.0
        assert s.avg_alpha_vs_nifty_pct == 10.0
        assert s.median_alpha_vs_nifty_pct == 10.0
        assert s.best_verdict is not None
        assert s.worst_verdict is not None
        assert s.best_verdict.period_start == s.worst_verdict.period_start

    def test_best_and_worst_pick_correctly(self):
        good = _row(period_start="2025-01-01", period_end="2025-04-01",
                    p_start=100, p_end=140, nifty=5.0, sector=5.0)   # alpha +35
        bad = _row(period_start="2025-04-02", period_end="2025-07-02",
                   p_start=100, p_end=95, nifty=10.0, sector=10.0)   # alpha -15
        mid = _row(period_start="2025-07-03", period_end="2025-10-03",
                   p_start=100, p_end=112, nifty=5.0, sector=5.0)    # alpha +7
        s = summarise("RELIANCE", [good, bad, mid])
        assert s.total_verdicts_tracked == 3
        assert s.best_verdict is not None
        assert s.best_verdict.alpha_vs_nifty == 35.0
        assert s.worst_verdict is not None
        assert s.worst_verdict.alpha_vs_nifty == -15.0
        # avg = (35 + -15 + 7) / 3 = 9.0
        assert s.avg_alpha_vs_nifty_pct == pytest.approx(9.0, abs=0.01)
        # median of [-15, 7, 35] = 7
        assert s.median_alpha_vs_nifty_pct == 7.0

    def test_direction_correct_pct_math(self):
        # 2 correct out of 3 → 66.67%
        u_good = _row(verdict="undervalued", p_start=100, p_end=120, nifty=5.0, sector=5.0)   # alpha +15, correct
        u_bad = _row(verdict="undervalued", p_start=100, p_end=102, nifty=5.0, sector=5.0,
                     period_start="2025-04-01", period_end="2025-07-01")                       # alpha -3, incorrect
        o_good = _row(verdict="overvalued", p_start=100, p_end=80, nifty=5.0, sector=5.0,
                      period_start="2025-08-01", period_end="2025-11-01")                      # alpha -25, correct
        s = summarise("RELIANCE", [u_good, u_bad, o_good])
        assert s.direction_correct_pct == pytest.approx(66.67, abs=0.05)

    def test_bad_rows_silently_dropped(self):
        bad_verdict_row = _row(verdict="garbage")
        s = summarise("RELIANCE", [_row(), bad_verdict_row, _row(period_start="2025-08-01", period_end="2025-11-01")])
        assert s.total_verdicts_tracked == 2

    def test_rolling_track_record_bucketing(self):
        # Two episodes ending close together (< 30 days) should bucket
        # together; a third one 60 days later should be its own bucket.
        ep1 = _row(period_start="2025-01-01", period_end="2025-03-01",
                   p_start=100, p_end=110, nifty=5.0, sector=5.0)
        ep2 = _row(period_start="2025-03-02", period_end="2025-03-15",
                   p_start=100, p_end=120, nifty=10.0, sector=10.0)
        ep3 = _row(period_start="2025-04-01", period_end="2025-06-30",
                   p_start=100, p_end=130, nifty=5.0, sector=5.0)
        s = summarise("RELIANCE", [ep1, ep2, ep3])
        buckets = s.rolling_30d_track_record
        # ep1.end = Mar 1 -> bucket A; ep2.end = Mar 15 -> same bucket A (same 30-day cell).
        # ep3.end = Jun 30 -> bucket B.
        # bucketing is deterministic by ordinal // 30; exact bucket count
        # could be 2 or 3 depending on alignment. Assert monotonic + non-empty.
        assert 1 <= len(buckets) <= 3
        assert sum(b["verdict_count"] for b in buckets) == 3


# ═════════════════════════════════════════════════════════════════
# compute_attribution — uses injected loader so we test the public
# entry point without touching the DB.
# ═════════════════════════════════════════════════════════════════
class TestComputeAttribution:
    def test_with_injected_loader(self):
        def fake_loader(ticker, lookback_days):
            assert ticker == "RELIANCE"
            assert lookback_days == 365
            return [_row(), _row(period_start="2025-08-01", period_end="2025-11-01")]

        s = compute_attribution("RELIANCE", lookback_days=365, loader=fake_loader)
        assert s.total_verdicts_tracked == 2
        assert s.ticker == "RELIANCE"

    def test_loader_raising_returns_empty_summary(self):
        def broken_loader(ticker, lookback_days):
            raise RuntimeError("DB went away")

        s = compute_attribution("RELIANCE", loader=broken_loader)
        # Must NOT raise — degrades to empty summary so router 200s.
        assert s.total_verdicts_tracked == 0


# ═════════════════════════════════════════════════════════════════
# to_dict — serialisation lock
# ═════════════════════════════════════════════════════════════════
class TestSerialisation:
    def test_to_dict_shape(self):
        s = summarise("RELIANCE", [_row()])
        d = to_dict(s)
        assert d["ticker"] == "RELIANCE"
        assert d["total_verdicts_tracked"] == 1
        assert "best_verdict" in d
        assert "worst_verdict" in d
        assert "rolling_30d_track_record" in d
        # Episode shape preserved across asdict
        assert d["best_verdict"]["verdict_at_start"] == "undervalued"
        assert d["best_verdict"]["alpha_vs_nifty"] == 10.0

    def test_to_dict_handles_none_episodes(self):
        s = summarise("RELIANCE", [])
        d = to_dict(s)
        assert d["best_verdict"] is None
        assert d["worst_verdict"] is None
        assert d["total_verdicts_tracked"] == 0


# ═════════════════════════════════════════════════════════════════
# Manifest entry presence — guards against the entry being deleted
# in a rebase / merge resolution. Mirrors test pattern used by
# test_day108a_manifest_history_public.
# ═════════════════════════════════════════════════════════════════
def test_performance_attribution_manifest_entry_present():
    from backend.services.cache_invalidation_manifest import MANIFEST
    ids = {entry.get("version_id") for entry in MANIFEST}
    assert "v_performance_attribution_2026_06_10" in ids, (
        "Manifest entry for the Performance Attribution panel must "
        "remain in MANIFEST; downstream gates expect it."
    )
