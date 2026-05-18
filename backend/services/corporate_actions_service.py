# backend/services/corporate_actions_service.py
# ═══════════════════════════════════════════════════════════════
# Structural-break-aware corporate-actions overlay service.
#
# Phase A (initial): SKELETON only.
# Phase B (this PR — feat/hdfc-merger-growth-truncation):
#   Seed rows landed in
#   data_pipeline/migrations/042_seed_structural_mergers.sql
#   (mirror: db/migrations/013_seed_structural_mergers.sql).
# Phase C (this PR): compute_cagr_structural_aware() now implements
#   the post-break truncation logic (Approach B) reserved in the
#   original Phase-A docstring slot. See
#   docs/design/hdfc-merger-growth-normalization.md for the design.
#
# Wire-in:
#   backend/services/analysis/service.py (~line 2062) now routes the
#   3y / 5y revenue CAGR calls through compute_cagr_structural_aware
#   so that tickers with seed structural rows get the truncated series
#   while non-seeded tickers fall through to plain CAGR byte-identically.
#
# Behaviour contract:
#   * has_structural_break() returns False for any ticker without a
#     structural seed row → callers fall through to plain CAGR.
#   * For seeded tickers, the merger fiscal year (Indian Apr–Mar) is
#     dropped from the trailing window. Positions strictly *after* the
#     merger FY are used. If <`years + 1` post-break points remain,
#     the function returns None — the bellwether allowlist in
#     analysis/service.py handles the None state gracefully.
#
# See docs/design/corporate-actions-overlay.md for Phase-A context.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional, Sequence

logger = logging.getLogger("yieldiq.corporate_actions")

# action_type values treated as STRUCTURAL breaks. Existing dividend /
# split / bonus rows are NOT in this set, so their behaviour is
# untouched. Kept in sync with the CHECK constraint in
# data_pipeline/migrations/041_corporate_actions_structural.sql.
STRUCTURAL_ACTION_TYPES: frozenset[str] = frozenset({
    "MERGER",
    "REVERSE_MERGER",
    "DEMERGER",
    "SCHEME_OF_ARRANGEMENT",
    "MATERIAL_ACQUISITION",
})


