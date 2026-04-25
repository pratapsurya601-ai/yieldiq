# backend/routers/account.py
# ═══════════════════════════════════════════════════════════════
# Account profile endpoints — editable display name with a 3-edit
# lifetime cap stored in Supabase auth.users.raw_user_meta_data.
#
# Storage decision: piggyback on Supabase's built-in user_metadata
# JSONB blob (no DB migration). Schema:
#   {
#     "display_name": str,
#     "display_name_edits_used": int,        # 0..3
#     "display_name_first_set_at": ISO8601,  # set on first edit
#   }
#
# The 3-edit cap is enforced server-side. Anti-abuse rationale: once
# we wire the display name into social/community surfaces, we don't
# want users churning their handle to dodge moderation. Free-text but
# capped is a reasonable middle ground.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user

_log = logging.getLogger("yieldiq.account.profile")

router = APIRouter(prefix="/api/v1/account", tags=["account"])

# Lifetime cap on display-name edits. Bump only after a real product
# decision — this is the integer the test_account_profile suite
# locks against.
MAX_DISPLAY_NAME_EDITS = 3

# Hard server-side bounds. Match StepName.tsx + /account/profile.
DISPLAY_NAME_MIN_LEN = 1
DISPLAY_NAME_MAX_LEN = 60


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)


class ProfileUpdateResponse(BaseModel):
    display_name: str
    edits_used: int
    edits_remaining: int


def _validate_display_name(raw: str) -> str:
    """Return the canonicalized display name or raise HTTPException(400).

    Validation rules (kept narrow on purpose):
      - 1..60 chars after trim
      - no '@' (prevents email-as-name confusion)
      - no '<' / '>' (XSS-safe even though render escapes)
      - not all whitespace
    """
    if raw is None:
        raise HTTPException(status_code=400, detail="Display name is required.")
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Display name cannot be empty.")
    if len(name) < DISPLAY_NAME_MIN_LEN or len(name) > DISPLAY_NAME_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Display name must be {DISPLAY_NAME_MIN_LEN}-{DISPLAY_NAME_MAX_LEN} characters.",
        )
    if "@" in name:
        raise HTTPException(
            status_code=400,
            detail="Display name cannot contain '@'.",
        )
    if "<" in name or ">" in name:
        raise HTTPException(
            status_code=400,
            detail="Display name cannot contain '<' or '>'.",
        )
    return name


def _read_user_metadata(client, user_id: str) -> dict:
    """Best-effort read of auth.users.raw_user_meta_data via the admin API.

    Returns {} on any failure — callers must treat absence as "first edit".
    """
    try:
        resp = client.auth.admin.get_user_by_id(user_id)
    except Exception as exc:
        _log.warning("admin.get_user_by_id failed for %s: %s", user_id, exc)
        return {}
    user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)
    if user is None:
        return {}
    meta = getattr(user, "user_metadata", None)
    if meta is None and isinstance(user, dict):
        meta = user.get("user_metadata") or user.get("raw_user_meta_data")
    return dict(meta or {})


def _coerce_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_display_name_state(user_id: str) -> tuple[Optional[str], int]:
    """Return (display_name, edits_remaining) for a user.

    Used by /auth/login and /auth/me to surface the current display
    name + remaining edit budget without forcing a separate frontend
    round-trip. Soft-fails to (None, MAX) when Supabase is unreachable
    so the auth flow never hard-breaks on a metadata lookup hiccup.
    """
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
    except Exception as exc:
        _log.warning("supabase admin client unavailable: %s", exc)
        return None, MAX_DISPLAY_NAME_EDITS
    meta = _read_user_metadata(client, user_id)
    name = meta.get("display_name")
    used = _coerce_int(meta.get("display_name_edits_used"), 0)
    remaining = max(0, MAX_DISPLAY_NAME_EDITS - used)
    return (name if isinstance(name, str) and name else None), remaining


@router.patch("/profile", response_model=ProfileUpdateResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update the authenticated user's display name.

    Enforces the 3-edit lifetime cap. On the first edit, also stamps
    display_name_first_set_at so we have an audit anchor.
    """
    name = _validate_display_name(body.display_name)

    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="No user_id on session.")

    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
    except Exception as exc:
        _log.error("supabase admin client unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Profile service unavailable — please try again shortly.",
        )

    meta = _read_user_metadata(client, user_id)
    used = _coerce_int(meta.get("display_name_edits_used"), 0)
    if used >= MAX_DISPLAY_NAME_EDITS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Display-name edit limit reached "
                f"({MAX_DISPLAY_NAME_EDITS} lifetime edits)."
            ),
        )

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    new_meta = dict(meta)
    new_meta["display_name"] = name
    new_meta["display_name_edits_used"] = used + 1
    if not meta.get("display_name_first_set_at"):
        new_meta["display_name_first_set_at"] = now_iso

    try:
        client.auth.admin.update_user_by_id(
            user_id, {"user_metadata": new_meta}
        )
    except Exception as exc:
        _log.error("update_user_by_id failed for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Couldn't save display name — please try again.",
        )

    new_used = used + 1
    return ProfileUpdateResponse(
        display_name=name,
        edits_used=new_used,
        edits_remaining=max(0, MAX_DISPLAY_NAME_EDITS - new_used),
    )
