# backend/routers/incidents.py
# ═══════════════════════════════════════════════════════════════
# Public incident log HTTP API.
#
# Backs the /status page incident table and the dismissible
# recent-incident banner that renders on every marketing/app page.
#
# Endpoints (no auth):
#   GET /api/v1/public/incidents -> {incidents: [...], current_status: str}
#
# Reads from the `incidents` table created in
# data_pipeline/migrations/027_incidents.sql. Sector-isolated, no
# CACHE_VERSION coupling, no analysis-math touch — purely a
# transparency surface.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text as _sql_text

logger = logging.getLogger("yieldiq.incidents")

router = APIRouter(prefix="/api/v1/public", tags=["public", "incidents"])


def _get_db_session():
    """Borrow the pipeline session helper used by other public routes."""
    try:
        from backend.services.analysis_service import _get_pipeline_session
        return _get_pipeline_session()
    except Exception:  # pragma: no cover - defensive
        return None


def _safe_close(session) -> None:
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy Row (or RowMapping) to a JSON-safe dict.

    Timestamps are emitted as ISO-8601 with timezone so the frontend
    can render them in the visitor's local zone without guessing.
    """
    m = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    for k in ("started_at", "ended_at", "created_at", "updated_at"):
        v = m.get(k)
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            m[k] = v.isoformat()
    return m


def _compute_current_status(incidents: list[dict[str, Any]]) -> str:
    """Derive overall status from the incident list.

    - any open incident (ended_at is None) with severity=major  -> "outage"
    - any open incident (ended_at is None) otherwise            -> "degraded"
    - everything resolved                                       -> "operational"
    """
    open_incidents = [i for i in incidents if i.get("ended_at") in (None, "")]
    if not open_incidents:
        return "operational"
    if any(i.get("severity") == "major" for i in open_incidents):
        return "outage"
    return "degraded"


@router.get("/incidents")
async def get_public_incidents():
    """List incidents from the last 90 days plus the current status.

    Cached at the edge for 5 minutes so a launch-day traffic spike
    does not hammer the DB. Frontend revalidates on its own cadence.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    incidents: list[dict[str, Any]] = []
    db = _get_db_session()
    try:
        if db is None:
            logger.warning("incidents: no DB session available")
        else:
            rows = db.execute(
                _sql_text(
                    "SELECT id, started_at, ended_at, severity, surface, "
                    "       title, description, resolution "
                    "FROM incidents "
                    "WHERE started_at >= :cutoff "
                    "ORDER BY started_at DESC"
                ),
                {"cutoff": cutoff},
            ).fetchall()
            incidents = [_row_to_dict(r) for r in rows]
    except Exception as exc:
        logger.warning("incidents: query failed: %s", exc)
        incidents = []
    finally:
        _safe_close(db)

    payload = {
        "incidents": incidents,
        "current_status": _compute_current_status(incidents),
    }

    # 5 min fresh, 30 min stale-while-revalidate.
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": "public, s-maxage=300, stale-while-revalidate=1800",
            "X-Source": "public_incidents_v1",
        },
    )
