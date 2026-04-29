# tests/test_band_alert_service.py
# ═══════════════════════════════════════════════════════════════
# Hermetic tests for backend.services.band_alert_service.
#
# We monkeypatch _get_cursor to return a fake (conn, cursor) pair
# backed by an in-memory list, so the tests run without Postgres
# (CI / dev laptops with no DATABASE_URL).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from typing import Any

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import band_alert_service as bas


# ── Fake DB ───────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, store: dict):
        self.store = store
        self._last: list[Any] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_norm = " ".join(sql.split()).lower()
        if sql_norm.startswith("insert into valuation_band_history"):
            ticker, band, percentile, cohort, sector = params
            self.store["band_history"].append({
                "ticker": ticker, "band": band, "percentile": percentile,
                "cohort_size": cohort, "sector_label": sector,
            })
            self.rowcount = 1
            return
        if sql_norm.startswith("select band from valuation_band_history"):
            ticker = params[0]
            rows = [
                (r["band"],) for r in reversed(self.store["band_history"])
                if r["ticker"] == ticker
            ][:2]
            self._last = rows
            return
        if sql_norm.startswith("select distinct user_email from watchlist"):
            ticker = params[0]
            self._last = [
                (u,) for u in self.store["watchlist"].get(ticker, [])
            ]
            return
        if sql_norm.startswith("insert into band_alerts"):
            uid, ticker, fb, tb = params
            row = {
                "id": len(self.store["band_alerts"]) + 1,
                "user_id": uid, "ticker": ticker,
                "from_band": fb, "to_band": tb,
                "delivered_email": False, "delivered_push": False,
                "user_dismissed": False,
            }
            self.store["band_alerts"].append(row)
            self.rowcount = 1
            return
        if sql_norm.startswith("select id, ticker, from_band, to_band"):
            uid = params[0]
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            self._last = [
                (r["id"], r["ticker"], r["from_band"], r["to_band"], now,
                 r["delivered_email"], r["delivered_push"], r["user_dismissed"])
                for r in self.store["band_alerts"] if r["user_id"] == uid
            ]
            return
        if sql_norm.startswith("update band_alerts set user_dismissed"):
            alert_id, uid = params
            for r in self.store["band_alerts"]:
                if r["id"] == alert_id and r["user_id"] == uid:
                    r["user_dismissed"] = True
                    self.rowcount = 1
                    return
            self.rowcount = 0
            return
        # Unknown query — return empty.
        self._last = []

    def fetchall(self) -> list:
        return self._last

    def fetchone(self):
        return self._last[0] if self._last else None

    def close(self) -> None:
        pass


class FakeConn:
    def __init__(self, store: dict):
        self.store = store

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def fake_db(monkeypatch):
    store = {
        "band_history": [],
        "band_alerts": [],
        "watchlist": {},  # ticker -> [emails]
    }
    conn = FakeConn(store)

    def _fake_get_cursor():
        return conn, conn.cursor()

    monkeypatch.setattr(bas, "_get_cursor", _fake_get_cursor)

    # Stub notifications_service.create_notification — we don't want to
    # cross the module boundary in unit tests.
    monkeypatch.setattr(
        "backend.services.notifications_service.create_notification",
        lambda **kw: 1,
    )
    return store


# ── Tests ─────────────────────────────────────────────────────

def test_record_band_inserts_row(fake_db):
    ok = bas.record_band_for_ticker("INFY", "in_range", 50, 25, "IT")
    assert ok is True
    assert len(fake_db["band_history"]) == 1
    assert fake_db["band_history"][0]["ticker"] == "INFY"
    assert fake_db["band_history"][0]["band"] == "in_range"


def test_record_band_uppercases_ticker(fake_db):
    bas.record_band_for_ticker("infy", "in_range", 50, 25, "IT")
    assert fake_db["band_history"][0]["ticker"] == "INFY"


def test_detect_shift_returns_none_with_zero_or_one_history(fake_db):
    assert bas.detect_band_shift("INFY") is None
    bas.record_band_for_ticker("INFY", "in_range", 50, 25, "IT")
    assert bas.detect_band_shift("INFY") is None


def test_detect_shift_returns_none_when_band_unchanged(fake_db):
    bas.record_band_for_ticker("INFY", "in_range", 50, 25, "IT")
    bas.record_band_for_ticker("INFY", "in_range", 55, 25, "IT")
    assert bas.detect_band_shift("INFY") is None


