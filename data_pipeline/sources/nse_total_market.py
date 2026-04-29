"""NSE Total Market universe fetcher — main board EQUITY_L + SME Emerge.

Phase A of the universe-5000 expansion. Pulls the NSE archive's official
equity master CSV (covers the full main-board universe, all series) and
the live NIFTY SME EMERGE index roster (the only reliable source for the
~500 active SME-board listings now that the legacy ``sme_list.csv``
archive 404s).

Sources (verified 2026-04-29):

  Main board:
      https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
      Columns: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING,
               PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
      ~2,360 rows, series in {EQ, BE, BZ}.

  SME (Emerge):
      https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20SME%20EMERGE
      JSON; ``data`` is a list of {symbol, series='SM', lastPrice, ...}.
      ~514 rows. The legacy archive CSV is empty/404; this is the only
      reliable canonical roster.

The SME endpoint is the same shape as the live-index APIs already used
by ``nse_sectoral_indices`` so we reuse the curl_cffi Chrome-impersonate
pattern (NSE blocks plain UAs).

This module returns deduped dicts; persistence is the caller's job
(see ``scripts/data_pipelines/expand_universe.py``).
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Iterable

logger = logging.getLogger(__name__)

EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SME_INDEX_URL = (
    "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20SME%20EMERGE"
)


def _session():
    """curl_cffi Chrome-impersonate session — NSE rejects bare requests UAs."""
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    # Warm cookies — NSE sets a session cookie on first GET / which the
    # archive + api endpoints both require.
    try:
        s.get("https://www.nseindia.com/", timeout=15)
        s.get(
            "https://www.nseindia.com/market-data/equity-stock-listings-on-nse-emerge",
            timeout=15,
        )
    except Exception as exc:
        logger.debug("NSE cookie warm-up swallowed exception: %s", exc)
    return s


def _parse_listing_date(raw: str):
    """Parse NSE 'DD-MON-YYYY' (e.g. '06-OCT-2008') -> date or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def fetch_main_board(session=None) -> list[dict]:
    """Return all rows from EQUITY_L.csv as normalised dicts.

    Output keys: ticker, name, isin, series, listing_date, exchange='NSE', board='MAIN'.
    """
    s = session or _session()
    r = s.get(EQUITY_L_URL, timeout=30)
    if r.status_code != 200:
        logger.error("EQUITY_L fetch failed: HTTP %s", r.status_code)
        return []
    text = r.text
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    # NSE pads column names with leading spaces — normalise.
    field_map = {k: k.strip().upper() for k in (reader.fieldnames or [])}
    for raw in reader:
        rec = {field_map[k]: (v or "").strip() for k, v in raw.items() if k in field_map}
        ticker = rec.get("SYMBOL", "").upper()
        if not ticker:
            continue
        isin = rec.get("ISIN NUMBER", "").upper() or None
        if isin and len(isin) != 12:
            isin = None
        rows.append({
            "ticker": ticker,
            "name": rec.get("NAME OF COMPANY") or None,
            "isin": isin,
            "series": rec.get("SERIES") or None,
            "listing_date": _parse_listing_date(rec.get("DATE OF LISTING", "")),
            "exchange": "NSE",
            "board": "MAIN",
        })
    logger.info("EQUITY_L: %d rows parsed", len(rows))
    return rows


def fetch_sme_emerge(session=None) -> list[dict]:
    """Return active NIFTY SME EMERGE constituents.

    The live-index JSON endpoint omits ISIN and company name — for SME we
    only persist {ticker, series='SM', exchange='NSE', board='SME'} on
    the first pass. Industry/financials enrichment is left to the
    downstream pipelines (fetch_industry, fetch_market_metrics).
    """
    s = session or _session()
    r = s.get(SME_INDEX_URL, timeout=30, headers={
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/market-data/equity-stock-listings-on-nse-emerge",
    })
    if r.status_code != 200:
        logger.error("SME EMERGE fetch failed: HTTP %s", r.status_code)
        return []
    try:
        payload = r.json()
    except Exception as exc:
        logger.error("SME EMERGE JSON parse failed: %s", exc)
        return []
    data = payload.get("data") or []
    rows: list[dict] = []
    for item in data:
        sym = (item.get("symbol") or "").strip().upper()
        # Skip the synthetic header row some NSE index responses include.
        if not sym or sym in {"NIFTY SME EMERGE", "SME EMERGE"}:
            continue
        rows.append({
            "ticker": sym,
            "name": None,
            "isin": None,
            "series": (item.get("series") or "SM").strip().upper(),
            "listing_date": None,
            "exchange": "NSE",
            "board": "SME",
        })
    logger.info("NIFTY SME EMERGE: %d rows parsed", len(rows))
    return rows


def fetch_all(session=None) -> list[dict]:
    """Return deduplicated main-board + SME rows.

    De-dup key: ticker. If the same ticker shows up in both rosters
    (extremely rare — main-board takes precedence) the SME row is dropped.
    """
    s = session or _session()
    main = fetch_main_board(s)
    sme = fetch_sme_emerge(s)

    seen: set[str] = set()
    out: list[dict] = []
    for row in main:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        out.append(row)
    sme_added = 0
    for row in sme:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        out.append(row)
        sme_added += 1
    logger.info(
        "fetch_all: %d total (%d main-board + %d SME after dedup)",
        len(out), len(main), sme_added,
    )
    return out
