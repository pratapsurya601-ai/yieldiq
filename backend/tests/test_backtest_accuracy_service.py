"""Tests for backend.services.backtest_accuracy_service.

Pure-function tests — no DB, no network. compute_backtest_accuracy takes
an injectable ``data_provider`` so we pre-bake observation rows and
assert the math.

What this file locks:
  * Verdict bands map correctly (undervalued→below, overvalued→above,
    fairly_valued→near) and non-mappable verdicts are dropped.
  * Per-band mean/median forward return and direction hit-rate.
  * Band-return monotonicity (below > near > above).
  * MoS-decile curve splits rows into deciles and reports per-decile
    forward returns; monotonicity flag.
  * Per-sector, per-horizon stats respect min_sector_observations.
  * Multi-horizon partitioning by horizon_days.
  * low_n flagging below the threshold.
  * Empty / malformed input degrades to a well-shaped empty result.
  * Quarantine epoch + SEBI-safe vocabulary in to_dict meta + the
    absence of legacy verdict tokens on the wire.
"""
from __future__ import annotations

import pytest

from backend.services.backtest_accuracy_service import (
    EPOCH_POLICY_TEXT,
    FORWARD_HORIZONS_DAYS,
    LOW_N_THRESHOLD,
    QUARANTINE_EPOCH_DATE,
    BacktestAccuracyResult,
    compute_backtest_accuracy,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# Row factory
# ─────────────────────────────────────────────────────────────────
def _row(
    *,
    sector: str = "TestSector",
    ticker: str = "AAA",
    verdict: str = "undervalued",
    price: float = 100.0,
    forward_price: float | None = 110.0,
    mos_pct: float | None = 10.0,
    horizon_days: int = 21,
    date_str: str = "2026-05-25",
) -> dict:
    return {
        "sector": sector,
        "ticker": ticker,
        "date": date_str,
        "verdict": verdict,
        "price": price,
        "forward_price": forward_price,
        "mos_pct": mos_pct,
        "horizon_days": horizon_days,
    }


def _provider(rows: list[dict]):
    def _p(horizons):
        return list(rows)
    return _p


def _card_for(result: BacktestAccuracyResult, horizon: int):
    for c in result.horizons:
        if c.horizon_days == horizon:
            return c
    raise AssertionError(f"no horizon card for {horizon}")


def _band(card, band_name: str):
    for b in card.by_band:
        if b.band == band_name:
            return b
    raise AssertionError(f"no band {band_name}")


# ═════════════════════════════════════════════════════════════════
# Empty / defensive
# ═════════════════════════════════════════════════════════════════
class TestEmpty:
    def test_empty_provider_returns_shaped_empty(self):
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider([])
        )
        assert isinstance(res, BacktestAccuracyResult)
        assert len(res.horizons) == 1
        assert res.horizons[0].observation_count == 0
        assert res.sectors == []

    def test_provider_raises_returns_empty(self):
        def _bad(horizons):
            raise RuntimeError("DB down")
        res = compute_backtest_accuracy(horizons=(21,), data_provider=_bad)
        assert res.horizons[0].observation_count == 0

    def test_non_mappable_verdicts_dropped(self):
        rows = [
            _row(verdict="data_limited"),
            _row(verdict="avoid"),
            _row(verdict="under_review"),
        ]
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        assert res.horizons[0].observation_count == 0

    def test_missing_forward_price_dropped(self):
        rows = [_row(forward_price=None) for _ in range(5)]
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        assert res.horizons[0].observation_count == 0

    def test_zero_price_dropped(self):
        rows = [_row(price=0.0) for _ in range(5)]
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        assert res.horizons[0].observation_count == 0


