# backend/routers/notes.py
# ═══════════════════════════════════════════════════════════════
# Save-Note + Decision Tags router — backs the analysis-page
# SaveNotePanel and the /notes index page.
#
# Endpoints (all require_auth):
#   GET    /api/v1/notes/                list signed-in user's notes
#                                        (optional ?tag=… filter)
#   GET    /api/v1/notes/{ticker}        fetch one note (404 when none)
#   POST   /api/v1/notes/{ticker}        upsert (create OR refresh)
#   PUT    /api/v1/notes/{ticker}        strict update (404 when none)
#   DELETE /api/v1/notes/{ticker}        delete (404 when none)
#
# POST is upsert because the frontend auto-save-on-blur path does not
# track create-vs-update — it just POSTs the latest body. PUT is kept
# for API hygiene and explicit-edit flows that want strict 404 on
# missing rows.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.middleware.auth import get_current_user
from backend.services import notes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])


# ── Auth helper ────────────────────────────────────────────────
def _user_id_from_user(user: dict) -> str:
    """Pick a stable identifier from the auth payload. Email is the
    de-facto user key elsewhere (watchlist, alerts, account) so we
    use it here too — keeps the JSONL rows joinable across surfaces.
    """
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Not authenticated")
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")
    return email


# ── Payload models ─────────────────────────────────────────────
class NoteUpsertPayload(BaseModel):
    content_md: str = Field(
        default="",
        description="Markdown body. Capped at 50 000 chars.",
    )
    decision_tag: str = Field(
        default="researching",
        description=(
            "One of researching | watching | skipping | owned | sold."
        ),
    )


class NoteResponse(BaseModel):
    ticker: str
    content_md: str
    decision_tag: str
    created_at: str
    updated_at: str


def _to_response(n: notes_service.Note) -> NoteResponse:
    return NoteResponse(
        ticker=n.ticker,
        content_md=n.content_md,
        decision_tag=n.decision_tag,
        created_at=(
            n.created_at.isoformat()
            if hasattr(n.created_at, "isoformat")
            else str(n.created_at)
        ),
        updated_at=(
            n.updated_at.isoformat()
            if hasattr(n.updated_at, "isoformat")
            else str(n.updated_at)
        ),
    )


# ── GET /api/v1/notes/ — list all user notes ───────────────────
@router.get("/", response_model=list[NoteResponse])
async def list_notes(
    tag: Optional[str] = Query(
        None,
        description=(
            "Optional decision-tag filter. Unknown tags return [] "
            "rather than 400 so the index page can pass raw query "
            "strings without pre-validating."
        ),
    ),
    user: dict = Depends(get_current_user),
):
    """List every note for the signed-in user, newest-first.

    The /notes index page hits this endpoint with no filter to get
    the full set, then re-fetches with ?tag=owned (etc.) when the
    chip selector changes. Cheap by construction — single read of
    the JSONL file, in-memory filter + sort.
    """
    user_id = _user_id_from_user(user)
    rows = notes_service.list_notes_for_user(user_id, decision_tag=tag)
    return [_to_response(r) for r in rows]


# ── GET /api/v1/notes/{ticker} — fetch one ─────────────────────
@router.get("/{ticker}", response_model=NoteResponse)
async def get_note(
    ticker: str,
    user: dict = Depends(get_current_user),
):
    """Fetch the signed-in user's note for one ticker. 404 when none
    — SaveNotePanel reads this on mount and a 404 just means it
    shows the empty composer; treat as a benign first-write state."""
    user_id = _user_id_from_user(user)
    n = notes_service.get_note(user_id, ticker)
    if n is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _to_response(n)


# ── POST /api/v1/notes/{ticker} — upsert ───────────────────────
@router.post("/{ticker}", response_model=NoteResponse)
async def upsert_note(
    ticker: str,
    payload: NoteUpsertPayload,
    user: dict = Depends(get_current_user),
):
    """Create or update a note. Idempotent — the auto-save-on-blur
    path POSTs every blur and trusts the service to merge.

    Tag enum: researching | watching | skipping | owned | sold.
    400 on unknown tags or content over 50 000 chars.
    """
    user_id = _user_id_from_user(user)
    try:
        n = notes_service.create_note(
            user_id=user_id,
            ticker=ticker,
            content_md=payload.content_md or "",
            decision_tag=payload.decision_tag or "researching",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(n)


# ── PUT /api/v1/notes/{ticker} — strict update ─────────────────
@router.put("/{ticker}", response_model=NoteResponse)
async def edit_note(
    ticker: str,
    payload: NoteUpsertPayload,
    user: dict = Depends(get_current_user),
):
    """Strict update — 404 when the row does not exist. Kept distinct
    from POST upsert for explicit-edit flows that want to surface a
    missing-row error rather than silently create."""
    user_id = _user_id_from_user(user)
    try:
        n = notes_service.update_note(
            user_id=user_id,
            ticker=ticker,
            content_md=payload.content_md or "",
            decision_tag=payload.decision_tag or "researching",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if n is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return _to_response(n)


# ── DELETE /api/v1/notes/{ticker} — remove ─────────────────────
@router.delete("/{ticker}")
async def remove_note(
    ticker: str,
    user: dict = Depends(get_current_user),
):
    """Delete a note. 404 when nothing matched so the client can
    distinguish "already gone" from "delete failed"."""
    user_id = _user_id_from_user(user)
    ok = notes_service.delete_note(user_id, ticker)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"message": f"Note for {ticker.upper()} deleted"}


__all__ = ["router"]
