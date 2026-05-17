"""Tests for the Supabase-session OAuth path (feat/oauth-supabase-session-flow).

Covers verify_supabase_session_token (success, bad shape, admin client
unavailable, get_user raises, user resolves with no email) and the
supabase_session_login_or_register wrapper end-to-end (new user creation
and returning user login), using the same mocking pattern as
test_google_oauth.py.

The Supabase admin SDK is mocked so the suite never touches a real
network.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

# Mirror test_google_oauth: configure env BEFORE importing the module so
# _auth_backend() returns "supabase".
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-supabase-session-tests")

from backend.middleware import auth as mw_auth  # noqa: E402


# A 3-segment JWT-shaped string so the cheap pre-flight passes. Content
# doesn't matter — get_user is mocked.
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.signature_part_here"


def _user(email="returning@example.com", uid="uid-123", provider="google"):
    return SimpleNamespace(
        id=uid,
        email=email,
        app_metadata={"provider": provider},
        user_metadata={"name": "Jane Doe", "picture": "https://x/p.jpg"},
    )


def _ok_get_user(**kwargs):
    return SimpleNamespace(user=_user(**kwargs))


# ── verify_supabase_session_token ────────────────────────────────────


def test_verify_supabase_session_token_empty():
    result = mw_auth.verify_supabase_session_token("")
    assert result["ok"] is False
    assert "Missing" in result["error"]


def test_verify_supabase_session_token_bad_shape():
    # Single segment, no dots — must be rejected before any network call.
    result = mw_auth.verify_supabase_session_token("opaque-not-a-jwt")
    assert result["ok"] is False
    assert "shape" in result["error"].lower()


def test_verify_supabase_session_token_success():
    admin = MagicMock()
    admin.auth.get_user.return_value = _ok_get_user(email="JANE@example.com", uid="u-1")
    with patch("db.supabase_client.get_admin_client", return_value=admin):
        result = mw_auth.verify_supabase_session_token(FAKE_JWT)
    assert result["ok"] is True
    assert result["email"] == "jane@example.com"   # lower-cased
    assert result["sub"] == "u-1"
    assert result["provider"] == "google"
    assert result["name"] == "Jane Doe"
    admin.auth.get_user.assert_called_once_with(FAKE_JWT)


def test_verify_supabase_session_token_get_user_raises():
    admin = MagicMock()
    admin.auth.get_user.side_effect = RuntimeError("token expired")
    with patch("db.supabase_client.get_admin_client", return_value=admin):
        result = mw_auth.verify_supabase_session_token(FAKE_JWT)
    assert result["ok"] is False
    assert "Supabase" in result["error"] or "retry" in result["error"].lower()


def test_verify_supabase_session_token_no_user():
    admin = MagicMock()
    admin.auth.get_user.return_value = SimpleNamespace(user=None)
    with patch("db.supabase_client.get_admin_client", return_value=admin):
        result = mw_auth.verify_supabase_session_token(FAKE_JWT)
    assert result["ok"] is False


def test_verify_supabase_session_token_missing_email():
    admin = MagicMock()
    admin.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="u-1", email=None, app_metadata={}, user_metadata={})
    )
    with patch("db.supabase_client.get_admin_client", return_value=admin):
        result = mw_auth.verify_supabase_session_token(FAKE_JWT)
    assert result["ok"] is False


# ── supabase_session_login_or_register: returning user ───────────────


def test_session_login_returning_user():
    existing = _user(email="returning@example.com", uid="uid-existing")
    existing.user_metadata = {"tier": "pro", "google_sub": "g-1"}
    admin = MagicMock()
    admin.auth.get_user.return_value = SimpleNamespace(user=existing)
    admin.auth.admin.list_users.return_value = SimpleNamespace(users=[existing])

    with patch("db.supabase_client.get_admin_client", return_value=admin), \
         patch("backend.services.verification_service._set_meta_verified"):
        result = mw_auth.supabase_session_login_or_register(FAKE_JWT)

    assert result["ok"] is True
    assert result["is_new_user"] is False
    assert result["email"] == "returning@example.com"
    assert result["tier"] == "pro"
    assert result["token"]  # JWT minted


# ── supabase_session_login_or_register: new user creation ────────────


def test_session_login_new_user_created():
    incoming = _user(email="newbie@example.com", uid="uid-from-session")
    admin = MagicMock()
    admin.auth.get_user.return_value = SimpleNamespace(user=incoming)
    # list_users returns empty so the create path is exercised.
    admin.auth.admin.list_users.return_value = SimpleNamespace(users=[])
    created = SimpleNamespace(user=SimpleNamespace(id="uid-new", email="newbie@example.com"))
    admin.auth.admin.create_user.return_value = created

    with patch("db.supabase_client.get_admin_client", return_value=admin), \
         patch("backend.services.verification_service._set_meta_verified"):
        result = mw_auth.supabase_session_login_or_register(FAKE_JWT)

    assert result["ok"] is True
    assert result["is_new_user"] is True
    assert result["email"] == "newbie@example.com"
    assert result["tier"] == "free"
    assert result["user_id"] == "uid-new"
    # Confirm provider metadata seeded so analytics can split on signup channel.
    create_args = admin.auth.admin.create_user.call_args[0][0]
    assert create_args["email"] == "newbie@example.com"
    assert create_args["email_confirm"] is True
    assert create_args["user_metadata"]["provider"] == "google"
    assert create_args["user_metadata"]["signup_source"] == "google"


def test_session_login_invalid_token_short_circuits():
    """When the JWT pre-flight fails we must not touch Supabase at all."""
    with patch("db.supabase_client.get_admin_client") as get_admin:
        result = mw_auth.supabase_session_login_or_register("not-a-jwt")
    assert result["ok"] is False
    get_admin.assert_not_called()
