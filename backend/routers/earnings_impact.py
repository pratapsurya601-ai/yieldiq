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
from backend.services.ma_event_detector import (
    detect_ma_event,
    is_quarter_distorted_by_ma,
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


def _fy_quarter_label(period_end_iso: Optional[str]) -> Optional[str]:
    """Render an Indian-FY quarter label (Q1 FY27 etc.) for an ISO date.

    Used in the M&A suppression copy so the user sees the concrete
    quarter when YoY comparisons resume. Returns None when the date
    can't be parsed — caller falls back to a generic phrasing.

    Indian FY: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.
    The FY label is the year-end (March 31) — a date in Q3 FY24 sits
    inside the FY ending March 2024.
    """
    if not period_end_iso:
        return None
    try:
        from datetime import date as _date, datetime as _datetime
        if isinstance(period_end_iso, str):
            d = _datetime.fromisoformat(period_end_iso[:10]).date()
        elif isinstance(period_end_iso, _datetime):
            d = period_end_iso.date()
        elif isinstance(period_end_iso, _date):
            d = period_end_iso
        else:
            return None
    except Exception:
        return None
    m = d.month
    if 4 <= m <= 6:
        q, fy_year = 1, d.year + 1
    elif 7 <= m <= 9:
        q, fy_year = 2, d.year + 1
    elif 10 <= m <= 12:
        q, fy_year = 3, d.year + 1
    else:
        q, fy_year = 4, d.year
    return f"Q{q} FY{fy_year % 100:02d}"


def _resume_quarter_label(event_date_iso: str, window_quarters: int) -> Optional[str]:
    """Compute the first quarter where YoY comparisons resume after
    the M&A event — i.e. the quarter whose period_end is at least
    `window_quarters * 3` months past `event_date_iso`.

    Used to fill the "YoY comparison resumes in <Q-FY>" copy in the
    suppression body. Returns None on parse failure (caller falls
    back to the bare-window phrasing).
    """
    if not event_date_iso:
        return None
    try:
        from datetime import datetime as _datetime
        ev = _datetime.fromisoformat(event_date_iso[:10]).date()
    except Exception:
        return None
    months = window_quarters * 3
    year = ev.year + (months // 12)
    month = ev.month + (months % 12)
    while month > 12:
        month -= 12
        year += 1
    # Use the END of that month as a representative period_end so the
    # Indian-FY quarter label resolver picks the same quarter the
    # event_date + window lands in.
    # Day 28 is safe for every month including February.
    try:
        from datetime import date as _date
        target = _date(year, month, 28)
    except Exception:
        return None
    return _fy_quarter_label(target.isoformat())


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

    # ── ROOT CAUSE #8 (2026-06-11): M&A distortion check ─────────────
    # Detect a material structural event (merger/demerger/etc.) inside
    # the 8-quarter normalisation window. When the YoY baseline straddles
    # the event, the surprise %/range is structurally broken regardless
    # of operational performance — HDFCBANK's HDFC-Ltd merger inflates
    # the YoY baseline by ~70% so a "miss" reading is meaningless. We
    # SUPPRESS the surprise number in that case and stamp a flag the
    # frontend reads to swap in the M&A-distortion copy. The latest
    # quarter and baseline rows still flow through so the panel can
    # render context, but the misleading number is gone.
    ma_event_payload: Optional[dict] = None
    ma_distortion_flag = False
    suppression_copy: Optional[str] = None
    try:
        ma_event_payload = detect_ma_event(raw)
    except Exception as exc:  # pragma: no cover — defensive
        logger.info(
            "earnings_impact: ma_event detection failed for %s (%s)",
            raw, str(exc)[:120],
        )
        ma_event_payload = None

    latest_pe_iso: Optional[str] = None
    if rows:
        _pe = rows[0].get("period_end")
        if hasattr(_pe, "isoformat"):
            latest_pe_iso = _pe.isoformat()
        elif isinstance(_pe, str):
            latest_pe_iso = _pe

    if ma_event_payload is not None:
        try:
            from datetime import date as _date, datetime as _datetime
            ev_iso = ma_event_payload.get("event_date")
            ev_date = (
                _datetime.fromisoformat(ev_iso[:10]).date()
                if isinstance(ev_iso, str) else None
            )
            latest_pe = None
            if latest_pe_iso:
                latest_pe = _datetime.fromisoformat(latest_pe_iso[:10]).date()
            ma_distortion_flag = is_quarter_distorted_by_ma(
                quarter_end=latest_pe,
                event_date=ev_date,
                window_quarters=ma_event_payload.get(
                    "normalization_window_quarters", 8,
                ),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.info(
                "earnings_impact: ma distortion check failed for %s (%s)",
                raw, str(exc)[:120],
            )
            ma_distortion_flag = False

        if ma_distortion_flag:
            resume_label = _resume_quarter_label(
                ma_event_payload.get("event_date") or "",
                int(ma_event_payload.get(
                    "normalization_window_quarters", 8,
                )),
            )
            window_q = ma_event_payload.get(
                "normalization_window_quarters", 8,
            )
            ev_iso = ma_event_payload.get("event_date") or ""
            base_phrase = (
                f"Baseline distorted by structural M&A event on {ev_iso}. "
                f"YoY comparison resumes "
                + (
                    f"{resume_label} "
                    if resume_label else ""
                )
                + f"({int(window_q)} quarters post-event)."
            )
            suppression_copy = base_phrase

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
        # Even when the heuristic can't compute, surface the M&A flag so
        # the panel can render the suppression copy instead of going
        # silent on a freshly-reported quarter.
        if ma_distortion_flag and ma_event_payload is not None:
            return {
                "ticker": raw,
                "impact": None,
                "reason": "ma_distortion_suppressed",
                "ma_distortion_flag": True,
                "ma_event": ma_event_payload,
                "suppression_copy": suppression_copy,
                "is_heuristic": True,
            }
        return _empty_payload(raw, "insufficient_baseline")

    # When M&A distortion is active, suppress the headline surprise +
    # FV-delta numbers (they're computed off the YoY baseline that
    # straddles the event) while preserving the rest of the payload so
    # the panel can still render the latest quarter print and the
    # explainer body.
    if ma_distortion_flag:
        # Pydantic isn't in scope here — `impact` is a plain dict from
        # `estimate_earnings_impact`. Mutate a shallow copy so the
        # heuristic result remains pure.
        impact = dict(impact)
        impact["surprise_pct"] = None
        impact["fv_delta_estimate"] = None
        impact["fv_delta_range"] = None
        impact["ma_distortion_flag"] = True

    return {
        "ticker": raw,
        "impact": impact,
        "is_heuristic": True,
        "ma_distortion_flag": ma_distortion_flag,
        "ma_event": ma_event_payload,
        "suppression_copy": suppression_copy,
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
