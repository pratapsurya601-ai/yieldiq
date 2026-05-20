# backend/middleware/auth.py
# JWT authentication + tier-based access control.
# Reuses existing auth database from dashboard/.
from __future__ import annotations
import sys, os
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

try:
    from jose import jwt, JWTError
except ImportError:
    from jose import jwt, JWTError  # python-jose

from backend.middleware.rate_limit import rate_limiter, clamped_used

# Superuser emails — bypass the rate limiter and get effective tier="pro".
# Comma-separated env var, case-insensitive comparison.
#   Set in Railway → Variables → SUPERUSER_EMAILS="you@example.com,other@example.com"
# Empty / unset = no superusers (default).
_RAW_SUPERUSERS = (os.environ.get("SUPERUSER_EMAILS") or "").strip()
SUPERUSER_EMAILS: set[str] = {
    e.strip().lower() for e in _RAW_SUPERUSERS.split(",") if e.strip()
}


def is_superuser(user: dict) -> bool:
    """True if the user's email is in SUPERUSER_EMAILS."""
    email = (user.get("email") or "").strip().lower()
    return bool(email) and email in SUPERUSER_EMAILS


# JWT config
JWT_SECRET = os.environ.get("JWT_SECRET") or os.environ.get("YIELDIQ_JWT_SECRET") or ""
if not JWT_SECRET:
    import logging as _jl
    _jl.getLogger("yieldiq.auth").critical("JWT_SECRET not set — using random secret (tokens won't persist across restarts)")
    import secrets
    JWT_SECRET = secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

security = HTTPBearer(auto_error=False)

TIER_LIMITS = {"free": 5, "starter": 999999, "pro": 999999, "analyst": 999999}


# ─────────────────────────────────────────────────────────────────
# Tier freshness cache
#
# JWTs carry a snapshot of `tier` from login time. When a user pays
# via Razorpay and verify-subscription flips their users_meta.tier,
# the existing JWT still says 'free' — so rate limiting and tier
# gates silently ignore the upgrade until the user logs out + back
# in to mint a new token.
#
# Fix: on every authenticated request, read the fresh tier from
# users_meta with a 60-second in-process cache to keep DB pressure
# bounded (1 read/min per active user, not per request).
#
# verify-subscription + the webhook call invalidate_tier_cache(uid)
# so upgrades are effectively instant — no 60s lag between payment
# and unlock.
# ─────────────────────────────────────────────────────────────────
_tier_cache: dict[str, tuple[str, float]] = {}
_TIER_CACHE_TTL_SECS = 60

# Observability for persistent Supabase failures in the tier refresh
# path. We don't want to log on every single failure (this runs per
# request), but we MUST surface sustained problems — otherwise a paid
# user with a broken users_meta row or a bad RLS policy stays stuck
# on their stale JWT tier and we never find out.
#
# Policy: keep a sliding 5-minute window of failure timestamps per user.
# If 3+ failures accumulate in that window AND we haven't logged for
# this user in the last 60 seconds, emit a WARN. Still falls back to
# the JWT tier silently — logging is purely additive.
_tier_fetch_failures: dict[str, list[float]] = {}
_tier_fetch_last_logged: dict[str, float] = {}
_TIER_FAIL_WINDOW_SECS = 300.0   # 5 min sliding window
_TIER_FAIL_THRESHOLD = 3          # failures within window before we log
_TIER_FAIL_LOG_COOLDOWN_SECS = 60.0  # per-user log de-dupe


def invalidate_tier_cache(user_id: str) -> None:
    """Drop cached tier for this user — call after Razorpay tier flip
    so the very next request reflects the new tier instead of waiting
    up to 60s for the cache to expire."""
    _tier_cache.pop(user_id, None)


def _record_tier_fetch_failure(user_id: str, jwt_tier: str) -> None:
    """Append a failure timestamp for this user, prune the sliding
    window, and emit a WARN if we've crossed the threshold AND the
    per-user log cooldown has elapsed. Best-effort — never raises.

    Kept as a separate helper so the hot path in _get_fresh_tier stays
    readable and so this logic can be unit-tested in isolation.
    """
    import time as _t
    try:
        now = _t.monotonic()
        window = _tier_fetch_failures.setdefault(user_id, [])
        window.append(now)
        # Prune anything older than the sliding window.
        cutoff = now - _TIER_FAIL_WINDOW_SECS
        # List is small (bounded by request rate × window); linear scan is fine.
        while window and window[0] < cutoff:
            window.pop(0)

        if len(window) < _TIER_FAIL_THRESHOLD:
            return

        last_logged = _tier_fetch_last_logged.get(user_id, 0.0)
        if now - last_logged < _TIER_FAIL_LOG_COOLDOWN_SECS:
            return

        _tier_fetch_last_logged[user_id] = now
        _log().warning(
            "Supabase tier fetch failed %d× for user %s in %ds — "
            "falling back to JWT tier=%s",
            len(window), user_id, int(_TIER_FAIL_WINDOW_SECS), jwt_tier,
        )
    except Exception:
        # Observability must never break the request.
        pass


