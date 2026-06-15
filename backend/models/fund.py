# backend/models/fund.py
# Pydantic response shapes for the mutual-fund API surface.
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums (string literals — Pydantic v2-style) ───────────────────────


PLAN_VALUES = ("Direct", "Regular")
OPTION_VALUES = ("Growth", "IDCW", "IDCW-Reinvest")
RISKOMETER_LEVELS = (
    "Low",
    "LowToModerate",
    "Moderate",
    "ModeratelyHigh",
    "High",
    "VeryHigh",
)


class Fund(BaseModel):
    scheme_code: str = Field(..., description="AMFI 6-digit scheme code.")
    isin_growth: Optional[str] = None
    isin_div: Optional[str] = None
    scheme_name: str
    amc: str
    plan: Optional[str] = None
    option: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    benchmark_index_code: Optional[str] = None
    inception_date: Optional[date] = None
    riskometer_level: Optional[str] = None
    is_active: bool = True


class FundNavPoint(BaseModel):
    nav_date: date
    nav: float
    aum_cr: Optional[float] = None


class FundCategory(BaseModel):
    category: str
    bucket: str
    default_benchmark: Optional[str] = None
    description: Optional[str] = None


class FundBenchmarkPoint(BaseModel):
    benchmark_index_code: str
    nav_date: date
    tri_value: float


# ── Phase 2 compute-side shapes (nested, used by backend/services/funds/) ──


class FundReturns(BaseModel):
    """Trailing returns + CAGR + monthly-anchored rolling-window stats."""

    nav_as_of: Optional[date] = None
    history_days: Optional[int] = None
    ret_1y: Optional[float] = None
    ret_3y: Optional[float] = None
    ret_5y: Optional[float] = None
    ret_10y: Optional[float] = None
    ret_si: Optional[float] = None
    cagr_3y: Optional[float] = None
    cagr_5y: Optional[float] = None
    cagr_10y: Optional[float] = None
    rolling_3y_mean: Optional[float] = None
    rolling_3y_median: Optional[float] = None
    rolling_3y_min: Optional[float] = None
    rolling_3y_max: Optional[float] = None
    rolling_3y_window_count: Optional[int] = None


class FundRisk(BaseModel):
    """Risk metrics: dispersion, drawdown, benchmark-relative stats."""

    stdev_3y: Optional[float] = None
    sharpe_3y: Optional[float] = None
    sortino_3y: Optional[float] = None
    max_dd_3y: Optional[float] = None
    max_dd_5y: Optional[float] = None
    beta_3y: Optional[float] = None
    alpha_3y: Optional[float] = None
    info_ratio_3y: Optional[float] = None
    tracking_error_3y: Optional[float] = None
    upside_capture_3y: Optional[float] = None
    downside_capture_3y: Optional[float] = None
    benchmark_excess_3y: Optional[float] = None


class FundScore(BaseModel):
    """YieldIQ Fund Score (rule-based composite)."""

    score: Optional[int] = Field(None, ge=0, le=100)
    component_rolling: Optional[int] = Field(None, ge=0, le=100)
    component_sharpe: Optional[int] = Field(None, ge=0, le=100)
    component_drawdown: Optional[int] = Field(None, ge=0, le=100)
    component_ter: Optional[int] = Field(None, ge=0, le=100)
    component_tenure: Optional[int] = Field(None, ge=0, le=100)
    notes: Optional[str] = None


# ── Phase 3 read-only API shapes (flat, used by router) ───────────────


class FundReturnsCache(BaseModel):
    """Flat subset of fund_returns_cache surfaced by /api/v1/funds/{code}."""

    ret_1y: Optional[float] = None
    ret_3y: Optional[float] = None
    ret_5y: Optional[float] = None
    ret_10y: Optional[float] = None
    ret_si: Optional[float] = None
    cagr_3y: Optional[float] = None
    cagr_5y: Optional[float] = None
    ter_direct: Optional[float] = None
    ter_regular: Optional[float] = None
    yieldiq_fund_score: Optional[int] = None


class FundDetailResponse(BaseModel):
    """Composite payload for /api/v1/funds/{scheme_code}."""

    fund: Fund
    nav_history: list[FundNavPoint] = Field(default_factory=list)
    benchmark_history: list[FundBenchmarkPoint] = Field(default_factory=list)
    metrics: Optional[FundReturnsCache] = None


class FundListItem(BaseModel):
    """Compact projection used by the /api/v1/funds index endpoint.

    The trailing three metric fields (`ret_1y`, `yieldiq_fund_score`,
    `ter`) are LEFT-JOINed in from `fund_returns_cache` so the hub cards
    can lead with real numbers instead of em-dashes. They are nullable:
    a fund with no cache row (Phase 2 not yet computed for it, or the
    cache table absent entirely) returns nulls here rather than being
    dropped from the grid. `ter` prefers the Direct-plan TER
    (COALESCE(ter_direct, ter_regular)) since the list defaults to the
    Direct-Growth variant.
    """

    scheme_code: str
    scheme_name: str
    amc: str
    category: Optional[str] = None
    sub_category: Optional[str] = None
    riskometer_level: Optional[str] = None
    plan: Optional[str] = None
    # ── LEFT-JOINed metrics (nullable; see class docstring) ──────────
    ret_1y: Optional[float] = Field(None, description="Trailing 1-year return, percent.")
    yieldiq_fund_score: Optional[int] = Field(
        None, ge=0, le=100, description="YieldIQ Fund Score (rule-based composite)."
    )
    ter: Optional[float] = Field(
        None, description="Expense ratio, percent — prefers Direct (ter_direct)."
    )


class FundListResponse(BaseModel):
    """Wrapper for the index landing card grid."""

    funds: list[FundListItem] = Field(default_factory=list)
    total: int = 0


class FundCategoryCount(BaseModel):
    """A SEBI category label + how many active schemes carry it.

    Powers the hub's filter chips so users can browse by category
    (Large Cap, ELSS, Liquid, ...) instead of the flat alphabetical list.
    """

    category: str
    count: int


class FundCategoriesResponse(BaseModel):
    categories: list[FundCategoryCount] = Field(default_factory=list)
