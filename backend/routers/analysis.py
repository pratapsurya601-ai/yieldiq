# backend/routers/analysis.py
from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root and dashboard root are on sys.path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
_DASHBOARD_ROOT = str(Path(_PROJECT_ROOT) / "dashboard")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

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


@router.get("/analysis/preview/{ticker}")
async def get_analysis_preview(ticker: str):
    """
    Public preview of stock analysis — no auth required.
    Returns limited data for share links.
    Rate limited to prevent abuse.
    """
    ticker = ticker.upper().strip()

    # Check cache first
    _cache_key = f"preview:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        result = service.get_full_analysis(ticker)
        # Strip sensitive/premium data for public preview
        preview = {
            "ticker": result.ticker,
            "company": result.company,
            "valuation": {
                "fair_value": result.valuation.fair_value,
                "current_price": result.valuation.current_price,
                "margin_of_safety": result.valuation.margin_of_safety,
                "verdict": result.valuation.verdict,
                "wacc": result.valuation.wacc,
                "confidence_score": result.valuation.confidence_score,
            },
            "quality": {
                "yieldiq_score": result.quality.yieldiq_score,
                "grade": result.quality.grade,
                "piotroski_score": result.quality.piotroski_score,
                "moat": result.quality.moat,
            },
            "preview": True,
            "cta": "Sign up free to see full analysis with scenarios, insights, and more",
        }
        cache.set(_cache_key, preview, ttl=3600)  # 1 hour cache
        return preview
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


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


# ── Chart data endpoint ──────────────────────────────────────
_PERIOD_MAP = {"1m": "1mo", "3m": "3mo", "6m": "6mo", "1y": "1y"}


@router.get("/analysis/{ticker}/chart-data")
async def get_chart_data(
    ticker: str,
    period: str = "1m",
    user: dict = Depends(get_current_user),
):
    """Get price history and financial data for charts."""
    ticker = ticker.upper().strip()
    yf_period = _PERIOD_MAP.get(period, "1mo")

    _cache_key = f"chart_data:{ticker}:{period}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    # --- Price history via yfinance ---
    prices: list[dict] = []
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=yf_period)
        if hist is not None and not hist.empty:
            hist = hist.reset_index()
            for _, row in hist.iterrows():
                prices.append({
                    "date": row["Date"].strftime("%Y-%m-%d"),
                    "price": round(float(row["Close"]), 2),
                })
    except Exception:
        pass  # prices stays empty → frontend falls back to mock

    # --- Financial data (revenue + FCF) from collector ---
    financials: dict = {}
    try:
        from data.collector import StockDataCollector

        collector = StockDataCollector(ticker)

        revenue_list: list[dict] = []
        income_df = collector.get_income_history()
        if income_df is not None and not income_df.empty:
            for _, row in income_df.iterrows():
                revenue_list.append({
                    "year": str(row.get("year", "")),
                    "value": round(float(row.get("revenue", 0))),
                })

        fcf_list: list[dict] = []
        cf_df = collector.get_cashflow_history()
        if cf_df is not None and not cf_df.empty:
            for _, row in cf_df.iterrows():
                fcf_list.append({
                    "year": str(row.get("year", "")),
                    "value": round(float(row.get("fcf", 0))),
                })

        if revenue_list or fcf_list:
            financials = {"revenue": revenue_list, "fcf": fcf_list}
    except Exception:
        pass  # financials stays empty

    result = {"prices": prices, "period": period, "financials": financials}
    cache.set(_cache_key, result, ttl=900)  # 15 min cache
    return result


@router.get("/analysis/{ticker}/report")
async def get_report(ticker: str, user: dict = Depends(get_current_user)):
    """Generate downloadable DCF report as text."""
    ticker = ticker.upper().strip()
    try:
        analysis = service.get_full_analysis(ticker)
        v = analysis.valuation
        q = analysis.quality
        s = analysis.scenarios

        lines = [
            "",
            "\u250c" + "\u2500" * 70 + "\u2510",
            "\u2502" + " Y I E L D I Q".center(70) + "\u2502",
            "\u2502" + " Quantitative Valuation Report".center(70) + "\u2502",
            "\u2502" + "".center(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + f"  Company: {analysis.company.company_name}".ljust(70) + "\u2502",
            "\u2502" + f"  Ticker:  {analysis.ticker}".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  VALUATION".ljust(70) + "\u2502",
            "\u2502" + f"  Fair Value:        \u20b9{v.fair_value:>12,.2f}".ljust(70) + "\u2502",
            "\u2502" + f"  Current Price:     \u20b9{v.current_price:>12,.2f}".ljust(70) + "\u2502",
            "\u2502" + f"  Margin of Safety:  {v.margin_of_safety:>+12.1f}%".ljust(70) + "\u2502",
            "\u2502" + f"  Verdict:           {v.verdict:>12s}".ljust(70) + "\u2502",
            "\u2502" + f"  WACC:              {v.wacc:>12.1f}%".ljust(70) + "\u2502",
            "\u2502" + f"  Confidence:        {v.confidence_score:>12d}/100".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  QUALITY".ljust(70) + "\u2502",
            "\u2502" + f"  YieldIQ Score:     {q.yieldiq_score:>12d}/100".ljust(70) + "\u2502",
            "\u2502" + f"  Piotroski:         {q.piotroski_score:>12d}/9".ljust(70) + "\u2502",
            "\u2502" + f"  Moat:              {q.moat:>12s}".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  SCENARIOS".ljust(70) + "\u2502",
            "\u2502" + f"  Bear Case:         \u20b9{s.bear.iv:>12,.2f}  (MoS {s.bear.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u2502" + f"  Base Case:         \u20b9{s.base.iv:>12,.2f}  (MoS {s.base.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u2502" + f"  Bull Case:         \u20b9{s.bull.iv:>12,.2f}  (MoS {s.bull.mos_pct:+.1f}%)".ljust(70) + "\u2502",
            "\u251c" + "\u2500" * 70 + "\u2524",
            "\u2502" + "  DISCLAIMER".ljust(70) + "\u2502",
            "\u2502" + "  Model output only. Not investment advice.".ljust(70) + "\u2502",
            "\u2502" + "  YieldIQ is not registered with SEBI.".ljust(70) + "\u2502",
            "\u2514" + "\u2500" * 70 + "\u2518",
            "",
            "  Generated by YieldIQ | yieldiq.in",
            "",
        ]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content="\n".join(lines),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=YieldIQ_{ticker}.txt"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
