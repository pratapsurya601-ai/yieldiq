"""Phase J — observation harness.

Locks the contract on the two endpoints introduced by
backend/routers/internal.py:

  * POST /api/v1/internal/session-trace — requires session JWT. Anon
    callers get 401. Auth'd callers get 200 with a row written.
  * GET  /api/v1/admin/session-traces — requires admin role. Non-admin
    auth'd callers get 403. Admin gets 200 with paginated results.

The DB is an in-memory SQLite bound to the SessionTrace metadata —
same pattern used by test_day101_pwa_funnel_dashboard.py.
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

from backend.routers import internal as internal_router  # noqa: E402
from backend.models.session_trace import SessionTrace  # noqa: E402
from backend.middleware.auth import get_current_user  # noqa: E402
from backend.routers.admin import require_admin  # noqa: E402


ADMIN_USER = {"user_id": "u-admin", "email": "pratapsurya601@gmail.com", "tier": "pro"}
AUTH_USER = {"user_id": "u-regular", "email": "user@example.com", "tier": "free"}


@pytest.fixture()
def session_factory(monkeypatch: pytest.MonkeyPatch):
    # SQLite doesn't grok JSONB natively — SQLAlchemy maps it to JSON
    # transparently for the SQLite dialect, which is what we want for
    # an in-memory test.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionTrace.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, future=True)

    def fake_get_session():
        return Session()

    monkeypatch.setattr(internal_router, "_get_session", fake_get_session)
    return Session


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(internal_router.router)
    app.include_router(internal_router.admin_router)
    return app


def test_anon_post_returns_401(session_factory) -> None:
    app = _build_app()
    # No dependency override → get_current_user raises 401 via the
    # HTTPBearer auto_error=False + None-credentials branch.
    client = TestClient(app)
    r = client.post(
        "/api/v1/internal/session-trace",
        json={
            "session_id": "s1",
            "events": [{"event_type": "page_view", "event_data": {"path": "/x"}}],
        },
    )
    assert r.status_code == 401, r.text


def test_auth_post_returns_200_and_writes_row(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _build_app()
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    client = TestClient(app)

    r = client.post(
        "/api/v1/internal/session-trace",
        json={
            "session_id": "s-abc",
            "events": [
                {"event_type": "page_view", "event_data": {"path": "/analysis/RELIANCE.NS"}},
                {"event_type": "button_click", "event_data": {"button_id": "expand_dcf"}},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["persisted"] == 2

    sess = session_factory()
    try:
        rows = sess.query(SessionTrace).order_by(SessionTrace.id).all()
        assert len(rows) == 2
        assert all(row.user_id == "u-regular" for row in rows)
        assert all(row.session_id == "s-abc" for row in rows)
        assert rows[0].event_type == "page_view"
        assert rows[1].event_type == "button_click"
    finally:
        sess.close()


def test_auth_post_rejects_bad_event_type(session_factory) -> None:
    app = _build_app()
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    client = TestClient(app)
    r = client.post(
        "/api/v1/internal/session-trace",
        json={
            "session_id": "s-bad",
            "events": [{"event_type": "form_submit", "event_data": {}}],
        },
    )
    # Pydantic Literal mismatch → 422.
    assert r.status_code == 422, r.text


def test_admin_get_returns_paginated(session_factory) -> None:
    app = _build_app()
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    client = TestClient(app)

    # Seed 5 events via the POST endpoint.
    for i in range(5):
        r = client.post(
            "/api/v1/internal/session-trace",
            json={
                "session_id": "s-seed",
                "events": [
                    {"event_type": "page_view", "event_data": {"path": f"/p/{i}"}}
                ],
            },
        )
        assert r.status_code == 200, r.text

    r = client.get("/api/v1/admin/session-traces?limit=3")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["limit"] == 3
    assert data["offset"] == 0
    assert len(data["traces"]) == 3
    # Newest first.
    paths = [t["event_data"]["path"] for t in data["traces"]]
    assert paths == ["/p/4", "/p/3", "/p/2"]

    r2 = client.get("/api/v1/admin/session-traces?limit=3&offset=3")
    assert r2.status_code == 200, r2.text
    page2 = r2.json()
    assert len(page2["traces"]) == 2
    paths2 = [t["event_data"]["path"] for t in page2["traces"]]
    assert paths2 == ["/p/1", "/p/0"]


def test_non_admin_get_returns_403(session_factory) -> None:
    app = _build_app()
    # Only override get_current_user — leave require_admin in place so
    # its real allow-list check kicks in and returns 403.
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    client = TestClient(app)
    r = client.get("/api/v1/admin/session-traces")
    assert r.status_code == 403, r.text


def test_admin_get_with_since_filter(session_factory) -> None:
    app = _build_app()
    app.dependency_overrides[get_current_user] = lambda: AUTH_USER
    app.dependency_overrides[require_admin] = lambda: ADMIN_USER
    client = TestClient(app)

    # Insert a row, then query with since=now() — should return 0.
    r = client.post(
        "/api/v1/internal/session-trace",
        json={
            "session_id": "s-since",
            "events": [{"event_type": "page_view", "event_data": {"path": "/x"}}],
        },
    )
    assert r.status_code == 200

    # Use a since timestamp far in the future.
    r = client.get(
        "/api/v1/admin/session-traces?since=2099-01-01T00:00:00Z"
    )
    assert r.status_code == 200
    assert r.json()["traces"] == []
