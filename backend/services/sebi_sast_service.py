"""
sebi_sast_service.py — SEBI SAST / PIT insider-filing fetcher.

Ingests the NSE Prohibition of Insider Trading (PIT) disclosure feed at
  https://www.nseindia.com/api/corporates-pit
which surfaces the same Reg 7 insider trading disclosures SEBI requires
under the SAST / PIT regulations. One HTTP call returns every disclosure
in the requested date window, so we fetch once and aggregate per ticker.

Per ticker over the last `days`:
  - Sum SECVAL where NOOFSECACQ > 0       (acquisitions)
  - Minus sum SECVAL where NOOFSECSOLD > 0 (disposals)
  - Convert INR → INR Cr (divide by 1e7)
  - Only include promoter / director / KMP / designated-person categories.

These are raw regulatory disclosures — nothing here constitutes
investment advice.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("yieldiq.pulse.sebi_sast")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


_NSE_HOME = "https://www.nseindia.com/"
_NSE_PIT_URL = (
    "https://www.nseindia.com/api/corporates-pit"
    "?index=equities&from_date={from_d}&to_date={to_d}"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; YieldIQ/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    "Connection": "keep-alive",
}

_INCLUDE_CATEGORIES = {
    "promoters", "promoter group", "promoter",
    "director", "directors",
    "kmp", "key managerial personnel",
    "designated person", "designated persons",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _pick(row: Dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return str(row[k]).strip()
        for rk in row.keys():
            if rk and rk.strip().lower() == k.lower() and row[rk] not in (None, ""):
                return str(row[rk]).strip()
    return None


def _to_float(v: Optional[str]) -> float:
    if not v:
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _rows_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("data", "DATA", "rows", "result"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _is_included_category(cat: Optional[str]) -> bool:
    if not cat:
        return False
    c = cat.strip().lower()
    if c in _INCLUDE_CATEGORIES:
        return True
    # Some rows embed category like "Promoter & Promoter Group" or
    # "Director/KMP" — substring check as a safety net.
    return any(k in c for k in _INCLUDE_CATEGORIES)


# ---------------------------------------------------------------------------
# HTTP (NSE needs cookie priming)
# ---------------------------------------------------------------------------

def _fetch_pit(days: int) -> List[Dict[str, Any]]:
    try:
        import requests
    except Exception as exc:
        logger.warning("SEBI SAST: requests unavailable: %s", exc)
        return []

    to_d = date.today()
    from_d = to_d - timedelta(days=max(1, int(days)))
    url = _NSE_PIT_URL.format(
        from_d=from_d.strftime("%d-%m-%Y"),
        to_d=to_d.strftime("%d-%m-%Y"),
    )

    session = requests.Session()
    # NSE rejects calls that arrive without the site cookies. Prime by
    # visiting the home and filings pages first.
    try:
        session.get(_NSE_HOME, headers=_HEADERS, timeout=15)
        session.get(_HEADERS["Referer"], headers=_HEADERS, timeout=15)
    except Exception as exc:
        logger.info("SEBI SAST: cookie prime failed: %s", exc)

    for attempt in range(2):
        try:
            resp = session.get(url, headers=_HEADERS, timeout=30)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.info("SEBI SAST: non-JSON body len=%d", len(resp.content or b""))
                    return []
                return _rows_from_payload(data)
            if resp.status_code in (403, 429, 503) or 500 <= resp.status_code < 600:
                time.sleep(2.0 * (attempt + 1))
                continue
            logger.info("SEBI SAST HTTP %s", resp.status_code)
            return []
        except Exception as exc:
            logger.info("SEBI SAST attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2.0 * (attempt + 1))
    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_sebi_sast_batch(tickers: List[str], days: int = 30) -> Dict[str, Dict[str, Any]]:
    """Returns {ticker: {"insider_net_30d": float}}  # INR Cr, signed."""
    out: Dict[str, Dict[str, Any]] = {}
    if not tickers:
        return out

    rows = _fetch_pit(days)
    if not rows:
        logger.info("SEBI SAST: no rows fetched")
        return out

    ticker_set = {t.upper() for t in tickers}
    agg: Dict[str, Dict[str, float]] = {}

    for r in rows:
        sym = _pick(r, "symbol", "SYMBOL", "Symbol")
        if not sym:
            continue
        sym_u = sym.upper()
        if sym_u not in ticker_set:
            continue

        cat = _pick(r, "personCategory", "category", "CATEGORY", "Category",
                    "acqMode", "personcategory")
        if not _is_included_category(cat):
            continue

        acq_qty = _to_float(_pick(r, "secAcq", "NOOFSECACQ", "noOfSecAcq", "NoOfSecAcq"))
        sold_qty = _to_float(_pick(r, "secSold", "NOOFSECSOLD", "noOfSecSold", "NoOfSecSold"))
        secval = _to_float(_pick(r, "secVal", "SECVAL", "secval", "SecVal"))

        if secval <= 0:
            continue

        bucket = agg.setdefault(sym_u, {"net_inr": 0.0, "count": 0})
        if acq_qty > 0 and sold_qty <= 0:
            bucket["net_inr"] += secval
            bucket["count"] += 1
        elif sold_qty > 0 and acq_qty <= 0:
            bucket["net_inr"] -= secval
            bucket["count"] += 1
        else:
            # Rows with both buy and sell (rare, reclassifications) —
            # skip rather than double-count.
            continue

    for sym, data in agg.items():
        out[sym] = {
            "insider_net_30d": round(data["net_inr"] / 1e7, 4),
            "raw": {"filings": data["count"]},
        }

    logger.info("SEBI SAST: matched %d/%d tickers from %d filings",
                len(out), len(tickers), len(rows))
    return out
