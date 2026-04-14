# backend/models/requests.py
# Pydantic request models for API endpoints.
from __future__ import annotations
from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    referral_code: Optional[str] = None


class AddHoldingRequest(BaseModel):
    ticker: str
    entry_price: float
    iv: float = 0
    mos_pct: float = 0
    signal: str = ""
    wacc: float = 0
    sector: str = ""
    notes: str = ""


class AddWatchlistRequest(BaseModel):
    ticker: str
    company_name: str = ""
    added_price: float = 0
    target_price: float = 0
    alert_mos_threshold: float = 20.0
    notes: str = ""


class CreateAlertRequest(BaseModel):
    ticker: str
    alert_type: str = "price_below"
    target_price: float = 0


class ScreenerFilterRequest(BaseModel):
    min_score: int = 0
    min_mos: float = -100
    max_mos: float = 100
    moat: Optional[str] = None
    sector: Optional[str] = None
    market_cap_min: Optional[float] = None
    market_cap_max: Optional[float] = None
    fcf_positive: Optional[bool] = None
    page: int = 1
    page_size: int = 20
