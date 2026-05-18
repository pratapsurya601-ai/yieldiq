"""Tests for `scripts/run_cache_cleanup.py`.

The production script targets Postgres (`ANY(:versions)` array, JSONB
payload). For these tests we shim against in-memory SQLite to keep
the suite pure-offline. We:

  * monkeypatch the script's `_build_engine` to return a SQLite engine
    against an in-memory DB pre-loaded with a SQLite-compatible
    mirror of the analysis_cache table.
  * override the DELETE statement path indirectly by swapping in a
    SQLite-friendly DELETE (the `= ANY(:versions)` syntax does not
    exist in SQLite). We do this by patching `text` at module level
    for the DELETE call only — simpler: we patch `run` to call a
    SQLite-compatible deleter. Cleanest: patch `sqlalchemy.text` is
    too broad. So we provide a thin shim that intercepts the ANY(...)
    statement and rewrites it to `IN (...)`.

Test matrix per the PR brief:
  1. Older versions exist + current → older removed, current kept.
  2. Only current version exists → no-op (zero deletions).
  3. Empty table → no-op.
  4. KEEP_PREVIOUS=2 grace buffer: current + prev 2 retained,
     anything older deleted.
  5. Non-numeric junk `cache_version` rows are pruned (not in keep set).
  6. `compute_keep_set` unit test for the keep-N math.
"""
from __future__ import annotations

import os
from typing import Iterable

import pytest
from sqlalchemy import create_engine, text

from scripts import run_cache_cleanup


# SQLite-compatible mirror of `analysis_cache`. JSONB → TEXT, TIMESTAMPTZ → TEXT.
_TEST_SCHEMA_SQL = """
CREATE TABLE analysis_cache (
    ticker        TEXT PRIMARY KEY,
    payload       TEXT NOT NULL,
    computed_at   TEXT NOT NULL DEFAULT '2026-05-18T00:00:00Z',
    cache_version TEXT NOT NULL,
    compute_ms    INTEGER
);
"""


class _SqliteEngineShim:
    """Wraps a SQLite engine and rewrites Postgres-only `ANY(:versions)`
    DELETE syntax into SQLite-friendly literal `IN (...)` on the fly.

    Necessary because the production query uses
    `WHERE cache_version = ANY(:versions)` which SQLite does not parse.
    """

    def __init__(self, engine):
        self._engine = engine

    def connect(self):
        return self._engine.connect()

    def begin(self):
        return _BeginShim(self._engine.begin())


class _BeginShim:
    def __init__(self, ctx):
        self._ctx = ctx
        self._conn = None

    def __enter__(self):
        self._conn = self._ctx.__enter__()
        return _ConnShim(self._conn)

    def __exit__(self, *a):
        return self._ctx.__exit__(*a)


class _ConnShim:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, stmt, params=None):
        # Rewrite the Postgres ANY-array DELETE into a SQLite IN(...).
        sql = str(stmt)
        if "= ANY(:versions)" in sql and params and "versions" in params:
            versions = list(params["versions"])
            if not versions:
                # Nothing to delete; return a zero-rowcount sentinel.
                return _EmptyResult()
            placeholders = ",".join(f":v{i}" for i in range(len(versions)))
            new_sql = sql.replace("= ANY(:versions)", f"IN ({placeholders})")
            new_params = {f"v{i}": v for i, v in enumerate(versions)}
            return self._conn.execute(text(new_sql), new_params)
        if params is None:
            return self._conn.execute(stmt)
        return self._conn.execute(stmt, params)


class _EmptyResult:
    rowcount = 0


@pytest.fixture()
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as conn:
        conn.exec_driver_sql(_TEST_SCHEMA_SQL)

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")  # bypass guard
    monkeypatch.setattr(run_cache_cleanup, "_build_engine", lambda: _SqliteEngineShim(eng))
    return eng


def _insert_rows(eng, rows: Iterable[tuple[str, str]]) -> None:
    with eng.begin() as conn:
        for ticker, version in rows:
            conn.execute(
                text(
                    "INSERT INTO analysis_cache (ticker, payload, cache_version) "
                    "VALUES (:t, :p, :v)"
                ),
                {"t": ticker, "p": "{}", "v": version},
            )


