"""Per-user page-view telemetry service.

Append-only INSERT path + cheap per-user SELECT. Used by the admin
``/api/v1/admin/user-activity/{email}`` endpoint to answer "did user
X view any analysis page after signup?".

Motivation (2026-05-16): 5 organic signups in 16 days, 0 watchlist
or portfolio writes. We had no way to distinguish "signed up and
bounced" from "signed up, viewed 50 stocks, never clicked add".

Design constraints (deliberately narrow):
    * Never block the request path — callers use
      ``FastAPI BackgroundTasks`` so the INSERT happens after the
      response has been flushed.
    * Never record for anonymous users — would explode the table and
      contributes no activation signal.
    * No joins on the read path — single-table SELECT keyed by
      ``(user_email, viewed_at)`` index.
    * 30-day rolling retention via ``scripts/prune_page_views.py``
      (daily cron) — we never need older data for activation.

Schema lives in ``data_pipeline/migrations/027_user_page_views.sql``.
"""
from __future__ import annotations

import logging
from typing import Optional, Literal

logger = logging.getLogger("yieldiq.page_views")

PageKind = Literal[
    "analysis",
    "compare",
    "portfolio_analyze",
    "discover",
    "watchlist",
    "pulse",
    "sector",
    "methodology",
    "other",
]

_ALLOWED_KINDS: set[str] = {
    "analysis", "compare", "portfolio_analyze", "discover",
    "watchlist", "pulse", "sector", "methodology", "other",
}

# Cap field sizes so a hostile UA / referrer header can't bloat rows.
_MAX_PATH_LEN = 500
_MAX_UA_LEN = 500
_MAX_REFERRER_LEN = 500
_MAX_TICKER_LEN = 32


def _get_raw_cursor():
    """Yield a raw psycopg2 (conn, cursor) from the pipeline engine.

    Mirrors backend/services/notifications_service.py:_get_raw_cursor —
    same DATABASE_URL, same engine, same close discipline.
    """
    try:
        from data_pipeline.db import engine
    except Exception as exc:
        logger.warning("page_view_service: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    try:
        conn = engine.raw_connection()
        cur = conn.cursor()
        return conn, cur
    except Exception as exc:
        logger.warning("page_view_service: raw_connection failed: %s", exc)
        return None, None


def record_page_view(
    *,
    user_email: Optional[str],
    page_kind: str,
    ticker: Optional[str],
    path: str,
    user_agent: Optional[str] = None,
    referrer: Optional[str] = None,
) -> None:
    """Insert one page view. Designed for BackgroundTasks (fire-and-forget).

    Silently no-ops for anonymous users (``user_email`` falsy) — we
    never want to log anon traffic into this table.

    Never raises: telemetry must not break the request that scheduled
    it. All failure paths log + swallow.
    """
    if not user_email:
        return  # anonymous — skip
    if page_kind not in _ALLOWED_KINDS:
        # Reject unknown kinds rather than insert garbage that fails
        # the CHECK constraint. Log so we notice if a caller passes a
        # typo.
        logger.warning("page_view: rejecting unknown page_kind=%r", page_kind)
        page_kind = "other"

    # Truncate to keep rows small / harden against header bloat.
    path = (path or "")[:_MAX_PATH_LEN]
    if not path:
        return  # nothing to record
    ticker = ((ticker or "") or None)
    if ticker:
        ticker = ticker[:_MAX_TICKER_LEN]
    user_agent = (user_agent or "")[:_MAX_UA_LEN] or None
    referrer = (referrer or "")[:_MAX_REFERRER_LEN] or None

    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        # DB unavailable — drop silently. Telemetry is best-effort.
        return
    try:
        cur.execute(
            """
            INSERT INTO user_page_views
                (user_email, page_kind, ticker, path, user_agent, referrer)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_email, page_kind, ticker, path, user_agent, referrer),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # Don't propagate — telemetry must never break the caller.
        logger.exception(
            "page_view_service.record_page_view failed (email=%s kind=%s)",
            user_email, page_kind,
        )
    finally:
        try:
            cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass


def recent_views_by_user(user_email: str, days: int = 30) -> list[dict]:
    """Return one user's recent page views, newest first.

    ``days`` is clamped to [1, 30] — the retention window is 30d, so
    asking for more returns no extra rows.
    """
    if not user_email:
        return []
    days = max(1, min(int(days or 30), 30))
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return []
    try:
        cur.execute(
            """
            SELECT id, user_email, page_kind, ticker, path,
                   viewed_at, user_agent, referrer
              FROM user_page_views
             WHERE user_email = %s
               AND viewed_at > now() - (%s || ' days')::interval
             ORDER BY viewed_at DESC
             LIMIT 1000
            """,
            (user_email, str(days)),
        )
        rows = cur.fetchall() or []
        out: list[dict] = []
        for r in rows:
            (id_, email, kind, tkr, p, viewed, ua, ref) = r
            out.append({
                "id": int(id_),
                "user_email": email,
                "page_kind": kind,
                "ticker": tkr,
                "path": p,
                "viewed_at": viewed.isoformat() if viewed else None,
                "user_agent": ua,
                "referrer": ref,
            })
        return out
    except Exception:
        logger.exception(
            "page_view_service.recent_views_by_user failed (email=%s)", user_email,
        )
        return []
    finally:
        try:
            cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass


def activity_summary(user_email: str, days: int = 30) -> dict:
    """Aggregate a user's views into per-kind + per-ticker counts.

    Returned shape (admin-only consumer):
        {
          "user_email": str,
          "days": int,
          "total_views": int,
          "by_page_kind": {kind: count},
          "by_ticker":    {ticker: count},  -- nulls/blanks dropped
          "first_view":   isoformat | None,
          "last_view":    isoformat | None,
          "views":        [ ... raw rows, newest first ... ],
        }

    Pure aggregation in Python over ``recent_views_by_user`` — keeps the
    read path single-query and avoids putting GROUP BY logic in SQL we'd
    have to maintain in two places.
    """
    rows = recent_views_by_user(user_email, days=days)
    by_kind: dict[str, int] = {}
    by_ticker: dict[str, int] = {}
    first_view: Optional[str] = None
    last_view: Optional[str] = None
    for r in rows:
        k = r.get("page_kind") or "other"
        by_kind[k] = by_kind.get(k, 0) + 1
        t = (r.get("ticker") or "").strip()
        if t:
            by_ticker[t] = by_ticker.get(t, 0) + 1
        v = r.get("viewed_at")
        if v:
            if last_view is None or v > last_view:
                last_view = v
            if first_view is None or v < first_view:
                first_view = v
    return {
        "user_email": user_email,
        "days": max(1, min(int(days or 30), 30)),
        "total_views": len(rows),
        "by_page_kind": by_kind,
        "by_ticker": by_ticker,
        "first_view": first_view,
        "last_view": last_view,
        "views": rows,
    }


def prune_older_than(days: int = 30) -> int:
    """Delete rows older than ``days``. Returns rows removed.

    Called by ``scripts/prune_page_views.py`` daily. Safe to invoke
    ad-hoc from a Python shell.
    """
    days = max(1, int(days or 30))
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return 0
    try:
        cur.execute(
            "DELETE FROM user_page_views "
            "WHERE viewed_at < now() - (%s || ' days')::interval",
            (str(days),),
        )
        deleted = cur.rowcount or 0
        conn.commit()
        return int(deleted)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("page_view_service.prune_older_than failed")
        return 0
    finally:
        try:
            cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass
