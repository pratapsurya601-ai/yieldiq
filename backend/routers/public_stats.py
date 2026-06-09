# backend/routers/public_stats.py
# ═══════════════════════════════════════════════════════════════
# Public coverage-stats endpoint for the logged-out landing
# "trust strip" — 4 real numbers sourced from live DB tables
# so a first-time visitor sees concrete coverage instead of
# vanity prose. No auth; cached 1h at router level.
#
# SEBI note: every field is factual coverage data (counts,
# timestamps, source labels). NEVER add fields that imply
# quality of picks ("X winning trades", "Y% accuracy") — those
# would be advisory claims under SEBI IA Regs 2013.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.services.cache_service import cache

logger = logging.getLogger("yieldiq.public_stats")

router = APIRouter(prefix="/api/v1/public", tags=["public"])


# Static data-source labels — these are the ingestors the engine
# actually reads from in production. Kept in-code (not env-driven)
# because the public claim is "these sources, full stop"; an
# operator toggling env should not silently change the disclosure.
DATA_SOURCES: list[str] = ["BSE XBRL", "NSE", "yfinance"]

# Cache key + TTL. 1 hour matches the brief; the underlying counts
# move ~daily, so an hour of staleness is invisible to visitors.
_CACHE_KEY = "public:coverage-stats:v1"
_CACHE_TTL_SECONDS = 3600


