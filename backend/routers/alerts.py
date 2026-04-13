# backend/routers/alerts.py
from __future__ import annotations
import sys, os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.models.requests import CreateAlertRequest
from backend.models.responses import AlertResponse, SuccessResponse
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("/", response_model=list[AlertResponse])
async def get_alerts(user: dict = Depends(get_current_user)):
    """Get all active price alerts."""
    try:
        from alerts import get_active_alerts
        alerts = get_active_alerts(int(user["user_id"]))
        return [
            AlertResponse(
                id=a.get("id", 0), ticker=a.get("ticker", ""),
                alert_type=a.get("alert_type", ""), target_price=a.get("target_price", 0),
                created_at=str(a.get("created_at", "")), is_active=a.get("is_active", True),
            )
            for a in alerts
        ]
    except Exception:
        return []


@router.post("/", response_model=SuccessResponse)
async def create_alert(req: CreateAlertRequest, user: dict = Depends(get_current_user)):
    """Create a new price alert."""
    try:
        from alerts import create_alert
        result = create_alert(
            user_id=int(user["user_id"]), ticker=req.ticker.upper(),
            alert_type=req.alert_type, target_price=req.target_price,
            tier=user["tier"],
        )
        if result.get("ok"):
            return SuccessResponse(message=f"Alert set for {req.ticker}")
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{alert_id}", response_model=SuccessResponse)
async def delete_alert(alert_id: int, user: dict = Depends(get_current_user)):
    """Delete a price alert."""
    try:
        from alerts import delete_alert
        result = delete_alert(alert_id, int(user["user_id"]))
        if result.get("ok"):
            return SuccessResponse(message="Alert removed")
        raise HTTPException(status_code=404, detail="Alert not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check")
async def check_alerts(user: dict = Depends(get_current_user)):
    """Check all alerts against current prices."""
    try:
        from alerts import check_alerts
        triggered = check_alerts(int(user["user_id"]))
        return {"triggered": triggered, "count": len(triggered)}
    except Exception:
        return {"triggered": [], "count": 0}
