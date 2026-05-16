"""Tests for the unsubscribe flow and the notification-preferences API.

Covers:
  - HMAC token validation (good token, bad token, missing token)
  - GET /api/v1/email/unsubscribe sets the opt-out flag
  - GET/PUT /api/v1/email/preferences round-trips through Supabase
    user_metadata (using a fake admin client, no network)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch):
    """Minimal FastAPI app wired with just the email router and a
    stub get_current_user so we can hit the prefs endpoints."""
    monkeypatch.setenv("JWT_SECRET", "unsub-test-secret")
    monkeypatch.setenv("SENDGRID_API_KEY", "test-key")
    from fastapi import FastAPI
    from backend.routers import email as email_router
    from backend.middleware.auth import get_current_user

    app = FastAPI()
    app.include_router(email_router.router)

    # Override the auth dep so the prefs routes don't need a real JWT.
    def _fake_user():
        return {"user_id": "user-uuid-1", "email": "u@example.com",
                "tier": "free"}
    app.dependency_overrides[get_current_user] = _fake_user
    return app


def test_unsubscribe_token_required_when_provided(monkeypatch, app):
    """If a token is provided but doesn't match, the endpoint must
    reject the request rather than silently opting the user out."""
    from backend.services import email_service

    monkeypatch.setattr(email_service, "verify_unsubscribe_token",
                        lambda e, t: False)
    monkeypatch.setattr(email_service, "mark_user_unsubscribed",
                        lambda e: True)

    client = TestClient(app)
    r = client.get(
        "/api/v1/email/unsubscribe",
        params={"email": "u@example.com", "token": "bad"},
    )
    assert r.status_code == 400
    assert "Invalid" in r.text


def test_unsubscribe_valid_token_marks_opt_out(monkeypatch, app):
    from backend.services import email_service

    called = {}

    def _mark(e: str) -> bool:
        called["email"] = e
        return True

    monkeypatch.setattr(email_service, "verify_unsubscribe_token",
                        lambda e, t: True)
    monkeypatch.setattr(email_service, "mark_user_unsubscribed", _mark)

    client = TestClient(app)
    r = client.get(
        "/api/v1/email/unsubscribe",
        params={"email": "u@example.com", "token": "good"},
    )
    assert r.status_code == 200
    assert called["email"] == "u@example.com"


def test_hmac_token_roundtrip(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unsub-test-secret")
    from backend.services import email_service
    import importlib
    importlib.reload(email_service)
    url = email_service._get_unsubscribe_url("user@example.com")
    token = url.split("token=")[-1]
    assert email_service.verify_unsubscribe_token("user@example.com", token)
    assert not email_service.verify_unsubscribe_token("other@example.com", token)


# ── preferences API --------------------------------------------------

class _FakeAdminAuth:
    def __init__(self, metadata):
        self.metadata = dict(metadata)
        self.last_update = None

    def get_user_by_id(self, _uid):
        return SimpleNamespace(user=SimpleNamespace(user_metadata=self.metadata))

    def update_user_by_id(self, _uid, payload):
        self.last_update = payload
        self.metadata.update(payload.get("user_metadata", {}))
        return SimpleNamespace(user=SimpleNamespace(user_metadata=self.metadata))


class _FakeClient:
    def __init__(self, metadata):
        self.auth = SimpleNamespace(admin=_FakeAdminAuth(metadata))


def test_get_preferences_defaults_to_opted_in(monkeypatch, app):
    fake = _FakeClient({})
    monkeypatch.setattr("db.supabase_client.get_admin_client", lambda: fake)

    client = TestClient(app)
    r = client.get("/api/v1/email/preferences")
    assert r.status_code == 200
    data = r.json()
    assert data == {"weekly_digest": True, "band_alerts": True,
                    "product_updates": True}


def test_get_preferences_reflects_unsub_flags(monkeypatch, app):
    fake = _FakeClient({"weekly_digest_unsubscribed": True})
    monkeypatch.setattr("db.supabase_client.get_admin_client", lambda: fake)

    client = TestClient(app)
    r = client.get("/api/v1/email/preferences")
    assert r.status_code == 200
    assert r.json()["weekly_digest"] is False
    assert r.json()["band_alerts"] is True


def test_put_preferences_writes_inverted_flags(monkeypatch, app):
    fake = _FakeClient({})
    monkeypatch.setattr("db.supabase_client.get_admin_client", lambda: fake)

    client = TestClient(app)
    r = client.put(
        "/api/v1/email/preferences",
        json={"weekly_digest": False, "band_alerts": True,
              "product_updates": False},
    )
    assert r.status_code == 200
    update = fake.auth.admin.last_update
    assert update["user_metadata"]["weekly_digest_unsubscribed"] is True
    assert update["user_metadata"]["band_alerts_unsubscribed"] is False
    assert update["user_metadata"]["product_updates_unsubscribed"] is True
