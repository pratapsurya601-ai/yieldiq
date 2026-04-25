"""Tests for the in-app notifications service.

Strategy: monkey-patch `_get_raw_cursor` to return a fake psycopg2-shaped
(conn, cursor) pair backed by an in-memory list of rows. This keeps the
test suite hermetic — no DB needed — while still exercising the SQL
shapes by recording the (sql, params) tuples each call makes.

The tests for `can_receive` are pure-function and need no patching.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from backend.services import notifications_service as svc


# ── Pure-function tier-gating tests ───────────────────────────

def test_can_receive_free_tier_alert_fired_allowed():
    assert svc.can_receive("free", "alert_fired") is True


def test_can_receive_free_tier_earnings_reminder_blocked():
    assert svc.can_receive("free", "earnings_reminder") is False


def test_can_receive_pro_tier_model_update_allowed():
    assert svc.can_receive("pro", "model_update") is True


def test_can_receive_unknown_tier_falls_back_to_free():
    # Unknown tier should never accidentally surface Pro-only content.
    assert svc.can_receive("mystery", "earnings_reminder") is False
    assert svc.can_receive("mystery", "alert_fired") is True


def test_can_receive_analyst_includes_portfolio_event():
    assert svc.can_receive("analyst", "portfolio_event") is True
    assert svc.can_receive("analyst", "earnings_reminder") is False


# ── Fake DB plumbing ──────────────────────────────────────────


class _FakeCursor:
    def __init__(self, store: "_FakeStore"):
        self.store = store
        self.rowcount = 0
        self._last_result: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()):  # noqa: D401
        self.store.queries.append((sql, params))
        sql_upper = " ".join(sql.split()).upper()

        if sql_upper.startswith("INSERT INTO NOTIFICATIONS"):
            user_id, type_, title, body, link, metadata_json = params
            metadata = json.loads(metadata_json) if metadata_json else {}
            row_id = self.store.next_id
            self.store.next_id += 1
            self.store.rows.append({
                "id": row_id,
                "user_id": user_id,
                "type": type_,
                "title": title,
                "body": body,
                "link": link,
                "metadata": metadata,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
            })
            self._last_result = [(row_id,)]
            self.rowcount = 1
            return

        if sql_upper.startswith("SELECT ID, TYPE, TITLE"):
            # list_unread or list_recent
            user_id = params[0]
            limit = params[1] if len(params) > 1 else 50
            unread_only = "READ_AT IS NULL" in sql_upper
            matching = [
                r for r in self.store.rows
                if r["user_id"] == user_id and (not unread_only or r["read_at"] is None)
            ]
            matching.sort(key=lambda r: r["created_at"], reverse=True)
            matching = matching[:limit]
            self._last_result = [
                (
                    r["id"], r["type"], r["title"], r["body"], r["link"],
                    r["metadata"], r["created_at"], r["read_at"],
                )
                for r in matching
            ]
            self.rowcount = len(self._last_result)
            return

        if sql_upper.startswith("SELECT COUNT(*)"):
            user_id = params[0]
            n = sum(
                1 for r in self.store.rows
                if r["user_id"] == user_id and r["read_at"] is None
            )
            self._last_result = [(n,)]
            self.rowcount = 1
            return

        if sql_upper.startswith("UPDATE NOTIFICATIONS"):
            if "WHERE ID = %S" in sql_upper:
                # mark_read: (id, user_id)
                nid, user_id = params
                hit = 0
                for r in self.store.rows:
                    if r["id"] == nid and r["user_id"] == user_id and r["read_at"] is None:
                        r["read_at"] = datetime.now(timezone.utc)
                        hit += 1
                self.rowcount = hit
            else:
                # mark_all_read: (user_id,)
                (user_id,) = params
                hit = 0
                for r in self.store.rows:
                    if r["user_id"] == user_id and r["read_at"] is None:
                        r["read_at"] = datetime.now(timezone.utc)
                        hit += 1
                self.rowcount = hit
            return

        raise RuntimeError(f"Unrecognized SQL in fake cursor: {sql!r}")

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, store: "_FakeStore"):
        self.store = store

    def commit(self):
        self.store.commits += 1

    def rollback(self):
        self.store.rollbacks += 1

    def close(self):
        pass


class _FakeStore:
    def __init__(self):
        self.rows: list[dict[str, Any]] = []
        self.queries: list[tuple] = []
        self.next_id = 1
        self.commits = 0
        self.rollbacks = 0


@pytest.fixture
def fake_db(monkeypatch):
    store = _FakeStore()

    def _factory():
        conn = _FakeConn(store)
        cur = _FakeCursor(store)
        return conn, cur

    monkeypatch.setattr(svc, "_get_raw_cursor", _factory)
    return store


# ── Service-function tests against the fake DB ────────────────

USER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def test_create_notification_returns_int_id(fake_db):
    nid = svc.create_notification(
        user_id=USER, type="system", title="Welcome", body="Hi there",
    )
    assert isinstance(nid, int)
    assert nid >= 1
    assert len(fake_db.rows) == 1


def test_create_notification_caps_field_lengths(fake_db):
    long_title = "x" * 500
    long_body = "y" * 5000
    long_link = "z" * 2000
    nid = svc.create_notification(
        user_id=USER, type="system", title=long_title, body=long_body, link=long_link,
    )
    row = next(r for r in fake_db.rows if r["id"] == nid)
    assert len(row["title"]) == 120
    assert len(row["body"]) == 1000
    assert len(row["link"]) == 500


def test_list_unread_returns_only_unread_newest_first(fake_db):
    a = svc.create_notification(user_id=USER, type="system", title="A")
    b = svc.create_notification(user_id=USER, type="alert_fired", title="B")
    c = svc.create_notification(user_id=USER, type="system", title="C")
    # Bump created_at so order is deterministic.
    base = datetime.now(timezone.utc)
    for i, r in enumerate(fake_db.rows):
        r["created_at"] = base + timedelta(seconds=i)
    # Mark B as read.
    svc.mark_read(USER, b)

    rows = svc.list_unread(USER)
    ids = [r["id"] for r in rows]
    assert ids == [c, a]


def test_list_unread_respects_limit(fake_db):
    for i in range(10):
        svc.create_notification(user_id=USER, type="system", title=f"n{i}")
    rows = svc.list_unread(USER, limit=3)
    assert len(rows) == 3


def test_mark_read_flips_read_at_and_returns_true(fake_db):
    nid = svc.create_notification(user_id=USER, type="system", title="X")
    assert svc.mark_read(USER, nid) is True
    # Calling again returns False — already read.
    assert svc.mark_read(USER, nid) is False


def test_mark_read_does_not_cross_users(fake_db):
    nid = svc.create_notification(user_id=USER, type="system", title="X")
    # OTHER user cannot mark USER's notification.
    assert svc.mark_read(OTHER, nid) is False
    assert svc.unread_count(USER) == 1


def test_mark_all_read_returns_count_and_zeroes_unread(fake_db):
    for _ in range(5):
        svc.create_notification(user_id=USER, type="system", title="x")
    n = svc.mark_all_read(USER)
    assert n == 5
    assert svc.unread_count(USER) == 0


def test_unread_count_only_counts_user(fake_db):
    svc.create_notification(user_id=USER, type="system", title="me")
    svc.create_notification(user_id=OTHER, type="system", title="them")
    svc.create_notification(user_id=OTHER, type="system", title="them2")
    assert svc.unread_count(USER) == 1
    assert svc.unread_count(OTHER) == 2


def test_list_recent_includes_read_and_unread(fake_db):
    a = svc.create_notification(user_id=USER, type="system", title="A")
    svc.create_notification(user_id=USER, type="system", title="B")
    svc.mark_read(USER, a)
    rows = svc.list_recent(USER)
    assert len(rows) == 2
