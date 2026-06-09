# backend/services/multiples_fv.py
# ═══════════════════════════════════════════════════════════════
# Peer-relative "multiples-based" fair value.
#
# Sprint A2 (2026-06-09). Closes AlphaSpread's #1 positioning win:
# they show DCF + Multiples-Based Value side-by-side with a "both
# methods agree" callout. We showed DCF only.
#
# This is NOT a separate valuation model — it's a cheap peer-relative
# re-pricing of the current quote: "what would this stock be worth if
# it traded at the sector-median multiple?"
#
#     multiples_fv = current_price * (sector_median_pe / pe)
#         OR
#     multiples_fv = current_price * (sector_median_pb / pb)   as fallback
#
# Returns None when the cohort isn't available, when the ticker's own
# multiple is missing / non-positive, or when the cohort median is
# missing — the frontend chip self-hides in that case so we never paint
# a fake "second opinion".
#
# Wired into the response in backend/routers/analysis.py alongside the
# existing sector_medians injection (same warm-cache injection cadence,
# zero extra cache writes). Purely additive — `fair_value` is unchanged.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

logger = logging.getLogger("yieldiq.multiples_fv")

# Method tag — keep in sync with the Literal on AnalysisResponse.
MultiplesMethod = Literal["pe", "pb", "ev_ebitda"]


def _coerce_pos_float(v: Any) -> Optional[float]:
    """Float-coerce that drops None, NaN, and non-positive values.

    The multiples formula divides by the ticker's own multiple, so a
    zero or negative input would produce a meaningless FV. Returning
    None routes the call to the next fallback path (PE -> PB) or to
    None overall.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if f <= 0:
        return None
    return f


def _get_ticker_pe(payload: dict) -> Optional[float]:
    """Best-effort positive PE from a cached / fresh analysis payload.

    The PE slot lives on `quality.pe_ratio` in cached payloads — same
    slot sector_medians_for_ticker reads when computing cohort medians.
    Falls back to insights.pe_ratio for legacy payload shapes.
    """
    if not isinstance(payload, dict):
        return None
    qual = payload.get("quality") or {}
    pe = _coerce_pos_float(qual.get("pe_ratio"))
    if pe is not None:
        return pe
    # Legacy / alt path.
    insights = payload.get("insights") or {}
    return _coerce_pos_float(insights.get("pe_ratio"))


def _get_ticker_pb(payload: dict) -> Optional[float]:
    """Best-effort positive PB from a cached / fresh analysis payload."""
    if not isinstance(payload, dict):
        return None
    qual = payload.get("quality") or {}
    pb = _coerce_pos_float(qual.get("pb_ratio"))
    if pb is not None:
        return pb
    insights = payload.get("insights") or {}
    return _coerce_pos_float(insights.get("pb_ratio"))


def _get_current_price(payload: dict) -> Optional[float]:
    """Positive current price from the response's valuation block."""
    if not isinstance(payload, dict):
        return None
    val = payload.get("valuation") or {}
    return _coerce_pos_float(val.get("current_price"))


def compute_multiples_fv(
    payload: dict,
    sector_medians: Optional[dict],
) -> tuple[Optional[float], Optional[MultiplesMethod]]:
    """Compute the peer-relative fair value and the method that drove it.

    Returns ``(None, None)`` when any input is missing, when both PE
    and PB paths fail, or when the resulting FV is non-finite. The
    caller writes both values to the response (or both as None) —
    the frontend chip treats either being None as "hide".

    Args:
        payload: The analysis response payload (dict form). Reads the
            ticker's own PE / PB from `quality.*_ratio` and the current
            price from `valuation.current_price`.
        sector_medians: The {pe, pb, roe, div_yield, op_margin} dict
            produced by `sector_medians_for_ticker`. None or empty -> no
            chip.

    Returns:
        (multiples_based_fv, method) — both populated together, or both
        None when the chip cannot be rendered.
    """
    if not isinstance(payload, dict) or not isinstance(sector_medians, dict):
        return (None, None)

    price = _get_current_price(payload)
    if price is None:
        return (None, None)

    # Path 1: P/E. Preferred — sector_median_pe is populated for the
    # widest range of cohorts (financial-services tickers route through
    # the PB fallback because P/E is meaningless for banks under
    # local accounting practice).
    pe = _get_ticker_pe(payload)
    median_pe = _coerce_pos_float(sector_medians.get("pe"))
    if pe is not None and median_pe is not None:
        try:
            fv = price * (median_pe / pe)
            if fv > 0 and fv == fv:  # finite, positive
                return (round(fv, 2), "pe")
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    # Path 2: P/B fallback. Banks / financial-services / capital-heavy
    # cohorts often run through P/B-only valuation; the frontend treats
    # the chip identically and the tooltip label switches.
    pb = _get_ticker_pb(payload)
    median_pb = _coerce_pos_float(sector_medians.get("pb"))
    if pb is not None and median_pb is not None:
        try:
            fv = price * (median_pb / pb)
            if fv > 0 and fv == fv:
                return (round(fv, 2), "pb")
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return (None, None)
