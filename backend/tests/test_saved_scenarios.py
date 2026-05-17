"""Tests for the saved-scenarios service (Phase-2 editable assumptions).

Covers the service layer end-to-end against the in-memory fallback
so the suite is hermetic (no DATABASE_URL needed). The Postgres
path uses the same logical semantics; CI Postgres exercises it
separately via the migration smoke test.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from backend.services import saved_scenarios_service as svc


@pytest.fixture(autouse=True)
def _reset():
    svc._reset_memory_for_tests()
    yield
    svc._reset_memory_for_tests()


@pytest.fixture(autouse=True)
def _force_memory(monkeypatch):
    """Pin to the in-memory path even if DATABASE_URL is set in CI."""
    monkeypatch.setattr(svc, "_connect", lambda: None)


# ── Save ────────────────────────────────────────────────────────────

def test_save_and_list_one_scenario():
    row = svc.save_scenario(
        user_id="u1",
        ticker="reliance.ns",  # service normalises to upper
        name="My Bear Case",
        assumptions={"wacc": 0.12, "growth": 0.05},
        result={"fair_value": 1200.0, "mos_pct": -8.0},
    )
    assert row["ticker"] == "RELIANCE.NS"
    assert row["name"] == "My Bear Case"
    assert isinstance(row["id"], int)
    listing = svc.list_scenarios("u1")
    assert len(listing) == 1
    assert listing[0]["id"] == row["id"]
    # user_id is NOT stripped at service layer (router does that)
    assert listing[0]["user_id"] == "u1"


def test_save_same_name_updates_existing_row():
    a = svc.save_scenario("u1", "TCS.NS", "Base", {"wacc": 0.12}, {"fv": 100})
    b = svc.save_scenario("u1", "TCS.NS", "Base", {"wacc": 0.13}, {"fv": 90})
    # Same id — overwrite, not duplicate
    assert a["id"] == b["id"]
    rows = svc.list_scenarios("u1", ticker="TCS.NS")
    assert len(rows) == 1
    assert rows[0]["assumptions"]["wacc"] == 0.13
    assert rows[0]["result"]["fv"] == 90


def test_list_scoped_per_user():
    svc.save_scenario("alice", "X.NS", "a", {}, {})
    svc.save_scenario("bob", "X.NS", "b", {}, {})
    assert len(svc.list_scenarios("alice")) == 1
    assert len(svc.list_scenarios("bob")) == 1
    assert len(svc.list_scenarios("carol")) == 0


def test_list_can_filter_by_ticker():
    svc.save_scenario("u1", "A.NS", "n1", {}, {})
    svc.save_scenario("u1", "B.NS", "n2", {}, {})
    only_a = svc.list_scenarios("u1", ticker="A.NS")
    assert len(only_a) == 1
    assert only_a[0]["ticker"] == "A.NS"


def test_list_order_recent_first():
    import time
    svc.save_scenario("u1", "X.NS", "first", {}, {})
    # Sub-microsecond saves can tie on updated_at; nudge the clock so
    # the ordering assertion is deterministic without coupling the
    # service to a mockable now().
    time.sleep(0.001)
    svc.save_scenario("u1", "X.NS", "second", {}, {})
    rows = svc.list_scenarios("u1")
    # Most recent update at index 0
    assert rows[0]["name"] == "second"
    assert rows[1]["name"] == "first"


# ── Delete ──────────────────────────────────────────────────────────

def test_delete_own_scenario():
    row = svc.save_scenario("u1", "X.NS", "n", {}, {})
    assert svc.delete_scenario("u1", row["id"]) is True
    assert svc.list_scenarios("u1") == []
    # Double-delete → False
    assert svc.delete_scenario("u1", row["id"]) is False


def test_cannot_delete_other_users_scenario():
    row = svc.save_scenario("alice", "X.NS", "n", {}, {})
    assert svc.delete_scenario("bob", row["id"]) is False
    # Still there for alice
    assert len(svc.list_scenarios("alice")) == 1


# ── Cap ─────────────────────────────────────────────────────────────

def test_cap_enforced_on_new_inserts(monkeypatch):
    monkeypatch.setattr(svc, "MAX_SCENARIOS_PER_USER", 3)
    for i in range(3):
        svc.save_scenario("u1", "X.NS", f"n{i}", {}, {})
    with pytest.raises(svc.ScenarioCapReached):
        svc.save_scenario("u1", "X.NS", "overflow", {}, {})


def test_cap_does_not_block_updates_at_limit(monkeypatch):
    monkeypatch.setattr(svc, "MAX_SCENARIOS_PER_USER", 2)
    svc.save_scenario("u1", "X.NS", "n0", {}, {"v": 1})
    svc.save_scenario("u1", "X.NS", "n1", {}, {"v": 2})
    # At cap — but re-saving an existing name should still work
    row = svc.save_scenario("u1", "X.NS", "n0", {}, {"v": 99})
    assert row["result"]["v"] == 99


# ── Validation ──────────────────────────────────────────────────────

def test_empty_name_rejected():
    with pytest.raises(ValueError):
        svc.save_scenario("u1", "X.NS", "  ", {}, {})


def test_empty_ticker_rejected():
    with pytest.raises(ValueError):
        svc.save_scenario("u1", "", "n", {}, {})


def test_non_dict_payload_rejected():
    with pytest.raises(ValueError):
        svc.save_scenario("u1", "X.NS", "n", "not a dict", {})  # type: ignore[arg-type]


def test_count_for_user():
    assert svc.count_for_user("u1") == 0
    svc.save_scenario("u1", "X.NS", "a", {}, {})
    svc.save_scenario("u1", "Y.NS", "b", {}, {})
    assert svc.count_for_user("u1") == 2
    assert svc.count_for_user("other") == 0
