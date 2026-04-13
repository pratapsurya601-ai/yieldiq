# backend/routers/market.py
from __future__ import annotations
from fastapi import APIRouter, Depends
from backend.models.responses import MarketPulseResponse, SectorOverviewItem
from backend.services.data_service import DataService
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/market", tags=["market"])
data_service = DataService()


@router.get("/pulse", response_model=MarketPulseResponse)
async def get_market_pulse(user: dict = Depends(get_current_user)):
    """Market indices + fear/greed. Cached 5 minutes."""
    return data_service.get_market_pulse()


@router.get("/sectors", response_model=list[SectorOverviewItem])
async def get_sector_overview(user: dict = Depends(get_current_user)):
    """Sector valuation summary."""
    return data_service.get_sector_overview()
