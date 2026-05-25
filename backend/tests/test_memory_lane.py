"""Phase 4 manifesto (Paradigm 11): Memory Lane endpoints.

Locks the contract for the three additive endpoints under
``/api/v1/me/`` (router: backend/routers/me.py):

  1. POST /ticker-visit/{ticker}        — upsert visit, snapshot price/FV on
                                          first call, bump counters thereafter.
  2. GET  /memory-lane/{ticker}         — return personal history payload,
                                          204 when no prior visit.
  3. PUT  /memory-lane/{ticker}/note    — save personal note, 404 when no
                                          prior visit.

Avoids live Postgres by monkey-patching ``_pg_conn`` with an in-memory
fake that mimics the columns the router selects. Avoids live
analysis_cache by monkey-patching ``_fetch_current_snapshot`` with a
deterministic stub.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import me as me_router  # noqa: E402
from backend.middleware import auth as auth_middleware  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Fake DB layer
# ─────────────────────────────────────────────────────────────────
class _FakeCursor:
    def __init__(self, store: dict):
        self.store = store
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()):
        s = " ".join(sql.split()).lower()

        if "insert into user_ticker_visits" in s:
            (
                user_id, ticker,
                price, fv, verdict,
            ) = params
            key = (user_id, ticker)
            existing = self.store.get(key)
            if existing is None:
                self.store[key] = {
                    "first_visited_at": datetime.now(timezone.utc),
                    "last_visited_at": datetime.now(timezone.utc),
                    "visit_count": 1,
                    "price_at_first_visit": price,
                    "fair_value_at_first_visit": fv,
                    "verdict_at_first_visit": verdict,
                    "user_note": None,
                }
                self._rows = [(True,)]  # xmax = 0 → inserted
            else:
                existing["last_visited_at"] = datetime.now(timezone.utc)
                existing["visit_count"] += 1
                self._rows = [(False,)]
            return

        if "select first_visited_at" in s:
            user_id, ticker = params
            row = self.store.get((user_id, ticker))
            if row is None:
                self._rows = []
            else:
                self._rows = [(
                    row["first_visited_at"],
                    row["last_visited_at"],
                    row["visit_count"],
                    row["price_at_first_visit"],
                    row["fair_value_at_first_visit"],
                    row["verdict_at_first_visit"],
                    row["user_note"],
                )]
            return

        if "update user_ticker_visits" in s:
            note, user_id, ticker = params
            row = self.store.get((user_id, ticker))
            if row is None:
                self._rows = []
            else:
                row["user_note"] = note
                self._rows = [(1,)]  # returning id
            return

        raise AssertionError(f"unexpected SQL in fake cursor: {s[:120]}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, store: dict):
        self.store = store

    def cursor(self):
        return _FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def store() -> dict:
    return {}


@pytest.fixture()
def snapshot() -> dict:
    """Mutable holder so individual tests can re-tune the 'current' snapshot."""
    return {
        "current_price": 786.0,
        "current_fair_value": 1131.0,
        "current_verdict": "undervalued",
    }


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    store: dict,
    snapshot: dict,
) -> TestClient:
    monkeypatch.setattr(me_router, "_pg_conn", lambda: _FakeConn(store))
    monkeypatch.setattr(
        me_router, "_fetch_current_snapshot", lambda ticker_bare: dict(snapshot)
    )

    app = FastAPI()
    app.include_router(me_router.router)

    async def _fake_user() -> dict:
        return {"user_id": "user-alice", "email": "alice@example.com", "tier": "free"}

    app.dependency_overrides[auth_middleware.get_current_user] = _fake_user
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────
# POST /ticker-visit
# ─────────────────────────────────────────────────────────────────
def test_first_visit_captures_snapshot_and_reports_first_visit(
    client: TestClient, store: dict, snapshot: dict
):
    snapshot["current_price"] = 720.0
    snapshot["current_fair_value"] = 1054.0
    snapshot["current_verdict"] = "undervalued"

    r = client.post("/api/v1/me/ticker-visit/HDFCBANK.NS")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "first_visit": True}

    # Stored as bare ticker with the snapshot frozen in.
    row = store[("user-alice", "HDFCBANK")]
    assert row["visit_count"] == 1
    assert row["price_at_first_visit"] == 720.0
    assert row["fair_value_at_first_visit"] == 1054.0
    assert row["verdict_at_first_visit"] == "undervalued"


def test_subsequent_visit_bumps_count_and_preserves_snapshot(
    client: TestClient, store: dict, snapshot: dict
):
    # Seed a "first visit" snapshot.
    snapshot["current_price"] = 720.0
    snapshot["current_fair_value"] = 1054.0
    client.post("/api/v1/me/ticker-visit/HDFCBANK")

    # Move the snapshot forward and revisit — snapshot must NOT change.
    snapshot["current_price"] = 999.0
    snapshot["current_fair_value"] = 1200.0
    r = client.post("/api/v1/me/ticker-visit/HDFCBANK")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "first_visit": False}

    row = store[("user-alice", "HDFCBANK")]
    assert row["visit_count"] == 2
    assert row["price_at_first_visit"] == 720.0   # frozen
    assert row["fair_value_at_first_visit"] == 1054.0  # frozen


# ─────────────────────────────────────────────────────────────────
# GET /memory-lane
# ─────────────────────────────────────────────────────────────────
def test_memory_lane_204_when_no_prior_visit(client: TestClient):
    r = client.get("/api/v1/me/memory-lane/HDFCBANK")
    assert r.status_code == 204
    assert r.text == ""


def test_memory_lane_payload_computes_deltas_and_hypothetical(
    client: TestClient, store: dict
):
    # Seed a first-visit row 47 days ago, by hand.
    forty_seven_days_ago = datetime.now(timezone.utc) - timedelta(days=47)
    store[("user-alice", "HDFCBANK")] = {
        "first_visited_at": forty_seven_days_ago,
        "last_visited_at": datetime.now(timezone.utc),
        "visit_count": 12,
        "price_at_first_visit": 720.0,
        "fair_value_at_first_visit": 1054.0,
        "verdict_at_first_visit": "undervalued",
        "user_note": None,
    }
    # Snapshot fixture defaults: price 786, FV 1131.
    r = client.get("/api/v1/me/memory-lane/HDFCBANK")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "HDFCBANK.NS"
    assert body["days_ago"] == 47
    assert body["visit_count"] == 12
    assert body["price_at_first_visit"] == 720.0
    assert body["fair_value_at_first_visit"] == 1054.0
    assert body["current_price"] == 786.0
    assert body["current_fair_value"] == 1131.0
    # (786-720)/720*100 = 9.166 → 9.2
    assert body["price_delta_pct"] == pytest.approx(9.2, abs=0.1)
    # (1131-1054)/1054*100 = 7.305 → 7.3
    assert body["fv_delta_pct"] == pytest.approx(7.3, abs=0.1)
    # 10_000 * 786 / 720 = 10916.67 → rounded to 10917
    assert body["hypothetical_10k_value"] == pytest.approx(10917, abs=1)


def test_memory_lane_handles_missing_first_visit_price(
    client: TestClient, store: dict
):
    """When the cache had no entry on first visit, deltas/hypothetical
    return None gracefully rather than throwing or computing garbage."""
    store[("user-alice", "INFY")] = {
        "first_visited_at": datetime.now(timezone.utc) - timedelta(days=5),
        "last_visited_at": datetime.now(timezone.utc),
        "visit_count": 1,
        "price_at_first_visit": None,
        "fair_value_at_first_visit": None,
        "verdict_at_first_visit": None,
        "user_note": None,
    }
    r = client.get("/api/v1/me/memory-lane/INFY")
    assert r.status_code == 200
    body = r.json()
    assert body["price_delta_pct"] is None
    assert body["fv_delta_pct"] is None
    assert body["hypothetical_10k_value"] is None


# ─────────────────────────────────────────────────────────────────
# Pure-function unit checks (deltas / days / hypothetical)
# ─────────────────────────────────────────────────────────────────
def test_pct_delta_handles_edge_cases():
    assert me_router._pct_delta(None, 100) is None
    assert me_router._pct_delta(100, None) is None
    assert me_router._pct_delta(0, 100) is None  # divide-by-zero guard
    assert me_router._pct_delta(100, 110) == 10.0
    assert me_router._pct_delta(100, 90) == -10.0


def test_hypothetical_10k_value():
    # ₹10,000 at ₹720 → 13.888 shares → 13.888 × ₹786 = ₹10,916.67 → 10917
    assert me_router._hypothetical_10k(720.0, 786.0) == pytest.approx(10917, abs=1)
    assert me_router._hypothetical_10k(None, 786.0) is None
    assert me_router._hypothetical_10k(720.0, None) is None
    assert me_router._hypothetical_10k(0, 786.0) is None


def test_days_between_floors_at_zero():
    future = datetime.now(timezone.utc) + timedelta(days=5)
    assert me_router._days_between(future) == 0
    past = datetime.now(timezone.utc) - timedelta(days=47, hours=3)
    assert me_router._days_between(past) == 47


def test_norm_visit_ticker_strips_exchange_suffix():
    assert me_router._norm_visit_ticker("HDFCBANK.NS") == "HDFCBANK"
    assert me_router._norm_visit_ticker("hdfcbank") == "HDFCBANK"
    assert me_router._norm_visit_ticker(" infy.bo ") == "INFY"


# ─────────────────────────────────────────────────────────────────
# PUT /note
# ─────────────────────────────────────────────────────────────────
def test_note_save_round_trips(client: TestClient, store: dict):
    # Seed a visit first.
    client.post("/api/v1/me/ticker-visit/HDFCBANK")

    r = client.put(
        "/api/v1/me/memory-lane/HDFCBANK/note",
        json={"note": "Watching the NIM trajectory after the merger."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user_note"] == "Watching the NIM trajectory after the merger."

    # GET reflects the saved note.
    r2 = client.get("/api/v1/me/memory-lane/HDFCBANK")
    assert r2.status_code == 200
    assert r2.json()["user_note"] == "Watching the NIM trajectory after the merger."


def test_note_save_404_without_prior_visit(client: TestClient):
    r = client.put(
        "/api/v1/me/memory-lane/NEVERSEEN/note",
        json={"note": "hello"},
    )
    assert r.status_code == 404


def test_note_empty_string_clears_note(client: TestClient, store: dict):
    client.post("/api/v1/me/ticker-visit/HDFCBANK")
    client.put(
        "/api/v1/me/memory-lane/HDFCBANK/note",
        json={"note": "initial"},
    )
    r = client.put(
        "/api/v1/me/memory-lane/HDFCBANK/note",
        json={"note": "   "},
    )
    assert r.status_code == 200
    assert r.json()["user_note"] is None
