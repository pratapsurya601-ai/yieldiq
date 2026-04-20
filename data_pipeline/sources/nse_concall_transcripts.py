# data_pipeline/sources/nse_concall_transcripts.py
# Fetches earnings-call / analyst-meet filings from NSE's
# corporate-announcements API and persists metadata (not PDF contents)
# into concall_transcripts.
#
# Endpoint:
#   GET https://www.nseindia.com/api/corporate-announcements
#       ?index=equities
#       &from_date=DD-MM-YYYY
#       &to_date=DD-MM-YYYY
#       &symbol=<NSE_SYMBOL>
# (the brief referenced a "corporate-annoucements" typo variant; the
# current live endpoint is spelled correctly. Response fields observed:
#   desc           - NSE's broad category label (e.g. "Analysts /
#                    Institutional Investor Meet / Con. Call Updates")
#   attchmntText   - free-text subject / description
#   attchmntFile   - PDF URL on nsearchives.nseindia.com (no Akamai wall)
#   an_dt          - announcement datetime e.g. "17-Apr-2026 18:20:49"
#   sort_date      - YYYY-MM-DD HH:MM:SS fallback
#   sm_name, symbol, sm_isin, seq_id)
#
# NSE blocks plain requests with Akamai on www.nseindia.com, so we use
# curl_cffi Chrome impersonation + session warmup (same pattern as
# data_pipeline/sources/nse_shareholding.py).
#
# We filter returned records by subject-text for:
#   - "conference call"
#   - "earnings call"
#   - "analyst meet"
#   - "investor meet"
#   - "analysts meet"
# plus any record whose `desc`/`category` contains "Analyst / Investor
# Meet" or "Earnings Call".
#
# For each surviving record we store:
#   ticker, filing_date, quarter_end (best-effort from subject),
#   pdf_url (the `attchmntFile` field), subject, category.
# We intentionally do NOT download or parse the PDF. TODO: separate
# worker for PDF text extraction.
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_CORP_ANN_URL = (
    "https://www.nseindia.com/api/corporate-announcements"
    "?index=equities&from_date={from_date}&to_date={to_date}"
    "&symbol={symbol}"
)

# Subject keywords that mark a record as concall-worthy.
_SUBJECT_PATTERNS = [
    re.compile(r"\bconference\s*call\b", re.I),
    re.compile(r"\bearnings\s*call\b", re.I),
    re.compile(r"\banalysts?\s*meet\b", re.I),
    re.compile(r"\banalysts?\s*/\s*investors?\s*meet\b", re.I),
    re.compile(r"\binvestors?\s*meet\b", re.I),
    re.compile(r"\btranscript\b", re.I),            # often "transcript of earnings call"
    re.compile(r"\bearnings\s*concall\b", re.I),
    re.compile(r"\bcon[-\s]*call\b", re.I),
]

# Category labels NSE uses that unambiguously mark this type of filing.
_CATEGORY_HINTS = (
    "analyst / investor meet",
    "analyst/investor meet",
    "analysts/institutional investor meet",
    "con. call",
    "concall",
    "conference call",
    "earnings call",
    "investor presentation",
    "analyst meet",
)

# Quarter parsing: "Q1 FY25", "Q3 FY2024", "Q2FY24"
_Q_FY_RE = re.compile(
    r"\bQ\s*([1-4])\s*FY\s*(\d{2,4})\b", re.I,
)
# "Quarter ended 30 June 2024" / "Quarter ended June 30, 2024"
_QTR_ENDED_RE = re.compile(
    r"quarter\s+ended\s+"
    r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})"
    r"|([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}))",
    re.I,
)

_MONTHS = {
    m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"],
        start=1,
    )
}
_MONTHS_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_num(name: str) -> int | None:
    if not name:
        return None
    k = name.strip().lower().rstrip(".")
    return _MONTHS.get(k) or _MONTHS_ABBR.get(k[:3])


def get_nse_session():
    """Create a warmed-up curl_cffi session impersonating Chrome."""
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    # Warmup for cookies (NSE Akamai gate).
    try:
        session.get(NSE_BASE, timeout=30)
    except Exception as exc:
        logger.debug(f"NSE warmup non-fatal: {exc}")
    return session


def is_concall_record(subject: str, category: str | None) -> bool:
    """Return True if this filing looks like a concall / analyst meet."""
    s = (subject or "").lower()
    c = (category or "").lower()

    if any(h in c for h in _CATEGORY_HINTS):
        return True
    if any(p.search(s) for p in _SUBJECT_PATTERNS):
        return True
    return False


