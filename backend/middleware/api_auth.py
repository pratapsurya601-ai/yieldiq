"""FastAPI dependency that authenticates an API request via the
``Authorization: Bearer yk_…`` header (or ``X-API-Key: yk_…``).

Returns the same ``user`` dict shape as
``backend.middleware.auth.get_current_user`` plus an ``api_key_id`` and
``_via='api_key'`` marker so downstream handlers can branch on auth
method when they need to (e.g. choose CSV vs. HTML response).

Tier check: only Pro users can use API keys. The check is layered
after authentication on purpose — a downgraded user's keys still
exist (the row remains active) but every request 403s, so re-upgrading
re-enables them without losing key state.

Rate limit: per-KEY (not per user) at 100 req/day. See
``backend.services.api_keys_service.check_and_increment_quota``.

Security:
  * NEVER log the raw key. We log only ``key_id`` (logged inside the
    service) so leaked log lines don't grant access.
  * The 401 message is intentionally generic — we don't reveal whether
    the key is malformed, unknown, or revoked.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Header, HTTPException

from backend.middleware.auth import _get_fresh_tier
from backend.services import api_keys_service as svc

logger = logging.getLogger("yieldiq.api_auth")


def _extract_raw_key(authorization: Optional[str],
                     x_api_key: Optional[str]) -> Optional[str]:
    """Pull a ``yk_…`` token out of either header. Returns None if
    neither header carries one."""
    if authorization and authorization.startswith("Bearer "):
        candidate = authorization[len("Bearer "):].strip()
        if candidate.startswith(svc.RAW_KEY_PREFIX):
            return candidate
    if x_api_key:
        candidate = x_api_key.strip()
        if candidate.startswith(svc.RAW_KEY_PREFIX):
            return candidate
    return None


async def get_user_from_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Required-API-key dependency. Raises 401/403/429 as appropriate."""
    raw = _extract_raw_key(authorization, x_api_key)
    if not raw:
        raise HTTPException(
            status_code=401,
            detail=(
                "API key required (Authorization: Bearer yk_… "
                "or X-API-Key: yk_…)"
            ),
        )

    info = svc.authenticate(raw)
    if not info:
        # Generic 401 — never leak whether the key was malformed,
        # unknown, or revoked.
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Tier gate — Pro only. Downgraded users' keys stay alive but 403.
    user_tier = _get_fresh_tier(info["user_id"], "free")
    if user_tier != "pro":
        raise HTTPException(
            status_code=403,
            detail="API access requires Pro tier",
        )

    allowed, count, cap = svc.check_and_increment_quota(info["api_key_id"])
    if not allowed:
        # 429 with structured detail so the client can show a useful
        # error without parsing free-form English.
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limit_exceeded",
                "limit": cap,
                "used": count,
                "message": (
                    f"API key over the {cap} req/day cap. "
                    "Resets at midnight UTC."
                ),
            },
        )

    return {
        "user_id": info["user_id"],
        "tier": user_tier,
        "api_key_id": info["api_key_id"],
        "_via": "api_key",
    }


async def get_user_from_api_key_optional(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[dict]:
    """Optional variant — returns None instead of raising when there's
    no API key on the request. Used by ``get_user_jwt_or_api_key`` to
    let JWT auth take over when the caller is a browser.

    NB: if the caller DOES present an API key but it's invalid/over-quota,
    this still raises — passing a broken key is an explicit signal that
    the caller intended API-key auth and we shouldn't silently fall back
    to "anonymous, then maybe JWT".
    """
    raw = _extract_raw_key(authorization, x_api_key)
    if not raw:
        return None
    # Delegating to the strict path means quota + tier 401/403/429 still
    # bubble — that's deliberate (see docstring).
    return await get_user_from_api_key(
        authorization=authorization, x_api_key=x_api_key,
    )


async def get_user_jwt_or_api_key(
    # Imported lazily inside the function to avoid pulling auth.py at
    # module import time where it sometimes triggers circular issues
    # in test setups that import api_auth before auth.
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Accept EITHER JWT (browser users) OR API key (programmatic).

    If the caller passes ``Authorization: Bearer yk_…`` we treat it as
    an API key (because it carries the yk_ prefix). Anything else with
    a ``Bearer …`` header is treated as a JWT.

    Auth precedence:
      1. If a yk_-prefixed key is present, validate it (raises on bad).
      2. Otherwise try JWT.
      3. Otherwise 401.
    """
    raw = _extract_raw_key(authorization, x_api_key)
    if raw:
        return await get_user_from_api_key(
            authorization=authorization, x_api_key=x_api_key,
        )

    # JWT fallback — call get_current_user with the same Authorization
    # header. We construct a credentials object in the shape FastAPI's
    # HTTPBearer would have produced.
    if authorization and authorization.startswith("Bearer "):
        from fastapi.security import HTTPAuthorizationCredentials
        from backend.middleware.auth import get_current_user
        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=authorization[len("Bearer "):],
        )
        return await get_current_user(creds)

    raise HTTPException(status_code=401, detail="Authentication required")
