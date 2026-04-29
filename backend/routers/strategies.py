# backend/routers/strategies.py
# ═══════════════════════════════════════════════════════════════
# Strategy Builder backend — thin wrapper around the existing
# /backtest engine (backend/services/backtest_service.py) plus
# CRUD on the saved_strategies table.
#
# Endpoints
#   POST /api/v1/strategies/run         — run a backtest (no save)
#   POST /api/v1/strategies/save        — persist + (optional) re-run
#   GET  /api/v1/strategies             — list current user's strategies
#   GET  /api/v1/strategies/{id}        — fetch one (auth-gated)
#   POST /api/v1/strategies/{id}/share  — flip is_public + mint slug
#   GET  /api/v1/strategies/public/{slug} — public read-only view
#
# Discipline:
# - ADDITIVE only. No CACHE_VERSION bump.
# - No analysis-response math change (delegates to backtest_tickers).
# - All persistence through Supabase admin client (matches watchlist /
#   saved_queries patterns).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services.strategy_service import (
    generate_public_slug,
    run_strategy_backtest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


# ── Request models ───────────────────────────────────────────────────
class StrategyRunRequest(BaseModel):
    strategy_def: dict[str, Any] = Field(..., description="Full strategy spec from the builder UI")


class StrategySaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    strategy_def: dict[str, Any]
    run_now: bool = True


class StrategyUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    strategy_def: Optional[dict[str, Any]] = None


# ── Helpers ──────────────────────────────────────────────────────────
def _supabase():
    try:
        from db.supabase_client import get_admin_client
        return get_admin_client()
    except Exception as e:
        logger.warning("supabase admin client unavailable: %s", e)
        return None


def _row_to_dto(row: dict) -> dict:
    """Trim Supabase row into the wire-format the frontend consumes."""
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "strategy_def": row.get("strategy_def"),
        "last_backtest_results": row.get("last_backtest_results"),
        "last_backtested_at": row.get("last_backtested_at"),
        "is_public": bool(row.get("is_public", False)),
        "public_slug": row.get("public_slug"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ── POST /run — fire-and-forget backtest, no save ────────────────────
@router.post("/run")
async def run_strategy(req: StrategyRunRequest, user: dict = Depends(get_current_user)):
    """
    Run a backtest on an ad-hoc strategy_def. Result is NOT persisted.

    Free tier: still gated by the /backtest endpoint underneath. Heavy
    universes (kind=all) can take 10-60s for a 5y backtest.
    """
    result = run_strategy_backtest(req.strategy_def)
    if result.get("error") and not result.get("curve"):
        # Treat 'no matches' as a 200 with the error string — the UI shows
        # an inline empty-state, not a toast. True failures (parquet / DB
        # outage) still come back as 200 here for the same reason; the
        # frontend distinguishes by presence of `curve`.
        return result
    return result


# ── POST /save — persist + (optionally) re-run ───────────────────────
@router.post("/save")
async def save_strategy(req: StrategySaveRequest, user: dict = Depends(get_current_user)):
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")

    last_results = None
    last_at = None
    if req.run_now:
        last_results = run_strategy_backtest(req.strategy_def)
        from datetime import datetime, timezone
        last_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "user_email": email,
        "name": req.name,
        "strategy_def": req.strategy_def,
        "last_backtest_results": last_results,
        "last_backtested_at": last_at,
    }
    try:
        ins = sb.table("saved_strategies").insert(payload).execute()
        rows = ins.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="Insert returned no rows")
        return _row_to_dto(rows[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("save_strategy failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Save failed: {type(e).__name__}")


# ── GET / — list current user's strategies (lightweight) ─────────────
@router.get("/")
async def list_strategies(user: dict = Depends(get_current_user)):
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    sb = _supabase()
    if not sb:
        return {"strategies": []}
    try:
        # Don't ship the heavy results blob in the list view — the
        # individual GET /{id} endpoint loads it on demand.
        res = (
            sb.table("saved_strategies")
            .select("id,name,strategy_def,last_backtested_at,is_public,public_slug,created_at,updated_at")
            .eq("user_email", email)
            .order("created_at", desc=True)
            .execute()
        )
        return {"strategies": [_row_to_dto(r) for r in (res.data or [])]}
    except Exception as e:
        logger.warning("list_strategies failed: %s", e)
        return {"strategies": []}


# ── GET /{id} — fetch one (with last results) ────────────────────────
@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str, user: dict = Depends(get_current_user)):
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")
    try:
        res = (
            sb.table("saved_strategies")
            .select("*")
            .eq("id", strategy_id)
            .eq("user_email", email)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return _row_to_dto(rows[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("get_strategy failed: %s", e)
        raise HTTPException(status_code=500, detail="Fetch failed")


# ── DELETE /{id} ─────────────────────────────────────────────────────
@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str, user: dict = Depends(get_current_user)):
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")
    try:
        sb.table("saved_strategies").delete().eq("id", strategy_id).eq("user_email", email).execute()
        return {"ok": True}
    except Exception as e:
        logger.warning("delete_strategy failed: %s", e)
        raise HTTPException(status_code=500, detail="Delete failed")


# ── POST /{id}/share — toggle is_public + mint slug ──────────────────
@router.post("/{strategy_id}/share")
async def share_strategy(strategy_id: str, user: dict = Depends(get_current_user)):
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=401, detail="Email not found in token")

    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")
    try:
        # Fetch current state first so we know if a slug was already minted.
        cur = (
            sb.table("saved_strategies")
            .select("id,is_public,public_slug")
            .eq("id", strategy_id)
            .eq("user_email", email)
            .limit(1)
            .execute()
        )
        rows = cur.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Strategy not found")
        existing = rows[0]
        slug = existing.get("public_slug") or generate_public_slug()

        sb.table("saved_strategies").update(
            {"is_public": True, "public_slug": slug}
        ).eq("id", strategy_id).eq("user_email", email).execute()

        return {"ok": True, "public_slug": slug}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("share_strategy failed: %s", e)
        raise HTTPException(status_code=500, detail="Share failed")


# ── GET /public/{slug} — anonymous read-only ─────────────────────────
@router.get("/public/{slug}")
async def get_public_strategy(slug: str):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")
    try:
        res = (
            sb.table("saved_strategies")
            .select("id,name,strategy_def,last_backtest_results,last_backtested_at,public_slug,created_at")
            .eq("public_slug", slug)
            .eq("is_public", True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Public strategy not found")
        # Don't leak user_email — _row_to_dto already strips it.
        return _row_to_dto(rows[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("get_public_strategy failed: %s", e)
        raise HTTPException(status_code=500, detail="Fetch failed")
