"""Unit tests for scripts/weekly_ratio_history_maintenance.py.

Synthetic-only — no live DB. Drives ``run()`` with an injected
``rebuild_fn`` and ``dry_db=True`` so we exercise the audit ->
flag -> rebuild loop without psycopg2.
"""
from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import audit_ratio_history as ara  # type: ignore[import-not-found]
import weekly_ratio_history_maintenance as wrm  # type: ignore[import-not-found]


def _read_csv(p: Path) -> list[dict]:
    with p.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_run_dry_db_flags_all_missing_and_writes_csv(tmp_path):
    """With dry_db=True every ticker has no rows → all flagged 'missing'."""
    calls: list[tuple[str, bool]] = []

    def fake_rebuild(ticker, dsn, *, dry_run):
        calls.append((ticker, dry_run))
        return 0, ""

    out = tmp_path / "out.csv"
    rc = wrm.run(
        tickers=["AAA", "BBB", "CCC"],
        dsn=None,
        apply=False,
        rate=0,  # no throttle in tests
        out_csv=out,
        dry_db=True,
        rebuild_fn=fake_rebuild,
    )
    assert rc == 0
    rows = _read_csv(out)
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC"}
    # Each row was missing → each was attempted in dry-run
    assert all(c[1] is True for c in calls)
    assert {c[0] for c in calls} == {"AAA", "BBB", "CCC"}
    assert all(r["pre_flags"] == "missing" for r in rows)
    assert all(r["rebuilt"] == "yes" for r in rows)


def test_run_apply_calls_rebuild_with_dry_run_false(tmp_path):
    seen: list[bool] = []

    def fake_rebuild(ticker, dsn, *, dry_run):
        seen.append(dry_run)
        return 0, ""

    out = tmp_path / "out.csv"
    rc = wrm.run(
        tickers=["XYZ"],
        dsn="postgres://fake",
        apply=True,
        rate=0,
        out_csv=out,
        dry_db=True,  # synthetic flag eval, but apply=True for rebuild_fn
        rebuild_fn=fake_rebuild,
    )
    assert rc == 0
    assert seen == [False]


def test_run_failure_threshold_triggers_nonzero_exit(tmp_path):
    """If >10% of rebuilds fail, exit code is 1."""
    def fake_rebuild(ticker, dsn, *, dry_run):
        # Fail every rebuild → 100% failure → exit 1
        return 1, "synthetic failure"

    out = tmp_path / "out.csv"
    rc = wrm.run(
        tickers=[f"T{i:03d}" for i in range(20)],
        dsn=None,
        apply=False,
        rate=0,
        out_csv=out,
        dry_db=True,
        rebuild_fn=fake_rebuild,
    )
    assert rc == 1


def test_run_under_failure_threshold_returns_zero(tmp_path):
    """1 failure out of 20 = 5%, under the 10% threshold → exit 0."""
    counter = {"n": 0}

    def fake_rebuild(ticker, dsn, *, dry_run):
        counter["n"] += 1
        if counter["n"] == 1:
            return 1, "first one fails"
        return 0, ""

    out = tmp_path / "out.csv"
    rc = wrm.run(
        tickers=[f"T{i:03d}" for i in range(20)],
        dsn=None,
        apply=False,
        rate=0,
        out_csv=out,
        dry_db=True,
        rebuild_fn=fake_rebuild,
    )
    assert rc == 0


def test_run_no_tickers_returns_two(tmp_path):
    rc = wrm.run(
        tickers=[],
        dsn=None,
        apply=False,
        rate=0,
        out_csv=tmp_path / "out.csv",
        dry_db=True,
        rebuild_fn=lambda *a, **kw: (0, ""),
    )
    assert rc == 2


def test_csv_columns_include_pre_post_fields(tmp_path):
    out = tmp_path / "out.csv"
    wrm.run(
        tickers=["AAA"],
        dsn=None,
        apply=False,
        rate=0,
        out_csv=out,
        dry_db=True,
        rebuild_fn=lambda *a, **kw: (0, ""),
    )
    rows = _read_csv(out)
    assert rows
    expected = {
        "ticker", "pre_flags", "pre_period_end", "pre_pe_ratio",
        "post_flags", "post_period_end", "post_pe_ratio",
        "rebuilt", "remediation_hint",
    }
    assert set(rows[0].keys()) == expected


def test_audit_universe_uses_evaluate_row(tmp_path, monkeypatch):
    """The maintenance script delegates flag logic to the audit's
    ``evaluate_row`` — verify by feeding a sub-1 PE row."""
    today = date.today()
    recent = today - timedelta(days=10)

    def fake_fetch(dsn, tickers):
        return [("HCLTECH", recent, 0.30, 15.0, 4.5, 22.0, 28.0)]

    monkeypatch.setattr(ara, "fetch_latest_rows", fake_fetch)

    rows = wrm._audit_universe(["HCLTECH"], "postgres://fake", dry_db=False)
    assert len(rows) == 1
    assert "sub_one_pe" in rows[0].flags


def test_extend_audit_all_active_flag_exists():
    """Backward-compat check: the new --all-active flag must parse."""
    args = ara._parse_args(["--all-active", "--dry-db"])
    assert args.all_active is True
    # Existing behaviour preserved when flag absent.
    args2 = ara._parse_args([])
    assert args2.all_active is False


def test_audit_resolve_tickers_limit_truncates():
    args = type("A", (), {})()
    args.tickers = "A,B,C,D,E"
    args.include_canary = False
    args.all_active = False
    args.limit = 2
    out = ara._resolve_tickers(args, _ROOT)
    assert out == ["A", "B"]
