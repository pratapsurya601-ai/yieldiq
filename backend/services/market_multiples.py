# backend/services/market_multiples.py
# ═══════════════════════════════════════════════════════════════
# Latest PE / PB per ticker from `market_metrics`.
#
# v_composite_warm_path_estimator_fix_2026_06_11
#
# Why this exists
# ───────────────
# The peer-multiples estimator (multiples_fv) and the per-cohort
# sector-median chips both need the ticker's own PE / PB and the
# cohort medians. Historically both read `quality.pe_ratio` /
# `quality.pb_ratio` off cached analysis payloads — but the
# AnalysisResponse `QualityOutput` model has NEVER carried those
# fields, so every lookup returned None and the multiples slot of
# the composite stayed empty on every request (verified on the
# Banking cohort: all 12 cached payloads surface pe_ratio=None on
# /api/v1/public/sector/banking).
#
# The authoritative per-ticker multiples live in the
# `market_metrics` table (same source the screener, peer table and
# hex Value pillar use). This module is a thin, read-only,
# TTL-cached accessor over that table so request-path callers pay
# a dict lookup after first warm-up.
#
# Contract
# ────────
#   get_ticker_multiples("HDFCBANK.NS")  -> {"pe": 16.7, "pb": 2.0}
#   get_multiples_for_tickers([...])     -> {"HDFCBANK.NS": {...}, ...}
#
# Missing rows / DB-down / no DATABASE_URL all degrade to
# {"pe": None, "pb": None} — callers treat None as "hide the chip".
# Never raises.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import threading
import time
from typing import Iterable, Optional

logger = logging.getLogger("yieldiq.market_multiples")

# Same TTL the sector-median chips use (sector_medians_for_ticker).
_TTL_SECONDS = 15 * 60

_EMPTY: dict[str, Optional[float]] = {"pe": None, "pb": None}

_cache_lock = threading.Lock()
# ticker (suffixed, upper) -> (monotonic_ts, {"pe": ..., "pb": ...})
_cache: dict[str, tuple[float, dict[str, Optional[float]]]] = {}


def _coerce_pos(v) -> Optional[float]:
    """Positive-finite float or None (drops zero / negative / NaN)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    return f


def _canonical(ticker: str) -> str:
    """Cache / result keying — suffixed symbol (HDFCBANK.NS)."""
    s = (ticker or "").strip().upper()
    if not s:
        return ""
    if "." not in s:
        s = f"{s}.NS"
    return s


def _bare(ticker: str) -> str:
    """`market_metrics.ticker` keying — BARE symbol (HDFCBANK).

    The table stores exchange-suffix-free tickers (verified live:
    ``SELECT ticker FROM market_metrics WHERE ticker ILIKE
    '%HDFCBANK%'`` returns ``HDFCBANK``, never ``HDFCBANK.NS``).
    Querying with suffixed symbols silently matches zero rows, which
    is exactly the bug this module exists to fix — so the SQL below
    must always be fed bare symbols.
    """
    s = (ticker or "").strip().upper()
    for suffix in (".NS", ".BO", ".NSE", ".BSE"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def _get_session():
    """Pipeline SQLAlchemy session, or None when DB is unavailable.

    Mirrors analysis_cache_service._get_session — returns None when
    DATABASE_URL is not configured so request paths degrade cleanly.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover — import failures rare
        logger.warning("market_multiples: pipeline db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        logger.warning("market_multiples: Session() failed: %s", exc)
        return None


def _fetch_rows(tickers: list[str]) -> dict[str, dict[str, Optional[float]]]:
    """One query for the latest PE / PB of each requested ticker.

    Uses the same DISTINCT ON precedence the sector-percentile cohort
    builder uses (best data_quality_rank first, then most recent
    trade_date) so this module never disagrees with the hex Value
    pillar on which row is "latest".
    """
    out: dict[str, dict[str, Optional[float]]] = {
        t: dict(_EMPTY) for t in tickers
    }
    if not tickers:
        return out
    # The table keys BARE symbols; requests/results key canonical
    # (suffixed) symbols. Build the reverse map so each DB row lands
    # on every canonical alias that asked for it.
    bare_to_canon: dict[str, list[str]] = {}
    for t in tickers:
        bare_to_canon.setdefault(_bare(t), []).append(t)
    sess = _get_session()
    if sess is None:
        return out
    try:
        from sqlalchemy import text
        rows = sess.execute(
            text(
                """
                SELECT DISTINCT ON (mm.ticker)
                    mm.ticker, mm.pe_ratio, mm.pb_ratio
                FROM market_metrics mm
                WHERE mm.ticker = ANY(:tickers)
                ORDER BY mm.ticker,
                         COALESCE(mm.data_quality_rank, 50) ASC,
                         mm.trade_date DESC
                """
            ),
            {"tickers": [b for b in bare_to_canon if b]},
        ).fetchall()
        for row in rows:
            try:
                ticker, pe, pb = row[0], row[1], row[2]
            except Exception:
                continue
            for key in bare_to_canon.get(_bare(str(ticker)), ()):
                if key in out:
                    out[key] = {
                        "pe": _coerce_pos(pe), "pb": _coerce_pos(pb),
                    }
    except Exception as exc:
        logger.warning("market_multiples: fetch failed: %s", exc)
    finally:
        try:
            sess.close()
        except Exception:
            pass
    return out


def get_multiples_for_tickers(
    tickers: Iterable[str],
) -> dict[str, dict[str, Optional[float]]]:
    """Batch lookup. Returns {canonical_ticker: {"pe": .., "pb": ..}}.

    Served from the in-process TTL cache where possible; one SQL
    round-trip for the misses. Never raises.
    """
    canon = [c for c in (_canonical(t) for t in tickers) if c]
    result: dict[str, dict[str, Optional[float]]] = {}
    misses: list[str] = []
    now = time.monotonic()
    with _cache_lock:
        for t in canon:
            entry = _cache.get(t)
            if entry is not None and (now - entry[0]) < _TTL_SECONDS:
                result[t] = dict(entry[1])
            else:
                misses.append(t)
    if misses:
        fetched = _fetch_rows(misses)
        with _cache_lock:
            for t, vals in fetched.items():
                _cache[t] = (now, dict(vals))
        result.update(fetched)
    return result


def get_ticker_multiples(ticker: str) -> dict[str, Optional[float]]:
    """Single-ticker convenience wrapper. Never raises."""
    try:
        canon = _canonical(ticker)
        if not canon:
            return dict(_EMPTY)
        return get_multiples_for_tickers([canon]).get(canon, dict(_EMPTY))
    except Exception as exc:
        logger.warning(
            "market_multiples: get_ticker_multiples failed for %s: %s",
            ticker, exc,
        )
        return dict(_EMPTY)


def _reset_cache_for_tests() -> None:
    """Test hook — clears the in-process TTL cache."""
    with _cache_lock:
        _cache.clear()
