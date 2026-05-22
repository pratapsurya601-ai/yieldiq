# data_pipeline/sources/nse_annual_reports.py
# Fetches Annual Report (AR) metadata from NSE's annual-reports JSON
# feed and persists URL + fiscal-year metadata into the canonical
# `company_annual_reports` table (migration 027).
#
# Endpoint:
#   GET https://www.nseindia.com/api/annual-reports
#       ?index=equities
#       &symbol=<NSE_SYMBOL>
#
# Observed response shape (subset):
#   {
#     "data": [
#       {
#         "companyName": "...",
#         "symbol": "...",
#         "from_yr": "2023",      # FY start year (calendar)
#         "to_yr":   "2024",      # FY end year (calendar) — fiscal_year
#         "fileName" / "attchmntFile": "https://nsearchives.nseindia.com/...",
#         "submissionDate" / "an_dt": "DD-MM-YYYY HH:MM:SS"
#       },
#       ...
#     ]
#   }
#
# NSE is gated by Akamai on www.nseindia.com, so we reuse the
# curl_cffi Chrome-impersonation pattern from
# data_pipeline/sources/nse_concall_transcripts.py — that file is the
# canonical reference for the session warm-up dance.
#
# Phase-1 scope (this module): metadata + URL only — segment_data,
# capex_commitments and the rest of the JSONB columns in migration 027
# are LLM-extracted in a follow-up PR (Phase-2 / Day-104b). We never
# download or open the PDF here.
#
# Idempotency: UPSERT on UNIQUE (ticker, fiscal_year) — re-runs are
# safe and skip rows that already exist.
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_AR_URL = (
    "https://www.nseindia.com/api/annual-reports"
    "?index=equities&symbol={symbol}"
)


def get_nse_session():
    """Create a warmed-up curl_cffi session impersonating Chrome.

    Mirrors data_pipeline/sources/nse_concall_transcripts.py.get_nse_session.
    """
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    try:
        session.get(NSE_BASE, timeout=30)
    except Exception as exc:  # warm-up is best-effort
        logger.debug(f"NSE warmup non-fatal: {exc}")
    return session


def _strip_ns_suffix(ticker: str) -> str:
    """`HDFCBANK.NS` -> `HDFCBANK`. NSE feed uses the bare symbol."""
    t = ticker.strip().upper()
    if t.endswith(".NS"):
        t = t[:-3]
    return t


def fetch_filings_for_symbol(
    symbol: str,
    session=None,
    timeout: int = 30,
) -> list[dict]:
    """Hit NSE annual-reports for a single symbol, return raw items.

    The caller passes either a ``HDFCBANK`` or ``HDFCBANK.NS`` form;
    we strip the suffix.
    """
    sess = session or get_nse_session()
    sym = _strip_ns_suffix(symbol)
    url = NSE_AR_URL.format(symbol=sym)
    try:
        resp = sess.get(url, timeout=timeout)
    except Exception as exc:
        logger.warning(f"NSE AR fetch error for {sym}: {exc}")
        return []

    if resp.status_code != 200:
        logger.debug(f"NSE AR HTTP {resp.status_code} for {sym}")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        logger.debug(f"NSE AR non-JSON for {sym}: {exc}")
        return []

    if isinstance(data, dict):
        items = data.get("data") or data.get("rows") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


def load_fixture(symbol: str, fixtures_dir: Path) -> list[dict]:
    """Load a saved NSE response from disk — used for tests and
    ``--dry-run`` smokes without network access."""
    sym = _strip_ns_suffix(symbol)
    path = fixtures_dir / f"{sym}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    if isinstance(blob, dict):
        items = blob.get("data") or blob.get("rows") or []
    elif isinstance(blob, list):
        items = blob
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


# Accept a handful of date formats NSE has emitted historically.
_DATE_FMTS = [
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y",
    "%d-%b-%Y %H:%M:%S", "%d-%b-%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
]


