# backend/workers/market_data_refresher.py
"""
Background refresher for live_quotes, fx_rates, and index_snapshots.

Called by APScheduler jobs registered in backend/main.py. Every function
in this module is idempotent and uses PostgreSQL UPSERT (ON CONFLICT ...
DO UPDATE) so a failed mid-run leaves the table in a consistent state.

yfinance is still the upstream source — but it is called here, ONCE per
job tick, in batches of ≤100 tickers — never from the request path.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text

log = logging.getLogger("yieldiq.market_data_refresher")

# Keep batches small so a single call to yf.Tickers(...) never blows
# up the Railway worker. 100 is a safe ceiling observed in practice.
BATCH_SIZE = 100

# Parallel fast_info fetches per batch. Sequential ~540ms/ticker means
# 1500 tickers would not fit in the 5-min cron interval — at 20 workers
# the same set completes in ~3.3 min (measured 2026-05-18 on 100 NSE
# tickers, extrapolated). yfinance fast_info is I/O-bound, so threads
# are sufficient (no need for asyncio/multiprocessing). Tune via
# YIELDIQ_QUOTES_WORKERS env var if Yahoo starts rate-limiting.
MAX_QUOTE_WORKERS = int(os.environ.get("YIELDIQ_QUOTES_WORKERS", "20"))

# Default ceiling for collect_refresh_tickers — matches pulse_daily's
# top-1500 universe (Nifty500 + mid+small-cap watch). Override per call
# (e.g. legacy APScheduler path still uses 200).
DEFAULT_LIMIT_FV = int(os.environ.get("YIELDIQ_QUOTES_LIMIT_FV", "1500"))

# Symbols refreshed by refresh_index_snapshots(). Keep in sync with
# market_data_service.get_all_index_snapshots() consumers.
INDEX_SYMBOLS: list[tuple[str, str]] = [
    ("^NSEI",      "NIFTY 50"),
    ("^BSESN",     "SENSEX"),
    ("^NSEBANK",   "NIFTY Bank"),
    ("^INDIAVIX",  "India VIX"),
    ("GC=F",       "Gold Futures"),
    ("SI=F",       "Silver Futures"),
    # Brent crude (USD/bbl). Added 2026-06-09 for MarketsStrip crude tile.
    # Daily-engagement surface; same yfinance cron treats it identically
    # to GC=F / SI=F. Frontend renders as $X/bbl (no INR conversion).
    ("BZ=F",       "Brent Crude Oil"),
    ("^NSEMDCP50", "Nifty Midcap 50"),
    # Sector benchmarks consumed by the per-sector retrospective.
    # See backend/services/sector_benchmarks.py — the source of
    # truth for sector → ticker mapping.
    ("^CNXIT",       "Nifty IT"),
    ("^CNXPHARMA",   "Nifty Pharma"),
    ("^CNXFMCG",     "Nifty FMCG"),
    ("^CNXAUTO",     "Nifty Auto"),
    ("^CNXMETAL",    "Nifty Metal"),
    ("^CNXENERGY",   "Nifty Energy"),
    ("^CNXREALTY",   "Nifty Realty"),
    ("^CNXMEDIA",    "Nifty Media"),
    ("^CNXPSUBANK",  "Nifty PSU Bank"),
    ("^CNXFIN",      "Nifty Financial Services"),
    ("^CNXCONSUM",   "Nifty Consumer Durables"),
]

FX_PAIRS: list[tuple[str, str]] = [
    ("USDINR", "USDINR=X"),
]


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

def _session():
    from data_pipeline.db import Session
    if Session is None:
        raise RuntimeError("DATABASE_URL not set — refresher disabled")
    return Session()


def _yf():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        log.warning("yfinance not installed — refresher is a no-op")
        return None


def _chunk(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _quote_for(tk) -> tuple[float | None, float | None, int | None, float | None]:
    """Pull (price, change_pct, volume, prev_close) from a yfinance Ticker handle."""
    try:
        fi = tk.fast_info
        price = float(getattr(fi, "last_price", 0) or 0)
        prev = float(getattr(fi, "previous_close", 0) or 0)
        vol = getattr(fi, "last_volume", None)
        try:
            vol = int(vol) if vol is not None else None
        except (TypeError, ValueError):
            vol = None
        chg = ((price - prev) / prev * 100) if prev else None
        return (
            price if price else None,
            chg,
            vol,
            prev if prev else None,
        )
    except Exception as exc:
        log.debug("fast_info failed: %s", exc)
        return (None, None, None, None)


# ─────────────────────────────────────────────────────────────────
# Write-time sanity gate
# ─────────────────────────────────────────────────────────────────
#
# Background: on 2026-05-18 we observed POLICYBZR live_quotes.price =
# ₹16,479 while true CMP was ~₹1,718 (~9x). yfinance fast_info had
# returned a single momentary absurd tick; the refresher accepted it
# and the bad row stayed in live_quotes until the next refresh cycle
# overwrote it. PR #317 added a READ-time staleness gate; this gate
# is the WRITE-time complement — it prevents a corrupt tick from
# ever landing in the table in the first place.
#
# Heuristics (intentionally simple, easy to reason about):
#   1. Intraday move vs PREVIOUS live_quotes.price > 50% → reject.
#   2. Move vs yfinance previous_close > +20% or < -20% AND the
#      previous live_quotes price exists → reject (suspicious, even
#      a circuit-breaker max move on NSE is ±20%).
#   3. No previous row → accept (first-ever fetch must seed somehow).
#
# Caveats for future work:
#   * Legitimate moves that may trip the gate:
#     - Stock splits / bonus / reverse-splits on the ex-date (e.g.
#       1:10 split → 90% price drop). Mitigation: maintain a corporate-
#       actions allow-list keyed by (ticker, date) and bypass the gate
#       for that single day.
#     - Resumption of trading after a long suspension or a UC/LC
#       circuit on a thinly-traded counter the next day.
#     - Currency-redenominated tickers (rare in NSE/BSE universe).
#   * The +20% prev_close band assumes equities. Derivatives / index
#     futures / penny stocks may need different bands — this gate is
#     wired into live_quotes only, which is equity-only today.

INTRADAY_MAX_MOVE = 0.50          # vs previous live_quotes.price
PREV_CLOSE_UPPER_BAND = 1.20      # vs yfinance previous_close
PREV_CLOSE_LOWER_BAND = 0.80


def _fetch_prev_prices(sess, tickers: list[str]) -> dict[str, float]:
    """Return {ticker: prev_live_price} for the tickers we are about to
    write. Tickers missing from live_quotes are omitted from the result.

    Robust to missing table / empty input — returns {} on failure.
    """
    if not tickers:
        return {}
    try:
        rows = sess.execute(
            text(
                "SELECT ticker, price FROM live_quotes "
                "WHERE ticker = ANY(:tickers)"
            ),
            {"tickers": list(tickers)},
        ).fetchall()
        return {r[0]: float(r[1]) for r in rows if r[1] is not None}
    except Exception as exc:
        log.debug("prev live_quotes lookup failed: %s", exc)
        return {}


def _sanity_check_quote(
    ticker: str,
    new_price: float,
    prev_close: float | None,
    prev_live_price: float | None,
) -> tuple[bool, str | None]:
    """Decide whether to accept this quote.

    Returns (accept, reason_if_rejected). `reason` is a short string
    suitable for logging; None when accepted.

    Rules (see module docstring above for rationale):
      * new_price <= 0 → reject (defensive; caller already filters None)
      * no prev_live_price → accept (first-ever fetch)
      * |new - prev_live| / prev_live > INTRADAY_MAX_MOVE → reject
      * new / prev_close outside [0.80, 1.20] AND prev_live_price exists
        → reject (would normally be a circuit-breaker, treat as bad tick)
    """
    if new_price is None or new_price <= 0:
        return (False, "non_positive_price")

    if prev_live_price is None or prev_live_price <= 0:
        # First ever fetch — must seed the row somehow.
        return (True, None)

    move = abs(new_price - prev_live_price) / prev_live_price
    if move > INTRADAY_MAX_MOVE:
        return (
            False,
            f"intraday_move_{move:.2%}_prev={prev_live_price:g}_new={new_price:g}",
        )

    if prev_close is not None and prev_close > 0:
        ratio = new_price / prev_close
        if ratio > PREV_CLOSE_UPPER_BAND or ratio < PREV_CLOSE_LOWER_BAND:
            return (
                False,
                f"prev_close_band_ratio={ratio:.3f}_prev_close={prev_close:g}_new={new_price:g}",
            )

    return (True, None)


# ─────────────────────────────────────────────────────────────────
# refresh_live_quotes
# ─────────────────────────────────────────────────────────────────

def refresh_live_quotes(tickers: Iterable[str]) -> dict:
    """Batch-fetch quotes for `tickers` and UPSERT into live_quotes.

    Returns stats dict {requested, ok, failed}."""
    tickers = list({t for t in (tickers or []) if t})
    if not tickers:
        return {"requested": 0, "ok": 0, "failed": 0}

    yf = _yf()
    if yf is None:
        return {"requested": len(tickers), "ok": 0, "failed": len(tickers)}

    now = datetime.now(timezone.utc)
    ok, fail = 0, 0

    try:
        sess = _session()
    except Exception as exc:
        log.warning("refresh_live_quotes: no session (%s)", exc)
        return {"requested": len(tickers), "ok": 0, "failed": len(tickers)}

    def _fetch_one(t: str):
        try:
            tk = yf.Ticker(t)
            price, chg, vol, prev_close = _quote_for(tk)
            if price is None:
                return (t, None)
            return (
                t,
                {
                    "ticker": t,
                    "price": price,
                    "change_pct": chg,
                    "volume": vol,
                    "as_of": now,
                    "_prev_close": prev_close,
                },
            )
        except Exception as exc:
            log.debug("quote %s failed: %s", t, exc)
            return (t, None)

    rejected = 0
    try:
        for batch in _chunk(tickers, BATCH_SIZE):
            raw_rows = []
            # I/O-bound — threads are enough. See MAX_QUOTE_WORKERS comment.
            with ThreadPoolExecutor(max_workers=MAX_QUOTE_WORKERS) as pool:
                for _t, row in pool.map(_fetch_one, batch):
                    if row is None:
                        fail += 1
                    else:
                        raw_rows.append(row)

            if not raw_rows:
                continue

            # Write-time sanity gate. Look up previous live_quotes price
            # for every candidate ticker in one query, then drop any row
            # whose new price is implausibly far from the previous.
            prev_map = _fetch_prev_prices(
                sess, [r["ticker"] for r in raw_rows]
            )
            rows = []
            for r in raw_rows:
                accept, reason = _sanity_check_quote(
                    r["ticker"],
                    r["price"],
                    r.get("_prev_close"),
                    prev_map.get(r["ticker"]),
                )
                if not accept:
                    rejected += 1
                    fail += 1
                    log.warning(
                        "live_quotes write-gate REJECT %s: %s",
                        r["ticker"], reason,
                    )
                    continue
                # Strip internal-only keys before UPSERT.
                rows.append({
                    "ticker": r["ticker"],
                    "price": r["price"],
                    "change_pct": r["change_pct"],
                    "volume": r["volume"],
                    "as_of": r["as_of"],
                })

            if not rows:
                continue

            try:
                sess.execute(
                    text(
                        """
                        INSERT INTO live_quotes
                            (ticker, price, change_pct, volume, as_of)
                        VALUES
                            (:ticker, :price, :change_pct, :volume, :as_of)
                        ON CONFLICT (ticker) DO UPDATE SET
                            price      = EXCLUDED.price,
                            change_pct = EXCLUDED.change_pct,
                            volume     = EXCLUDED.volume,
                            as_of      = EXCLUDED.as_of
                        """
                    ),
                    rows,
                )
                sess.commit()
                ok += len(rows)
            except Exception as exc:
                log.warning("live_quotes UPSERT failed: %s", exc)
                sess.rollback()
                fail += len(rows)
    finally:
        sess.close()

    log.info(
        "refresh_live_quotes: requested=%d ok=%d failed=%d rejected=%d",
        len(tickers), ok, fail, rejected,
    )
    return {
        "requested": len(tickers),
        "ok": ok,
        "failed": fail,
        "rejected": rejected,
    }


# ─────────────────────────────────────────────────────────────────
# refresh_fx_rates
# ─────────────────────────────────────────────────────────────────

def refresh_fx_rates() -> dict:
    """Refresh every pair in FX_PAIRS. UPSERTs into fx_rates."""
    yf = _yf()
    if yf is None:
        return {"ok": 0, "failed": len(FX_PAIRS)}

    now = datetime.now(timezone.utc)
    ok, fail = 0, 0

    try:
        sess = _session()
    except Exception as exc:
        log.warning("refresh_fx_rates: no session (%s)", exc)
        return {"ok": 0, "failed": len(FX_PAIRS)}

    try:
        for pair, yf_sym in FX_PAIRS:
            try:
                fi = yf.Ticker(yf_sym).fast_info
                rate = float(getattr(fi, "last_price", 0) or 0)
                if not rate:
                    fail += 1
                    continue
                sess.execute(
                    text(
                        """
                        INSERT INTO fx_rates (pair, rate, as_of)
                        VALUES (:pair, :rate, :as_of)
                        ON CONFLICT (pair) DO UPDATE SET
                            rate  = EXCLUDED.rate,
                            as_of = EXCLUDED.as_of
                        """
                    ),
                    {"pair": pair, "rate": rate, "as_of": now},
                )
                sess.commit()
                ok += 1
            except Exception as exc:
                log.warning("refresh_fx_rates(%s) failed: %s", pair, exc)
                sess.rollback()
                fail += 1
    finally:
        sess.close()

    log.info("refresh_fx_rates: ok=%d failed=%d", ok, fail)
    return {"ok": ok, "failed": fail}


# ─────────────────────────────────────────────────────────────────
# refresh_index_snapshots
# ─────────────────────────────────────────────────────────────────

def refresh_index_snapshots() -> dict:
    """Refresh INDEX_SYMBOLS. One pass, UPSERTs into index_snapshots."""
    yf = _yf()
    if yf is None:
        return {"ok": 0, "failed": len(INDEX_SYMBOLS)}

    now = datetime.now(timezone.utc)
    ok, fail = 0, 0

    try:
        sess = _session()
    except Exception as exc:
        log.warning("refresh_index_snapshots: no session (%s)", exc)
        return {"ok": 0, "failed": len(INDEX_SYMBOLS)}

    try:
        rows = []
        for sym, name in INDEX_SYMBOLS:
            try:
                fi = yf.Ticker(sym).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                prev = float(getattr(fi, "previous_close", 0) or 0)
                if not price:
                    fail += 1
                    continue
                chg = ((price - prev) / prev * 100) if prev else None
                rows.append(
                    {
                        "symbol": sym,
                        "name": name,
                        "price": price,
                        "change_pct": chg,
                        "as_of": now,
                    }
                )
            except Exception as exc:
                log.warning("index fetch %s failed: %s", sym, exc)
                fail += 1

        if rows:
            try:
                sess.execute(
                    text(
                        """
                        INSERT INTO index_snapshots
                            (symbol, name, price, change_pct, as_of)
                        VALUES
                            (:symbol, :name, :price, :change_pct, :as_of)
                        ON CONFLICT (symbol) DO UPDATE SET
                            name       = EXCLUDED.name,
                            price      = EXCLUDED.price,
                            change_pct = EXCLUDED.change_pct,
                            as_of      = EXCLUDED.as_of
                        """
                    ),
                    rows,
                )
                sess.commit()
                ok = len(rows)
            except Exception as exc:
                log.warning("index_snapshots UPSERT failed: %s", exc)
                sess.rollback()
                fail += len(rows)
    finally:
        sess.close()

    log.info("refresh_index_snapshots: ok=%d failed=%d", ok, fail)
    return {"ok": ok, "failed": fail}


# ─────────────────────────────────────────────────────────────────
# Ticker discovery for the quotes job
# ─────────────────────────────────────────────────────────────────

def collect_refresh_tickers(limit_fv: int | None = None) -> list[str]:
    """
    Build the union of:
      • all distinct tickers currently held in Supabase `holdings`
      • top `limit_fv` tickers from fair_value_history (by last_updated)

    `limit_fv` defaults to DEFAULT_LIMIT_FV (1500, matching pulse_daily's
    top-N universe). Pass an explicit smaller integer for legacy callers
    that need a tighter blast radius (e.g. the in-process APScheduler in
    backend/main.py keeps 200 to bound Railway worker CPU).

    Returns a deduped list of ticker strings already carrying .NS/.BO
    suffixes where applicable. Missing data sources are silently
    skipped; this function never raises.
    """
    if limit_fv is None:
        limit_fv = DEFAULT_LIMIT_FV
    tickers: set[str] = set()

    # 1) Supabase holdings
    try:
        from backend.services.portfolio_service import _get_supabase
        client = _get_supabase()
        if client is not None:
            res = client.table("holdings").select("ticker").execute()
            for row in (res.data or []):
                t = (row or {}).get("ticker")
                if t:
                    tickers.add(t.upper())
    except Exception as exc:
        log.debug("holdings ticker pull failed: %s", exc)

    # 2) fair_value_history top-N
    try:
        from data_pipeline.db import Session
        if Session is not None:
            sess = Session()
            try:
                rows = sess.execute(
                    text(
                        """
                        SELECT ticker
                        FROM fair_value_history
                        GROUP BY ticker
                        ORDER BY MAX(date) DESC
                        LIMIT :n
                        """
                    ),
                    {"n": int(limit_fv)},
                ).fetchall()
                for r in rows:
                    t = r[0]
                    if not t:
                        continue
                    # fair_value_history stores clean symbol — add .NS
                    if "." not in t:
                        tickers.add(f"{t.upper()}.NS")
                    else:
                        tickers.add(t.upper())
            finally:
                sess.close()
    except Exception as exc:
        log.debug("fv_history ticker pull failed: %s", exc)

    return sorted(tickers)
