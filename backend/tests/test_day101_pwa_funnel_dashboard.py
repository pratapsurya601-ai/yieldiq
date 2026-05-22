"""Day-101c (2026-05-22): PWA install funnel dashboard + persistent telemetry.

Locks the contract on the new admin aggregation endpoint:

  * POST /api/v1/telemetry/pwa-event persists into pwa_telemetry_events
    in addition to logging (best-effort, never 500s).
  * GET  /api/v1/admin/pwa-funnel returns the 7d totals, a conversion
    rate (installed / prompted), a dismissal rate (dismissed /
    prompted), and a daily breakdown.
  * The admin endpoint is gated by require_admin — non-admins get 403.

The test patches backend.routers.telemetry._get_session to point at an
in-memory SQLite database so we don't need a live Neon during CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import telemetry as telemetry_router  # noqa: E402
from backend.models.pwa_telemetry_event import PwaTelemetryEvent  # noqa: E402
from backend.routers.admin import require_admin  # noqa: E402
from data_pipeline.models import Base  # noqa: E402


ADMIN_USER = {"email": "pratapsurya601@gmail.com"}


@pytest.fixture()
def db_session_factory(monkeypatch: pytest.MonkeyPatch):
    """In-memory SQLite session bound to the shared metadata.

    We only create the one table we care about so we don't pay the
    full schema cost (and so unrelated migration drift never breaks
    this test).
    """
    # TestClient runs each request on its own thread; share a single
    # in-memory SQLite connection across threads using StaticPool +
    # check_same_thread=False so the table created here is visible to
    # the request-handling thread.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PwaTelemetryEvent.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, future=True)

    def fake_get_session():
        return Session()

    monkeypatch.setattr(telemetry_router, "_get_session", fake_get_session)
    return Session


@pytest.fixture()
def client(db_session_factory) -> TestClient:
    app = FastAPI()
    app.include_router(telemetry_router.router)
    app.include_router(telemetry_router.admin_router)
    # Admin gating override — we test the gate separately below.
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    return TestClient(app)


def _post_event(client: TestClient, event: str) -> None:
    r = client.post(
        "/api/v1/telemetry/pwa-event",
        json={"event": event, "ua": "Mozilla/5.0"},
    )
    assert r.status_code == 200, r.text


def test_events_persist_and_funnel_aggregates(client: TestClient) -> None:
    # Post 20 events: 10 prompted, 4 installed, 3 dismissed, 3 ios_hint_shown.
    for _ in range(10):
        _post_event(client, "prompted")
    for _ in range(4):
        _post_event(client, "installed")
    for _ in range(3):
        _post_event(client, "dismissed")
    for _ in range(3):
        _post_event(client, "ios_hint_shown")

    r = client.get("/api/v1/admin/pwa-funnel")
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["window_days"] == 7
    assert data["totals"] == {
        "prompted": 10,
        "installed": 4,
        "dismissed": 3,
        "ios_hint_shown": 3,
    }
    # 4/10 installed → 0.4
    assert data["conversion_rate"] == pytest.approx(0.4, abs=1e-4)
    # 3/10 dismissed → 0.3
    assert data["dismissal_rate"] == pytest.approx(0.3, abs=1e-4)

    # Daily breakdown is non-empty and rows contain all four event keys.
    breakdown = data["daily_breakdown"]
    assert breakdown, breakdown
    row = breakdown[0]
    for key in ("date", "prompted", "installed", "dismissed", "ios_hint_shown"):
        assert key in row, key


def test_funnel_empty_window_returns_zeros(client: TestClient) -> None:
    r = client.get("/api/v1/admin/pwa-funnel")
    assert r.status_code == 200
    data = r.json()
    assert data["totals"] == {
        "prompted": 0,
        "installed": 0,
        "dismissed": 0,
        "ios_hint_shown": 0,
    }
    assert data["conversion_rate"] == 0.0
    assert data["dismissal_rate"] == 0.0
    assert data["daily_breakdown"] == []


def test_funnel_requires_admin(db_session_factory) -> None:
    """Without the admin override the real require_admin should 403."""
    from backend.middleware.auth import get_current_user

    app = FastAPI()
    app.include_router(telemetry_router.admin_router)
    app.dependency_overrides[get_current_user] = lambda: {"email": "rando@example.com"}

    with TestClient(app) as c:
        r = c.get("/api/v1/admin/pwa-funnel")
    assert r.status_code == 403


def test_post_does_not_500_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist failure must never break the user flow."""
    monkeypatch.setattr(telemetry_router, "_get_session", lambda: None)
    app = FastAPI()
    app.include_router(telemetry_router.router)
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/telemetry/pwa-event",
            json={"event": "prompted"},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
