# backend/services/corporate_actions_service.py
# ═══════════════════════════════════════════════════════════════
# Structural-break-aware corporate-actions overlay service.
#
# Phase A (this file): SKELETON only.
#   * Schema for the structural columns landed in
#     data_pipeline/migrations/041_corporate_actions_structural.sql
#     (mirror: db/migrations/012_corporate_actions_structural.sql).
#   * No structural rows are seeded yet (Phase B).
#   * The analysis pipeline does NOT call this module yet (Phase C).
#
# As a result, the public methods here are DESIGNED to be safe no-ops
# until Phase B lands seed data:
#   * has_structural_break() → always returns False (no rows → no break).
#   * compute_cagr_structural_aware() → falls back to plain
#     ratios_service.compute_revenue_cagr semantics.
#
# This means callers wired in Phase C will see ZERO behaviour change
# on tickers without seed rows — i.e. canary-diff stays clean and the
# CACHE_VERSION bump in Phase C only affects the 2-3 seeded names.
#
# See docs/design/corporate-actions-overlay.md for the full design.
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
    ticker_norm = ticker.strip().upper()
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


# ── 3. compute_cagr_structural_aware ────────────────────────────
def compute_cagr_structural_aware(
    ticker: str,
    field: str,
    years: int,
    series: Optional[Sequence[float]] = None,
) -> Optional[float]:
    """Structural-break-aware CAGR.

    Phase-A behaviour: no seed rows exist, so this always falls back to
    the plain `ratios_service.compute_revenue_cagr` primitive. The
    `field` argument is reserved for Phase C, where the structural
    truncation logic will branch on field ("revenue" | "ebitda" |
    "net_profit") to look up the right post-break series.

    Args:
        ticker: NSE/BSE ticker.
        field: metric name; reserved for Phase C.
        years: CAGR horizon (typically 3 or 5).
        series: chronological values (oldest → newest) for the metric.
            REQUIRED in Phase A — the caller already has the series in
            hand from analysis/service.py. Phase C will optionally load
            it from cache when None.

    Returns:
        Decimal CAGR (e.g. 0.124 for 12.4%) or None if insufficient data.
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
        # Phase A: no cache fallback. Caller must supply the series.
        return None

    # Phase-A: no break detection in effect (no seed rows). Once Phase B
    # seeds rows, has_structural_break() will start returning True for
    # the affected tickers and Phase C will branch here on the
    # truncation logic. For now, plain CAGR.
    if has_structural_break(ticker, window_years=years):
        # Reserved branch — Phase C will truncate `series` to the
        # post-break window here. Until then, log and fall through to
        # the plain primitive so behaviour is unchanged.
        logger.debug(
            "compute_cagr_structural_aware(%s, %s, %dy): break detected "
            "but Phase-A truncation not implemented; using plain CAGR",
            ticker, field, years,
        )

    return compute_revenue_cagr(series, years)
