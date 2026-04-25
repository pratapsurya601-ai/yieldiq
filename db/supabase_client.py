# db/supabase_client.py
# ═══════════════════════════════════════════════════════════════
# Central Supabase client for YieldIQ.
# All database operations go through this module.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import os
from functools import lru_cache

_client = None
_admin_client = None


def get_client():
    """Get Supabase client (anon key — for client-side operations)."""
    global _client
    if _client is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
        _client = create_client(url, key)
    return _client


def get_admin_client():
    """Get Supabase admin client (service role key — for server-side operations).
    Use this for: creating users, updating tiers, admin operations.

    REQUIRES the service role key. The earlier silent fallback to
    SUPABASE_ANON_KEY was a footgun — the anon key cannot perform admin
    operations like ``auth.admin.update_user_by_id()``, so the client
    would build successfully but every admin call would fail at runtime
    with a generic error. Caught 2026-04-25 when /api/v1/account/profile
    returned "Couldn't save display name — please try again" on every
    save attempt against prod, with the underlying cause being
    SUPABASE_SERVICE_KEY missing in Railway env.

    For local dev without the service key, set
    ``YIELDIQ_ALLOW_ANON_ADMIN_FALLBACK=1`` to opt into the legacy
    fallback. Production must NEVER set that.
    """
    global _admin_client
    if _admin_client is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        allow_fallback = os.environ.get(
            "YIELDIQ_ALLOW_ANON_ADMIN_FALLBACK", ""
        ).strip().lower() in {"1", "true", "yes"}
        if not url:
            raise RuntimeError(
                "SUPABASE_URL must be set for the admin client."
            )
        if not key:
            if not allow_fallback:
                raise RuntimeError(
                    "SUPABASE_SERVICE_KEY must be set for the admin "
                    "client. The anon-key fallback is disabled because "
                    "admin operations (e.g. update_user_by_id) silently "
                    "fail with the anon key. Set "
                    "YIELDIQ_ALLOW_ANON_ADMIN_FALLBACK=1 to opt into "
                    "the legacy fallback for local-only dev."
                )
            key = os.environ.get("SUPABASE_ANON_KEY", "")
            if not key:
                raise RuntimeError(
                    "SUPABASE_SERVICE_KEY missing AND fallback "
                    "SUPABASE_ANON_KEY also missing."
                )
        _admin_client = create_client(url, key)
    return _admin_client


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — common database operations
# ═══════════════════════════════════════════════════════════════

def get_user_tier(email: str) -> str:
    """Get user's tier from users_meta table."""
    try:
        client = get_admin_client()
        result = client.table("users_meta").select("tier").eq("email", email).single().execute()
        return result.data.get("tier", "free") if result.data else "free"
    except Exception:
        return "free"


def set_user_tier(email: str, tier: str) -> bool:
    """Update user's tier in users_meta table."""
    try:
        client = get_admin_client()
        client.table("users_meta").update({"tier": tier}).eq("email", email).execute()
        return True
    except Exception:
        return False


def upsert_users_meta(user_id: str, email: str, tier: str = "free") -> None:
    """Create or update users_meta row."""
    try:
        client = get_admin_client()
        client.table("users_meta").upsert({
            "id": user_id,
            "email": email,
            "tier": tier,
        }).execute()
    except Exception:
        pass
