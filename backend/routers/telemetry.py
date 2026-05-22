# backend/routers/telemetry.py
# ═══════════════════════════════════════════════════════════════
# Lightweight client-side telemetry endpoints.
#
# Distinct from backend.routers.analytics (which is DuckDB SQL over
# Parquet for the analyst panel — same word, very different beast).
# This router is for funnel-style UX events from the PWA shell.
#
# Endpoints:
#   POST /api/v1/telemetry/pwa-event   -> {"ok": true}
#   GET  /api/v1/admin/pwa-funnel      -> aggregated funnel (admin only)
#
# POST has no auth (we want anonymous funnel data — pre-login installs
# count). It writes to stdout AND best-effort persists into the
# pwa_telemetry_events table (Day-101c, migration 050) so the admin
# dashboard has something to aggregate against. DB failures degrade
# silently because telemetry must never break the user flow.
#
# UA is truncated to 80 chars to keep lines compact and avoid logging
# fingerprintable PII. The remote IP is hashed with a server-side salt
# (env SALT_PWA_TELEMETRY) before storage — useful for dedup without
# persisting raw IPs.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


PwaEventName = Literal["prompted", "installed", "dismissed", "ios_hint_shown"]
_EVENT_NAMES: tuple[str, ...] = (
    "prompted",
    "installed",
    "dismissed",
    "ios_hint_shown",
)


class PwaEventPayload(BaseModel):
    event: PwaEventName
    ua: Optional[str] = None


def _hash_ip(remote_ip: Optional[str]) -> Optional[str]:
    """SHA256(salt || ip) for dedup. Returns None if no IP available."""
    if not remote_ip:
        return None
    salt = os.environ.get("SALT_PWA_TELEMETRY", "")
    return hashlib.sha256((salt + remote_ip).encode("utf-8")).hexdigest()


def _get_session():
    """Lazily acquire a pipeline SQLAlchemy session.

    Returns None when DATABASE_URL is not configured (local dev) or the
    import fails for any reason. Mirrors the pattern in
    backend.services.analysis_cache_service._get_session.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover - import failures are rare
        logger.warning("telemetry: pipeline db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:  # pragma: no cover - connection failures
        logger.warning("telemetry: session open failed: %s", exc)
        return None


def _persist_event(event: str, ua_truncated: str, ip_hash: Optional[str]) -> None:
    """Best-effort insert into pwa_telemetry_events.

    Never raises. The endpoint is fire-and-forget from sendBeacon — a
    transient DB blip must not 500 the client and break the funnel.
    """
    session = _get_session()
    if session is None:
        return
    try:
        from backend.models.pwa_telemetry_event import PwaTelemetryEvent

        row = PwaTelemetryEvent(
            event=event,
            ua_truncated=ua_truncated or None,
            ip_hash=ip_hash,
        )
        session.add(row)
        session.commit()
    except Exception as exc:
        logger.warning("telemetry: persist failed for %s: %s", event, exc)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


@router.post("/pwa-event")
async def pwa_event(payload: PwaEventPayload, request: Request):
    """Record one step of the PWA install funnel.

    Fire-and-forget from the client (sendBeacon). We acknowledge with a
    bare {"ok": true} so even slow networks don't hold the page on
    unload. Pydantic enforces the event whitelist; unknown values 422.
    """
    ua = (payload.ua or "")[:80]
    logger.info("pwa_event %s ua=%s", payload.event, ua)

    remote_ip = request.client.host if request.client else None
    _persist_event(payload.event, ua, _hash_ip(remote_ip))

    return {"ok": True}


# ── Admin dashboard endpoint ─────────────────────────────────────


def _require_admin_dep():
    """Lazy import of require_admin to avoid circular imports.

    backend.routers.admin pulls in many services; this telemetry
    router is intentionally small and imported early by main.py.
    """
    from backend.routers.admin import require_admin

    return require_admin


@admin_router.get("/pwa-funnel")
async def pwa_funnel(user: dict = Depends(_require_admin_dep())):
    """Aggregate the PWA install funnel over the last 7 days.

    Returns prompted → installed conversion rate, prompted → dismissed
    dismissal rate, totals across the four event names, and a daily
    breakdown for the chart.
    """
    window_days = 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    totals: dict[str, int] = {name: 0 for name in _EVENT_NAMES}
    daily: dict[str, dict[str, int]] = {}

    session = _get_session()
    if session is not None:
        try:
            from backend.models.pwa_telemetry_event import PwaTelemetryEvent
            from sqlalchemy import func

            rows = (
                session.query(
                    PwaTelemetryEvent.event,
                    func.date(PwaTelemetryEvent.created_at).label("d"),
                    func.count(PwaTelemetryEvent.id).label("c"),
                )
                .filter(PwaTelemetryEvent.created_at >= cutoff)
                .group_by(
                    PwaTelemetryEvent.event,
                    func.date(PwaTelemetryEvent.created_at),
                )
                .all()
            )
            for r in rows:
                event = r.event
                count = int(r.c or 0)
                if event in totals:
                    totals[event] += count
                date_key = (
                    r.d.isoformat() if hasattr(r.d, "isoformat") else str(r.d)
                )
                bucket = daily.setdefault(
                    date_key, {name: 0 for name in _EVENT_NAMES}
                )
                if event in bucket:
                    bucket[event] += count
        except Exception as exc:
            logger.warning("pwa_funnel: aggregation failed: %s", exc)
        finally:
            try:
                session.close()
            except Exception:
                pass

    prompted = totals["prompted"]
    installed = totals["installed"]
    dismissed = totals["dismissed"]
    conversion_rate = (installed / prompted) if prompted > 0 else 0.0
    dismissal_rate = (dismissed / prompted) if prompted > 0 else 0.0

    daily_breakdown = [
        {"date": d, **counts} for d, counts in sorted(daily.items())
    ]

    return {
        "window_days": window_days,
        "totals": totals,
        "conversion_rate": round(conversion_rate, 4),
        "dismissal_rate": round(dismissal_rate, 4),
        "daily_breakdown": daily_breakdown,
    }
