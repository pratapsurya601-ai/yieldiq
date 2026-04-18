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
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text

log = logging.getLogger("yieldiq.market_data_refresher")

# Keep batches small so a single call to yf.Tickers(...) never blows
# up the Railway worker. 100 is a safe ceiling observed in practice.
BATCH_SIZE = 100

# Symbols refreshed by refresh_index_snapshots(). Keep in sync with
# market_data_service.get_all_index_snapshots() consumers.
INDEX_SYMBOLS: list[tuple[str, str]] = [
    ("^NSEI",      "NIFTY 50"),
    ("^BSESN",     "SENSEX"),
    ("^NSEBANK",   "NIFTY Bank"),
    ("^INDIAVIX",  "India VIX"),
    ("GC=F",       "Gold Futures"),
    ("SI=F",       "Silver Futures"),
    ("^NSEMDCP50", "Nifty Midcap 50"),
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


def _quote_for(tk) -> tuple[float | None, float | None, int | None]:
    """Pull (price, change_pct, volume) from a yfinance Ticker handle."""
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
        return (price if price else None, chg, vol)
    except Exception as exc:
        log.debug("fast_info failed: %s", exc)
        return (None, None, None)


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

    try:
        for batch in _chunk(tickers, BATCH_SIZE):
            rows = []
            for t in batch:
                try:
                    tk = yf.Ticker(t)
                    price, chg, vol = _quote_for(tk)
                    if price is None:
                        fail += 1
                        continue
                    rows.append(
                        {
                            "ticker": t,
                            "price": price,
                            "change_pct": chg,
                            "volume": vol,
                            "as_of": now,
                        }
                    )
                except Exception as exc:
                    log.debug("quote %s failed: %s", t, exc)
                    fail += 1

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
        "refresh_live_quotes: requested=%d ok=%d failed=%d",
        len(tickers), ok, fail,
    )
    return {"requested": len(tickers), "ok": ok, "failed": fail}


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

def collect_refresh_tickers(limit_fv: int = 200) -> list[str]:
    """
    Build the union of:
      • all distinct tickers currently held in Supabase `holdings`
      • top `limit_fv` tickers from fair_value_history (by last_updated)

    Returns a deduped list of ticker strings already carrying .NS/.BO
    suffixes where applicable. Missing data sources are silently
    skipped; this function never raises.
    """
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
