# backend/validators/validator_service.py
# ═══════════════════════════════════════════════════════════════
# Single entry point for dict-based validation.
#
# Callers (canary scripts, ingestion pipelines, ad-hoc checks) pass
# a flat record dict with fields in YieldIQ's dual convention:
#   wacc etc      -> decimal
#   roe/roce/mos  -> percent
#   de_ratio      -> ratio
#   market_cap    -> raw INR
#
# For response-object validation (AnalysisResponse), use
# backend.services.validators.validate_analysis() instead.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging

from .bounds import BOUNDS, validate_record
from .consistency import check_consistency

logger = logging.getLogger("yieldiq.validators.stock")


def validate_stock(record: dict) -> tuple[bool, list[str]]:
    """
    Validate a flat stock record dict.

    Returns (is_valid, errors). is_valid is True iff no CRITICAL-severity
    field bound is violated. Warning-level issues are returned but do not
    flip is_valid to False — callers decide how to treat them.
    """
    if not isinstance(record, dict):
        return False, ["record is not a dict"]

    errors: list[str] = []
    critical_hit = False

    # Bounds pass — track whether any critical bound failed.
    for field, value in record.items():
        if field not in BOUNDS or value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            errors.append(f"{field} must be numeric, got {type(value).__name__}")
            if BOUNDS[field][2] == "critical":
                critical_hit = True
            continue
        if v != v:
            errors.append(f"{field} is NaN")
            if BOUNDS[field][2] == "critical":
                critical_hit = True
            continue
        lo, hi, sev = BOUNDS[field]
        if v < lo or v > hi:
            errors.append(f"{field}={v:g} outside bounds [{lo}, {hi}]")
            if sev == "critical":
                critical_hit = True

    # Cross-field consistency (all treated as warnings unless they mutate a
    # critical field, in which case they'll already be flagged by bounds).
    errors.extend(check_consistency(record))

    is_valid = not critical_hit

    if errors:
        if not is_valid:
            logger.error(
                "VALIDATION_CRITICAL symbol=%s errors=%s",
                record.get("symbol") or record.get("ticker"), errors,
            )
        else:
            logger.warning(
                "VALIDATION_WARN symbol=%s errors=%s",
                record.get("symbol") or record.get("ticker"), errors,
            )

    return is_valid, errors
