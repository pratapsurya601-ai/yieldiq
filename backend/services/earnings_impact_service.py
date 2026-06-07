# backend/services/earnings_impact_service.py
# ═══════════════════════════════════════════════════════════════
# Earnings impact estimator (Phase 1).
#
# What this is: a HEURISTIC that bridges "fresh quarterly result"
# to "rough sense of how the next nightly fair-value recompute may
# move". It does NOT recompute fair value, it does NOT update the
# DCF, and it does NOT issue advice. The number it returns is an
# expected range that a non-expert reader can use to anchor their
# expectation between a beat / miss headline and the next formal
# nightly recompute.
#
# Math (intentionally simple, intentionally a heuristic):
#
#   1. "Actual" revenue = the latest row in
#      `company_quarterly_results` for the ticker (newest by
#      period_end — the fiscal_quarter label string is known buggy).
#
#   2. "Expected" revenue is derived from one of two baselines, in
#      preference order:
#        (a) YoY: same quarter last year's revenue, scaled up by
#            YieldIQ's current DCF-implied annual growth rate. This
#            is the cleaner comparison because it removes quarterly
#            seasonality (Q3 vs Q4 mix shifts, festive demand, etc.).
#        (b) QoQ: previous quarter's revenue, scaled up by
#            (1 + implied_growth / 4). Used only when a YoY row is
#            absent in the table.
#
#   3. surprise_pct = (actual - expected) / expected.
#
#   4. FV impact (point estimate):
#         fv_delta = surprise_pct * sector_multiplier * 0.3
#
#      The 0.3 dampener exists because a DCF is anchored by
#      multi-year compounding — a one-quarter revenue beat moves
#      the multi-year fair value by far less than the headline
#      beat percentage. 0.3 is a deliberate, dampening guess; it
#      is NOT calibrated against historical recomputes. We are
#      explicit about this everywhere this number surfaces.
#
#   5. Sector multipliers reflect how much a top-line beat tends
#      to translate to DCF moves:
#         - IT Services, Auto, Metal, Real Estate: 1.2 (cyclical
#           / op-leverage rich — a beat tends to mean more)
#         - Pharma, Consumer Durables, Energy, Media: 1.0 (neutral)
#         - FMCG, Bank, Private Bank, PSU Bank, Financial Services:
#           0.7 (defensive / interest-rate-driven — single-quarter
#           top-line is less load-bearing in their DCF)
#      Unknown sector → 1.0.
#
#   6. The output range is the point estimate ± 2 percentage
#      points, then clamped to [-15%, +15%]. A single quarter
#      should not justify a swing larger than that against a
#      multi-year DCF — if it does, the formal recompute will
#      catch it on its own merits.
#
# Caller contract: this function is PURE — no DB calls, no cache
# reads, no IO. The router fetches the inputs and applies the
# math. Tests can drive it with synthetic rows directly.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Optional


# Sector multipliers — see module docstring for rationale.
# Keep keys lowercase; the resolver lowercase-strips its input.
_SECTOR_MULTIPLIER: dict[str, float] = {
    "it services": 1.2,
    "auto": 1.2,
    "metal": 1.2,
    "real estate": 1.2,
    "pharma": 1.0,
    "consumer durables": 1.0,
    "energy": 1.0,
    "media": 1.0,
    "fmcg": 0.7,
    "bank": 0.7,
    "private bank": 0.7,
    "psu bank": 0.7,
    "financial services": 0.7,
}

# Dampener: a one-quarter revenue beat does NOT translate 1:1 to
# DCF fair value. The DCF is anchored by multi-year compounding,
# and the formal nightly recompute will incorporate the beat
# through its own pipeline. 0.3 is an explicit, deliberate guess.
_DAMPENER = 0.3

# Clamp on the displayed range. A single quarter should not move
# the heuristic by more than ±15% — if the formal recompute moves
# the FV by more than that, the cause is multi-quarter, not this
# one print.
_RANGE_CLAMP = 0.15

