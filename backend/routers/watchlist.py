# backend/routers/watchlist.py
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

from backend.models.requests import AddWatchlistRequest
from backend.models.responses import WatchlistItemResponse, SuccessResponse
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


@router.get("/", response_model=list[WatchlistItemResponse])
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get all watchlist items."""
    from portfolio import get_watchlist
    items = get_watchlist()
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


@router.post("/", response_model=SuccessResponse)
async def add_to_watchlist(req: AddWatchlistRequest, user: dict = Depends(get_current_user)):
    """Add stock to watchlist."""
    from portfolio import add_to_watchlist
    ok = add_to_watchlist(
        ticker=req.ticker, company_name=req.company_name,
        added_price=req.added_price, target_price=req.target_price,
        alert_mos_threshold=req.alert_mos_threshold, notes=req.notes,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to add to watchlist")
    return SuccessResponse(message=f"{req.ticker} added to watchlist")


@router.delete("/{ticker}", response_model=SuccessResponse)
async def remove_from_watchlist(ticker: str, user: dict = Depends(get_current_user)):
    """Remove stock from watchlist."""
    from portfolio import remove_from_watchlist
    ok = remove_from_watchlist(ticker.upper())
    if not ok:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
    return SuccessResponse(message=f"{ticker} removed from watchlist")
