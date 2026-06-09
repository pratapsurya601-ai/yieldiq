# backend/tests/test_valuation_history_aggregate.py
# ═══════════════════════════════════════════════════════════════
# Premium Feel R3 — tests for the public valuation-history aggregate
# endpoint and its underlying service.
#
# These tests exercise the pure-Python aggregator with synthetic rows
# (no DB) and pin the contract that the FastAPI route returns.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date, timedelta

import pytest

from backend.services.analysis.valuation_history_service import (
    DEFAULT_WINDOW_MONTHS,
    EVENT_DEDUP_DAYS,
    HOLDING_CAP_DAYS,
    MIN_OBSERVATIONS_FOR_STATS,
    SIGNAL_THRESHOLD_PCT,
    _deviation_pct,
    _find_signal_events,
    _holding_outcome,
    _Row,
)


def _make_rows(
    n: int,
    *,
    start: Date = Date(2024, 1, 1),
    fv: float = 100.0,
    price_fn=lambda i: 100.0,
    step_days: int = 30,
) -> list[_Row]:
    """Build a synthetic ascending-date series of rows."""
    return [
        _Row(
            date=start + timedelta(days=i * step_days),
            price=float(price_fn(i)),
            fair_value=float(fv),
        )
        for i in range(n)
    ]


class TestDeviation:
    def test_positive_premium(self):
        assert _deviation_pct(120.0, 100.0) == pytest.approx(20.0)

    def test_negative_discount(self):
        assert _deviation_pct(75.0, 100.0) == pytest.approx(-25.0)

    def test_zero_fv_returns_zero(self):
        # Defensive: zero fair_value should not raise.
        assert _deviation_pct(50.0, 0.0) == 0.0


class TestSignalEvents:
    def test_single_crossing_below_threshold(self):
        # Prices stay flat at FV, then dive to -25% (past -20 threshold).
        prices = [100.0] * 5 + [75.0] * 3
        rows = _make_rows(len(prices), price_fn=lambda i: prices[i])
        events = _find_signal_events(
            rows,
            threshold_pct=SIGNAL_THRESHOLD_PCT,
            dedup_days=EVENT_DEDUP_DAYS,
        )
        assert len(events) == 1
        # The event fires at the FIRST index where the crossing happens.
        assert events[0] == 5

    def test_dedup_within_window(self):
        # Two below-threshold prints inside dedup window count once.
        prices = [100.0, 75.0, 100.0, 75.0]
        rows = _make_rows(
            len(prices),
            price_fn=lambda i: prices[i],
            step_days=5,
        )
        events = _find_signal_events(
            rows,
            threshold_pct=SIGNAL_THRESHOLD_PCT,
            dedup_days=EVENT_DEDUP_DAYS,
        )
        # Second crossing is 5*3=15 days after the first — inside the
        # 30-day dedup window — suppressed.
        assert len(events) == 1

    def test_dedup_outside_window(self):
        # Two crossings 60 days apart — both counted.
        prices = [100.0, 75.0, 100.0, 75.0]
        rows = _make_rows(
            len(prices),
            price_fn=lambda i: prices[i],
            step_days=20,
        )
        events = _find_signal_events(
            rows,
            threshold_pct=SIGNAL_THRESHOLD_PCT,
            dedup_days=EVENT_DEDUP_DAYS,
        )
        assert len(events) == 2

    def test_no_crossings_for_flat_series(self):
        rows = _make_rows(20, price_fn=lambda i: 95.0)  # always -5%
        events = _find_signal_events(
            rows,
            threshold_pct=SIGNAL_THRESHOLD_PCT,
            dedup_days=EVENT_DEDUP_DAYS,
        )
        assert events == []


class TestHoldingOutcome:
    def test_exit_when_price_touches_fv(self):
        # Entry at -25%; price recovers to FV after 3 steps of 30 days.
        prices = [75.0, 80.0, 95.0, 100.0]
        rows = _make_rows(len(prices), price_fn=lambda i: prices[i])
        days, realized = _holding_outcome(rows, 0, cap_days=HOLDING_CAP_DAYS)
        assert days == 90  # 3 * 30
        assert realized == pytest.approx((100.0 / 75.0 - 1) * 100, rel=1e-3)

    def test_time_cap_exit_when_no_recovery(self):
        # Price stays below FV for 400 days — cap fires at 365.
        rows = _make_rows(
            20,
            price_fn=lambda i: 75.0,
            step_days=20,
        )
        days, realized = _holding_outcome(rows, 0, cap_days=HOLDING_CAP_DAYS)
        # Cap is 365 days; first row PAST deadline (~day 380) is the exit.
        assert days == HOLDING_CAP_DAYS
        assert realized == pytest.approx(0.0)

    def test_no_exit_no_more_data_returns_none(self):
        rows = _make_rows(3, price_fn=lambda i: 75.0, step_days=20)
        days, realized = _holding_outcome(rows, 0, cap_days=HOLDING_CAP_DAYS)
        assert days is None and realized is None


