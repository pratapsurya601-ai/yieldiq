# backend/routers/prism.py
# ═══════════════════════════════════════════════════════════════
# The YieldIQ Prism — consolidated analysis-page payload endpoint.
#
# GET  /api/v1/prism/{ticker}           — single-ticker prism (public)
# GET  /api/v1/prism/compare?t1=&t2=    — two-ticker overlay (public)
#
# Warm path target: <150ms. Cold path: <800ms. Never 500s — the
# service layer returns a populated baseline on any internal error.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.services import prism_service, prism_narration_service
from backend.services import hex_history_service
from backend.services.cache_service import cache

# Shared Cache-Control for public prism responses. s-maxage caches at
# Vercel edge for 5 min; browsers don't honour s-maxage so private
# callers still get a fresh payload on refresh. stale-while-revalidate
# lets the edge serve stale for an hour while revalidating in the
# background, which smooths the post-TTL cliff.
_PRISM_CACHE_CONTROL = "public, s-maxage=300, stale-while-revalidate=3600"

logger = logging.getLogger("yieldiq.prism.router")

router = APIRouter(prefix="/api/v1/prism", tags=["prism"])

# Prism history (Time Machine) cache TTL — snapshots update weekly at most.
_HISTORY_TTL = 6 * 3600


# ── Simple in-memory IP rate limiter for the narrate endpoint ──
# 30 requests / minute / IP. Exists purely to stop a single client
# from spamming Groq via repeated button clicks (cache also helps,
# but the first request per ticker is the expensive one).
_NARRATE_LIMIT = 30
_NARRATE_WINDOW = 60.0
_narrate_lock = threading.Lock()
_narrate_hits: dict[str, Deque[float]] = {}


def _narrate_rate_ok(ip: str) -> bool:
    now = time.time()
    with _narrate_lock:
        dq = _narrate_hits.get(ip)
        if dq is None:
            dq = deque()
            _narrate_hits[ip] = dq
        # Drop entries outside the window.
        while dq and (now - dq[0]) > _NARRATE_WINDOW:
            dq.popleft()
        if len(dq) >= _NARRATE_LIMIT:
            return False
        dq.append(now)
        return True


