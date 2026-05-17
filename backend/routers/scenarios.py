"""Per-user saved DCF scenarios (Phase-2 of editable-assumptions).

Endpoints (all JWT-gated; POST additionally requires paid tier):
  * GET    /api/v1/scenarios?ticker=XYZ   List my scenarios (optionally filtered)
  * POST   /api/v1/scenarios              Save (insert-or-update) a scenario
  * DELETE /api/v1/scenarios/{id}         Delete one of my scenarios

Tier policy:
  * GET is open to all authenticated users (free tier just sees an
    empty list — keeps the UI gate-free on reads).
  * POST is paid-only via ``require_tier("pro")``. We use the same
    ``pro`` floor that the /recompute endpoint already enforces, so
    the gating story stays consistent: any user who can move the
    sliders can also save the result.
  * DELETE is open — letting a user clean up their own data is never
    something we want to gate on tier (would be hostile UX after a
    downgrade).

Storage trusts the service layer (saved_scenarios_service) — see
that module's docstring for the in-memory fallback + DB plumbing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user, require_tier
from backend.services import saved_scenarios_service as svc

logger = logging.getLogger("yieldiq.scenarios.router")

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


# ── Request / response models ────────────────────────────────────────

class SaveScenarioRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=svc.MAX_NAME_LEN)
    # Free-form JSON — kept loose on purpose so the frontend can ship
    # new sliders (beta, tax rate, projection_years) without forcing
    # a backend model bump. Validators on the recompute endpoint
    # already enforce sane ranges at compute time.
    assumptions: dict[str, Any]
    result: dict[str, Any]


class ScenarioOut(BaseModel):
    id: int
    ticker: str
    name: str
    assumptions: dict[str, Any]
    result: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ListScenariosResponse(BaseModel):
    scenarios: list[ScenarioOut]
    cap: int = svc.MAX_SCENARIOS_PER_USER


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/", response_model=ListScenariosResponse)
async def list_my_scenarios(
    ticker: Optional[str] = Query(default=None, max_length=32),
    user: dict = Depends(get_current_user),
):
    """List the calling user's saved scenarios. Optionally scope to
    one ticker — the common case for the analysis page sidebar.

    No tier gate on reads: free-tier users just see an empty list,
    which lets the frontend render the panel unconditionally without
    a tier-aware code path."""
    rows = svc.list_scenarios(user["user_id"], ticker=ticker)
    return {
        "scenarios": [_strip_user_id(r) for r in rows],
        "cap": svc.MAX_SCENARIOS_PER_USER,
    }


@router.post("/", response_model=ScenarioOut)
async def save_my_scenario(
    body: SaveScenarioRequest,
    user: dict = Depends(require_tier("pro")),
):
    """Save (insert-or-update) a scenario for the calling user.

    Paid-tier only — gating mirrors the /analysis/{ticker}/recompute
    endpoint that produces the result we're storing. If the user
    saves with a name that already exists for this (user, ticker),
    we overwrite — that's the user's mental model of "save".
    """
    try:
        row = svc.save_scenario(
            user_id=user["user_id"],
            ticker=body.ticker,
            name=body.name,
            assumptions=body.assumptions,
            result=body.result,
        )
    except svc.ScenarioCapReached as e:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "scenario_cap_reached",
                "cap": e.cap,
                "current": e.current,
                "message": (
                    f"You've reached the {e.cap}-scenario cap. "
                    "Delete an old one to save a new one."
                ),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _strip_user_id(row)


@router.delete("/{scenario_id}")
async def delete_my_scenario(
    scenario_id: int,
    user: dict = Depends(get_current_user),
):
    """Hard-delete one of my scenarios. Idempotent: a second DELETE
    for the same id returns 404."""
    ok = svc.delete_scenario(user["user_id"], scenario_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Scenario not found.",
        )
    return {"ok": True}


# ── Helpers ──────────────────────────────────────────────────────────

def _strip_user_id(row: dict) -> dict:
    """Service layer returns user_id; never echo it back to the client."""
    return {k: v for k, v in row.items() if k != "user_id"}
