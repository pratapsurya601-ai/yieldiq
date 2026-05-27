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
