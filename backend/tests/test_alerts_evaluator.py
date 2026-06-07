"""Unit tests for the hourly alerts evaluator.

Covers:

  Pure helpers
    1. _should_fire honors each kind's direction
    2. _should_fire suppresses MoS kinds on untrusted verdicts
    3. _should_fire never raises on missing snapshot fields
    4. _in_cooldown is True within COOLDOWN_HOURS, False outside

  Integration (in-memory SQLite)
    5. evaluate_alerts is a no-op when there are no active alerts
    6. evaluate_alerts skips alerts whose verdict is in
       UNTRUSTED_VERDICTS — reason is "untrusted_verdict", not "fired"
    7. evaluate_alerts respects status='paused' / 'triggered'
    8. one-shot alerts flip to status='triggered' once fired

The integration tests stub the email + push send paths so no network IO
happens; the assertions are on the EvaluationResult records and the DB
side-effects (status, last_triggered_at, last_checked_at).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.alerts_service import (  # noqa: E402
    COOLDOWN_HOURS,
    ONE_SHOT_KINDS,
    UNTRUSTED_VERDICTS,
    EvaluationResult,
    TickerSnapshot,
    _in_cooldown,
    _should_fire,
    evaluate_alerts,
)


# ── 1. _should_fire honors each kind's direction ──────────────


def test_should_fire_price_above():
    snap = TickerSnapshot("ITC.NS", price=500.0, mos_pct=10.0, verdict="undervalued")
    assert _should_fire("price_above", 450.0, snap, None) is True
    assert _should_fire("price_above", 550.0, snap, None) is False


def test_should_fire_price_below():
    snap = TickerSnapshot("ITC.NS", price=500.0, mos_pct=10.0, verdict="undervalued")
    assert _should_fire("price_below", 550.0, snap, None) is True
    assert _should_fire("price_below", 450.0, snap, None) is False


def test_should_fire_mos_above():
    snap = TickerSnapshot("ITC.NS", price=500.0, mos_pct=30.0, verdict="undervalued")
    assert _should_fire("mos_above", 25.0, snap, None) is True
    assert _should_fire("mos_above", 35.0, snap, None) is False


def test_should_fire_mos_below():
    snap = TickerSnapshot("ITC.NS", price=500.0, mos_pct=5.0, verdict="undervalued")
    assert _should_fire("mos_below", 10.0, snap, None) is True
    assert _should_fire("mos_below", 0.0, snap, None) is False


def test_should_fire_verdict_change_first_run_no_fire():
    # First run after an alert is created: previous_verdict is None,
    # so we don't fire even if a current verdict exists. Avoids a
    # stampede on the first evaluator pass.
    snap = TickerSnapshot("ITC.NS", 500.0, 10.0, verdict="undervalued")
    assert _should_fire("verdict_change", None, snap, None) is False


def test_should_fire_verdict_change_fires_on_diff():
    snap = TickerSnapshot("ITC.NS", 500.0, 10.0, verdict="overvalued")
    assert _should_fire("verdict_change", None, snap, "undervalued") is True


def test_should_fire_verdict_change_no_fire_on_same():
    snap = TickerSnapshot("ITC.NS", 500.0, 10.0, verdict="undervalued")
    assert _should_fire("verdict_change", None, snap, "undervalued") is False


# ── 2. MoS kinds suppressed on untrusted verdicts ─────────────


@pytest.mark.parametrize("bad_verdict", sorted(UNTRUSTED_VERDICTS))
def test_should_fire_mos_above_suppressed_on_untrusted(bad_verdict):
    # Even though the numeric MoS is past the threshold, an
    # under_review / data_limited / unavailable / avoid verdict means
    # the engine doesn't trust the read — we don't fire.
    snap = TickerSnapshot("XYZ.NS", price=100.0, mos_pct=50.0, verdict=bad_verdict)
    assert _should_fire("mos_above", 25.0, snap, None) is False


@pytest.mark.parametrize("bad_verdict", sorted(UNTRUSTED_VERDICTS))
def test_should_fire_mos_below_suppressed_on_untrusted(bad_verdict):
    snap = TickerSnapshot("XYZ.NS", price=100.0, mos_pct=-50.0, verdict=bad_verdict)
    assert _should_fire("mos_below", 0.0, snap, None) is False


def test_should_fire_price_kinds_NOT_suppressed_on_untrusted():
    # Price alerts are factual ("price crossed X") and don't depend on
    # the engine's trust in the FV; they remain valid even when the
    # verdict is untrusted.
    snap = TickerSnapshot("XYZ.NS", price=500.0, mos_pct=0.0, verdict="under_review")
    assert _should_fire("price_above", 450.0, snap, None) is True


# ── 3. _should_fire never raises on missing fields ───────────


def test_should_fire_handles_missing_price():
    snap = TickerSnapshot("XYZ.NS", price=None, mos_pct=10.0, verdict="undervalued")
    assert _should_fire("price_above", 100.0, snap, None) is False
    assert _should_fire("price_below", 100.0, snap, None) is False


def test_should_fire_handles_missing_mos():
    snap = TickerSnapshot("XYZ.NS", price=100.0, mos_pct=None, verdict="undervalued")
    assert _should_fire("mos_above", 10.0, snap, None) is False
    assert _should_fire("mos_below", 10.0, snap, None) is False


def test_should_fire_handles_missing_threshold():
    snap = TickerSnapshot("XYZ.NS", price=100.0, mos_pct=20.0, verdict="undervalued")
    assert _should_fire("mos_above", None, snap, None) is False
    assert _should_fire("price_above", None, snap, None) is False


def test_should_fire_unknown_kind_returns_false():
    snap = TickerSnapshot("XYZ.NS", price=100.0, mos_pct=20.0, verdict="undervalued")
    assert _should_fire("nonsense_kind", 0.0, snap, None) is False


# ── 4. _in_cooldown ───────────────────────────────────────────


def test_in_cooldown_none_means_never_fired():
    assert _in_cooldown(None) is False


def test_in_cooldown_recent_fire_is_in_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS - 1)
    assert _in_cooldown(recent) is True


def test_in_cooldown_old_fire_is_not_in_cooldown():
    old = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS + 1)
    assert _in_cooldown(old) is False


def test_in_cooldown_handles_naive_datetimes():
    # Defence-in-depth — SQLite tests can return naive timestamps even
    # though prod is TIMESTAMPTZ. Should not raise.
    recent_naive = datetime.utcnow() - timedelta(hours=1)
    assert _in_cooldown(recent_naive) is True


# ── 5–8. Integration with in-memory SQLite ────────────────────


@pytest.fixture
def session():
    """In-memory SQLite session with the user_alerts table created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.models.alerts import UserAlert  # noqa: F401 register
    from data_pipeline.models import Base

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_alert(session, *, ticker, kind, threshold, status="active",
                last_triggered_at=None, user_id="user-1"):
    from backend.models.alerts import UserAlert
    a = UserAlert(
        user_id=user_id,
        ticker=ticker,
        kind=kind,
        threshold=threshold,
        status=status,
        last_triggered_at=last_triggered_at,
        notify_email=True,
        notify_push=False,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_evaluate_alerts_no_active_alerts_returns_empty(session):
    # No rows in the table at all.
    assert evaluate_alerts(session, dry_run=True) == []


def test_evaluate_alerts_skips_paused_and_triggered(session):
    _make_alert(session, ticker="A.NS", kind="mos_above", threshold=25.0,
                status="paused")
    _make_alert(session, ticker="B.NS", kind="mos_above", threshold=25.0,
                status="triggered")
    # Even with snapshots that would otherwise fire, paused/triggered
    # rows are not even considered by the evaluator query.
    with patch("backend.services.alerts_service._fetch_snapshots") as fs:
        fs.return_value = {
            "A.NS": TickerSnapshot("A.NS", 500.0, 50.0, "undervalued"),
            "B.NS": TickerSnapshot("B.NS", 500.0, 50.0, "undervalued"),
        }
        results = evaluate_alerts(session, dry_run=True)
    assert results == []


def test_evaluate_alerts_untrusted_verdict_does_not_fire(session):
    """Criticism guard: a 25%-discount alert on an under_review ticker
    must NOT fire — the engine doesn't trust the MoS reading."""
    _make_alert(session, ticker="THIN.NS", kind="mos_above", threshold=25.0)
    with patch("backend.services.alerts_service._fetch_snapshots") as fs:
        fs.return_value = {
            "THIN.NS": TickerSnapshot(
                "THIN.NS", 100.0, mos_pct=50.0, verdict="under_review"
            ),
        }
        results = evaluate_alerts(session, dry_run=True)

    assert len(results) == 1
    r = results[0]
    assert r.fired is False
    assert r.reason == "untrusted_verdict"


def test_evaluate_alerts_one_shot_flips_to_triggered(session):
    a = _make_alert(session, ticker="ITC.NS", kind="mos_above", threshold=25.0)
    assert "mos_above" in ONE_SHOT_KINDS  # invariant

    with patch("backend.services.alerts_service._fetch_snapshots") as fs, \
         patch("backend.services.alerts_service._resolve_email") as re_, \
         patch("backend.services.alerts_service._send_alert_email") as send:
        fs.return_value = {
            "ITC.NS": TickerSnapshot("ITC.NS", 400.0, 30.0, "undervalued"),
        }
        re_.return_value = "user@example.com"
        send.return_value = True
        results = evaluate_alerts(session, dry_run=False)

    assert len(results) == 1
    assert results[0].fired is True
    assert results[0].reason == "fired"
    # DB side-effects: status flipped, last_triggered_at populated.
    session.refresh(a)
    assert a.status == "triggered"
    assert a.last_triggered_at is not None


def test_evaluate_alerts_dry_run_makes_no_writes(session):
    a = _make_alert(session, ticker="ITC.NS", kind="mos_above", threshold=25.0)
    with patch("backend.services.alerts_service._fetch_snapshots") as fs:
        fs.return_value = {
            "ITC.NS": TickerSnapshot("ITC.NS", 400.0, 30.0, "undervalued"),
        }
        results = evaluate_alerts(session, dry_run=True)

    assert len(results) == 1
    assert results[0].fired is True
    session.refresh(a)
    # Dry-run must not flip status nor stamp last_triggered_at.
    assert a.status == "active"
    assert a.last_triggered_at is None


def test_evaluate_alerts_cooldown_blocks_refire(session):
    recent = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS - 1)
    _make_alert(session, ticker="ITC.NS", kind="mos_above", threshold=25.0,
                last_triggered_at=recent)
    with patch("backend.services.alerts_service._fetch_snapshots") as fs:
        fs.return_value = {
            "ITC.NS": TickerSnapshot("ITC.NS", 400.0, 30.0, "undervalued"),
        }
        results = evaluate_alerts(session, dry_run=True)

    assert len(results) == 1
    assert results[0].fired is False
    assert results[0].reason == "cooldown"
