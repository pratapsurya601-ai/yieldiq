# backend/services/market_data_service.py
"""
Market data read service — DB-first helpers for live quotes, FX rates,
and index snapshots. All reads hit the Aiven Postgres tables populated
by backend/workers/market_data_refresher.py; the caller decides what to
do with stale rows via the `as_of` field returned in every response.

Write path lives in market_data_refresher. This module is read-only.

Fallback policy: if a row is missing (or the DB is down), these helpers
return None — the caller must fall through to the original yfinance
path and log a warning so production gaps are visible.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text

log = logging.getLogger("yieldiq.market_data")


def _get_session():
    """Return a fresh Aiven session or None if DATABASE_URL is unset."""
    try:
        from data_pipeline.db import Session
    except Exception as exc:
        log.debug("market_data_service: db import failed: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        log.warning("market_data_service: could not open session: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────
# Live quotes
# ─────────────────────────────────────────────────────────────────

def get_live_quote(ticker: str) -> dict | None:
    """Return {ticker, price, change_pct, volume, as_of} or None."""
    if not ticker:
        return None
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(
                "SELECT ticker, price, change_pct, volume, as_of "
                "FROM live_quotes WHERE ticker = :t"
            ),
            {"t": ticker},
        ).fetchone()
        if row is None:
            return None
        return {
            "ticker": row[0],
            "price": float(row[1]) if row[1] is not None else None,
            "change_pct": float(row[2]) if row[2] is not None else None,
            "volume": int(row[3]) if row[3] is not None else None,
            "as_of": row[4],
        }
    except Exception as exc:
        log.warning("get_live_quote(%s) failed: %s", ticker, exc)
        return None
    finally:
        sess.close()


def get_live_quotes_bulk(tickers: Iterable[str]) -> dict[str, dict]:
    """One-shot bulk read for portfolio pages. Missing tickers are
    simply absent from the returned mapping."""
    tickers = [t for t in (tickers or []) if t]
    if not tickers:
        return {}
    sess = _get_session()
    if sess is None:
        return {}
    try:
        rows = sess.execute(
            text(
                "SELECT ticker, price, change_pct, volume, as_of "
                "FROM live_quotes WHERE ticker = ANY(:tix)"
            ),
            {"tix": list(tickers)},
        ).fetchall()
        return {
            r[0]: {
                "ticker": r[0],
                "price": float(r[1]) if r[1] is not None else None,
                "change_pct": float(r[2]) if r[2] is not None else None,
                "volume": int(r[3]) if r[3] is not None else None,
                "as_of": r[4],
            }
            for r in rows
        }
    except Exception as exc:
        log.warning("get_live_quotes_bulk failed (%d tix): %s", len(tickers), exc)
        return {}
    finally:
        sess.close()


# ─────────────────────────────────────────────────────────────────
# FX
# ─────────────────────────────────────────────────────────────────

def get_fx_rate(pair: str = "USDINR") -> float | None:
    """Return the last-known rate for a pair, or None."""
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text("SELECT rate FROM fx_rates WHERE pair = :p"),
            {"p": pair},
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])
    except Exception as exc:
        log.warning("get_fx_rate(%s) failed: %s", pair, exc)
        return None
    finally:
        sess.close()


def get_fx_rate_row(pair: str = "USDINR") -> dict | None:
    """Variant that returns the full row including as_of."""
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text("SELECT pair, rate, as_of FROM fx_rates WHERE pair = :p"),
            {"p": pair},
        ).fetchone()
        if row is None:
            return None
        return {
            "pair": row[0],
            "rate": float(row[1]) if row[1] is not None else None,
            "as_of": row[2],
        }
    except Exception as exc:
        log.warning("get_fx_rate_row(%s) failed: %s", pair, exc)
        return None
    finally:
        sess.close()


# ─────────────────────────────────────────────────────────────────
# Index snapshots
# ─────────────────────────────────────────────────────────────────

def get_index_snapshot(symbol: str) -> dict | None:
    """Return {symbol, name, price, change_pct, as_of} or None."""
    if not symbol:
        return None
    sess = _get_session()
    if sess is None:
        return None
    try:
        row = sess.execute(
            text(
                "SELECT symbol, name, price, change_pct, as_of "
                "FROM index_snapshots WHERE symbol = :s"
            ),
            {"s": symbol},
        ).fetchone()
        if row is None:
            return None
        return {
            "symbol": row[0],
            "name": row[1],
            "price": float(row[2]) if row[2] is not None else None,
            "change_pct": float(row[3]) if row[3] is not None else None,
            "as_of": row[4],
        }
    except Exception as exc:
        log.warning("get_index_snapshot(%s) failed: %s", symbol, exc)
        return None
    finally:
        sess.close()


def get_all_index_snapshots() -> list[dict]:
    """Return every row in index_snapshots, newest first."""
    sess = _get_session()
    if sess is None:
        return []
    try:
        rows = sess.execute(
            text(
                "SELECT symbol, name, price, change_pct, as_of "
                "FROM index_snapshots ORDER BY as_of DESC"
            )
        ).fetchall()
        return [
            {
                "symbol": r[0],
                "name": r[1],
                "price": float(r[2]) if r[2] is not None else None,
                "change_pct": float(r[3]) if r[3] is not None else None,
                "as_of": r[4],
            }
            for r in rows
        ]
    except Exception as exc:
        log.warning("get_all_index_snapshots failed: %s", exc)
        return []
    finally:
        sess.close()
