# backend/routers/market.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.models.responses import MarketPulseResponse, SectorOverviewItem
from backend.services.data_service import DataService
from backend.services.cache_service import cache
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api/v1/market", tags=["market"])
data_service = DataService()
log = logging.getLogger("yieldiq.market")


def _pipeline_session():
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


@router.get("/pulse", response_model=MarketPulseResponse)
async def get_market_pulse(
    user: dict = Depends(get_current_user),
    include_macro: bool = Query(default=False),
):
    """
    Market indices + fear/greed.

    Pass ``?include_macro=true`` to additionally fetch FII/DII
    flows, FX, commodities and the risk-free rate. Macro fields
    are optional and default to ``null`` — clients unaware of
    them continue to work.
    """
    # Tier-0 RAW dict cache. Data is identical for all users
    # (market indices, not user-specific) so a single shared cache
    # entry is safe. Auth is still enforced — the cache check
    # runs AFTER get_current_user via Depends.
    _raw_key = f"market:pulse:raw:{int(bool(include_macro))}"
    try:
        _raw = cache.get(_raw_key)
    except Exception:
        _raw = None
    if _raw is not None:
        return JSONResponse(
            content=_raw,
            headers={
                "X-Cache": "HIT-MEM-RAW",
                # Auth-gated endpoint — use private so Vercel's
                # shared edge cache does not cache responses
                # across authenticated users. 60s max-age still
                # lets the browser avoid repeat calls during
                # page navigation.
                "Cache-Control": "private, max-age=60",
            },
        )

    base = data_service.get_market_pulse()

    if not include_macro:
        try:
            _dump = base.model_dump(mode="json") if hasattr(base, "model_dump") else base
            cache.set(_raw_key, _dump, ttl=60)
        except Exception:
            pass
        return base

    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        db = _pipeline_session()
        try:
            snapshot = svc.get_snapshot(cache, db)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

        base_dict = base.model_dump()
        allowed = set(MarketPulseResponse.model_fields.keys())
        for k, v in (snapshot or {}).items():
            if k in allowed:
                base_dict[k] = v
        # Attach AI summary if already cached (24h) — avoid
        # blocking the /pulse call on a live LLM roundtrip.
        cached_summary = cache.get("macro:ai_summary")
        if cached_summary:
            base_dict["ai_summary"] = cached_summary
        out = MarketPulseResponse(**base_dict)
        try:
            cache.set(_raw_key, out.model_dump(mode="json"), ttl=60)
        except Exception:
            pass
        return out
    except Exception as exc:
        log.debug("Macro merge failed: %s", exc)
        return base


@router.get("/macro-summary")
async def get_macro_summary(user: dict = Depends(get_current_user)):
    """
    AI-generated 2-sentence market commentary. Cached 24 hours.
    Separate from ``/pulse`` so the main market strip never waits
    on an LLM roundtrip.
    """
    try:
        from backend.services.macro_service import MacroService
        svc = MacroService()
        snapshot = cache.get("macro:snapshot") or {}
        summary = svc.get_ai_summary(snapshot, cache)
        return {"summary": summary}
    except Exception as exc:
        log.debug("macro-summary failed: %s", exc)
        return {"summary": None}


@router.get("/sectors", response_model=list[SectorOverviewItem])
async def get_sector_overview(user: dict = Depends(get_current_user)):
    """Sector valuation summary."""
    return data_service.get_sector_overview()
