# backend/routers/earnings_impact.py
# ═══════════════════════════════════════════════════════════════
# Earnings-impact estimator endpoint (Phase 1).
#
# GET /api/v1/analysis/{ticker}/earnings-impact
#   → Returns the latest quarter's revenue, YieldIQ's expected
#     baseline, the surprise %, and a HEURISTIC fair-value impact
#     range for the next nightly recompute.
#
# What this endpoint is NOT:
#   - Not a recompute. The DCF is unchanged after this call.
#   - Not advice. We do not say "buy" / "sell" / "hold" anywhere.
#   - Not a forecast of the next nightly result. The number is a
#     dampened heuristic; the actual formal recompute incorporates
#     many inputs this endpoint deliberately ignores (concall
#     guidance, capex changes, currency, sector cohort shifts).
#
# The is_heuristic=True flag in the payload is contractual. Every
# consumer (frontend panel, any future API user) MUST surface it.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.services.earnings_impact_service import (
    estimate_earnings_impact,
)
from backend.services.quarterly_results_service import (
    get_quarterly_results,
)

logger = logging.getLogger("yieldiq.earnings_impact")

router = APIRouter(prefix="/api/v1", tags=["earnings-impact"])


def _empty_payload(ticker: str, reason: str) -> dict:
    """Return a clean empty payload. The panel renders nothing
    when `impact is None`, so we never 500 the analysis page over
    a missing-quarterly-data condition."""
    return {
        "ticker": ticker,
        "impact": None,
        "reason": reason,
        "is_heuristic": True,
    }


def _resolve_sector_and_growth(ticker: str) -> tuple[Optional[str], Optional[float]]:
    """Pull the canonical sector + DCF-implied growth rate for the
    ticker from the cached analysis. We deliberately call the
    public analysis surface so we benefit from `analysis_cache_service`
    (warm cache hit on any recently-viewed ticker).

    Returns (sector, implied_growth). Either may be None — the
    heuristic handles missing growth with a 10% fallback and
    missing sector with a 1.0 multiplier.
    """
    try:
        # Lazy import: keeps this router importable in test contexts
        # that don't wire the full AnalysisService.
        from backend.services.analysis_service import AnalysisService
        svc = AnalysisService()
        analysis = svc.get_full_analysis(ticker)
    except Exception as exc:  # pragma: no cover — defensive
        logger.info(
            "earnings_impact: full-analysis lookup failed for %s (%s); "
            "falling back to None sector / None growth",
            ticker, str(exc)[:120],
        )
        return None, None

    sector: Optional[str] = None
    growth: Optional[float] = None
    try:
        sector = getattr(analysis.company, "sector", None) or None
    except Exception:
        sector = None
    try:
        # `fcf_growth_rate` is YieldIQ's modelled annual growth rate
        # used in the DCF — the closest single number to "what
        # YieldIQ already expects". Stored as a fraction (0.12 = 12%).
        g = getattr(analysis.valuation, "fcf_growth_rate", None)
        if g is not None and g != 0:
            growth = float(g)
    except Exception:
        growth = None
    return sector, growth


@router.get("/analysis/{ticker}/earnings-impact")
async def get_earnings_impact(ticker: str):
    """
    Heuristic earnings-impact estimator. Returns the latest
    quarter print, YieldIQ's expected baseline, the surprise %,
    and a clamped range of likely FV impact at the next nightly
    recompute.

    Public read-only — no auth. The frontend panel is rendered
    on every analysis page; gating it behind auth would push the
    waterfall and hurt the page's perceived freshness on a beat
    day. The endpoint reads only `company_quarterly_results`
    (already public via /financials).

    The payload always has `is_heuristic: true`. Consumers are
    contractually required to label this surface as a heuristic
    estimate, not a recompute.
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        raise HTTPException(status_code=400, detail="ticker required")

    # Pull the latest 5 quarters: enough for either YoY (need same
    # quarter ~4 rows back) or QoQ (need the previous row) baseline.
    try:
        rows = get_quarterly_results(raw, n_quarters=5, consolidated=True)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "earnings_impact: quarterly fetch failed for %s (%s)",
            raw, str(exc)[:120],
        )
        return _empty_payload(raw, "quarterly_fetch_failed")

    if not rows:
        return _empty_payload(raw, "no_quarterly_data")

    sector, growth = _resolve_sector_and_growth(raw)

    try:
        impact = estimate_earnings_impact(
            rows,
            implied_growth=growth,
            sector=sector,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "earnings_impact: heuristic crashed for %s (%s)",
            raw, str(exc)[:120],
        )
        return _empty_payload(raw, "heuristic_crashed")

    if impact is None:
        return _empty_payload(raw, "insufficient_baseline")

    return {
        "ticker": raw,
        "impact": impact,
        "is_heuristic": True,
        # Explicit disclaimer surfaced at the API boundary too —
        # API consumers must not present this as an FV update.
        "disclaimer": (
            "Heuristic estimate based on a single quarter's revenue "
            "surprise. Not a fair-value recompute. The formal fair "
            "value will refresh on the next nightly run, which "
            "incorporates concall guidance, capex, and sector "
            "context that this heuristic does not."
        ),
    }
