# backend/routers/alerts.py
# ═══════════════════════════════════════════════════════════════
# Alerts CRUD — backed by the Postgres `user_alerts` table
# (migration 009). Evaluated hourly by scripts/alerts_evaluator.py.
#
# Endpoints (all require_auth):
#   GET    /api/v1/alerts/          list my alerts
#   POST   /api/v1/alerts/          create alert
#   PATCH  /api/v1/alerts/{id}      update status/threshold
#   DELETE /api/v1/alerts/{id}      delete
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.middleware.auth import get_current_user
from backend.models.alerts import ALERT_KINDS, ALERT_STATUSES, UserAlert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


# ── Dependency: DB session ────────────────────────────────────

def _get_db():
    """Yield a SQLAlchemy session bound to the pipeline engine.

    Raises 503 if DATABASE_URL isn't configured — the alerts engine is
    Postgres-only; there is no SQLite fallback for the new schema.
    """
    from data_pipeline.db import Session as _S
    if _S is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    db = _S()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic payloads ─────────────────────────────────────────

class AlertCreatePayload(BaseModel):
    ticker: str
    kind: str
    threshold: Optional[float] = None
    notify_email: Optional[bool] = True
    notify_push: Optional[bool] = False


# Legacy payload shape used by the old Supabase-backed router and still
# emitted by frontend/src/lib/api.ts createAlert() at time of the
# migration. Translated into AlertCreatePayload by POST /create below.
class LegacyAlertCreatePayload(BaseModel):
    ticker: str
    alert_type: str  # "price_above" | "price_below" | "mos_above" | ...
    target_price: float


class AlertPatchPayload(BaseModel):
    status: Optional[str] = None
    threshold: Optional[float] = None
    notify_email: Optional[bool] = None
    notify_push: Optional[bool] = None


def _user_id(user: dict) -> str:
    """Extract the stable user identifier from the JWT payload."""
    uid = user.get("user_id") or user.get("sub") or user.get("email")
    if not uid:
        raise HTTPException(status_code=401, detail="Missing user identifier")
    return str(uid)


def _serialize(alert: UserAlert) -> dict:
    return alert.to_dict()


# ── GET / ─────────────────────────────────────────────────────

@router.get("/")
async def list_alerts(
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    uid = _user_id(user)
    rows = (
        db.query(UserAlert)
        .filter(UserAlert.user_id == uid)
        .order_by(UserAlert.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


# ── POST / ────────────────────────────────────────────────────

@router.post("/create")
async def create_alert_legacy(
    payload: LegacyAlertCreatePayload,
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    """Legacy-shape compatibility route for frontend/src/lib/api.ts
    ``createAlert()``. Translates ``{alert_type, target_price}`` to the
    new ``{kind, threshold}`` and delegates to create_alert."""
    translated = AlertCreatePayload(
        ticker=payload.ticker,
        kind=payload.alert_type,
        threshold=payload.target_price,
    )
    return await create_alert(translated, user=user, db=db)


@router.post("/")
async def create_alert(
    payload: AlertCreatePayload,
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    uid = _user_id(user)
    ticker = (payload.ticker or "").strip().upper()
    kind = (payload.kind or "").strip().lower()

    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")
    if kind not in ALERT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid kind '{kind}' (allowed: {', '.join(ALERT_KINDS)})",
        )
    # threshold required for everything except verdict_change
    if kind != "verdict_change" and payload.threshold is None:
        raise HTTPException(
            status_code=400,
            detail=f"threshold is required for kind='{kind}'",
        )

    existing = (
        db.query(UserAlert)
        .filter(
            UserAlert.user_id == uid,
            UserAlert.ticker == ticker,
            UserAlert.kind == kind,
        )
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Alert already exists for this (ticker, kind)",
        )

    alert = UserAlert(
        user_id=uid,
        ticker=ticker,
        kind=kind,
        threshold=payload.threshold if kind != "verdict_change" else None,
        status="active",
        notify_email=bool(payload.notify_email) if payload.notify_email is not None else True,
        notify_push=bool(payload.notify_push) if payload.notify_push is not None else False,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _serialize(alert)


# ── PATCH /{id} ───────────────────────────────────────────────

@router.patch("/{alert_id}")
async def update_alert(
    alert_id: int,
    payload: AlertPatchPayload,
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    uid = _user_id(user)
    alert = (
        db.query(UserAlert)
        .filter(UserAlert.id == alert_id, UserAlert.user_id == uid)
        .one_or_none()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    if payload.status is not None:
        if payload.status not in ALERT_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid status (allowed: {', '.join(ALERT_STATUSES)})",
            )
        alert.status = payload.status
    if payload.threshold is not None:
        alert.threshold = payload.threshold
    if payload.notify_email is not None:
        alert.notify_email = bool(payload.notify_email)
    if payload.notify_push is not None:
        alert.notify_push = bool(payload.notify_push)

    db.commit()
    db.refresh(alert)
    return _serialize(alert)


# ── DELETE /{id} ──────────────────────────────────────────────

@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: int,
    user: dict = Depends(get_current_user),
    db: OrmSession = Depends(_get_db),
):
    uid = _user_id(user)
    alert = (
        db.query(UserAlert)
        .filter(UserAlert.id == alert_id, UserAlert.user_id == uid)
        .one_or_none()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()
    return {"ok": True, "id": alert_id}
