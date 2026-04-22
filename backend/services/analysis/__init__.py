# backend/services/analysis/__init__.py
# ═══════════════════════════════════════════════════════════════
# Analysis subpackage — split out of the historical monolith
# backend/services/analysis_service.py. See refactor/analysis-
# package-split commit for rationale.
#
# Public API is re-exported both here and in the shim at
# backend/services/analysis_service.py so downstream importers
# can migrate gradually.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys
import os
from pathlib import Path

# Ensure project root is on path so existing imports (data., screener.,
# models., config., data_pipeline.) continue to resolve regardless of
# how this subpackage is imported. Mirrors the bootstrap previously
# performed at the top of analysis_service.py.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

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
from backend.services.analysis.utils import (
    _KNOWN_INDIAN_BARE,
    _known_indian_bare,
    _canonicalize_ticker,
    _normalize_pct,
    _fx_multiplier,
    _debt_ebitda_label,
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
from backend.services.analysis.db import (
    _get_pipeline_session,
    _db_dead_until,
    _db_fail_count,
    _fetch_roce_inputs,
    _fetch_current_assets,
    _fetch_ebit_and_interest,
    _fetch_bank_metrics_inputs,
    _convert_row_to_inr,
    _query_ttm_financials,
    _query_latest_annual_financials,
    _query_shareholding,
    _query_promoter_pledge,
    _query_earnings_date,
    _query_bulk_deals,
)
from backend.services.analysis.narrative import NarrativeMixin
from backend.services.analysis.service import (
    AnalysisService,
    TickerNotFoundError,
)
