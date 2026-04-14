# backend/routers/watchlist.py
# ═══════════════════════════════════════════════════════════════
# Watchlist CRUD — Supabase-backed, per-user by email.
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

from backend.models.requests import AddWatchlistRequest
from backend.models.responses import WatchlistItemResponse, SuccessResponse
from backend.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


def _get_supabase():
    """Get Supabase admin client for server-side watchlist operations."""
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception:
        return None


# ── GET /api/v1/watchlist — list user's watchlist ─────────────

@router.get("/", response_model=list[WatchlistItemResponse])
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get all watchlist items for the authenticated user."""
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    client = _get_supabase()
    if client:
        try:
            result = (
                client.table("watchlist")
                .select("*")
                .eq("user_email", email)
                .order("added_at", desc=True)
                .execute()
            )
            return [
                WatchlistItemResponse(
                    ticker=row.get("ticker", ""),
                    company_name=row.get("company_name", ""),
                    added_price=row.get("added_price", 0),
                    added_at=str(row.get("added_at", "")),
                )
                for row in (result.data or [])
            ]
        except Exception as e:
            logger.warning(f"Supabase watchlist read failed: {e}")

    # Fallback to dashboard SQLite
    try:
        from portfolio import get_watchlist as _sqlite_get
        items = _sqlite_get()
        return [
            WatchlistItemResponse(
                ticker=w.get("ticker", ""),
                company_name=w.get("company_name", ""),
                added_price=w.get("added_price", 0),
                target_price=w.get("target_price", 0),
                alert_mos_threshold=w.get("alert_mos_threshold", 0),
                notes=w.get("notes", ""),
                added_at=str(w.get("added_at", "")),
            )
            for w in items
        ]
    except Exception:
        return []


# ── POST /api/v1/watchlist — add ticker ───────────────────────

@router.post("/", response_model=SuccessResponse)
async def add_to_watchlist(req: AddWatchlistRequest, user: dict = Depends(get_current_user)):
    """Add stock to watchlist."""
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    ticker = req.ticker.strip().upper()
    now = datetime.now(timezone.utc).isoformat()

    client = _get_supabase()
    if client:
        try:
            client.table("watchlist").upsert(
                {
                    "user_email": email,
                    "ticker": ticker,
                    "company_name": getattr(req, "company_name", "") or "",
                    "added_price": getattr(req, "added_price", 0) or 0,
                    "added_at": now,
                },
                on_conflict="user_email,ticker",
            ).execute()
            return SuccessResponse(message=f"{ticker} added to watchlist")
        except Exception as e:
            logger.error(f"Supabase watchlist write failed: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to add to watchlist: {type(e).__name__}")

    # Fallback to dashboard SQLite
    try:
        from portfolio import add_to_watchlist as _sqlite_add
        ok = _sqlite_add(
            ticker=ticker, company_name=req.company_name,
            added_price=req.added_price, target_price=req.target_price,
            alert_mos_threshold=req.alert_mos_threshold, notes=req.notes,
        )
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to add to watchlist")
        return SuccessResponse(message=f"{ticker} added to watchlist")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /api/v1/watchlist/add — alias for POST / ────────────

@router.post("/add", response_model=SuccessResponse)
async def add_to_watchlist_alias(req: AddWatchlistRequest, user: dict = Depends(get_current_user)):
    """Alias: add stock to watchlist."""
    return await add_to_watchlist(req, user)


# ── POST /api/v1/watchlist/remove — remove by ticker ─────────

@router.post("/remove", response_model=SuccessResponse)
async def remove_from_watchlist_post(req: AddWatchlistRequest, user: dict = Depends(get_current_user)):
    """Remove stock from watchlist (POST variant)."""
    return await remove_from_watchlist(req.ticker.strip().upper(), user)


# ── DELETE /api/v1/watchlist/{ticker} — remove by ticker ──────

@router.delete("/{ticker}", response_model=SuccessResponse)
async def remove_from_watchlist(ticker: str, user: dict = Depends(get_current_user)):
    """Remove stock from watchlist."""
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    ticker = ticker.strip().upper()

    client = _get_supabase()
    if client:
        try:
            result = (
                client.table("watchlist")
                .delete()
                .eq("user_email", email)
                .eq("ticker", ticker)
                .execute()
            )
            # Supabase returns deleted rows in result.data
            if result.data and len(result.data) > 0:
                return SuccessResponse(message=f"{ticker} removed from watchlist")
            raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Supabase watchlist delete failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to remove from watchlist")

    # Fallback to dashboard SQLite
    try:
        from portfolio import remove_from_watchlist as _sqlite_remove
        ok = _sqlite_remove(ticker)
        if not ok:
            raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
        return SuccessResponse(message=f"{ticker} removed from watchlist")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /api/v1/watchlist/check/{ticker} — check if in watchlist ──

@router.get("/check/{ticker}")
async def check_in_watchlist(ticker: str, user: dict = Depends(get_current_user)):
    """Check if a ticker is in the user's watchlist."""
    email = user.get("email", "")
    if not email:
        return {"in_watchlist": False}

    ticker = ticker.strip().upper()

    client = _get_supabase()
    if client:
        try:
            result = (
                client.table("watchlist")
                .select("ticker")
                .eq("user_email", email)
                .eq("ticker", ticker)
                .execute()
            )
            return {"in_watchlist": bool(result.data and len(result.data) > 0)}
        except Exception:
            pass

    return {"in_watchlist": False}
