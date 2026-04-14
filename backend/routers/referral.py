# backend/routers/referral.py
# Referral system — each user gets a code, referrers earn bonus analyses.
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.referral")

router = APIRouter(prefix="/api/v1/referral", tags=["referral"])

# In-memory referral store (production would use Supabase users_meta)
# Structure: { user_id: { referral_code, referred_by, referral_count, bonus_analyses } }
_referral_store: dict[str, dict] = {}


def _get_referral_code(user_id: str) -> str:
    """Generate referral code from first 8 chars of user_id."""
    return user_id.replace("-", "")[:8].lower()


def _ensure_user(user_id: str) -> dict:
    """Ensure user has a referral record."""
    if user_id not in _referral_store:
        _referral_store[user_id] = {
            "referral_code": _get_referral_code(user_id),
            "referred_by": None,
            "referral_count": 0,
            "bonus_analyses": 0,
        }
    return _referral_store[user_id]


def _find_user_by_code(code: str) -> str | None:
    """Find user_id by referral code."""
    for uid, data in _referral_store.items():
        if data["referral_code"] == code.lower():
            return uid
    # Code might belong to a user not yet in store — try matching prefix
    return None


class ApplyReferralRequest(BaseModel):
    referral_code: str


@router.get("/code")
async def get_referral_code(user: dict = Depends(get_current_user)):
    """Get current user's referral code and shareable link."""
    record = _ensure_user(user["user_id"])
    return {
        "referral_code": record["referral_code"],
        "referral_link": f"https://yieldiq.in/?ref={record['referral_code']}",
    }


@router.get("/stats")
async def get_referral_stats(user: dict = Depends(get_current_user)):
    """Get referral statistics for current user."""
    record = _ensure_user(user["user_id"])
    return {
        "referral_code": record["referral_code"],
        "referral_count": record["referral_count"],
        "bonus_analyses": record["bonus_analyses"],
        "referred_by": record["referred_by"],
    }


@router.post("/apply")
async def apply_referral(req: ApplyReferralRequest, user: dict = Depends(get_current_user)):
    """Apply a referral code during signup. Gives referrer +5 bonus analyses."""
    code = req.referral_code.strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Referral code is required")

    record = _ensure_user(user["user_id"])

    # Don't allow self-referral
    if record["referral_code"] == code:
        raise HTTPException(status_code=400, detail="Cannot refer yourself")

    # Don't allow double referral
    if record["referred_by"]:
        raise HTTPException(status_code=400, detail="Already used a referral code")

    # Find the referrer — search existing store or try to match
    referrer_id = _find_user_by_code(code)
    if not referrer_id:
        # The referrer may not have called /code yet — create a placeholder
        # In production, this would query Supabase by user_id prefix
        raise HTTPException(status_code=404, detail="Invalid referral code")

    # Apply referral
    record["referred_by"] = code
    referrer = _ensure_user(referrer_id)
    referrer["referral_count"] += 1
    referrer["bonus_analyses"] += 5

    logger.info(f"Referral applied: {user['user_id']} referred by {referrer_id} (code={code})")

    return {
        "ok": True,
        "message": "Referral applied! Your friend earned 5 bonus analyses.",
    }
