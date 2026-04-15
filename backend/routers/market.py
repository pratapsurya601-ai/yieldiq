# backend/routers/market.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

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
    base = data_service.get_market_pulse()

    if not include_macro:
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
        return MarketPulseResponse(**base_dict)
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
