# backend/routers/auth.py
from __future__ import annotations
import threading
from fastapi import APIRouter, HTTPException, Depends
from backend.models.requests import LoginRequest, RegisterRequest
from backend.models.responses import TokenResponse, UserResponse
from backend.middleware.auth import (
    get_current_user, login_user_and_get_token, register_user_and_get_token,
    is_superuser,
)
from backend.middleware.rate_limit import rate_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate user and return JWT token."""
    result = login_user_and_get_token(req.email, req.password)
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error", "Invalid credentials"))

    # Superuser promotion — if email is in SUPERUSER_EMAILS env, present
    # them as tier="analyst" with unlimited quota. (The DB row can stay
    # as free; the bypass is purely response-side so it's easy to revoke
    # by just editing the env var.)
    _effective_tier = result["tier"]
    _effective_limit = None
    if is_superuser({"email": result["email"]}):
        _effective_tier = "analyst"
        _effective_limit = 999999

    used, limit = rate_limiter.get_usage(result["user_id"], _effective_tier)
    if _effective_limit is not None:
        limit = _effective_limit
    return TokenResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier=_effective_tier,
        analyses_today=used,
        analysis_limit=limit,
    )


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    """Register new user and return JWT token."""
    result = register_user_and_get_token(req.email, req.password)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Registration failed"))

    # Send welcome email in background (don't block signup response)
    try:
        from backend.services.email_service import send_welcome_email
        threading.Thread(
            target=send_welcome_email,
            args=(req.email,),
            daemon=True,
        ).start()
    except Exception:
        pass  # Email failure should never block registration

    # Apply referral code if provided
    if req.referral_code:
        try:
            from backend.routers.referral import _ensure_user, _find_user_by_code
            new_user_record = _ensure_user(result["user_id"])
            code = req.referral_code.strip().lower()
            referrer_id = _find_user_by_code(code)
            if referrer_id and referrer_id != result["user_id"]:
                new_user_record["referred_by"] = code
                referrer = _ensure_user(referrer_id)
                referrer["referral_count"] += 1
                referrer["bonus_analyses"] += 5
        except Exception:
            pass  # Referral failure should never block registration

    return TokenResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier="free",
        analyses_today=0,
        analysis_limit=5,
    )


@router.get("/debug")
async def debug_auth(user: dict = Depends(get_current_user)):
    """Temporary diagnostic — shows what the server sees for superuser
    bypass. Remove once the tier flip is confirmed working."""
    from backend.middleware.auth import SUPERUSER_EMAILS, is_superuser
    return {
        "user_email_from_jwt": user.get("email"),
        "user_tier_from_jwt": user.get("tier"),
        "superuser_emails_loaded": sorted(SUPERUSER_EMAILS),
        "is_superuser_result": is_superuser(user),
    }


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info."""
    _effective_tier = user["tier"]
    _limit_override = None
    if is_superuser(user):
        _effective_tier = "analyst"
        _limit_override = 999999
    used, limit = rate_limiter.get_usage(user["user_id"], _effective_tier)
    if _limit_override is not None:
        limit = _limit_override
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        tier=_effective_tier,
        analyses_today=used,
        analysis_limit=limit,
    )
