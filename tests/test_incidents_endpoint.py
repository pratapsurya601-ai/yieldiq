"""Tests for backend/routers/incidents.py.

The endpoint is a thin transparency surface — it has to:
  1. Filter to the last 90 days.
  2. Sort by started_at DESC.
  3. Compute current_status from the open-incident set.
  4. Survive a DB outage gracefully (return empty list, not 500).

We test the pure helpers (_compute_current_status, _row_to_dict) directly
and exercise the endpoint with a stubbed _get_db_session so no live DB
is required in CI.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The router pulls a few transitive imports from backend.services on import;
# we don't need those services to be wired for the unit tests below.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from backend.routers import incidents as inc_router  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────


def _row(**fields):
    """Build an object that quacks like a SQLAlchemy Row for _row_to_dict."""
    obj = MagicMock()
    obj._mapping = fields
    return obj


# ── _compute_current_status ────────────────────────────────────────────


def test_status_operational_when_all_resolved():
    incidents = [
        {"severity": "major", "ended_at": "2026-05-02T21:00:00+00:00"},
        {"severity": "minor", "ended_at": "2026-05-02T14:00:00+00:00"},
    ]
    assert inc_router._compute_current_status(incidents) == "operational"


def test_status_outage_when_open_major():
    incidents = [
        {"severity": "major", "ended_at": None},
        {"severity": "minor", "ended_at": "2026-05-02T14:00:00+00:00"},
    ]
    assert inc_router._compute_current_status(incidents) == "outage"


def test_status_degraded_when_only_open_minor():
    incidents = [
        {"severity": "minor", "ended_at": None},
        {"severity": "major", "ended_at": "2026-05-02T21:00:00+00:00"},
    ]
    assert inc_router._compute_current_status(incidents) == "degraded"


def test_status_operational_on_empty_list():
    assert inc_router._compute_current_status([]) == "operational"


def test_status_treats_empty_string_ended_at_as_open():
    """Defensive: a stringified empty ended_at should still count as open."""
    incidents = [{"severity": "partial", "ended_at": ""}]
    assert inc_router._compute_current_status(incidents) == "degraded"


# ── _row_to_dict ───────────────────────────────────────────────────────


def test_row_to_dict_serializes_naive_datetime_as_utc():
    naive = datetime(2026, 5, 2, 16, 0, 0)  # no tzinfo
    out = inc_router._row_to_dict(_row(
        id=1,
        started_at=naive,
        ended_at=None,
        severity="major",
        title="x",
    ))
    assert out["started_at"] == "2026-05-02T16:00:00+00:00"
    assert out["ended_at"] is None


def test_row_to_dict_preserves_aware_datetime():
    aware = datetime(2026, 5, 2, 21, 0, 0, tzinfo=timezone.utc)
    out = inc_router._row_to_dict(_row(
        id=2, started_at=aware, ended_at=aware, severity="minor", title="y",
    ))
    assert out["started_at"].endswith("+00:00")
    assert out["ended_at"].endswith("+00:00")


# ── Endpoint behaviour (DB stubbed) ────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_returns_rows_sorted_and_status(monkeypatch):
    rows = [
        _row(
            id=10,
            started_at=datetime(2026, 5, 2, 16, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 5, 2, 21, 0, 0, tzinfo=timezone.utc),
            severity="major",
            surface="frontend",
            title="Vercel 402",
            description="...",
            resolution="upgraded",
        ),
        _row(
            id=11,
            started_at=datetime(2026, 5, 2, 8, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc),
            severity="minor",
            surface="data_pipeline",
            title="Stale FV cache",
            description="...",
            resolution="reclassified",
        ),
    ]

    fake_session = MagicMock()
    fake_session.execute.return_value.fetchall.return_value = rows
    monkeypatch.setattr(inc_router, "_get_db_session", lambda: fake_session)

    resp = await inc_router.get_public_incidents()
    import json
    payload = json.loads(resp.body)

    assert payload["current_status"] == "operational"
    assert len(payload["incidents"]) == 2
    assert payload["incidents"][0]["title"] == "Vercel 402"
    assert payload["incidents"][1]["title"] == "Stale FV cache"
    # Cache-Control must be present for edge caching to work.
    assert "s-maxage=300" in resp.headers["Cache-Control"]


@pytest.mark.asyncio
async def test_endpoint_survives_db_outage(monkeypatch):
    monkeypatch.setattr(inc_router, "_get_db_session", lambda: None)

    resp = await inc_router.get_public_incidents()
    import json
    payload = json.loads(resp.body)

    assert payload == {"incidents": [], "current_status": "operational"}


@pytest.mark.asyncio
async def test_endpoint_handles_query_exception(monkeypatch):
    fake_session = MagicMock()
    fake_session.execute.side_effect = RuntimeError("boom")
    monkeypatch.setattr(inc_router, "_get_db_session", lambda: fake_session)

    resp = await inc_router.get_public_incidents()
    import json
    payload = json.loads(resp.body)

    assert payload["incidents"] == []
    assert payload["current_status"] == "operational"
    fake_session.close.assert_called_once()
