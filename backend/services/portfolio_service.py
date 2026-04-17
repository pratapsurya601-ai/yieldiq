# backend/services/portfolio_service.py
# ═══════════════════════════════════════════════════════════════
# Portfolio CRUD — Supabase-backed with per-user isolation.
# Table: holdings (user_email PK composite)
#
# SQL to create the table (run once in Supabase SQL editor):
# CREATE TABLE IF NOT EXISTS holdings (
#     id            BIGSERIAL PRIMARY KEY,
#     user_email    TEXT NOT NULL,
#     ticker        TEXT NOT NULL,
#     company_name  TEXT DEFAULT '',
#     entry_price   DOUBLE PRECISION NOT NULL,
#     iv            DOUBLE PRECISION DEFAULT 0,
#     mos_pct       DOUBLE PRECISION DEFAULT 0,
#     signal        TEXT DEFAULT '',
#     wacc          DOUBLE PRECISION DEFAULT 0,
#     sector        TEXT DEFAULT '',
#     notes         TEXT DEFAULT '',
#     saved_at      TIMESTAMPTZ DEFAULT NOW(),
#     UNIQUE(user_email, ticker)
# );
# CREATE INDEX IF NOT EXISTS idx_holdings_email ON holdings(user_email);
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger("yieldiq.portfolio")


def _get_supabase():
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception as e:
        logger.warning(f"Supabase client unavailable: {e}")
        return None


def save_holding(
    user_email: str,
    ticker: str,
    entry_price: float,
    iv: float = 0,
    mos_pct: float = 0,
    signal: str = "",
    wacc: float = 0.12,
    sector: str = "",
    notes: str = "",
    company_name: str = "",
) -> tuple[bool, str]:
    """
    Upsert a holding for a user. Returns (ok, error_message).
    """
    if not user_email:
        return False, "user_email required"
    if not ticker:
        return False, "ticker required"

    client = _get_supabase()
    if client is None:
        return False, "Supabase unavailable"

    ticker_up = ticker.upper()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # Upsert on (user_email, ticker) unique constraint
        row = {
            "user_email": user_email,
            "ticker": ticker_up,
            "company_name": company_name,
            "entry_price": float(entry_price),
            "iv": float(iv) if iv else 0,
            "mos_pct": float(mos_pct) if mos_pct else 0,
            "signal": signal or "",
            "wacc": float(wacc) if wacc else 0.12,
            "sector": sector or "",
            "notes": notes or "",
            "saved_at": now_iso,
        }
        client.table("holdings").upsert(row, on_conflict="user_email,ticker").execute()
        return True, ""
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        logger.warning(f"save_holding failed for {user_email}/{ticker_up}: {err_msg}")
        return False, err_msg


def get_holdings(user_email: str) -> list[dict]:
    """Return all holdings for a user."""
    if not user_email:
        return []
    client = _get_supabase()
    if client is None:
        return []
    try:
        result = (
            client.table("holdings")
            .select("*")
            .eq("user_email", user_email)
            .order("saved_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"get_holdings failed for {user_email}: {e}")
        return []


def remove_holding(user_email: str, ticker: str) -> bool:
    """Delete a holding by ticker for a user."""
    if not user_email or not ticker:
        return False
    client = _get_supabase()
    if client is None:
        return False
    try:
        result = (
            client.table("holdings")
            .delete()
            .eq("user_email", user_email)
            .eq("ticker", ticker.upper())
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.warning(f"remove_holding failed for {user_email}/{ticker}: {e}")
        return False


def count_holdings(user_email: str) -> int:
    """Count holdings for tier-limit checks."""
    if not user_email:
        return 0
    client = _get_supabase()
    if client is None:
        return 0
    try:
        result = (
            client.table("holdings")
            .select("id", count="exact")
            .eq("user_email", user_email)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0
