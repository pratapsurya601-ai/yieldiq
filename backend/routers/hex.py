# backend/routers/hex.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Hex — 6-axis hexagonal radar API.
#
# Public (no-auth) read endpoints so Hex URLs can be shared and
# previewed by social scrapers. Portfolio endpoint requires auth.
# Results are cached for 1 hour in the shared in-memory cache.
#
# SEBI note: responses carry a `disclaimer` field and no
# "buy/sell/recommend" language.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services.cache_service import cache
from backend.services import hex_service

logger = logging.getLogger("yieldiq.hex.router")

router = APIRouter(prefix="/api/v1/hex", tags=["hex"])


# ── Request models ──────────────────────────────────────────────
class Holding(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    weight: float = Field(..., ge=0.0)


class PortfolioHexRequest(BaseModel):
    holdings: list[Holding] = Field(..., min_length=1, max_length=100)


# ── Cache helpers ────────────────────────────────────────────────
_CACHE_TTL = 3600  # 1 hour


def _cache_key(ticker: str) -> str:
    return f"hex:{ticker.upper()}"


# ── Endpoints ────────────────────────────────────────────────────
@router.get("/sector-median/{category}")
async def get_sector_median(category: str):
    """
    Return current per-axis medians for a sector category
    ('general', 'bank', 'it'). Used by the frontend to draw a
    benchmark ring on the Hex radar. Public, no auth.
    """
    cat = (category or "").lower().strip()
    if cat not in ("general", "bank", "it"):
        raise HTTPException(
            status_code=400,
            detail="category must be one of: general, bank, it",
        )
    try:
        medians = hex_service._sector_medians(cat)
    except Exception as exc:
        logger.warning("sector_median failed for %s: %s", cat, exc)
        medians = {k: 5.0 for k in hex_service.AXIS_WEIGHTS}
    return {
        "category": cat,
        "medians": medians,
        "disclaimer": hex_service.DISCLAIMER,
    }


@router.get("/compare")
async def compare_hex(
    t1: str = Query(..., min_length=1, max_length=32),
    t2: str = Query(..., min_length=1, max_length=32),
):
    """
    Return Hex payloads for two tickers side by side, plus an
    overlap object (per-axis delta = t1 - t2). Public, cached 1h.
    """
    hex1 = _get_or_compute(t1)
    hex2 = _get_or_compute(t2)

    try:
        delta = {
            k: round(
                float(hex1["axes"][k]["score"]) - float(hex2["axes"][k]["score"]),
                2,
            )
            for k in hex_service.AXIS_WEIGHTS
        }
        overall_delta = round(
            float(hex1.get("overall", 5.0)) - float(hex2.get("overall", 5.0)),
            2,
        )
    except Exception:
        delta = {k: 0.0 for k in hex_service.AXIS_WEIGHTS}
        overall_delta = 0.0

    return {
        "t1": hex1,
        "t2": hex2,
        "overlap": {
            "axis_delta": delta,
            "overall_delta": overall_delta,
            "leader_axis": _leader_axes(hex1, hex2),
        },
        "disclaimer": hex_service.DISCLAIMER,
    }


@router.post("/portfolio")
async def portfolio_hex(
    payload: PortfolioHexRequest,
    user: dict = Depends(get_current_user),
):
    """
    Compute aggregate portfolio Hex from a list of holdings. Weighted
    mean per axis across tickers. Auth required.
    """
    holdings = [h.model_dump() for h in payload.holdings]
    try:
        return hex_service.compute_portfolio_hex(holdings)
    except Exception as exc:
        logger.warning("portfolio_hex failed for user=%s: %s",
                       user.get("email", "?"), exc)
        return {
            "axes": {
                k: {"score": 5.0, "label": "Moderate",
                    "why": "compute error", "data_limited": True}
                for k in hex_service.AXIS_WEIGHTS
            },
            "overall": 5.0,
            "holdings": [],
            "error": "compute_error",
            "data_limited": True,
            "disclaimer": hex_service.DISCLAIMER,
        }


@router.get("/{ticker}")
async def get_hex(ticker: str):
    """
    Return the 6-axis Hex for a single ticker. Public, no auth,
    cached 1 hour. Always returns 200 with `data_limited: true`
    on the affected axes when data is missing.
    """
    return _get_or_compute(ticker)


# ── Internal helpers ────────────────────────────────────────────
def _get_or_compute(ticker: str) -> dict:
    normalized = hex_service._normalize_ticker(ticker)
    if not normalized:
        return hex_service.compute_hex_safe(ticker)
    key = _cache_key(normalized)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = hex_service.compute_hex_safe(normalized)
    try:
        cache.set(key, result, ttl=_CACHE_TTL)
    except Exception:
        pass
    return result


def _leader_axes(h1: dict, h2: dict) -> dict:
    """Per-axis winner label for the compare overlap block."""
    out: dict[str, str] = {}
    t1 = h1.get("ticker", "t1")
    t2 = h2.get("ticker", "t2")
    for k in hex_service.AXIS_WEIGHTS:
        try:
            s1 = float(h1["axes"][k]["score"])
            s2 = float(h2["axes"][k]["score"])
            if abs(s1 - s2) < 0.25:
                out[k] = "tie"
            else:
                out[k] = t1 if s1 > s2 else t2
        except Exception:
            out[k] = "tie"
    return out
