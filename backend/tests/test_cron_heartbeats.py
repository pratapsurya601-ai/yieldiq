"""Tests for the cron dead-man monitoring layer.

Covers:
  1. First-ever heartbeat for a workflow → row created with
     consecutive_misses=0.
  2. Subsequent heartbeat → row updated, consecutive_misses reset to 0
     even if a hypothetical dead-man pass had bumped it.
  3. Dead-man check: workflow whose last_success_at is older than
     2 * expected_interval_minutes is flagged.
  4. Dead-man check: healthy workflow is NOT flagged.
  5. Dead-man check: edge case at exactly 2x — not flagged (strict >).

The production write path uses Postgres ON CONFLICT semantics. SQLite
3.24+ supports the same UPSERT syntax, so the test schema mirrors
045_cron_heartbeats.sql closely enough that the same UPSERT statement
exercised by `upsert_heartbeat_sqlite` validates the logic.

No DATABASE_URL, no network, no psycopg2.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts import check_cron_deadman, write_cron_heartbeat


_TEST_SCHEMA_SQL = """
CREATE TABLE cron_heartbeats (
    workflow_name              TEXT      PRIMARY KEY,
    last_success_at            TEXT      NOT NULL,
    expected_interval_minutes  INTEGER   NOT NULL,
    consecutive_misses         INTEGER   NOT NULL DEFAULT 0,
    updated_at                 TEXT      NOT NULL
);
"""


@pytest.fixture()
def sess():
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as conn:
        conn.exec_driver_sql(_TEST_SCHEMA_SQL)
    Session = sessionmaker(bind=eng, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── 1. First heartbeat creates a row ────────────────────────────────


def test_first_heartbeat_creates_row(sess):
    write_cron_heartbeat.upsert_heartbeat_sqlite(
        sess, workflow="cron-market-live-quotes", interval_minutes=5,
    )

    rows = sess.execute(text(
        "SELECT workflow_name, expected_interval_minutes, consecutive_misses "
        "FROM cron_heartbeats"
    )).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "cron-market-live-quotes"
    assert rows[0][1] == 5
    assert rows[0][2] == 0


# ── 2. Second heartbeat updates the row and resets consecutive_misses ──


def test_second_heartbeat_updates_and_resets_misses(sess):
    # Seed a row that pretends the dead-man checker had bumped misses.
    old_ts = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    sess.execute(text(
        "INSERT INTO cron_heartbeats "
        "(workflow_name, last_success_at, expected_interval_minutes, "
        " consecutive_misses, updated_at) "
        "VALUES ('cron-market-fx-rates', :ts, 15, 7, :ts)"
    ), {"ts": old_ts})
    sess.commit()

    write_cron_heartbeat.upsert_heartbeat_sqlite(
        sess, workflow="cron-market-fx-rates", interval_minutes=15,
    )

    rows = sess.execute(text(
        "SELECT workflow_name, last_success_at, consecutive_misses "
        "FROM cron_heartbeats WHERE workflow_name = 'cron-market-fx-rates'"
    )).fetchall()

    assert len(rows) == 1
    assert rows[0][2] == 0, "consecutive_misses must reset on success"
    assert rows[0][1] > old_ts, "last_success_at must move forward"


# ── 3. Dead-man check flags stale workflows ─────────────────────────


def test_deadman_flags_workflow_past_2x_interval():
    now = datetime(2026, 5, 18, 12, 0, 0)
    rows = [
        # 5-min cron, last seen 12 minutes ago → 12 > 10 → DEAD.
        ("cron-market-live-quotes", now - timedelta(minutes=12), 5),
    ]

    dead = check_cron_deadman.find_dead_workflows_rows(rows, now=now)

    assert len(dead) == 1
    assert dead[0]["workflow_name"] == "cron-market-live-quotes"
    assert dead[0]["threshold_minutes"] == 10
    assert dead[0]["age_minutes"] == 12.0


# ── 4. Healthy workflow is not flagged ──────────────────────────────


def test_deadman_does_not_flag_healthy_workflow():
    now = datetime(2026, 5, 18, 12, 0, 0)
    rows = [
        # 15-min cron, last seen 3 minutes ago → well under 30-min threshold.
        ("cron-market-fx-rates", now - timedelta(minutes=3), 15),
    ]
    dead = check_cron_deadman.find_dead_workflows_rows(rows, now=now)
    assert dead == []


# ── 5. Boundary at exactly 2x → still healthy ───────────────────────


def test_deadman_boundary_at_exact_2x_is_healthy():
    now = datetime(2026, 5, 18, 12, 0, 0)
    rows = [
        # 5-min cron, last seen exactly 10 minutes ago → 10 > 10 is False → healthy.
        ("cron-market-live-quotes", now - timedelta(minutes=10), 5),
    ]
    assert check_cron_deadman.find_dead_workflows_rows(rows, now=now) == []


# ── 6. Mixed batch: only the dead ones come back ────────────────────


def test_deadman_returns_only_dead_in_mixed_batch():
    now = datetime(2026, 5, 18, 12, 0, 0)
    rows = [
        ("cron-market-live-quotes", now - timedelta(minutes=2), 5),     # healthy
        ("cron-market-fx-rates",    now - timedelta(minutes=45), 15),   # DEAD (>30)
        ("cron-consensus-refresh",  now - timedelta(hours=10), 1440),   # healthy
        ("pulse_daily",             now - timedelta(hours=30), 720),    # DEAD (>24h)
    ]
    dead_names = {d["workflow_name"] for d in
                  check_cron_deadman.find_dead_workflows_rows(rows, now=now)}
    assert dead_names == {"cron-market-fx-rates", "pulse_daily"}
