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
from datetime import datetime, time, timedelta, timezone
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
# Freshness alert (non-blocking)
# ─────────────────────────────────────────────────────────────────

# NSE trading hours: 09:15–15:30 IST (Mon-Fri). IST = UTC+5:30.
# Translated to UTC: 03:45–10:00.
_MKT_OPEN_UTC = time(3, 45)
_MKT_CLOSE_UTC = time(10, 0)
_FRESHNESS_THRESHOLD = timedelta(hours=4)


def _is_market_hours_utc(now_utc: datetime) -> bool:
    """True if `now_utc` falls inside NSE trading hours (Mon-Fri)."""
    if now_utc.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    t = now_utc.timetz().replace(tzinfo=None)
    return _MKT_OPEN_UTC <= t <= _MKT_CLOSE_UTC


def _warn_if_stale(ticker: str, as_of) -> None:
    """Log a warning if `as_of` is older than 4h during NSE market hours.
    Non-blocking — never raises. Helps surface silent pulse_daily failures
    without grepping cron logs."""
    if as_of is None:
        return
    try:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if not _is_market_hours_utc(now):
            return
        age = now - as_of
        if age > _FRESHNESS_THRESHOLD:
            log.warning(
                "canonical_price: live_quotes for %s is stale during "
                "market hours (age=%s, as_of=%s) — pulse_daily may have "
                "skipped this ticker",
                ticker, age, as_of.isoformat(),
            )
    except Exception:
        pass


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


# ─────────────────────────────────────────────────────────────────
# Canonical price cascade (PR INFY-PRICE-CASCADE, 2026-04-30)
# ─────────────────────────────────────────────────────────────────
#
# yfinance .info `currentPrice` has caused multiple prod incidents:
#   • INFY ₹0 (null), INFY ₹1,09,652 (92x unit bug), SBIN ₹1,069,
#     TCS stale.
# We have two higher-trust sources for "what is the price right now":
#   1. live_quotes: refreshed every ~5m during market hours from
#      bhavcopy + corporate actions. Survives yfinance outages.
#   2. daily_prices: NSE EOD bhavcopy. Authoritative for trade-day
#      close. Stale intraday but never wrong.
#
# This cascade is the SINGLE READ-PATH preference rule for the
# `price` field served by the Prism endpoint and the Analysis
# endpoint. Write-path validation lives in
# data_pipeline/sources/yf_info_cache.py — DO NOT couple the two.

def get_canonical_price(
    ticker: str,
    yf_fallback: float | None = None,
) -> float | None:
    """Resolve current price using the trusted cascade.

    Priority:
      1. live_quotes.price (latest by as_of, refreshed ~5m)
      2. daily_prices.close_price (latest trade_date, NSE EOD)
      3. ``yf_fallback`` (yfinance currentPrice already in-hand)
      4. None — caller decides what to do (usually 'unavailable')

    The yfinance value is passed in (not fetched here) so this helper
    stays read-only against the DB and cheap (~1ms warm). Callers
    that already loaded yfinance .info pass that price as the last-
    resort fallback.

    Logs a warning when both live_quotes and daily_prices miss so
    prod gaps are visible without grepping yfinance fallback usage.

    Accepts canonical (TICKER.NS / TICKER.BO) or bare (TICKER) form;
    tries both since the two writers historically disagreed on suffix
    handling (same class of bug as fair_value_history / market_metrics).
    """
    if not ticker:
        return yf_fallback if (yf_fallback or 0) > 0 else None

    bare = ticker.replace(".NS", "").replace(".BO", "")
    canonical = ticker if ticker.endswith((".NS", ".BO")) else f"{bare}.NS"
    candidates = [canonical, bare] if canonical != bare else [canonical]

    sess = _get_session()
    if sess is not None:
        try:
            # 1. live_quotes — preferred (intraday, bhavcopy-backed)
            for cand in candidates:
                try:
                    row = sess.execute(
                        text(
                            "SELECT price, as_of FROM live_quotes "
                            "WHERE ticker = :t "
                            "AND price IS NOT NULL AND price > 0 "
                            "ORDER BY as_of DESC LIMIT 1"
                        ),
                        {"t": cand},
                    ).fetchone()
                except Exception:
                    row = None
                if row and row[0] is not None:
                    try:
                        _warn_if_stale(canonical, row[1])
                        return float(row[0])
                    except Exception:
                        pass

            # 2. daily_prices — NSE EOD fallback
            for cand in candidates:
                try:
                    row = sess.execute(
                        text(
                            "SELECT close_price FROM daily_prices "
                            "WHERE ticker = :t "
                            "AND close_price IS NOT NULL AND close_price > 0 "
                            "ORDER BY trade_date DESC LIMIT 1"
                        ),
                        {"t": cand},
                    ).fetchone()
                except Exception:
                    row = None
                if row and row[0] is not None:
                    try:
                        px = float(row[0])
                        log.warning(
                            "canonical_price: %s missing from live_quotes, "
                            "fell through to daily_prices close=%.2f",
                            canonical, px,
                        )
                        return px
                    except Exception:
                        pass
        finally:
            try:
                sess.close()
            except Exception:
                pass

    # 3. yfinance fallback — only when both DB sources missed
    if yf_fallback is not None:
        try:
            yf_px = float(yf_fallback)
        except Exception:
            yf_px = 0.0
        if yf_px > 0:
            log.warning(
                "canonical_price: %s missing from live_quotes AND "
                "daily_prices, falling back to yfinance=%.2f (untrusted)",
                canonical, yf_px,
            )
            return yf_px

    log.warning(
        "canonical_price: %s has NO price in any source "
        "(live_quotes / daily_prices / yfinance)",
        canonical,
    )
    return None


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
