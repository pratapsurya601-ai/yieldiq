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


# Source ranks for market_metrics. Lower = higher trust. Mirrors PR #208's
# financials precedence pattern. yfinance is the only source writing today;
# the other ranks are pre-allocated for future ingest paths.
_RANK_BY_SOURCE = {
    "NSE_QUOTE_API": 10,
    "NSE_BHAVCOPY":  20,
    "BSE_QUOTE":     30,
    "BSE_BHAVCOPY":  35,
    "finnhub":       40,
    "yfinance":      50,
}


def _rank_for(source: str | None) -> int:
    return _RANK_BY_SOURCE.get(source or "", 60)


# Source-precedence UPSERT (mirrors PR #208 / migration 021_data_quality_rank).
# A lower-rank row CANNOT overwrite a higher-rank row's columns. Rank itself
# only ever decreases (LEAST). Prevents the 2026-04-30 incident where yfinance
# wrote NULL market_cap rows that displaced 2026-04-26's valid values.
UPSERT_SQL = text("""
    INSERT INTO market_metrics (
        ticker, trade_date, pe_ratio, pb_ratio, debt_equity, roe,
        data_source, data_quality_rank
    )
    VALUES (
        :ticker, :trade_date, :pe, :pb, :de, :roe,
        :data_source, :data_quality_rank
    )
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        pe_ratio = CASE
            WHEN EXCLUDED.data_quality_rank <= market_metrics.data_quality_rank
             AND EXCLUDED.pe_ratio IS NOT NULL
            THEN EXCLUDED.pe_ratio
            ELSE market_metrics.pe_ratio
        END,
        pb_ratio = CASE
            WHEN EXCLUDED.data_quality_rank <= market_metrics.data_quality_rank
             AND EXCLUDED.pb_ratio IS NOT NULL
            THEN EXCLUDED.pb_ratio
            ELSE market_metrics.pb_ratio
        END,
        debt_equity = CASE
            WHEN EXCLUDED.data_quality_rank <= market_metrics.data_quality_rank
             AND EXCLUDED.debt_equity IS NOT NULL
            THEN EXCLUDED.debt_equity
            ELSE market_metrics.debt_equity
        END,
        roe = CASE
            WHEN EXCLUDED.data_quality_rank <= market_metrics.data_quality_rank
             AND EXCLUDED.roe IS NOT NULL
            THEN EXCLUDED.roe
            ELSE market_metrics.roe
        END,
        data_source = CASE
            WHEN EXCLUDED.data_quality_rank <= market_metrics.data_quality_rank
            THEN EXCLUDED.data_source
            ELSE market_metrics.data_source
        END,
        data_quality_rank = LEAST(EXCLUDED.data_quality_rank, market_metrics.data_quality_rank)
""")


def _row_is_writable(pe, pb, de, roe) -> tuple[bool, str]:
    """Pre-write validation gate. Returns (is_writable, reason).

    Rejects rows where the values are obviously broken (PE > 500, all NULL,
    impossible ranges). Mirrors the validation pattern from data_quality
    helper module (PR #217).
    """
    # All-null row provides no signal — skip
    if pe is None and pb is None and de is None and roe is None:
        return False, "all metrics NULL — no signal to record"
    # PE outliers
    if pe is not None and (pe < 0 or pe > 500):
        return False, f"PE={pe} outside plausible range [0, 500]"
    # PB outliers
    if pb is not None and (pb < 0 or pb > 100):
        return False, f"PB={pb} outside plausible range [0, 100]"
    # ROE outliers (decimal form expected: 0.20 = 20%)
    if roe is not None and (roe < -2 or roe > 5):
        return False, f"ROE={roe} outside plausible range [-2, 5]"
    return True, ""


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

        # Pre-write validation gate (PR #218): reject rows whose values are
        # obvious unit-bug signatures or all-null. Prevents the 2026-04-30
        # incident class where yfinance writes NULL/junk over prior good data.
        ok, reason = _row_is_writable(merged.get("pe"), merged.get("pb"),
                                      merged.get("de"), merged.get("roe"))
        if not ok:
            return {"status": "skip", "source": source or "yfinance",
                    "error": f"validation: {reason}"}

        sess = session_factory()
        try:
            sess.execute(UPSERT_SQL, {
                "ticker": C.bare(ticker),
                "trade_date": date.today(),
                "pe": merged.get("pe"), "pb": merged.get("pb"),
                "de": merged.get("de"), "roe": merged.get("roe"),
                "data_source": source or "yfinance",
                "data_quality_rank": _rank_for(source or "yfinance"),
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
