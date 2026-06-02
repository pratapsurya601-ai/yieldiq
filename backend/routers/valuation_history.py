# backend/routers/valuation_history.py
# ═══════════════════════════════════════════════════════════════
# Phase 1 — Fair-Value History router.
#
# Thin HTTP boundary. All query + annotation logic lives in
# backend/services/analysis/valuation_history_service.py so the
# router stays the contract surface that Agent D's tests pin
# against. Never raises — the service layer returns the empty-shape
# on internal failure, preserving the stub's reachability guarantee.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter, Path

from backend.models.fair_value_history import FairValueHistoryResponse
from backend.services.analysis.valuation_history_service import (
    fetch_history_payload,
)


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
    return await fetch_history_payload(ticker)
