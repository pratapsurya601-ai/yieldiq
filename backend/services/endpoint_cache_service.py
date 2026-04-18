# backend/services/endpoint_cache_service.py
"""
Persistent KV cache for slow authenticated endpoints that can't be
cached at the CDN layer (per-user / per-tier responses, but where
the underlying data is ticker-shared).

Survives Railway redeploys. Complements the in-memory cache_service
(tier 1) with a tier 2 that's shared across workers and cold-restart
resilient.

Keys follow a flat namespace convention:
    "{endpoint}:{ticker}:{param-hash}"
Example:
    "financials:TCS.NS:annual:5"
    "fv-history:TCS.NS:3"

All operations are best-effort — DB issues are logged and degrade
to a cache miss. Never raises.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger("yieldiq.endpoint_cache")


def _get_session():
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        logger.warning("endpoint_cache: db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        logger.warning("endpoint_cache: Session() failed: %s", exc)
        return None


def get(key: str) -> Optional[dict]:
    """Return the cached value for `key` if present + not expired, else None."""
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(
                """
                SELECT value
                FROM endpoint_cache
                WHERE key = :k AND expires_at > now()
                """
            ),
            {"k": key},
        ).fetchone()
        if not row:
            return None
        payload = row[0]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return None
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception as exc:
        logger.warning("endpoint_cache.get failed for %s: %s", key, exc)
        return None
    finally:
        try:
            sess.close()
        except Exception:
            pass


def set(key: str, value: dict, ttl_hours: int = 24) -> None:
    """UPSERT a cache row. Swallows any DB error."""
    sess = _get_session()
    if sess is None:
        return
    try:
        blob = json.dumps(value, default=str)
        sess.execute(
            text(
                """
                INSERT INTO endpoint_cache (key, value, expires_at)
                VALUES (:k, CAST(:v AS JSONB), now() + (:ttl || ' hours')::interval)
                ON CONFLICT (key) DO UPDATE SET
                    value      = EXCLUDED.value,
                    expires_at = EXCLUDED.expires_at,
                    created_at = now()
                """
            ),
            {"k": key, "v": blob, "ttl": str(ttl_hours)},
        )
        sess.commit()
    except Exception as exc:
        logger.warning("endpoint_cache.set failed for %s: %s", key, exc)
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        try:
            sess.close()
        except Exception:
            pass


def delete(key: str) -> None:
    sess = _get_session()
    if sess is None:
        return
    try:
        sess.execute(text("DELETE FROM endpoint_cache WHERE key = :k"), {"k": key})
        sess.commit()
    except Exception:
        try:
            sess.rollback()
        except Exception:
            pass
    finally:
        try:
            sess.close()
        except Exception:
            pass


__all__ = ["get", "set", "delete"]
