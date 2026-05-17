# backend/services/verification_service.py
# ─────────────────────────────────────────────────────────────────
# Soft email verification — gate sensitive actions (paid upgrade,
# API-key create, Pro-tier export) on a confirmed email address.
#
# Source of truth: users_meta.email_verified (see migration 011).
# Read path: 60s per-user in-process cache, JWT-tier-style. Fail-open
# on any Supabase/DB error so a transient backend hiccup never blocks
# a paying customer mid-purchase.
#
# Token format: short-lived HMAC over (user_id, email, issued_at)
# signed with JWT_SECRET. No DB table needed — verify by recomputing
# the HMAC against the embedded payload. Tokens expire after
# TOKEN_TTL_SECS (24h by default).
#
# Throttling: in-process per-user rate limiter for /verify/send,
# capped at SEND_MAX_PER_HOUR. Best-effort — survives a single
# Railway worker but resets on redeploy. Acceptable for an MVP
# abuse guard.
# ─────────────────────────────────────────────────────────────────
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("yieldiq.verification")

# 24h token window. Long enough that a user can sit on the email for
# a day and still click through; short enough that a leaked token
# from an old inbox can't be replayed forever.
TOKEN_TTL_SECS = 24 * 3600

SEND_MAX_PER_HOUR = 3
SEND_WINDOW_SECS = 3600.0

_verified_cache: dict[str, tuple[bool, float]] = {}
_VERIFIED_CACHE_TTL_SECS = 60.0

_send_attempts: dict[str, list[float]] = {}


def _jwt_secret() -> str:
    # Reuse the JWT_SECRET so we don't grow a new env-var surface.
    return (
        os.environ.get("JWT_SECRET")
        or os.environ.get("YIELDIQ_JWT_SECRET")
        or "yieldiq-verify-fallback"
    )


def invalidate_verified_cache(user_id: str) -> None:
    """Drop the cached verification flag for a user — call after a
    successful /verify/confirm so the next request reflects the flip
    instead of waiting 60s for the cache to expire."""
    _verified_cache.pop(user_id, None)