# ═════════════════════════════════════════════════════════════════
# Band mapping + forward-return math
# ═════════════════════════════════════════════════════════════════
class TestBandMath:
    def test_band_mapping_and_counts(self):
        rows = (
            [_row(verdict="undervalued", ticker=f"U{i}") for i in range(4)]
            + [_row(verdict="overvalued", ticker=f"O{i}") for i in range(3)]
            + [_row(verdict="fairly_valued", ticker=f"F{i}", mos_pct=0.0,
                    forward_price=100.0) for i in range(2)]
        )
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        card = _card_for(res, 21)
        assert _band(card, "below_fair_value").observation_count == 4
        assert _band(card, "above_fair_value").observation_count == 3
        assert _band(card, "near_fair_value").observation_count == 2

    def test_median_and_mean_forward_return(self):
        # below_fair_value rows with forward returns of exactly +10% each.
        rows = [
            _row(verdict="undervalued", ticker=f"U{i}",
                 price=100.0, forward_price=110.0)
            for i in range(5)
        ]
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        below = _band(card, "below_fair_value")
        assert below.median_forward_return_pct == 10.0
        assert below.mean_forward_return_pct == 10.0

    def test_direction_hit_rate_below_band(self):
        # below_fair_value is "correct" when forward return > +5%.
        # 3 winners (+10%) + 1 loser (-10%) → 75%.
        rows = [
            _row(verdict="undervalued", ticker=f"W{i}",
                 price=100.0, forward_price=110.0)
            for i in range(3)
        ]
        rows.append(_row(verdict="undervalued", ticker="L",
                         price=100.0, forward_price=90.0))
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert _band(card, "below_fair_value").direction_hit_rate_pct == 75.0

    def test_direction_hit_rate_above_band(self):
        # above_fair_value is "correct" when forward return < -5%.
        rows = [
            _row(verdict="overvalued", ticker=f"D{i}",
                 mos_pct=-10.0, price=100.0, forward_price=85.0)
            for i in range(4)
        ]
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert _band(card, "above_fair_value").direction_hit_rate_pct == 100.0

    def test_band_monotonic_true_when_ordered(self):
        rows = (
            # below: +20%
            [_row(verdict="undervalued", ticker=f"U{i}", mos_pct=20.0,
                  price=100.0, forward_price=120.0) for i in range(3)]
            # near: 0%
            + [_row(verdict="fairly_valued", ticker=f"F{i}", mos_pct=0.0,
                    price=100.0, forward_price=100.0) for i in range(3)]
            # above: -20%
            + [_row(verdict="overvalued", ticker=f"O{i}", mos_pct=-20.0,
                    price=100.0, forward_price=80.0) for i in range(3)]
        )
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert card.band_return_monotonic is True

    def test_band_monotonic_none_when_band_empty(self):
        # Only below + near populated → cannot judge full ordering.
        rows = (
            [_row(verdict="undervalued", ticker=f"U{i}") for i in range(3)]
            + [_row(verdict="fairly_valued", ticker=f"F{i}", mos_pct=0.0,
                    forward_price=100.0) for i in range(3)]
        )
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert card.band_return_monotonic is None


# ═════════════════════════════════════════════════════════════════
# MoS-decile curve
# ═════════════════════════════════════════════════════════════════
class TestMosDecileCurve:
    def test_curve_has_ten_deciles_and_populated_counts(self):
        # 100 rows ranked by MoS → 10 deciles of 10.
        rows = []
        for i in range(100):
            mos = float(i) - 50.0  # -50 .. +49
            # construct a forward return that increases with mos so the
            # curve is monotonic.
            fwd = 100.0 * (1.0 + (mos / 100.0))
            rows.append(_row(
                ticker=f"T{i}", verdict="fairly_valued", mos_pct=mos,
                price=100.0, forward_price=fwd,
            ))
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert len(card.mos_decile_curve) == 10
        assert all(d.observation_count == 10 for d in card.mos_decile_curve)
        # avg mos increases across deciles
        avgs = [d.avg_mos_pct for d in card.mos_decile_curve]
        assert avgs == sorted(avgs)
        assert card.mos_curve_monotonic is True

    def test_curve_monotonic_false_when_inverted(self):
        rows = []
        for i in range(100):
            mos = float(i) - 50.0
            # INVERT: higher mos → lower forward return.
            fwd = 100.0 * (1.0 - (mos / 100.0))
            rows.append(_row(
                ticker=f"T{i}", verdict="fairly_valued", mos_pct=mos,
                price=100.0, forward_price=fwd,
            ))
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert card.mos_curve_monotonic is False

    def test_rows_without_mos_excluded_from_curve(self):
        rows = [
            _row(ticker=f"T{i}", verdict="undervalued", mos_pct=None)
            for i in range(10)
        ]
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        # No usable MoS → empty curve, but band stats still populated.
        assert card.mos_decile_curve == []
        assert _band(card, "below_fair_value").observation_count == 10


# ═════════════════════════════════════════════════════════════════
# Sectors
# ═════════════════════════════════════════════════════════════════
class TestSectors:
    def test_sector_below_min_excluded(self):
        rows = (
            [_row(sector="Big", ticker=f"B{i}") for i in range(20)]
            + [_row(sector="Small", ticker=f"S{i}") for i in range(3)]
        )
        res = compute_backtest_accuracy(
            horizons=(21,), min_sector_observations=15,
            data_provider=_provider(rows),
        )
        sectors = [s.sector for s in res.sectors]
        assert "Big" in sectors
        assert "Small" not in sectors

    def test_sector_hit_rate_computed(self):
        rows = [
            _row(sector="IT", ticker=f"W{i}", verdict="undervalued",
                 price=100.0, forward_price=120.0)
            for i in range(15)
        ]
        res = compute_backtest_accuracy(
            horizons=(21,), min_sector_observations=15,
            data_provider=_provider(rows),
        )
        it = [s for s in res.sectors if s.sector == "IT"]
        assert len(it) == 1
        assert it[0].direction_hit_rate_pct == 100.0


