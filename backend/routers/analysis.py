# backend/routers/analysis.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from backend.models.responses import AnalysisResponse, ScreenerResponse, ScreenerStock
from backend.services.analysis_service import AnalysisService
from backend.services.cache_service import cache
from backend.middleware.auth import get_current_user, get_current_user_optional, check_analysis_limit
from backend.services.ticker_search import search_tickers
from datetime import date

router = APIRouter(prefix="/api/v1", tags=["analysis"])
service = AnalysisService()


@router.get("/analysis/{ticker}", response_model=AnalysisResponse)
async def get_analysis(
    ticker: str,
    user: dict = Depends(check_analysis_limit),
):
    """
    Full stock analysis with DCF, quality scores, scenarios, and insights.
    Rate limited by tier: Free=5/day, Starter=50/day, Pro=unlimited.
    """
    ticker = ticker.upper().strip()

    # Check cache (15 min TTL)
    _cache_key = f"analysis:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        cached.cached = True
        return cached

    try:
        result = service.get_full_analysis(ticker)
        cache.set(_cache_key, result, ttl=900)
        return result
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"ANALYSIS ERROR:\n{tb}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/analysis/{ticker}/summary")
async def get_ai_summary(ticker: str, user: dict = Depends(get_current_user)):
    """AI plain-English summary for a ticker."""
    ticker = ticker.upper().strip()
    _cache_key = f"analysis:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        analysis = cached
    else:
        analysis = service.get_full_analysis(ticker)

    summary = service.get_ai_summary(ticker, analysis)
    return {"ticker": ticker, "summary": summary}


@router.get("/yieldiq50", response_model=ScreenerResponse)
async def get_yieldiq50(user: dict = Depends(get_current_user)):
    """Top 50 undervalued high-quality stocks. Cached daily."""
    _cache_key = f"yieldiq50:{date.today().isoformat()}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    # Load from screener_results.csv
    try:
        import pandas as pd
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if _path.exists():
            df = pd.read_csv(_path)
            _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)
            _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
            _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)
            _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name")), None)

            if _score_col:
                df = df.nlargest(50, _score_col)

            stocks = []
            for _, row in df.iterrows():
                stocks.append(ScreenerStock(
                    ticker=str(row.get(_ticker_col, "")),
                    company_name=str(row.get(_company_col, "")) if _company_col else "",
                    score=int(row.get(_score_col, 0)) if _score_col else 0,
                    margin_of_safety=float(row.get(_mos_col, 0)) if _mos_col else 0,
                ))

            result = ScreenerResponse(results=stocks, total=len(stocks))
            cache.set(_cache_key, result, ttl=86400)
            return result
    except Exception:
        pass

    return ScreenerResponse()


@router.get("/top-pick")
async def get_top_pick(user: dict = Depends(get_current_user)):
    """Single highest-conviction stock of the day."""
    yiq50 = await get_yieldiq50(user)
    if yiq50.results:
        top = yiq50.results[0]
        return {"ticker": top.ticker, "company_name": top.company_name,
                "score": top.score, "mos": top.margin_of_safety}
    return {"ticker": "RELIANCE.NS", "company_name": "Reliance Industries",
            "score": 70, "mos": 15}


@router.get("/search")
async def search_stocks(
    q: str = "",
    user: dict | None = Depends(get_current_user_optional),
):
    """
    Search Indian stocks by name, ticker, or keyword.
    No auth required — works for everyone.
    Examples: "reliance", "tcs", "hdfc", "airtel", "mankind"
    """
    results = search_tickers(q, limit=8)
    return {"query": q, "results": results}
