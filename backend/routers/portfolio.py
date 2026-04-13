# backend/routers/portfolio.py
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

from backend.models.requests import AddHoldingRequest
from backend.models.responses import (
    HoldingResponse, PortfolioHealthResponse, SuccessResponse,
)
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


@router.get("/holdings", response_model=list[HoldingResponse])
async def get_holdings(user: dict = Depends(get_current_user)):
    """Get all portfolio holdings."""
    from portfolio import get_portfolio
    holdings = get_portfolio()
    return [
        HoldingResponse(
            ticker=h.get("ticker", ""),
            company_name=h.get("company_name", ""),
            entry_price=h.get("entry_price", 0),
            iv=h.get("iv", 0),
            mos_pct=h.get("mos_pct", 0),
            signal=h.get("signal", ""),
            sector=h.get("sector", ""),
            notes=h.get("notes", ""),
            saved_at=str(h.get("saved_at", "")),
        )
        for h in holdings
    ]


@router.post("/holdings", response_model=SuccessResponse)
async def add_holding(req: AddHoldingRequest, user: dict = Depends(get_current_user)):
    """Add stock to portfolio."""
    from portfolio import save_to_portfolio
    ok = save_to_portfolio(
        ticker=req.ticker, entry_price=req.entry_price,
        iv=req.iv, mos_pct=req.mos_pct, signal=req.signal,
        wacc=req.wacc, sector=req.sector, notes=req.notes,
        sym="₹", to_code="INR",
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to add holding")
    return SuccessResponse(message=f"{req.ticker} added to portfolio")


@router.delete("/holdings/{ticker}", response_model=SuccessResponse)
async def remove_holding(ticker: str, user: dict = Depends(get_current_user)):
    """Remove stock from portfolio."""
    from portfolio import remove_from_portfolio
    ok = remove_from_portfolio(ticker.upper())
    if not ok:
        raise HTTPException(status_code=404, detail=f"{ticker} not found in portfolio")
    return SuccessResponse(message=f"{ticker} removed from portfolio")


@router.get("/health", response_model=PortfolioHealthResponse)
async def get_portfolio_health(user: dict = Depends(get_current_user)):
    """Portfolio health score (0-100)."""
    from portfolio import get_portfolio
    from dashboard.utils.portfolio_health import calculate_portfolio_health
    holdings = get_portfolio()
    health = calculate_portfolio_health(holdings)
    return PortfolioHealthResponse(**health)
