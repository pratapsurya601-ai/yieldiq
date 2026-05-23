# backend/services/cagr_service.py
"""
Day-103c (2026-05-22) — Compounded growth (CAGR) panel.

Computes 3y / 5y / 10y compounded growth for:
  * revenue   — CAGR of annual revenue
  * profit    — CAGR of annual net income (PAT)
  * roe_avg   — simple average of annual ROE over the window
                (ROE does not compound — averaging is the conventional
                 Screener.in-style presentation)
  * stock     — CAGR of close price using daily_prices

Insufficient data → None for that cell. Sanity gate: |CAGR| > 100%
is treated as a data error and nulled. Returned shape is intentionally
simple JSON so the SEO/public stock-summary endpoint can ferry it to
the React panel with no further reshaping.

Pure read service. No engine recompute, no cache writes. Adding the
panel as a new field on stock-summary is additive — no CACHE_VERSION
bump (see Day-94 manifest; this ships a scoped entry instead).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("yieldiq.cagr")

# Maximum absolute CAGR we treat as plausible. Anything beyond this is
# almost certainly a unit mismatch or a base-effect from a near-zero
# denominator and is nulled so the UI shows "—".
_SANITY_ABS_CAP = 100.0

# Coverage threshold: a window of N years needs at least this fraction
# of expected periods to compute. Below the threshold we return None
# rather than risk publishing a half-window CAGR labelled as e.g. "10y".
_MIN_COVERAGE = 0.70

# Windows we publish, in years. Order matters for the response shape.
_WINDOWS = (3, 5, 10)


# ──────────────────────────────────────────────────────────────────────
# Math primitives
# ──────────────────────────────────────────────────────────────────────


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Standard CAGR: ((end/start) ** (1/years) - 1) * 100.

    Returns None if either endpoint is missing, ``start`` is non-positive
    (sign-flip makes CAGR undefined), the result is non-finite, or the
    sanity gate trips. One decimal place.
    """
    if start is None or end is None or years <= 0:
        return None
    try:
        s = float(start)
        e = float(end)
    except (TypeError, ValueError):
        return None
    if s <= 0 or e <= 0:
        return None
    try:
        pct = ((e / s) ** (1.0 / years) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if not math.isfinite(pct):
        return None
    if abs(pct) > _SANITY_ABS_CAP:
        return None
    return round(pct, 1)


def _avg(values: list[float | None]) -> float | None:
    """Simple mean over non-None values, sanity-gated, one decimal."""
    nums: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        nums.append(f)
    if not nums:
        return None
    mean = sum(nums) / len(nums)
    if not math.isfinite(mean):
        return None
    if abs(mean) > _SANITY_ABS_CAP:
        return None
    return round(mean, 1)


# ──────────────────────────────────────────────────────────────────────
# Annual financials snapshot used by all 3 of revenue / profit / roe_avg
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _AnnualPoint:
    fy: int                  # Indian FY (year ending in Mar)
    period_end: date
    revenue: float | None
    pat: float | None
    equity: float | None

    @property
    def roe(self) -> float | None:
        if self.pat is None or self.equity is None or self.equity <= 0:
            return None
        return self.pat / self.equity * 100.0


def _fy_for(period_end: date) -> int:
    return period_end.year + 1 if period_end.month >= 4 else period_end.year


def _fetch_annual_points(db, db_ticker: str, max_years: int = 12) -> list[_AnnualPoint]:
    """Pull annual revenue / PAT / equity, newest-first, deduped by FY."""
    inc_rows = db.execute(text("""
        SELECT period_end_date, revenue, net_income
        FROM company_financials
        WHERE ticker_nse = :t
          AND statement_type = 'income'
          AND period_type = 'annual'
          AND period_end_date IS NOT NULL
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "lim": max_years}).mappings().all()

    if not inc_rows:
        return []

    bs_rows = db.execute(text("""
        SELECT period_end_date, total_equity
        FROM company_financials
        WHERE ticker_nse = :t
          AND statement_type = 'balance_sheet'
          AND period_type = 'annual'
          AND period_end_date IS NOT NULL
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "lim": max_years}).mappings().all()

    eq_by_pend = {r["period_end_date"]: r.get("total_equity") for r in bs_rows}

    seen_fy: set[int] = set()
    out: list[_AnnualPoint] = []
    for r in inc_rows:
        pend = r["period_end_date"]
        if pend is None:
            continue
        fy = _fy_for(pend)
        if fy in seen_fy:
            continue
        seen_fy.add(fy)
        out.append(_AnnualPoint(
            fy=fy,
            period_end=pend,
            revenue=_safe_num(r.get("revenue")),
            pat=_safe_num(r.get("net_income")),
            equity=_safe_num(eq_by_pend.get(pend)),
        ))
    return out


def _safe_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


# ──────────────────────────────────────────────────────────────────────
# Window helpers
# ──────────────────────────────────────────────────────────────────────


def _window_endpoints(
    points: list[_AnnualPoint], years: int, attr: str,
) -> tuple[float | None, float | None, int]:
    """Find the newest and ``years``-back values of ``attr`` (e.g. 'revenue').

    Strategy: walk newest→oldest until we find a usable newest endpoint;
    then look for the point whose FY is exactly ``years`` earlier. If
    that exact-FY point is missing/null, fall back to the nearest
    older point — but only if it's within +/-1 FY of the target. This
    keeps the labelled window honest.

    Returns (start_value, end_value, actual_years_used). actual_years
    may differ from ``years`` by ±1 due to the fallback above; callers
    use it to derive the CAGR exponent.
    """
    usable = [p for p in points if getattr(p, attr) is not None]
    if len(usable) < 2:
        return (None, None, 0)
    newest = usable[0]
    target_fy = newest.fy - years
    # Prefer exact FY match; fallback ±1.
    candidate: _AnnualPoint | None = None
    for p in usable[1:]:
        if p.fy == target_fy:
            candidate = p
            break
    if candidate is None:
        for p in usable[1:]:
            if abs(p.fy - target_fy) <= 1:
                candidate = p
                break
    if candidate is None:
        return (None, None, 0)
    actual_years = newest.fy - candidate.fy
    if actual_years <= 0:
        return (None, None, 0)
    return (getattr(candidate, attr), getattr(newest, attr), actual_years)


def _coverage_ok(points: list[_AnnualPoint], window_years: int, attr: str) -> bool:
    """At least ``_MIN_COVERAGE`` × (window_years+1) usable points present?

    A 5y CAGR needs 6 endpoints in the ideal case. We accept down to
    70% — i.e. 5 of 6 for a 5y window. Below that we null the cell.
    """
    if not points:
        return False
    newest_fy = points[0].fy
    needed_min = max(2, int(math.ceil((window_years + 1) * _MIN_COVERAGE)))
    in_window = [
        p for p in points
        if (newest_fy - p.fy) <= window_years
        and getattr(p, attr) is not None
    ]
    return len(in_window) >= needed_min


def _window_avg(
    points: list[_AnnualPoint], years: int, attr: str,
) -> float | None:
    if not points:
        return None
    if not _coverage_ok(points, years, attr):
        return None
    newest_fy = points[0].fy
    values = [
        getattr(p, attr) for p in points
        if (newest_fy - p.fy) <= years
        and getattr(p, attr) is not None
    ]
    return _avg(values)


# ──────────────────────────────────────────────────────────────────────
# Stock CAGR — uses daily_prices via psycopg2 (consistent with
# price_history_service.py for the live PG path).
# ──────────────────────────────────────────────────────────────────────


def _fetch_adj_close_on_or_before(conn, ticker: str, target: date) -> tuple[date, float] | None:
    """Most recent NON-NULL adj_close on or before ``target`` for ``ticker``.

    Day-112: we now read adj_close (split + bonus + dividend adjusted)
    instead of raw close_price. adj_close is populated by
    scripts/rebuild_adj_close.py and is the canonical series for any
    return calculation. If adj_close is NULL the row is skipped — we
    intentionally do NOT fall back to close_price, because doing so
    silently re-introduces the pre-Day-112 bug (a -7.8% RELIANCE 5y
    CAGR computed from raw post-bonus close vs raw pre-bonus close).

    Trade-date alignment: weekend/holiday target -> walk back up to
    14 days; outside that window we return None and the response
    payload surfaces "stock_cagr_status": "rebuild_pending".
    """
    floor = target - timedelta(days=14)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT trade_date, adj_close FROM daily_prices "
            "WHERE ticker = %s AND trade_date <= %s AND trade_date >= %s "
            "  AND adj_close IS NOT NULL "
            "ORDER BY trade_date DESC LIMIT 1",
            (ticker, target, floor),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if not row:
        return None
    td, adj = row
    if adj is None:
        return None
    try:
        return (td, float(adj))
    except (TypeError, ValueError):
        return None


def _stock_cagr_panel(ticker_full: str, today: date) -> dict[str, Any]:
    """3y / 5y / 10y CAGR of adj_close.

    Day-112 return shape: in addition to the per-window CAGRs, this
    dict carries a ``status`` field so the caller can surface
    "rebuild_pending" to ops when adj_close is missing for the
    requested ticker. Possible status values:

      * ``ok``               — adj_close present and all windows computed
      * ``partial``          — at least one window resolved, at least one None
      * ``rebuild_pending``  — no usable adj_close found for this ticker
                               (the rebuild script never covered it, or it
                               was added to ``stocks`` after the last rebuild)
      * ``db_unavailable``   — DATABASE_URL unset or psycopg2 connect failed
    """
    import os
    url = os.environ.get("DATABASE_URL")
    out: dict[str, Any] = {"3y": None, "5y": None, "10y": None,
                           "status": "rebuild_pending"}
    if not url:
        out["status"] = "db_unavailable"
        return out
    bare = ticker_full.replace(".NS", "").replace(".BO", "")
    try:
        import psycopg2
        conn = psycopg2.connect(url)
    except Exception as exc:
        logger.info("stock CAGR: psycopg2 connect failed for %s: %s", bare, exc)
        out["status"] = "db_unavailable"
        return out
    try:
        # Latest adj_close: most recent trade_date in last 14 days.
        latest = _fetch_adj_close_on_or_before(conn, bare, today)
        if latest is None:
            # No adj_close at all — surface "rebuild_pending" loudly. We
            # do NOT fall back to close_price (see _fetch_adj_close_on_
            # or_before docstring).
            return out
        _, end_price = latest
        any_resolved = False
        any_missing = False
        for years in _WINDOWS:
            anchor = today - timedelta(days=365 * years)
            start = _fetch_adj_close_on_or_before(conn, bare, anchor)
            if start is None:
                out[f"{years}y"] = None
                any_missing = True
                continue
            _, start_price = start
            v = _cagr(start_price, end_price, years)
            out[f"{years}y"] = v
            if v is None:
                any_missing = True
            else:
                any_resolved = True
        if any_resolved and not any_missing:
            out["status"] = "ok"
        elif any_resolved:
            out["status"] = "partial"
        # else: stays "rebuild_pending"
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


# ──────────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────────


def _empty_panel(as_of_fy: int | None) -> dict[str, Any]:
    return {
        "revenue": {"3y": None, "5y": None, "10y": None, "as_of_fy": as_of_fy},
        "profit":  {"3y": None, "5y": None, "10y": None, "as_of_fy": as_of_fy},
        "roe_avg": {"3y": None, "5y": None, "10y": None, "as_of_fy": as_of_fy},
        # Day-112: stock dict carries `status` (ok / partial /
        # rebuild_pending / db_unavailable) so the caller knows when
        # to render the "rebuild needed" badge vs the "—" placeholder.
        "stock":   {"3y": None, "5y": None, "10y": None, "as_of_fy": as_of_fy,
                    "status": "rebuild_pending"},
    }


def compute_cagr_panel(
    ticker: str,
    *,
    today: date | None = None,
    points: list[_AnnualPoint] | None = None,
    stock_panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the compounded-growth panel dict for ``ticker``.

    ``points`` and ``stock_panel`` exist for test injection. The
    production path opens its own DB sessions.
    """
    ticker = (ticker or "").upper().strip()
    if today is None:
        today = date.today()
    db_ticker = ticker.replace(".NS", "").replace(".BO", "")

    # ── annual financials ─────────────────────────────────────────
    if points is None:
        from data_pipeline.db import Session as PipelineSession  # type: ignore
        db = None
        try:
            db = PipelineSession()
            points = _fetch_annual_points(db, db_ticker, max_years=12)
        except Exception as exc:
            logger.info("CAGR: financials fetch failed for %s: %s", ticker, exc)
            points = []
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    as_of_fy = points[0].fy if points else None

    if not points:
        # Still try stock — financials can be missing for newly listed
        # names while prices are fine. But profit/revenue/roe stay null.
        if stock_panel is None:
            stock_panel = _stock_cagr_panel(ticker, today)
        panel = _empty_panel(as_of_fy)
        panel["stock"] = {**stock_panel, "as_of_fy": as_of_fy}
        return panel

    revenue: dict[str, float | None] = {"as_of_fy": as_of_fy}
    profit: dict[str, float | None] = {"as_of_fy": as_of_fy}
    roe_avg: dict[str, float | None] = {"as_of_fy": as_of_fy}

    for w in _WINDOWS:
        key = f"{w}y"
        # Revenue CAGR
        if _coverage_ok(points, w, "revenue"):
            s, e, n = _window_endpoints(points, w, "revenue")
            revenue[key] = _cagr(s, e, n)
        else:
            revenue[key] = None
        # Profit CAGR
        if _coverage_ok(points, w, "pat"):
            s, e, n = _window_endpoints(points, w, "pat")
            profit[key] = _cagr(s, e, n)
        else:
            profit[key] = None
        # ROE average (not CAGR)
        roe_avg[key] = _window_avg(points, w, "roe")

    # ── stock CAGR ────────────────────────────────────────────────
    if stock_panel is None:
        stock_panel = _stock_cagr_panel(ticker, today)
    stock = {**stock_panel, "as_of_fy": as_of_fy}

    return {
        "revenue": revenue,
        "profit": profit,
        "roe_avg": roe_avg,
        "stock": stock,
    }
