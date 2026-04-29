"""Backfill corporate_actions — NSE-archive-first.

Cascade priority:
  1. NSE bulk endpoint:
     ``https://www.nseindia.com/api/corporates-corporateActions?index=equities``
     ONE call returns every dividend / split / bonus / rights for every
     equity over the recent rolling window. Bulk-mode is by far the
     cheapest path: a single network call covers thousands of tickers.
  2. NSE per-symbol historical actions (for older dividends not in the
     rolling bulk feed):
     ``https://www.nseindia.com/api/historical/equityaction?symbol=…``
  3. yfinance ``Ticker.dividends`` / ``.splits`` — last-resort fallback
     for the rare ticker NSE has no record of (delisted, name-change
     edge cases).

Idempotent: rows keyed on (ticker, ex_date, action_type) — re-running
overwrites rather than duplicating. The ``run_once_bulk`` path returns
the count and no per-ticker fan-out happens (efficient).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import text

from . import _common as C

logger = logging.getLogger(__name__)


NSE_BULK_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
)
NSE_HISTORICAL_URL = (
    "https://www.nseindia.com/api/historical/equityaction"
    "?symbol={symbol}&from={from_d}&to={to_d}"
)


# Rows keyed by (ticker, ex_date, action_type) — see migration notes.
# We DELETE per-ticker before insert when running per-ticker mode so
# stale yfinance rows can't shadow the NSE truth.
DELETE_BY_TICKER = text("DELETE FROM corporate_actions WHERE ticker = :ticker")
INSERT_SQL = text("""
    INSERT INTO corporate_actions
        (ticker, action_type, ex_date, ratio, remarks, adjustment_factor)
    VALUES
        (:ticker, :action_type, :ex_date, :ratio, :remarks, :adjustment_factor)
