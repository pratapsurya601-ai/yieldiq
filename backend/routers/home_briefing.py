# backend/routers/home_briefing.py
# ═══════════════════════════════════════════════════════════════
# Morning Briefing endpoint — feeds the /home hero on the
# logged-in dashboard.
#
# GET /api/v1/home/morning-briefing
#   → 200 with the composed briefing payload (see
#     morning_briefing_service.build_morning_briefing for the
#     wire shape).
#
# Auth: requires a valid JWT. Cache is pinned to user_id so the
# response NEVER bleeds across users — see the service module for
# the 5-minute TTL rationale.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import sys
import os
from pathlib import Path

from fastapi import APIRouter, Depends

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.middleware.auth import get_current_user
from backend.services.morning_briefing_service import build_morning_briefing

logger = logging.getLogger("yieldiq.home_briefing")

router = APIRouter(prefix="/api/v1/home", tags=["home"])


@router.get("/morning-briefing")
async def get_morning_briefing(user: dict = Depends(get_current_user)) -> dict:
    """Compose and return the user's Morning Briefing payload.

    Server-side cached 5 min per user_id. Composer is deterministic —
    no LLM, no opinion verbs, SEBI-clean prose.
    """
    return build_morning_briefing(user)
