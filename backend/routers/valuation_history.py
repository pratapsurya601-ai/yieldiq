# backend/routers/valuation_history.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History router (Agent B / contract-first).
#
# Stub endpoint that returns the empty-shape so the route is reachable,
# tests can hit it, and the frontend can mock against the real
# Pydantic contract. Agent A wires the actual query off the
# fair_value_history table in the follow-up PR.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter, Path

from backend.models.fair_value_history import FairValueHistoryResponse


router = APIRouter(prefix="/api/valuation-history", tags=["valuation-history"])


@router.get("/{ticker}", response_model=FairValueHistoryResponse)
async def get_valuation_history(
    ticker: str = Path(..., min_length=1, max_length=32),
) -> FairValueHistoryResponse:
    """Return historical fair value points + material-move annotations.

    Production-faithful only: every point is the FV a user would have
    seen on that date. Empty series returns points_count=0 with an empty
    points list — the UI handles this with 'Fair value history starts
    <date>' copy.
    """
    # AGENT A WIRES THE QUERY HERE — see Phase 1 Agent A scope.
    # This stub returns empty so the route is reachable, tests can hit
    # it, and frontend can mock against the real shape.
    return FairValueHistoryResponse(
        ticker=ticker.upper(),
        points=[],
        annotations=[],
        starts_at=None,
        points_count=0,
        is_sparse=True,
    )
