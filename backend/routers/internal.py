# backend/routers/internal.py
# Phase J — session-observation harness.
#
# Two endpoints:
#   POST /api/v1/internal/session-trace      (auth: any logged-in user)
#   GET  /api/v1/admin/session-traces        (auth: admin only)
#
# The POST endpoint accepts a batch of UI events captured by
# `frontend/src/lib/useSessionTrace.ts` and writes them into the
# `session_traces` table (migration 062). Anonymous visitors get 401 —
# the frontend hook short-circuits before sending, and the backend
# enforces auth as a defense in depth.
#
# The GET endpoint surfaces the most recent traces for admins to replay
# user sessions during launch-week debugging. Paginated and bounded.
#
# No PII, no form contents — the Pydantic schema accepts only the
# allowed event_type values and a small event_data blob. Validation
# happens before persistence.
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, conlist

from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.internal.session_trace")

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Maximum events per single POST batch. Mirrors the per-session cap in
# the frontend hook (100 events / session, 30s flush interval) — the
# hook itself rate-limits, but we enforce a hard server-side ceiling.
_MAX_EVENTS_PER_BATCH = 100

# Whitelisted event types — keep narrow. New types require a code
# change and a review.
EventType = Literal["page_view", "search_query", "button_click"]


class SessionTraceEvent(BaseModel):
    event_type: EventType
    event_data: Optional[dict[str, Any]] = Field(default=None)


class SessionTracePayload(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    # conlist enforces the per-batch ceiling at validation time.
    events: conlist(SessionTraceEvent, min_length=1, max_length=_MAX_EVENTS_PER_BATCH)  # type: ignore[valid-type]


def _get_session():
    """Lazily acquire a pipeline SQLAlchemy session.

    Mirrors the pattern used in backend.routers.telemetry — returns
    None if DATABASE_URL is not configured (local dev) or the import
    fails. Callers should check for None before using.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover - import failures are rare
        logger.warning("session_trace: pipeline db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:  # pragma: no cover - connection failures
        logger.warning("session_trace: session open failed: %s", exc)
        return None


@router.post("/session-trace")
async def session_trace(
    payload: SessionTracePayload,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist a batch of session events for the authenticated user.

    Anonymous callers get 401 from get_current_user before reaching
    this handler.
    """
    user_id = user.get("user_id")
    if not user_id:
        # Defensive: get_current_user should always set user_id.
        raise HTTPException(status_code=401, detail="Authentication required")

    session = _get_session()
    if session is None:
        # No DB configured — accept silently so the frontend hook does
        # not retry forever in local dev.
        logger.info(
            "session_trace: dropped %d events (no DB) user=%s session=%s",
            len(payload.events), user_id, payload.session_id,
        )
        return {"ok": True, "persisted": 0}

    persisted = 0
    try:
        from backend.models.session_trace import SessionTrace

        for evt in payload.events:
            row = SessionTrace(
                user_id=str(user_id),
                session_id=payload.session_id,
                event_type=evt.event_type,
                event_data=evt.event_data,
            )
            session.add(row)
            persisted += 1
        session.commit()
    except Exception as exc:
        logger.warning("session_trace: persist failed: %s", exc)
        try:
            session.rollback()
        except Exception:
            pass
        # Surface a generic 500 — the frontend hook will drop the
        # batch (events are advisory, not load-bearing).
        raise HTTPException(status_code=500, detail="trace persistence failed")
    finally:
        try:
            session.close()
        except Exception:
            pass

    return {"ok": True, "persisted": persisted}


def _require_admin_dep():
    """Lazy import of require_admin to avoid circular imports."""
    from backend.routers.admin import require_admin

    return require_admin


@admin_router.get("/session-traces")
async def list_session_traces(
    since: Optional[datetime] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(_require_admin_dep()),
) -> dict[str, Any]:
    """Return the most recent session traces for admin replay.

    Newest first. Bounded paginated query — admin tooling only, but
    we still cap `limit` at 1000 to keep responses reasonable.
    """
    session = _get_session()
    if session is None:
        return {"traces": [], "limit": limit, "offset": offset, "since": None}

    try:
        from backend.models.session_trace import SessionTrace

        q = session.query(SessionTrace)
        if since is not None:
            # Normalise to UTC tz-aware for safety against naive inputs.
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            q = q.filter(SessionTrace.created_at >= since)

        rows = (
            q.order_by(SessionTrace.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        traces = [
            {
                "id": int(r.id),
                "user_id": r.user_id,
                "session_id": r.session_id,
                "event_type": r.event_type,
                "event_data": r.event_data,
                "created_at": (
                    r.created_at.isoformat()
                    if r.created_at is not None
                    else None
                ),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("session_trace: list failed: %s", exc)
        raise HTTPException(status_code=500, detail="trace query failed")
    finally:
        try:
            session.close()
        except Exception:
            pass

    return {
        "traces": traces,
        "limit": limit,
        "offset": offset,
        "since": since.isoformat() if since else None,
    }
