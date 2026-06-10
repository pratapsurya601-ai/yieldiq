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
    headline_fv: Optional[float] = None,
) -> Optional[float]:
    """Return the user-facing fair_value to surface in summary projections.

    Policy (see AUDIT5_P0B_FAIR_VALUE_FLOOR in routers/public.py for the
    long-form rationale; ROOT CAUSE #1 2026-06-10 added the
    ``headline_fv`` parameter so og-data / stock-summary read the same
    canonical headline number the analysis page hero pill shows):

      * If the response carries a positive ``headline_fair_value``
        (composite IV when present, else DCF — populated by
        ``_inject_headline_fair_value_*`` on every AnalysisResponse),
        prefer THAT — it is the single source of truth every
        user-visible FV pill agrees on.
      * Otherwise, if the engine produced a positive value, use it.
      * Otherwise, if the base scenario midpoint is positive, surface
        base_case so the verdict-pill gating shows the
        analyst-meaningful number instead of "₹0".
      * If none of those is available, return None so the frontend
        hides the pill (AnalysisHero branches on fairValue > 0).
      * If the engine genuinely computed 0 (and base is also 0/missing),
        preserve the 0 — the verdict gate is already data_limited and
        that's the truthful signal. Never synthesise a positive number.

    Args:
        engine_fv: Raw fair_value from the analysis engine (may be None,
            0, negative, or positive float).
        base_case: Base-scenario midpoint from the scenario layer (may
            be None or a positive float).
        headline_fv: Canonical headline_fair_value field from the
            response (set by routers/analysis.py
            ``_inject_headline_fair_value_*``). When positive, preferred
            over engine_fv so og-data / stock-summary surface the same
            number as the hero pill. Optional for back-compat with
            callers predating ROOT CAUSE #1.

    Returns:
        Rounded float to 2 dp, or None when all inputs are missing.
    """
    if headline_fv is not None and float(headline_fv) > 0:
        return round(float(headline_fv), 2)
    if engine_fv is not None and float(engine_fv) > 0:
        return round(float(engine_fv), 2)
    if base_case is not None and float(base_case) > 0:
        return round(float(base_case), 2)
    if engine_fv is None and base_case is None:
        return None
    # Engine genuinely produced 0 (or 0 with no base scenario).
    return round(float(engine_fv or 0), 2)


def resolve_display_mos(
    raw_mos: Optional[float],
    mos_is_extreme: bool,
) -> Optional[float]:
    """Return the user-facing margin-of-safety to surface in summaries.

    Policy (extreme-MoS display suppression, 2026-05-24):

      * When the analysis pipeline flagged the MoS as "extreme"
        (`mos_is_extreme=True` — fires above the Phase B.2 threshold,
        e.g. KALYANI.NS at MoS=829% which triggered an `under_review`
        verdict), the raw number is meaningless on a public surface.
        Returning the literal 829 would render as "+829% upside" even
        though the verdict chip and note already tell the user the
        valuation is being held back. Suppress the number by returning
        None — the frontend renders "—" and the under_review chip
        carries the actual message.
      * When the flag is False, pass the raw value through unchanged
        (rounded to 1 dp for display parity). None propagates as None.

    The internal `valuation.margin_of_safety` field on AnalysisResponse
    is intentionally left alone so admin / debugging views and the
    canary-diff harness can still see the unsuppressed number. This
    helper is for public-facing serializers only.

    Args:
        raw_mos: The canonical margin_of_safety from the valuation
            block (may be None).
        mos_is_extreme: The `valuation.mos_is_extreme` flag set by the
            analysis pipeline when the MoS crosses the extreme
            threshold.

    Returns:
        None when raw_mos is None OR when the extreme flag is set,
        otherwise the rounded MoS value (1 dp).
    """
    if mos_is_extreme:
        return None
    if raw_mos is None:
        return None
    return round(float(raw_mos), 1)
