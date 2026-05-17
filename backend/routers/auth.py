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
    is_superuser, google_oauth_login_or_register, build_google_oauth_url,
    supabase_session_login_or_register,
)
from backend.middleware.rate_limit import rate_limiter, clamped_used
from backend.services.feature_flags import list_enabled_for
from backend.services import verification_service as _verify_svc


def _safe_is_verified(user_id: str, email: str | None) -> bool:
    """Wrapper that never raises — used in the auth response builders
    so a broken verification lookup can't break login. Defaults True
    (fail-open) for parity with require_email_verified."""
    try:
        return _verify_svc.is_email_verified(user_id, email)
    except Exception:
        return True

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
    # Display clamp — see clamped_used() docstring. Without this, a free
    # user whose DB row reads count=14 (e.g. tier was pro yesterday)
    # would log in and see "14/5 today" in the nav.
    used = clamped_used(used, limit)
    # Pull editable display_name + remaining-edits from Supabase user_metadata
    # so the frontend can render the personalised greeting on first paint.
    # Soft-fails to (None, MAX) — never blocks login.
    try:
        from backend.routers.account import get_display_name_state
        _dn, _dn_remaining = get_display_name_state(result["user_id"])
    except Exception:
        _dn, _dn_remaining = None, 3
    return TokenResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier=_effective_tier,
        analyses_today=used,
        analysis_limit=limit,
        display_name=_dn,
        display_name_edits_remaining=_dn_remaining,
        feature_flags=list_enabled_for(result["user_id"], _effective_tier),
        email_verified=_safe_is_verified(result["user_id"], result["email"]),
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
        display_name=None,
        display_name_edits_remaining=3,
        feature_flags=list_enabled_for(result["user_id"], "free"),
        # New email/password signups land unverified — see
        # register_user_and_get_token, which seeds users_meta with
        # email_verified=false and fires the verification email.
        email_verified=False,
    )


# ═════════════════════════════════════════════════════════════════
# Google OAuth (feat/google-oauth-signup)
#
# Two endpoints back the "Continue with Google" button on
# /auth/signup and /auth/login:
#
#   GET  /api/v1/auth/google/url     → returns the Supabase-hosted
#                                       Google OAuth consent URL
#   POST /api/v1/auth/google         → exchanges a verified Google
#                                       ID token for a YieldIQ JWT
#
# The actual Google client secret lives ONLY in the Supabase project
# config — we never see it. See PR body for the operator checklist.
# ═════════════════════════════════════════════════════════════════


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=10, max_length=8192)
    # Optional referral pass-through for new-user signups.
    referral_code: Optional[str] = Field(default=None, max_length=64)


class SupabaseSessionLoginRequest(BaseModel):
    """New OAuth shape: Supabase's session JWT (not Google's id_token).

    Frontend extracts this from the /auth/callback URL hash. See
    backend.middleware.auth.verify_supabase_session_token for why this
    replaces the old id_token path.
    """
    access_token: str = Field(min_length=10, max_length=8192)
    referral_code: Optional[str] = Field(default=None, max_length=64)


class GoogleAuthResponse(TokenResponse):
    is_new_user: bool = False


def _finalise_oauth_login(result: dict, referral_code: Optional[str]) -> GoogleAuthResponse:
    """Build the GoogleAuthResponse + fire new-user side effects.

    Shared by /auth/google (deprecated) and /auth/supabase so the two
    endpoints stay byte-identical from the frontend's perspective —
    same response shape, same referral handling, same superuser promotion.
    """
    is_new = bool(result.get("is_new_user"))

    if is_new:
        try:
            from backend.services.email_service import send_welcome_email
            threading.Thread(
                target=send_welcome_email,
                args=(result["email"],),
                daemon=True,
            ).start()
        except Exception:
            pass
        if referral_code:
            try:
                from backend.routers.referral import _ensure_user, _find_user_by_code
                new_user_record = _ensure_user(result["user_id"])
                code = referral_code.strip().lower()
                referrer_id = _find_user_by_code(code)
                if referrer_id and referrer_id != result["user_id"]:
                    new_user_record["referred_by"] = code
                    referrer = _ensure_user(referrer_id)
                    referrer["referral_count"] += 1
                    referrer["bonus_analyses"] += 5
            except Exception:
                pass

    _effective_tier = result["tier"]
    _effective_limit = None
    if is_superuser({"email": result["email"]}):
        _effective_tier = "analyst"
        _effective_limit = 999999

    used, limit = rate_limiter.get_usage(result["user_id"], _effective_tier)
    if _effective_limit is not None:
        limit = _effective_limit
    used = clamped_used(used, limit)

    try:
        from backend.routers.account import get_display_name_state
        _dn, _dn_remaining = get_display_name_state(result["user_id"])
    except Exception:
        _dn, _dn_remaining = None, 3

    return GoogleAuthResponse(
        access_token=result["token"],
        user_id=result["user_id"],
        email=result["email"],
        tier=_effective_tier,
        analyses_today=used,
        analysis_limit=limit,
        display_name=_dn,
        display_name_edits_remaining=_dn_remaining,
        feature_flags=list_enabled_for(result["user_id"], _effective_tier),
        # OAuth providers (Google via Supabase) vouch for the email — the
        # backend also seeds users_meta.email_verified=true so the soft
        # gates open immediately.
        email_verified=True,
        is_new_user=is_new,
    )


