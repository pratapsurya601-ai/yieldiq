"""Unit tests for the analyze() write-hook skip-rules — task #264.

The hook is ``data_pipeline.sources.fv_history.store_today_fair_value``,
called from ``backend.services.analysis.service`` after every successful
analyze() pass. It builds the per-day series that
``ValuationHistoryChart`` (task #265) renders.

The skip-rules under test here:

  R1. Numeric gate — fv <= 0 or price <= 0 must NOT persist a row.
  R2. Verdict gate — verdict in NON_CHARTABLE_VERDICTS
      ({"data_limited", "unavailable", "under_review"}) must NOT
      persist a row even when the numeric gate passes (a clamped FV
      is still a positive number, but is a sentinel, not a model
      output).
  R3. Happy path — a normal valuation (positive fv + positive price
      + verdict in {undervalued, fairly_valued, overvalued, avoid})
      DOES persist a row.
  R4. Idempotency — two analyze() calls on the same day produce
      ONE row, not two.

Plus one belt-and-braces property:

  R5. The hook never raises on a broken session — the analyze()
      response contract says this write must never fail the request.

All tests use an in-memory SQLite session, same pattern as
backend/tests/test_alerts_evaluator.py. Avoids any network IO / Aiven
round-trip / FastAPI client startup.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.models import Base, FairValueHistory  # noqa: E402
from data_pipeline.sources.fv_history import (  # noqa: E402
    NON_CHARTABLE_VERDICTS,
    store_today_fair_value,
)


@pytest.fixture
def session():
    """In-memory SQLite session with the fair_value_history table."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _count_rows(session, ticker: str) -> int:
    return (
        session.query(FairValueHistory)
        .filter_by(ticker=ticker, date=date.today())
        .count()
    )


# ── R3. Happy path — a chartable result persists a row ─────────


def test_chartable_undervalued_persists_one_row(session):
    """A valid analyze() result with verdict='undervalued' writes a row."""
    store_today_fair_value(
        ticker="HAPPY.NS",
        fv=120.0,
        price=100.0,
        mos=20.0,
        verdict="undervalued",
        wacc=0.105,
        confidence=85,
        db=session,
    )
    assert _count_rows(session, "HAPPY.NS") == 1
    row = (
        session.query(FairValueHistory)
        .filter_by(ticker="HAPPY.NS", date=date.today())
        .first()
    )
    assert row.fair_value == pytest.approx(120.0)
    assert row.price == pytest.approx(100.0)
    assert row.verdict == "undervalued"


@pytest.mark.parametrize("verdict", ["undervalued", "fairly_valued",
                                      "overvalued", "avoid"])
def test_each_chartable_verdict_persists(session, verdict):
    """Each non-skip verdict round-trips a row."""
    ticker = f"OK_{verdict.upper()}.NS"
    store_today_fair_value(
        ticker=ticker,
        fv=100.0,
        price=100.0,
        mos=0.0,
        verdict=verdict,
        wacc=0.10,
        confidence=70,
        db=session,
    )
    assert _count_rows(session, ticker) == 1


# ── R2. Verdict gate — non-chartable verdicts are silently skipped ──


@pytest.mark.parametrize("verdict", sorted(NON_CHARTABLE_VERDICTS))
def test_non_chartable_verdict_writes_no_row(session, verdict):
    """data_limited / unavailable / under_review must NOT persist.

    The numeric inputs here pass the > 0 gate — only the verdict
    gate should reject them. This is the regression that motivated
    task #264: a clamped FV from a data_limited result was being
    persisted with provenance='live' and corrupting the chart.
    """
    ticker = f"SKIP_{verdict.upper()}.NS"
    store_today_fair_value(
        ticker=ticker,
        fv=50.0,           # positive — would pass the numeric gate
        price=500.0,       # positive — would pass the numeric gate
        mos=-90.0,         # extreme — typical of a clamp scenario
        verdict=verdict,
        wacc=0.10,
        confidence=10,
        db=session,
    )
    assert _count_rows(session, ticker) == 0


def test_non_chartable_verdicts_set_is_locked():
    """The skip-list is the contract that the call-site in
    backend/services/analysis/service.py mirrors. If anyone adds
    a new verdict here without updating the inner gate (or vice
    versa), this assertion catches the drift."""
    assert NON_CHARTABLE_VERDICTS == frozenset({
        "data_limited",
        "unavailable",
        "under_review",
    })


# ── R1. Numeric gate — degenerate FV / price ───────────────────


@pytest.mark.parametrize("fv,price", [
    (0.0, 100.0),       # FV zero
    (-5.0, 100.0),      # FV negative
    (100.0, 0.0),       # price zero
    (100.0, -10.0),     # price negative
    (None, 100.0),      # FV missing
    (100.0, None),      # price missing
])
def test_degenerate_numerics_write_no_row(session, fv, price):
    """The numeric gate refuses to persist rows we can't compute MoS on."""
    store_today_fair_value(
        ticker="BAD.NS",
        fv=fv,
        price=price,
        mos=0.0,
        verdict="undervalued",
        wacc=0.10,
        confidence=50,
        db=session,
    )
    assert _count_rows(session, "BAD.NS") == 0


# ── R4. Idempotency — two writes on the same day produce one row ──


def test_same_day_writes_are_idempotent(session):
    """Two analyze() calls for the same ticker on the same day must
    leave ONE row in the table (UPSERT semantics)."""
    common = dict(
        ticker="IDEM.NS",
        price=100.0,
        mos=10.0,
        verdict="undervalued",
        wacc=0.10,
        confidence=80,
        db=session,
    )
    store_today_fair_value(fv=110.0, **common)
    store_today_fair_value(fv=115.0, **common)
    assert _count_rows(session, "IDEM.NS") == 1
    row = (
        session.query(FairValueHistory)
        .filter_by(ticker="IDEM.NS", date=date.today())
        .first()
    )
    # Second write wins. (115.0 is in the assertion, smoothed against
    # historical rows; with no priors EMA returns the raw value.)
    assert row.fair_value == pytest.approx(115.0)


# ── R5. Hook never raises on a broken session ──────────────────


def test_hook_swallows_session_errors():
    """A broken session must not propagate — the analyze() contract
    is that the hook can never fail the user-facing response."""
    class _BrokenSession:
        def query(self, *_a, **_kw):
            raise RuntimeError("simulated DB outage")
        def add(self, *_a, **_kw):
            raise RuntimeError("simulated DB outage")
        def commit(self):
            raise RuntimeError("simulated DB outage")
        def rollback(self):
            pass

    # MUST NOT raise.
    store_today_fair_value(
        ticker="ERR.NS",
        fv=100.0,
        price=100.0,
        mos=0.0,
        verdict="undervalued",
        wacc=0.10,
        confidence=50,
        db=_BrokenSession(),
    )
