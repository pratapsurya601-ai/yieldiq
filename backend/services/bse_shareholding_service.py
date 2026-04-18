"""
bse_shareholding_service.py — BSE shareholding pattern fetcher.

Pulls the JSON the BSE website itself consumes:
  https://api.bseindia.com/BseIndiaAPI/api/ShareholdingPattern/w?scripcode={code}

For each ticker with a known `stocks.bse_code` we read the two most
recent quarterly filings and compute:
  - promoter_delta_qoq   (percentage points, latest - previous)
  - pledged_pct_delta    (percentage points, latest - previous)
  - latest_promoter_pct
  - latest_pledged_pct
  - quarter_end          (ISO date of latest filing)

Rows without both quarters are skipped — we only emit deltas that are
actually comparable QoQ.

Nothing here constitutes investment advice. These are raw regulatory
disclosures feeding the Pulse axis of the YieldIQ Hex.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("yieldiq.pulse.bse_shareholding")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


_BSE_SHP_URL = "https://api.bseindia.com/BseIndiaAPI/api/ShareholdingPattern/w?scripcode={code}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; YieldIQ/1.0)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

_CACHE_DIR = Path(os.environ.get("BSE_SHP_CACHE_DIR", "/tmp/bse_cache"))
_CACHE_TTL = timedelta(days=7)
_REQUEST_SLEEP_S = 0.5  # between requests
_RETRY_BACKOFF_S = 2.0


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _get_session_factory():
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from data_pipeline.db import Session  # type: ignore
        return Session
    except Exception as exc:
        logger.warning("could not import data_pipeline.db.Session: %s", exc)
        return None


def _load_bse_code_map(tickers: List[str]) -> Dict[str, str]:
    """Return {ticker: bse_code} for tickers that have one."""
    if not tickers:
        return {}
    Session = _get_session_factory()
    if Session is None:
        return {}
    from sqlalchemy import text as _t
    sess = Session()
    try:
        rows = sess.execute(
            _t(
                "SELECT ticker, bse_code FROM stocks "
                "WHERE bse_code IS NOT NULL AND ticker = ANY(:tickers)"
            ),
            {"tickers": list(tickers)},
        ).fetchall()
        return {r[0]: str(r[1]).strip() for r in rows if r and r[1]}
    except Exception as exc:
        logger.warning("bse_code map load failed: %s", exc)
        return {}
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(code: str) -> Path:
    return _CACHE_DIR / f"{code}.json"


def _read_cache(code: str) -> Optional[Any]:
    p = _cache_path(code)
    try:
        if not p.exists():
            return None
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        if datetime.now() - mtime > _CACHE_TTL:
            return None
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(code: str, data: Any) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(code).open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as exc:
        logger.debug("cache write failed for %s: %s", code, exc)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _fetch_shareholding(session, code: str) -> Optional[Any]:
    cached = _read_cache(code)
    if cached is not None:
        return cached

    url = _BSE_SHP_URL.format(code=code)
    for attempt in range(2):
        try:
            resp = session.get(url, headers=_HEADERS, timeout=30)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.debug("BSE SHP %s: non-JSON", code)
                    return None
                _write_cache(code, data)
                return data
            if resp.status_code in (429, 503) or 500 <= resp.status_code < 600:
                time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
                continue
            logger.debug("BSE SHP %s HTTP %s", code, resp.status_code)
            return None
        except Exception as exc:
            logger.debug("BSE SHP %s attempt %d error: %s", code, attempt + 1, exc)
            time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _rows_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """BSE wraps quarterly rows in either a list or {'Table': [...]}."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("Table", "data", "result"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _pick_float(row: Dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            try:
                return float(str(row[k]).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
        # case-insensitive fallback
        for rk in row.keys():
            if rk and rk.strip().lower() == k.lower():
                v = row[rk]
                if v not in (None, ""):
                    try:
                        return float(str(v).replace(",", "").strip())
                    except (TypeError, ValueError):
                        continue
    return None


def _pick_date(row: Dict[str, Any], *keys: str) -> Optional[datetime]:
    raw = None
    for k in keys:
        if k in row and row[k]:
            raw = str(row[k]).strip()
            break
        for rk in row.keys():
            if rk and rk.strip().lower() == k.lower() and row[rk]:
                raw = str(row[rk]).strip()
                break
        if raw:
            break
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.split(".")[0], fmt)
        except ValueError:
            continue
    return None