""")


# ── HTTP session ─────────────────────────────────────────────────────

def _session():
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    try:
        s.get("https://www.nseindia.com/", timeout=15)
    except Exception:
        pass
    return s


# ── action-type normaliser ───────────────────────────────────────────

def _classify(subject: str) -> str:
    s = (subject or "").upper()
    if "BONUS" in s:
        return "BONUS"
    if "SPLIT" in s or "SUB-DIVISION" in s or "SUBDIVISION" in s:
        return "SPLIT"
    if "RIGHTS" in s:
        return "RIGHTS"
    if "DIVIDEND" in s:
        return "DIVIDEND"
    return "OTHER"


def _parse_ex_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ── Bulk fetch (the cheap, primary path) ─────────────────────────────

def fetch_bulk(session_http=None) -> list[dict]:
    """Return all recent corporate actions in one call.

    The NSE bulk endpoint covers a rolling window (typically the last
    ~12 months of upcoming + recent past). Sufficient for keeping
    `corporate_actions` current. Use ``fetch_per_symbol`` for deep
    history on individual tickers.
    """
    sess = session_http or _session()
    try:
        r = sess.get(NSE_BULK_URL, timeout=30)
    except Exception as e:
        logger.error("nse bulk corp actions fetch failed: %s", e)
        return []
    if r.status_code != 200:
        logger.warning("nse bulk corp actions HTTP %s", r.status_code)
        return []
    try:
        data = r.json()
    except Exception as e:
        logger.warning("nse bulk corp actions JSON decode: %s", e)
        return []

    # NSE returns a list (sometimes wrapped in {"data": [...]}).
    items = data if isinstance(data, list) else (data.get("data") or [])
    rows: list[dict] = []
    for item in items:
        sym = (item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ex_d = _parse_ex_date(item.get("exDate"))
        if not ex_d:
            continue
        subject = str(item.get("subject") or "")[:500]
        rows.append({
            "ticker": sym,
            "action_type": _classify(subject),
            "ex_date": ex_d,
            "ratio": subject[:200],
            "remarks": subject,
            "adjustment_factor": 1.0,
        })
    return rows


def upsert_bulk(rows: Iterable[dict], session) -> int:
    """Insert NSE bulk rows. Returns count written.

    Uses DB ``merge``-equivalent: deletes any existing rows for the
    affected tickers in the rolling window, then re-inserts. Cheap on
    a per-batch basis since the bulk API only returns ~6-12 months of
    actions.
    """
    rows = list(rows)
    if not rows:
        return 0
    affected_tickers = sorted({r["ticker"] for r in rows})
    # Wipe old rows ONLY for tickers we have fresh data for, ONLY in the
    # date window the bulk feed covers (don't nuke 10-year history).
    earliest = min(r["ex_date"] for r in rows)
    session.execute(text("""
        DELETE FROM corporate_actions
         WHERE ticker = ANY(:tickers)
           AND ex_date >= :earliest
    """), {"tickers": affected_tickers, "earliest": earliest})
    n = 0
    for r in rows:
        try:
            session.execute(INSERT_SQL, r)
            n += 1
        except Exception as e:
            logger.debug("corp_action insert fail %s/%s: %s",
                         r["ticker"], r["ex_date"], e)
    session.commit()
    return n


# ── Per-symbol historical (deeper backfill) ──────────────────────────

def _from_nse_per_symbol(symbol: str, http) -> list[dict]:
    today = date.today()
    from_d = today.replace(year=today.year - 10).strftime("%d-%m-%Y")
    to_d = today.strftime("%d-%m-%Y")
    url = NSE_HISTORICAL_URL.format(symbol=symbol, from_d=from_d, to_d=to_d)
    try:
        r = http.get(url, timeout=20)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    items = data.get("data") if isinstance(data, dict) else data
    rows: list[dict] = []
    for item in items or []:
        ex_d = _parse_ex_date(item.get("exDate") or item.get("ex_dt"))
        if not ex_d:
            continue
        subject = str(item.get("subject") or item.get("purpose") or "")[:500]
        rows.append({
            "action_type": _classify(subject),
            "ex_date": ex_d,
            "ratio": subject[:200],
            "remarks": subject,
            "adjustment_factor": 1.0,
        })
    return rows


def _from_yfinance(ticker_yf: str) -> list[dict]:
    """Last-resort yfinance fallback (unchanged from PR #192)."""
    import yfinance as yf
    yt = yf.Ticker(ticker_yf)
    splits = yt.splits
    divs = yt.dividends

    rows: list[dict] = []
    if splits is not None and len(splits) > 0:
        for ex, factor in splits.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                f = float(factor)
            except Exception:
                continue
            if f <= 0 or f > 100:
                continue
            rows.append({
                "action_type": "SPLIT" if f < 1 else "BONUS",
                "ex_date": ex_d,
                "ratio": f"factor={f:g}",
                "remarks": f"yfinance splits: {f:g}",
                "adjustment_factor": f,
            })
    if divs is not None and len(divs) > 0:
        for ex, amt in divs.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                a = float(amt)
            except Exception:
                continue
            if a <= 0:
                continue
            rows.append({
                "action_type": "DIVIDEND",
                "ex_date": ex_d,
                "ratio": f"Rs {a:.4f}",
                "remarks": f"yfinance dividend Rs {a:.4f}",
                "adjustment_factor": 1.0,
            })
    return rows


# ── per-ticker driver (used by run_completeness_backfill) ────────────

# Bulk-fed NSE rows are pre-loaded once per process so the per-ticker
# worker only touches the network if NSE has nothing for that symbol.
_BULK_BY_TICKER: dict[str, list[dict]] | None = None


def _ensure_bulk_loaded() -> dict[str, list[dict]]:
    global _BULK_BY_TICKER
    if _BULK_BY_TICKER is not None:
        return _BULK_BY_TICKER
    out: dict[str, list[dict]] = {}
    for r in fetch_bulk():
        out.setdefault(r["ticker"], []).append(r)
    _BULK_BY_TICKER = out
    logger.info("nse bulk corp actions: %d tickers loaded", len(out))
    return out


def _fetch_one(session_factory):
    bulk = _ensure_bulk_loaded()
    http = _session()

    def inner(ticker: str) -> dict:
        bare = C.bare(ticker)
        rows: list[dict] = []
        source = ""

        # 1. From the bulk pre-load.
        bulk_hit = bulk.get(bare) or []
        if bulk_hit:
            rows = [{
                "action_type": r["action_type"],
                "ex_date": r["ex_date"],
                "ratio": r["ratio"],
                "remarks": r["remarks"],
                "adjustment_factor": r["adjustment_factor"],
            } for r in bulk_hit]
            source = "nse_bulk"

        # 2. Top-up with per-symbol historical for deeper coverage.
        try:
            hist = _from_nse_per_symbol(bare, http)
        except Exception as e:
            logger.debug("nse historical fail %s: %s", bare, e)
            hist = []
        if hist:
            rows.extend(hist)
            source = source or "nse_historical"

        # 3. yfinance ONLY if NSE has nothing.
        if not rows:
            sym = C.yf_symbol(ticker)
            yf_rows, yf_err = C.with_retries(
                lambda: _from_yfinance(sym),
                label=f"yfinance:{ticker}",
            )
            if yf_rows:
                rows = yf_rows
                source = "yfinance"
            elif yf_err:
                return {"status": "error", "source": "yfinance", "error": yf_err}

        if not rows:
            return {"status": "skip", "source": "all", "error": "no actions"}

        sess = session_factory()
        try:
            sess.execute(DELETE_BY_TICKER, {"ticker": bare})
            for r in rows:
                sess.execute(INSERT_SQL, {"ticker": bare, **r})
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": source, "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": source, "rows": len(rows), "error": ""}
    return inner


def backfill(tickers: list[str], session_factory, *, dry_run: bool = False) -> C.BackfillReport:
    return C.drive_workers(
        "corporate_actions",
        tickers,
        _fetch_one(session_factory),
        workers=4,
        sleep_s=0.5,
        dry_run=dry_run,
    )
