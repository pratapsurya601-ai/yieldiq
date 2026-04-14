# backend/routers/auth.py
from __future__ import annotations
import threading
from fastapi import APIRouter, HTTPException, Depends
from backend.models.requests import LoginRequest, RegisterRequest
from backend.models.responses import TokenResponse, UserResponse
from backend.middleware.auth import (
    get_current_user, login_user_and_get_token, register_user_and_get_token,
)
from backend.middleware.rate_limit import rate_limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate user and return JWT token."""
    result = login_user_and_get_token(req.email, req.password)
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error", "Invalid credentials"))
    used, limit = rate_limiter.get_usage(result["user_id"], result["tier"])
    return TokenResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier=result["tier"],
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

    return TokenResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier="free",
        analyses_today=0,
        analysis_limit=5,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info."""
    used, limit = rate_limiter.get_usage(user["user_id"], user["tier"])
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        tier=user["tier"],
        analyses_today=used,
        analysis_limit=limit,
    )
