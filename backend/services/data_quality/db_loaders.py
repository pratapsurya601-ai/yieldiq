"""Production DB loaders for validators (Phase A.2.1, 2026-05-23).

A.1 deferred wiring the live Neon read path — every validator's
`_load_sample_from_db` raised NotImplementedError so the orchestrator
could be smoke-tested without DATABASE_URL. A.2.1 wires the actual
loaders, one helper per (table, sample) pair.

Design rules
------------
- All loaders accept an optional ``conn_factory`` so tests can inject a
  callable that returns a connection-like object (e.g. a fake exposing
  ``cursor()`` with the standard DB-API surface). Production passes
  None and we open a psycopg2 connection from DATABASE_URL.
- DATABASE_URL is gracefully optional. A loader called without it
  returns ``None`` rather than raising. The orchestrator interprets
  None as "skip this validator with a clear log line", same as the
  A.1 NotImplementedError path.
- Loaders never compute thresholds — they only fetch raw counts /
  samples / column lists. Threshold logic stays in checks.py and the
  per-validator modules so it's reviewable in isolation.
- Loaders use parameterised queries everywhere. No string interpolation
  of table names from caller input; everything in here is a literal.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("yieldiq.data_quality.db_loaders")

# How far back to look when computing "prior" row counts. Daily
# populators are stable run-to-run so a 1-day baseline is enough;
# weekly populators (stocks) compare against ~7d prior.
_PRIOR_LOOKBACK_DAYS_DAILY = 1
_PRIOR_LOOKBACK_DAYS_WEEKLY = 7

# Sample size for null-rate checks. Drawing the full table is wasteful;
# 5k is statistically more than enough at our universe size (~2k tickers).
_NULL_SAMPLE_LIMIT = 5000


@contextmanager
def _open_connection(conn_factory: Optional[Callable[[], Any]] = None) -> Iterator[Optional[Any]]:
    """Yield a DB connection or None when DATABASE_URL is unset.

    The factory indirection exists so tests can inject a fake without
    monkeypatching psycopg2. Production passes nothing and we connect
    to ``$DATABASE_URL``; if that env var is missing we yield None and
    the caller short-circuits to a "skipped" outcome.
    """
    if conn_factory is not None:
        conn = conn_factory()
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                logger.debug("conn.close() raised", exc_info=True)
        return

    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.info("DATABASE_URL unset; data-quality loader returning None")
        yield None
        return

    import psycopg2  # imported lazily so unit tests don't need it

    conn = psycopg2.connect(url)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            logger.debug("psycopg2 conn.close() raised", exc_info=True)


def _columns_of(cur: Any, table: str) -> list[str]:
    """Return the column list of ``table`` from information_schema."""
    cur.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = %s
         ORDER BY ordinal_position
        """,
        (table,),
    )
    return [row[0] for row in cur.fetchall()]


def _scalar(cur: Any, sql: str, params: tuple = ()) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def load_daily_prices_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    """Load a DailyPricesSample for the live validator.

    Returns None when DATABASE_URL is unset (orchestrator skip path).
    """
    from .validators.daily_prices import (
        ADJ_CLOSE_DISTINCTNESS_TICKERS,
        ADJ_CLOSE_PRE_DATE,
        DailyPricesSample,
        PLAUSIBILITY_BANDS,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "daily_prices")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM daily_prices") or 0)
            # "prior" = rows as of N days ago. We approximate this by
            # counting rows whose trade_date is <= (today - lookback).
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM daily_prices "
                "WHERE trade_date <= (CURRENT_DATE - INTERVAL '%s days')" % _PRIOR_LOOKBACK_DAYS_DAILY,
            ) or 0)
            close_null_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ("
                "  SELECT close_price FROM daily_prices ORDER BY trade_date DESC LIMIT %s"
                ") s WHERE close_price IS NULL",
                (_NULL_SAMPLE_LIMIT,),
            ) or 0)
            sample_size = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ("
                "  SELECT 1 FROM daily_prices ORDER BY trade_date DESC LIMIT %s"
                ") s",
                (_NULL_SAMPLE_LIMIT,),
            ) or 0)
            last_update: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(trade_date)::timestamp FROM daily_prices",
            )

            latest_close: dict[str, Optional[float]] = {}
            for ticker in PLAUSIBILITY_BANDS:
                latest_close[ticker] = _scalar(
                    cur,
                    "SELECT close_price FROM daily_prices "
                    "WHERE ticker = %s ORDER BY trade_date DESC LIMIT 1",
                    (ticker,),
                )

            adj_close_eq_close_fraction: dict[str, float] = {}
            for ticker in ADJ_CLOSE_DISTINCTNESS_TICKERS:
                total = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM daily_prices "
                    "WHERE ticker = %s AND trade_date < %s "
                    "AND close_price IS NOT NULL AND adj_close IS NOT NULL",
                    (ticker, ADJ_CLOSE_PRE_DATE),
                ) or 0)
                if total == 0:
                    continue
                equal = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM daily_prices "
                    "WHERE ticker = %s AND trade_date < %s "
                    "AND close_price IS NOT NULL AND adj_close IS NOT NULL "
                    "AND ABS(close_price - adj_close) < 0.01",
                    (ticker, ADJ_CLOSE_PRE_DATE),
                ) or 0)
                adj_close_eq_close_fraction[ticker] = equal / total

        return DailyPricesSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            close_null_count=close_null_count,
            sample_size=sample_size,
            schema_columns=schema_columns,
            last_update=last_update,
            latest_close=latest_close,
            adj_close_eq_close_fraction=adj_close_eq_close_fraction,
        )


def load_stocks_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    """Load a StocksSample for the live validator."""
    from .validators.stocks import CANARY_INDUSTRY_TOKENS, StocksSample

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM stocks WHERE is_active = TRUE") or 0)
            # prior_row_count: stocks is updated weekly, no time-series
            # column to slice by, so we use updated_at as a coarse proxy.
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM stocks "
                "WHERE is_active = TRUE AND updated_at <= (now() - INTERVAL '%s days')"
                % _PRIOR_LOOKBACK_DAYS_WEEKLY,
            ) or 0)
            industry_empty_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM stocks "
                "WHERE is_active = TRUE AND (industry IS NULL OR TRIM(industry) = '')",
            ) or 0)
            sector_empty_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM stocks "
                "WHERE is_active = TRUE AND (sector IS NULL OR TRIM(sector) = '')",
            ) or 0)
            is_active_null_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM stocks WHERE is_active IS NULL",
            ) or 0)
            sample_size = int(_scalar(cur, "SELECT COUNT(*) FROM stocks") or 0)
            hdfcbank_industry: Optional[str] = _scalar(
                cur,
                "SELECT industry FROM stocks WHERE ticker = %s LIMIT 1",
                ("HDFCBANK",),
            )
            last_update: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(updated_at) FROM stocks",
            )
            # A.2.2: fetch broader canary industry set.
            canary_industries: dict[str, Optional[str]] = {}
            for ticker in CANARY_INDUSTRY_TOKENS:
                canary_industries[ticker] = _scalar(
                    cur,
                    "SELECT industry FROM stocks WHERE ticker = %s LIMIT 1",
                    (ticker,),
                )

        return StocksSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            industry_empty_count=industry_empty_count,
            sector_empty_count=sector_empty_count,
            is_active_null_count=is_active_null_count,
            sample_size=sample_size,
            hdfcbank_industry=hdfcbank_industry,
            last_update=last_update,
            canary_industries=canary_industries,
        )


__all__ = [
    "load_daily_prices_sample",
    "load_stocks_sample",
]