def _parse_published_date(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()
    for f in _DATE_FMTS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


_YEAR_RE = re.compile(r"(20\d{2})")


def _resolve_fiscal_year(item: dict) -> int | None:
    """Pull the FY-END year out of the record.

    NSE puts the FY in ``to_yr`` (or ``fyTo`` / ``toYr``). We treat
    that as the fiscal_year (Indian convention: FY2024 = Apr-2023 to
    Mar-2024, identified by the end year). Defensive fallbacks check
    ``period``, ``year``, then any 4-digit year in ``fileName``.
    """
    for key in ("to_yr", "fyTo", "toYr", "year", "fiscalYear", "fiscal_year"):
        v = item.get(key)
        if v is None:
            continue
        try:
            n = int(str(v).strip())
            if 1990 <= n <= 2100:
                return n
        except ValueError:
            continue

    # Fall back to a 4-digit year in the filename / period.
    for key in ("fileName", "attchmntFile", "period"):
        v = item.get(key)
        if not v:
            continue
        m = _YEAR_RE.findall(str(v))
        if m:
            # Use the LATEST year present — the AR for FY24 will
            # mention both 2023 and 2024; we want 2024.
            try:
                return max(int(y) for y in m)
            except ValueError:
                continue
    return None


def normalize_record(item: dict, ticker: str) -> dict | None:
    """Map a raw NSE AR record to our ``company_annual_reports`` shape.

    Returns ``None`` for records we can't map (missing URL or FY) so
    the caller can skip them silently.
    """
    ar_url = (
        item.get("fileName")
        or item.get("attchmntFile")
        or item.get("attachment")
        or item.get("url")
    )
    if ar_url:
        ar_url = str(ar_url).strip() or None
    if not ar_url:
        return None

    fy = _resolve_fiscal_year(item)
    if not fy:
        return None

    raw_dt = (
        item.get("submissionDate")
        or item.get("an_dt")
        or item.get("filedDate")
        or item.get("submission_date")
    )
    published_at = _parse_published_date(raw_dt)

    return {
        "ticker": ticker.strip().upper(),
        "fiscal_year": int(fy),
        "ar_url": ar_url,
        "ar_pdf_sha256": None,   # Phase-2: hash the PDF after download
        "source": "nse",
        "published_at": published_at,
    }


# UPSERT against the canonical Day-103d / migration 027 table.
# UNIQUE (ticker, fiscal_year) — ON CONFLICT DO NOTHING means we
# never overwrite an existing row (e.g. one that already has Phase-2
# LLM-extracted JSONB columns populated). A future "force-refresh"
# flag could switch this to DO UPDATE if we ever need to repoint a
# stale URL.
UPSERT_SQL = """
INSERT INTO company_annual_reports (
    ticker, fiscal_year, ar_url, ar_pdf_sha256, source, published_at
) VALUES (
    %(ticker)s, %(fiscal_year)s, %(ar_url)s, %(ar_pdf_sha256)s,
    %(source)s, %(published_at)s
)
ON CONFLICT (ticker, fiscal_year) DO NOTHING
"""


def upsert_records(rows: Iterable[dict], conn) -> int:
    """INSERT ... ON CONFLICT DO NOTHING. Returns rows actually inserted.

    ``conn`` is a psycopg2 connection (same convention as the
    annual_reports_service read path). We commit at the end so a
    failure mid-batch rolls back the whole batch — re-runs are
    idempotent so this is safe.
    """
    rows = list(rows)
    if not rows:
        return 0

    new_rows = 0
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(UPSERT_SQL, r)
                # psycopg2 reports rowcount=1 on insert, 0 on conflict.
                if cur.rowcount and cur.rowcount > 0:
                    new_rows += int(cur.rowcount)
        conn.commit()
    except Exception as exc:
        logger.error(f"AR upsert failed, rolling back: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    return new_rows