def _raw_dump(obj):
    """Best-effort convert a possibly-Pydantic response to a plain dict."""
    if obj is None or isinstance(obj, (dict, list)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    return obj


@router.get("/compare")
async def compare_prism(
    t1: str = Query(..., min_length=1, max_length=32),
    t2: str = Query(..., min_length=1, max_length=32),
):
    """Return Prism payloads for two tickers plus per-axis delta overlay.
    Public, cached 1h per side via the underlying service."""
    # Tier-0 RAW cache: pair key is order-normalised so ?t1=A&t2=B
    # and ?t1=B&t2=A share a cache slot. Skips Pydantic + the
    # compare_prisms recomputation.
    try:
        _pair = tuple(sorted([(t1 or "").upper().strip(), (t2 or "").upper().strip()]))
        _raw_key = f"prism-compare:{_pair[0]}:{_pair[1]}:raw"
        _raw = cache.get(_raw_key)
        if _raw is not None:
            return JSONResponse(
                content=_raw,
                headers={
                    "X-Cache": "HIT-MEM-RAW",
                    "Cache-Control": _PRISM_CACHE_CONTROL,
                },
            )
    except Exception:
        _raw_key = None

    try:
        result = prism_service.compare_prisms(t1, t2)
        try:
            if _raw_key:
                cache.set(_raw_key, _raw_dump(result), ttl=3600)
        except Exception:
            pass
        return result
    except Exception as exc:
        logger.warning("prism compare failed: %s", exc)
        # Return a shape-stable object instead of 500ing.
        return {
            "stock1": prism_service.get_prism(t1),
            "stock2": prism_service.get_prism(t2),
            "overlap": {
                "per_axis_delta": {
                    k: 0.0 for k in
                    ("value", "quality", "growth", "moat", "safety", "pulse")
                },
                "overall_delta": 0.0,
                "score_delta": 0.0,
                "mos_delta": 0.0,
            },
            "error": "compare_error",
            "data_limited": True,
            "disclaimer": prism_service.DISCLAIMER,
        }


@router.get("/{ticker}/history")
async def get_ticker_history(
    ticker: str,
    quarters: int = Query(12, ge=2, le=20),
):
    """Return the last N quarters of Prism snapshots for the Time Machine
    scrubber. Public, cached 6hr. Always HTTP 200 — on failure returns
    `{quarters: [], data_limited: true}`.

    Snapshots are reconstructed from point-in-time quarterly financials
    (company_financials). Value axis scales today's fair value by revenue
    ratio; Pulse is only populated for the current quarter (past quarters
    are honestly None since we lack historical insider/promoter data)."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker is required")

    norm_ticker = (ticker or "").strip().upper()
    cache_key = f"prism-history:{norm_ticker}:{quarters}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return JSONResponse(
            content=cached if isinstance(cached, (dict, list)) else _raw_dump(cached),
            headers={
                "X-Cache": "HIT-MEM-RAW",
                "Cache-Control": _PRISM_CACHE_CONTROL,
            },
        )

    try:
        rows = hex_history_service.get_hex_history(ticker, quarters=quarters)
    except Exception as exc:
        logger.warning("prism history failed for %s: %s", ticker, exc)
        return {
            "ticker": norm_ticker,
            "quarters": [],
            "data_limited": True,
            "error": "history_error",
            "disclaimer": hex_history_service.DISCLAIMER,
        }

    response = {
        "ticker": norm_ticker,
        "quarters": rows,
        "data_limited": len(rows) == 0,
        "disclaimer": hex_history_service.DISCLAIMER,
    }
    try:
        cache.set(cache_key, response, ttl=_HISTORY_TTL)
    except Exception:
        pass
    return response


@router.get("/{ticker}")
async def get_prism(ticker: str):
    """Return the consolidated Prism payload for a ticker. Public, no auth,
    cached 1 hour. Always returns HTTP 200 — missing data surfaces as
    `data_limited: true` in the payload."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker is required")

    # Tier-0 RAW dict cache. Skips Pydantic + re-compute of the
    # ~30-50 KB Prism payload. Warm-warm path returns in ~3-5ms
    # vs ~60-120ms for the legacy path that re-serializes the
    # Pydantic object inside prism_service.
    _norm = ticker.upper().strip()
    _raw_key = f"prism:{_norm}:raw"
    try:
        _raw = cache.get(_raw_key)
    except Exception:
        _raw = None
    if _raw is not None:
        return JSONResponse(
            content=_raw,
            headers={
                "X-Cache": "HIT-MEM-RAW",
                "Cache-Control": _PRISM_CACHE_CONTROL,
            },
        )

    result = prism_service.get_prism(ticker)
    try:
        cache.set(_raw_key, _raw_dump(result), ttl=3600)
    except Exception:
        pass
    return result


@router.post("/{ticker}/narrate")
async def narrate_ticker(ticker: str, request: Request):
    """Generate or fetch cached 45-second Prism narration.

    Public (no auth). Cached 24 hours per ticker. Rate-limited to 30
    requests/minute per IP to stop accidental Groq spam. Returns HTTP 200
    even on upstream failure — the service layer falls back to a
    deterministic templated narration."""
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker is required")

    # Rate limit (best-effort client IP)
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _narrate_rate_ok(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many narration requests. Try again in a minute.",
        )

    try:
        return prism_narration_service.get_or_generate_narration(ticker)
    except Exception as exc:  # pragma: no cover — service is designed not to raise
        logger.warning("prism narrate failed for %s: %s", ticker, exc)
        return {
            "ticker": ticker,
            "intro": "Narration is temporarily unavailable.",
            "pillars": [],
            "outro": "",
            "total_duration_ms": 0,
            "error": "narrate_error",
            "disclaimer": prism_service.DISCLAIMER,
        }