def _count(eng) -> int:
    with eng.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM analysis_cache")).scalar() or 0


def _versions(eng) -> set[str]:
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT cache_version FROM analysis_cache")).fetchall()
    return {r[0] for r in rows}


# ── compute_keep_set unit tests ──────────────────────────────────────────


def test_compute_keep_set_basic():
    keep = run_cache_cleanup.compute_keep_set(["100", "101", "102", "103"], keep_previous=2)
    assert keep == {"101", "102", "103"}


def test_compute_keep_set_drops_non_numeric():
    keep = run_cache_cleanup.compute_keep_set(["100", "101", "102", "junk"], keep_previous=2)
    assert keep == {"100", "101", "102"}
    assert "junk" not in keep


def test_compute_keep_set_empty():
    assert run_cache_cleanup.compute_keep_set([], keep_previous=2) == set()


def test_compute_keep_set_fewer_than_keep_n():
    # Only 2 versions exist, keep_previous=5 → keep both.
    keep = run_cache_cleanup.compute_keep_set(["10", "11"], keep_previous=5)
    assert keep == {"10", "11"}


# ── integration tests against in-memory SQLite ───────────────────────────


def test_older_versions_exist_plus_current_older_removed(sqlite_engine):
    # current=105; rows under 100, 101, 102, 103, 104, 105 exist.
    rows = [
        ("AAA", "100"),
        ("BBB", "101"),
        ("CCC", "102"),
        ("DDD", "103"),
        ("EEE", "104"),
        ("FFF", "105"),
    ]
    _insert_rows(sqlite_engine, rows)
    assert _count(sqlite_engine) == 6

    deleted = run_cache_cleanup.run(dry_run=False, keep_previous=2)

    # keep set: {105, 104, 103} → delete 100, 101, 102 → 3 rows.
    assert deleted == 3
    assert _count(sqlite_engine) == 3
    assert _versions(sqlite_engine) == {"103", "104", "105"}


def test_only_current_version_exists_is_noop(sqlite_engine):
    _insert_rows(sqlite_engine, [("AAA", "105"), ("BBB", "105"), ("CCC", "105")])
    assert _count(sqlite_engine) == 3

    deleted = run_cache_cleanup.run(dry_run=False, keep_previous=2)

    assert deleted == 0
    assert _count(sqlite_engine) == 3
    assert _versions(sqlite_engine) == {"105"}


def test_empty_table_is_noop(sqlite_engine):
    assert _count(sqlite_engine) == 0
    deleted = run_cache_cleanup.run(dry_run=False, keep_previous=2)
    assert deleted == 0
    assert _count(sqlite_engine) == 0


def test_junk_cache_version_is_pruned(sqlite_engine):
    # Non-numeric versions never enter the keep set → always pruned
    # when a numeric current version exists.
    _insert_rows(
        sqlite_engine,
        [
            ("AAA", "105"),
            ("BBB", "104"),
            ("CCC", "garbage"),
            ("DDD", ""),
        ],
    )
    deleted = run_cache_cleanup.run(dry_run=False, keep_previous=2)
    assert deleted == 2  # garbage + ''
    assert _versions(sqlite_engine) == {"104", "105"}


def test_dry_run_reports_without_deleting(sqlite_engine):
    _insert_rows(sqlite_engine, [("AAA", "100"), ("BBB", "105")])
    would_delete = run_cache_cleanup.run(dry_run=True, keep_previous=2)
    # keep_previous=2 + current → keep top 3, only 2 versions exist, both kept
    # so 0 would be deleted.
    assert would_delete == 0
    assert _count(sqlite_engine) == 2

    # Now with keep_previous=0 (current-only), version 100 must be pruned.
    would_delete = run_cache_cleanup.run(dry_run=True, keep_previous=0)
    assert would_delete == 1
    # Row count unchanged (dry-run).
    assert _count(sqlite_engine) == 2
