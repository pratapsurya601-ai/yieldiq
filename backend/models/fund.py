# backend/models/fund.py
# Pydantic response shapes for the mutual-fund API surface.
#
# Phase 1 scope: minimal models for what the Phase 3 fund analysis page
# will need to render. No router wired yet (that lands in Phase 3) —
# these are placed now so:
#   1. Migration-author and frontend-author can reference a single
#      source-of-truth shape during their parallel build.
#   2. The category enum is anchored alongside the seed table
#      (073_fund_categories_seed.sql) — drift between the two becomes
#      a code-review-visible diff.
#
# Compute fields (returns, alpha, beta, Sharpe, etc.) are intentionally
# NOT modeled here — they belong to Phase 2's fund_returns_cache shape.
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums (string literals — Pydantic v2-style) ───────────────────────


# Mirrors funds.plan CHECK constraint.
PLAN_VALUES = ("Direct", "Regular")
# Mirrors funds.option CHECK constraint.
OPTION_VALUES = ("Growth", "IDCW", "IDCW-Reinvest")
# Mirrors funds.riskometer_level CHECK constraint. SEBI-mandated six
# levels — these MUST be read from the AMC disclosure verbatim,
# never recomputed in our pipeline.
RISKOMETER_LEVELS = (
    "Low",
    "LowToModerate",
    "Moderate",
    "ModeratelyHigh",
    "High",
    "VeryHigh",
)


class Fund(BaseModel):
    """Master record for a single mutual fund scheme.

    Mirrors the columns of data_pipeline.migrations.067_funds.sql with
    snake_case → camelCase conversion deliberately deferred to the
    response serializer (router-level), keeping this shape close to
    the DB row for low-friction validators in the ingest layer.
    """

    scheme_code: str = Field(..., description="AMFI 6-digit scheme code.")
    isin_growth: Optional[str] = Field(None, description="ISIN for the Growth option.")
    isin_div: Optional[str] = Field(None, description="ISIN for the IDCW option.")
    scheme_name: str
    amc: str = Field(..., description="Asset Management Company name as published by AMFI.")
    plan: Optional[str] = Field(None, description="Direct or Regular.")
    option: Optional[str] = Field(None, description="Growth, IDCW, or IDCW-Reinvest.")
    category: Optional[str] = Field(
        None,
        description="SEBI 36-category label (matches fund_categories.category).",
    )
    sub_category: Optional[str] = None
    benchmark_index_code: Optional[str] = Field(
        None,
        description="Canonical TRI benchmark code (e.g. NIFTY_500_TRI). "
                    "Maps to fund_benchmark_history.benchmark_index_code.",
    )
    inception_date: Optional[date] = None
    riskometer_level: Optional[str] = Field(
        None,
        description="Official SEBI Riskometer level. Read verbatim from "
                    "AMC disclosure — never recomputed.",
    )
    is_active: bool = True


class FundNavPoint(BaseModel):
    """One row of NAV history for a scheme.

    Wire shape for chart endpoints (returns a list of these). Date is
    serialized as ISO-8601 by the default Pydantic v2 JSON encoder.
    """

    nav_date: date
    nav: float = Field(..., description="Net Asset Value in INR per unit.")
    aum_cr: Optional[float] = Field(
        None,
        description="Assets Under Management in INR crore. Sparse — only "
                    "month-end disclosures carry it.",
    )


class FundCategory(BaseModel):
    """Seed row from fund_categories — used by the screener category filter."""

    category: str
    bucket: str = Field(..., description="Equity | Debt | Hybrid | Solution | Other")
    default_benchmark: Optional[str] = None
    description: Optional[str] = None


class FundBenchmarkPoint(BaseModel):
    """One row of TRI history for a benchmark index."""

    benchmark_index_code: str
    nav_date: date
    tri_value: float


# ── Phase 2 — compute response shapes ────────────────────────────────
#
# These mirror the columns of fund_returns_cache (075_fund_returns_cache.sql).
# Phase 2 lands the compute service + cache table; Phase 3 will wire the
# router that hydrates these shapes from the cache row. Keeping the
# pydantic models alongside the table now lets the Phase 3 frontend
# author reference a single source-of-truth shape.


