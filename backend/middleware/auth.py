# backend/middleware/auth.py
# JWT authentication + tier-based access control.
# Reuses existing auth database from dashboard/.
from __future__ import annotations
import sys, os
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
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

from backend.middleware.rate_limit import rate_limiter

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


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Validate JWT and return user dict."""
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


def check_analysis_limit(user: dict = Depends(get_current_user)):
    """Check daily analysis limit by tier. Raises 429 if exceeded."""
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
        user["analyses_today"] = used
        user["analysis_limit"] = limit
        user["is_superuser"] = True
        return user

    allowed, used, limit = rate_limiter.check_and_increment(
        user["user_id"], user["tier"]
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily analysis limit reached ({used}/{limit}). Upgrade for more.",
        )
    user["analyses_today"] = used
    user["analysis_limit"] = limit
    return user


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
                "email_confirm": True,           # skip email confirmation
                "user_metadata": {"tier": "free"},
            })
            if not result or not result.user:
                return {"ok": False, "error": "Could not create account. Try again."}
            _uid = str(result.user.id)
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