@router.get("/google/url")
async def google_oauth_consent_url(redirect_to: Optional[str] = None):
    """Return the Supabase-hosted Google OAuth consent URL.

    The frontend redirects the browser to `url` in the response;
    Supabase handles the Google round-trip and bounces back to
    `redirect_to` (defaulting to the production callback) with the
    access/id tokens in the URL hash fragment.
    """
    # Allow an env override so staging can point at preview URLs
    # without a code change.
    import os as _os
    default_cb = (
        _os.environ.get("GOOGLE_OAUTH_REDIRECT_URL")
        or "https://www.yieldiq.in/auth/callback"
    )
    target = (redirect_to or default_cb).strip()
    # Soft allowlist — only YieldIQ + localhost may be passed in. Prevents
    # the endpoint from being used as an open redirector.
    _ok = (
        target.startswith("https://www.yieldiq.in/")
        or target.startswith("https://yieldiq.in/")
        or target.startswith("http://localhost:")
        or target.startswith("http://127.0.0.1:")
    )
    if not _ok:
        target = default_cb
    try:
        return {"url": build_google_oauth_url(target)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/google", response_model=GoogleAuthResponse, deprecated=True)
async def google_oauth_exchange(req: GoogleAuthRequest):
    """DEPRECATED: exchange a Google ID token for a YieldIQ JWT.

    Only works when the Supabase project has "Skip nonce checks" enabled —
    otherwise Google's id_token never reaches the browser, so the frontend
    has nothing to POST here. Use POST /api/v1/auth/supabase instead, which
    validates Supabase's own session JWT (always available in the callback
    hash regardless of the nonce setting).

    Kept as a transitional alias for any clients still on the old code path.
    """
    result = google_oauth_login_or_register(req.id_token)
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error", "Google sign-in failed."))
    return _finalise_oauth_login(result, req.referral_code)


@router.post("/supabase", response_model=GoogleAuthResponse)
async def supabase_session_exchange(req: SupabaseSessionLoginRequest):
    """Exchange a Supabase session JWT for a YieldIQ JWT.

    Modern OAuth flow:
      1. Frontend hits GET /auth/google/url → redirects browser to Supabase
      2. Supabase → Google → Supabase callback (server-side code exchange)
      3. Supabase bounces back to /auth/callback with `access_token` in the
         URL hash. This `access_token` IS the Supabase session JWT (signed
         by Supabase, 3-segment).
      4. Frontend POSTs that JWT here.
      5. We call Supabase admin.auth.get_user(jwt) to validate, then mint
         a YieldIQ JWT keyed on the resolved email.

    Response shape is identical to the deprecated /auth/google endpoint
    so the frontend store/auth callback handler doesn't care which path
    was used.
    """
    result = supabase_session_login_or_register(req.access_token)
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error", "Google sign-in failed."))
    return _finalise_oauth_login(result, req.referral_code)


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
    # Display clamp at the /auth/me boundary — the nav counter polls
    # this endpoint, so a stale DB row > limit must not surface here.
    used = clamped_used(used, limit)
    try:
        from backend.routers.account import get_display_name_state
        _dn, _dn_remaining = get_display_name_state(user["user_id"])
    except Exception:
        _dn, _dn_remaining = None, 3
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        tier=_effective_tier,
        analyses_today=used,
        analysis_limit=limit,
        display_name=_dn,
        display_name_edits_remaining=_dn_remaining,
        feature_flags=list_enabled_for(user["user_id"], _effective_tier),
        email_verified=_safe_is_verified(user["user_id"], user.get("email")),
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


# ═════════════════════════════════════════════════════════════════
# Soft email verification — send + confirm (feat/soft-email-verify-gates)
#
# Pair of endpoints behind the EmailVerifyBanner. /verify/send mints a
# 24h HMAC token and emails a link; /verify/confirm validates the token
# and flips users_meta.email_verified=true. No DB rows for tokens —
# verification is stateless via verification_service.make/verify_token.
#
# Throttle: max 3 sends per user per rolling hour. SendGrid not
# configured → 503 with a "try again later" so we never crash on a
# missing env var.
# ═════════════════════════════════════════════════════════════════


@router.post("/verify/send")
async def verify_send(user: dict = Depends(get_current_user)):
    """Send (or resend) the verification email.

    Soft-rate-limited at 3/hour per user. Already-verified users get
    a no-op 200 (so a stale frontend that calls this after the user
    already verified doesn't error). SendGrid misconfiguration returns
    503 with a graceful message — never crashes.
    """
    uid = user["user_id"]
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="No email on this account.")

    # Already verified? No-op success.
    try:
        if _verify_svc.is_email_verified(uid, email):
            return {"ok": True, "already_verified": True}
    except Exception:
        pass  # fall through and attempt the send

    allowed, retry_in = _verify_svc.can_send_verification(uid)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many verification emails requested. "
                f"Try again in {retry_in // 60 + 1} min."
            ),
        )

    token = _verify_svc.make_verification_token(uid, email)
    ok = _verify_svc.send_verification_email(email, token)
    if not ok:
        # SendGrid not configured / install missing / API failure. We
        # don't tell the user "your env vars are broken" — just ask
        # them to try later. Operators see the underlying cause in
        # the email_service logger.
        raise HTTPException(
            status_code=503,
            detail=(
                "Couldn't send the verification email right now. "
                "Please try again in a few minutes."
            ),
        )
    _verify_svc.record_send_attempt(uid)
    return {"ok": True}


@router.get("/verify/confirm")
async def verify_confirm(token: str):
    """Confirm a verification token. Flips users_meta.email_verified=true.

    Unauthenticated by design — the user clicks the link from their
    inbox; we shouldn't require them to log in first.

    On success returns {ok, email} and the frontend /auth/verify page
    can show "Verified — return to YieldIQ". On failure returns 400
    with a user-readable error so the page can render it inline.
    """
    if not token:
        raise HTTPException(status_code=400, detail="Missing token.")
    result = _verify_svc.confirm_verification(token)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Invalid token."))
    return {"ok": True, "email": result.get("email")}
