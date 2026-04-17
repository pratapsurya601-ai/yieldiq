# data_pipeline/pipeline.py
# Main pipeline orchestrator.
# PRIMARY SOURCE: yfinance (NSE/BSE block Railway cloud IPs).
# NSE Bhavcopy and BSE XBRL are kept as optional sources for
# self-hosted deployments where IPs aren't blocked.
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import desc
from sqlalchemy.orm import Session

from data_pipeline.models import (
    DailyPrice,
    Financials,
    MarketMetrics,
    ShareholdingPattern,
)
from data_pipeline.sources.yfinance_supplement import (
    batch_fetch_fundamentals,
    batch_fetch_prices,
    fetch_and_store_yfinance,
    fetch_price_history,
)

logger = logging.getLogger(__name__)

# Complete NSE universe — quality stocks for YieldIQ analysis
NSE_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "HINDUNILVR",
    "INFY", "ITC", "SBIN", "BAJFINANCE", "KOTAKBANK",
    "AXISBANK", "LT", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "NESTLEIND", "ULTRACEMCO", "WIPRO", "HCLTECH",
    "ONGC", "POWERGRID", "NTPC", "COALINDIA", "JSWSTEEL",
    # TATAMOTORS was demerged (2024-25); TMPV is the passenger-vehicle successor
    "TMPV", "TATASTEEL", "TECHM", "DRREDDY", "DIVISLAB",
    "CIPLA", "APOLLOHOSP", "BAJAJFINSV", "ADANIPORTS", "GRASIM",
    "HEROMOTOCO", "EICHERMOT", "BAJAJ-AUTO", "TATACONSUM", "BRITANNIA",
    # BERGERPAINTS → BERGEPAINT (NSE canonical symbol)
    "PIDILITIND", "BERGEPAINT", "WHIRLPOOL", "MARICO", "DABUR",
    "COLPAL", "HINDPETRO", "BPCL", "IOC", "ICICIGI",
    # KPIT → KPITTECH (NSE canonical symbol)
    "HDFCLIFE", "SBILIFE", "LTIM", "PERSISTENT", "COFORGE",
    "MPHASIS", "OFSS", "KPITTECH", "TATAELXSI",
    # ZOMATO → ETERNAL (Nov 2024 rebrand); DOMINOS doesn't exist as separate
    # NSE ticker (JUBLFOOD is the franchisee, already in list); BARBEQUE
    # appears unlisted — removed
    "ETERNAL", "PAYTM", "NYKAA", "POLICYBZR", "IRCTC", "DMART",
    "INDIGO", "JUBLFOOD", "WESTLIFE",
    "BANKBARODA", "PNB", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
    "CHOLAFIN", "MUTHOOTFIN", "BAJAJHFL", "LICHSGFIN", "PNBHOUSING",
    # DALMIA → DALBHARAT (Dalmia Bharat Ltd)
    "AMBUJACEM", "SHREECEM", "JKCEMENT", "RAMCOCEM", "DALBHARAT",
    "HAVELLS", "VOLTAS", "BLUESTAR", "CROMPTON", "POLYCAB",
    "ASTRAL", "SUPREMEIND", "FINPIPE", "APLAPOLLO", "HINDALCO",
    "VEDL", "NATIONALUM", "HINDCOPPER", "SAIL", "NMDC",
]

# ISIN mapping — populate from NSE equity list or yfinance
ISIN_MAP: dict[str, str] = {}


def run_initial_setup(db: Session):
    """
    Run once when setting up the database for the first time.
    Uses yfinance as primary source (NSE/BSE block cloud IPs).
    Takes ~60-90 minutes for 100 stocks.
    """
    logger.info("=== Starting initial YieldIQ data setup (yfinance) ===")

    # Step 1: 3-year price history via yfinance
    logger.info("Step 1/3: Downloading 3-year price history via yfinance")
    price_ok, price_total = batch_fetch_prices(NSE_UNIVERSE, db, period="3y")
    logger.info(f"Prices done: {price_ok} stocks, {price_total} records")

    # Step 2: Fundamentals (financials + market metrics)
    logger.info("Step 2/3: Downloading fundamentals via yfinance")
    fund_ok, fund_fail = batch_fetch_fundamentals(NSE_UNIVERSE, db)
    logger.info(f"Fundamentals done: {fund_ok} ok, {fund_fail} failed")

    # Step 3: Try NSE/BSE as bonus (will silently fail on Railway)
    logger.info("Step 3/3: Attempting NSE/BSE supplement (may fail on cloud)")
    try:
        from data_pipeline.sources.nse_bhavcopy import download_corporate_actions
        download_corporate_actions(db)
    except Exception as e:
        logger.info(f"NSE corporate actions skipped: {e}")

    try:
        from data_pipeline.sources.nse_shareholding import download_bulk_shareholding
        current_year = date.today().year
        for quarter in [1, 2, 3, 4]:
            download_bulk_shareholding(current_year - 1, quarter, db)
    except Exception as e:
        logger.info(f"NSE shareholding skipped: {e}")

    logger.info("=== Initial setup complete ===")