def _get_fresh_tier(user_id: str, jwt_tier: str) -> str:
    """Read tier from users_meta. 60s per-user cache. Silent fallback
    to jwt_tier on any Supabase failure (we never want a DB hiccup
    to 500 authenticated requests).

    Observability: persistent failures (3+ in 5min for the same user)
    emit a rate-limited WARN via _record_tier_fetch_failure — so a
    broken users_meta row / RLS policy / Neon cold-start loop is
    visible in logs without spamming them on every request.
    """
    import time as _t
    now = _t.monotonic()
    cached = _tier_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]

    tier = jwt_tier
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        result = (
            client.table("users_meta")
            .select("tier")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if rows and rows[0].get("tier"):
            tier = rows[0]["tier"]
    except Exception:
        # JWT fallback is safe; silently log at WARN only when failures
        # are persistent (see _record_tier_fetch_failure). We never
        # raise — a DB hiccup must not 500 authenticated requests.
        _record_tier_fetch_failure(user_id, jwt_tier)

    _tier_cache[user_id] = (tier, now + _TIER_CACHE_TTL_SECS)
    return tier


def create_access_token(user_id: str, email: str, tier: str = "free") -> str:
    """Create JWT token with 7-day expiry."""
    payload = {
        "sub": user_id,
        "email": email,
        "tier": tier,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _dev_mode_user_or_none() -> dict | None:
    """Local-only dev bypass for the canary-diff harness.

    Returns a synthetic 'pro' user when YIELDIQ_DEV_MODE=true, but ONLY
    when we are clearly NOT running on Railway production. Crashes loud
    if both envs are set so an accidental Railway redeploy with this var
    can never serve unauthenticated traffic.

    Designed for `scripts/canary_diff.py` against a local uvicorn so the
    authed `/api/v1/analysis/{ticker}` path returns real DCF data without
    needing a real Supabase JWT. See scripts/run_canary_local.ps1.
    """
    if (os.environ.get("YIELDIQ_DEV_MODE") or "").strip().lower() != "true":
        return None
    rail = (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip().lower()
    if rail in ("production", "prod"):
        # Defensive crash: refuse to run in prod with the bypass on.
        raise RuntimeError(
            "YIELDIQ_DEV_MODE=true is set in Railway production — refusing "
            "to serve unauthenticated traffic. Unset YIELDIQ_DEV_MODE in "
            "Railway dashboard immediately."
        )
    return {
        "user_id": "dev-canary-bypass",
        "email": "dev@localhost",
        "tier": "pro",
        "is_superuser": True,
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Validate JWT and return user dict."""
    # Local-only dev bypass for canary-diff harness. See _dev_mode_user_or_none.
    _dev_user = _dev_mode_user_or_none()
    if _dev_user is not None:
        return _dev_user
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        tier = payload.get("tier", "free")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        # JWT tier is a stale snapshot from login time. Read the
        # current tier from users_meta so post-payment upgrades take
        # effect without forcing a re-login.
        tier = _get_fresh_tier(user_id, tier)
        return {"user_id": user_id, "email": email, "tier": tier}
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    """Like get_current_user but returns None instead of 401 for unauthenticated."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


def check_analysis_limit(
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Check daily analysis limit by tier. Raises 429 if exceeded.

    Also writes `X-Analyses-Today` and `X-Analyses-Limit` response
    headers on success so the frontend can keep its usage counter in
    lock-step with the backend without a second round-trip to
    /auth/me. The Zustand auth store reads these headers inside
    lib/api.ts's getAnalysis interceptor and updates
    analysesToday + analysisLimit atomically. Previously the frontend
    counter was set once at login and then never refreshed —
    incrementAnalyses() existed in the store but was orphaned, and
    the response body carried no usage metadata, so users saw "0/5
    today" indefinitely until they reloaded the page.
    """
    # Superuser bypass: still track usage (so admin sees correct numbers
    # in the UI) but never block.
    if is_superuser(user):
        used, limit = rate_limiter.get_usage(user["user_id"], "pro")
        # Best-effort bump so /auth/me and the counter stay in sync.
        try:
            rate_limiter.check_and_increment(user["user_id"], "pro")
            used += 1
        except Exception:
            pass
        user["tier"] = "pro"  # effective tier for downstream handlers
        # Superusers have effectively-unlimited limit; clamp is a no-op
        # but we still apply it for symmetry with the free path.
        display_used = clamped_used(used, limit)
        user["analyses_today"] = display_used
        user["analysis_limit"] = limit
        user["is_superuser"] = True
        response.headers["X-Analyses-Today"] = str(display_used)
        response.headers["X-Analyses-Limit"] = str(limit)
        response.headers["X-Analyses-Real-Count"] = str(used)
        return user

    allowed, used, limit = rate_limiter.check_and_increment(
        user["user_id"], user["tier"]
    )
    # Display clamp: user-visible count never exceeds the limit (defence
    # in depth — the SQL UPSERT guard is what actually enforces the cap,
    # but a stale row from a tier flip could still leave count > limit
    # for a single day; clamp here so the nav can't render "14/5").
    display_used = clamped_used(used, limit)
    # Always set headers on the 200 response object FIRST so the success
    # path carries them. For the 429 path we ALSO include them on the
    # HTTPException headers dict — FastAPI builds the error response
    # from scratch and ignores the dependency-scoped Response headers,
    # so if we don't pass them via HTTPException(..., headers=...) the
    # nav counter goes stale the instant a user hits the cap (nav shows
    # 0/5 despite just having run 5, seen in production 2026-04-23).
    response.headers["X-Analyses-Today"] = str(display_used)
    response.headers["X-Analyses-Limit"] = str(limit)
    # Operator-visibility header — exposes the raw DB count so we can
    # tell when display clamp is masking drift. Free-tier users shouldn't
    # see "5/5" on the nav while ops sees X-Analyses-Real-Count: 47 in
    # logs without being told.
    response.headers["X-Analyses-Real-Count"] = str(used)
    if not allowed:
        # Day-48 (2026-05-20): structured 429 payload so the frontend
        # can render a clickable upgrade CTA instead of plain error
        # text. Keys mirror the broker/compare quota errors so a single
        # TierCapUpsell component handles all three surfaces.
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "message": f"Daily analysis limit reached ({display_used}/{limit})",
                "limit": limit,
                "used": display_used,
                "upgrade_link": "/pricing?ref=quota_wall",
            },
            headers={
                "X-Analyses-Today": str(display_used),
                "X-Analyses-Limit": str(limit),
                "X-Analyses-Real-Count": str(used),
            },
        )
    user["analyses_today"] = display_used
    user["analysis_limit"] = limit
    user["analyses_real_count"] = used
    return user


def require_email_verified(user: dict = Depends(get_current_user)):
    """Dependency for soft email-verify gates.

    Allowed through:
      * Superusers (SUPERUSER_EMAILS env)
      * Users with users_meta.email_verified = true

    Blocked with 403 + structured detail so the frontend can render a
    "Verify your email" modal pointing at /auth/verify/send.

    Fail-open in verification_service.is_email_verified() — any
    Supabase / DB lookup error treats the user as verified. We never
    want a transient infra hiccup to block a paid upgrade or API key
    creation mid-flow; the inverse failure mode is worse than the
    abuse risk this gate exists to mitigate.
    """
    from backend.services.verification_service import is_email_verified
    if is_superuser(user):
        return user
    if is_email_verified(user["user_id"], user.get("email")):
        user["email_verified"] = True
        return user
    raise HTTPException(
        status_code=403,
        detail={
            "error": "email_verification_required",
            "message": (
                "Verify your email before continuing. We sent a confirmation "
                "link when you signed up — check your inbox, or request a "
                "new one from your account page."
            ),
            "resend_url": "/api/v1/auth/verify/send",
        },
    )


def require_tier(min_tier: str):
    """Factory: returns dependency that requires minimum tier."""
    _tier_order = {"free": 0, "starter": 1, "pro": 1, "analyst": 2}

    def _require(user: dict = Depends(get_current_user)):
        # Superusers pass every tier gate.
        if is_superuser(user):
            user["tier"] = "analyst"
            user["is_superuser"] = True
            return user
        if _tier_order.get(user["tier"], 0) < _tier_order.get(min_tier, 0):
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {min_tier} plan or above",
            )
        return user

    return _require


# ────────────────────────────────────────────────────────────────
# Auth backend selection
#
# Historically this file tried Supabase first, then fell back silently
# to a SQLite file if Supabase threw anything — which caused the
# "register works but login says 'Invalid credentials'" bug: Supabase
# would refuse the login (unconfirmed email, unrecognised client, etc.),
# the exception was swallowed, and SQLite wouldn't have the user. So
# the app appeared to work on signup but was fundamentally broken on
# return visits.
#
# Fix: pick ONE backend up front based on whether SUPABASE_URL is set.
# Never mix. Never swallow. Bubble the real error so the user sees why.
# SQLite also won't survive a Railway redeploy anyway — its on-disk
# file lives in /app which is ephemeral — so mixing was never safe.
# ────────────────────────────────────────────────────────────────
_auth_log = None  # lazy logger


def _log() -> "logging.Logger":
    global _auth_log
    if _auth_log is None:
        import logging as _l
        _auth_log = _l.getLogger("yieldiq.auth")
    return _auth_log


def _auth_backend() -> str:
    """Return 'supabase' if Supabase is configured, else 'sqlite'."""
    if os.environ.get("SUPABASE_URL") and (
        os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    ):
        return "supabase"
    return "sqlite"


def _extract_supabase_error(exc: Exception) -> str:
    """Pull a user-friendly message out of a Supabase AuthApiError / AuthError."""
    msg = str(exc) or exc.__class__.__name__
    low = msg.lower()
    if "email not confirmed" in low or "email_not_confirmed" in low:
        return (
            "Your email is not confirmed yet. Check your inbox for the "
            "confirmation link, or ask the admin to auto-confirm your account."
        )
    if "invalid login credentials" in low or "invalid_login_credentials" in low:
        return "Invalid email or password."
    if "user already registered" in low or "already_registered" in low:
        return "An account with this email already exists. Please sign in instead."
    if "weak password" in low or "password should be" in low:
        return "Password is too weak. Use at least 6 characters."
    # Default: surface whatever Supabase said, trimmed.
    return msg[:200]


def login_user_and_get_token(email: str, password: str) -> dict:
    """Authenticate against the configured auth backend and return JWT.

    No silent fallback between backends — if Supabase is configured,
    we use Supabase exclusively; otherwise we use the on-disk SQLite
    DB. Mixing the two caused the register/login mismatch bug.
    """
    backend = _auth_backend()

    if backend == "supabase":
        try:
            from db.supabase_client import get_client
            client = get_client()
            if client is None:
                return {"ok": False, "error": "Auth backend unavailable — try again shortly."}
            result = client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            if not result or not result.user:
                return {"ok": False, "error": "Invalid email or password."}
            _tier = (result.user.user_metadata or {}).get("tier", "free")
            _uid = str(result.user.id)
            token = create_access_token(_uid, email, _tier)
            return {"ok": True, "token": token, "user_id": _uid,
                    "email": email, "tier": _tier}
        except Exception as exc:
            _log().warning("Supabase login failed for %s: %s", email, exc)
            return {"ok": False, "error": _extract_supabase_error(exc)}

    # SQLite backend (local dev / self-hosted deployments)
    try:
        from dashboard.auth import login_user as _sqlite_login
        result = _sqlite_login(email, password, "api", "0.0.0.0")
        if result.get("ok"):
            token = create_access_token(
                str(result["user_id"]), email, result.get("tier", "free")
            )
            return {"ok": True, "token": token, "user_id": str(result["user_id"]),
                    "email": email, "tier": result.get("tier", "free")}
        return {"ok": False, "error": result.get("error", "Invalid email or password.")}
    except Exception as exc:
        _log().error("SQLite login failed for %s: %s", email, exc)
        return {"ok": False, "error": "Auth backend error — please try again."}


def register_user_and_get_token(email: str, password: str) -> dict:
    """Register a new user on the configured auth backend.

    On Supabase, we use the admin client to auto-confirm the email —
    this skips Supabase's double-opt-in flow, which was the root cause
    of the login-after-signup bug (the account existed but couldn't
    sign in until the user clicked a confirmation link they never got).
    If the admin client isn't available (no SUPABASE_SERVICE_KEY),
    we fall back to the regular sign_up flow and tell the user to
    check their inbox.
    """
    backend = _auth_backend()

    if backend == "supabase":
        # Prefer admin create_user so the account is usable immediately.
        try:
            from db.supabase_client import get_admin_client
            admin = get_admin_client()
            result = admin.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,           # skip Supabase email confirmation
                "user_metadata": {"tier": "free"},
            })
            if not result or not result.user:
                return {"ok": False, "error": "Could not create account. Try again."}
            _uid = str(result.user.id)
            # Seed users_meta with email_verified=false. The Supabase
            # auth row is auto-confirmed (so the user can log in
            # immediately) but our soft gates read from users_meta —
            # they must verify before paid upgrade / API-key / export.
            # Best-effort: if users_meta seeding fails the user can
            # still log in; the read path defaults to True for missing
            # rows (legacy grandfathering) so the gate fails-open.
            try:
                from backend.services.verification_service import send_verification_email, make_verification_token
                from db.supabase_client import get_admin_client as _gac
                _c = _gac()
                if _c is not None:
                    _c.table("users_meta").upsert(
                        {"id": _uid, "email": email, "email_verified": False,
                         "tier": "free"},
                        on_conflict="id",
                    ).execute()
                # Fire-and-forget the verification email. The signup
                # response doesn't block on this — frontend shows the
                # banner regardless, with a "resend" button.
                import threading as _th
                _vtok = make_verification_token(_uid, email)
                _th.Thread(
                    target=send_verification_email,
                    args=(email, _vtok),
                    daemon=True,
                ).start()
            except Exception as _vexc:
                _log().info(
                    "signup: verification seed/send soft-failed for %s: %s",
                    email, _vexc,
                )
            token = create_access_token(_uid, email, "free")
            return {"ok": True, "token": token, "user_id": _uid,
                    "email": email, "tier": "free"}
        except Exception as admin_exc:
            _log().info(
                "Admin signup unavailable for %s (%s) — falling back to sign_up",
                email, admin_exc,
            )
            # Fall through to regular sign_up below

        try:
            from db.supabase_client import get_client
            client = get_client()
            if client is None:
                return {"ok": False, "error": "Auth backend unavailable — try again shortly."}
            result = client.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"tier": "free"}},
            })
            if not result or not result.user:
                return {"ok": False, "error": "Could not create account. Try again."}
            _uid = str(result.user.id)
            token = create_access_token(_uid, email, "free")
            # NB: if the Supabase project has email confirmation turned ON
            # and the admin path isn't available, the user won't be able
            # to log in until they confirm via email. Flag it.
            return {
                "ok": True, "token": token, "user_id": _uid,
                "email": email, "tier": "free",
                "note": "Check your inbox to confirm your email if prompted.",
            }
        except Exception as exc:
            _log().warning("Supabase signup failed for %s: %s", email, exc)
            return {"ok": False, "error": _extract_supabase_error(exc)}

    # SQLite backend
    try:
        from dashboard.auth import register_user as _sqlite_register
        result = _sqlite_register(email, password)
        if result.get("ok"):
            token = create_access_token(str(result["user_id"]), email, "free")
            return {"ok": True, "token": token, "user_id": str(result["user_id"]),
                    "email": email, "tier": "free"}
        return {"ok": False, "error": result.get("error", "Registration failed.")}
    except Exception as exc:
        _log().error("SQLite signup failed for %s: %s", email, exc)
        return {"ok": False, "error": "Auth backend error — please try again."}


# ─────────────────────────────────────────────────────────────────
# Google OAuth (feat/google-oauth-signup)
#
# The frontend signs in with Google via Supabase's hosted OAuth flow
# (so we never see the client secret). Supabase redirects back to
# /auth/callback with an `access_token` + `id_token` in the URL hash.
# The callback POSTs the id_token here; we verify with Google's
# tokeninfo endpoint, then mint a YieldIQ JWT.
#
# Returning users: looked up by email via Supabase admin.list_users.
# New users: created via admin.create_user with email_confirm=True
# and user_metadata={provider: "google", signup_source: "google"}.
# The `provider` field lets future analytics split conversion by
# signup channel without a separate column.
# ─────────────────────────────────────────────────────────────────

_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def verify_google_id_token(id_token: str, timeout: float = 8.0) -> dict:
    """Verify a Google ID token via the tokeninfo REST endpoint.

    Returns a dict {ok, email, sub, name, picture, error}. Network
    failures and invalid tokens both return ok=False with a safe
    user-facing error string.

    We use the REST endpoint (vs google-auth library) to avoid pulling
    in a new dependency — `requests` is already in requirements.
    """
    if not id_token or not isinstance(id_token, str):
        return {"ok": False, "error": "Missing Google token."}
    try:
        import requests as _r
        resp = _r.get(_GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=timeout)
    except Exception as exc:
        _log().warning("Google tokeninfo network error: %s", exc)
        return {"ok": False, "error": "Could not reach Google — please retry."}

    if resp.status_code != 200:
        # Diagnostic logging so we can see WHY Google rejected the token.
        # Previously this branch swallowed everything — we were flying blind
        # in Railway logs. Token prefix/suffix only (never the full token)
        # for correlation; truncate Google's error body to avoid log spam.
        try:
            _body_snippet = (resp.text or "")[:500]
        except Exception:
            _body_snippet = "<unreadable>"
        _tok_len = len(id_token)
        _tok_prefix = id_token[:20]
        _tok_suffix = id_token[-10:] if _tok_len > 30 else ""
        _segments = id_token.count(".") + 1
        _shape = "jwt-3seg" if _segments == 3 else f"opaque-{_segments}seg"
        _log().warning(
            "Google tokeninfo rejected token: status=%s shape=%s len=%s "
            "prefix=%r suffix=%r body=%r",
            resp.status_code, _shape, _tok_len, _tok_prefix, _tok_suffix, _body_snippet,
        )
        return {"ok": False, "error": "Google rejected the sign-in token. Please try again."}

    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "error": "Unexpected response from Google."}

    email = (body.get("email") or "").strip().lower()
    sub = body.get("sub") or ""
    if not email or not sub:
        return {"ok": False, "error": "Google did not return a verified email."}

    # email_verified comes back as the string "true" / "false" from tokeninfo.
    email_verified = str(body.get("email_verified", "")).lower() in ("true", "1")
    if not email_verified:
        return {"ok": False, "error": "Your Google account email is not verified."}

    # Optional audience pin — if GOOGLE_OAUTH_CLIENT_ID is set, require the
    # token was minted for our client (defence in depth against token reuse).
    expected_aud = (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    if expected_aud and body.get("aud") != expected_aud:
        return {"ok": False, "error": "Sign-in token was not issued for this app."}

    return {
        "ok": True,
        "email": email,
        "sub": sub,
        "name": body.get("name") or "",
        "picture": body.get("picture") or "",
    }


def verify_supabase_session_token(access_token: str) -> dict:
    """Verify a Supabase session JWT via the admin SDK.

    This is the modern OAuth path: Supabase performs the Google round-trip
    server-side (response_type=code), so the browser only ever sees
    Supabase's OWN session access_token in the URL hash — Google's id_token
    never reaches the client unless "Skip nonce checks" is enabled in the
    Supabase dashboard. We validate that Supabase JWT here by asking
    Supabase to resolve it to a user.

    Returns {ok, email, sub, provider, name, picture, error}. Network /
    invalid-token failures both return ok=False with a safe user-facing
    message; underlying cause is logged for ops.

    Why the admin SDK (not jose.jwt.decode):
      Supabase signs session JWTs with the project's JWT_SECRET — which we
      don't (and shouldn't) hold in this service. The admin client uses the
      service-role key to call /auth/v1/user, which validates the token
      server-side against Supabase's own copy. That's the supported path.
    """
    if not access_token or not isinstance(access_token, str):
        return {"ok": False, "error": "Missing Supabase session token."}

    # Cheap pre-flight: Supabase JWTs are 3-segment. If we got something
    # opaque (e.g. provider_token, which is Google's access_token) we
    # surface a clearer error than waiting for Supabase to 401.
    _segments = access_token.count(".") + 1
    if _segments != 3:
        _log().warning(
            "Supabase session token: bad shape segments=%s len=%s prefix=%r",
            _segments, len(access_token), access_token[:20],
        )
        return {"ok": False, "error": "Sign-in token has unexpected shape — please retry."}

    try:
        from db.supabase_client import get_admin_client
        admin = get_admin_client()
    except Exception as exc:
        _log().error("Supabase session verify: admin client unavailable: %s", exc)
        return {"ok": False, "error": "Auth backend unavailable — please retry."}

    try:
        # supabase-py 2.x exposes auth.get_user(jwt) — returns a UserResponse
        # whose .user is the resolved auth.user row. The call wraps
        # GET /auth/v1/user with the JWT as the bearer.
        result = admin.auth.get_user(access_token)
    except Exception as exc:
        # AuthApiError on invalid/expired tokens. Diagnostic logging so ops
        # can tell network errors from genuine rejections.
        _log().warning(
            "Supabase session verify: get_user raised: %s (token len=%s prefix=%r)",
            exc, len(access_token), access_token[:20],
        )
        return {"ok": False, "error": "Supabase rejected the sign-in token. Please try again."}

    user = getattr(result, "user", None) if result is not None else None
    if user is None:
        _log().warning("Supabase session verify: get_user returned no user")
        return {"ok": False, "error": "Sign-in session not recognised. Please try again."}

    email = (getattr(user, "email", None) or "").strip().lower()
    sub = str(getattr(user, "id", "") or "")
    if not email or not sub:
        _log().warning(
            "Supabase session verify: missing email/sub on user (email=%r sub=%r)",
            email, sub,
        )
        return {"ok": False, "error": "Supabase did not return a verified email."}

    # Pull provider hints from app_metadata / user_metadata. For Google
    # we expect app_metadata.provider == "google".
    app_meta = getattr(user, "app_metadata", None) or {}
    user_meta = getattr(user, "user_metadata", None) or {}
    provider = (
        (app_meta.get("provider") if isinstance(app_meta, dict) else None)
        or (user_meta.get("provider") if isinstance(user_meta, dict) else None)
        or "google"
    )
    name = ""
    picture = ""
    if isinstance(user_meta, dict):
        name = user_meta.get("name") or user_meta.get("full_name") or ""
        picture = user_meta.get("picture") or user_meta.get("avatar_url") or ""

    return {
        "ok": True,
        "email": email,
        "sub": sub,
        "provider": provider,
        "name": name,
        "picture": picture,
    }


def _oauth_login_or_register_from_verified(verified: dict) -> dict:
    """Shared upsert path for any verified OAuth identity.

    Both verify_google_id_token (deprecated) and verify_supabase_session_token
    produce a {ok, email, sub, name, ...} dict; this helper consumes that
    and:
      - looks up the user by email in Supabase
      - creates the row if absent (with provider/signup_source metadata)
      - mints a YieldIQ JWT
      - syncs users_meta.email_verified=true (OAuth providers vouch for email)

    Returns {ok, token, user_id, email, tier, is_new_user, error}.
    """
    email = verified["email"]
    google_sub = verified.get("sub", "")
    name = verified.get("name", "")

    backend = _auth_backend()
    if backend != "supabase":
        # SQLite path is local-dev only; not wiring OAuth there.
        return {"ok": False, "error": "Google sign-in is not available in this environment."}

    try:
        from db.supabase_client import get_admin_client
        admin = get_admin_client()
    except Exception as exc:
        _log().error("Google OAuth: admin client unavailable: %s", exc)
        return {"ok": False, "error": "Auth backend unavailable — please retry."}

    # Look up existing user by email. supabase-py exposes
    # admin.list_users() but no direct get-by-email; we filter client-side.
    # The endpoint paginates (default 50/page) so we walk pages until we
    # find the match or run out of users. Without this, the 51st user
    # onwards silently failed lookup and got pushed onto the create path
    # (which then 422'd on the duplicate-email check).
    existing_user = None
    try:
        page = 1
        per_page = 200
        max_pages = 50  # hard stop: 10,000 users
        while page <= max_pages and existing_user is None:
            try:
                resp = admin.auth.admin.list_users(page=page, per_page=per_page)
            except TypeError:
                # Older supabase-py builds don't accept kwargs — fall back
                # to a single un-paginated call (matches prior behaviour).
                resp = admin.auth.admin.list_users()
            # supabase-py returns either a list of users or an object with .users
            candidates = getattr(resp, "users", None) or (resp if isinstance(resp, list) else [])
            if not candidates:
                break
            for u in candidates:
                u_email = (getattr(u, "email", None) or "").strip().lower()
                if u_email == email:
                    existing_user = u
                    break
            # Stop when the page came back short — no more rows.
            if len(candidates) < per_page:
                break
            page += 1
    except Exception as exc:
        _log().warning("Google OAuth: list_users failed: %s", exc)
        # Fall through — we'll try to create; if it already exists Supabase
        # will tell us and we can fall back to a sign-in attempt.

    if existing_user is not None:
        uid = str(getattr(existing_user, "id", "") or "")
        meta = getattr(existing_user, "user_metadata", None) or {}
        tier = meta.get("tier", "free")
        # Best-effort backfill of provider linkage so analytics can see
        # this user has Google linked (idempotent — only adds keys).
        try:
            if not meta.get("google_sub"):
                merged = dict(meta)
                merged.setdefault("provider", meta.get("provider") or "google")
                merged["google_sub"] = google_sub
                if name and not merged.get("name"):
                    merged["name"] = name
                admin.auth.admin.update_user_by_id(uid, {"user_metadata": merged})
        except Exception as exc:
            _log().info("Google OAuth: metadata backfill failed for %s: %s", email, exc)

        # Google has already verified the email — keep users_meta in
        # sync so the soft-verify gates let them straight through.
        try:
            from backend.services.verification_service import _set_meta_verified
            _set_meta_verified(uid, email)
        except Exception as _vexc:
            _log().info("google oauth: meta verify backfill failed for %s: %s", email, _vexc)
        token = create_access_token(uid, email, tier)
        return {
            "ok": True, "token": token, "user_id": uid,
            "email": email, "tier": tier, "is_new_user": False,
        }

    # New user — create with auto-confirmed email + provider metadata.
    try:
        result = admin.auth.admin.create_user({
            "email": email,
            "email_confirm": True,
            "user_metadata": {
                "tier": "free",
                "provider": "google",
                "signup_source": "google",
                "google_sub": google_sub,
                "name": name,
            },
        })
        if not result or not getattr(result, "user", None):
            return {"ok": False, "error": "Could not create account. Try again."}
        uid = str(result.user.id)
        # New Google user — seed users_meta with email_verified=true
        # so the soft-verify gates open immediately (Google has already
        # verified the email; no need to make them click a second link).
        try:
            from backend.services.verification_service import _set_meta_verified
            _set_meta_verified(uid, email)
        except Exception as _vexc:
            _log().info(
                "google oauth: new-user meta verify seed failed for %s: %s",
                email, _vexc,
            )
        token = create_access_token(uid, email, "free")
        return {
            "ok": True, "token": token, "user_id": uid,
            "email": email, "tier": "free", "is_new_user": True,
        }
    except Exception as exc:
        _log().warning("Google OAuth: create_user failed for %s: %s", email, exc)
        return {"ok": False, "error": _extract_supabase_error(exc)}


def google_oauth_login_or_register(id_token: str) -> dict:
    """DEPRECATED: verify a Google ID token directly and mint a YieldIQ JWT.

    This path only works when the Supabase project has "Skip nonce checks"
    enabled, because otherwise Supabase strips the Google id_token from the
    callback hash and the browser never sees it. Prefer
    supabase_session_login_or_register, which validates Supabase's own
    session JWT instead.

    Kept as a backward-compat alias for older frontends still POSTing
    {id_token} to /api/v1/auth/google.
    """
    verified = verify_google_id_token(id_token)
    if not verified.get("ok"):
        return {"ok": False, "error": verified.get("error", "Google sign-in failed.")}
    return _oauth_login_or_register_from_verified(verified)


def supabase_session_login_or_register(access_token: str) -> dict:
    """Verify a Supabase session JWT and mint a YieldIQ JWT.

    This is the supported OAuth path (see verify_supabase_session_token
    docstring). The frontend extracts Supabase's `access_token` from the
    /auth/callback hash and POSTs it to /api/v1/auth/supabase.
    """
    verified = verify_supabase_session_token(access_token)
    if not verified.get("ok"):
        return {"ok": False, "error": verified.get("error", "Google sign-in failed.")}
    return _oauth_login_or_register_from_verified(verified)


def build_google_oauth_url(redirect_to: str) -> str:
    """Return the Supabase-hosted Google OAuth consent URL.

    Frontend redirects the browser here; Supabase handles the Google
    round-trip and bounces back to `redirect_to` with the tokens in
    the URL hash. This keeps the Google client secret out of YieldIQ
    entirely — it lives only in the Supabase project config.
    """
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL not configured")
    from urllib.parse import urlencode
    # CRITICAL: include `openid` in scopes so Google returns an id_token JWT
    # (not just the opaque OAuth access_token). Without `openid` Supabase
    # passes `email profile` to Google → Google omits id_token → the
    # frontend hash never carries `provider_id_token` → backend tokeninfo
    # rejects the opaque access_token with 400. Confirmed via live trace
    # 2026-05-17 (Chrome MCP) — Google redirect URL showed scope=email+profile.
    qs = urlencode({
        "provider": "google",
        "redirect_to": redirect_to,
        "scopes": "openid email profile",
    })
    return f"{supabase_url}/auth/v1/authorize?{qs}"