def test_detect_shift_returns_dict_when_band_changed(fake_db):
    bas.record_band_for_ticker("INFY", "in_range", 50, 25, "IT")
    bas.record_band_for_ticker("INFY", "below_peers", 25, 25, "IT")
    shift = bas.detect_band_shift("INFY")
    assert shift == {"from_band": "in_range", "to_band": "below_peers"}


def test_detect_shift_ignores_data_limited_transitions(fake_db):
    # Going from data_limited -> in_range is not a real shift.
    bas.record_band_for_ticker("INFY", "data_limited", None, 5, "IT")
    bas.record_band_for_ticker("INFY", "in_range", 50, 25, "IT")
    # data_limited isn't allowed by the _REAL_BANDS gate — and the
    # record path itself accepts it, but detect_band_shift filters it.
    assert bas.detect_band_shift("INFY") is None


def test_fire_alerts_inserts_one_row_per_watchlister(fake_db):
    fake_db["watchlist"]["INFY"] = ["alice@example.com", "bob@example.com"]
    n = bas.fire_alerts_for_shift("INFY", "in_range", "below_peers")
    assert n == 2
    assert len(fake_db["band_alerts"]) == 2
    assert {r["user_id"] for r in fake_db["band_alerts"]} == {
        "alice@example.com", "bob@example.com",
    }


def test_fire_alerts_zero_when_no_watchlisters(fake_db):
    n = bas.fire_alerts_for_shift("INFY", "in_range", "below_peers")
    assert n == 0
    assert fake_db["band_alerts"] == []


def test_record_and_maybe_fire_full_flow(fake_db):
    fake_db["watchlist"]["INFY"] = ["alice@example.com"]
    # First call: only records, no shift yet.
    out1 = bas.record_and_maybe_fire("INFY", "in_range", 50, 25, "IT")
    assert out1 is None
    # Second call same band: still no shift.
    out2 = bas.record_and_maybe_fire("INFY", "in_range", 55, 25, "IT")
    assert out2 is None
    # Third call: band shifts -> alert fires.
    out3 = bas.record_and_maybe_fire("INFY", "below_peers", 25, 25, "IT")
    assert out3 is not None
    assert out3["from_band"] == "in_range"
    assert out3["to_band"] == "below_peers"
    assert out3["notified_users"] == 1
    assert len(fake_db["band_alerts"]) == 1


def test_list_recent_for_user_returns_only_their_alerts(fake_db):
    fake_db["band_alerts"].append({
        "id": 1, "user_id": "alice@example.com", "ticker": "INFY",
        "from_band": "in_range", "to_band": "below_peers",
        "delivered_email": False, "delivered_push": False, "user_dismissed": False,
    })
    fake_db["band_alerts"].append({
        "id": 2, "user_id": "bob@example.com", "ticker": "TCS",
        "from_band": "above_peers", "to_band": "in_range",
        "delivered_email": False, "delivered_push": False, "user_dismissed": False,
    })
    items = bas.list_recent_for_user("alice@example.com")
    assert len(items) == 1
    assert items[0]["ticker"] == "INFY"
    assert items[0]["from_label"] == "In peer range"
    assert items[0]["to_label"] == "Below peer range"


def test_dismiss_alert_sets_flag(fake_db):
    fake_db["band_alerts"].append({
        "id": 1, "user_id": "alice@example.com", "ticker": "INFY",
        "from_band": "in_range", "to_band": "below_peers",
        "delivered_email": False, "delivered_push": False, "user_dismissed": False,
    })
    ok = bas.dismiss_alert("alice@example.com", 1)
    assert ok is True
    assert fake_db["band_alerts"][0]["user_dismissed"] is True


def test_dismiss_alert_other_user_returns_false(fake_db):
    fake_db["band_alerts"].append({
        "id": 1, "user_id": "alice@example.com", "ticker": "INFY",
        "from_band": "in_range", "to_band": "below_peers",
        "delivered_email": False, "delivered_push": False, "user_dismissed": False,
    })
    ok = bas.dismiss_alert("bob@example.com", 1)
    assert ok is False


def test_human_band_label():
    assert bas._human_band("in_range") == "In peer range"
    assert bas._human_band("strong_discount") == "Notable discount to peers"
    assert bas._human_band("notably_overvalued") == "Notable premium to peers"
