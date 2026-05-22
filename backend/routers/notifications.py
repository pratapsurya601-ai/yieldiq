# backend/routers/notifications.py
# ═══════════════════════════════════════════════════════════════
# In-app notifications HTTP API.
#
# All routes require auth. user_id is taken from the JWT (never a
# query param) so a user can only ever read/modify their own
# notifications.
#
# Endpoints:
#   GET   /api/v1/notifications/unread        -> {items, count}
#   GET   /api/v1/notifications/recent        -> {items}
#   GET   /api/v1/notifications/unread-count  -> {count}   (polled every 60s)
#   PATCH /api/v1/notifications/{id}/read     -> {ok}
#   POST  /api/v1/notifications/mark-all-read -> {ok, marked}
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from backend.middleware.auth import get_current_user
from backend.services import notifications_service as svc
from backend.services import push_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/unread")
async def get_unread(user: dict = Depends(get_current_user)):
    return {
        "items": svc.list_unread(user["user_id"]),
        "count": svc.unread_count(user["user_id"]),
    }


@router.get("/recent")
async def get_recent(user: dict = Depends(get_current_user)):
    return {"items": svc.list_recent(user["user_id"])}


@router.get("/unread-count")
async def get_unread_count(user: dict = Depends(get_current_user)):
    """Tiny endpoint the frontend polls every 60s. Returns just the
    integer count to minimize payload size for cheap bell-badge polling.
    Backed by the partial index `idx_notif_user_unread`.
    """
    return {"count": svc.unread_count(user["user_id"])}


@router.patch("/{notification_id}/read")
async def mark_read(notification_id: int, user: dict = Depends(get_current_user)):
    ok = svc.mark_read(user["user_id"], notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(user: dict = Depends(get_current_user)):
    n = svc.mark_all_read(user["user_id"])
    return {"ok": True, "marked": n}


# ── Day-98: Web Push (PWA) subscribe + test ──────────────────────
#
# Subscribe stores the browser PushManager subscription. Test fires a
# single Web Push to every registered subscription for the user — used
# from /account/notifications "Send test notification" button to
# confirm the round-trip is wired up before the user trusts it for
# real band alerts.


def _get_db():
    """Yield a SQLAlchemy session on the pipeline engine (mirror of
    backend.routers.alerts._get_db).
    """
    from data_pipeline.db import Session as _S
    if _S is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    db = _S()
    try:
        yield db
    finally:
        db.close()


class PushSubscribePayload(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


@router.post("/subscribe")
async def subscribe_push(
    payload: PushSubscribePayload,
    request: Request,
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    """Register (or refresh) a Web Push subscription for the caller."""
    if not payload.endpoint or not payload.p256dh or not payload.auth:
        raise HTTPException(status_code=400, detail="Missing subscription fields")
    ua = (request.headers.get("user-agent") or "")[:255]
    row = push_service.upsert_subscription(
        db,
        user_id=user["user_id"],
        endpoint=payload.endpoint,
        p256dh=payload.p256dh,
        auth=payload.auth,
        user_agent=ua,
    )
    return {"ok": True, "subscription": row}


@router.post("/test")
async def test_push(
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    """Send a Web Push to every subscription on file for the caller.

    Copy is intentionally informational (SEBI-safe vocabulary).

    Hotfix 2026-05-22: target url was /account/notifications — same
    page the test button lives on. Click handler in sw.js found the
    already-open tab, called focus(), and looked like nothing
    happened. Point at / so the click traverses to a visibly
    different surface. Real alerts carry their own ticker URLs.
    """
    delivered = push_service.send_push(
        db,
        user_id=user["user_id"],
        title=push_service.TEST_NOTIFICATION_TITLE,
        body=push_service.TEST_NOTIFICATION_BODY,
        url="/",
    )
    return {"ok": True, "delivered": delivered}