# ── DB cursor helper (mirrors band_alert_service pattern) ────────
def _get_cursor():
    """Return (conn, cursor) from the pipeline engine, or (None, None).

    Returns (None, None) on any failure — callers must treat this as
    "no break information available" and fall through to plain CAGR.
    """
    try:
        from data_pipeline.db import engine
    except Exception as exc:
        logger.warning("corporate_actions: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    try:
        conn = engine.raw_connection()
        cur = conn.cursor()
        return conn, cur
    except Exception as exc:
        logger.warning("corporate_actions: engine.raw_connection() failed: %s", exc)
        return None, None


def _close(conn, cur) -> None:
    try:
        if cur is not None:
            cur.close()
    except Exception:
        pass
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


# ── 1. get_actions ──────────────────────────────────────────────
def get_actions(
    ticker: str,
    action_type: Optional[str] = None,
    since: Optional[date] = None,
) -> list[dict]:
    """Fetch corporate-actions rows for `ticker`.

    Args:
        ticker: NSE/BSE ticker, case-insensitive (normalised to upper).
        action_type: optional filter; pass a single action_type string
            (e.g. "REVERSE_MERGER") or None for all.
        since: optional lower bound on ex_date (inclusive).

    Returns:
        List of dicts with keys:
            ticker, ex_date, action_type, multiplier,
            source_url, source_doc, notes, data_source, data_quality_rank.
        Empty list on any DB error or if the table is empty for `ticker`.
        Never raises.
    """
    if not ticker:
        return []
    # FIX-CORP-ACTIONS-TICKER-NORM (2026-05-18): the corp_actions table
    # stores tickers in BARE form (e.g. "HDFCBANK") but the caller in
    # analysis/service.py passes the canonical .NS-suffixed form
    # ("HDFCBANK.NS") because that's what the rest of the analysis
    # pipeline uses as the cache key. Without this strip, the query
    # returns empty for every Indian ticker and `has_structural_break`
    # silently returns False — the HDFCBANK 30% phantom growth fix
    # (PR #324) was a no-op in prod until this hotfix landed.
    ticker_norm = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    if not ticker_norm:
        return []

    conn, cur = _get_cursor()
    if cur is None:
        return []

    rows: list[dict] = []
    try:
        sql = (
            "SELECT ticker, ex_date, action_type, multiplier, "
            "       source_url, source_doc, notes, "
            "       data_source, data_quality_rank "
            "FROM corporate_actions "
            "WHERE ticker = %s"
        )
        params: list = [ticker_norm]
        if action_type:
            sql += " AND action_type = %s"
            params.append(action_type)
        if since is not None:
            sql += " AND ex_date >= %s"
            params.append(since)
        sql += " ORDER BY ex_date ASC"

        cur.execute(sql, tuple(params))
        for r in cur.fetchall():
            rows.append({
                "ticker":            r[0],
                "ex_date":           r[1],
                "action_type":       r[2],
                "multiplier":        float(r[3]) if r[3] is not None else None,
                "source_url":        r[4],
                "source_doc":        r[5],
                "notes":             r[6],
                "data_source":       r[7],
                "data_quality_rank": r[8],
            })
    except Exception as exc:
        logger.warning("get_actions(%s) failed: %s", ticker_norm, exc)
        rows = []
    finally:
        _close(conn, cur)

    return rows


# ── 2. has_structural_break ─────────────────────────────────────
def has_structural_break(ticker: str, window_years: int = 3) -> bool:
    """Return True if any structural action_type row exists for `ticker`
    in the trailing `window_years`-year window from today.

    Phase-A behaviour: there are no structural rows seeded yet, so this
    method will always return False. The wiring is in place so Phase B
    can drop seed rows and immediately activate detection without any
    further code change.
    """
    if window_years <= 0:
        return False
    today = date.today()
    try:
        window_start = today.replace(year=today.year - window_years)
    except ValueError:
        # leap-day rollover (Feb 29 → Mar 1 conceptually); safe fallback
        window_start = today.replace(month=1, day=1, year=today.year - window_years)

    rows = get_actions(ticker, since=window_start)
    for r in rows:
        if r.get("action_type") in STRUCTURAL_ACTION_TYPES:
            ex_date = r.get("ex_date")
            if isinstance(ex_date, datetime):
                ex_date = ex_date.date()
            if ex_date is None or ex_date <= today:
                return True
    return False


# ── Helpers: Indian fiscal-year mapping ────────────────────────
def _indian_fy_end_year(d: date) -> int:
    """Return the year-number of the Indian FY-end (Mar 31) containing `d`.

    Indian financial year runs Apr 1 → Mar 31. A date in Jul 2023 sits
    inside FY24, whose period_end is 2024-03-31; this helper returns
    2024 for that date. A date in Feb 2024 also sits inside FY24 → 2024.
    """
    if d.month >= 4:
        return d.year + 1
    return d.year


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


def _earliest_structural_break_fy(ticker: str, window_years: int) -> Optional[int]:
    """Return the earliest in-window structural-break FY (year-number of
    the FY-end), or None if no in-window structural row exists.

    Used by compute_cagr_structural_aware() to compute how many tail
    positions of the input series are post-break.
    """
    if window_years <= 0:
        return None
    today = date.today()
    try:
        window_start = today.replace(year=today.year - window_years)
    except ValueError:
        window_start = today.replace(month=1, day=1, year=today.year - window_years)

    rows = get_actions(ticker, since=window_start)
    fy_ends: list[int] = []
    for r in rows:
        if r.get("action_type") not in STRUCTURAL_ACTION_TYPES:
            continue
        ex_date = _coerce_date(r.get("ex_date"))
        if ex_date is None or ex_date > today:
            continue
        fy_ends.append(_indian_fy_end_year(ex_date))
    if not fy_ends:
        return None
    return min(fy_ends)


# ── 3. compute_cagr_structural_aware ────────────────────────────
def compute_cagr_structural_aware(
    ticker: str,
    field: str,
    years: int,
    series: Optional[Sequence[float]] = None,
    latest_period_end: Optional[object] = None,
) -> Optional[float]:
    """Structural-break-aware CAGR (post-break truncation — Approach B).

    For tickers with a STRUCTURAL_ACTION_TYPES row inside the trailing
    `years`-year window, truncate `series` to the strictly post-break
    fiscal-year tail before delegating to ratios_service.compute_revenue_cagr.
    The merger FY itself is excluded — its YoY YoY-comparable is broken
    by the corporate event, so the first comparable position is FY+1.

    If the post-break tail has fewer than `years + 1` points, return
    None (the analysis pipeline's bellwether allowlist / null-CAGR gate
    handle the None display).

    Args:
        ticker: NSE/BSE ticker.
        field: metric name; informational only today ("revenue" /
            "ebitda" / "net_profit") — `series` is the authoritative
            input. Reserved for a future cache-pull path.
        years: CAGR horizon (typically 3 or 5).
        series: chronological values (oldest → newest) for the metric.
            REQUIRED — the caller already has the series in hand from
            analysis/service.py.
        latest_period_end: date (or ISO string) of the last position in
            `series`. Used to derive each position's FY. When omitted,
            we fall back to *today's* FY which is correct for the live
            analysis call-site (the latest annual / TTM row is current).

    Returns:
        Decimal CAGR (e.g. 0.124 for 12.4%) or None on:
          * insufficient post-break data,
          * insufficient raw data,
          * unrecoverable input shape.
    """
    # Defensive imports — avoid a hard dependency at module import time
    # so test environments without the full backend can still import
    # this module's signatures.
    try:
        from backend.services.ratios_service import compute_revenue_cagr
    except Exception as exc:
        logger.warning("compute_cagr_structural_aware: ratios import failed: %s", exc)
        return None

    if series is None:
        return None

    series_list = list(series)

    # Fast path: no structural break → plain CAGR. This is the lion's
    # share of tickers and the path canary-diff stays clean on.
    break_fy = _earliest_structural_break_fy(ticker, window_years=years)
    if break_fy is None:
        return compute_revenue_cagr(series_list, years)

    # Derive the FY-end year of the LAST series position. The analysis
    # call-site populates `latest_period_end` from
    # local_data_service.py (string date of the latest annual or TTM
    # row); fall back to today's FY when absent.
    pe = _coerce_date(latest_period_end)
    if pe is not None:
        latest_fy = _indian_fy_end_year(pe)
    else:
        latest_fy = _indian_fy_end_year(date.today())

    # Each preceding position is FY-1, FY-2, ... assuming the input is
    # a strictly annual series (which is the analysis-pipeline contract
    # — income_df rows are annual financials, optionally with a TTM
    # row appended; the TTM row by convention belongs to `latest_fy`).
    n = len(series_list)
    # Position i (0-indexed) corresponds to FY (latest_fy - (n - 1 - i)).
    # The first STRICTLY post-break position is the smallest i with
    # FY > break_fy, i.e. (latest_fy - (n - 1 - i)) > break_fy
    # ⇒ i > break_fy - latest_fy + n - 1
    first_post = break_fy - latest_fy + n  # = break_fy + (n - latest_fy)
    if first_post < 0:
        first_post = 0
    if first_post >= n:
        post_break = []
    else:
        post_break = series_list[first_post:]

    logger.info(
        "structural_cagr.truncate ticker=%s field=%s years=%d "
        "break_fy=%d latest_fy=%d n=%d first_post=%d post_break_len=%d",
        ticker, field, years, break_fy, latest_fy, n, first_post,
        len(post_break),
    )

    if len(post_break) < years + 1:
        # Grace window: not enough post-break annuals to compute the
        # horizon. Caller already handles None via the bellwether
        # allowlist + null-CAGR gate (see analysis/service.py FIX 1).
        return None

    return compute_revenue_cagr(post_break, years)
