"""Unit tests for scripts/backfill_mf_nav.py — DB-driven resume.

The full-universe NAV backfill is capped at 350 min in CI and resumes by
re-dispatch. The resume mechanism is ``--skip-existing``: the funds_table
loader must exclude schemes that already have NAV rows so a re-dispatch
does only net-new work (the checkpoint-cache approach silently lost state
on a timeout-cancellation, restarting from scheme 1). These tests pin the
SQL branch.

Imported via importlib-from-path so the test does not depend on the
repo-root ``scripts`` package being importable (it is shadowed by
``backend/scripts`` under pytest's default rootdir — a known collection
quirk). psycopg2 is faked in sys.modules so the test runs without the
real driver installed.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKFILL_PATH = REPO_ROOT / "scripts" / "backfill_mf_nav.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "backfill_mf_nav_under_test", BACKFILL_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_fake_psycopg2(monkeypatch, captured: dict, rows):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, *args):
            captured["sql"] = sql

        def fetchall(self):
            return rows

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def close(self):
            captured["closed"] = True

    fake = types.ModuleType("psycopg2")
    fake.connect = lambda *a, **k: FakeConn()
    monkeypatch.setitem(sys.modules, "psycopg2", fake)


def test_skip_existing_uses_not_exists(monkeypatch):
    captured: dict = {}
    _install_fake_psycopg2(monkeypatch, captured, [("100033",), ("118989",)])
    mod = _load_module()

    out = mod._load_funds_table_schemes("postgresql://x", skip_existing=True)

    assert out == ["100033", "118989"]
    sql = captured["sql"]
    assert "NOT EXISTS" in sql
    assert "fund_nav_history" in sql
    # Must key on a NAV row OLDER than a recency threshold, not "any row":
    # the daily cron gives every scheme today's row, so "any row" skips the
    # whole universe (the bug this guards). Require the date-range filter.
    assert "nav_date" in sql
    assert "make_interval" in sql or "interval" in sql.lower()
    assert captured.get("closed") is True


def test_default_loads_all_without_filter(monkeypatch):
    captured: dict = {}
    _install_fake_psycopg2(monkeypatch, captured, [("100033",)])
    mod = _load_module()

    out = mod._load_funds_table_schemes("postgresql://x")

    assert out == ["100033"]
    assert "NOT EXISTS" not in captured["sql"]


def test_skip_existing_flag_threads_through_to_loader(monkeypatch):
    # Guard the wiring: main() must pass args.skip_existing to the loader,
    # not silently drop it. We stub the loader and assert the kwarg.
    captured: dict = {}
    _install_fake_psycopg2(monkeypatch, captured, [])
    mod = _load_module()

    seen: dict = {}

    def fake_loader(db_url, skip_existing=False):
        seen["skip_existing"] = skip_existing
        return []

    monkeypatch.setattr(mod, "_load_funds_table_schemes", fake_loader)
    monkeypatch.setattr(mod, "_funds_row_count", lambda db_url: 1)

    # --dry-run with no DATABASE_URL: main() skips the funds-count guard
    # and reaches the (stubbed) loader directly. _funds_row_count is
    # stubbed too so a DATABASE_URL present in the CI env can't divert us.
    rc = mod.main([
        "--schemes-source", "funds_table",
        "--source", "mfapi",
        "--skip-existing",
        "--dry-run",
    ])
    assert seen.get("skip_existing") is True
    assert rc == 0
