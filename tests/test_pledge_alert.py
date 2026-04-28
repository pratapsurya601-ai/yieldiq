"""Test the pledge-jump alert pipeline.

We monkey-patch the small DB-touching surface (``_get_raw_cursor``,
``compute_pledge_change_pp``, ``get_latest_pledge``,
``_recently_fired``, and ``create_notification``) so the test runs
offline against synthetic state.

Threshold: 5pp (matches SEBI material-disclosure threshold).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_pledge_row(pct: float, ticker: str = "RCOM"):
    from backend.services.promoter_pledge_service import PledgeRow
    return PledgeRow(
        ticker=ticker,
        as_of_date=date(2026, 1, 31),
        promoter_group_pct=21.97,
        pledged_pct=pct,
        pledged_shares=4_400_000_000,
        source_url="https://example.com",
    )


def test_pledge_jump_above_threshold_fires_alert():
    """+15pp jump for a watchlisted ticker fires exactly one alert."""
    from backend.services import promoter_pledge_service as svc

    # Synthetic watchlist: one user, one ticker.
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [("user-123", "RCOM")]
    fake_conn = MagicMock()

    create_calls: list[dict] = []

    def fake_create(**kwargs):
        create_calls.append(kwargs)
        return 7

    with patch.object(svc, "_get_raw_cursor", return_value=(fake_conn, fake_cur)), \
         patch.object(svc, "compute_pledge_change_pp", return_value=15.0), \
         patch.object(svc, "get_latest_pledge", return_value=_make_pledge_row(80.0)), \
         patch.object(svc, "_recently_fired", return_value=False), \
         patch("backend.services.notifications_service.create_notification",
               side_effect=fake_create), \
         patch("backend.services.notifications_service.can_receive",
               return_value=True):
        fired = svc.detect_pledge_jumps()

    assert len(fired) == 1
    summary = fired[0]
    assert summary["ticker"] == "RCOM"
    assert summary["change_pp"] == 15.0
    assert summary["latest_pct"] == 80.0
    assert summary["prior_pct"] == 65.0  # 80 - 15
    assert summary["notification_id"] == 7

    assert len(create_calls) == 1
    call = create_calls[0]
    assert call["user_id"] == "user-123"
    assert call["type"] == "alert_fired"
    assert "RCOM" in call["title"]
    assert "65.0%" in call["body"] and "80.0%" in call["body"]
    assert call["metadata"]["kind"] == "promoter_pledge_jump"
    assert call["metadata"]["change_pp"] == 15.0


def test_pledge_jump_below_threshold_does_not_fire():
    """+3pp change is below the 5pp threshold — no alert."""
    from backend.services import promoter_pledge_service as svc

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [("user-123", "RCOM")]
    fake_conn = MagicMock()

    create_calls: list = []

    with patch.object(svc, "_get_raw_cursor", return_value=(fake_conn, fake_cur)), \
         patch.object(svc, "compute_pledge_change_pp", return_value=3.0), \
         patch.object(svc, "get_latest_pledge", return_value=_make_pledge_row(50.0)), \
         patch.object(svc, "_recently_fired", return_value=False), \
         patch("backend.services.notifications_service.create_notification",
               side_effect=lambda **k: create_calls.append(k) or 1), \
         patch("backend.services.notifications_service.can_receive",
               return_value=True):
        fired = svc.detect_pledge_jumps()

    assert fired == []
    assert create_calls == []


def test_recently_fired_idempotency_skips_duplicate():
    """If we already fired in last 7 days, no second alert."""
    from backend.services import promoter_pledge_service as svc

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [("user-123", "RCOM")]
    fake_conn = MagicMock()
    create_calls: list = []

    with patch.object(svc, "_get_raw_cursor", return_value=(fake_conn, fake_cur)), \
         patch.object(svc, "compute_pledge_change_pp", return_value=15.0), \
         patch.object(svc, "get_latest_pledge", return_value=_make_pledge_row(80.0)), \
         patch.object(svc, "_recently_fired", return_value=True), \
         patch("backend.services.notifications_service.create_notification",
               side_effect=lambda **k: create_calls.append(k) or 1):
        fired = svc.detect_pledge_jumps()

    assert fired == []
    assert create_calls == []


def test_compute_pledge_change_pp_returns_positive_for_increase():
    """Sanity: a 65 -> 80 transition gives +15pp."""
    from backend.services import promoter_pledge_service as svc

    fake_cur = MagicMock()
    fake_cur.fetchone.side_effect = [
        (date(2026, 1, 31), 80.0),  # latest
        (date(2025, 10, 1), 65.0),  # prior @ <= cutoff
    ]
    fake_conn = MagicMock()

    with patch.object(svc, "_get_raw_cursor", return_value=(fake_conn, fake_cur)):
        change = svc.compute_pledge_change_pp("RCOM", lookback_days=90)
    assert change == 15.0
