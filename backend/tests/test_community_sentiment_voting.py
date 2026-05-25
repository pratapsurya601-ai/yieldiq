"""Week-3 manifesto: community sentiment voting widget.

Locks the contract for the three additive endpoints under
``/api/v1/public/sentiment/{ticker}``:

  1. POST  .../vote     — auth required, upserts (user,ticker), 400 on
                           bad sentiment, replaces prior vote.
  2. GET   .../          — public, aggregated counts + pct + your_vote.
  3. GET   .../history?days=N — public, daily rollup.

Avoids live Postgres by monkey-patching ``_sentiment_pg_conn`` with an
in-memory fake that mimics the columns the router selects. Keeps the
test self-contained, deterministic, and free of network/DB flake.

Ticker normalization is asserted via HDFCBANK vs HDFCBANK.NS (bare
form is what we store).
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

from backend.routers import public as public_router  # noqa: E402
from backend.middleware import auth as auth_middleware  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Fake DB layer — captures inserts in a dict keyed by (user, ticker)
# and re-emits rows in the shape the router's SELECTs expect.
# ─────────────────────────────────────────────────────────────────
class _FakeCursor:
    def __init__(self, store: dict):
        self.store = store
        self._rows: list[tuple] = []
        self.description: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()):
        sql_norm = " ".join(sql.split()).lower()
        # POST upsert
        if "insert into community_sentiment_votes" in sql_norm:
            user_id, ticker, sentiment = params
            self.store[(user_id, ticker)] = {
                "sentiment": sentiment,
                "voted_at": datetime.now(timezone.utc),
            }
            self._rows = []
            return
        # Aggregate count
        if "select sentiment, count(*)" in sql_norm:
            (ticker,) = params
            counts: dict[str, int] = {}
            for (_uid, t), row in self.store.items():
                if t != ticker:
                    continue
                counts[row["sentiment"]] = counts.get(row["sentiment"], 0) + 1
            self._rows = [(k, v) for k, v in counts.items()]
            return
        # your_vote lookup
        if "select sentiment from community_sentiment_votes" in sql_norm:
            user_id, ticker = params
            row = self.store.get((user_id, ticker))
            self._rows = [(row["sentiment"],)] if row else []
            return
        # History query
        if "group by day, sentiment" in sql_norm:
            ticker = params[0]
            agg: dict[tuple, int] = {}
            for (_uid, t), row in self.store.items():
                if t != ticker:
                    continue
                day = row["voted_at"].date()
                key = (day, row["sentiment"])
                agg[key] = agg.get(key, 0) + 1
            self._rows = [(day, sentiment, n) for (day, sentiment), n in agg.items()]
            return
        raise AssertionError(f"unexpected SQL in fake cursor: {sql_norm[:120]}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, store: dict):
        self.store = store
        self.committed = False

    def cursor(self):
        return _FakeCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def store() -> dict:
    return {}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, store: dict) -> TestClient:
    monkeypatch.setattr(
        public_router, "_sentiment_pg_conn", lambda: _FakeConn(store)
    )

    app = FastAPI()
    app.include_router(public_router.router)

    # Override auth so tests don't need a real JWT. The router only
    # touches user.get("user_id"); we provide a stable canned identity.
    async def _fake_user() -> dict:
        return {"user_id": "user-alice", "email": "alice@example.com", "tier": "free"}

    async def _fake_user_optional() -> dict:
        return {"user_id": "user-alice", "email": "alice@example.com", "tier": "free"}

    app.dependency_overrides[auth_middleware.get_current_user] = _fake_user
    app.dependency_overrides[auth_middleware.get_current_user_optional] = (
        _fake_user_optional
    )
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────
# 1. POST /vote — upsert semantics
# ─────────────────────────────────────────────────────────────────
def test_vote_upsert_replaces_prior_vote(client: TestClient, store: dict):
    r = client.post(
        "/api/v1/public/sentiment/HDFCBANK/vote",
        json={"sentiment": "bullish"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["your_vote"] == "bullish"
    assert body["bullish_count"] == 1
    assert body["total_votes"] == 1

    # Same user changes mind → vote replaces, total stays 1.
    r2 = client.post(
        "/api/v1/public/sentiment/HDFCBANK/vote",
        json={"sentiment": "bearish"},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["your_vote"] == "bearish"
    assert body2["bullish_count"] == 0
    assert body2["bearish_count"] == 1
    assert body2["total_votes"] == 1

    # The fake store carries exactly one row for (alice, HDFCBANK).
    assert list(store.keys()) == [("user-alice", "HDFCBANK")]


def test_vote_rejects_invalid_sentiment(client: TestClient):
    r = client.post(
        "/api/v1/public/sentiment/HDFCBANK/vote",
        json={"sentiment": "very_bullish"},
    )
    assert r.status_code == 400


def test_vote_normalizes_ns_suffix(client: TestClient, store: dict):
    r = client.post(
        "/api/v1/public/sentiment/HDFCBANK.NS/vote",
        json={"sentiment": "neutral"},
    )
    assert r.status_code == 200
    # Stored as bare ticker so a follow-up GET on either form aggregates.
    assert ("user-alice", "HDFCBANK") in store


# ─────────────────────────────────────────────────────────────────
# 2. GET / — aggregate counts + percentages
# ─────────────────────────────────────────────────────────────────
def test_aggregate_counts_and_percentages(client: TestClient, store: dict):
    # Seed three votes for HDFCBANK across distinct users.
    store[("u1", "HDFCBANK")] = {
        "sentiment": "bullish",
        "voted_at": datetime.now(timezone.utc),
    }
    store[("u2", "HDFCBANK")] = {
        "sentiment": "bullish",
        "voted_at": datetime.now(timezone.utc),
    }
    store[("u3", "HDFCBANK")] = {
        "sentiment": "bearish",
        "voted_at": datetime.now(timezone.utc),
    }

    r = client.get("/api/v1/public/sentiment/HDFCBANK")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_votes"] == 3
    assert body["bullish_count"] == 2
    assert body["bearish_count"] == 1
    assert body["neutral_count"] == 0
    # 2/3 = 66.7, 1/3 = 33.3
    assert body["bullish_pct"] == pytest.approx(66.7, abs=0.1)
    assert body["bearish_pct"] == pytest.approx(33.3, abs=0.1)
    assert body["neutral_pct"] == 0.0
    # Alice (the canned auth identity) hasn't voted yet on this ticker.
    assert body["your_vote"] is None


def test_aggregate_empty_returns_zero_counts(client: TestClient):
    r = client.get("/api/v1/public/sentiment/NEWCOSTOCK")
    assert r.status_code == 200
    body = r.json()
    assert body["total_votes"] == 0
    assert body["bullish_pct"] == 0.0


# ─────────────────────────────────────────────────────────────────
# 3. GET /history — daily time-series
# ─────────────────────────────────────────────────────────────────
def test_history_returns_daily_rollup(client: TestClient, store: dict):
    today = datetime.now(timezone.utc)
    store[("u1", "INFY")] = {"sentiment": "bullish", "voted_at": today}
    store[("u2", "INFY")] = {"sentiment": "bullish", "voted_at": today}
    store[("u3", "INFY")] = {
        "sentiment": "bearish",
        "voted_at": today - timedelta(days=1),
    }

    r = client.get("/api/v1/public/sentiment/INFY/history?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "INFY"
    assert body["days"] == 30
    # Two distinct days seeded → two points.
    assert len(body["points"]) == 2
    # Each point carries all three buckets (zero-filled).
    for pt in body["points"]:
        assert set(pt.keys()) >= {"date", "bullish", "neutral", "bearish"}
    # Today's bucket sums to 2 bullish.
    today_iso = today.date().isoformat()
    today_pt = next(p for p in body["points"] if p["date"] == today_iso)
    assert today_pt["bullish"] == 2
    assert today_pt["bearish"] == 0


def test_history_rejects_out_of_range_days(client: TestClient):
    r = client.get("/api/v1/public/sentiment/INFY/history?days=999")
    assert r.status_code == 422  # FastAPI Query(le=180) rejects.
