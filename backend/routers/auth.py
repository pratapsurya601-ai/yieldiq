# backend/routers/auth.py
from __future__ import annotations
import logging
import threading
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict, Field
from backend.models.requests import LoginRequest, RegisterRequest
from backend.models.responses import TokenResponse, UserResponse
from backend.middleware.auth import (
    get_current_user, login_user_and_get_token, register_user_and_get_token,
    is_superuser,
)
from backend.middleware.rate_limit import rate_limiter

_log = logging.getLogger("yieldiq.auth.onboarding")

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


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class UpdatePasswordRequest(BaseModel):
    access_token: str = Field(min_length=10, max_length=4096)
    new_password: str = Field(min_length=6, max_length=200)


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Trigger a Supabase password-reset email.

    Always returns 200 regardless of whether the email is registered
    (anti-enumeration: don't leak account existence to random probes).
    Supabase sends the recovery email via whatever SMTP is configured
    in Project Settings → Auth → SMTP; for YieldIQ that's the SendGrid
    relay configured 2026-04-22.
    """
    email = req.email.strip().lower()
    if not email or "@" not in email:
        return {"ok": True}
    try:
        from db.supabase_client import get_client
        client = get_client()
        if client is None:
            # Silent — anti-enumeration. Operators see the issue in logs.
            logging.getLogger("yieldiq.auth").warning(
                "forgot-password: Supabase client unavailable"
            )
            return {"ok": True}
        # redirect_to MUST be an allowlisted URL in Supabase Auth →
        # URL Configuration → Redirect URLs. This points the reset link
        # at our in-brand /auth/reset-password page (not Supabase's
        # hosted recovery UI). The page reads access_token from the URL
        # hash and calls /auth/update-password below.
        try:
            client.auth.reset_password_for_email(
                email,
                options={"redirect_to": "https://www.yieldiq.in/auth/reset-password"},
            )
        except TypeError:
            # Older Supabase SDKs use positional args / different kwargs.
            client.auth.reset_password_for_email(email)
    except Exception as exc:
        # Don't expose the failure to the caller (anti-enumeration) but
        # log it so we can see it in Sentry when the config breaks.
        logging.getLogger("yieldiq.auth").warning(
            "forgot-password failed for %s: %s", email, exc
        )
    return {"ok": True}


@router.post("/update-password")
async def update_password(req: UpdatePasswordRequest):
    """Set a new password using a Supabase recovery access token.

    The reset flow:
      1. User clicks email link → lands on /auth/reset-password with
         #access_token=... in the URL hash (Supabase's convention).
      2. Frontend reads the token and POSTs here with the token + new
         password.
      3. We call Supabase's REST endpoint to update the user's password,
         authenticating as that user via the recovery token.

    Uses direct REST call instead of the Python SDK because the SDK's
    session-mutation pattern (set_session then update_user) is flaky
    in a stateless FastAPI process.
    """
    import os
    import requests
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not supabase_url or not anon_key:
        raise HTTPException(
            status_code=503,
            detail="Auth backend unavailable — please try again shortly.",
        )
    try:
        resp = requests.put(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {req.access_token}",
                "apikey": anon_key,
                "Content-Type": "application/json",
            },
            json={"password": req.new_password},
            timeout=15,
        )
    except requests.RequestException as exc:
        logging.getLogger("yieldiq.auth").warning(
            "update-password: network error: %s", exc
        )
        raise HTTPException(status_code=503, detail="Network error, please retry.")

    if resp.status_code == 200:
        return {"ok": True}

    # Map Supabase's error shapes to user-friendly messages without
    # leaking internals. The most common failures here are:
    #   401 — token expired or already consumed (reset links are single-use)
    #   422 — password fails Supabase's strength requirements
    try:
        body = resp.json()
        msg = body.get("msg") or body.get("message") or body.get("error_description") or ""
    except Exception:
        msg = resp.text[:200] if resp.text else ""

    if resp.status_code in (401, 403):
        raise HTTPException(
            status_code=400,
            detail="This reset link has expired or already been used. Request a new one.",
        )
    if resp.status_code == 422:
        raise HTTPException(
            status_code=400,
            detail=msg or "Password doesn't meet requirements. Try at least 8 characters.",
        )
    logging.getLogger("yieldiq.auth").warning(
        "update-password: Supabase returned %s: %s", resp.status_code, msg
    )
    raise HTTPException(
        status_code=400,
        detail="Couldn't set password. Request a new reset link.",
    )


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


# ═════════════════════════════════════════════════════════════════
# Onboarding state — cross-device source of truth
#
# Before this endpoint existed, the frontend used localStorage
# (yieldiq-settings.state.onboardingComplete) as the sole source of
# truth. That broke for anyone logging in on a 2nd browser/device/
# incognito session — they'd see the onboarding wizard AGAIN because
# localStorage is per-device. The backing table user_onboarding
# already existed in Supabase (see db/schema.sql:114), but nothing
# on the FastAPI side read/wrote to it.
#
# Endpoints here back the localStorage cache with the real DB so
# onboarding completion persists across devices. localStorage stays
# as a fast-path cache to prevent flash-of-wizard on every page load.
# ═════════════════════════════════════════════════════════════════


class OnboardingStatusResponse(BaseModel):
    completed: bool
    last_step: int = 1
    completed_at: Optional[str] = None
    source: str  # "db" | "default" — helps the frontend know to trust this vs fall back


class CompleteOnboardingRequest(BaseModel):
    last_step: Optional[int] = Field(default=None, ge=1)
    # interests / firstStock come from the signup wizard; we don't persist them
    # server-side today but accept them for forward compatibility so a future
    # preference sync doesn't need a new endpoint.
    interests: Optional[list[str]] = None
    first_stock: Optional[str] = Field(default=None, alias="firstStock")

    model_config = ConfigDict(populate_by_name=True)


class CompleteOnboardingResponse(BaseModel):
    completed: bool
    completed_at: str


def _supabase_enabled() -> bool:
    """True when SUPABASE_URL + a key are set — otherwise every onboarding
    call is a no-op (frontend falls back to localStorage)."""
    import os
    return bool(
        os.environ.get("SUPABASE_URL")
        and (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY"))
    )


@router.get("/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(user: dict = Depends(get_current_user)):
    """Return this user's onboarding completion state from the DB.

    On any backend failure we return `completed=false, source="default"` so
    the frontend can fall back to localStorage. We never 500 here — the
    login flow MUST NOT hard-fail if the onboarding table is down.
    """
    email = (user.get("email") or "").strip().lower()
    if not email:
        return OnboardingStatusResponse(completed=False, source="default")

    if not _supabase_enabled():
        # No Supabase configured (e.g. local dev against SQLite) — fall back
        # silently so frontend uses localStorage cache.
        return OnboardingStatusResponse(completed=False, source="default")

    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        result = (
            client.table("user_onboarding")
            .select("onboarding_completed, last_step, completed_at")
            .eq("user_email", email)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return OnboardingStatusResponse(completed=False, source="db")
        row = rows[0]
        return OnboardingStatusResponse(
            completed=bool(row.get("onboarding_completed")),
            last_step=int(row.get("last_step") or 1),
            completed_at=row.get("completed_at"),
            source="db",
        )
    except Exception as exc:
        # Soft-fail — frontend treats source="default" as "trust localStorage".
        _log.warning("onboarding-status lookup failed for %s: %s", email, exc)
        return OnboardingStatusResponse(completed=False, source="default")


@router.post("/complete-onboarding", response_model=CompleteOnboardingResponse)
async def complete_onboarding(
    body: CompleteOnboardingRequest,
    user: dict = Depends(get_current_user),
):
    """Mark onboarding as complete for this user.

    Idempotent — calling twice is fine; the completed_at timestamp is
    preserved on first completion (we only set it when flipping false → true).
    """
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="No email on user")

    now_iso = datetime.now(timezone.utc).isoformat()

    if not _supabase_enabled():
        # No Supabase — nothing to persist server-side. Return "completed" so
        # the frontend still clears its own in-flight state; localStorage is
        # the source of truth in this env.
        return CompleteOnboardingResponse(completed=True, completed_at=now_iso)

    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()

        # Check whether the row exists + whether it was already completed
        existing = (
            client.table("user_onboarding")
            .select("onboarding_completed, completed_at")
            .eq("user_email", email)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        already_completed_at = None
        if rows and rows[0].get("onboarding_completed") and rows[0].get("completed_at"):
            already_completed_at = rows[0]["completed_at"]

        payload: dict = {
            "user_email": email,
            "onboarding_completed": True,
            "last_step": body.last_step or 3,
            "completed_at": already_completed_at or now_iso,
        }

        # Supabase upsert on the unique user_email key.
        client.table("user_onboarding").upsert(
            payload, on_conflict="user_email"
        ).execute()

        return CompleteOnboardingResponse(
            completed=True,
            completed_at=already_completed_at or now_iso,
        )
    except Exception as exc:
        _log.warning("complete-onboarding upsert failed for %s: %s", email, exc)
        # Don't 500 — the user already completed the wizard client-side;
        # localStorage will carry them through, and next login will retry.
        return CompleteOnboardingResponse(completed=True, completed_at=now_iso)
