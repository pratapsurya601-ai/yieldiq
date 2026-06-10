# backend/services/ma_event_detector.py
# ═══════════════════════════════════════════════════════════════
# M&A event detector (ROOT CAUSE #2 + #8, 2026-06-11).
#
# Purpose:
#   Surface a structural M&A event for the analysis page so the
#   front-end can render captions that explain WHY trailing
#   ratios (ROE / ROA) and YoY quarterly comparisons look unusual
#   on a post-merger ticker.
#
#   The detector is a thin reader over `corporate_actions` rows
#   already maintained by the structural-break overlay
#   (data_pipeline/migrations/041_corporate_actions_structural.sql
#   + 042_seed_structural_mergers.sql). No new tables, no new
#   schema. Same STRUCTURAL_ACTION_TYPES set
#   (`MERGER`, `REVERSE_MERGER`, `DEMERGER`,
#   `SCHEME_OF_ARRANGEMENT`, `MATERIAL_ACQUISITION`) the existing
#   `corporate_actions_service.compute_cagr_structural_aware`
#   gates on.
#
# Contract:
#   * `detect_ma_event(ticker, window_quarters=8)` returns a single
#     dict for the most-recent in-window structural row, or `None`
#     when no qualifying row exists (or DB lookup fails).
#   * The dict shape is the public API for the
#     `AnalysisResponse.ma_event` field and the frontend
#     `PostMergerRatioCaption` reads:
#       {
#         "event_date":     "YYYY-MM-DD",   # ISO date
#         "event_type":     "REVERSE_MERGER" | ... | "DEMERGER" | "MERGER" | ...,
#         "magnitude_pct":  70.0,            # balance-sheet expansion %, or None
#         "multiplier":     2.0,             # raw multiplier from corp_actions, or None
#         "normalization_window_quarters": 8,
#         "quarters_since_event": 3,         # whole quarters between event_date and today
#         "description":    "Reverse merger — HDFC Ltd absorbed into HDFC Bank.",
#         "source_url":     "https://..." | None,
#         "source_doc":     "RBI/SEBI ..." | None,
#         "is_within_normalization_window": True,
#       }
#
# Determinism + safety:
#   * Pure read; never writes.
#   * Catches every DB exception, never raises. Returns `None` on
#     any error path so the analysis response is never broken by a
#     missing/late table or a Postgres outage.
#   * Pure dict output — easy to serialise, easy to assert in tests.
#
# Tests:
#   backend/tests/test_ma_event_detector.py — HDFCBANK fixture
#   (asserts a populated payload), TCS fixture (asserts `None`).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger("yieldiq.ma_event_detector")


# Default normalisation window (whole quarters since event_date).
# 8 quarters ≈ 2 years — matches the analytical_notes "allow 2-3
# years for normalisation" copy and the existing post-demerger
# routing window used in `corporate_actions_service.quarters_since_event`.
DEFAULT_WINDOW_QUARTERS: int = 8


# Human-readable label per action_type (for the `description` field).
# Kept stand-alone so the front-end never has to translate the
# upper-snake-case enum string into English on the fly.
_EVENT_DESCRIPTIONS: dict[str, str] = {
    "MERGER":                "Merger",
    "REVERSE_MERGER":        "Reverse merger",
    "DEMERGER":              "Demerger",
    "SCHEME_OF_ARRANGEMENT": "Scheme of arrangement",
    "MATERIAL_ACQUISITION":  "Material acquisition",
}


