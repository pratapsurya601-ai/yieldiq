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
# PR #317: hard reject staleness — above this age the live_quotes row
# is considered unreliable (likely pre-split / pre-corp-action / yfinance
# hiccup never overwritten) and the cascade falls through to daily_prices
# instead of serving a 10×-off price to the DCF engine.
# Symptom that motivated this: HINDPETRO 2026-05-18 DCF used price=₹3870
# (stored 9 days earlier, real CMP ~₹400) which crushed the FV/CMP ratio
# to 0.01 and broke the verdict gate.
_HARD_STALE_THRESHOLD = timedelta(days=2)

# Day-58 (2026-05-21): defensive gates against TCS-class price bugs.
#
# Two failure modes the existing cascade does NOT catch:
#
#   (a) daily_prices stuck for months. If NSE bhavcopy ingestion
#       silently stopped for a ticker, daily_prices keeps serving the
#       last good close forever. TCS observed 2026-05-21 at ₹2,327
#       (its Nov-2025 low), real market ~₹3,500 (+50% off).
#
#   (b) Outlier in a fresh row. A 92x unit bug, an FX-conversion bug,
#       or a wrong-ticker resolution can pass through every staleness
#       check because the timestamp is new. INFY 2026-04 hit
#       ₹1,09,652 from yfinance .info this way.
#
# Defenses:
#   - Daily-prices staleness gate: reject close_price rows older than
#     _DAILY_PRICES_HARD_STALE_DAYS trading days.
#   - Outlier gate: compare any served price against the 30-day median
#     of daily_prices for the same ticker. Reject if deviation exceeds
#     _OUTLIER_TOLERANCE_PCT. Returns None → upstream renders
#     "data_limited" rather than a confidently-wrong number.
#
# Both gates fail OPEN if the comparison data isn't available (new
# listings, fresh tickers). They only reject when we have ENOUGH
# evidence to know the served value is anomalous.
_DAILY_PRICES_HARD_STALE_DAYS = 7      # 7 trading days (~10 calendar)
_OUTLIER_TOLERANCE_PCT = 0.40          # 40% deviation from 30d median
_OUTLIER_MIN_HISTORY = 5               # need ≥5 closes to validate


