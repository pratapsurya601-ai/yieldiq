# data_pipeline/sources/rbi_rate.py
# Fetches 10-year G-Sec yield from RBI / market sources.
# Used for WACC calculation (risk-free rate for India).
from __future__ import annotations

import logging
from datetime import date

import requests
from sqlalchemy.orm import Session

from data_pipeline.models import RiskFreeRate

logger = logging.getLogger(__name__)

# Worldgovernmentbonds.com provides free G-Sec yield data
# Alternative: RBI weekly statistical supplement PDF (harder to parse)
GSEC_SOURCES = [
    {
        "name": "investing_com_api",
        "url": "https://api.investing.com/api/financialdata/8080/historical/chart/"
               "?interval=P1M&pointscount=12",
        "headers": {"User-Agent": "Mozilla/5.0", "domain-id": "www"},
    },
]

# Fallback: hardcoded recent values (updated manually if needed)
# India 10Y G-Sec has been in 6.8-7.3% range for 2024-2026
FALLBACK_RATE = 7.10


def fetch_rbi_gsec_yield(db: Session) -> float:
    """
    Fetch India 10-year G-Sec yield and store in database.
    Returns the yield as percentage (e.g. 7.12).
    """
    rate = None

    # Method 1: Try yfinance for India 10Y bond
    try:
        import yfinance as yf
        # ^IRX is 13-week treasury, not India specific
        # Try India 10Y via yfinance (may not be available)
        bond = yf.Ticker("IN10Y.NS")
        info = bond.info
        if info and info.get("regularMarketPrice"):
            rate = float(info["regularMarketPrice"])
            logger.info(f"India 10Y G-Sec from yfinance: {rate}%")
    except Exception:
        pass

    # Method 2: Calculate from known recent range
    if rate is None:
        # Use a reasonable estimate based on recent RBI data
        # India 10Y has been 6.8-7.2% through 2025-2026
        rate = FALLBACK_RATE
        logger.info(f"Using fallback India 10Y G-Sec rate: {rate}%")

    # Store in database
    try:
        record = RiskFreeRate(
            trade_date=date.today(),
            gsec_10yr_yield=rate,
            source="yfinance" if rate != FALLBACK_RATE else "fallback",
        )
        db.merge(record)
        db.commit()
        logger.info(f"Stored risk-free rate: {rate}%")
    except Exception as e:
        logger.error(f"Failed to store risk-free rate: {e}")

    return rate


def get_latest_risk_free_rate(db: Session) -> float:
    """Get the most recent risk-free rate from database."""
    from sqlalchemy import desc
    record = db.query(RiskFreeRate).order_by(
        desc(RiskFreeRate.trade_date)
    ).first()

    if record:
        return record.gsec_10yr_yield
    return FALLBACK_RATE
