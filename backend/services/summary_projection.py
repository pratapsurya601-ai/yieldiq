# backend/services/summary_projection.py
# ═══════════════════════════════════════════════════════════════════════
# Shared projection helpers for endpoints that surface a flat
# AnalysisResponse summary (public stock-summary, og-data, etc.).
#
# Extracted Day-100 (2026-05-22, Audit#5 P0b follow-up) so the
# fair_value 0-floor fallthrough lives in exactly ONE place. Prior
# to this, `_extract_analysis_summary` in routers/public.py had the
# floor but the /og-data path in routers/analysis.py forwarded engine
# fair_value verbatim — same defect shape (ULTRACEMCO.NS rendered
# "₹0 fair value" on OG cards while the public summary was correct).
# ═══════════════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Optional


def resolve_fair_value(
    engine_fv: Optional[float],
    base_case: Optional[float],
) -> Optional[float]:
    """Return the user-facing fair_value to surface in summary projections.

    Policy (see AUDIT5_P0B_FAIR_VALUE_FLOOR in routers/public.py for the
    long-form rationale):

      * If the engine produced a positive value, use it verbatim.
      * Otherwise, if the base scenario midpoint is positive, surface
        base_case so the verdict-pill gating shows the analyst-meaningful
        number instead of "₹0".
      * If neither is available (both None), return None so the
        frontend hides the pill (AnalysisHero branches on fairValue > 0).
      * If the engine genuinely computed 0 (and base is also 0/missing),
        preserve the 0 — the verdict gate is already data_limited and
        that's the truthful signal. Never synthesise a positive number.

    Args:
        engine_fv: Raw fair_value from the analysis engine (may be None,
            0, negative, or positive float).
        base_case: Base-scenario midpoint from the scenario layer (may
            be None or a positive float).

    Returns:
        Rounded float to 2 dp, or None when both inputs are missing.
    """
    if engine_fv is not None and float(engine_fv) > 0:
        return round(float(engine_fv), 2)
    if base_case is not None and float(base_case) > 0:
        return round(float(base_case), 2)
    if engine_fv is None and base_case is None:
        return None
    # Engine genuinely produced 0 (or 0 with no base scenario).
    return round(float(engine_fv or 0), 2)
