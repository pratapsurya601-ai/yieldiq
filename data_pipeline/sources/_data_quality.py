"""Cross-cutting helpers for data-quality guards used by every ingest path."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_RANK_BY_SOURCE = {
    # Financials
    "NSE_XBRL": 10, "NSE_XBRL_SYNTH": 20,
    # Market metrics
    "NSE_QUOTE_API": 10, "NSE_BHAVCOPY": 20,
    "BSE_QUOTE": 30, "BSE_BHAVCOPY": 35,
    # Corporate actions
    "NSE_CORP_ANN": 10, "NSE_ARCHIVE": 15, "BSE_CORP_FILE": 30,
    # Shareholding
    "NSE_SHAREHOLDING": 10, "BSE_SHAREHOLDING": 30, "AMFI": 25,
    # Generic fallbacks
    "finnhub": 40, "yfinance": 50,
}

def rank_for(source: str | None) -> int:
    if not source:
        return 70
    return _RANK_BY_SOURCE.get(source, 70)


def log_anomaly(
    sess: Session,
    *,
    table_name: str,
    ticker: str | None,
    field: str,
    suspected_value: Any,
    reason: str,
    auto_handled: str,                    # 'rejected' | 'logged' | 'overwritten' | 'flagged'
    source: str | None = None,
    notes: str | None = None,
    raw_payload: dict | None = None,
) -> None:
    """Insert one row into data_anomalies. Best-effort; never raises."""
    try:
        sess.execute(sa_text("""
            INSERT INTO data_anomalies (
                table_name, ticker, field, suspected_value, plausible_range_or_reason,
                auto_handled, source, notes, raw_payload
            ) VALUES (:tbl, :tk, :fld, :val, :rsn, :hnd, :src, :nt, :raw::jsonb)
        """), {
            "tbl": table_name, "tk": ticker, "fld": field,
            "val": str(suspected_value)[:512] if suspected_value is not None else None,
            "rsn": reason[:512],
            "hnd": auto_handled, "src": source, "nt": notes,
            "raw": __import__("json").dumps(raw_payload) if raw_payload else None,
        })
        sess.commit()
    except Exception as e:
        logger.warning("log_anomaly failed (%s): %s", reason, e)
        try: sess.rollback()
        except Exception: pass


# Common validation predicates — return (is_valid, reason_if_not)
def is_plausible_pe(pe: float | None) -> tuple[bool, str]:
    if pe is None: return (True, "")
    if pe < 0: return (False, "PE < 0 (impossible for positive earnings)")
    if pe > 500: return (False, "PE > 500 (likely unit bug)")
    return (True, "")


def is_plausible_mcap(mcap: float | None, ticker: str = "") -> tuple[bool, str]:
    if mcap is None: return (False, "market_cap is NULL")
    if mcap <= 0: return (False, "market_cap <= 0")
    if mcap > 1e10: return (False, "market_cap > ₹10 trillion (likely overflow)")
    return (True, "")


def is_plausible_pb(pb: float | None) -> tuple[bool, str]:
    if pb is None: return (True, "")
    if pb < 0: return (False, "PB < 0")
    if pb > 100: return (False, "PB > 100 (likely unit bug)")
    return (True, "")