# Half-width of the displayed range around the point estimate,
# in absolute units (i.e. ±0.02 = ±2 percentage points). Kept
# small enough that the range is informative but wide enough to
# signal "this is heuristic, not a recompute."
_RANGE_HALF_WIDTH = 0.02


def _sector_multiplier(sector: Optional[str]) -> float:
    """Resolve the sector multiplier; unknown sector → 1.0."""
    if not sector:
        return 1.0
    return _SECTOR_MULTIPLIER.get(sector.strip().lower(), 1.0)


def _period_end_month(row: dict) -> Optional[int]:
    """Return the calendar month of `period_end` (1..12) or None."""
    pe = row.get("period_end")
    if pe is None:
        return None
    return getattr(pe, "month", None)


def _find_yoy_baseline(rows: list[dict]) -> Optional[dict]:
    """
    Return the row whose period_end is in the same calendar month
    as the latest row's period_end but ~1 year earlier. Matches by
    month (Q1 = Jun, Q2 = Sep, Q3 = Dec, Q4 = Mar for Indian
    Ind-AS filings) rather than by the buggy fiscal_quarter label.
    Returns None when the YoY row is absent in the window.
    """
    if not rows or len(rows) < 2:
        return None
    latest = rows[0]
    latest_month = _period_end_month(latest)
    if latest_month is None:
        return None
    latest_pe = latest.get("period_end")
    latest_year = getattr(latest_pe, "year", None) if latest_pe else None
    for r in rows[1:]:
        if _period_end_month(r) != latest_month:
            continue
        r_pe = r.get("period_end")
        r_year = getattr(r_pe, "year", None) if r_pe else None
        if latest_year is None or r_year is None:
            return r
        # Accept any earlier-year row in the same calendar month;
        # the closest one is preferred (rows are sorted newest first
        # so the first match is the closest).
        if r_year < latest_year:
            return r
    return None


