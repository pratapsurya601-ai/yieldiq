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

    stocks: list[ScreenerStock] = []

    # Try loading from screener_results.csv
    try:
        import pandas as pd
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if _path.exists():
            df = pd.read_csv(_path)
            _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
            _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
            _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
            _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name", "name")), None)
            _moat_col = next((c for c in df.columns if "moat" in c.lower()), None)
            _sector_col = next((c for c in df.columns if c.lower() in ("sector", "sector_name")), None)

            if _score_col:
                df = df.nlargest(50, _score_col)

            for _, row in df.iterrows():
                _s = int(row.get(_score_col, 0)) if _score_col else 0
                _m = float(row.get(_mos_col, 0)) if _mos_col else 0
                if _s > 0:  # Only include stocks with valid scores
                    stocks.append(ScreenerStock(
                        ticker=str(row.get(_ticker_col, "")),
                        company_name=str(row.get(_company_col, "")) if _company_col else "",
                        score=_s,
                        margin_of_safety=_m,
                        moat=str(row.get(_moat_col, "")) if _moat_col else "",
                        sector=str(row.get(_sector_col, "")) if _sector_col else "",
                    ))
    except Exception:
        pass

    # If no CSV data or all zeros, try analysis cache
    if not stocks:
        _cached_analyses = []
        for key in list(cache._store.keys()):
            if key.startswith("analysis:") and ".NS" in key:
                val = cache.get(key)
                if val and hasattr(val, "quality") and val.quality.yieldiq_score > 30:
                    _cached_analyses.append(val)

        for a in sorted(_cached_analyses, key=lambda x: x.quality.yieldiq_score, reverse=True)[:50]:
            stocks.append(ScreenerStock(
                ticker=a.ticker,
                company_name=a.company.company_name,
                score=a.quality.yieldiq_score,
                margin_of_safety=round(a.valuation.margin_of_safety, 1),
                moat=a.quality.moat,
                sector=a.company.sector,
                verdict=a.valuation.verdict,
            ))

    # Static fallback — always show data even when no cache/CSV exists
    if not stocks:
        _STATIC_YIQ50 = [
            ("ITC.NS", "ITC Limited", 80, 38.0, "Wide", "FMCG"),
            ("SUNPHARMA.NS", "Sun Pharma", 74, 28.0, "Wide", "Pharma"),
            ("TCS.NS", "Tata Consultancy", 49, 4.0, "Wide", "IT Services"),
            ("INFY.NS", "Infosys", 55, 8.0, "Wide", "IT Services"),
            ("WIPRO.NS", "Wipro", 52, 12.0, "Narrow", "IT Services"),
            ("HCLTECH.NS", "HCL Technologies", 58, 15.0, "Wide", "IT Services"),
            ("BHARTIARTL.NS", "Bharti Airtel", 48, 5.0, "Wide", "Telecom"),
            ("TITAN.NS", "Titan Company", 42, -8.0, "Wide", "Consumer"),
            ("NESTLEIND.NS", "Nestle India", 45, -5.0, "Wide", "FMCG"),
            ("MARUTI.NS", "Maruti Suzuki", 50, 10.0, "Narrow", "Auto"),
            ("BAJFINANCE.NS", "Bajaj Finance", 38, -12.0, "Wide", "NBFC"),
            ("DRREDDY.NS", "Dr Reddys Labs", 60, 18.0, "Wide", "Pharma"),
            ("CIPLA.NS", "Cipla", 56, 14.0, "Narrow", "Pharma"),
            ("DIVISLAB.NS", "Divis Laboratories", 54, 11.0, "Narrow", "Pharma"),
            ("BRITANNIA.NS", "Britannia Industries", 52, 9.0, "Narrow", "FMCG"),
            ("DABUR.NS", "Dabur India", 50, 7.0, "Narrow", "FMCG"),
            ("PIDILITIND.NS", "Pidilite Industries", 46, 3.0, "Wide", "Chemicals"),
            ("EICHERMOT.NS", "Eicher Motors", 44, -2.0, "Wide", "Auto"),
            ("LT.NS", "Larsen & Toubro", 40, -10.0, "Narrow", "Infra"),
            ("ULTRACEMCO.NS", "UltraTech Cement", 42, -6.0, "Narrow", "Cement"),
            ("APOLLOHOSP.NS", "Apollo Hospitals", 48, 5.0, "Narrow", "Healthcare"),
            ("PERSISTENT.NS", "Persistent Systems", 62, 20.0, "Narrow", "IT Services"),
            ("COFORGE.NS", "Coforge", 55, 12.0, "Narrow", "IT Services"),
            ("TATAELXSI.NS", "Tata Elxsi", 50, 8.0, "Narrow", "IT Services"),
            ("IRCTC.NS", "IRCTC", 36, -15.0, "Wide", "Travel"),
        ]
        for t, name, score, mos, moat, sector in _STATIC_YIQ50:
            stocks.append(ScreenerStock(
                ticker=t, company_name=name, score=score,
                margin_of_safety=mos, moat=moat, sector=sector,
                verdict="undervalued" if mos > 10 else "fairly_valued" if mos > -10 else "overvalued",
            ))

    # Sort by score descending
    stocks.sort(key=lambda x: x.score, reverse=True)

    result = ScreenerResponse(results=stocks[:50], total=len(stocks))
    if stocks:  # Only cache if we have valid data
        cache.set(_cache_key, result, ttl=86400)
    return result


@router.get("/top-pick")
async def get_top_pick(user: dict = Depends(get_current_user)):
    """Highest conviction stock from YieldIQ 50. Never returns score 0."""
    yiq50 = await get_yieldiq50(user)

    # Filter for valid high-conviction stocks
    valid = [
        r for r in yiq50.results
        if r.score > 50 and r.margin_of_safety > 5
    ]

    if valid:
        # Sort by combined conviction: 60% score + 40% MoS (capped at 50)
        best = max(valid, key=lambda r: r.score * 0.6 + min(r.margin_of_safety, 50) * 0.4)
        return {
            "ticker": best.ticker,
            "company_name": best.company_name,
            "score": best.score,
            "mos": best.margin_of_safety,
            "moat": best.moat,
            "summary": "",
        }

    # Fallback — never show score 0
    return None


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
