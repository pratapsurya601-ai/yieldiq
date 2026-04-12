# dashboard/auth_supabase.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ Authentication — Supabase Auth
# Replaces the old SQLite-based auth.py with Supabase's built-in
# authentication (email/password, sessions, rate limiting).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_client():
    """Get Supabase client."""
    from db.supabase_client import get_client
    return get_client()


def _get_admin():
    """Get Supabase admin client."""
    from db.supabase_client import get_admin_client
    return get_admin_client()


def init_auth_db() -> None:
    """No-op — Supabase manages the schema. Kept for backward compatibility."""
    pass


def register_user(email: str, password: str, tier: str = "free") -> dict:
    """Register a new user via Supabase Auth."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "error": "Invalid email address."}
    if len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}

    try:
        client = _get_client()
        result = client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {"tier": tier},
            },
        })

        if result.user:
            # Create users_meta row
            from db.supabase_client import upsert_users_meta
            upsert_users_meta(str(result.user.id), email, tier)
            return {"ok": True, "user_id": str(result.user.id)}
        else:
            return {"ok": False, "error": "Registration failed. Please try again."}

    except Exception as e:
        err_msg = str(e)
        if "already registered" in err_msg.lower() or "already been registered" in err_msg.lower():
            return {"ok": False, "error": "An account with that email already exists."}
        return {"ok": False, "error": f"Registration error: {err_msg}"}


def login_user(email: str, password: str, user_agent: str = "", ip: str = "") -> dict:
    """Sign in via Supabase Auth."""
    email = email.strip().lower()
    if not email or not password:
        return {"ok": False, "error": "Enter email and password."}

    try:
        client = _get_client()
        result = client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if result.user and result.session:
            # Get tier from users_meta
            from db.supabase_client import get_user_tier
            tier = get_user_tier(email)

            return {
                "ok": True,
                "token": result.session.access_token,
                "tier": tier,
                "email": email,
                "user_id": str(result.user.id),
            }
        else:
            return {"ok": False, "error": "Invalid email or password."}

    except Exception as e:
        err_msg = str(e)
        if "invalid" in err_msg.lower() or "credentials" in err_msg.lower():
            return {"ok": False, "error": "Incorrect email or password."}
        return {"ok": False, "error": f"Sign in error: {err_msg}"}


def validate_session(token: str) -> dict | None:
    """Validate a Supabase session token."""
    if not token or token == "_guest_":
        return None

    try:
        client = _get_client()
        result = client.auth.get_user(token)

        if result.user:
            email = result.user.email
            from db.supabase_client import get_user_tier
            tier = get_user_tier(email)
            return {
                "email": email,
                "tier": tier,
                "user_id": str(result.user.id),
            }
    except Exception:
        pass

    return None


def logout_session(token: str) -> None:
    """Sign out via Supabase Auth."""
    try:
        client = _get_client()
        client.auth.sign_out()
    except Exception:
        pass


def reset_password(email: str, new_password: str) -> dict:
    """Reset password — uses admin client to update directly."""
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "error": "Invalid email address."}
    if len(new_password) < 8:
        return {"ok": False, "error": "New password must be at least 8 characters."}

    try:
        admin = _get_admin()
        # Find user by email
        users = admin.auth.admin.list_users()
        target_user = None
        for u in users:
            if hasattr(u, 'email') and u.email == email:
                target_user = u
                break

        if not target_user:
            return {"ok": False, "error": "No account found with that email."}

        # Update password
        admin.auth.admin.update_user_by_id(
            str(target_user.id),
            {"password": new_password},
        )
        return {"ok": True}

    except Exception as e:
        return {"ok": False, "error": f"Password reset failed: {e}"}
