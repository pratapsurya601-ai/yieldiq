"""User-facing CRUD for API keys.

Endpoints (all gated by JWT — these manage keys, they don't use them):
  * GET    /api/v1/account/api-keys/         List active keys
  * POST   /api/v1/account/api-keys/         Create a new key (Pro only)
  * DELETE /api/v1/account/api-keys/{id}     Revoke a key

Tier policy:
  * Free / Analyst can list — they'll just see an empty array. We don't
    403 reads so the UI never has to special-case "did the user ever
    have a key on a higher tier?".
  * POST is Pro-only and additionally capped at
    ``DEFAULT_ACTIVE_KEY_CAP`` active keys per user.

Security:
  * The raw key value is included in the POST response — and only there.
    GET never returns it. The frontend MUST capture-and-show it once.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services import api_keys_service as svc

logger = logging.getLogger("yieldiq.api_keys.router")

router = APIRouter(prefix="/api/v1/account/api-keys", tags=["api-keys"])


# ── Request / response models ────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    label: Optional[str] = Field(
        default=None,
        max_length=80,
        description="User-supplied label, e.g. 'My Sheets script'.",
    )


class ApiKeySummary(BaseModel):
    id: int
    key_prefix: str
    label: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ListKeysResponse(BaseModel):
    keys: List[ApiKeySummary]


class CreateKeyResponse(BaseModel):
    id: int
    raw: str = Field(
        ..., description="The raw API key. Shown ONCE — capture it now."
    )
    prefix: str
    label: str
    created_at: Optional[str] = None
    daily_cap: int = svc.DAILY_REQUEST_CAP


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/", response_model=ListKeysResponse)
async def list_my_keys(user: dict = Depends(get_current_user)):
    """List the user's active keys (no raw values).

    Free/Analyst can call; they'll see an empty list. Read is unrestricted
    so the UI doesn't have to gate the page on tier just to render
    "no keys yet".
    """
    keys = svc.list_keys(user["user_id"])
    return {"keys": keys}


@router.post("/", response_model=CreateKeyResponse)
async def create_my_key(
    body: CreateKeyRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new key. Pro-only. Returns the RAW key in the response —
    only opportunity to capture it. Frontend MUST show with a copy
    button and a "this is your only chance" warning.
    """
    if user.get("tier") != "pro":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tier_required",
                "required_tier": "pro",
                "message": "API access is a Pro-tier feature.",
                "upgrade_link": "/pricing",
            },
        )

    # TODO: once tier_caps lands, replace DEFAULT_ACTIVE_KEY_CAP with
    # tier_caps.cap_for(user['tier'], 'active_api_keys') so the limit
    # is data-driven instead of hardcoded.
    existing = svc.list_keys(user["user_id"])
    cap = svc.DEFAULT_ACTIVE_KEY_CAP
    if len(existing) >= cap:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "key_count_cap_reached",
                "cap": cap,
                "current": len(existing),
                "message": (
                    f"Pro plan allows up to {cap} active API keys. "
                    "Revoke one to create another."
                ),
            },
        )

    result = svc.create_key(user["user_id"], body.label or "Untitled")
    # Include the daily cap so the UI can display "100 req/day" right
    # next to the new key without a separate config endpoint.
    result["daily_cap"] = svc.DAILY_REQUEST_CAP
    return result


@router.delete("/{key_id}")
async def revoke_my_key(
    key_id: int,
    user: dict = Depends(get_current_user),
):
    """Revoke a key. Idempotent from the user's perspective in that a
    second DELETE for the same id returns 404 ("already gone")."""
    ok = svc.revoke_key(user["user_id"], key_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Key not found or already revoked.",
        )
    return {"ok": True}