def _daily_prices_baseline(
    candidates: list[str], sess
) -> tuple[float, "datetime | None"] | None:
    """Return (median_close, latest_trade_date) over last 30 closes
    from daily_prices, or None if insufficient history.

    Iterates candidates so callers can pass [canonical, bare] without
    pre-knowing which form the writer used. Returns the FIRST candidate
    with enough history rather than merging across forms (avoids the
    bare/canonical drift bug that's bitten us in fair_value_history).
    """
    for cand in candidates:
        try:
            rows = sess.execute(
                text(
                    "SELECT close_price, trade_date FROM daily_prices "
                    "WHERE ticker = :t AND close_price IS NOT NULL "
                    "AND close_price > 0 "
                    "ORDER BY trade_date DESC LIMIT 30"
                ),
                {"t": cand},
            ).fetchall()
        except Exception:
            continue
        if len(rows) >= _OUTLIER_MIN_HISTORY:
            closes = sorted(float(r[0]) for r in rows)
            median = closes[len(closes) // 2]
            latest_trade_date = rows[0][1]
            return median, latest_trade_date
    return None


def _is_price_outlier(price: float, median: float) -> bool:
    """True if `price` deviates more than _OUTLIER_TOLERANCE_PCT from
    `median`. Fails CLOSED on zero/negative median (rare; treat as
    insufficient evidence and skip the gate)."""
    if median <= 0 or price <= 0:
        return False
    return abs(price - median) / median > _OUTLIER_TOLERANCE_PCT


def _is_daily_prices_stale(latest_trade_date) -> bool:
    """True if the latest daily_prices row for this ticker is older
    than _DAILY_PRICES_HARD_STALE_DAYS calendar days. Liberal on the
    boundary (7 days) since 7 trading days is ~10 calendar including
    weekends + holidays."""
    if latest_trade_date is None:
        return False
    try:
        # latest_trade_date is a date or datetime; normalize to date.
        if hasattr(latest_trade_date, "date"):
            ld = latest_trade_date.date()
        else:
            ld = latest_trade_date
        from datetime import date as _date_cls
        age_days = (_date_cls.today() - ld).days
        return age_days > _DAILY_PRICES_HARD_STALE_DAYS
    except Exception:
        return False


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
            # Day-58 (2026-05-21): compute the 30-day daily_prices
            # baseline ONCE up front so we can outlier-check every
            # candidate price the cascade returns. Failing the baseline
            # lookup (new listing, no history) leaves baseline=None and
            # the outlier gate falls open — never falsely rejects.
            _baseline = _daily_prices_baseline(candidates, sess)

            def _accept(px: float, source: str) -> "float | None":
                """Apply the outlier gate and return px if it passes,
                else None. Centralised so every cascade rung uses the
                same logic."""
                if _baseline is None:
                    return px  # insufficient history; accept
                median, _latest = _baseline
                if _is_price_outlier(px, median):
                    log.warning(
                        "canonical_price: REJECTING %s for %s — px=%.2f "
                        "deviates >%.0f%% from 30d median %.2f; "
                        "falling through cascade",
                        source, canonical, px,
                        _OUTLIER_TOLERANCE_PCT * 100, median,
                    )
                    return None
                return px

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
                        # PR #317: hard-stale gate — refuse live_quotes
                        # values older than _HARD_STALE_THRESHOLD during
                        # market hours. Falling through to daily_prices
                        # (NSE EOD) is safer than serving a pre-split /
                        # pre-corp-action stale value. Off-hours we still
                        # accept the stale value (no daily_prices write
                        # might have happened yet).
                        as_of_val = row[1]
                        if as_of_val is not None and _is_market_hours_utc(
                            datetime.now(timezone.utc)
                        ):
                            age = datetime.now(timezone.utc) - as_of_val
                            if age > _HARD_STALE_THRESHOLD:
                                log.warning(
                                    "canonical_price: REJECTING live_quotes "
                                    "for %s — age=%s exceeds hard-stale "
                                    "threshold %s; falling through to "
                                    "daily_prices",
                                    canonical, age, _HARD_STALE_THRESHOLD,
                                )
                                break  # skip remaining live_quotes candidates
                        # Day-58 outlier gate.
                        gated = _accept(float(row[0]), "live_quotes")
                        if gated is not None:
                            return gated
                        # Outlier rejected — try next candidate /
                        # cascade rung.
                    except Exception:
                        pass

            # 2. daily_prices — NSE EOD fallback
            for cand in candidates:
                try:
                    row = sess.execute(
                        text(
                            "SELECT close_price, trade_date FROM daily_prices "
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
                        # Day-58 daily_prices staleness gate. Catches
                        # the TCS-class failure (bhavcopy ingestion
                        # silently stopped for months; close_price
                        # served forever as the last good close).
                        if _is_daily_prices_stale(row[1]):
                            log.warning(
                                "canonical_price: REJECTING daily_prices "
                                "for %s — trade_date=%s exceeds %d-day "
                                "staleness threshold; falling through to "
                                "yfinance",
                                canonical, row[1], _DAILY_PRICES_HARD_STALE_DAYS,
                            )
                            continue
                        px = float(row[0])
                        # Day-58 outlier gate (rare here since baseline
                        # uses daily_prices itself, but catches a brand-
                        # new outlier row against the older median).
                        gated = _accept(px, "daily_prices")
                        if gated is None:
                            continue
                        log.warning(
                            "canonical_price: %s missing from live_quotes, "
                            "fell through to daily_prices close=%.2f",
                            canonical, gated,
                        )
                        return gated
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
