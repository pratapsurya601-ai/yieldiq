"""Tests for the Google OAuth signup/login path (feat/google-oauth-signup).

Covers:
  - verify_google_id_token: success, network error, non-200, unverified email
  - google_oauth_login_or_register: new-user creation path (metadata seeded
    with provider=google + signup_source=google)
  - google_oauth_login_or_register: returning-user login path (existing user
    matched by email, JWT minted with their stored tier)

The Google tokeninfo HTTP call and the Supabase admin client are both
mocked so the suite never touches a real network. Pattern mirrors
backend/tests/test_account_profile.py.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

# Ensure Supabase backend is "configured" for the duration of these tests
# so _auth_backend() returns "supabase" — the helpers we exercise short-
# circuit out of the SQLite path otherwise.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-google-oauth-tests")

from backend.middleware import auth as mw_auth  # noqa: E402


# ── verify_google_id_token ────────────────────────────────────────


def _ok_tokeninfo(email="test@example.com", sub="g-123", verified="true", aud=None):
    payload = {
        "email": email,
        "sub": sub,
        "email_verified": verified,
        "name": "Test User",
        "picture": "https://example.com/p.jpg",
    }
    if aud is not None:
        payload["aud"] = aud
    return SimpleNamespace(status_code=200, json=lambda: payload)


def test_verify_google_id_token_success():
    with patch("requests.get", return_value=_ok_tokeninfo()):
        result = mw_auth.verify_google_id_token("fake-id-token")
    assert result["ok"] is True
    assert result["email"] == "test@example.com"
    assert result["sub"] == "g-123"
    assert result["name"] == "Test User"


def test_verify_google_id_token_empty_token():
    result = mw_auth.verify_google_id_token("")
    assert result["ok"] is False
    assert "Missing" in result["error"]


def test_verify_google_id_token_network_error():
    import requests

    with patch("requests.get", side_effect=requests.RequestException("boom")):
        result = mw_auth.verify_google_id_token("fake")
    assert result["ok"] is False
    assert "Google" in result["error"]


def test_verify_google_id_token_non_200():
    bad = SimpleNamespace(status_code=400, json=lambda: {})
    with patch("requests.get", return_value=bad):
        result = mw_auth.verify_google_id_token("fake")
    assert result["ok"] is False


def test_verify_google_id_token_unverified_email():
    resp = _ok_tokeninfo(verified="false")
    with patch("requests.get", return_value=resp):
        result = mw_auth.verify_google_id_token("fake")
    assert result["ok"] is False
    assert "not verified" in result["error"]


def test_verify_google_id_token_audience_mismatch(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "expected-aud-123")
    with patch("requests.get", return_value=_ok_tokeninfo(aud="some-other-aud")):
        result = mw_auth.verify_google_id_token("fake")
    assert result["ok"] is False


def test_verify_google_id_token_audience_match(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "expected-aud-123")
    with patch("requests.get", return_value=_ok_tokeninfo(aud="expected-aud-123")):
        result = mw_auth.verify_google_id_token("fake")
    assert result["ok"] is True


# ── google_oauth_login_or_register ────────────────────────────────


class _FakeAdminAuth:
    """Stand-in for client.auth.admin used by google_oauth_login_or_register."""

    def __init__(self, existing_users=None):
        self._users = list(existing_users or [])
        self.created = []
        self.updated = []

    def list_users(self):
        return SimpleNamespace(users=list(self._users))

    def create_user(self, payload):
        user = SimpleNamespace(
            id=f"new-uid-{len(self.created) + 1}",
            email=payload["email"],
            user_metadata=dict(payload.get("user_metadata") or {}),
        )
        self.created.append(payload)
        self._users.append(user)
        return SimpleNamespace(user=user)

    def update_user_by_id(self, user_id, payload):
        self.updated.append((user_id, payload))
        return SimpleNamespace(user=SimpleNamespace(id=user_id))


class _FakeAdminClient:
    def __init__(self, existing_users=None):
        self.auth = SimpleNamespace(admin=_FakeAdminAuth(existing_users))


def test_google_oauth_creates_new_user():
    """New-user path: no existing match → create_user invoked with
    provider/signup_source metadata + a JWT comes back."""
    fake_admin = _FakeAdminClient(existing_users=[])

    with patch("requests.get", return_value=_ok_tokeninfo(email="new@user.com", sub="g-new")), \
         patch("db.supabase_client.get_admin_client", return_value=fake_admin):
        result = mw_auth.google_oauth_login_or_register("fake-id-token")

    assert result["ok"] is True
    assert result["is_new_user"] is True
    assert result["email"] == "new@user.com"
    assert result["tier"] == "free"
    assert result["token"]  # JWT minted

    # Metadata seeded with provider tracking so analytics can split
    # google vs email signups later.
    assert len(fake_admin.auth.admin.created) == 1
    created_meta = fake_admin.auth.admin.created[0]["user_metadata"]
    assert created_meta["provider"] == "google"
    assert created_meta["signup_source"] == "google"
    assert created_meta["google_sub"] == "g-new"
    assert created_meta["tier"] == "free"
    # email_confirm=True so the user can sign in immediately (no
    # confirmation-link round-trip).
    assert fake_admin.auth.admin.created[0]["email_confirm"] is True


def test_google_oauth_returning_user_login():
    """Returning-user path: existing user matched by email → no create_user,
    JWT minted with the user's stored tier."""
    existing = SimpleNamespace(
        id="existing-uid-42",
        email="known@user.com",
        user_metadata={"tier": "pro"},
    )
    fake_admin = _FakeAdminClient(existing_users=[existing])

    with patch("requests.get", return_value=_ok_tokeninfo(email="known@user.com", sub="g-known")), \
         patch("db.supabase_client.get_admin_client", return_value=fake_admin):
        result = mw_auth.google_oauth_login_or_register("fake-id-token")

    assert result["ok"] is True
    assert result["is_new_user"] is False
    assert result["user_id"] == "existing-uid-42"
    assert result["tier"] == "pro"
    assert result["email"] == "known@user.com"
    # No new user created — only a metadata backfill for the google_sub link.
    assert fake_admin.auth.admin.created == []
    assert any(uid == "existing-uid-42" for uid, _ in fake_admin.auth.admin.updated)