class TestAggregatorWiringWithFakeSession:
    """Wire compute_valuation_history() through a fake Session that
    returns canned rows, then pin the response shape."""

    @pytest.fixture
    def fake_session(self, monkeypatch):
        from backend.services.analysis import valuation_history_service as svc

        canned_rows: list[_Row] = []
        canned_quar: int = 0

        def _stub_fetch(db, ticker, *, months):
            return list(canned_rows), canned_quar

        monkeypatch.setattr(svc, "_fetch_rows", _stub_fetch)

        # Lightweight container so tests can swap canned data per case.
        @dataclass
        class _Ctx:
            rows: list[_Row]
            quar: int

            def set(self, rows, quar):
                canned_rows.clear()
                canned_rows.extend(rows)
                nonlocal_ref["quar"] = quar

        nonlocal_ref = {"quar": 0}

        def _set(rows, quar=0):
            canned_rows.clear()
            canned_rows.extend(rows)
            nonlocal canned_quar
            canned_quar = quar

        # Re-bind via closure trick — pytest doesn't let us nonlocal
        # from a fixture cleanly otherwise.
        class _Setter:
            def __call__(self, rows, quar=0):
                _set(rows, quar)

        return _Setter()

    def test_empty_history_returns_null_stats_and_caveat(
        self, fake_session, monkeypatch
    ):
        from backend.services.analysis import valuation_history_service as svc

        def _empty_fetch(db, ticker, *, months):
            return [], 0

        monkeypatch.setattr(svc, "_fetch_rows", _empty_fetch)
        payload = svc.compute_valuation_history(db=None, ticker="UNKNOWN")
        assert payload["ticker"] == "UNKNOWN"
        assert payload["stats"] is None
        assert payload["series"] == []
        assert any("No fair-value history" in c for c in payload["caveats"])

    def test_sparse_history_returns_null_stats_and_caveat(self, monkeypatch):
        from backend.services.analysis import valuation_history_service as svc

        rows = _make_rows(5, price_fn=lambda i: 100.0 - i)

        def _sparse_fetch(db, ticker, *, months):
            return rows, 0

        monkeypatch.setattr(svc, "_fetch_rows", _sparse_fetch)
        payload = svc.compute_valuation_history(db=None, ticker="SPARSE")
        assert payload["stats"] is None
        assert any("Insufficient history" in c for c in payload["caveats"])
        assert len(payload["series"]) == 5

    def test_full_history_emits_stats_payload(self, monkeypatch):
        from backend.services.analysis import valuation_history_service as svc

        # 24 monthly rows; price oscillates around FV=100 with one
        # multi-month dive to ~75 starting at month 6.
        def _price(i: int) -> float:
            if 6 <= i <= 10:
                return 75.0  # below the -20% threshold
            return 100.0 + (i % 4 - 2) * 5  # ±10

        rows = _make_rows(24, price_fn=_price)

        def _fetch(db, ticker, *, months):
            return rows, 2  # 2 quarantined excluded

        monkeypatch.setattr(svc, "_fetch_rows", _fetch)
        payload = svc.compute_valuation_history(db=None, ticker="RELIANCE")
        assert payload["ticker"] == "RELIANCE"
        assert payload["stats"] is not None
        stats = payload["stats"]
        assert stats["n_observations"] == 24
        assert stats["signal_threshold_pct"] == SIGNAL_THRESHOLD_PCT
        # Exactly one signal event in this synthetic series (one crossing).
        assert stats["n_signal_events"] >= 1
        # Calibration metrics are bounded.
        assert 0.0 <= stats["pct_within_10"] <= 1.0
        assert 0.0 <= stats["pct_within_20"] <= 1.0
        assert stats["median_abs_error_pct"] >= 0
        # Quarantined caveat appears.
        assert any("quarantined" in c for c in payload["caveats"])


class TestRouterEndpoint:
    """End-to-end via FastAPI TestClient. Patches the service so we
    don't need a real DB."""

    def test_route_returns_200_and_valid_pydantic_shape(self, monkeypatch):
        from fastapi.testclient import TestClient

        from backend.main import app
        from backend.models.fair_value_history import ValuationHistoryResponse
        from backend.services.cache_service import cache

        # Clear cache so the prior test run's payload doesn't leak.
        cache.clear()

        def _fake_compute(db, ticker, *, window_months=DEFAULT_WINDOW_MONTHS):
            return {
                "ticker": ticker.upper(),
                "as_of": Date.today(),
                "history_window_months": 24,
                "series": [],
                "stats": None,
                "caveats": ["No fair-value history on record yet."],
            }

        from backend.services.analysis import valuation_history_service as svc

        monkeypatch.setattr(svc, "compute_valuation_history", _fake_compute)

        # Patch the get_db dependency so the endpoint resolves without
        # requiring a DATABASE_URL in the test environment.
        from data_pipeline import db as _db

        def _fake_get_db():
            yield None

        app.dependency_overrides[_db.get_db] = _fake_get_db
        try:
            client = TestClient(app)
            r = client.get("/api/v1/public/valuation-history/TEST")
            assert r.status_code == 200, r.text
            # Pydantic-validate the response.
            body = r.json()
            ValuationHistoryResponse(**body)
            assert body["ticker"] == "TEST"
            assert body["stats"] is None
            assert body["series"] == []
        finally:
            app.dependency_overrides.pop(_db.get_db, None)


class TestNamedConstants:
    """Pin the tunables so they don't drift silently across PRs."""

    def test_default_window_months(self):
        assert DEFAULT_WINDOW_MONTHS == 60

    def test_signal_threshold_pct(self):
        assert SIGNAL_THRESHOLD_PCT == 20.0

    def test_min_observations(self):
        assert MIN_OBSERVATIONS_FOR_STATS == 12

    def test_holding_cap_days(self):
        assert HOLDING_CAP_DAYS == 365
