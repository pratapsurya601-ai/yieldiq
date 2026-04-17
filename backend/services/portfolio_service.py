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


def get_holdings_with_live_data(user_email: str) -> dict:
    """
    Get holdings enriched with live prices + P&L computation.

    Returns:
        {
            "holdings": [
                {
                    ticker, company_name, sector, entry_price, quantity,
                    current_price, invested_value, current_value,
                    pnl_abs, pnl_pct, fair_value, mos_pct, verdict, score,
                }
            ],
            "summary": {
                "total_invested", "total_current_value",
                "total_pnl_abs", "total_pnl_pct",
                "winners", "losers", "count",
            }
        }
    """
    holdings = get_holdings(user_email)
    if not holdings:
        return {"holdings": [], "summary": _empty_summary()}

    enriched = []
    total_invested = 0.0
    total_current = 0.0
    winners = 0
    losers = 0

    for h in holdings:
        ticker = h.get("ticker", "")
        entry_price = float(h.get("entry_price", 0) or 0)
        # Extract quantity from notes if available (e.g. "Imported from zerodha (80 shares)")
        quantity = _extract_quantity(h.get("notes", "")) or 1
        invested = entry_price * quantity

        # Get current price (from analysis cache, then Parquet fallback)
        current_price = _get_current_price(ticker)
        if current_price is None or current_price <= 0:
            current_price = entry_price  # fallback

        current_value = current_price * quantity
        pnl_abs = current_value - invested
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        if pnl_pct > 0:
            winners += 1
        elif pnl_pct < 0:
            losers += 1

        # Get fair value from cache (don't refetch)
        from backend.services.cache_service import cache as _c
        cached = _c.get(f"analysis:{ticker}")
        fair_value = None
        verdict = ""
        score = None
        mos_pct = None
        if cached and hasattr(cached, "valuation"):
            fair_value = cached.valuation.fair_value
            verdict = cached.valuation.verdict
            score = cached.quality.yieldiq_score
            # MoS = (fair_value - current_price) / current_price (forward-looking)
            mos_pct = ((fair_value - current_price) / current_price * 100) if current_price > 0 else None

        enriched.append({
            "ticker": ticker,
            "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": h.get("company_name", ""),
            "sector": h.get("sector", "") or "—",
            "entry_price": round(entry_price, 2),
            "quantity": quantity,
            "current_price": round(current_price, 2),
            "invested_value": round(invested, 2),
            "current_value": round(current_value, 2),
            "pnl_abs": round(pnl_abs, 2),
            "pnl_pct": round(pnl_pct, 2),
            "fair_value": round(fair_value, 2) if fair_value else None,
            "mos_pct": round(mos_pct, 2) if mos_pct is not None else None,
            "verdict": verdict,
            "score": score,
            "saved_at": h.get("saved_at", ""),
            "notes": h.get("notes", ""),
        })

        total_invested += invested
        total_current += current_value

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # Sort by current value descending
    enriched.sort(key=lambda x: x["current_value"], reverse=True)

    return {
        "holdings": enriched,
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_current_value": round(total_current, 2),
            "total_pnl_abs": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "winners": winners,
            "losers": losers,
            "count": len(enriched),
        },
    }


def _empty_summary() -> dict:
    return {
        "total_invested": 0, "total_current_value": 0,
        "total_pnl_abs": 0, "total_pnl_pct": 0,
        "winners": 0, "losers": 0, "count": 0,
    }


def _extract_quantity(notes: str) -> int | None:
    """Extract quantity from notes like 'Imported from zerodha (80 shares)'."""
    if not notes:
        return None
    import re
    m = re.search(r"\((\d+(?:\.\d+)?)\s*shares?\)", notes)
    if m:
        try:
            return int(float(m.group(1)))
        except ValueError:
            return None
    return None


def _get_current_price(ticker: str) -> float | None:
    """Get the most recent price — from analysis cache first, then Parquet."""
    # Try analysis cache (fastest, has live price)
    try:
        from backend.services.cache_service import cache as _c
        cached = _c.get(f"analysis:{ticker}")
        if cached and hasattr(cached, "valuation"):
            return float(cached.valuation.current_price)
    except Exception:
        pass

    # Fallback to Parquet (latest close)
    try:
        from data_pipeline.nse_prices.db_integration import get_latest_price
        clean = ticker.replace(".NS", "").replace(".BO", "")
        price = get_latest_price(clean)
        if price:
            return float(price)
    except Exception:
        pass

    return None


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
