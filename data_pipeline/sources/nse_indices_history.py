"""NSE daily index close + valuation ratios (P/E, P/B, Div Yield).

Source: https://archives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv

One CSV per NSE trading day, ~110 rows (Nifty 50/Next50/100/200/500,
all sector niftys, thematic indices). Earliest date with data is
2014-01-01.

Module API:
    fetch_ind_close_all(d: date, session=None) -> list[dict]
        Download + parse one date's CSV. Returns [] for holidays / 404.

    upsert_rows(rows: list[dict], session) -> int
        Bulk UPSERT into ``nse_index_history``. Idempotent on
        (index_name, trade_date).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import Iterable

logger = logging.getLogger(__name__)

ARCHIVE_URL = (
    "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv"
)
NSE_BASE = "https://www.nseindia.com"


# ── HTTP session ─────────────────────────────────────────────────────

def _get_session():
    """curl_cffi Chrome-impersonate session (NSE archives are picky)."""
    from curl_cffi import requests as cffi_requests
    s = cffi_requests.Session(impersonate="chrome")
    try:
        s.get(NSE_BASE, timeout=10)
    except Exception:
        pass
    return s


# ── Parsing helpers ──────────────────────────────────────────────────

def _safe_num(val) -> float | None:
    """Parse numeric from CSV cell. NSE uses '-' for null, commas for
    thousands separator."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ("-", "—", "NA", "N/A"):
        return None
    s = s.replace(",", "")
    try:
        f = float(s)
        # Filter NaN
        import math
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> int | None:
    f = _safe_num(val)
    if f is None:
        return None
    try:
        return int(f)
    except (ValueError, OverflowError):
        return None


def _parse_csv_text(text: str, trade_date: date) -> list[dict]:
    """Parse the ind_close_all CSV body into a list of row dicts."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw in reader:
        # Normalise keys (strip whitespace, case-insensitive lookup)
        norm = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}

        index_name = norm.get("Index Name") or norm.get("INDEX NAME")
        if not index_name:
            continue
        # Truncate to column limit (VARCHAR(64))
        index_name = index_name[:64]

        # NSE has shipped two header variants over the years:
        #   2014-2018ish: "Open / High / Low / Close / Pts Chg / Chg%"
        #   2019+:        "Open Index Value / High Index Value /
        #                  Low Index Value / Closing Index Value /
        #                  Points Change / Change(%)"
        rows.append({
            "index_name": index_name,
            "trade_date": trade_date,
            "open": _safe_num(norm.get("Open Index Value")
                              or norm.get("Open")),
            "high": _safe_num(norm.get("High Index Value")
                              or norm.get("High")),
            "low": _safe_num(norm.get("Low Index Value")
                             or norm.get("Low")),
            "close": _safe_num(norm.get("Closing Index Value")
                               or norm.get("Close")),
            "pts_chg": _safe_num(norm.get("Points Change")
                                 or norm.get("Pts Chg")),
            "chg_pct": _safe_num(norm.get("Change(%)")
                                 or norm.get("Chg(%)")
                                 or norm.get("Chg%")
                                 or norm.get("Change %")),
            "volume": _safe_int(norm.get("Volume")),
            "turnover_cr": _safe_num(norm.get("Turnover (Rs. Cr.)")
                                     or norm.get("Turnover")),
            "pe_ratio": _safe_num(norm.get("P/E")),
            "pb_ratio": _safe_num(norm.get("P/B")),
            "div_yield": _safe_num(norm.get("Div Yield")
                                   or norm.get("Div. Yield")),
        })
    return rows


# ── Public API ───────────────────────────────────────────────────────

def fetch_ind_close_all(
    trade_date: date,
    session=None,
) -> list[dict]:
    """Download + parse the ind_close_all CSV for one date.

    Returns [] if the date is a weekend, holiday, or 404 — caller
    treats empty list as "skip".
    """
    if trade_date.weekday() >= 5:
        # Weekend — skip without an HTTP call.
        return []

    date_str = trade_date.strftime("%d%m%Y")
    url = ARCHIVE_URL.format(date=date_str)

    try:
        sess = session or _get_session()
        r = sess.get(url, timeout=30)
    except Exception as e:
        logger.warning("ind_close_all %s: fetch failed: %s", trade_date, e)
        return []

    if r.status_code == 404:
        logger.debug("ind_close_all %s: 404 (holiday)", trade_date)
        return []
    if r.status_code != 200:
        logger.warning("ind_close_all %s: HTTP %s", trade_date, r.status_code)
        return []
    if not r.content or len(r.content) < 200:
        logger.debug("ind_close_all %s: empty body", trade_date)
        return []

    try:
        text = r.text
        rows = _parse_csv_text(text, trade_date)
    except Exception as e:
        logger.warning("ind_close_all %s: parse failed: %s", trade_date, e)
        return []

    return rows


# ── Persistence ──────────────────────────────────────────────────────

UPSERT_SQL = """
INSERT INTO nse_index_history
    (index_name, trade_date, open, high, low, close, pts_chg, chg_pct,
     volume, turnover_cr, pe_ratio, pb_ratio, div_yield)
VALUES
    (%(index_name)s, %(trade_date)s, %(open)s, %(high)s, %(low)s,
     %(close)s, %(pts_chg)s, %(chg_pct)s, %(volume)s, %(turnover_cr)s,
     %(pe_ratio)s, %(pb_ratio)s, %(div_yield)s)
ON CONFLICT (index_name, trade_date) DO UPDATE SET
    open        = EXCLUDED.open,
    high        = EXCLUDED.high,
    low         = EXCLUDED.low,
    close       = EXCLUDED.close,
    pts_chg     = EXCLUDED.pts_chg,
    chg_pct     = EXCLUDED.chg_pct,
    volume      = EXCLUDED.volume,
    turnover_cr = EXCLUDED.turnover_cr,
    pe_ratio    = EXCLUDED.pe_ratio,
    pb_ratio    = EXCLUDED.pb_ratio,
    div_yield   = EXCLUDED.div_yield
"""


def upsert_rows_psycopg(rows: Iterable[dict], conn) -> int:
    """Bulk UPSERT using a raw psycopg2 connection.

    Returns the count of input rows (psycopg2 doesn't reliably report
    affected-rowcount for executemany).
    """
    rows = list(rows)
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    conn.commit()
    return len(rows)


def upsert_rows_sqlalchemy(rows: Iterable[dict], session) -> int:
    """Bulk UPSERT via a SQLAlchemy session (for callers that already
    hold one)."""
    from sqlalchemy import text
    rows = list(rows)
    if not rows:
        return 0
    # SQLAlchemy expects :name placeholders rather than %()s.
    sa_sql = text(UPSERT_SQL.replace("%(", ":").replace(")s", ""))
    for r in rows:
        session.execute(sa_sql, r)
    session.commit()
    return len(rows)
