"""BSE securities master fetcher — daily bhavcopy as the universe roster.

The BSE corporate-actions / List_Scrips endpoint is gated by Akamai and
serves a JS challenge to non-browser clients (same pattern as the
Peercomp endpoint that broke earlier in 2026). The daily bhavcopy on
``download/BhavCopy/Equity/`` is open and stable — every active BSE
equity that traded that day appears with ``ISIN``, ``FinInstrmId`` (the
6-digit BSE scrip code), ``TckrSymb`` and ``FinInstrmNm``.

Source (verified 2026-04-29):

    https://www.bseindia.com/download/BhavCopy/Equity/
        BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV

  ~4,800 rows / day across all groups (A, B, T, X, Z, M).
  Liquid groups: A, B, X. Skip T (trade-to-trade), Z (suspended),
  M (mutual-fund-style trust units) for the universe-expansion goal.

This module is a thin reusable wrapper around the same fetch already
used by ``scripts/ingest_bse_only_universe.py``. It returns rows in the
same dict shape as ``nse_total_market`` so the universe-expansion
runner can iterate uniformly across exchanges.
"""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

BHAV_URL = (
    "https://www.bseindia.com/download/BhavCopy/Equity/"
    "BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
)

DEFAULT_GROUPS: tuple[str, ...] = ("A", "B", "X")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,application/octet-stream,*/*",
    "Referer": "https://www.bseindia.com/",
}


def _fetch_csv(trade_date: date):
    import requests
    url = BHAV_URL.format(yyyymmdd=trade_date.strftime("%Y%m%d"))
    try:
        r = requests.get(url, headers=_HEADERS, timeout=30)
    except Exception as exc:
        logger.warning("BSE bhavcopy fetch error %s: %s", trade_date, exc)
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200 or len(r.content) < 1000:
        logger.warning("BSE bhavcopy %s: HTTP %s, %d bytes",
                       trade_date, r.status_code, len(r.content))
        return None
    return r.content


def _latest_available(max_lookback: int = 7):
    """Walk back from today until we find a non-holiday with a posted bhavcopy."""
    for back in range(max_lookback + 1):
        d = date.today() - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        body = _fetch_csv(d)
        if body is not None:
            return body, d
    return None, None


def fetch_securities_master(
    trade_date: date | None = None,
    groups: tuple[str, ...] = DEFAULT_GROUPS,
) -> list[dict]:
    """Return all liquid-group BSE equities as normalised dicts.

    Output keys: ticker, name, isin, series, listing_date=None,
    exchange='BSE', board='MAIN', bse_code.

    ``ticker`` is the canonical BSE TckrSymb (uppercased). The caller is
    responsible for collision-handling against existing NSE tickers.
    """
    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas required for BSE securities master")
        return []

    if trade_date is None:
        body, used_date = _latest_available()
        if body is None:
            logger.error("BSE: no bhavcopy available in last 7 days")
            return []
    else:
        body = _fetch_csv(trade_date)
        used_date = trade_date
        if body is None:
            logger.error("BSE: bhavcopy for %s not available", trade_date)
            return []

    logger.info("BSE bhavcopy: using trade_date=%s", used_date)

    df = pd.read_csv(io.BytesIO(body))
    if "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].astype(str).str.strip().str.upper() == "STK"].copy()
    if "SctySrs" in df.columns:
        df["SctySrs"] = df["SctySrs"].astype(str).str.strip().str.upper()
        df = df[df["SctySrs"].isin(groups)].copy()
    df["ISIN"] = df["ISIN"].astype(str).str.strip().str.upper()
    df["FinInstrmId"] = df["FinInstrmId"].astype(str).str.strip()
    df["TckrSymb"] = df["TckrSymb"].astype(str).str.strip().str.upper()
    df["FinInstrmNm"] = df["FinInstrmNm"].astype(str).str.strip()
    df = df[df["ISIN"].str.len() == 12].copy()

    rows: list[dict] = []
    for _, row in df.iterrows():
        rows.append({
            "ticker": row["TckrSymb"],
            "name": (row["FinInstrmNm"] or None) and row["FinInstrmNm"][:200],
            "isin": row["ISIN"],
            "series": row["SctySrs"],
            "listing_date": None,
            "exchange": "BSE",
            "board": "MAIN",
            "bse_code": row["FinInstrmId"],
        })
    logger.info("BSE securities master: %d rows (groups=%s)", len(rows), groups)
    return rows
