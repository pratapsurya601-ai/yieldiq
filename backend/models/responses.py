# backend/models/responses.py
# Pydantic response models — the API contract for the Next.js frontend.
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, Literal


# ── Core analysis response ────────────────────────────────────

class CompanyInfo(BaseModel):
    ticker: str
    company_name: str
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    currency: str = "INR"
    logo_url: Optional[str] = None
    description: Optional[str] = None
    market_cap: float = 0
    employees: Optional[int] = None


class ValuationOutput(BaseModel):
    fair_value: float
    current_price: float
    margin_of_safety: float
    verdict: Literal["undervalued", "fairly_valued", "overvalued", "avoid", "data_limited", "unavailable"]
    bear_case: float = 0
    base_case: float = 0
    bull_case: float = 0
    wacc: float = 0
    terminal_growth: float = 0
    fcf_growth_rate: float = 0
    confidence_score: int = 50
    wacc_industry_min: float = 0
    wacc_industry_max: float = 0
    fcf_growth_historical_avg: float = 0
    tv_pct_of_ev: float = 0
    dcf_reliable: bool = True
    reliability_score: int = 100
    pv_fcfs: float = 0
    pv_terminal: float = 0
    enterprise_value: float = 0
    equity_value: float = 0
    margin_of_safety_display: float = 0
    mos_is_extreme: bool = False
    mos_extreme_note: str | None = None
    fcf_data_source: str = ""  # "ttm", "annual", or "yfinance"
    valuation_model: str = "dcf"  # "dcf" or "pb_ratio" for financials


class QualityOutput(BaseModel):
    yieldiq_score: int = 0
    grade: str = "C"
    piotroski_score: int = 0
    piotroski_grade: str = ""
    earnings_quality_grade: str = ""
    earnings_quality_score: float = 0
    moat: Literal["Wide", "Narrow", "None", "N/A (Financial)"] = "None"
    moat_score: float = 0
    momentum_score: float = 0
    momentum_grade: str = ""
    fundamental_score: float = 0
    fundamental_grade: str = ""
    roe: Optional[float] = None
    de_ratio: Optional[float] = None


class BulkDealItem(BaseModel):
    date: str = ""
    client: str = ""
    deal_type: str = ""  # BUY / SELL
    qty_lakh: float = 0
    price: float = 0
    category: str = ""  # bulk / block


class RedFlag(BaseModel):
    """Structured risk/strength signal for the deep-dive UI."""
    flag: str                    # short machine key, e.g. "negative_equity"
    severity: str                # "critical" | "warning" | "info"
    title: str                   # display title, e.g. "Negative Equity"
    explanation: str             # 1-sentence plain English
    data_point: str              # actual number / value behind the flag
    why_it_matters: str          # impact on valuation / decision


class InsightCards(BaseModel):
    patience_months: Optional[int] = None
    red_flag_count: int = 0
    red_flags: list[str] = []
    red_flags_structured: list[RedFlag] = []
    earnings_date: Optional[str] = None
    earnings_est_eps: Optional[float] = None
    earnings_days_until: Optional[int] = None
    wall_street_avg_target: Optional[float] = None
    wall_street_target_count: Optional[int] = None
    insider_net_sentiment: Optional[str] = None
    market_expectations_growth: Optional[float] = None
    fcf_yield: Optional[float] = None
    ev_ebitda: Optional[float] = None
    reverse_dcf_implied_growth: Optional[float] = None
    bulk_deals: list[BulkDealItem] = []


class ScenarioCase(BaseModel):
    iv: float = 0
    mos_pct: float = 0
    growth: float = 0
    wacc: float = 0
    term_g: float = 0


class ScenariosOutput(BaseModel):
    bear: ScenarioCase = ScenarioCase()
    base: ScenarioCase = ScenarioCase()
    bull: ScenarioCase = ScenarioCase()


class PriceLevels(BaseModel):
    entry_signal: str = ""
    discount_zone: Optional[float] = None
    model_estimate: Optional[float] = None
    downside_range: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    holding_period: Optional[str] = None


class AnalysisResponse(BaseModel):
    ticker: str
    company: CompanyInfo
    valuation: ValuationOutput
    quality: QualityOutput
    insights: InsightCards
    scenarios: ScenariosOutput = ScenariosOutput()
    price_levels: PriceLevels = PriceLevels()
    ai_summary: Optional[str] = None
    data_confidence: Literal["high", "medium", "low", "unusable"] = "medium"
    data_issues: list[str] = []
    cached: bool = False
    timestamp: str = ""


# ── Screener response ─────────────────────────────────────────

class ScreenerStock(BaseModel):
    ticker: str
    company_name: str = ""
    score: int = 0
    fair_value: float = 0
    current_price: float = 0
    margin_of_safety: float = 0
    verdict: str = ""
    moat: str = ""
    confidence: str = ""
    sector: str = ""


class ScreenerResponse(BaseModel):
    results: list[ScreenerStock] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    filter_applied: dict = {}


# ── Portfolio health response ─────────────────────────────────

class PortfolioHealthResponse(BaseModel):
    score: int = 0
    grade: str = "F"
    summary: str = ""
    issues: list[str] = []
    strengths: list[str] = []
    overvalued_count: int = 0
    undervalued_count: int = 0
    danger_positions: list[str] = []
    concentration_warning: Optional[str] = None


class HoldingResponse(BaseModel):
    ticker: str
    company_name: str = ""
    entry_price: float = 0
    current_price: float = 0
    iv: float = 0
    mos_pct: float = 0
    signal: str = ""
    sector: str = ""
    notes: str = ""
    saved_at: str = ""


class WatchlistItemResponse(BaseModel):
    ticker: str
    company_name: str = ""
    added_price: float = 0
    target_price: float = 0
    alert_mos_threshold: float = 0
    notes: str = ""
    added_at: str = ""


# ── Market data response ──────────────────────────────────────

class MarketIndex(BaseModel):
    name: str
    price: float = 0
    change_pct: float = 0


class MarketPulseResponse(BaseModel):
    indices: list[MarketIndex] = []
    fear_greed_index: Optional[int] = None
    fear_greed_label: Optional[str] = None
    timestamp: str = ""


class SectorOverviewItem(BaseModel):
    name: str
    avg_score: float = 0
    pct_undervalued: float = 0
    trend: str = ""


# ── Alert response ────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int = 0
    ticker: str = ""
    alert_type: str = ""
    target_price: float = 0
    created_at: str = ""
    is_active: bool = True


# ── Auth responses ────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str = ""
    email: str = ""
    tier: Literal["free", "starter", "pro"] = "free"
    analyses_today: int = 0
    analysis_limit: int = 5


class UserResponse(BaseModel):
    user_id: str = ""
    email: str = ""
    tier: Literal["free", "starter", "pro"] = "free"
    analyses_today: int = 0
    analysis_limit: int = 5
    created_at: str = ""


# ── Generic responses ─────────────────────────────────────────

class SuccessResponse(BaseModel):
    ok: bool = True
    message: str = ""


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str = ""
