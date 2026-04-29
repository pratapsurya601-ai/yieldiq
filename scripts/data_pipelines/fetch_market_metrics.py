"""Backfill market_metrics PE / PB / D-E / ROE from yfinance .info.

Generalised from PR #174 (`scripts/data_patches/backfill_pe_pb_all_*`).
Cascade:
  1. yfinance .info -> trailingPE, priceToBook, debtToEquity, returnOnEquity
  2. Finnhub /stock/metric -> peTTM, pbAnnual, totalDebt/totalEquity, roeTTM

Idempotent UPSERT key: (ticker, trade_date=today). Re-runs same day
top-up missing metrics rather than overwriting.
"""
from __future__ import annotations

import os
from datetime import date

from sqlalchemy import text

from . import _common as C


UPSERT_SQL = text("""
    INSERT INTO market_metrics (ticker, trade_date, pe_ratio, pb_ratio,
                                debt_equity, roe)
    VALUES (:ticker, :trade_date, :pe, :pb, :de, :roe)
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        pe_ratio    = COALESCE(EXCLUDED.pe_ratio, market_metrics.pe_ratio),
        pb_ratio    = COALESCE(EXCLUDED.pb_ratio, market_metrics.pb_ratio),
        debt_equity = COALESCE(EXCLUDED.debt_equity, market_metrics.debt_equity),
        roe         = COALESCE(EXCLUDED.roe, market_metrics.roe)
""")


def _sane(v, lo: float, hi: float) -> float | None:
    try:
        f = float(v)
        if f != f or f <= lo or f >= hi:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _from_yfinance(ticker_yf: str) -> dict:
    import yfinance as yf
    info = yf.Ticker(ticker_yf).info or {}
    de = info.get("debtToEquity")
    if de is not None:
        try:
            de = float(de) / 100.0    # yf returns percent; convention is ratio
        except (TypeError, ValueError):
            de = None
    return {
        "pe":  _sane(info.get("trailingPE"), -1000, 10000),
        "pb":  _sane(info.get("priceToBook"), -1000, 10000),
        "de":  _sane(de, -100, 100),
        "roe": _sane(info.get("returnOnEquity"), -100, 100),
    }


def _from_finnhub(ticker_yf: str) -> dict:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return {}
    import urllib.parse
    import urllib.request
    import json
    url = (
        "https://finnhub.io/api/v1/stock/metric"
        f"?symbol={urllib.parse.quote(ticker_yf)}&metric=all&token={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return {}
    m = (data or {}).get("metric") or {}
    return {
        "pe":  _sane(m.get("peTTM"), -1000, 10000),
        "pb":  _sane(m.get("pbAnnual"), -1000, 10000),
        "de":  _sane(m.get("totalDebt/totalEquityAnnual"), -100, 100),
        "roe": _sane(m.get("roeTTM"), -100, 100),
    }


def _fetch_one(session_factory):
    def inner(ticker: str) -> dict:
        sym = C.yf_symbol(ticker)
        primary, err = C.with_retries(lambda: _from_yfinance(sym),
                                      label=f"metrics:{ticker}")
        if err and not primary:
            return {"status": "error", "source": "yfinance", "error": err}
        merged = primary or {}
        source = "yfinance" if any(merged.values()) else ""

        # Top-up via Finnhub if anything still missing
        if not all(merged.get(k) is not None for k in ("pe", "pb", "de", "roe")):
            fh = _from_finnhub(sym)
            for k, v in fh.items():
                if merged.get(k) is None and v is not None:
                    merged[k] = v
                    source = source or "finnhub"
                    if source == "yfinance":
                        source = "yfinance+finnhub"

        if not any(merged.get(k) is not None for k in ("pe", "pb", "de", "roe")):
            return {"status": "skip", "source": "all", "error": "no metrics"}

        sess = session_factory()
        try:
            sess.execute(UPSERT_SQL, {
                "ticker": C.bare(ticker),
                "trade_date": date.today(),
                "pe": merged.get("pe"), "pb": merged.get("pb"),
                "de": merged.get("de"), "roe": merged.get("roe"),
            })
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": source, "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": source, "error": ""}
    return inner


def backfill(tickers: list[str], session_factory, *, dry_run: bool = False) -> C.BackfillReport:
    return C.drive_workers(
        "market_metrics_pe_pb",
        tickers,
        _fetch_one(session_factory),
        workers=5,
        sleep_s=0.4,
        dry_run=dry_run,
    )