def _set_meta_verified(user_id: str, email: str) -> bool:
    """Upsert email_verified=true into users_meta. Returns False on
    any failure so the caller can surface a useful error."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return False
        now_iso = datetime.now(timezone.utc).isoformat()
        # Upsert pattern matches the existing onboarding flow in
        # routers/auth.py — on_conflict on the unique id column.
        client.table("users_meta").upsert(
            {
                "id": user_id,
                "email": email,
                "email_verified": True,
                "email_verified_at": now_iso,
            },
            on_conflict="id",
        ).execute()
        return True
    except Exception as exc:
        logger.warning("verification: users_meta upsert failed for %s: %s", user_id, exc)
        return False


def _read_meta_verified(user_id: str) -> Optional[bool]:
    """Read email_verified from users_meta. Returns None on any error
    (caller decides the fail-open policy)."""
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return None
        r = (
            client.table("users_meta")
            .select("email_verified")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if not rows:
            # No users_meta row yet — pre-migration grandfathering path.
            # Default to True so we never block a legacy user.
            return True
        return bool(rows[0].get("email_verified", False))
    except Exception as exc:
        logger.debug("verification: read failed for %s: %s", user_id, exc)
        return None


def is_email_verified(user_id: str, email: str | None = None) -> bool:
    """Return True if this user's email is verified.

    Fail-open: any Supabase / DB error returns True so a transient
    outage never blocks a paid upgrade or API-key creation. The
    inverse — blocking a real user mid-checkout because Supabase
    flaked — is the worse failure mode.
    """
    if not user_id:
        return True  # superuser / dev path
    now = time.monotonic()
    cached = _verified_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]

    fresh = _read_meta_verified(user_id)
    verified = True if fresh is None else fresh
    _verified_cache[user_id] = (verified, now + _VERIFIED_CACHE_TTL_SECS)
    return verified


# ── Token helpers ────────────────────────────────────────────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_verification_token(user_id: str, email: str) -> str:
    """HMAC-signed token carrying (user_id, email, iat). No DB row
    needed — verify by recomputing the HMAC.

    Format: <b64url(payload_json)>.<b64url(hmac_sha256)>
    """
    payload = {
        "uid": str(user_id),
        "email": (email or "").strip().lower(),
        "iat": int(time.time()),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_jwt_secret().encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64url(body)}.{_b64url(sig)}"


def verify_token(token: str) -> dict:
    """Validate a verification token. Returns {ok, uid, email, error}."""
    if not token or "." not in token:
        return {"ok": False, "error": "Invalid token."}
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
    except Exception:
        return {"ok": False, "error": "Malformed token."}

    expected = hmac.new(_jwt_secret().encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        return {"ok": False, "error": "Token signature mismatch."}

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "Token payload unreadable."}

    iat = int(payload.get("iat") or 0)
    if iat <= 0 or (time.time() - iat) > TOKEN_TTL_SECS:
        return {"ok": False, "error": "This verification link has expired. Request a new one."}

    uid = str(payload.get("uid") or "")
    email = (payload.get("email") or "").strip().lower()
    if not uid or not email:
        return {"ok": False, "error": "Token missing user data."}

    return {"ok": True, "uid": uid, "email": email}


def confirm_verification(token: str) -> dict:
    """Validate token and flip users_meta.email_verified = true.

    Returns {ok, email, error}. Idempotent — confirming a second time
    for the same user just re-upserts the same row.
    """
    decoded = verify_token(token)
    if not decoded.get("ok"):
        return {"ok": False, "error": decoded.get("error", "Invalid token.")}

    uid = decoded["uid"]
    email = decoded["email"]
    ok = _set_meta_verified(uid, email)
    if not ok:
        return {
            "ok": False,
            "error": "Could not record verification right now. Please try again shortly.",
        }
    invalidate_verified_cache(uid)
    return {"ok": True, "email": email}


# ── Resend throttle ──────────────────────────────────────────────

def can_send_verification(user_id: str) -> tuple[bool, int]:
    """Return (allowed, seconds_until_reset). Caps at SEND_MAX_PER_HOUR
    per user per rolling hour."""
    if not user_id:
        return True, 0
    now = time.monotonic()
    window = _send_attempts.setdefault(user_id, [])
    cutoff = now - SEND_WINDOW_SECS
    while window and window[0] < cutoff:
        window.pop(0)
    if len(window) >= SEND_MAX_PER_HOUR:
        # Seconds until the oldest attempt rolls out of the window.
        retry_in = int(SEND_WINDOW_SECS - (now - window[0])) + 1
        return False, max(retry_in, 1)
    return True, 0


def record_send_attempt(user_id: str) -> None:
    if not user_id:
        return
    _send_attempts.setdefault(user_id, []).append(time.monotonic())


# ── Email send (best-effort, SendGrid-aware graceful failure) ────

def send_verification_email(email: str, token: str) -> bool:
    """Render + send the verification email.

    Returns True on success. Returns False (NOT raises) when SendGrid
    isn't configured, the sendgrid package isn't installed, or the
    API call fails — the router translates that into a 503 with a
    "try again later" message so we never crash on an env hole.
    """
    site_url = os.environ.get("YIELDIQ_SITE_URL", "https://yieldiq.in").rstrip("/")
    link = f"{site_url}/auth/verify?token={token}"

    subject = "Verify your YieldIQ email"
    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;background-color:#F1F5F9;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table width="560" cellpadding="0" cellspacing="0" border="0"
                 style="max-width:560px;width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background-color:#FFFFFF;border-radius:8px;">
            <tr>
              <td style="background-color:#0F172A;padding:28px 32px;text-align:center;border-radius:8px 8px 0 0;">
                <span style="color:#FFFFFF;font-size:18px;font-weight:700;letter-spacing:3px;">YIELDIQ</span>
              </td>
            </tr>
            <tr>
              <td style="padding:32px 32px 8px;">
                <h1 style="margin:0 0 12px;font-size:20px;color:#0F172A;">Verify your email</h1>
                <p style="margin:0 0 20px;font-size:15px;color:#334155;line-height:1.6;">
                  Click the button below to confirm this email address.
                  This unlocks paid upgrades, API access, and exports —
                  free analyses, portfolio, and watchlist work without it.
                </p>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:8px 32px 28px;">
                <a href="{link}"
                   style="display:inline-block;padding:14px 32px;background-color:#2563EB;color:#FFFFFF;font-size:15px;font-weight:600;text-decoration:none;border-radius:6px;">
                  Verify email
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 28px;">
                <p style="margin:0;font-size:12px;color:#64748B;line-height:1.6;">
                  Or paste this link into your browser:<br>
                  <span style="word-break:break-all;color:#475569;">{link}</span>
                </p>
                <p style="margin:16px 0 0;font-size:12px;color:#94A3B8;">
                  This link expires in 24 hours. If you didn&rsquo;t request it,
                  you can ignore this email.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """
    text = (
        "Verify your YieldIQ email.\n\n"
        f"Click to confirm: {link}\n\n"
        "This unlocks paid upgrades, API access, and exports. "
        "Free analyses, portfolio, and watchlist work without it.\n\n"
        "Link expires in 24 hours. Didn't request this? Ignore it.\n"
    )
    try:
        from backend.services.email_service import send_email
        return bool(send_email(email, subject, html, text=text, tags=["verify"]))
    except Exception as exc:
        logger.warning("verification: send_email crashed for %s: %s", email, exc)
        return False
