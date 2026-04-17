# data_pipeline/models.py
# SQLAlchemy schema for YieldIQ India data pipeline.
# All monetary values in Crore, share counts in Lakhs.
from sqlalchemy import (
    Column, String, Float, Integer, Date, DateTime,
    BigInteger, Boolean, Text, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Stock(Base):
    """Master list of all NSE listed stocks."""
    __tablename__ = "stocks"

    ticker = Column(String(20), primary_key=True)       # e.g. "RELIANCE"
    ticker_ns = Column(String(25), unique=True)          # e.g. "RELIANCE.NS"
    company_name = Column(String(200))
    isin = Column(String(12), unique=True)
    series = Column(String(5))                            # EQ, BE, etc.
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap_category = Column(String(20))              # Large/Mid/Small
    is_active = Column(Boolean, default=True)
    listed_date = Column(Date)
    updated_at = Column(DateTime, default=datetime.utcnow)


class DailyPrice(Base):
    """Daily OHLCV from NSE Bhavcopy."""
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_price_date"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("stocks.ticker"), index=True)
    trade_date = Column(Date, index=True)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    prev_close = Column(Float)
    volume = Column(BigInteger)
    turnover_cr = Column(Float)
    delivery_qty = Column(BigInteger)
    delivery_pct = Column(Float)
    trades = Column(Integer)
    vwap = Column(Float)
    adj_close = Column(Float)


class CorporateAction(Base):
    """Splits, bonuses, dividends from NSE."""
    __tablename__ = "corporate_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True)
    action_type = Column(String(500))         # SPLIT / BONUS / DIVIDEND
    ex_date = Column(Date)
    ratio = Column(String(200))               # e.g. "1:2" for split
    remarks = Column(Text)
    adjustment_factor = Column(Float)


class Financials(Base):
    """Annual and quarterly financials from BSE XBRL / yfinance."""
    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "period_type",
                         name="uq_financials_period"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("stocks.ticker"), index=True)
    isin = Column(String(12))
    period_end = Column(Date)
    period_type = Column(String(10))          # "annual" or "quarterly"
    filing_date = Column(Date)

    # Income Statement
    revenue = Column(Float)
    revenue_from_ops = Column(Float)
    ebitda = Column(Float)
    ebit = Column(Float)
    pbt = Column(Float)
    pat = Column(Float)
    eps_basic = Column(Float)
    eps_diluted = Column(Float)

    # Cash Flow Statement
    cfo = Column(Float)
    cfi = Column(Float)
    cff = Column(Float)
    capex = Column(Float)
    free_cash_flow = Column(Float)

    # Balance Sheet
    total_assets = Column(Float)
    total_equity = Column(Float)
    total_debt = Column(Float)
    cash_and_equivalents = Column(Float)
    net_debt = Column(Float)
    shares_outstanding = Column(Float)        # in Lakhs

    # Derived Ratios
    roe = Column(Float)
    roa = Column(Float)
    debt_to_equity = Column(Float)
    gross_margin = Column(Float)
    operating_margin = Column(Float)
    net_margin = Column(Float)
    fcf_margin = Column(Float)

    # Growth (vs prior year)
    revenue_growth_yoy = Column(Float)
    pat_growth_yoy = Column(Float)
    fcf_growth_yoy = Column(Float)

    data_source = Column(String(50))          # "BSE_XBRL" or "yfinance"
    raw_data = Column(Text)                   # JSON of original filing

    # Reporting currency of this filing. Most Indian issuers file in INR
    # but a handful (IT services, some pharma) file their consolidated
    # XBRL in USD. Tagging the column here lets the read path convert
    # USD → INR on demand instead of silently mixing magnitudes.
    currency = Column(String(3), nullable=False, default="INR",
                      server_default="INR")


class ShareholdingPattern(Base):
    """Quarterly shareholding from NSE."""
    __tablename__ = "shareholding_pattern"
    __table_args__ = (
        UniqueConstraint("ticker", "quarter_end", name="uq_sh_quarter"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True)
    quarter_end = Column(Date)
    promoter_pct = Column(Float)
    promoter_pledge_pct = Column(Float)
    fii_pct = Column(Float)
    dii_pct = Column(Float)
    public_pct = Column(Float)
    total_shares = Column(Float)


class MarketMetrics(Base):
    """Daily market-derived metrics."""
    __tablename__ = "market_metrics"
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_metrics_date"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True)
    trade_date = Column(Date, index=True)
    market_cap_cr = Column(Float)
    pe_ratio = Column(Float)
    pb_ratio = Column(Float)
    ev_cr = Column(Float)
    ev_ebitda = Column(Float)
    dividend_yield = Column(Float)
    beta_1yr = Column(Float)
    beta_3yr = Column(Float)


class RiskFreeRate(Base):
    """RBI 10-year G-Sec yield for WACC calculation."""
    __tablename__ = "risk_free_rates"

    trade_date = Column(Date, primary_key=True)
    gsec_10yr_yield = Column(Float)           # e.g. 7.12 (percent)
    source = Column(String(50))


class BulkDeal(Base):
    """Bulk and block deals from NSE."""
    __tablename__ = "bulk_deals"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "trade_date", "client_name", "deal_type",
            "deal_category", name="uq_bulk_deal"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True)
    trade_date = Column(Date)
    client_name = Column(String(200))
    deal_type = Column(String(10))            # BUY / SELL
    quantity = Column(BigInteger)
    price = Column(Float)
    deal_category = Column(String(10))        # bulk / block


class UpcomingEarnings(Base):
    """Upcoming earnings / financial results dates from NSE event calendar."""
    __tablename__ = "upcoming_earnings"
    __table_args__ = (
        UniqueConstraint("ticker", "event_date", name="uq_earnings_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True)
    event_date = Column(Date, index=True)
    event_type = Column(String(100))
    purpose = Column(String(500))
    updated_at = Column(DateTime, default=datetime.utcnow)


class DataFreshness(Base):
    """Tracks when each data type was last updated."""
    __tablename__ = "data_freshness"

    data_type = Column(String(50), primary_key=True)
    last_updated = Column(DateTime)
    last_trade_date = Column(Date)
    records_updated = Column(Integer)
    status = Column(String(20))               # "success" / "failed"
    error_msg = Column(Text)


class FairValueHistory(Base):
    """
    Forward-filled history of YieldIQ fair value estimates.
    One row per ticker per day. Populated by
    store_today_fair_value() after every analysis call.
    """
    __tablename__ = "fair_value_history"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_fv_ticker_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)
    fair_value = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    mos_pct = Column(Float, nullable=False)
    verdict = Column(String(20))
    wacc = Column(Float)
    confidence = Column(Integer)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
