"""Tests for backend/services/page_view_service.py.

Strategy mirrors test_notifications.py: monkey-patch ``_get_raw_cursor``
to return a fake (conn, cursor) pair backed by an in-memory list. We
record the (sql, params) tuples so we can assert INSERT shape, and we
replay rows back through SELECTs for the read-path tests.

No DB required — the service module is exercised in full.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from backend.services import page_view_service as svc


# ── Fake DB plumbing ──────────────────────────────────────────


class _FakeStore:
    def __init__(self):
        self.rows: list[dict] = []
        self.queries: list[tuple[str, tuple]] = []
        self.next_id = 1


class _FakeCursor:
    def __init__(self, store: _FakeStore):
        self.store = store
        self.rowcount = 0
        self._last_result: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()):
        self.store.queries.append((sql, tuple(params)))
        sql_upper = " ".join(sql.split()).upper()

        if sql_upper.startswith("INSERT INTO USER_PAGE_VIEWS"):
            user_email, page_kind, ticker, path, ua, ref = params
            self.store.rows.append({
                "id": self.store.next_id,
                "user_email": user_email,
                "page_kind": page_kind,
                "ticker": ticker,
                "path": path,
                "viewed_at": datetime.now(timezone.utc),
                "user_agent": ua,
                "referrer": ref,
            })
            self.store.next_id += 1
            self.rowcount = 1
            self._last_result = []
            return

        if sql_upper.startswith("SELECT ID, USER_EMAIL, PAGE_KIND"):
            email, days_str = params
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_str))
            matched = [
                r for r in self.store.rows
                if r["user_email"] == email and r["viewed_at"] > cutoff
            ]
            matched.sort(key=lambda r: r["viewed_at"], reverse=True)
            self._last_result = [
                (r["id"], r["user_email"], r["page_kind"], r["ticker"],
                 r["path"], r["viewed_at"], r["user_agent"], r["referrer"])
                for r in matched[:1000]
            ]
            self.rowcount = len(self._last_result)
            return

        if sql_upper.startswith("DELETE FROM USER_PAGE_VIEWS"):
            (days_str,) = params
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_str))
            before = len(self.store.rows)
            self.store.rows = [r for r in self.store.rows if r["viewed_at"] >= cutoff]
            self.rowcount = before - len(self.store.rows)
            return

        if sql_upper.startswith("SELECT COUNT(*)"):
            (days_str,) = params
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(days_str))
            n = sum(1 for r in self.store.rows if r["viewed_at"] < cutoff)
            self._last_result = [(n,)]
            self.rowcount = 1
            return

        raise AssertionError(f"unexpected SQL in test: {sql_upper[:80]}")

    def fetchone(self):
        return self._last_result[0] if self._last_result else None

    def fetchall(self):
        return list(self._last_result)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    store = _FakeStore()
    cur = _FakeCursor(store)
    conn = _FakeConn(cur)
    monkeypatch.setattr(svc, "_get_raw_cursor", lambda: (conn, cur))
    return store


# ── record_page_view ──────────────────────────────────────────


def test_record_skips_anonymous(fake_db):
    svc.record_page_view(
        user_email=None, page_kind="analysis", ticker="INFY.NS", path="/analysis/INFY",
    )
    svc.record_page_view(
        user_email="", page_kind="analysis", ticker="INFY.NS", path="/analysis/INFY",
    )
    assert fake_db.rows == []
    assert fake_db.queries == []  # never even touched the DB


def test_record_inserts_with_expected_shape(fake_db):
    svc.record_page_view(
        user_email="a@b.com",
        page_kind="analysis",
        ticker="INFY.NS",
        path="/analysis/INFY",
        user_agent="UA/1.0",
        referrer="https://example.com",
    )
    assert len(fake_db.rows) == 1
    row = fake_db.rows[0]
    assert row["user_email"] == "a@b.com"
    assert row["page_kind"] == "analysis"
    assert row["ticker"] == "INFY.NS"
    assert row["path"] == "/analysis/INFY"
    assert row["user_agent"] == "UA/1.0"
    assert row["referrer"] == "https://example.com"
    # Verify exact SQL shape
    sql, params = fake_db.queries[0]
    assert "INSERT INTO user_page_views" in sql
    assert params == (
        "a@b.com", "analysis", "INFY.NS", "/analysis/INFY",
        "UA/1.0", "https://example.com",
    )


def test_record_rejects_unknown_kind_and_downgrades_to_other(fake_db):
    svc.record_page_view(
        user_email="a@b.com",
        page_kind="bogus_kind",
        ticker=None,
        path="/x",
    )
    assert len(fake_db.rows) == 1
    assert fake_db.rows[0]["page_kind"] == "other"


def test_record_truncates_long_fields(fake_db):
    svc.record_page_view(
        user_email="a@b.com",
        page_kind="analysis",
        ticker="X" * 100,
        path="/" + ("a" * 1000),
        user_agent="U" * 1000,
        referrer="R" * 1000,
    )
    row = fake_db.rows[0]
    assert len(row["ticker"]) <= 32
    assert len(row["path"]) <= 500
    assert len(row["user_agent"]) <= 500
    assert len(row["referrer"]) <= 500


def test_record_empty_path_is_skipped(fake_db):
    svc.record_page_view(
        user_email="a@b.com", page_kind="analysis", ticker="INFY.NS", path="",
    )
    assert fake_db.rows == []


def test_record_swallows_db_exceptions(monkeypatch, fake_db):
    # Patch cursor.execute to blow up — the caller must NEVER see it.
    def _boom(*a, **k):
        raise RuntimeError("simulated DB outage")
    # Find the cursor — fake_db gives us the store; replace via factory.
    store = _FakeStore()
    cur = _FakeCursor(store)
    conn = _FakeConn(cur)
    cur.execute = _boom  # type: ignore[assignment]
    monkeypatch.setattr(svc, "_get_raw_cursor", lambda: (conn, cur))
    # No exception should propagate.
    svc.record_page_view(
        user_email="a@b.com", page_kind="analysis", ticker="INFY.NS", path="/x",
    )


# ── recent_views_by_user ──────────────────────────────────────


def test_recent_views_returns_only_target_user(fake_db):
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="A", path="/a")
    svc.record_page_view(user_email="c@d.com", page_kind="analysis", ticker="B", path="/b")
    svc.record_page_view(user_email="a@b.com", page_kind="watchlist", ticker=None, path="/w")
    rows = svc.recent_views_by_user("a@b.com", days=30)
    assert len(rows) == 2
    assert {r["user_email"] for r in rows} == {"a@b.com"}
    # Newest-first ordering
    assert rows[0]["viewed_at"] >= rows[1]["viewed_at"]


def test_recent_views_filters_by_window(fake_db):
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="A", path="/a")
    # Backdate the row by 40 days.
    fake_db.rows[0]["viewed_at"] = datetime.now(timezone.utc) - timedelta(days=40)
    rows = svc.recent_views_by_user("a@b.com", days=30)
    assert rows == []


def test_recent_views_empty_email_returns_empty(fake_db):
    assert svc.recent_views_by_user("", days=30) == []


# ── activity_summary ──────────────────────────────────────────


def test_activity_summary_aggregates_kinds_and_tickers(fake_db):
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="INFY.NS", path="/a/INFY")
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="INFY.NS", path="/a/INFY")
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="TCS.NS", path="/a/TCS")
    svc.record_page_view(user_email="a@b.com", page_kind="portfolio_analyze", ticker=None, path="/p")

    summary = svc.activity_summary("a@b.com", days=30)
    assert summary["user_email"] == "a@b.com"
    assert summary["total_views"] == 4
    assert summary["by_page_kind"] == {"analysis": 3, "portfolio_analyze": 1}
    assert summary["by_ticker"] == {"INFY.NS": 2, "TCS.NS": 1}
    assert summary["first_view"] is not None
    assert summary["last_view"] is not None
    assert len(summary["views"]) == 4


def test_activity_summary_no_views_returns_zero_shape(fake_db):
    summary = svc.activity_summary("ghost@example.com", days=30)
    assert summary["total_views"] == 0
    assert summary["by_page_kind"] == {}
    assert summary["by_ticker"] == {}
    assert summary["first_view"] is None
    assert summary["last_view"] is None
    assert summary["views"] == []


# ── prune_older_than ──────────────────────────────────────────


def test_prune_deletes_only_old_rows(fake_db):
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="A", path="/a")
    svc.record_page_view(user_email="a@b.com", page_kind="analysis", ticker="B", path="/b")
    # Backdate the first.
    fake_db.rows[0]["viewed_at"] = datetime.now(timezone.utc) - timedelta(days=45)
    deleted = svc.prune_older_than(days=30)
    assert deleted == 1
    assert len(fake_db.rows) == 1
    assert fake_db.rows[0]["ticker"] == "B"
