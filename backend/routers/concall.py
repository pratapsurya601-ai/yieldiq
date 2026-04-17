# backend/routers/concall.py
# ═══════════════════════════════════════════════════════════════
# Concall (earnings call) analysis endpoints — Pro tier required.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.services.concall_service import (
    analyze_transcript,
    save_user_concall,
    get_user_concalls,
)

logger = logging.getLogger("yieldiq.concall")

router = APIRouter(prefix="/api/v1/concall", tags=["concall"])


class AnalyzeRequest(BaseModel):
    transcript: str
    ticker: str = ""
    quarter: str = ""
    save: bool = True


def _require_paid_tier(user: dict) -> None:
    tier = user.get("tier", "free")
    if tier == "free":
        raise HTTPException(
            status_code=402,
            detail="Concall AI summaries require Pro plan (Rs 299/mo). Upgrade to unlock.",
        )


@router.post("/analyze")
async def analyze_concall(req: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """
    Analyze an earnings call transcript using AI.
    Pro/Analyst tier required.

    Returns structured insights:
        executive_summary, financial_highlights, forward_guidance,
        strategic_priorities, q_and_a_themes, concerns_raised, sentiment
    """
    _require_paid_tier(user)

    if not req.transcript or len(req.transcript.strip()) < 200:
        raise HTTPException(status_code=400, detail="Transcript must be at least 200 characters")

    try:
        result = analyze_transcript(req.transcript, req.ticker, req.quarter)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        # Save to user's library if requested
        if req.save and user.get("email"):
            try:
                save_user_concall(user["email"], result)
            except Exception as e:
                logger.warning(f"Save concall failed: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"analyze_concall failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Concall analysis failed")


@router.get("/library")
async def list_user_concalls(ticker: str = "", user: dict = Depends(get_current_user)):
    """List user's saved concall analyses (optionally filtered by ticker)."""
    _require_paid_tier(user)
    email = user.get("email", "")
    if not email:
        return {"items": []}
    items = get_user_concalls(email, ticker=ticker if ticker else None)
    return {"items": items, "count": len(items)}