def test_google_oauth_rejects_invalid_google_token():
    """Tokeninfo failure short-circuits before ever calling Supabase."""
    bad = SimpleNamespace(status_code=400, json=lambda: {})
    with patch("requests.get", return_value=bad):
        result = mw_auth.google_oauth_login_or_register("garbage")
    assert result["ok"] is False
    assert "error" in result


def test_google_oauth_returning_user_case_insensitive_email_match():
    """Returning user lookup must be case-insensitive — Google normalises
    email casing but historical Supabase rows might differ."""
    existing = SimpleNamespace(
        id="mixed-case-uid",
        email="Mixed@User.com",
        user_metadata={"tier": "free"},
    )
    fake_admin = _FakeAdminClient(existing_users=[existing])

    with patch("requests.get", return_value=_ok_tokeninfo(email="mixed@user.com", sub="g-mc")), \
         patch("db.supabase_client.get_admin_client", return_value=fake_admin):
        result = mw_auth.google_oauth_login_or_register("fake")

    assert result["ok"] is True
    assert result["is_new_user"] is False
    assert result["user_id"] == "mixed-case-uid"


# ── build_google_oauth_url ────────────────────────────────────────


def test_build_google_oauth_url_includes_provider_and_redirect(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://my-project.supabase.co")
    url = mw_auth.build_google_oauth_url("https://www.yieldiq.in/auth/callback")
    assert url.startswith("https://my-project.supabase.co/auth/v1/authorize?")
    assert "provider=google" in url
    assert "redirect_to=" in url


def test_build_google_oauth_url_missing_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        mw_auth.build_google_oauth_url("https://www.yieldiq.in/auth/callback")
