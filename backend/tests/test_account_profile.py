"""Tests for the editable-display-name endpoint (PR #72).

Covers:
  - PATCH /api/v1/account/profile success path
  - 400 on invalid display names (empty, too long, '@', '<')
  - 403 on exhausted lifetime edits (3rd edit OK, 4th edit blocked)
  - Edit counter increments correctly across calls

The Supabase admin client is mocked via a stand-in object so the
suite never touches a real network. Pattern mirrors the in-memory
fakes used in backend/tests/test_score_history.py.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.routers import account as account_router


class _FakeAdminAuth:
    """Tiny stand-in for `client.auth.admin`. Records every update and
    returns whatever metadata we seed it with on get_user_by_id."""

    def __init__(self, metadata: dict):
        self._metadata = dict(metadata)
        self.last_update = None

    def get_user_by_id(self, user_id: str):
        # Mirror the supabase-py shape: response.user.user_metadata
        return SimpleNamespace(
            user=SimpleNamespace(user_metadata=dict(self._metadata))
        )

    def update_user_by_id(self, user_id: str, payload: dict):
        meta = payload.get("user_metadata") or {}
        self._metadata = dict(meta)
        self.last_update = (user_id, dict(meta))
        return SimpleNamespace(user=SimpleNamespace(user_metadata=dict(meta)))


class _FakeSupabaseClient:
    def __init__(self, metadata: dict | None = None):
        self.auth = SimpleNamespace(admin=_FakeAdminAuth(metadata or {}))


def _patch_client(metadata: dict | None = None) -> _FakeSupabaseClient:
    """Patch get_admin_client at the place account.py imports it from."""
    fake = _FakeSupabaseClient(metadata or {})
    return fake


def _run_update(fake: _FakeSupabaseClient, name: str, user_id: str = "u-1"):
    """Invoke the endpoint coroutine synchronously with a mocked client."""
    import asyncio
    from db import supabase_client as _supa
    with patch.object(_supa, "get_admin_client", return_value=fake):
        body = account_router.ProfileUpdateRequest(display_name=name)
        return asyncio.get_event_loop().run_until_complete(
            account_router.update_profile(body, user={"user_id": user_id, "email": "x@y.com", "tier": "free"})
        )


# ── Success path ──────────────────────────────────────────────────


def test_update_profile_first_edit_success():
    fake = _patch_client({})
    resp = _run_update(fake, "Vinit S")
    assert resp.display_name == "Vinit S"
    assert resp.edits_used == 1
    assert resp.edits_remaining == 2
    # Metadata mutated correctly + first_set_at stamped.
    _uid, meta = fake.auth.admin.last_update
    assert meta["display_name"] == "Vinit S"
    assert meta["display_name_edits_used"] == 1
    assert "display_name_first_set_at" in meta
    assert meta["display_name_first_set_at"].endswith("Z")


def test_update_profile_trims_whitespace():
    fake = _patch_client({})
    resp = _run_update(fake, "   Vinit Sood   ")
    assert resp.display_name == "Vinit Sood"


# ── Validation 400s ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_name",
    [
        "   ",                    # whitespace only
        "x" * 61,                 # > MAX_DISPLAY_NAME_MAX_LEN
        "vinit@home",             # contains '@'
        "<script>",               # contains '<'
        "name>tag",               # contains '>'
    ],
)
def test_update_profile_rejects_invalid_names(bad_name):
    fake = _patch_client({})
    with pytest.raises(HTTPException) as exc:
        _run_update(fake, bad_name)
    assert exc.value.status_code == 400


def test_update_profile_rejects_empty_at_pydantic_layer():
    """Empty string fails Pydantic field validation before our handler
    runs — that becomes a 422 in real FastAPI requests, which is still
    a hard reject. Locking that behaviour here."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        account_router.ProfileUpdateRequest(display_name="")


# ── Lifetime cap (403) ────────────────────────────────────────────


def test_update_profile_blocks_after_three_edits():
    fake = _patch_client({
        "display_name": "Old Name",
        "display_name_edits_used": 3,
        "display_name_first_set_at": "2026-01-01T00:00:00Z",
    })
    with pytest.raises(HTTPException) as exc:
        _run_update(fake, "Tries Anyway")
    assert exc.value.status_code == 403
    assert "limit" in str(exc.value.detail).lower()


def test_update_profile_counter_increments_across_calls():
    fake = _patch_client({})
    r1 = _run_update(fake, "First")
    assert (r1.edits_used, r1.edits_remaining) == (1, 2)
    r2 = _run_update(fake, "Second")
    assert (r2.edits_used, r2.edits_remaining) == (2, 1)
    r3 = _run_update(fake, "Third")
    assert (r3.edits_used, r3.edits_remaining) == (3, 0)
    # Fourth edit must 403.
    with pytest.raises(HTTPException) as exc:
        _run_update(fake, "Fourth")
    assert exc.value.status_code == 403


def test_first_set_at_preserved_across_edits():
    fake = _patch_client({})
    _run_update(fake, "First")
    first_stamp = fake.auth.admin._metadata["display_name_first_set_at"]
    _run_update(fake, "Second")
    assert fake.auth.admin._metadata["display_name_first_set_at"] == first_stamp


# ── get_display_name_state helper ─────────────────────────────────


def test_get_display_name_state_with_existing_metadata():
    fake = _patch_client({
        "display_name": "Vinit",
        "display_name_edits_used": 1,
    })
    from db import supabase_client as _supa
    with patch.object(_supa, "get_admin_client", return_value=fake):
        name, remaining = account_router.get_display_name_state("u-1")
    assert name == "Vinit"
    assert remaining == 2


def test_get_display_name_state_soft_fails_when_client_unavailable():
    from db import supabase_client as _supa
    with patch.object(_supa, "get_admin_client", side_effect=RuntimeError("nope")):
        name, remaining = account_router.get_display_name_state("u-1")
    assert name is None
    assert remaining == account_router.MAX_DISPLAY_NAME_EDITS
