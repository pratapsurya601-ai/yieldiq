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

from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import get_current_user
from backend.services import notifications_service as svc

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