def run_daily_update(db: Session):
    """
    Daily update — runs every trading day after market close.
    Re-downloads latest prices for all stocks.
    """
    logger.info("Starting daily data update")

    # Update prices for last 5 days (covers weekends + missed days)
    for ticker in NSE_UNIVERSE:
        fetch_price_history(f"{ticker}.NS", ticker, db, period="5d")

    # Bulk and block deals
    try:
        from data_pipeline.sources.nse_bulk_deals import fetch_daily_deals
        deals = fetch_daily_deals(db)
        logger.info(f"Bulk/block deals: {deals} stored")
    except Exception as e:
        logger.warning(f"Bulk deals step failed: {e}")

    # Upcoming earnings dates
    try:
        from data_pipeline.sources.nse_earnings import fetch_earnings_dates
        earnings = fetch_earnings_dates(db)
        logger.info(f"Earnings dates: {earnings} stored")
    except Exception as e:
        logger.warning(f"Earnings dates step failed: {e}")

    logger.info("Daily update complete")


def run_weekly_update(db: Session):
    """
    Weekly update — runs every Sunday.
    Updates fundamentals for all stocks. Takes 30-60 minutes.
    """
    logger.info("Starting weekly fundamentals update")
    batch_fetch_fundamentals(NSE_UNIVERSE, db)
    logger.info("Weekly update complete")


def get_stock_data_from_db(ticker: str, db: Session) -> dict:
    """
    Main function called by YieldIQ DCF engine.
    Returns all data needed for analysis from local database.
    Fast — no external API calls.
    """
    # Latest price
    latest_price = db.query(DailyPrice).filter_by(
        ticker=ticker,
    ).order_by(desc(DailyPrice.trade_date)).first()

    # Latest 5 years of annual financials
    financials = db.query(Financials).filter_by(
        ticker=ticker, period_type="annual",
    ).order_by(desc(Financials.period_end)).limit(5).all()

    # Latest shareholding
    shareholding = db.query(ShareholdingPattern).filter_by(
        ticker=ticker,
    ).order_by(desc(ShareholdingPattern.quarter_end)).first()

    # Latest market metrics
    metrics = db.query(MarketMetrics).filter_by(
        ticker=ticker,
    ).order_by(desc(MarketMetrics.trade_date)).first()

    # 52-week price range
    one_year_ago = date.today() - timedelta(days=365)
    price_history = db.query(DailyPrice).filter(
        DailyPrice.ticker == ticker,
        DailyPrice.trade_date >= one_year_ago,
    ).order_by(DailyPrice.trade_date).all()

    week_52_high = max((p.high_price for p in price_history if p.high_price), default=None) if price_history else None
    week_52_low = min((p.low_price for p in price_history if p.low_price), default=None) if price_history else None

    return {
        "ticker": ticker,
        "ticker_ns": f"{ticker}.NS",
        "currentPrice": latest_price.close_price if latest_price else None,
        "currency": "INR",

        # Financials (most recent year)
        "totalRevenue": _cr_to_raw(financials[0].revenue) if financials else None,
        "freeCashflow": _cr_to_raw(financials[0].free_cash_flow) if financials else None,
        "ebitda": _cr_to_raw(financials[0].ebitda) if financials else None,
        "operatingCashflow": _cr_to_raw(financials[0].cfo) if financials else None,
        "capitalExpenditures": _cr_to_raw(financials[0].capex) if financials else None,
        "totalDebt": _cr_to_raw(financials[0].total_debt) if financials else None,
        "totalCash": _cr_to_raw(financials[0].cash_and_equivalents) if financials else None,
        "sharesOutstanding": _lakhs_to_raw(financials[0].shares_outstanding) if financials else None,
        "returnOnEquity": financials[0].roe if financials else None,

        # Historical revenue (for growth rate calculation)
        "revenueHistory": [
            _cr_to_raw(f.revenue) for f in reversed(financials) if f.revenue
        ],
        "fcfHistory": [
            _cr_to_raw(f.free_cash_flow) for f in reversed(financials) if f.free_cash_flow
        ],

        # Market data
        "marketCap": _cr_to_raw(metrics.market_cap_cr) if metrics else None,
        "beta": metrics.beta_1yr if metrics else None,
        "trailingPE": metrics.pe_ratio if metrics else None,
        "priceToBook": metrics.pb_ratio if metrics else None,
        "dividendYield": (metrics.dividend_yield / 100) if metrics and metrics.dividend_yield else None,
        "52WeekHigh": week_52_high,
        "52WeekLow": week_52_low,

        # Shareholding
        "promoterHolding": shareholding.promoter_pct if shareholding else None,
        "fiiHolding": shareholding.fii_pct if shareholding else None,
        "diiHolding": shareholding.dii_pct if shareholding else None,

        # Data quality flags
        "_source": "local_db",
        "_fetched_at": datetime.utcnow().timestamp(),
        "_has_financials": len(financials) > 0,
        "_financials_years": len(financials),
    }


def _cr_to_raw(value_cr) -> float | None:
    """Convert Crore to raw rupees."""
    try:
        return float(value_cr) * 1e7 if value_cr else None
    except Exception:
        return None


def _lakhs_to_raw(value_lakhs) -> float | None:
    """Convert Lakhs to raw count."""
    try:
        return float(value_lakhs) * 1e5 if value_lakhs else None
    except Exception:
        return None