def estimate_earnings_impact(
    quarterly_rows: list[dict],
    *,
    implied_growth: Optional[float],
    sector: Optional[str],
) -> Optional[dict]:
    """
    Compute the earnings-impact heuristic from quarterly rows.

    Inputs:
      quarterly_rows: rows from `company_quarterly_results`,
        newest first. Each row MUST carry `period_end` (date) and
        `revenue_cr` (float, in crores). Other fields are ignored
        by the math but echoed in the output for the panel.
      implied_growth: YieldIQ's current DCF implied annual revenue
        growth rate (e.g. 0.12 for 12% / yr). May be None — in
        that case we fall back to 0.10 (a neutral assumption) and
        flag it in `notes`.
      sector: canonical sector string (see sector_taxonomy.py).
        May be None / empty — falls back to multiplier 1.0.

    Output (None when the inputs are insufficient):
      {
        "latest_quarter": {
          "period_end":  "YYYY-MM-DD",
          "revenue_cr":  float,
          "net_profit_cr": float | None,
        },
        "baseline": {
          "kind":        "yoy" | "qoq",
          "period_end":  "YYYY-MM-DD",
          "revenue_cr":  float,
        },
        "expected_revenue_cr":  float,
        "surprise_pct":         float,   # signed, e.g. 0.07 = +7%
        "sector":               str | None,
        "sector_multiplier":    float,
        "implied_growth_used":  float,
        "fv_delta_estimate":    float,   # point estimate, signed
        "fv_delta_range": {              # clamped, signed
          "low":   float,
          "high":  float,
        },
        "notes": list[str],              # caveat tags
        "method": "heuristic_v1",
        "is_heuristic": True,            # explicit, never absent
      }

    Returns None when there is no latest row, no usable baseline,
    or revenue is non-positive (can't divide).
    """
    if not quarterly_rows:
        return None
    latest = quarterly_rows[0]
    latest_revenue = latest.get("revenue_cr")
    if latest_revenue is None:
        return None
    try:
        latest_revenue = float(latest_revenue)
    except (TypeError, ValueError):
        return None
    if latest_revenue <= 0:
        return None

    notes: list[str] = []
    growth = implied_growth
    if growth is None:
        growth = 0.10
        notes.append("implied_growth_missing_fallback_10pct")
    # Defensive: clamp growth into a sane band so a corrupt -500%
    # value doesn't poison the expected baseline.
    if growth < -0.5:
        growth = -0.5
        notes.append("implied_growth_clamped_low")
    elif growth > 1.0:
        growth = 1.0
        notes.append("implied_growth_clamped_high")

    # ── Resolve baseline (YoY preferred, QoQ fallback) ──
    yoy = _find_yoy_baseline(quarterly_rows)
    baseline_row: Optional[dict] = None
    baseline_kind: Optional[str] = None
    expected: Optional[float] = None

    if yoy is not None:
        yoy_rev = yoy.get("revenue_cr")
        try:
            yoy_rev_f = float(yoy_rev) if yoy_rev is not None else None
        except (TypeError, ValueError):
            yoy_rev_f = None
        if yoy_rev_f is not None and yoy_rev_f > 0:
            baseline_row = yoy
            baseline_kind = "yoy"
            # YoY → scale by the full annual growth rate.
            expected = yoy_rev_f * (1.0 + growth)

    if expected is None and len(quarterly_rows) >= 2:
        prev = quarterly_rows[1]
        prev_rev = prev.get("revenue_cr")
        try:
            prev_rev_f = float(prev_rev) if prev_rev is not None else None
        except (TypeError, ValueError):
            prev_rev_f = None
        if prev_rev_f is not None and prev_rev_f > 0:
            baseline_row = prev
            baseline_kind = "qoq"
            # QoQ → scale by one quarter's worth of the annual rate.
            expected = prev_rev_f * (1.0 + growth / 4.0)
            notes.append("baseline_qoq_used_yoy_absent")

    if expected is None or baseline_row is None or baseline_kind is None:
        return None
    if expected <= 0:
        return None

    surprise_pct = (latest_revenue - expected) / expected
    sector_mult = _sector_multiplier(sector)

    # Point estimate — explicit, dampened, and labelled as heuristic
    # at every surface.
    fv_delta = surprise_pct * sector_mult * _DAMPENER
    # Range around the point estimate, then clamp.
    low = max(-_RANGE_CLAMP, fv_delta - _RANGE_HALF_WIDTH)
    high = min(_RANGE_CLAMP, fv_delta + _RANGE_HALF_WIDTH)
    if fv_delta < -_RANGE_CLAMP or fv_delta > _RANGE_CLAMP:
        notes.append("fv_delta_clamped")
    # Clamp the point estimate too so the panel never displays a
    # number outside the range it just printed.
    fv_delta_clamped = max(-_RANGE_CLAMP, min(_RANGE_CLAMP, fv_delta))

    def _iso(row: dict) -> Optional[str]:
        pe = row.get("period_end")
        if pe is None:
            return None
        return pe.isoformat() if hasattr(pe, "isoformat") else str(pe)

    def _opt_float(v) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "latest_quarter": {
            "period_end": _iso(latest),
            "revenue_cr": latest_revenue,
            "net_profit_cr": _opt_float(latest.get("net_profit_cr")),
        },
        "baseline": {
            "kind": baseline_kind,
            "period_end": _iso(baseline_row),
            "revenue_cr": _opt_float(baseline_row.get("revenue_cr")),
        },
        "expected_revenue_cr": expected,
        "surprise_pct": surprise_pct,
        "sector": sector,
        "sector_multiplier": sector_mult,
        "implied_growth_used": growth,
        "fv_delta_estimate": fv_delta_clamped,
        "fv_delta_range": {"low": low, "high": high},
        "notes": notes,
        "method": "heuristic_v1",
        # Explicit flag — every downstream consumer (router, frontend,
        # any future caller) is required to label this surface as a
        # heuristic. Leaving this field implicit was rejected during
        # design review.
        "is_heuristic": True,
    }
