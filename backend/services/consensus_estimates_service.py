"""Consensus-estimates reader (analyst slot feeder for the composite).

Read-only, single-ticker lookup against the ``consensus_estimates``
table (migration ``015_consensus_estimates.sql``) which the nightly
``scripts/refresh_consensus.py`` cron populates with real yfinance +
Finnhub coverage (target_mean / target_median / analyst_count), keyed
by the BARE ticker (no ``.NS`` / ``.BO`` suffix).

Why this exists
---------------
The composite valuation's "analyst" estimator slot was fed ONLY by a
live Finnhub call (``finnhub_analyst_service.fetch_analyst_consensus``).
Finnhub's free tier returns ZERO price-target coverage for Indian
``.NS`` symbols, so for essentially the entire NSE universe the analyst
slot resolved to None and the composite collapsed toward DCF-only. The
correct analyst data was already in ``consensus_estimates`` but NOTHING
on the composite path read it. This module is that missing read.

Design notes
------------
- Query the BASE table directly, NOT the ``latest_consensus_per_ticker``
  view. The view orders ``finnhub(1)`` BEFORE ``yfinance(2)`` and
  ``DISTINCT ON (ticker)`` keeps only the first row — so an EMPTY
  Finnhub row (target_mean NULL) can SHADOW a populated yfinance row.
  We instead filter ``target_mean IS NOT NULL`` and prefer the freshest
  populated row regardless of source.
- Mirror the bare-vs-suffixed key normalization used by
  ``benchmark_reconciliation_service`` so an ``INFY.NS`` request matches
  the bare ``INFY`` rows written by the cron.
- NEVER raises. Any DB / import / type issue degrades to ``None`` so the
  analysis response is never broken by this best-effort enrichment.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.consensus_estimates")


# Only consider rows fresher than this — matches the 14-day window the
# `latest_consensus_per_ticker` view enforces, so a month-old target
# after a corporate action does not feed the composite.
CONSENSUS_MAX_AGE_DAYS = 14


# Prefer the freshest POPULATED row for the bare ticker. We bind the
# bare-normalized symbol on the Python side and normalize the stored
# ticker the same way in SQL, so both ``INFY.NS`` and ``INFY`` requests
# resolve to the cron's bare-keyed rows. ``target_mean IS NOT NULL`` is
# the populated-row guard that defeats the empty-finnhub-shadows-yfinance
# problem; ORDER BY fetched_at DESC then yfinance-first breaks ties.
_ONE_TICKER_SQL = """
SELECT
    target_mean,
    target_median,
    target_high,
    target_low,
    analyst_count,
    source,
    fetched_at
FROM consensus_estimates
WHERE UPPER(REPLACE(REPLACE(ticker, '.NS', ''), '.BO', '')) = :bare
  AND target_mean IS NOT NULL
  AND target_mean > 0
  AND fetched_at > now() - (:max_days || ' days')::interval
ORDER BY
    fetched_at DESC,
    CASE source WHEN 'yfinance' THEN 1 WHEN 'finnhub' THEN 2 ELSE 3 END
LIMIT 1
"""


def _bare(ticker: str) -> str:
    """Normalize to the bare upper-case symbol the cron keys rows by."""
    return (
        ticker.strip().upper().replace(".NS", "").replace(".BO", "")
    )


def _get_session():
    """Lazy import so unit tests can run without the analysis stack.

    Mirrors ``benchmark_reconciliation_service._get_session`` — reuses
    the same pipeline session factory the rest of the read-only DB
    layer uses. Returns None when no DB is configured.
    """
    try:
        from backend.services.analysis_cache_service import (
            _get_session as _s,
        )
        return _s()
    except Exception as exc:  # noqa: BLE001
        logger.warning("consensus_estimates: no session: %s", exc)
        return None


def _coerce_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _row_to_consensus(row: dict) -> Optional[dict]:
    """Map a DB row mapping to the normalized consensus dict, or None
    when there is no usable price target. Pure — unit-testable without
    a DB."""
    if not row:
        return None
    target_mean = _coerce_float(row.get("target_mean"))
    target_median = _coerce_float(row.get("target_median"))
    if target_mean is None and target_median is None:
        return None
    count = row.get("analyst_count")
    try:
        count = int(count) if count is not None else 0
    except (TypeError, ValueError):
        count = 0
    fetched_at = row.get("fetched_at")
    as_of = None
    if fetched_at is not None:
        try:
            # `date()` on a datetime → ISO date; str() fallback for
            # any driver that already hands back a string.
            as_of = (
                fetched_at.date().isoformat()
                if hasattr(fetched_at, "date")
                else str(fetched_at)[:10]
            )
        except Exception:
            as_of = None
    return {
        "target_mean": target_mean,
        "target_median": target_median,
        "target_high": _coerce_float(row.get("target_high")),
        "target_low": _coerce_float(row.get("target_low")),
        "analyst_count": count,
        "source": row.get("source") or "yfinance",
        "as_of": as_of,
    }


def get_consensus_for_ticker(
    ticker: str,
    *,
    session=None,
) -> Optional[dict]:
    """Return the best available consensus estimate for ``ticker``.

    Looks up ``consensus_estimates`` for the BARE ticker and returns the
    freshest POPULATED row (``target_mean IS NOT NULL``) as a normalized
    dict::

        {
            "target_mean":   float | None,
            "target_median": float | None,
            "target_high":   float | None,
            "target_low":    float | None,
            "analyst_count": int,
            "source":        str,   # "yfinance" | "finnhub" | ...
            "as_of":         str | None,  # ISO date
        }

    Returns ``None`` when there is no fresh populated row, no DB session,
    or on any error. NEVER raises — this is best-effort enrichment for
    the composite analyst slot and must not fail the analysis response.
    """
    if not ticker:
        return None
    from sqlalchemy import text  # local import; keeps module test-importable
    sess = session if session is not None else _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(_ONE_TICKER_SQL),
            {"bare": _bare(ticker), "max_days": CONSENSUS_MAX_AGE_DAYS},
        ).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "consensus_estimates.get_consensus_for_ticker failed for %s: %s",
            ticker, exc,
        )
        return None
    finally:
        if session is None:
            try:
                sess.close()
            except Exception:
                pass
    return _row_to_consensus(dict(row) if row is not None else {})


__all__ = ["get_consensus_for_ticker", "CONSENSUS_MAX_AGE_DAYS"]
