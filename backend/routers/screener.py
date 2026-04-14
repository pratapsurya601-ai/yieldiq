# backend/routers/screener.py
# Stock screener — queries Aiven pipeline DB for real-time ranked stocks.
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query
from backend.models.responses import ScreenerResponse, ScreenerStock
from backend.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


def _query_stocks_from_db(min_score: int = 0, min_mos: float = -100,
                          page: int = 1, page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """Query stocks from Aiven pipeline database."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            return [], 0

        from sqlalchemy import text
        db = Session()
        try:
            # Get stocks with market metrics — rank by PE (lower = more undervalued)
            # Only show quality stocks: market cap > 2000 Cr, PE between 3-50
            query = text("""
                SELECT
                    s.ticker,
                    s.company_name,
                    mm.pe_ratio,
                    mm.pb_ratio,
                    mm.beta_1yr,
                    mm.market_cap_cr,
                    mm.dividend_yield
                FROM stocks s
                JOIN market_metrics mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
                ORDER BY mm.pe_ratio ASC
                LIMIT :lim OFFSET :off
            """)
            offset = (page - 1) * page_size
            rows = db.execute(query, {"lim": page_size, "off": offset}).fetchall()

            count_q = text("""
                SELECT COUNT(*) FROM stocks s
                JOIN market_metrics mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
            """)
            total = db.execute(count_q).scalar() or 0

            stocks = []
            for row in rows:
                ticker = row[0]
                name = row[1] or ticker
                pe = row[2] or 0
                pb = row[3] or 0
                beta = row[4] or 1.0
                mcap = row[5] or 0

                # Simple score: lower PE + lower PB = higher score
                pe_score = max(0, min(40, int((30 - pe) / 30 * 40))) if pe > 0 else 0
                pb_score = max(0, min(30, int((5 - pb) / 5 * 30))) if pb > 0 else 0
                simple_score = pe_score + pb_score + 20  # base 20

                # Simple MoS estimate from PE (sector median ~20)
                mos = round((20 - pe) / 20 * 100, 1) if pe > 0 else 0

                stocks.append(ScreenerStock(
                    ticker=f"{ticker}.NS" if "." not in ticker else ticker,
                    score=max(0, min(100, simple_score)),
                    margin_of_safety=mos,
                ))

            return stocks, total
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Screener DB query failed: {e}")
        return [], 0


def _query_preset_from_db(preset: str, page: int = 1,
                          page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """Run preset screener queries against Aiven DB."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            return [], 0

        from sqlalchemy import text
        db = Session()
        try:
            # Different queries for different presets
            # All presets require minimum market cap to filter out penny stocks
            # Market cap in Crore: >10,000 = large cap, >2,000 = mid cap
            if preset == "buffett":
                # Warren Buffett style: quality large caps at fair price
                # Low PE, decent PB, large market cap, dividend paying
                query = text("""
                    SELECT s.ticker, s.company_name, mm.pe_ratio, mm.pb_ratio,
                           mm.dividend_yield, mm.market_cap_cr
                    FROM stocks s
                    JOIN market_metrics mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                      AND mm.pe_ratio BETWEEN 8 AND 25
                      AND mm.pb_ratio BETWEEN 1 AND 8
                      AND mm.market_cap_cr > 10000
                      AND mm.dividend_yield > 0
                    ORDER BY mm.pe_ratio ASC
                    LIMIT :lim OFFSET :off
                """)
            elif preset == "deep_value":
                # Deep value: significantly undervalued mid/large caps
                # Very low PE relative to market, decent market cap
                query = text("""
                    SELECT s.ticker, s.company_name, mm.pe_ratio, mm.pb_ratio,
                           mm.dividend_yield, mm.market_cap_cr
                    FROM stocks s
                    JOIN market_metrics mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                      AND mm.pe_ratio BETWEEN 3 AND 15
                      AND mm.pb_ratio BETWEEN 0.3 AND 3
                      AND mm.market_cap_cr > 2000
                    ORDER BY mm.pe_ratio ASC
                    LIMIT :lim OFFSET :off
                """)
            elif preset == "growth_quality":
                # Growth at reasonable price: large caps with growth
                # Higher PE acceptable for quality, massive market cap
                query = text("""
                    SELECT s.ticker, s.company_name, mm.pe_ratio, mm.pb_ratio,
                           mm.dividend_yield, mm.market_cap_cr
                    FROM stocks s
                    JOIN market_metrics mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                      AND mm.pe_ratio BETWEEN 15 AND 45
                      AND mm.market_cap_cr > 20000
                    ORDER BY mm.market_cap_cr DESC
                    LIMIT :lim OFFSET :off
                """)
            else:
                # Custom / default — quality mid+large caps ranked by value
                query = text("""
                    SELECT s.ticker, s.company_name, mm.pe_ratio, mm.pb_ratio,
                           mm.dividend_yield, mm.market_cap_cr
                    FROM stocks s
                    JOIN market_metrics mm ON mm.ticker = s.ticker
                    WHERE s.is_active = true
                      AND mm.pe_ratio BETWEEN 3 AND 50
                      AND mm.market_cap_cr > 2000
                    ORDER BY mm.pe_ratio ASC
                    LIMIT :lim OFFSET :off
                """)

            offset = (page - 1) * page_size
            rows = db.execute(query, {"lim": page_size, "off": offset}).fetchall()

            stocks = []
            for row in rows:
                ticker = row[0]
                pe = row[2] or 0
                pb = row[3] or 0

                # Score: PE component (0-35) + PB component (0-25) + mcap component (0-20) + base 10
                mcap_val = row[5] or 0
                pe_score = max(0, min(35, int((25 - pe) / 25 * 35))) if 0 < pe < 50 else 0
                pb_score = max(0, min(25, int((4 - pb) / 4 * 25))) if 0 < pb < 10 else 0
                mcap_score = 20 if mcap_val > 50000 else 15 if mcap_val > 10000 else 10 if mcap_val > 2000 else 5
                score = pe_score + pb_score + mcap_score + 10

                # MoS capped at +50% to avoid absurd numbers
                mos = round(max(-50, min(50, (20 - pe) / 20 * 30)), 1) if pe > 0 else 0

                stocks.append(ScreenerStock(
                    ticker=f"{ticker}.NS" if "." not in ticker else ticker,
                    score=max(0, min(100, score)),
                    margin_of_safety=mos,
                ))

            return stocks, len(stocks)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Screener preset query failed: {e}")
        return [], 0


@router.get("/run", response_model=ScreenerResponse)
async def run_screener(
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Run custom screener. Available to all users."""
    stocks, total = _query_stocks_from_db(min_score, min_mos, page, page_size)

    # Filter by min_score and min_mos
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks, total=total, page=page, page_size=page_size,
        filter_applied={"min_score": min_score, "min_mos": min_mos},
    )


@router.get("/preset/{preset_name}", response_model=ScreenerResponse)
async def run_preset(
    preset_name: str,
    user: dict = Depends(get_current_user),
):
    """Run a pre-built screener preset. Available to all users."""
    stocks, total = _query_preset_from_db(preset_name)

    return ScreenerResponse(
        results=stocks, total=total, page=1, page_size=25,
        filter_applied={"preset": preset_name},
    )
