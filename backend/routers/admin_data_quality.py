"""Admin endpoint for the data-quality validator dashboard (Phase A.2.1).

Surfaces the latest run-per-(table, populator) from
``data_quality_runs`` so the admin UI can render a single-screen
green/yellow/red health board. Read-only, admin-gated, 5-minute
in-process cache (the underlying query hits a partial index but the
dashboard is loaded on every admin tab focus and we don't want N
identical scans per minute).

Surface
-------
GET /api/v1/admin/data-quality/runs?limit_history=20
    → {
        "latest_per_table": [
            {
                "table": "daily_prices",
                "populator": "data_pipeline.sources.nse_bhavcopy",
                "overall_status": "green" | "yellow" | "red",
                "run_at": ISO-8601,
                "checks": [ {name, status, details, threshold}, ... ],
            },
            ...
        ],
        "history": [
            {"table": "...", "overall_status": "...", "run_at": "..."},
            ... (newest first, capped to limit_history)
        ],
        "summary": {"green": n, "yellow": n, "red": n, "total_tables": n},
        "cached": bool,            -- true on warm-cache hits
        "cache_age_seconds": int,
    }

The endpoint also surfaces an empty-state cleanly: if
data_quality_runs has zero rows (fresh DB), it returns
`latest_per_table=[]` with `summary.total_tables=0`.

Caching
-------
Process-local TTL cache (5 minutes). Sufficient for the admin
dashboard's traffic profile (~10 hits/hour from two admin users).
The cache key is constant — there's only one global view — so a
single (response, fetched_at) tuple per process is all we need.

Auth
----
Reuses ``backend.routers.admin.require_admin`` so the same allow-list
governs this endpoint as the rest of /api/v1/admin/*.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.routers.admin import require_admin

logger = logging.getLogger("yieldiq.admin.data_quality")

router = APIRouter(prefix="/api/v1/admin/data-quality", tags=["admin", "data-quality"])

_CACHE_TTL_SECONDS = 300
# Module-level cache. A single tuple is enough — this endpoint has one
# logical "view" so any second caller within the TTL gets the same payload.
_CACHE: dict[str, Any] = {"payload": None, "fetched_at": 0.0, "limit_history": -1}


def _fetch_from_db(limit_history: int) -> dict[str, Any]:
    """Pull latest-per-table + bounded history from data_quality_runs."""
    try:
        from data_pipeline.db import Session
    except Exception as exc:  # pragma: no cover
        logger.error("data_pipeline.db.Session import failed: %r", exc)
        raise HTTPException(status_code=500, detail="database not configured")

    from sqlalchemy import text

    sess = Session()
    try:
        # Latest run per (table, populator). DISTINCT ON keeps this O(log
        # n) given the (table_name, run_at DESC) index from migration 057.
        latest_rows = sess.execute(text(
            """
            SELECT DISTINCT ON (table_name, populator)
                   table_name, populator, overall_status, run_at, checks
              FROM data_quality_runs
             ORDER BY table_name, populator, run_at DESC
            """
        )).fetchall()

        history_rows = sess.execute(text(
            """
            SELECT table_name, populator, overall_status, run_at
              FROM data_quality_runs
             ORDER BY run_at DESC
             LIMIT :lim
            """
        ), {"lim": limit_history}).fetchall()
    finally:
        try:
            sess.close()
        except Exception:  # pragma: no cover
            logger.debug("sess.close raised", exc_info=True)

    latest_per_table = []
    for r in latest_rows:
        # checks may already be a dict (JSONB → psycopg2 returns dict)
        # or a str depending on driver; handle both.
        checks = r[4]
        if isinstance(checks, str):
            import json
            try:
                checks = json.loads(checks)
            except Exception:
                checks = {"raw": checks, "parse_error": True}
        latest_per_table.append({
            "table": r[0],
            "populator": r[1],
            "overall_status": r[2],
            "run_at": r[3].isoformat() if r[3] else None,
            "checks": checks,
        })

    summary = {"green": 0, "yellow": 0, "red": 0, "total_tables": len(latest_per_table)}
    for row in latest_per_table:
        s = row["overall_status"]
        if s in summary:
            summary[s] = summary.get(s, 0) + 1

    history = [
        {
            "table": r[0],
            "populator": r[1],
            "overall_status": r[2],
            "run_at": r[3].isoformat() if r[3] else None,
        }
        for r in history_rows
    ]

    return {
        "latest_per_table": latest_per_table,
        "history": history,
        "summary": summary,
    }


@router.get("/runs")
async def get_data_quality_runs(
    limit_history: int = Query(20, ge=1, le=200),
    force_refresh: bool = Query(False),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """Return latest run per (table, populator) + bounded history.

    `limit_history` caps the time-series tail (default 20, max 200).
    `force_refresh=true` bypasses the 5-minute process cache — use
    this if a cron just ran and you want to see the fresh row
    without waiting for cache expiry.
    """
    now = time.time()
    cached_age = now - _CACHE["fetched_at"] if _CACHE["payload"] else _CACHE_TTL_SECONDS + 1
    same_history_limit = _CACHE["limit_history"] == limit_history
    if (
        not force_refresh
        and _CACHE["payload"] is not None
        and cached_age < _CACHE_TTL_SECONDS
        and same_history_limit
    ):
        payload = dict(_CACHE["payload"])
        payload["cached"] = True
        payload["cache_age_seconds"] = int(cached_age)
        return payload

    fresh = _fetch_from_db(limit_history)
    _CACHE["payload"] = fresh
    _CACHE["fetched_at"] = now
    _CACHE["limit_history"] = limit_history
    out = dict(fresh)
    out["cached"] = False
    out["cache_age_seconds"] = 0
    return out


def _reset_cache_for_tests() -> None:
    """Helper for tests that need a fresh cache between cases."""
    _CACHE["payload"] = None
    _CACHE["fetched_at"] = 0.0
    _CACHE["limit_history"] = -1


__all__ = ["router", "_reset_cache_for_tests"]
