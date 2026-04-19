# backend/services/analysis_cache_service.py
"""
Persistent (Postgres) tier of the analysis cache.

Tier layout on the /api/v1/analysis/{ticker} hot path:

    in-memory cache_service  (tier 1, 15 min-24 h TTL, per-process)
        |  miss
        v
    analysis_cache table     (tier 2, this module, 24 h by default,
                              shared across all Railway workers)
        |  miss
        v
    AnalysisService.get_full_analysis()   (cold compute, seconds)

Invalidation is automatic on a CACHE_VERSION bump: `get_cached` filters
by `cache_version = CACHE_VERSION`, so rows written against an older
version are treated as a miss and will be overwritten by the next
`save_cached` call.

All DB operations are best-effort: if the Aiven session is unavailable
or a query fails, we log and return None (on read) or swallow (on
write) so the user request continues to serve from compute. Cache
availability must never degrade availability of the primary endpoint.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

from sqlalchemy import text

from backend.services.cache_service import CACHE_VERSION

logger = logging.getLogger("yieldiq.analysis_cache")


def _fire_revalidate(ticker: str) -> None:
    """
    Fire-and-forget POST to the Next.js on-demand revalidation endpoint
    so the SEO page (/stocks/{ticker}/fair-value) refreshes its cached
    HTML immediately after we write a new analysis row. Without this
    the page can serve stale numbers for up to its time-based ISR
    window (currently 300s).

    Runs in a daemon thread — must never block or break save_cached.
    Skips silently if either env var is missing (local dev / preview
    deploys without the secret configured). Any HTTP / network error
    is logged at WARNING and swallowed.
    """
    url = os.environ.get("FRONTEND_REVALIDATE_URL")
    secret = os.environ.get("REVALIDATE_SECRET")
    if not url or not secret:
        return

    def _post() -> None:
        try:
            import requests  # local import — keeps module import cheap
            requests.post(
                url,
                json={"path": f"/stocks/{ticker}/fair-value"},
                headers={"x-revalidate-secret": secret},
                timeout=3,
            )
        except Exception as exc:
            logger.warning(
                "analysis_cache: revalidate POST failed for %s: %s",
                ticker, exc,
            )

    try:
        threading.Thread(target=_post, daemon=True).start()
    except Exception as exc:
        logger.warning(
            "analysis_cache: revalidate thread spawn failed for %s: %s",
            ticker, exc,
        )


def _get_session():
    """
    Lazily acquire a pipeline SQLAlchemy session. Returns None when
    DATABASE_URL is not configured (local dev without Aiven) so callers
    can skip the DB tier without blowing up.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover - import failures are rare
        logger.warning("analysis_cache: pipeline db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        logger.warning("analysis_cache: Session() failed: %s", exc)
        return None


def get_cached(ticker: str, max_age_hours: int = 24) -> Optional[dict]:
    """
    Return the cached analysis payload (as a plain dict) if a row
    exists for `ticker` with the current CACHE_VERSION and a
    `computed_at` newer than `max_age_hours` ago. Otherwise None.

    Never raises: DB problems are logged and treated as a miss.
    """
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(
                """
                SELECT payload
                FROM analysis_cache
                WHERE ticker = :ticker
                  AND cache_version = :version
                  AND computed_at > now() - (:hours || ' hours')::interval
                """
            ),
            {
                "ticker": ticker,
                "version": str(CACHE_VERSION),
                "hours": str(max_age_hours),
            },
        ).fetchone()
        if not row:
            return None
        payload = row[0]
        # psycopg2 returns JSONB as a dict already; psycopg3 / some
        # drivers return a str. Handle both.
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                logger.warning("analysis_cache: payload not valid JSON for %s", ticker)
                return None
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception as exc:
        logger.warning("analysis_cache.get_cached failed for %s: %s", ticker, exc)
        return None
    finally:
        try:
            sess.close()
        except Exception:
            pass


def save_cached(ticker: str, payload: dict, compute_ms: int) -> None:
    """
    UPSERT a cache row. Swallows any DB error — a failed write must not
    break the request (the user already has their computed result).
    """
    sess = _get_session()
    if sess is None:
        return
    try:
        # default=str handles datetime/Decimal/etc. that may sneak
        # through from the analysis layer.
        blob = json.dumps(payload, default=str)
        sess.execute(
            text(
                """
                INSERT INTO analysis_cache (ticker, payload, computed_at, cache_version, compute_ms)
                VALUES (:ticker, CAST(:payload AS JSONB), now(), :version, :compute_ms)
                ON CONFLICT (ticker) DO UPDATE SET
                    payload       = EXCLUDED.payload,
                    computed_at   = EXCLUDED.computed_at,
                    cache_version = EXCLUDED.cache_version,
                    compute_ms    = EXCLUDED.compute_ms
                """
            ),
            {
                "ticker": ticker,
                "payload": blob,
                "version": str(CACHE_VERSION),
                "compute_ms": int(compute_ms),
            },
        )
        sess.commit()
        # Fresh row written — kick the SEO page so the CDN-cached HTML
        # picks up the new numbers without waiting for the time-based
        # ISR window. Best-effort; runs in a daemon thread.
        try:
            _fire_revalidate(ticker)
        except Exception as exc:
            logger.warning(
                "analysis_cache: post-write revalidate hook failed for %s: %s",
                ticker, exc,
            )
    except Exception as exc:
        logger.warning("analysis_cache.save_cached failed for %s: %s", ticker, exc)
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        try:
            sess.close()
        except Exception:
            pass


def invalidate(ticker: str) -> None:
    """
    Delete the cache row for `ticker`. Best-effort; errors are logged.
    """
    sess = _get_session()
    if sess is None:
        return
    try:
        sess.execute(
            text("DELETE FROM analysis_cache WHERE ticker = :ticker"),
            {"ticker": ticker},
        )
        sess.commit()
    except Exception as exc:
        logger.warning("analysis_cache.invalidate failed for %s: %s", ticker, exc)
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        try:
            sess.close()
        except Exception:
            pass


__all__ = ["get_cached", "save_cached", "invalidate"]
