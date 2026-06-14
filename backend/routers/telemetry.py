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
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

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


# ═══════════════════════════════════════════════════════════════
# Web Vitals (RUM) — real-user Core Web Vitals from the client beacon.
#   POST /api/v1/telemetry/web-vital   -> {"ok": true}   (public)
#   GET  /api/v1/admin/web-vitals      -> p75 per metric (admin only)
# CrUX has no field data for this domain yet (traffic too low), so this
# is our own real-user monitoring. Lab traces measure one machine; p75
# here is what real visitors actually experience.
# ═══════════════════════════════════════════════════════════════

WebVitalMetric = Literal["LCP", "CLS", "INP", "TTFB", "FCP"]
_WEB_VITAL_METRICS: tuple[str, ...] = ("LCP", "CLS", "INP", "TTFB", "FCP")
_RATINGS: frozenset = frozenset({"good", "needs-improvement", "poor"})

# Per-metric sane upper bounds — reject garbage / hostile payloads. CLS
# is a unitless score; the others are milliseconds.
_METRIC_MAX: dict = {
    "LCP": 600_000.0,
    "INP": 600_000.0,
    "TTFB": 600_000.0,
    "FCP": 600_000.0,
    "CLS": 100.0,
}


class WebVitalItem(BaseModel):
    name: WebVitalMetric
    value: float
    rating: Optional[str] = None


class WebVitalsBatch(BaseModel):
    # One beacon carries every metric collected for a single page view.
    metrics: List[WebVitalItem] = Field(default_factory=list)
    path: Optional[str] = None
    nav_type: Optional[str] = None
    conn: Optional[str] = None


def _device_from_ua(ua: Optional[str]) -> str:
    """Coarse mobile/desktop bucket from the UA. Not fingerprintable."""
    if ua and "Mobi" in ua:
        return "mobile"
    return "desktop"


def _sanitize_path(path: Optional[str]) -> Optional[str]:
    """Defence in depth: strip query/hash, cap length. The client sends
    a route TEMPLATE (/analysis/[ticker]); this guards against a raw URL
    slipping through."""
    if not path:
        return None
    p = path.split("?", 1)[0].split("#", 1)[0]
    return p[:120] or None


def _persist_web_vitals(
    batch: WebVitalsBatch, device: str, ip_hash: Optional[str]
) -> None:
    """Best-effort insert of each metric. Never raises — a fire-and-forget
    sendBeacon must never 500 the client. Out-of-range / NaN values drop."""
    session = _get_session()
    if session is None:
        return
    try:
        from backend.models.web_vital_event import WebVitalEvent

        path = _sanitize_path(batch.path)
        nav_type = (batch.nav_type or None)
        conn = (batch.conn or None)
        if nav_type:
            nav_type = nav_type[:24]
        if conn:
            conn = conn[:24]

        added = 0
        for item in batch.metrics[:10]:  # cap items per beacon
            if item.name not in _WEB_VITAL_METRICS:
                continue
            v = float(item.value)
            if v != v or v < 0 or v > _METRIC_MAX.get(item.name, 600_000.0):
                continue  # NaN / negative / out-of-range -> skip
            # Derive the good/needs/poor band from the value using the same
            # p75 thresholds the admin summary uses (single source of truth).
            # A client-supplied rating, if any, is honoured when valid.
            rating = (
                item.rating
                if item.rating in _RATINGS
                else _cwv_band(item.name, v)
            )
            session.add(
                WebVitalEvent(
                    metric=item.name,
                    value=v,
                    rating=rating,
                    path=path,
                    nav_type=nav_type,
                    conn_type=conn,
                    device=device,
                    ip_hash=ip_hash,
                )
            )
            added += 1
        if added:
            session.commit()
    except Exception as exc:
        logger.warning("web_vitals: persist failed: %s", exc)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        try:
            session.close()
        except Exception:
            pass


@router.post("/web-vital")
async def web_vital(batch: WebVitalsBatch, request: Request):
    """Ingest one page view's worth of real-user Core Web Vitals.

    Fire-and-forget from navigator.sendBeacon on page-hide. Returns a
    bare {"ok": true} so unload is never blocked. Garbage values are
    dropped in _persist_web_vitals; the endpoint never 500s.
    """
    ua = request.headers.get("user-agent", "")[:200]
    remote_ip = request.client.host if request.client else None
    _persist_web_vitals(batch, _device_from_ua(ua), _hash_ip(remote_ip))
    return {"ok": True}


# Google's Core-Web-Vitals "good" / "needs-improvement" p75 thresholds.
# CLS is unitless; the rest are milliseconds.
_CWV_GOOD: dict = {"LCP": 2500, "INP": 200, "CLS": 0.1, "FCP": 1800, "TTFB": 800}
_CWV_NEEDS: dict = {"LCP": 4000, "INP": 500, "CLS": 0.25, "FCP": 3000, "TTFB": 1800}


def _cwv_band(metric: str, p75: Optional[float]) -> Optional[str]:
    if p75 is None or metric not in _CWV_GOOD:
        return None
    if p75 <= _CWV_GOOD[metric]:
        return "good"
    if p75 <= _CWV_NEEDS[metric]:
        return "needs-improvement"
    return "poor"


@admin_router.get("/web-vitals")
async def web_vitals_summary(
    days: int = 28, user: dict = Depends(_require_admin_dep())
):
    """Real-user Core Web Vitals — p75 (the percentile Google grades on),
    p50 and sample count per metric over the window. If p75 lands in the
    "good" band, real visitors are having a fast experience regardless of
    what one lab machine measured.
    """
    window_days = max(1, min(int(days or 28), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    metrics: dict = {}
    session = _get_session()
    if session is not None:
        try:
            from backend.models.web_vital_event import WebVitalEvent
            from sqlalchemy import func

            p75 = func.percentile_cont(0.75).within_group(
                WebVitalEvent.value.asc()
            )
            p50 = func.percentile_cont(0.5).within_group(
                WebVitalEvent.value.asc()
            )
            rows = (
                session.query(
                    WebVitalEvent.metric,
                    p75.label("p75"),
                    p50.label("p50"),
                    func.count(WebVitalEvent.id).label("n"),
                )
                .filter(WebVitalEvent.created_at >= cutoff)
                .group_by(WebVitalEvent.metric)
                .all()
            )
            for r in rows:
                val = float(r.p75) if r.p75 is not None else None
                metrics[r.metric] = {
                    "p75": round(val, 3) if val is not None else None,
                    "p50": (
                        round(float(r.p50), 3) if r.p50 is not None else None
                    ),
                    "samples": int(r.n or 0),
                    "band": _cwv_band(r.metric, val),
                }
        except Exception as exc:
            logger.warning("web_vitals_summary: aggregation failed: %s", exc)
        finally:
            try:
                session.close()
            except Exception:
                pass

    return {
        "window_days": window_days,
        "metrics": metrics,
        "thresholds_good": _CWV_GOOD,
    }
