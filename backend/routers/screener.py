# backend/routers/screener.py
# Stock screener — queries Aiven pipeline DB for real-time ranked stocks.
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, Query
from backend.models.responses import ScreenerResponse, ScreenerStock
from backend.middleware.auth import get_current_user, require_tier

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

            # PR-SCREENER-DEDUP: market_metrics can have duplicate ticker
            # rows (multi-listing on NSE+BSE, or pipeline write conflicts).
            # The JOIN above multiplies them. Dedupe in Python so the
            # output has exactly one row per ticker (first hit wins —
            # already ordered by pe_ratio so that's the cheapest).
            stocks = []
            seen: set[str] = set()
            for row in rows:
                ticker = row[0]
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
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
    """
    Run preset screener against the in-memory analysis cache.

    Replaces the previous market_metrics DB query (which returned empty
    because that table isn't populated yet). The analysis cache has
    hundreds of stocks with real DCF data — much more useful.
    """
    try:
        from backend.services.cache_service import cache as _c

        # Filter functions per preset
        def _is_buffett(score, mos, moat, pe):
            # Quality + reasonable price + wide moat
            return score >= 60 and mos >= 0 and moat == "Wide"

        def _is_deep_value(score, mos, moat, pe):
            # Big margin of safety + decent quality
            return mos >= 30 and score >= 50

        def _is_growth_quality(score, mos, moat, pe):
            # High score (good fundamentals) + non-negative MoS
            return score >= 75

        def _is_custom(score, mos, moat, pe):
            return score >= 30  # almost everything

        filter_fn = {
            "buffett": _is_buffett,
            "deep_value": _is_deep_value,
            "growth_quality": _is_growth_quality,
            "custom": _is_custom,
        }.get(preset, _is_custom)

        candidates = []
        seen_tickers: set[str] = set()

        # Tier 1 — persistent analysis_cache DB table. This survives
        # Railway redeploys, which wipe the in-memory cache below.
        # Before this was wired, the screener always returned "No stocks
        # match" for a few minutes after every deploy because the
        # in-memory cache hadn't rehydrated yet.
        try:
            from data_pipeline.db import Session as _Session
            from sqlalchemy import text as _sql_text
            _sess = _Session()
            try:
                _rows = _sess.execute(_sql_text(
                    "SELECT ticker, payload FROM analysis_cache "
                    "WHERE computed_at > now() - interval '48 hours'"
                )).fetchall()
            finally:
                _sess.close()
            for _r in _rows:
                _ticker = _r[0]
                _payload = _r[1]
                if _payload is None:
                    continue
                if isinstance(_payload, str):
                    import json as _json
                    try:
                        _payload = _json.loads(_payload)
                    except Exception:
                        continue
                _val = _payload.get("valuation") or {}
                _qual = _payload.get("quality") or {}
                score = _qual.get("yieldiq_score") or 0
                mos = _val.get("margin_of_safety") or 0
                moat = _qual.get("moat") or "None"
                pe = None
                try:
                    eps = _val.get("eps_ttm") or 0
                    cp = _val.get("current_price") or 0
                    if eps > 0 and cp > 0:
                        pe = cp / eps
                except Exception:
                    pass
                full_ticker = _ticker if "." in _ticker else f"{_ticker}.NS"
                if filter_fn(score, mos, moat, pe) and full_ticker not in seen_tickers:
                    candidates.append((full_ticker, score, mos))
                    seen_tickers.add(full_ticker)
        except Exception as _exc:
            logger.info("analysis_cache scan skipped: %s", _exc)

        # Tier 2 — in-memory cache. Catches anything freshly computed
        # on this worker but not yet in the persistent table.
        for key in list(_c._store.keys()):
            if not key.startswith("analysis:") or ".NS" not in key:
                continue
            val = _c.get(key)
            if not val or not hasattr(val, "valuation"):
                continue
            v = val.valuation
            q = val.quality
            score = q.yieldiq_score or 0
            mos = v.margin_of_safety or 0
            moat = q.moat or "None"
            pe = None
            try:
                eps = getattr(v, "eps_ttm", None)
                if eps and eps > 0 and v.current_price > 0:
                    pe = v.current_price / eps
            except Exception:
                pe = None

            if filter_fn(score, mos, moat, pe) and val.ticker not in seen_tickers:
                candidates.append((val.ticker, score, mos))
                seen_tickers.add(val.ticker)

        # Sort by score (descending) then MoS
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # Pagination
        total = len(candidates)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = candidates[start:end]

        stocks = [
            ScreenerStock(
                ticker=ticker,
                score=int(round(score)),
                margin_of_safety=round(mos, 1),
            )
            for ticker, score, mos in page_items
        ]
        return stocks, total
    except Exception as e:
        logger.warning(f"Screener preset query failed: {e}", exc_info=True)
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


@router.get("/export", response_model=ScreenerResponse)
async def export_screener(
    preset: str = Query("custom"),
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    user: dict = Depends(require_tier("starter")),
):
    """Export screener results (up to 500 stocks). Starter+ only."""
    if preset != "custom":
        api_preset = preset.replace("-", "_")
        stocks, total = _query_preset_from_db(api_preset, page=1, page_size=500)
    else:
        stocks, total = _query_stocks_from_db(min_score, min_mos, page=1, page_size=500)

    # Apply filters
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks[:500], total=len(stocks), page=1, page_size=500,
        filter_applied={"preset": preset, "min_score": min_score, "min_mos": min_mos, "export": True},
    )
