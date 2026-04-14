# backend/routers/alerts.py
# ═══════════════════════════════════════════════════════════════
# Price Alerts CRUD + trigger checking — Supabase-backed.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys, os, logging
from pathlib import Path
from datetime import datetime, timezone
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

ALERT_LIMITS: dict[str, int] = {
    "free": 3,
    "starter": 50,
    "pro": 9999,
}


def _get_supabase():
    """Get Supabase admin client for server-side alert operations."""
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception:
        return None


# ── GET /api/v1/alerts — list user's active alerts ────────────

@router.get("/", response_model=list[AlertResponse])
async def get_alerts(user: dict = Depends(get_current_user)):
    """Get all active price alerts for the authenticated user."""
    email = user.get("email", "")
    if not email:
        return []

    client = _get_supabase()
    if client:
        try:
            result = (
                client.table("price_alerts")
                .select("*")
                .eq("user_email", email)
                .eq("is_active", True)
                .order("created_at", desc=True)
                .execute()
            )
            return [
                AlertResponse(
                    id=row.get("id", 0),
                    ticker=row.get("ticker", ""),
                    alert_type=row.get("alert_type", ""),
                    target_price=row.get("target_price", 0),
                    created_at=str(row.get("created_at", "")),
                    is_active=row.get("is_active", True),
                )
                for row in (result.data or [])
            ]
        except Exception as e:
            logger.warning(f"Supabase alerts read failed: {e}")

    # Fallback to SQLite
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


# ── POST /api/v1/alerts — create new alert ────────────────────

@router.post("/", response_model=SuccessResponse)
async def create_alert_root(req: CreateAlertRequest, user: dict = Depends(get_current_user)):
    """Create a new price alert (POST to /)."""
    return await create_alert(req, user)


@router.post("/create", response_model=SuccessResponse)
async def create_alert(req: CreateAlertRequest, user: dict = Depends(get_current_user)):
    """Create a new price alert."""
    email = user.get("email", "")
    tier = user.get("tier", "free")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    ticker = req.ticker.strip().upper()
    alert_type = req.alert_type.strip().lower()
    if alert_type not in ("above", "below", "iv_reached", "price_below", "price_above"):
        raise HTTPException(status_code=400, detail=f"Invalid alert type '{alert_type}'")
    # Normalize: price_below -> below, price_above -> above
    if alert_type == "price_below":
        alert_type = "below"
    elif alert_type == "price_above":
        alert_type = "above"

    if req.target_price <= 0:
        raise HTTPException(status_code=400, detail="Target price must be greater than zero")

    client = _get_supabase()
    if client:
        try:
            # Check tier limit
            limit = ALERT_LIMITS.get(tier, 3)
            existing = (
                client.table("price_alerts")
                .select("id", count="exact")
                .eq("user_email", email)
                .eq("is_active", True)
                .execute()
            )
            current_count = existing.count if existing.count is not None else len(existing.data or [])
            if current_count >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Alert limit reached ({current_count}/{limit}). Upgrade for more."
                )

            now = datetime.now(timezone.utc).isoformat()
            client.table("price_alerts").insert({
                "user_email": email,
                "ticker": ticker,
                "alert_type": alert_type,
                "target_price": req.target_price,
                "is_active": True,
                "created_at": now,
            }).execute()
            return SuccessResponse(message=f"Alert set for {ticker}")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Supabase alert create failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to create alert")

    # Fallback to SQLite
    try:
        from alerts import create_alert as _sqlite_create
        result = _sqlite_create(
            user_id=int(user["user_id"]), ticker=ticker,
            alert_type=alert_type, target_price=req.target_price,
            tier=tier,
        )
        if result.get("ok"):
            return SuccessResponse(message=f"Alert set for {ticker}")
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── DELETE /api/v1/alerts/{alert_id} — delete alert ──────────

@router.delete("/{alert_id}", response_model=SuccessResponse)
async def delete_alert(alert_id: int, user: dict = Depends(get_current_user)):
    """Delete a price alert."""
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    client = _get_supabase()
    if client:
        try:
            result = (
                client.table("price_alerts")
                .delete()
                .eq("id", alert_id)
                .eq("user_email", email)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return SuccessResponse(message="Alert removed")
            raise HTTPException(status_code=404, detail="Alert not found")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Supabase alert delete failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete alert")

    # Fallback to SQLite
    try:
        from alerts import delete_alert as _sqlite_delete
        result = _sqlite_delete(alert_id, int(user["user_id"]))
        if result.get("ok"):
            return SuccessResponse(message="Alert removed")
        raise HTTPException(status_code=404, detail="Alert not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /api/v1/alerts/check — manual trigger check ─────────

@router.post("/check")
async def check_alerts_endpoint(user: dict = Depends(get_current_user)):
    """Check all alerts against current prices (manual trigger)."""
    try:
        from backend.services.alert_service import check_and_trigger_alerts
        triggered = check_and_trigger_alerts(user_email=user.get("email"))
        return {"triggered": triggered, "count": len(triggered)}
    except Exception as e:
        logger.warning(f"Alert check failed: {e}")
        return {"triggered": [], "count": 0}
