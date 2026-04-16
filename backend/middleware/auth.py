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
        if _tier_order.get(user["tier"], 0) < _tier_order.get(min_tier, 0):
            raise HTTPException(
                status_code=403,
                detail=f"This feature requires {min_tier} plan or above",
            )
        return user

    return _require


def login_user_and_get_token(email: str, password: str) -> dict:
    """Authenticate against existing auth DB and return JWT."""
    try:
        # Try Supabase auth first
        from db.supabase_client import get_client
        client = get_client()
        if client:
            result = client.auth.sign_in_with_password({"email": email, "password": password})
            if result and result.user:
                _tier = (result.user.user_metadata or {}).get("tier", "free")
                _uid = str(result.user.id)
                token = create_access_token(_uid, email, _tier)
                return {"ok": True, "token": token, "user_id": _uid, "email": email, "tier": _tier}
    except Exception:
        pass

    # Fallback to SQLite auth
    try:
        from dashboard.auth import login_user as _sqlite_login
        result = _sqlite_login(email, password, "api", "0.0.0.0")
        if result.get("ok"):
            token = create_access_token(
                str(result["user_id"]), email, result.get("tier", "free")
            )
            return {"ok": True, "token": token, "user_id": str(result["user_id"]),
                    "email": email, "tier": result.get("tier", "free")}
        return {"ok": False, "error": result.get("error", "Invalid credentials")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_user_and_get_token(email: str, password: str) -> dict:
    """Register new user and return JWT."""
    try:
        from db.supabase_client import get_client
        client = get_client()
        if client:
            result = client.auth.sign_up({"email": email, "password": password,
                                          "options": {"data": {"tier": "free"}}})
            if result and result.user:
                _uid = str(result.user.id)
                token = create_access_token(_uid, email, "free")
                return {"ok": True, "token": token, "user_id": _uid, "email": email, "tier": "free"}
    except Exception:
        pass

    try:
        from dashboard.auth import register_user as _sqlite_register
        result = _sqlite_register(email, password)
        if result.get("ok"):
            token = create_access_token(str(result["user_id"]), email, "free")
            return {"ok": True, "token": token, "user_id": str(result["user_id"]),
                    "email": email, "tier": "free"}
        return {"ok": False, "error": result.get("error", "Registration failed")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