class FundReturns(BaseModel):
    """Trailing returns + CAGR + monthly-anchored rolling-window stats.

    Values are decimal fractions (0.12 = 12 percent), per the equity-side
    convention. Any field may be null when the underlying NAV history is
    too short for that window.
    """

    nav_as_of: Optional[date] = None
    history_days: Optional[int] = None
    ret_1y: Optional[float] = None
    ret_3y: Optional[float] = None
    ret_5y: Optional[float] = None
    ret_10y: Optional[float] = None
    ret_si: Optional[float] = Field(
        None,
        description="Since-inception. Annualised (CAGR) when inception is "
                    "older than 1y, simple cumulative return otherwise.",
    )
    cagr_3y: Optional[float] = None
    cagr_5y: Optional[float] = None
    cagr_10y: Optional[float] = None
    rolling_3y_mean: Optional[float] = None
    rolling_3y_median: Optional[float] = None
    rolling_3y_min: Optional[float] = None
    rolling_3y_max: Optional[float] = None
    rolling_3y_window_count: Optional[int] = None


class FundRisk(BaseModel):
    """Risk metrics: dispersion, drawdown, and benchmark-relative stats.

    Benchmark-relative fields (beta, alpha, info ratio, capture, excess)
    are null when the scheme has no benchmark mapping or the overlap
    window is too thin.
    """

    stdev_3y: Optional[float] = Field(
        None,
        description="Annualised standard deviation of daily log returns "
                    "over the trailing 3y window.",
    )
    sharpe_3y: Optional[float] = None
    sortino_3y: Optional[float] = None
    max_dd_3y: Optional[float] = Field(
        None,
        description="Maximum drawdown over the trailing 3y NAV path. "
                    "Negative fraction (-0.18 = -18 percent peak-to-trough).",
    )
    max_dd_5y: Optional[float] = None
    beta_3y: Optional[float] = None
    alpha_3y: Optional[float] = Field(
        None,
        description="Jensen alpha (annualised regression intercept) on "
                    "excess returns vs the scheme's TRI benchmark.",
    )
    info_ratio_3y: Optional[float] = None
    tracking_error_3y: Optional[float] = None
    upside_capture_3y: Optional[float] = None
    downside_capture_3y: Optional[float] = None
    benchmark_excess_3y: Optional[float] = Field(
        None,
        description="Annualised return minus annualised benchmark return "
                    "over the trailing 3y window.",
    )


class FundScore(BaseModel):
    """YieldIQ Fund Score (rule-based composite) + component breakdown.

    The score is 0..100. Each component is 0..100 representing the
    scheme's percentile rank within its SEBI category for that metric
    (rolling 3y mean return, Sharpe, max drawdown, TER). The tenure
    component is a floor cap, not a ranked percentile — see
    compute_score.TENURE_CAPS for the rule.
    """

    score: Optional[int] = Field(None, ge=0, le=100)
    component_rolling: Optional[int] = Field(None, ge=0, le=100)
    component_sharpe: Optional[int] = Field(None, ge=0, le=100)
    component_drawdown: Optional[int] = Field(None, ge=0, le=100)
    component_ter: Optional[int] = Field(None, ge=0, le=100)
    component_tenure: Optional[int] = Field(None, ge=0, le=100)
    notes: Optional[str] = Field(
        None,
        description="Diagnostic explainer surfaced on the analysis page "
                    "when one or more components are null.",
    )


class FundReturnsCache(BaseModel):
    """Combined cache row — everything Phase 3 needs to render the panels.

    Returned by the (future) /api/funds/{scheme_code}/metrics endpoint.
    """

    scheme_code: str
    cache_version: Optional[str] = None
    computed_at: Optional[date] = None
    returns: FundReturns
    risk: FundRisk
    score: FundScore
    category_percentile_3y: Optional[float] = Field(
        None,
        description="Percentile of cagr_3y within funds.category. "
                    "1.0 = top, 0.0 = bottom.",
    )