def _get_pipeline_session():
    """Lazy import + open the shared Aiven Postgres session.

    Mirrors backend/routers/public.py:_get_db_session — kept local
    so this router has no cross-router import dependency.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
        if Session is None:
            return None
        return Session()
    except Exception as exc:
        logger.warning("public-stats: pipeline session unavailable: %s", exc)
        return None


def _safe_close(sess) -> None:
    if sess is None:
        return
    try:
        sess.close()
    except Exception:
        pass


def _scalar(sess, sql: str) -> Optional[int]:
    """Run a COUNT-style scalar query; log + return None on failure
    so the endpoint always responds 200 with the fields it can
    produce, never 500 because one column was missing."""
    try:
        row = sess.execute(text(sql)).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])
    except Exception as exc:
        logger.info("public-stats scalar failed [%s]: %s", sql[:60], exc)
        return None


def _logo_coverage_pct() -> Optional[int]:
    """Compute % of NIFTY 500 constituents that have a real PNG logo
    on disk. Reads backend/data/nifty500_tickers.json (the curated
    list shipped by PR #755) and checks each ticker against
    frontend/public/logos/<TICKER>.png.

    Returns an int percent (0-100) or None if either reference is
    unavailable. Cached for the same hour as the parent payload.
    """
    try:
        import json
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        tickers_path = os.path.join(
            repo_root, "backend", "data", "nifty500_tickers.json"
        )
        logos_dir = os.path.join(
            repo_root, "frontend", "public", "logos"
        )
        if not os.path.exists(tickers_path) or not os.path.isdir(logos_dir):
            return None
        with open(tickers_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        tickers = payload.get("tickers") or []
        if not tickers:
            return None
        have = sum(
            1 for t in tickers
            if os.path.exists(os.path.join(logos_dir, f"{t}.png"))
        )
        return int(round(100.0 * have / len(tickers)))
    except Exception as exc:
        logger.info("public-stats: logo-coverage compute failed: %s", exc)
        return None


def _latest_manifest_applied_at() -> Optional[str]:
    """Most-recent applied_at across the cache_invalidation_manifest.

    The manifest is a Python data structure (not a DB table) — see
    backend/services/cache_invalidation_manifest.py. Each entry's
    applied_at is the wall-clock time the engine change rolled out.
    The newest entry tells a visitor "the model was last refined
    this recently", which is the user-meaningful "last engine
    update" signal the brief asks for.
    """
    try:
        from backend.services.cache_invalidation_manifest import MANIFEST
        applied = [
            e.get("applied_at") for e in MANIFEST
            if isinstance(e, dict) and e.get("applied_at") is not None
        ]
        if not applied:
            return None
        newest: datetime = max(applied)  # type: ignore[type-var]
        # Manifest stores tz-aware UTC datetimes; isoformat preserves
        # the offset so the frontend can render in IST without re-
        # localising. Tests assert this is an ISO-8601 string.
        return newest.isoformat()
    except Exception as exc:
        logger.info("public-stats: manifest read failed: %s", exc)
        return None


def _build_stats_payload() -> dict[str, Any]:
    """Compose the response dict from the live DB + manifest.

    Each field is independently fault-tolerant: if a particular
    counter cannot be resolved, the key is OMITTED from the
    response (rather than emitting 0 or null). The frontend
    treats a missing key as "hide this tile" so a partial
    outage degrades gracefully instead of showing "0 stocks".
    """
    out: dict[str, Any] = {
        # as_of is when THIS response was assembled — distinct from
        # last_engine_update (when the model last changed) so the
        # consumer can tell stale-from-cache apart from no-recent-
        # engine-change.
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data_sources": list(DATA_SOURCES),
    }

    sess = _get_pipeline_session()
    if sess is not None:
        try:
            stocks_covered = _scalar(
                sess,
                "SELECT COUNT(*) FROM stocks WHERE is_active = TRUE",
            )
            if stocks_covered is not None and stocks_covered > 0:
                out["stocks_covered"] = stocks_covered

            dcf_count = _scalar(
                sess, "SELECT COUNT(*) FROM analysis_cache",
            )
            if dcf_count is not None and dcf_count > 0:
                out["dcf_valuations_generated"] = dcf_count

            sectors_count = _scalar(
                sess,
                "SELECT COUNT(DISTINCT sector) FROM stocks "
                "WHERE is_active = TRUE AND sector IS NOT NULL "
                "AND sector <> ''",
            )
            if sectors_count is not None and sectors_count > 0:
                out["sectors_covered"] = sectors_count

            # bank_quarters_backfilled — counts rows in financials
            # tagged as quarterly. Best-effort; the column shape has
            # shifted across migrations, so the inner _scalar swallows
            # an UndefinedColumn and we just omit the key.
            banks = _scalar(
                sess,
                "SELECT COUNT(*) FROM financials "
                "WHERE period_type = 'quarterly'",
            )
            if banks is not None and banks > 0:
                out["bank_quarters_backfilled"] = banks
        finally:
            _safe_close(sess)

    logo_pct = _logo_coverage_pct()
    if logo_pct is not None and logo_pct > 0:
        out["nifty500_logo_coverage_pct"] = logo_pct

    last_engine = _latest_manifest_applied_at()
    if last_engine is not None:
        out["last_engine_update"] = last_engine

    return out


@router.get("/coverage-stats")
async def get_coverage_stats():
    """Real coverage counters for the logged-out landing trust strip.

    Response shape (every key OPTIONAL — missing keys mean "hide
    that tile"; clients MUST tolerate any subset)::

        {
          "as_of": "2026-06-09T08:00:00+05:30",
          "stocks_covered": 2347,
          "nifty500_logo_coverage_pct": 95,
          "dcf_valuations_generated": 12483,
          "data_sources": ["BSE XBRL", "NSE", "yfinance"],
          "last_engine_update": "2026-06-07T12:00:00+00:00",
          "bank_quarters_backfilled": 174,
          "sectors_covered": 18
        }

    SEBI: every field is descriptive coverage. NO field implies
    quality of picks (no "X winning trades", no "Y% accuracy").
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={
                "Cache-Control": (
                    "public, s-maxage=3600, stale-while-revalidate=7200"
                ),
                "X-Cache": "HIT",
            },
        )

    payload = _build_stats_payload()
    cache.set(_CACHE_KEY, payload, ttl=_CACHE_TTL_SECONDS)
    return JSONResponse(
        content=payload,
        headers={
            "Cache-Control": (
                "public, s-maxage=3600, stale-while-revalidate=7200"
            ),
            "X-Cache": "MISS",
        },
    )
