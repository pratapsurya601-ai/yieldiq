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
    Use this for: creating users, updating tiers, admin operations."""
    global _admin_client
    if _admin_client is None:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            # Fallback to anon key if service key not set
            key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
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
