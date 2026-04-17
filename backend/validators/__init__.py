# backend/validators/__init__.py
# Dict-based validator module for the ingestion + canary paths.
#
# YieldIQ's response-object validator lives in backend/services/validators.py.
# This module is the complement for data flows that work with plain dicts
# (ingestion records, canary DB snapshots, ad-hoc checks). Both share the
# same BOUNDS source of truth defined in bounds.py.
#
# Conventions (match the live response shape):
#   wacc, terminal_growth, fcf_growth_rate  -> DECIMAL  (0.12 for 12%)
#   roe, roce, margin_of_safety             -> PERCENT  (23.5 for 23.5%)
#   de_ratio, current_ratio, asset_turnover -> RATIO    (0.85)
#   revenue_cagr_3y, revenue_cagr_5y        -> DECIMAL
#   market_cap                              -> INR      (raw rupees)
from __future__ import annotations

from .bounds import BOUNDS, validate_field, validate_record
from .consistency import check_consistency
from .ground_truth import CANARY_STOCKS, run_canary
from .validator_service import validate_stock

__all__ = [
    "BOUNDS",
    "validate_field",
    "validate_record",
    "check_consistency",
    "CANARY_STOCKS",
    "run_canary",
    "validate_stock",
]