def _coerce_date(v) -> Optional[date]:
    """Best-effort cast to `date`. Accepts date, datetime, ISO string."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v[:10]).date()
        except Exception:
            return None
    return None


def _whole_quarters_between(start: date, end: date) -> int:
    """Whole quarters between two dates (end - start), floor-divided.

    Mirrors the arithmetic in
    `corporate_actions_service.quarters_since_event` so the
    "quarters since event" reading is identical across both
    surfaces.
    """
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    if months < 0:
        months = 0
    return months // 3


def _magnitude_pct(multiplier: Optional[float]) -> Optional[float]:
    """Convert the raw structural-multiplier into a balance-sheet
    expansion percent for human display.

    The `corporate_actions.multiplier` column carries the structural
    impact factor — e.g. 2.0 for the HDFC reverse merger (FY24 reported
    interest-earned roughly doubled), 1.03 for the Axis-Citi consumer
    acquisition (a ~3% loan-book lift), 1.40 for IDFC-Capital-First
    (~40% balance-sheet lift). The displayable percent is
    `(multiplier - 1) * 100`; never less than zero. Returns None
    when the column is NULL (older non-structural rows).
    """
    if multiplier is None:
        return None
    try:
        m = float(multiplier)
    except (TypeError, ValueError):
        return None
    pct = (m - 1.0) * 100.0
    if pct < 0:
        pct = 0.0
    return pct


def detect_ma_event(
    ticker: str,
    window_quarters: int = DEFAULT_WINDOW_QUARTERS,
    *,
    today: Optional[date] = None,
) -> Optional[dict]:
    """Return the most-recent in-window structural M&A event for `ticker`.

    Args:
        ticker: NSE/BSE ticker. Normalised inside
            `corporate_actions_service.get_actions` to bare form
            (no .NS/.BO suffix).
        window_quarters: lookback window in quarters. Tickers whose
            most-recent structural row is older than this window
            return `None` (the M&A distortion has had time to wash
            through and the caption no longer applies). Default 8
            quarters ≈ 2 years. Pass a larger value (e.g. 20) when
            building historical analytics that need a wider net.
        today: explicit "today" for deterministic tests. Defaults
            to `date.today()`.

    Returns:
        Dict with the public shape documented at the module top, or
        `None` when no qualifying row exists.

    Never raises.
    """
    if window_quarters <= 0:
        return None
    if not ticker or not isinstance(ticker, str):
        return None

    today = today or date.today()

    # `corporate_actions_service.get_actions` already handles ticker
    # normalisation (.NS / .BO strip), DB cursor management, and
    # returns an empty list on any DB error. Window the lookup at
    # the SQL layer to keep the result set small.
    try:
        # Look back the requested window plus a half-year buffer in
        # CASE the window crosses a year boundary, since the
        # underlying SQL filters by ex_date.
        from backend.services.corporate_actions_service import (
            get_actions,
            STRUCTURAL_ACTION_TYPES,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("ma_event_detector: import failure: %s", exc)
        return None

    # Convert window-in-quarters to a since-date. window_quarters * 3
    # months back from today rounds neatly enough; +90 days of slack
    # so a 30-Jun event captured by a 31-Mar lookback isn't dropped
    # by a leap-day rounding edge case.
    months_back = window_quarters * 3
    try:
        year_back = today.year - (months_back // 12)
        month_back = today.month - (months_back % 12)
        while month_back <= 0:
            month_back += 12
            year_back -= 1
        # Day 1 of the resulting month — covers the full month in SQL.
        since = date(year_back, month_back, 1)
    except Exception:
        # Fall back to a 5y horizon if arithmetic fails on some odd
        # date boundary — never broader than the structural overlay
        # itself uses in `quarters_since_event`.
        since = today.replace(year=today.year - 5, day=1)

    try:
        rows = get_actions(ticker, since=since)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "ma_event_detector(%s): get_actions failed: %s",
            ticker, exc,
        )
        return None

    if not rows:
        return None

    # Pick the most-recent structural row whose event_date is on or
    # before today and within the requested window.
    most_recent_row: Optional[dict] = None
    most_recent_date: Optional[date] = None
    for r in rows:
        if r.get("action_type") not in STRUCTURAL_ACTION_TYPES:
            continue
        ev = _coerce_date(r.get("ex_date"))
        if ev is None or ev > today:
            continue
        # Quarters-since check guards against rows that slipped through
        # the SQL window filter (different month-arithmetic).
        q = _whole_quarters_between(ev, today)
        if q > window_quarters:
            continue
        if most_recent_date is None or ev > most_recent_date:
            most_recent_date = ev
            most_recent_row = r

    if most_recent_row is None or most_recent_date is None:
        return None

    action_type = most_recent_row.get("action_type") or ""
    multiplier_raw = most_recent_row.get("multiplier")
    magnitude_pct = _magnitude_pct(multiplier_raw)
    q_since = _whole_quarters_between(most_recent_date, today)

    base_label = _EVENT_DESCRIPTIONS.get(action_type, "Structural M&A event")
    notes = most_recent_row.get("notes")
    if notes and isinstance(notes, str) and notes.strip():
        # Use the curated `notes` column when present — it's the
        # canonical human-readable description from
        # 042_seed_structural_mergers.sql.
        description = f"{base_label} — {notes.strip()}"
    else:
        description = base_label

    multiplier_out: Optional[float]
    try:
        multiplier_out = float(multiplier_raw) if multiplier_raw is not None else None
    except (TypeError, ValueError):
        multiplier_out = None

    return {
        "event_date": most_recent_date.isoformat(),
        "event_type": action_type,
        "magnitude_pct": magnitude_pct,
        "multiplier": multiplier_out,
        "normalization_window_quarters": window_quarters,
        "quarters_since_event": q_since,
        "description": description,
        "source_url": most_recent_row.get("source_url"),
        "source_doc": most_recent_row.get("source_doc"),
        "is_within_normalization_window": q_since <= window_quarters,
    }


def is_quarter_distorted_by_ma(
    quarter_end: Optional[date],
    event_date: Optional[date],
    window_quarters: int = DEFAULT_WINDOW_QUARTERS,
) -> bool:
    """Return True when a structural M&A event landed inside the
    trailing-year window of `quarter_end`, OR when the YoY-baseline
    quarter (same calendar quarter, one year earlier than
    `quarter_end`) sits before the event.

    Used by `quarterly_surprise_service` to suppress the "Last quarter
    vs YieldIQ expected" surprise number when the YoY baseline is on
    the wrong side of the merger — the comparison is structurally
    broken regardless of operational performance.

    Args:
        quarter_end: period_end of the LATEST quarter being shown.
        event_date: ex_date of the M&A event (from
            `detect_ma_event(...)["event_date"]`).
        window_quarters: same 8-quarter normalisation default the
            detector uses. Once `quarter_end` is more than this
            many quarters past `event_date`, YoY comparisons are
            considered safe again.

    Returns False on any malformed input — the suppression is a
    discrete signal, not an estimate, so we err on the side of
    showing the surprise number when we can't be sure.
    """
    if quarter_end is None or event_date is None:
        return False
    if window_quarters <= 0:
        return False

    # Quarter is distorted if event_date is anywhere inside the
    # trailing 12 months of `quarter_end` (the YoY baseline straddles
    # the merger) OR inside the trailing
    # `window_quarters` quarters of `quarter_end` (the absorbed
    # entity's base is still half-loaded into the comp).
    months_since = (
        (quarter_end.year - event_date.year) * 12
        + (quarter_end.month - event_date.month)
    )
    if months_since < 0:
        # Event hasn't happened yet relative to this quarter — no
        # distortion of THIS comp.
        return False

    months_window = window_quarters * 3
    return months_since <= months_window
