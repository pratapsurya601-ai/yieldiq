# backend/routers/mos_band_alerts.py
# ═══════════════════════════════════════════════════════════════
# MoS-band alert subscriptions — task #131 retention play.
#
# Mounted at /api/v1/alerts/mos-band so it sits alongside the legacy
# /api/v1/alerts/* router (backend/routers/alerts.py) without clashing
# on the GET/POST/DELETE shape. Different storage (JSONL via
# mos_band_alerts_service) and different threshold semantics — see
# the service docstring for the design rationale.
#
# Endpoints (all auth-gated):
#   POST   /api/v1/alerts/mos-band
#   GET    /api/v1/alerts/mos-band
#   DELETE /api/v1/alerts/mos-band/{ticker}/{threshold_pct}/{direction}
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services import mos_band_alerts_service as mbas

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/alerts/mos-band",
    tags=["alerts", "mos-band"],
)


class CreateBandAlertPayload(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    threshold_pct: float = Field(
        ...,
        ge=mbas.THRESHOLD_MIN,
        le=mbas.THRESHOLD_MAX,
        description=(
            "Margin-of-safety percentage threshold. -50..+50 in 5pp "
            "steps recommended."
        ),
    )
    direction: Literal["positive", "negative"]


def _user_id(user: dict) -> str:
    uid = user.get("user_id") or user.get("sub") or user.get("email")
    if not uid:
        raise HTTPException(status_code=401, detail="Missing user identifier")
    return str(uid)


@router.post("")
async def create_band_alert(
    payload: CreateBandAlertPayload,
    user: dict = Depends(get_current_user),
):
    """Create (idempotent) a MoS-band alert subscription."""
    uid = _user_id(user)
    try:
        sub = mbas.create_subscription(
            user_id=uid,
            ticker=payload.ticker,
            threshold_pct=float(payload.threshold_pct),
            direction=payload.direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("mos_band_alerts: create failed user=%s ticker=%s",
                         uid, payload.ticker)
        raise HTTPException(status_code=500, detail="Could not create alert")
    return sub.to_dict()


@router.get("")
async def list_band_alerts(user: dict = Depends(get_current_user)):
    """List the calling user's MoS-band alert subscriptions."""
    uid = _user_id(user)
    return {"alerts": [s.to_dict() for s in mbas.list_subscriptions_for_user(uid)]}


@router.delete("/{ticker}/{threshold_pct}/{direction}")
async def delete_band_alert(
    ticker: str,
    threshold_pct: float,
    direction: str,
    user: dict = Depends(get_current_user),
):
    """Remove a MoS-band alert subscription identified by the path triple."""
    uid = _user_id(user)
    if direction not in ("positive", "negative"):
        raise HTTPException(
            status_code=400,
            detail="direction must be 'positive' or 'negative'",
        )
    ok = mbas.delete_subscription(uid, ticker, threshold_pct, direction)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}
