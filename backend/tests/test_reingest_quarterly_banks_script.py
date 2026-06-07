"""Tests for ``scripts/reingest_quarterly_banks.py`` — the PR #747
follow-up backfill script for Schedule III Div I bank fields.

Coverage:
    1. --dry-run never invokes the DB writer.
    2. Idempotency: running twice with the same inputs produces the
       same row count (the writer's ON CONFLICT DO UPDATE handles it).
    3. --resume-from skips alphabetically-earlier tickers.
    4. A failure on one ticker is logged but does NOT kill the run;
       subsequent tickers are still processed.
    5. The bank-universe resolver returns the canonical
       PURE_BANK_TICKERS_FOR_DE set when available.

These tests never touch the network or a live database — they pass
in-memory ``fetch_fn`` / ``extract_fn`` / ``upsert_fn`` overrides into
``reingest_one_ticker``, mirroring how the script's CLI entry would
call them.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "reingest_quarterly_banks.py"


def _load_script_module():
    """Load the script as a module without running it as __main__."""
    spec = importlib.util.spec_from_file_location(
        "reingest_quarterly_banks", SCRIPT_PATH,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec_module so @dataclass can find the module
    # in sys.modules during annotation resolution (Python 3.12 bug
    # path in dataclasses._is_type).
    sys.modules["reingest_quarterly_banks"] = mod
    # Make sure repo root is importable so any
    # ``from backend.services...`` imports inside the script resolve.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeUpserter:
    """Tracks every batch of records passed to it; emulates the writer
    contract (returns (inserted, errors)). ``ON CONFLICT DO UPDATE``
    means re-running with the same (ticker, period, statement_type,
    source) key is a no-op on row count — we model that by keeping a
    set of seen keys and only growing ``self.rows`` on first insert.
    """

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.rows: dict[tuple, dict] = {}

    def __call__(self, records: list[dict]) -> tuple[int, int]:
        self.calls.append(list(records))
        inserted_or_updated = 0
        for rec in records:
            key = (
                rec.get("ticker_nse"),
                rec.get("period_type"),
                rec.get("period_end_date"),
                rec.get("statement_type"),
                rec.get("source"),
            )
            self.rows[key] = dict(rec)   # upsert semantics
            inserted_or_updated += 1
        return inserted_or_updated, 0


def _fake_yf_data_factory(periods: list[str]):
    """Build an opaque ``data`` dict whose only purpose is to be passed
    to the fake extractor. We never inspect it inside the script
    when overrides are supplied.
    """
    def _fake_fetch(ticker: str):
        return {"ticker": ticker, "_periods": periods}
    return _fake_fetch


def _fake_extract(data: dict, period_type: str) -> list[dict]:
    """Synthesize one record per period. ``interest_earned`` is
    populated so the row counts as having bank signal.
    """
    assert period_type == "quarterly"
    ticker = data["ticker"]
    out = []
    for p in data["_periods"]:
        out.append({
            "ticker_nse": ticker,
            "period_type": "quarterly",
            "period_end_date": p,
            "statement_type": "income",
            "source": "yfinance",
            "interest_earned": 100.0,
            "interest_expended": 60.0,
            "other_income": 25.0,
            "operating_expense": 40.0,
            "total_income": 125.0,
        })
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dry_run_does_not_invoke_upsert():
    mod = _load_script_module()
    upserter = _FakeUpserter()
    outcome = mod.reingest_one_ticker(
        "HDFCBANK",
        since=date(2024, 12, 1),
        until=date(2024, 12, 31),
        dry_run=True,
        verbose=False,
        fetch_fn=_fake_yf_data_factory(["2024-12-31"]),
        extract_fn=_fake_extract,
        upsert_fn=upserter,
    )
    assert outcome.error is None
    assert outcome.in_window == 1
    assert outcome.upserted == 0, "dry-run must not upsert"
    assert upserter.calls == [], "writer must not be called in --dry-run"


def test_idempotency_double_run_same_row_count():
    mod = _load_script_module()
    upserter = _FakeUpserter()
    kwargs = dict(
        since=date(2024, 1, 1),
        until=date(2024, 12, 31),
        dry_run=False,
        verbose=False,
        fetch_fn=_fake_yf_data_factory(["2024-03-31", "2024-06-30"]),
        extract_fn=_fake_extract,
        upsert_fn=upserter,
    )
    out1 = mod.reingest_one_ticker("HDFCBANK", **kwargs)
    rows_after_first = len(upserter.rows)
    out2 = mod.reingest_one_ticker("HDFCBANK", **kwargs)
    rows_after_second = len(upserter.rows)

    assert out1.upserted == 2
    assert out2.upserted == 2, "writer reports 2 rows touched both runs"
    assert rows_after_first == 2
    assert rows_after_second == 2, (
        "ON CONFLICT DO UPDATE keeps total row count steady on re-run"
    )


def test_resume_from_skips_earlier_tickers(monkeypatch, caplog):
    mod = _load_script_module()
    upserter = _FakeUpserter()

    # Pretend the universe is exactly these three; --resume-from
    # KOTAKBANK must drop AXISBANK and HDFCBANK.
    monkeypatch.setattr(
        mod, "resolve_bank_universe",
        lambda: (["AXISBANK", "HDFCBANK", "KOTAKBANK"], "test_fixture"),
    )

    visited: list[str] = []

    def _spy_reingest(ticker, *a, **kw):
        visited.append(ticker)
        return mod.TickerOutcome(
            ticker=ticker, in_window=0, upserted=0,
            skip_reason="no data (test stub)",
        )

    monkeypatch.setattr(mod, "reingest_one_ticker", _spy_reingest)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    rc = mod.main([
        "--since", "2024-01-01",
        "--until", "2024-12-31",
        "--rate-limit-sec", "0",
        "--resume-from", "KOTAKBANK",
    ])
    assert rc == 0
    assert visited == ["KOTAKBANK"], (
        f"--resume-from must drop alphabetically-earlier tickers; "
        f"got {visited}"
    )
    # No writer calls because the spy returned skip outcomes.
    assert upserter.calls == []


def test_one_bad_ticker_does_not_kill_the_run(monkeypatch):
    mod = _load_script_module()

    monkeypatch.setattr(
        mod, "resolve_bank_universe",
        lambda: (["AAA", "BBB", "CCC"], "test_fixture"),
    )

    visited: list[str] = []

    def _maybe_explode(ticker, *a, **kw):
        visited.append(ticker)
        if ticker == "BBB":
            return mod.TickerOutcome(
                ticker=ticker, error="fetch failed: simulated 429",
            )
        return mod.TickerOutcome(
            ticker=ticker, in_window=1, upserted=1, bank_field_rows=1,
        )

    monkeypatch.setattr(mod, "reingest_one_ticker", _maybe_explode)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    rc = mod.main([
        "--since", "2024-01-01",
        "--until", "2024-12-31",
        "--rate-limit-sec", "0",
    ])
    assert rc == 0, "script exits 0 even when one ticker errors"
    assert visited == ["AAA", "BBB", "CCC"], (
        f"all tickers must be attempted; got {visited}"
    )


def test_resolve_bank_universe_prefers_canonical_list():
    mod = _load_script_module()
    universe, source = mod.resolve_bank_universe()
    # The canonical list MUST resolve in the repo's own test env
    # (sector_overrides ships with the project). If this fails, the
    # script's fallback warning would fire in production — not fatal
    # but worth noticing.
    assert source == "PURE_BANK_TICKERS_FOR_DE", (
        f"expected canonical list, got source={source}"
    )
    assert "HDFCBANK" in universe
    assert "SBIN" in universe
    assert universe == sorted(universe), "universe must be sorted"


def test_fail_fast_when_database_url_missing(monkeypatch, caplog):
    mod = _load_script_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    rc = mod.main([
        "--since", "2024-01-01",
        "--until", "2024-12-31",
        "--tickers", "HDFCBANK",
        "--rate-limit-sec", "0",
    ])
    assert rc == 1, "must exit non-zero when DATABASE_URL is unset and not --dry-run"


def test_dry_run_works_without_database_url(monkeypatch):
    mod = _load_script_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)

    monkeypatch.setattr(
        mod, "reingest_one_ticker",
        lambda t, *a, **kw: mod.TickerOutcome(
            ticker=t, in_window=1, upserted=0, bank_field_rows=1,
        ),
    )
    rc = mod.main([
        "--since", "2024-01-01",
        "--until", "2024-12-31",
        "--tickers", "HDFCBANK",
        "--rate-limit-sec", "0",
        "--dry-run",
    ])
    assert rc == 0


def test_window_filter_drops_out_of_range_periods():
    """Quarters outside [since, until] must be filtered out before upsert."""
    mod = _load_script_module()
    upserter = _FakeUpserter()
    outcome = mod.reingest_one_ticker(
        "HDFCBANK",
        since=date(2024, 6, 1),
        until=date(2024, 9, 30),
        dry_run=False,
        verbose=False,
        fetch_fn=_fake_yf_data_factory([
            "2024-03-31",   # out
            "2024-06-30",   # in
            "2024-09-30",   # in
            "2024-12-31",   # out
        ]),
        extract_fn=_fake_extract,
        upsert_fn=upserter,
    )
    assert outcome.fetched_quarters == 4
    assert outcome.in_window == 2
    assert outcome.upserted == 2
    assert {r["period_end_date"] for r in upserter.calls[0]} == {
        "2024-06-30", "2024-09-30",
    }
