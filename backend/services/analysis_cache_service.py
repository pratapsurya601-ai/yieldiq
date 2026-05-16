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


def _canonical_cache_key(ticker: str) -> str:
    """
    Canonicalize the ticker BEFORE it is used as a cache row key.

    Why this exists
    ---------------
    The 2026-05-16 data audit flagged that `analysis_cache` had 5,062
    rows but only 3,141 unique tickers — every Indian symbol was
    stored twice, once as `FOO` and once as `FOO.NS`. Two different
    callers (router vs background warmer; HEX vs analysis) each
    passed a different surface form, the table PK is just `ticker`,
    so two rows were UPSERTed against two different keys for what is
    semantically the same security. Dashboard counts were inflated
    by ~60% and stale halves of pairs masked fresh data on the other.

    Fix: every read/write/invalidate funnels through this normalizer
    and reuses the existing `_canonicalize_ticker` from
    `backend/services/analysis/utils.py` which already encodes the
    "bare Indian → .NS" rule (and leaves US/global symbols alone).

    Failures degrade open: if the canonicalize import or the
    known-Indian-bare cache fails, we fall back to the upper-cased
    raw ticker so cache traffic never breaks the request path.
    """
    if not ticker:
        return ticker
    try:
        from backend.services.analysis.utils import _canonicalize_ticker
        return _canonicalize_ticker(ticker)
    except Exception as exc:  # pragma: no cover - import/cache rare failure
        logger.warning(
            "analysis_cache: canonicalize failed for %s (%s); falling back to upper",
            ticker, exc,
        )
        return str(ticker).strip().upper()


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
    # Normalize before key lookup so FOO and FOO.NS hit the same row.
    ticker = _canonical_cache_key(ticker)
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


def _is_poisoned_payload(payload: dict) -> bool:
    """Heuristic: does this payload look like the 2026-05-17 MPHASIS junk?

    The incident: a snapshot-refresh script passed BARE Indian tickers
    (no .NS suffix) into compute. yfinance routed them through the US
    path, returned market_cap=0, and the resulting "data_limited"
    payload UPSERTed over the healthy .NS-keyed cache row.

    Definition of "poisoned" used here (intentionally narrow — false
    positives would skip legitimate writes for genuinely tiny companies,
    which we never want):

      * payload['data_issues'] is a non-empty list/iterable, AND
      * EITHER market_cap_inr == 0 OR market_cap == 0 anywhere in the
        common locations (payload root, ``valuation`` sub-dict, or
        ``insights`` sub-dict).

    The two-condition requirement (data_issues present AND market_cap=0)
    keeps the guard tight: a genuine micro-cap with low market_cap but
    no data_issues passes through; a clean payload missing market_cap
    metadata passes through; only the specific failure-mode pattern is
    rejected.
    """
    if not isinstance(payload, dict):
        return False
    issues = payload.get("data_issues")
    if not issues:
        return False
    # market_cap can live in a few places depending on which compute
    # path produced the payload. Walk the common spots.
    candidates: list = []
    for key in ("market_cap_inr", "market_cap"):
        if key in payload:
            candidates.append(payload.get(key))
    for sub_key in ("valuation", "insights", "quality"):
        sub = payload.get(sub_key)
        if isinstance(sub, dict):
            for key in ("market_cap_inr", "market_cap"):
                if key in sub:
                    candidates.append(sub.get(key))
    for val in candidates:
        try:
            if val is not None and float(val) == 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _existing_row_is_healthy(sess, ticker: str) -> bool:
    """Return True iff an analysis_cache row exists for ``ticker`` and
    that row's payload is NOT itself poisoned. Used by save_cached to
    decide whether to refuse an overwrite by a poisoned payload."""
    try:
        row = sess.execute(
            text("SELECT payload FROM analysis_cache WHERE ticker = :t"),
            {"t": ticker},
        ).fetchone()
    except Exception:
        return False
    if not row:
        return False
    payload = row[0]
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except Exception:
            return False
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return False
    if not isinstance(payload, dict):
        return False
    return not _is_poisoned_payload(payload)


def save_cached(ticker: str, payload: dict, compute_ms: int) -> None:
    """
    UPSERT a cache row. Swallows any DB error — a failed write must not
    break the request (the user already has their computed result).

    Seatbelt: refuses to overwrite an EXISTING healthy row with a
    POISONED payload (market_cap=0 + data_issues). See the
    ``_is_poisoned_payload`` docstring for the exact criteria; this
    catches the 2026-05-17 MPHASIS/COFORGE/PERSISTENT cache-poisoning
    regression at the write boundary.
    """
    sess = _get_session()
    if sess is None:
        return
    # Normalize so two callers passing FOO vs FOO.NS UPSERT the same row.
    ticker = _canonical_cache_key(ticker)
    # Seatbelt: never replace a healthy row with a poisoned payload.
    if _is_poisoned_payload(payload):
        try:
            if _existing_row_is_healthy(sess, ticker):
                logger.warning(
                    "analysis_cache.save_cached: refusing to overwrite "
                    "healthy row for %s with poisoned payload "
                    "(market_cap=0 + data_issues); keeping existing row.",
                    ticker,
                )
                return
            # No healthy prior row — allow the write so a genuine
            # data_limited compute can land for first-time tickers.
            logger.warning(
                "analysis_cache.save_cached: poisoned payload for %s but "
                "no healthy prior row; allowing first-time write.",
                ticker,
            )
        except Exception as exc:
            # If the guard check itself fails, fall through to the
            # normal write — availability of the write path matters
            # more than the guard for pre-existing rows.
            logger.warning(
                "analysis_cache.save_cached: poison guard check failed "
                "for %s: %s; proceeding with write.",
                ticker, exc,
            )
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
    # Delete BOTH the canonical row and any leftover legacy variant
    # (bare/.NS) so a stale ghost row can't survive an explicit
    # invalidate. Pre-2026-05-16 writes may have produced both forms.
    canonical = _canonical_cache_key(ticker)
    raw = str(ticker).strip().upper() if ticker else ticker
    keys = list({k for k in (canonical, raw) if k})
    try:
        sess.execute(
            text("DELETE FROM analysis_cache WHERE ticker = ANY(:tickers)"),
            {"tickers": keys},
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
