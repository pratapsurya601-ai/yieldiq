# backend/routers/sectors.py
# ═══════════════════════════════════════════════════════════════
# Sector deep-dive endpoints.
#
# GET /api/v1/sectors/{slug}/prism — sector-level Prism payload.
#
# Resolution flow:
#   slug → sector_from_slug → canonical sector name
#   if None: 404 "unknown sector"
#   else:    fetch constituents from stocks + analysis_cache
#            → build_sector_prism → cache 1h → return JSON
#
# Cache TTL: 3600s. The underlying analysis_cache moves slowly
# (compute_for_date runs nightly), so a 1h sector cache is safe
# and removes 99% of the database hits during business hours.
#
# Phase 2 (separate PR): frontend pages that consume this endpoint
# (/sectors and /sectors/[slug]) are intentionally out of scope here.
# This PR ships only the backend aggregator + shared taxonomy lib.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from backend.services.cache_service import cache
from backend.services.sector_aggregator import build_sector_prism
from backend.services.sector_taxonomy import (
    CANONICAL_SECTORS,
    normalize_sector,
    sector_from_slug,
)

logger = logging.getLogger("yieldiq.sectors.router")

router = APIRouter(prefix="/api/v1/sectors", tags=["sectors"])

# 1 hour. The analysis_cache itself updates ~daily, so stale-by-1h
# is well within tolerance. Bump down to 5min if you start seeing
# user complaints about same-day data drift between the stock page
# and the sector page.
_SECTOR_CACHE_TTL = 3600


def _cache_key(slug: str) -> str:
    return f"sector_prism:v1:{slug.lower()}"


def _fetch_constituents(canonical_sector: str) -> list[dict]:
    """Pull all stocks whose sector matches `canonical_sector`,
    along with their latest analysis_cache payload.

    Returns a list of {"ticker", "sector", "analysis"} dicts. The
    aggregator does the actual normalize_sector match — we pull a
    superset (any stock whose raw sector lowercases to a known alias)
    rather than relying on stored canonical labels (which generally
    do NOT exist in prod data, see sector_percentile.py:222 note).
    """
    try:
        from data_pipeline.db import Session
    except Exception as exc:
        logger.warning("sectors: data_pipeline.db unavailable: %s", exc)
        return []
    if Session is None:
        return []

    from sqlalchemy import text  # local import — keep cold-start fast

    db = Session()
    try:
        sql = text(
            """
            WITH latest_ac AS (
                SELECT DISTINCT ON (ticker)
                    ticker, payload
                FROM analysis_cache
                ORDER BY ticker, computed_at DESC
            )
            SELECT s.ticker, s.sector, la.payload
            FROM stocks s
            LEFT JOIN latest_ac la ON la.ticker = s.ticker
            WHERE COALESCE(s.is_active, TRUE) = TRUE
              AND s.sector IS NOT NULL
            """
        )
        rows = db.execute(sql).fetchall()
    except Exception as exc:
        logger.warning("sectors: cohort query failed: %s", exc)
        return []
    finally:
        try:
            db.close()
        except Exception:
            pass

    out: list[dict] = []
    for row in rows:
        # SQLAlchemy Row → dict-ish access. Normalize on the way out
        # so the aggregator can do a single canonical compare.
        try:
            ticker = row[0]
            raw_sector = row[1]
            payload = row[2]
        except Exception:
            continue
        if normalize_sector(raw_sector) != canonical_sector:
            continue
        analysis: dict = {}
        if isinstance(payload, dict):
            analysis = payload
        elif isinstance(payload, (str, bytes, bytearray)):
            try:
                analysis = json.loads(payload)
            except Exception:
                analysis = {}
        out.append({"ticker": ticker, "sector": raw_sector, "analysis": analysis})
    return out


@router.get("/{slug}/prism")
async def get_sector_prism(slug: str) -> dict:
    """Sector-level Prism for a canonical sector slug.

    404 when the slug is not in the canonical 13. The whitelist is
    deliberate — random slugs must not silently return an empty
    aggregate, because the UI would then render a broken card.
    """
    canonical: Optional[str] = sector_from_slug(slug)
    if canonical is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown sector slug '{slug}'. "
                f"Valid slugs map to: {', '.join(CANONICAL_SECTORS)}."
            ),
        )

    cache_key = _cache_key(slug)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    constituents = _fetch_constituents(canonical)
    payload = build_sector_prism(canonical, constituents)
    cache.set(cache_key, payload, ttl=_SECTOR_CACHE_TTL)
    return payload
