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
    """Risk metrics: dispersion, drawdown, benchmark-relative stats.

    Field names mirror the ``fund_returns_cache`` columns (075 migration)
    one-for-one: ``max_dd_*`` (not ``max_drawdown_*``) and
    ``upside_capture_3y`` / ``downside_capture_3y`` (not ``up_capture`` /
    ``down_capture``). The API-side :class:`FundRiskBlock` re-keys these to
    the frontend contract names. The 075 table only carries 3y dispersion
    and benchmark-relative metrics — there is no ``stdev_5y`` / ``sharpe_5y``
    / ``sortino_5y`` column, so those contract fields surface as null.
    """

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
    category_percentile_3y: Optional[float] = None
    nav_as_of: Optional[date] = None


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


class FundRiskBlock(BaseModel):
    """Risk-exposure block surfaced by /api/v1/funds/{code}.

    Re-keys the ``fund_returns_cache`` risk columns to the frontend
    contract names. ``stdev_5y`` / ``sharpe_5y`` / ``sortino_5y`` have no
    backing column in the 075 schema and are always null (kept in the
    contract so the frontend can wire them once a future migration adds
    the 5y dispersion window).

    Units (per the equity-side decimal-fraction convention):
      * stdev_3y/5y, max_drawdown_3y/5y, alpha_3y, benchmark_excess_3y →
        DECIMAL FRACTIONS (0.12 = 12%).
      * category_percentile_3y → 0..100 (re-scaled from the table's 0..1).
      * sharpe/sortino/beta/info_ratio/tracking_error/up_capture/
        down_capture → dimensionless ratios.
    """

    lookback: str = "3y"
    as_of: Optional[date] = None
    stdev_3y: Optional[float] = None
    stdev_5y: Optional[float] = None  # no backing column — always null
    sharpe_3y: Optional[float] = None
    sharpe_5y: Optional[float] = None  # no backing column — always null
    sortino_3y: Optional[float] = None
    sortino_5y: Optional[float] = None  # no backing column — always null
    max_drawdown_3y: Optional[float] = None
    max_drawdown_5y: Optional[float] = None
    beta_3y: Optional[float] = None
    alpha_3y: Optional[float] = None
    info_ratio_3y: Optional[float] = None
    tracking_error_3y: Optional[float] = None
    up_capture_3y: Optional[float] = None
    down_capture_3y: Optional[float] = None
    benchmark_excess_3y: Optional[float] = None
    category_percentile_3y: Optional[float] = Field(
        None, description="0..100 percentile of cagr_3y within sub_category."
    )


class FundCategoryStats(BaseModel):
    """Category-level aggregate stats for the fund's sub_category.

    Strictly comparative context — median / average peer metrics, never a
    recommendation. CAGR fields are DECIMAL FRACTIONS. ``avg_ter`` is
    intentionally null until factsheet TER ingest lands (it is not in the
    compute objects; the recompute pass leaves it NULL rather than fake it).
    """

    sub_category: Optional[str] = None
    n_funds: Optional[int] = None
    median_cagr_1y: Optional[float] = None
    median_cagr_3y: Optional[float] = None
    median_cagr_5y: Optional[float] = None
    avg_cagr_1y: Optional[float] = None
    avg_cagr_3y: Optional[float] = None
    avg_cagr_5y: Optional[float] = None
    avg_ter: Optional[float] = None
    avg_sharpe_3y: Optional[float] = None
    avg_stdev_3y: Optional[float] = None
    avg_max_drawdown_3y: Optional[float] = None


class FundPeer(BaseModel):
    """A single same-sub_category peer row, or the category-average
    pseudo-row (``is_category_average=True``, ``scheme_code=None``).

    Ordering by ``fund_score`` is a STABLE SORT for display only — not a
    ranking verdict. Comparative context, no recommendation language.
    """

    scheme_code: Optional[str] = None
    scheme_name: str
    amc: Optional[str] = None
    fund_score: Optional[int] = None
    ret_1y: Optional[float] = None
    ret_3y: Optional[float] = None
    ter_direct: Optional[float] = None
    riskometer_level: Optional[str] = None
    is_category_average: bool = False


class FundPeersResponse(BaseModel):
    """Payload for /api/v1/funds/{scheme_code}/peers."""

    sub_category: Optional[str] = None
    peers: list[FundPeer] = Field(default_factory=list)


class FundPortfolioHolding(BaseModel):
    """A single holding row (surfaced once the holdings table is populated)."""

    isin: Optional[str] = None
    instrument: Optional[str] = None
    weight_pct: Optional[float] = None  # PERCENT (e.g. 4.2 = 4.2%)
    asset_class: Optional[str] = None
    sector: Optional[str] = None
    mcap_bucket: Optional[str] = None
    change_3m_pct: Optional[float] = None


class FundAllocationSlice(BaseModel):
    """One rolled-up allocation slice (asset / sector / mcap)."""

    label: str
    weight_pct: Optional[float] = None  # PERCENT


class FundPortfolio(BaseModel):
    """Holdings block for /api/v1/funds/{code}.

    Forward-compatible scaffold: when no holdings rows exist it returns the
    explicit empty state (``updating=True``, empty lists). Once the ingester
    populates ``fund_holdings`` it surfaces top holdings + asset / sector /
    mcap roll-ups with ``updating=False``.
    """

    updating: bool = True
    as_of_month: Optional[date] = None
    holdings_count: int = 0
    holdings: list[FundPortfolioHolding] = Field(default_factory=list)
    asset_allocation: list[FundAllocationSlice] = Field(default_factory=list)
    sector_allocation: list[FundAllocationSlice] = Field(default_factory=list)
    mcap_allocation: list[FundAllocationSlice] = Field(default_factory=list)


class FundDetailResponse(BaseModel):
    """Composite payload for /api/v1/funds/{scheme_code}."""

    fund: Fund
    nav_history: list[FundNavPoint] = Field(default_factory=list)
    benchmark_history: list[FundBenchmarkPoint] = Field(default_factory=list)
    metrics: Optional[FundReturnsCache] = None
    # Additive blocks (Phase 3 expansion). All nullable / empty-safe so
    # the existing flat `metrics` contract stays backwards-compatible.
    risk: Optional[FundRiskBlock] = None
    category_stats: Optional[FundCategoryStats] = None
    portfolio: Optional[FundPortfolio] = None


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