# ═════════════════════════════════════════════════════════════════
# Multi-horizon
# ═════════════════════════════════════════════════════════════════
class TestHorizons:
    def test_rows_partitioned_by_horizon(self):
        rows = (
            [_row(ticker=f"A{i}", horizon_days=21) for i in range(5)]
            + [_row(ticker=f"B{i}", horizon_days=90) for i in range(3)]
        )
        res = compute_backtest_accuracy(
            horizons=(21, 90), data_provider=_provider(rows)
        )
        assert _card_for(res, 21).observation_count == 5
        assert _card_for(res, 90).observation_count == 3

    def test_empty_horizon_is_correct_but_empty(self):
        rows = [_row(horizon_days=21) for _ in range(5)]
        res = compute_backtest_accuracy(
            horizons=(21, 180), data_provider=_provider(rows)
        )
        assert _card_for(res, 180).observation_count == 0
        assert _card_for(res, 180).overall_direction_hit_rate_pct is None


# ═════════════════════════════════════════════════════════════════
# low_n flagging
# ═════════════════════════════════════════════════════════════════
class TestLowN:
    def test_low_n_flag_below_threshold(self):
        rows = [_row(ticker=f"T{i}") for i in range(LOW_N_THRESHOLD - 1)]
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert _band(card, "below_fair_value").low_n is True

    def test_not_low_n_at_threshold(self):
        rows = [_row(ticker=f"T{i}") for i in range(LOW_N_THRESHOLD)]
        card = _card_for(
            compute_backtest_accuracy(horizons=(21,), data_provider=_provider(rows)),
            21,
        )
        assert _band(card, "below_fair_value").low_n is False


# ═════════════════════════════════════════════════════════════════
# to_dict shape + SEBI vocabulary
# ═════════════════════════════════════════════════════════════════
class TestToDict:
    def test_shape_and_meta(self):
        rows = [_row(ticker=f"T{i}") for i in range(5)]
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        out = to_dict(res, horizons=(21,), min_sector_observations=15)
        assert "horizons" in out
        assert "sectors" in out
        assert "meta" in out
        meta = out["meta"]
        assert meta["quarantine_epoch_date"] == QUARANTINE_EPOCH_DATE
        assert meta["epoch_policy"] == EPOCH_POLICY_TEXT
        assert meta["forward_horizons_days"] == [21]
        assert meta["low_n_threshold"] == LOW_N_THRESHOLD
        assert "statistical_power_note" in meta
        assert set(meta["bands"]) == {
            "below_fair_value", "near_fair_value", "above_fair_value",
        }

    def test_empty_to_dict_well_shaped(self):
        out = to_dict(BacktestAccuracyResult())
        assert out["horizons"] == []
        assert out["sectors"] == []
        assert out["meta"]["total_evaluable_observations"] == 0

    def test_no_legacy_verdict_tokens_on_wire(self):
        # The serialized payload must never carry the legacy
        # under/over-valued tokens — only the SEBI-safe band names.
        import json
        rows = (
            [_row(verdict="undervalued", ticker=f"U{i}") for i in range(3)]
            + [_row(verdict="overvalued", ticker=f"O{i}", mos_pct=-10.0,
                    forward_price=90.0) for i in range(3)]
        )
        res = compute_backtest_accuracy(
            horizons=(21,), data_provider=_provider(rows)
        )
        blob = json.dumps(to_dict(res, horizons=(21,)))
        legacy = "under" + "valued"
        legacy2 = "over" + "valued"
        assert legacy not in blob
        assert legacy2 not in blob


# ═════════════════════════════════════════════════════════════════
# Default horizons sanity
# ═════════════════════════════════════════════════════════════════
class TestDefaults:
    def test_default_horizons_include_required_windows(self):
        # The strategic brief asks for 30/90/180; we additionally carry
        # 21 as the early-signal proxy.
        assert 30 in FORWARD_HORIZONS_DAYS
        assert 90 in FORWARD_HORIZONS_DAYS
        assert 180 in FORWARD_HORIZONS_DAYS
        assert 21 in FORWARD_HORIZONS_DAYS