def parse_quarter_end(subject: str) -> date | None:
    """Best-effort quarter-end parse from a filing subject line."""
    if not subject:
        return None

    # Pattern 1: "Quarter ended <date>"
    m = _QTR_ENDED_RE.search(subject)
    if m:
        try:
            if m.group(1):   # "30 June 2024"
                d = int(m.group(1))
                mo = _month_num(m.group(2))
                y = int(m.group(3))
            else:            # "June 30, 2024"
                mo = _month_num(m.group(4))
                d = int(m.group(5))
                y = int(m.group(6))
            if mo:
                return date(y, mo, d)
        except (ValueError, TypeError):
            pass

    # Pattern 2: "Q<n> FY<yy|yyyy>" -> quarter end is last day of the
    # Indian fiscal quarter. FY25 = April 2024 - March 2025.
    #   Q1 FY25 -> 30 Jun 2024
    #   Q2 FY25 -> 30 Sep 2024
    #   Q3 FY25 -> 31 Dec 2024
    #   Q4 FY25 -> 31 Mar 2025
    m = _Q_FY_RE.search(subject)
    if m:
        try:
            q = int(m.group(1))
            fy_raw = int(m.group(2))
            fy = fy_raw if fy_raw >= 100 else 2000 + fy_raw
            # fy 2025 spans Apr 2024 -> Mar 2025
            if q == 1:
                return date(fy - 1, 6, 30)
            if q == 2:
                return date(fy - 1, 9, 30)
            if q == 3:
                return date(fy - 1, 12, 31)
            if q == 4:
                return date(fy, 3, 31)
        except (ValueError, TypeError):
            pass

    return None


def _parse_filing_date(raw: str | None) -> date | None:
    """Parse NSE filing date strings into a date."""
    if not raw:
        return None
    raw = raw.strip()
    # Common NSE formats
    fmts = [
        "%d-%b-%Y %H:%M:%S", "%d-%b-%Y",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    ]
    for f in fmts:
        try:
            return datetime.strptime(raw, f).date()
        except ValueError:
            continue
    return None


def fetch_filings_for_symbol(
    symbol: str,
    from_date: date,
    to_date: date,
    session=None,
    timeout: int = 30,
) -> list[dict]:
    """
    Hit NSE corporate-announcements for a single symbol and return
    records (raw JSON items) with basic shape-normalization. The
    filter for concall-ness is applied by the caller via
    is_concall_record().
    """
    sess = session or get_nse_session()
    url = NSE_CORP_ANN_URL.format(
        from_date=from_date.strftime("%d-%m-%Y"),
        to_date=to_date.strftime("%d-%m-%Y"),
        symbol=symbol,
    )
    try:
        resp = sess.get(url, timeout=timeout)
    except Exception as exc:
        logger.warning(f"NSE concall fetch error for {symbol}: {exc}")
        return []

    if resp.status_code != 200:
        logger.debug(
            f"NSE corp-ann HTTP {resp.status_code} for {symbol}"
        )
        return []

    try:
        data = resp.json()
    except Exception as exc:
        logger.debug(f"NSE corp-ann non-JSON for {symbol}: {exc}")
        return []

    # NSE returns either a list, or a dict with "data" key.
    if isinstance(data, dict):
        items = data.get("data") or data.get("rows") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


def normalize_record(item: dict, ticker: str) -> dict | None:
    """Map a raw NSE announcement dict to our storable shape.

    NSE corporate-announcements records use:
      - `attchmntText` for the free-text subject / description
      - `desc` for the broad category label
      - `an_dt` ("17-Apr-2026 18:20:49") for filing datetime
      - `attchmntFile` for the PDF URL
    With a few legacy aliases tolerated defensively.
    """
    subject = (
        item.get("attchmntText")
        or item.get("subject")
        or item.get("smDesc")
        or item.get("sub")
        or ""
    )
    subject = str(subject).strip()

    category = (
        item.get("desc")
        or item.get("category")
        or item.get("sm_desc")
        or item.get("smDesc")
        or ""
    )
    category = str(category).strip() or None

    # If subject is empty, fall back to category so we still have SOMETHING
    # to dedupe on -- the unique constraint requires a non-null subject.
    if not subject:
        subject = category or ""
    if not subject:
        return None

    if not is_concall_record(subject, category):
        return None

    raw_dt = (
        item.get("an_dt")
        or item.get("sort_date")
        or item.get("announcementDate")
        or item.get("exchdisstime")
        or item.get("dt")
    )
    fdate = _parse_filing_date(str(raw_dt) if raw_dt else None)
    if not fdate:
        return None

    pdf_url = (
        item.get("attchmntFile")
        or item.get("attchmntfile")
        or item.get("attachment")
        or item.get("attchmnt")
    )
    if pdf_url:
        pdf_url = str(pdf_url).strip() or None

    return {
        "ticker": ticker,
        "filing_date": fdate,
        "quarter_end": parse_quarter_end(subject),
        "pdf_url": pdf_url,
        "subject": subject[:2000],   # defensive cap
        "category": (category[:200] if category else None),
    }


def upsert_records(rows: Iterable[dict], db: Session) -> int:
    """
    INSERT ... ON CONFLICT DO NOTHING on the natural dedupe key
    (ticker, filing_date, subject). Returns number of NEW rows.
    """
    new_rows = 0
    stmt = text(
        "INSERT INTO concall_transcripts "
        "  (ticker, filing_date, quarter_end, pdf_url, subject, category) "
        "VALUES "
        "  (:ticker, :filing_date, :quarter_end, :pdf_url, :subject, :category) "
        "ON CONFLICT ON CONSTRAINT uq_concall_ticker_date_subject "
        "DO NOTHING "
        "RETURNING id"
    )
    for row in rows:
        try:
            result = db.execute(stmt, row)
            if result.fetchone() is not None:
                new_rows += 1
        except Exception as exc:
            logger.debug(f"concall insert skipped ({row.get('ticker')}): {exc}")
            db.rollback()
            continue
    try:
        db.commit()
    except Exception as exc:
        logger.error(f"concall commit failed, rolling back: {exc}")
        db.rollback()
        return 0
    return new_rows
