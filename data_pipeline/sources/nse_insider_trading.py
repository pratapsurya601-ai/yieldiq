"""NSE insider-trading source — SEBI PIT Reg 7 disclosures.

NSE serves ~9-10 years of insider buy/sell records at
``/api/corporates-pit``. Two query shapes:

  * Per symbol:  ?index=equities&symbol=RELIANCE
  * Per year:    ?index=equities&from=01-01-2024&to=31-12-2024
                 (full universe — ~13MB JSON for a busy year)

Response shape (top-level either a list or ``{data: [...]}``):

  [
    {
      "symbol": "RELIANCE",
      "isin": "INE002A01018",
      "date": "13-Mar-2024",
      "acqName": "Mukesh D. Ambani",
      "acqCategory": "Promoter",
      "tdpTransactionType": "Market Purchase",
      "secAcq": 1000, "secVal": 30.00,                   # buy: qty/value-cr
      "secSold": 0,   "secValSold": 0,                   # sell: qty/value-cr
      "befAcqSharesPer": "10.0", "afterAcqSharesPer": "10.05",
      "anex": "C",
      "xbrl": "https://archives.nseindia.com/.../filing.pdf"
    },
    ...
  ]

Key naming on NSE varies between endpoints — we tolerate aliases. We
deliberately store transaction_value in ₹ crore (NSE's own unit) so
display code doesn't need to scale.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_API_BASE = "https://www.nseindia.com/api"
NSE_WARMUP = "https://www.nseindia.com/get-quotes/equity?symbol={symbol}"


# ── session helper (cookie warm-up — NSE blocks plain requests) ─────

def _get_session():
    """curl_cffi Chrome-impersonate session, with NSE homepage warm-up."""
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    try:
        s.get(NSE_BASE + "/", timeout=15)
    except Exception:
        pass
    return s


def _warmup_symbol(session, symbol: str) -> None:
    try:
        session.get(NSE_WARMUP.format(symbol=symbol), timeout=10)
    except Exception:
        pass


# ── parsing ─────────────────────────────────────────────────────────

def _parse_date(s: str | None):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_int(v: Any) -> int:
    if v in (None, "", "-"):
        return 0
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _to_float(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def _normalize_record(rec: dict, fallback_symbol: str | None = None) -> dict | None:
    """Map an NSE PIT record to our insider_trading schema.

    Returns None when the row is unusable (no symbol or no date).
    """
    if not isinstance(rec, dict):
        return None

    symbol = (rec.get("symbol") or fallback_symbol or "").strip().upper()
    if not symbol:
        return None

    filing_date = _parse_date(
        rec.get("date")
        or rec.get("acquisitionMode")
        or rec.get("disclosureDate")
        or rec.get("dateOfReceipt")
    )
    if filing_date is None:
        return None

    buy_qty = _to_int(rec.get("secAcq") or rec.get("secAcquired"))
    sell_qty = _to_int(rec.get("secSold") or rec.get("secVal_Sold"))
    # Value reported in ₹ crore on NSE; pick whichever side is non-zero.
    val_cr = _to_float(rec.get("secVal")) or _to_float(rec.get("secValSold"))

    return {
        "ticker": symbol,
        "isin": (rec.get("isin") or "").strip() or None,
        "filing_date": filing_date,
        "acquirer_name": (rec.get("acqName") or "").strip()[:256] or None,
        "acquirer_category": (rec.get("acqCategory") or rec.get("personCategory") or "").strip()[:64] or None,
        "transaction_type": (rec.get("tdpTransactionType") or rec.get("acqMode") or "").strip()[:32] or None,
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "transaction_value_cr": val_cr,
        "holding_before_pct": _to_float(rec.get("befAcqSharesPer") or rec.get("beforeAcqSharesPer")),
        "holding_after_pct": _to_float(rec.get("afterAcqSharesPer") or rec.get("afterAcqSharesPercentage")),
        "annex_type": (rec.get("anex") or "").strip()[:16] or None,
        "pdf_url": (rec.get("xbrl") or rec.get("pdfUrl") or "").strip() or None,
    }


def _unwrap_payload(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in ("data", "Table", "acqNameList", "records"):
            v = data.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


# ── public fetchers ────────────────────────────────────────────────

def fetch_insider_trading_for_symbol(symbol: str, session=None) -> list[dict]:
    """Pull the full ~10-year insider-trading history for one symbol."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return []
    if session is None:
        session = _get_session()
    _warmup_symbol(session, sym)
    url = f"{NSE_API_BASE}/corporates-pit?index=equities&symbol={sym}"
    try:
        r = session.get(url, timeout=30, headers={"Accept": "application/json"})
    except Exception as exc:
        logger.info("nse insider per-symbol error %s: %s", sym, exc)
        return []
    if r.status_code != 200:
        logger.info("nse insider per-symbol HTTP %d for %s", r.status_code, sym)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    raw = _unwrap_payload(data)
    out: list[dict] = []
    for rec in raw:
        norm = _normalize_record(rec, fallback_symbol=sym)
        if norm:
            out.append(norm)
    return out


def fetch_insider_trading_for_year(year: int, session=None) -> list[dict]:
    """Pull the full universe for a calendar year (one big call).

    NSE's per-year endpoint returns every ticker's PIT disclosures —
    far cheaper than iterating the universe per-symbol.
    """
    if session is None:
        session = _get_session()
    frm = f"01-01-{year:04d}"
    to = f"31-12-{year:04d}"
    url = (
        f"{NSE_API_BASE}/corporates-pit?index=equities"
        f"&from={frm}&to={to}"
    )
    try:
        r = session.get(url, timeout=120, headers={"Accept": "application/json"})
    except Exception as exc:
        logger.warning("nse insider per-year %d error: %s", year, exc)
        return []
    if r.status_code != 200:
        logger.warning("nse insider per-year %d HTTP %d", year, r.status_code)
        return []
    try:
        data = r.json()
    except Exception:
        logger.warning("nse insider per-year %d: invalid JSON", year)
        return []
    raw = _unwrap_payload(data)
    out: list[dict] = []
    for rec in raw:
        norm = _normalize_record(rec)
        if norm:
            out.append(norm)
    logger.info("nse insider %d: %d normalized rows", year, len(out))
    return out
