# backend/routers/telemetry.py
# ═══════════════════════════════════════════════════════════════
# Lightweight client-side telemetry endpoints.
#
# Distinct from backend.routers.analytics (which is DuckDB SQL over
# Parquet for the analyst panel — same word, very different beast).
# This router is for funnel-style UX events from the PWA shell.
#
# Endpoints:
#   POST /api/v1/telemetry/pwa-event  -> {"ok": true}
#
# No auth (we want anonymous funnel data — pre-login installs count).
# No DB writes; events land in stdout logs and are picked up by the
# log-shipping pipeline. UA is truncated to 80 chars to keep lines
# compact and avoid logging fingerprintable PII.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


PwaEventName = Literal["prompted", "installed", "dismissed", "ios_hint_shown"]


class PwaEventPayload(BaseModel):
    event: PwaEventName
    ua: Optional[str] = None


@router.post("/pwa-event")
async def pwa_event(payload: PwaEventPayload):
    """Record one step of the PWA install funnel.

    Fire-and-forget from the client (sendBeacon). We acknowledge with a
    bare {"ok": true} so even slow networks don't hold the page on
    unload. Pydantic enforces the event whitelist; unknown values 422.
    """
    ua = (payload.ua or "")[:80]
    logger.info("pwa_event %s ua=%s", payload.event, ua)
    return {"ok": True}
