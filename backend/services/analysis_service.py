# backend/services/analysis_service.py
# ══════════════════════════════════════════════════════════════════
# Backward-compat shim — the real code lives in backend/services/analysis/.
# This file preserves the public API so downstream importers don't break.
# Delete this shim after all importers migrate to the new paths.
# ══════════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.services.analysis.service import (
    AnalysisService,
    TickerNotFoundError,
)
from backend.services.analysis.db import (
    _fetch_roce_inputs,
    _fetch_current_assets,
    _fetch_ebit_and_interest,
    _fetch_bank_metrics_inputs,
    _get_pipeline_session,
    _db_dead_until,
    _db_fail_count,
    _convert_row_to_inr,
    _query_ttm_financials,
    _query_latest_annual_financials,
    _query_shareholding,
    _query_promoter_pledge,
    _query_earnings_date,
    _query_bulk_deals,
)
from backend.services.analysis.utils import (
    _canonicalize_ticker,
    _normalize_pct,
    _fx_multiplier,
    _debt_ebitda_label,
    _known_indian_bare,
    _KNOWN_INDIAN_BARE,
    _get_financial_sub_type,
    _get_adjusted_fcf,
    _clamp_ev_ebitda,
    _enforce_scenario_order,
    _compute_roe_fallback,
    _yf_compute_roe_from_statements,
    _resolve_sector,
    _fmt_cr,
    _build_structured_flags,
    _add_flags,
    _YF_ROE_CACHE,
)
from backend.services.analysis.constants import (
    FINANCIAL_COMPANIES,
    _NBFC_TICKERS,
    _INSURANCE_TICKERS,
    INVENTORY_HEAVY_TICKERS,
    TICKER_SECTOR_OVERRIDES,
    SECTOR_OVERRIDES,
    COMPANY_NAME_OVERRIDES,
    _PB_MEDIANS,
    USD_INR_RATE,
)
from backend.services.analysis.narrative import NarrativeMixin
