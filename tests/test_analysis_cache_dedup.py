"""Tests for the analysis_cache dedup migration + writer canonicalization.

Background
----------
The 2026-05-16 audit found analysis_cache had 5,062 rows but only
3,141 unique tickers — every Indian symbol stored twice (FOO and
FOO.NS). These tests pin two contracts that prevent the regression:

1. The bucketing/plan logic in scripts/migrate_dedup_analysis_cache.py
   keeps the most-recent `computed_at` and renames the survivor to
   the canonical key.
2. The writer in backend.services.analysis_cache_service funnels the
   ticker through `_canonical_cache_key` BEFORE the SQL UPSERT, so
   two callers passing FOO and FOO.NS end up on the same row.

We run against an in-memory SQLite engine to keep the test
hermetic; the migration script's plan() function does not depend
on the postgres-only `jsonb_set` etc. so it ports cleanly. The
writer test monkeypatches the session factory so no real DB call
is made.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def sqlite_engine():
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE analysis_cache (
                ticker TEXT PRIMARY KEY,
                payload TEXT,
                computed_at TIMESTAMP,
                cache_version TEXT,
                compute_ms INTEGER
            )
            """
        ))
    return eng


def _seed(engine, rows):
    with engine.begin() as conn:
        for ticker, payload, computed_at in rows:
            conn.execute(
                text(
                    "INSERT INTO analysis_cache "
                    "(ticker, payload, computed_at, cache_version, compute_ms) "
                    "VALUES (:t, :p, :ca, '84', 100)"
                ),
                {"t": ticker, "p": payload, "ca": computed_at},
            )


def test_dedup_keeps_newest_and_renames_to_canonical(sqlite_engine, monkeypatch):
    """FOO (older) + FOO.NS (newer) → keep FOO.NS payload under FOO.NS key."""
    from scripts import migrate_dedup_analysis_cache as mod

    # Pretend FOO is a known Indian bare ticker so canonical is FOO.NS.
    monkeypatch.setattr(mod, "_canonicalize",
                        lambda t: f"{t}.NS" if t == "FOO" else t)

    older = datetime(2026, 5, 1, 12, 0, 0)
    newer = datetime(2026, 5, 16, 12, 0, 0)
    _seed(sqlite_engine, [
        ("FOO",    '{"fv":100}', older),
        ("FOO.NS", '{"fv":200}', newer),
        ("AAPL",   '{"fv":190}', older),  # untouched US ticker
    ])

    buckets = mod.collect_buckets(sqlite_engine)
    total, kept, deleted, actions = mod.plan(buckets)
    assert total == 3
    assert kept == 2  # FOO collapsed into FOO.NS, AAPL unchanged
    assert deleted == 1
    mod.apply_plan(sqlite_engine, actions)

    with sqlite_engine.connect() as conn:
        rows = sorted(conn.execute(
            text("SELECT ticker, payload FROM analysis_cache")
        ).fetchall())
    assert rows == [("AAPL", '{"fv":190}'), ("FOO.NS", '{"fv":200}')]


def test_dedup_idempotent_second_run_is_noop(sqlite_engine, monkeypatch):
    from scripts import migrate_dedup_analysis_cache as mod
    monkeypatch.setattr(mod, "_canonicalize",
                        lambda t: f"{t}.NS" if t == "FOO" else t)

    _seed(sqlite_engine, [
        ("FOO",    '{"fv":100}', datetime(2026, 5, 1)),
        ("FOO.NS", '{"fv":200}', datetime(2026, 5, 16)),
    ])
    mod.apply_plan(sqlite_engine, mod.plan(mod.collect_buckets(sqlite_engine))[3])

    # Second pass: nothing to do.
    total2, kept2, deleted2, actions2 = mod.plan(mod.collect_buckets(sqlite_engine))
    assert total2 == 1 and kept2 == 1 and deleted2 == 0
    # actions list may still contain trivial single-row buckets; verify
    # none of them ask for a delete or a key change.
    for canonical, surv, losers in actions2:
        assert losers == []
        assert surv == canonical


def test_dedup_keeps_bare_when_only_bare_present(sqlite_engine, monkeypatch):
    """Bare-only row gets renamed to canonical .NS form."""
    from scripts import migrate_dedup_analysis_cache as mod
    monkeypatch.setattr(mod, "_canonicalize",
                        lambda t: f"{t}.NS" if t == "FOO" else t)

    _seed(sqlite_engine, [("FOO", '{"fv":100}', datetime(2026, 5, 1))])
    _, _, _, actions = mod.plan(mod.collect_buckets(sqlite_engine))
    mod.apply_plan(sqlite_engine, actions)

    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT ticker FROM analysis_cache")).fetchall()
    assert rows == [("FOO.NS",)]


def test_writer_canonicalizes_before_upsert(monkeypatch):
    """save_cached + get_cached must funnel ticker through
    _canonical_cache_key so FOO and FOO.NS hit the same row."""
    from backend.services import analysis_cache_service as svc

    # Force canonicalize to match the audit case: FOO -> FOO.NS.
    monkeypatch.setattr(svc, "_canonical_cache_key",
                        lambda t: f"{t}.NS" if t == "FOO" else t)

    seen_keys = []

    class _FakeResult:
        def fetchone(self):
            return None

    class _FakeSess:
        def execute(self, _sql, params):
            seen_keys.append(params.get("ticker"))
            return _FakeResult()

        def commit(self):
            pass

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(svc, "_get_session", lambda: _FakeSess())
    monkeypatch.setattr(svc, "_fire_revalidate", lambda _t: None)

    svc.save_cached("FOO", {"fv": 100}, 50)
    svc.save_cached("FOO.NS", {"fv": 100}, 50)
    svc.get_cached("FOO")

    # All three calls should have used the same canonical key.
    assert seen_keys == ["FOO.NS", "FOO.NS", "FOO.NS"]