def _parse_quarters(payload: Any) -> List[Dict[str, Any]]:
    """Return [{quarter_end: date, promoter_pct: float, pledged_pct: float}, ...]
    sorted DESC by quarter_end, skipping rows without a parseable date."""
    out: List[Dict[str, Any]] = []
    for row in _rows_from_payload(payload):
        qe = _pick_date(
            row,
            "QUARTER_END_DATE", "QUARTER_END", "QTR_END", "quarter_end_date",
            "Quarter_End_Date", "AS_ON_DATE",
        )
        if qe is None:
            continue
        promoter = _pick_float(
            row,
            "PROMOTER_TOTAL_PER", "PROMOTER_TOTAL", "Promoter_Total_Per",
            "PromoterTotalPer",
        )
        pledged = _pick_float(
            row,
            "PLEDGED_SHARES_PER", "PLEDGED_PER", "PledgedSharesPer",
            "Pledged_Shares_Per",
        )
        if promoter is None and pledged is None:
            continue
        out.append({
            "quarter_end": qe,
            "promoter_pct": promoter,
            "pledged_pct": pledged,
        })
    out.sort(key=lambda d: d["quarter_end"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_bse_shareholding_batch(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """See module docstring. Returns {ticker: {...}} only where both the
    latest and previous quarter data exist."""
    out: Dict[str, Dict[str, Any]] = {}
    if not tickers:
        return out

    mapping = _load_bse_code_map(tickers)
    if not mapping:
        logger.info("BSE SHP: no bse_code mapping found for any of %d tickers", len(tickers))
        return out

    try:
        import requests
    except Exception as exc:
        logger.warning("BSE SHP: requests unavailable: %s", exc)
        return out

    session = requests.Session()
    # Prime cookies by hitting bseindia.com once — some regions require this.
    try:
        session.get("https://www.bseindia.com/", headers=_HEADERS, timeout=15)
    except Exception:
        pass

    matched = 0
    for ticker, code in mapping.items():
        try:
            payload = _fetch_shareholding(session, code)
            if payload is None:
                continue
            quarters = _parse_quarters(payload)
            if len(quarters) < 2:
                continue
            latest, prev = quarters[0], quarters[1]

            # Need at least promoter OR pledged to compute something useful.
            promoter_delta = None
            if latest.get("promoter_pct") is not None and prev.get("promoter_pct") is not None:
                promoter_delta = float(latest["promoter_pct"]) - float(prev["promoter_pct"])
            pledged_delta = None
            if latest.get("pledged_pct") is not None and prev.get("pledged_pct") is not None:
                pledged_delta = float(latest["pledged_pct"]) - float(prev["pledged_pct"])

            if promoter_delta is None and pledged_delta is None:
                continue

            out[ticker] = {
                "promoter_delta_qoq": (
                    round(promoter_delta, 4) if promoter_delta is not None else None
                ),
                "pledged_pct_delta": (
                    round(pledged_delta, 4) if pledged_delta is not None else None
                ),
                "latest_promoter_pct": latest.get("promoter_pct"),
                "latest_pledged_pct": latest.get("pledged_pct"),
                "quarter_end": latest["quarter_end"].date().isoformat(),
            }
            matched += 1
        except Exception as exc:
            logger.debug("BSE SHP %s (%s) failed: %s", ticker, code, exc)
        finally:
            time.sleep(_REQUEST_SLEEP_S)

    logger.info("BSE SHP: %d/%d tickers with QoQ data (of %d with bse_code)",
                matched, len(tickers), len(mapping))
    return out
