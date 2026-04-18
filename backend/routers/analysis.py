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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from backend.models.responses import AnalysisResponse, ScreenerResponse, ScreenerStock
from backend.services.analysis_service import AnalysisService, TickerNotFoundError
from backend.services.cache_service import cache
from backend.services import analysis_cache_service
from backend.middleware.auth import get_current_user, get_current_user_optional, check_analysis_limit
from backend.services.ticker_search import search_tickers
from datetime import date

router = APIRouter(prefix="/api/v1", tags=["analysis"])
service = AnalysisService()

# ── Ticker renames ────────────────────────────────────────────
# Map retired symbols → canonical symbol. Requests hit the new
# ticker silently; frontend detects the mismatch between the URL
# ticker and response.ticker to show a rename banner.
TICKER_ALIASES: dict[str, str] = {
    # Renames / rebrands
    "ZOMATO.NS":       "ETERNAL.NS",    # Zomato → Eternal Ltd (Nov 2024 rebrand)
    "ZOMATO":          "ETERNAL.NS",
    # Demerger successors (redirect to primary business post-split)
    "TATAMOTORS.NS":   "TMPV.NS",       # Tata Motors → TMPV (passenger vehicles, post-demerger)
    "TATAMOTORS":      "TMPV.NS",
    # Common short/wrong forms → canonical NSE symbol
    "KPIT.NS":         "KPITTECH.NS",   # KPIT → KPITTECH
    "KPIT":            "KPITTECH.NS",
    "BERGERPAINTS.NS": "BERGEPAINT.NS", # typo in our universe list
    "BERGERPAINTS":    "BERGEPAINT.NS",
    "DALMIA.NS":       "DALBHARAT.NS",  # Dalmia Bharat
    "DALMIA":          "DALBHARAT.NS",
    "DOMINOS.NS":      "JUBLFOOD.NS",   # Domino's franchisee = Jubilant FoodWorks
    "DOMINOS":         "JUBLFOOD.NS",
    "BLUESTAR.NS":     "BLUESTARCO.NS", # Blue Star Ltd (NSE canonical)
    "BLUESTAR":        "BLUESTARCO.NS",
}

# ── Known-broken upstream tickers ─────────────────────────────
# When yfinance can't fetch a genuinely-listed stock (data-provider
# gap rather than delisted ticker), surface a specific note instead
# of the generic "check the symbol" message.
KNOWN_BROKEN_TICKERS: dict[str, str] = {
    # TATAMOTORS is now handled via TICKER_ALIASES → TMPV.NS (post-demerger)
}


@router.get("/analysis/{ticker}", response_model=AnalysisResponse)
async def get_analysis(
    ticker: str,
    response: Response,
    include_summary: bool = Query(
        True,
        description=(
            "If false, skip AI summary generation so the response returns "
            "instantly. Callers should then hit "
            "GET /api/v1/analysis/{ticker}/summary separately. Default is "
            "true for backward compatibility."
        ),
    ),
    user: dict = Depends(check_analysis_limit),
):
    """
    Full stock analysis with DCF, quality scores, scenarios, and insights.
    Rate limited by tier: Free=5/day, Starter=50/day, Pro=unlimited.

    Cache tiers (in order): in-memory cache_service -> analysis_cache
    (Postgres) -> compute. The persistent tier survives worker restarts
    and is shared across Railway workers; it is invalidated implicitly
    whenever CACHE_VERSION is bumped.

    Frontend contract (2026-04): the AI summary (Gemini/Groq) can add
    5-15s on a cold request. Callers rendering the summary asynchronously
    should pass ``?include_summary=false`` and hit
    ``/analysis/{ticker}/summary`` separately. When ``include_summary``
    is false, the ``ai_summary`` field in the returned payload is always
    ``None``. Default stays ``true`` so pre-existing callers keep the
    synchronous behaviour they had before this split.
    """
    import time as _time
    original_ticker = ticker.upper().strip()
    # Route renamed symbols to their canonical equivalent. Response
    # will carry the canonical ticker — frontend compares URL param
    # to response.ticker to show a "renamed to …" banner.
    ticker = TICKER_ALIASES.get(original_ticker, original_ticker)

    # Tier 1: in-memory cache (fastest, per-process, 24h TTL).
    _cache_key = f"analysis:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        cached.cached = True
        response.headers["X-Cache"] = "HIT-MEM"
        if not include_summary:
            # Caller asked to defer summary generation — strip it from the
            # cached payload so the client always gets a consistent contract.
            # The cached object is shared; mutate a shallow copy rather than
            # the original or subsequent ?include_summary=true reads would
            # see null too.
            try:
                cached = cached.model_copy(update={"ai_summary": None})
            except Exception:
                cached.ai_summary = None
        return cached

    # Tier 2: persistent DB cache (shared across workers, survives restart).
    # Never raises — failures degrade to compute.
    try:
        _db_cached = analysis_cache_service.get_cached(ticker)
    except Exception:
        _db_cached = None
    if _db_cached:
        try:
            # Schema-tolerant rehydrate. When we add fields to
            # QualityOutput/ValuationOutput without bumping CACHE_VERSION
            # (e.g. today's ROCE, Debt/EBITDA, Interest Coverage,
            # Promoter % additions), old cached payloads lack those
            # keys. model_validate fills Optional/defaulted fields
            # cleanly; strict __init__ on Pydantic v2 raises on unknown
            # extras, so we also strip any keys the current model
            # doesn't know about.
            _cls_fields = set(AnalysisResponse.model_fields.keys())
            _clean = {k: v for k, v in _db_cached.items() if k in _cls_fields}
            _obj = AnalysisResponse.model_validate(_clean)
            _obj.cached = True
            # Populate tier-1 so subsequent hits on this worker skip the DB.
            cache.set(_cache_key, _obj, ttl=86400)
            response.headers["X-Cache"] = "HIT-DB"
            if not include_summary:
                try:
                    _obj = _obj.model_copy(update={"ai_summary": None})
                except Exception:
                    _obj.ai_summary = None
            return _obj
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analysis_cache: failed to rehydrate payload for %s (%s: %s) — recomputing + invalidating",
                ticker, type(_exc).__name__, _exc,
            )
            # Invalidate the bad row so we don't keep retrying to rehydrate
            # it on every request (each retry costs a DB round-trip).
            try:
                analysis_cache_service.invalidate(ticker)
            except Exception:
                pass
            # fall through to compute

    _compute_start = _time.monotonic()
    try:
        result = service.get_full_analysis(ticker)

        # ── Output sanity gate ──────────────────────────────────
        # Two-layer defense:
        #   1. validate_analysis() — bounds + cross-field (WACC, MoS, FV/CMP,
        #      piotroski, moat-ROE consistency, DCF trace). Fires on any
        #      critical-severity failure anywhere in the response.
        #   2. FV/MoS ratio gate — defensive second layer tuned for the
        #      specific 'fair value is absurd' class of bug.
        # Either triggering flips verdict to 'data_limited' and zeroes the
        # numbers, keeping quality/moat/piotroski intact since those are
        # computed independently.
        _suspicious = False
        try:
            from backend.services.validators import validate_analysis, log_validation
            _vr = validate_analysis(result)
            if not _vr.ok and _vr.severity == "critical":
                _suspicious = True
                log_validation(ticker, _vr)
        except Exception:
            pass
        try:
            _fv = float(result.valuation.fair_value or 0)
            _px = float(result.valuation.current_price or 0)
            _mos = float(result.valuation.margin_of_safety or 0)
            # Zero fair value with positive price → validator fires
            # mos=-100% on these (e.g. PFC.NS, other NBFCs where
            # FCF-based DCF doesn't work). Caught by Sentry 18-Apr.
            if _px > 0 and _fv <= 0:
                _suspicious = True
            if _px > 0 and _fv > 0:
                _r = _fv / _px
                if _r > 3.0 or _r < 0.1:
                    _suspicious = True
            # Tightened from |mos|>200 to catch PFC-style -100%
            # (previously slipped through since 100 < 200). Any mos
            # that rounds to ±95+ is beyond what the validator allows
            # and almost always indicates bad inputs rather than a
            # genuinely 95%-undervalued stock.
            if abs(_mos) >= 95:
                _suspicious = True
            if _suspicious:
                result.valuation.verdict = "data_limited"
                result.valuation.fair_value = 0.0
                result.valuation.margin_of_safety = 0.0
                result.valuation.margin_of_safety_display = 0.0
                result.valuation.mos_is_extreme = False
                result.valuation.mos_extreme_note = None
                _issues = list(getattr(result, "data_issues", []) or [])
                _issues.append(
                    "[critical] Fair value computation produced an "
                    "unrealistic result — under review."
                )
                result.data_issues = _issues
        except Exception:
            pass

        # Cache for 24h — analysis data doesn't change fast, and cold-recomputes
        # hit yfinance which is the slowest link.
        cache.set(_cache_key, result, ttl=86400)

        # Tier-2 write-back: persist so other workers / post-restart
        # requests skip compute. Best-effort; failures are logged and
        # swallowed inside the service (must never fail the response).
        try:
            _compute_ms = int((_time.monotonic() - _compute_start) * 1000)
            _payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.dict()
            analysis_cache_service.save_cached(ticker, _payload, _compute_ms)
        except Exception as _write_exc:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analysis_cache: write-back failed for %s: %s", ticker, _write_exc
            )

        response.headers["X-Cache"] = "MISS"
        if not include_summary:
            # Cache retains the full object (including any ai_summary the
            # service populated); only the response to this caller is trimmed.
            try:
                result = result.model_copy(update={"ai_summary": None})
            except Exception:
                result.ai_summary = None
        return result
    except TickerNotFoundError:
        # Data provider returned nothing for this symbol. 404 lets the
        # frontend distinguish "bad ticker" from "our service broke".
        _detail: dict = {"error": "Ticker not found", "ticker": original_ticker}
        _note = KNOWN_BROKEN_TICKERS.get(original_ticker)
        if _note:
            _detail["note"] = _note
        raise HTTPException(status_code=404, detail=_detail)
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.analysis").error(f"Analysis failed for {ticker}: {e}", exc_info=True)
        # str(e) can include env-var values (e.g. DATABASE_URL with password,
        # JWT_SECRET) when they get concatenated into upstream error messages.
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}")


@router.get("/analysis/{ticker}/og-data")
async def get_og_data(ticker: str):
    """Return Open Graph data for social sharing. No auth required."""
    ticker = ticker.upper().strip()
    _cache_key = f"og:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        result = service.get_full_analysis(ticker)
        display_ticker = ticker.replace(".NS", "").replace(".BO", "")

        # ── Output sanity gate (router-level defense in depth) ──
        # If FV/price ratio > 3x or |MoS| > 200%, suppress the numbers
        # here at the edge so users never see them even if some upstream
        # path forgot to gate. Defensive — the analysis_service also
        # has this check, but duplicating at the router is cheap.
        _fv = float(result.valuation.fair_value or 0)
        _px = float(result.valuation.current_price or 0)
        _mos = float(result.valuation.margin_of_safety or 0)
        _verdict = result.valuation.verdict
        _suspicious = False
        try:
            # Positive price with zero/negative FV → NBFC-style DCF
            # failure (e.g. PFC.NS). The validator was firing
            # mos=-100% on these; gate it here too.
            if _px > 0 and _fv <= 0:
                _suspicious = True
            if _px > 0 and _fv > 0:
                _r = _fv / _px
                if _r > 3.0 or _r < 0.1:
                    _suspicious = True
            # Tightened from |mos|>200 → ≥95 to catch the -100% case.
            if abs(_mos) >= 95:
                _suspicious = True
        except Exception:
            pass
        if _suspicious:
            _verdict = "data_limited"
            _fv = 0.0
            _mos = 0.0

        verdict_text = _verdict.replace("_", " ").title()
        if _suspicious:
            desc = (
                f"{result.company.company_name} — valuation under review. "
                f"Current price ₹{_px:,.0f}. Fair value temporarily unavailable."
            )
        else:
            desc = (
                f"{result.company.company_name} fair value ₹{_fv:,.0f} "
                f"vs price ₹{_px:,.0f}. "
                f"Score: {result.quality.yieldiq_score}/100. "
                f"Moat: {result.quality.moat}."
            )

        og = {
            "title": f"{display_ticker} — {verdict_text} | YieldIQ",
            "description": desc,
            "ticker": ticker,
            "score": result.quality.yieldiq_score,
            "verdict": _verdict,
            "fair_value": _fv,
            "price": _px,
            "mos": _mos,
        }
        cache.set(_cache_key, og, ttl=3600)
        return og
    except Exception:
        return {
            "title": f"{ticker} Stock Analysis | YieldIQ",
            "description": "Free DCF valuation for Indian stocks. Know if a stock is undervalued.",
        }


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

        # Output sanity gate — same as og-data and main /analysis
        _fv = float(result.valuation.fair_value or 0)
        _px = float(result.valuation.current_price or 0)
        _mos = float(result.valuation.margin_of_safety or 0)
        _verdict = result.valuation.verdict
        try:
            _suspicious = False
            if _px > 0 and _fv > 0:
                _r = _fv / _px
                if _r > 3.0 or _r < 0.1:
                    _suspicious = True
            if abs(_mos) > 200:
                _suspicious = True
            if _suspicious:
                _verdict = "data_limited"
                _fv = 0.0
                _mos = 0.0
        except Exception:
            pass

        # Strip sensitive/premium data for public preview
        preview = {
            "ticker": result.ticker,
            "company": result.company,
            "valuation": {
                "fair_value": _fv,
                "current_price": _px,
                "margin_of_safety": _mos,
                "verdict": _verdict,
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
        import logging
        logging.getLogger("yieldiq.analysis").error(
            f"og-data failed for {ticker}: {type(e).__name__}", exc_info=True
        )
        # Never return raw str(e) — can leak env-var values (DATABASE_URL,
        # JWT_SECRET, etc.) embedded in upstream exception messages.
        return {"error": f"{type(e).__name__} (details suppressed)", "ticker": ticker}


# Timeout for the underlying LLM call (Gemini → Groq fallback). If the
# provider hangs beyond this, we return 503 rather than let the HTTP
# request block indefinitely. 10s matches what the frontend is willing
# to wait before showing a retry affordance.
_AI_SUMMARY_TIMEOUT_S = 10.0

# 24h TTL for the summary cache. Summary is derived from analysis which
# itself caches 24h, so there's no point re-asking the LLM more often.
_AI_SUMMARY_CACHE_TTL_S = 86400


@router.get("/analysis/{ticker}/summary")
async def get_ai_summary(ticker: str, user: dict = Depends(get_current_user)):
    """AI plain-English summary for a ticker.

    Returns ``{ticker, summary, model, generated_at, cached}``.

    Separate endpoint so the main ``/analysis/{ticker}`` payload can
    return instantly without waiting 5-15s for Gemini/Groq. Cache is
    the in-memory ``cache_service`` keyed by ``ai_summary:{ticker}`` for
    24h. On upstream LLM timeout or failure, returns 503 with
    ``{error: "summary_unavailable", retry_after: 30}`` so the frontend
    can degrade gracefully rather than render a fake summary.
    """
    import asyncio
    import logging
    from datetime import datetime, timezone

    ticker = ticker.upper().strip()
    _log = logging.getLogger("yieldiq.ai_summary")

    # ── Tier 1: in-memory cache ─────────────────────────────────
    _summary_cache_key = f"ai_summary:{ticker}"
    cached_summary = cache.get(_summary_cache_key)
    if cached_summary:
        return {**cached_summary, "cached": True}

    # ── Need the underlying analysis to build the summary prompt ─
    _analysis_cache_key = f"analysis:{ticker}"
    analysis = cache.get(_analysis_cache_key)
    if analysis is None:
        try:
            analysis = service.get_full_analysis(ticker)
        except TickerNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={"error": "Ticker not found", "ticker": ticker},
            )

    # ── Call the LLM with a hard timeout ────────────────────────
    # generate_ai_summary is sync (HTTP-bound), so offload to a thread
    # and wrap with asyncio.wait_for for a clean cancellation boundary.
    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(service.get_ai_summary, ticker, analysis),
            timeout=_AI_SUMMARY_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        _log.warning(f"[{ticker}] AI summary timed out after {_AI_SUMMARY_TIMEOUT_S}s")
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )
    except Exception as exc:  # noqa: BLE001 — surface any LLM failure as 503
        _log.error(f"[{ticker}] AI summary failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )

    # service.get_ai_summary swallows LLM errors and returns "" — treat
    # that as an upstream failure for this endpoint (the contract says
    # no fake/empty summaries). The main /analysis endpoint keeps the
    # swallow-and-return-empty behaviour separately so legacy callers
    # that embed summary inline don't regress.
    if not summary:
        raise HTTPException(
            status_code=503,
            detail={"error": "summary_unavailable", "retry_after": 30},
        )

    payload = {
        "ticker": ticker,
        "summary": summary,
        # Model identity isn't plumbed back from data_helpers.generate_ai_summary
        # today (it tries Gemini first, then Groq). Report the family name so
        # the frontend can display something useful without us lying about it.
        "model": "gemini-2.0-flash|groq-llama-3.3-70b",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    cache.set(_summary_cache_key, payload, ttl=_AI_SUMMARY_CACHE_TTL_S)
    return payload


_STATIC_YIQ50: list[tuple] = [
    ("ITC.NS",          "ITC Limited",              80,  38.0, "Wide",   "FMCG"),
    ("SUNPHARMA.NS",    "Sun Pharma",               74,  28.0, "Wide",   "Pharma"),
    ("PERSISTENT.NS",   "Persistent Systems",       62,  20.0, "Narrow", "IT Services"),
    ("DRREDDY.NS",      "Dr Reddys Labs",           60,  18.0, "Wide",   "Pharma"),
    ("HCLTECH.NS",      "HCL Technologies",         58,  15.0, "Wide",   "IT Services"),
    ("CIPLA.NS",        "Cipla",                    56,  14.0, "Narrow", "Pharma"),
    ("INFY.NS",         "Infosys",                  55,   8.0, "Wide",   "IT Services"),
    ("COFORGE.NS",      "Coforge",                  55,  12.0, "Narrow", "IT Services"),
    ("DIVISLAB.NS",     "Divis Laboratories",       54,  11.0, "Narrow", "Pharma"),
    ("WIPRO.NS",        "Wipro",                    52,  12.0, "Narrow", "IT Services"),
    ("BRITANNIA.NS",    "Britannia Industries",     52,   9.0, "Narrow", "FMCG"),
    ("TATAELXSI.NS",    "Tata Elxsi",               50,   8.0, "Narrow", "IT Services"),
    ("MARUTI.NS",       "Maruti Suzuki",            50,  10.0, "Narrow", "Auto"),
    ("DABUR.NS",        "Dabur India",              50,   7.0, "Narrow", "FMCG"),
    ("TCS.NS",          "Tata Consultancy",         49,   4.0, "Wide",   "IT Services"),
    ("BHARTIARTL.NS",   "Bharti Airtel",            48,   5.0, "Wide",   "Telecom"),
    ("APOLLOHOSP.NS",   "Apollo Hospitals",         48,   5.0, "Narrow", "Healthcare"),
    ("PIDILITIND.NS",   "Pidilite Industries",      46,   3.0, "Wide",   "Chemicals"),
    ("NESTLEIND.NS",    "Nestle India",             45,  -5.0, "Wide",   "FMCG"),
    ("EICHERMOT.NS",    "Eicher Motors",            44,  -2.0, "Wide",   "Auto"),
    ("ULTRACEMCO.NS",   "UltraTech Cement",         42,  -6.0, "Narrow", "Cement"),
    ("TITAN.NS",        "Titan Company",            42,  -8.0, "Wide",   "Consumer"),
    ("LT.NS",           "Larsen & Toubro",          40, -10.0, "Narrow", "Infra"),
    ("BAJFINANCE.NS",   "Bajaj Finance",            38, -12.0, "Wide",   "NBFC"),
    ("IRCTC.NS",        "IRCTC",                    36, -15.0, "Wide",   "Travel"),
    # Additional 25 entries to ensure static fallback can fill 50 rows.
    ("HINDUNILVR.NS",   "Hindustan Unilever",       60,  12.0, "Wide",   "FMCG"),
    ("HDFCBANK.NS",     "HDFC Bank",                58,   6.0, "Wide",   "Banking"),
    ("ICICIBANK.NS",    "ICICI Bank",               57,   8.0, "Wide",   "Banking"),
    ("KOTAKBANK.NS",    "Kotak Mahindra Bank",      54,   3.0, "Wide",   "Banking"),
    ("AXISBANK.NS",     "Axis Bank",                52,   4.0, "Narrow", "Banking"),
    ("SBIN.NS",         "State Bank of India",      50,   7.0, "Narrow", "Banking"),
    ("INDUSINDBK.NS",   "IndusInd Bank",            45,  -4.0, "Narrow", "Banking"),
    ("BAJAJFINSV.NS",   "Bajaj Finserv",            48,  -6.0, "Wide",   "NBFC"),
    ("CHOLAFIN.NS",     "Cholamandalam Finance",    52,   3.0, "Narrow", "NBFC"),
    ("MUTHOOTFIN.NS",   "Muthoot Finance",          54,   9.0, "Narrow", "NBFC"),
    ("RELIANCE.NS",     "Reliance Industries",      56,   5.0, "Wide",   "Oil & Gas"),
    ("ONGC.NS",         "ONGC",                     42,  -8.0, "Narrow", "Oil & Gas"),
    ("TATAMOTORS.NS",   "Tata Motors",              44,  -5.0, "Narrow", "Auto"),
    ("MOTHERSON.NS",    "Samvardhana Motherson",    46,   2.0, "Narrow", "Auto"),
    ("BOSCHLTD.NS",     "Bosch",                    50,   4.0, "Wide",   "Auto"),
    ("JSWSTEEL.NS",     "JSW Steel",                41,  -9.0, "Narrow", "Metals"),
    ("TATASTEEL.NS",    "Tata Steel",               39, -11.0, "Narrow", "Metals"),
    ("HINDALCO.NS",     "Hindalco",                 43,  -4.0, "Narrow", "Metals"),
    ("AMBUJACEM.NS",    "Ambuja Cements",           46,   1.0, "Narrow", "Cement"),
    ("ACC.NS",          "ACC",                      44,  -3.0, "Narrow", "Cement"),
    ("SIEMENS.NS",      "Siemens",                  49,  -2.0, "Wide",   "Capital Goods"),
    ("ABB.NS",          "ABB India",                48,  -1.0, "Wide",   "Capital Goods"),
    ("BEL.NS",          "Bharat Electronics",       55,   7.0, "Wide",   "Defence"),
    ("DMART.NS",        "Avenue Supermarts",        52,   6.0, "Wide",   "Retail"),
    ("TRENT.NS",        "Trent",                    56,  10.0, "Narrow", "Retail"),
]


def _load_screener_csv() -> list[ScreenerStock]:
    """Read screener_results.csv if available. Returns [] on any error."""
    try:
        import pandas as pd
        from pathlib import Path
        _path = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
        if not _path.exists():
            return []
        df = pd.read_csv(_path)
        _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
        _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
        _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
        _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name", "name")), None)
        _moat_col = next((c for c in df.columns if "moat" in c.lower()), None)
        _sector_col = next((c for c in df.columns if c.lower() in ("sector", "sector_name")), None)
        if _score_col:
            df = df.nlargest(50, _score_col)
        out: list[ScreenerStock] = []
        for _, row in df.iterrows():
            _s = int(row.get(_score_col, 0)) if _score_col else 0
            _m = float(row.get(_mos_col, 0)) if _mos_col else 0.0
            if _s > 0:
                out.append(ScreenerStock(
                    ticker=str(row.get(_ticker_col, "")),
                    company_name=str(row.get(_company_col, "")) if _company_col else "",
                    score=_s,
                    margin_of_safety=_m,
                    moat=str(row.get(_moat_col, "")) if _moat_col else "",
                    sector=str(row.get(_sector_col, "")) if _sector_col else "",
                ))
        return out
    except Exception:
        return []


def _load_cached_analyses() -> list[ScreenerStock]:
    """Read warm AnalysisResponse entries from the in-process cache."""
    out: list[ScreenerStock] = []
    try:
        for key in list(cache._store.keys()):
            if key.startswith("analysis:") and ".NS" in key:
                val = cache.get(key)
                if val and hasattr(val, "quality") and val.quality.yieldiq_score > 30:
                    out.append(ScreenerStock(
                        ticker=val.ticker,
                        company_name=val.company.company_name,
                        score=val.quality.yieldiq_score,
                        margin_of_safety=round(val.valuation.margin_of_safety, 1),
                        moat=val.quality.moat,
                        sector=val.company.sector,
                        verdict=val.valuation.verdict,
                    ))
    except Exception:
        pass
    return out


@router.get("/yieldiq50", response_model=ScreenerResponse)
async def get_yieldiq50(user: dict = Depends(get_current_user)):
    """Top 50 undervalued high-quality stocks. Cached daily.

    Sources are merged (not exclusive) and deduped by ticker so the
    response reliably fills 50 rows:
      1. Real screener CSV output (highest priority — real scores)
      2. Warm AnalysisResponse cache (real scores from recent runs)
      3. Static fallback (50 Nifty-100 tickers with placeholder scores)
    """
    _cache_key = f"yieldiq50:{date.today().isoformat()}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    by_ticker: dict[str, ScreenerStock] = {}
    # Merge in priority order; first-seen wins per ticker.
    for source in (_load_screener_csv(), _load_cached_analyses()):
        for s in source:
            if s.ticker and s.ticker not in by_ticker:
                by_ticker[s.ticker] = s

    # Pad from static only if we still have < 50 real entries.
    if len(by_ticker) < 50:
        for t, name, score, mos, moat, sector in _STATIC_YIQ50:
            if t in by_ticker:
                continue
            by_ticker[t] = ScreenerStock(
                ticker=t, company_name=name, score=score,
                margin_of_safety=mos, moat=moat, sector=sector,
                verdict="undervalued" if mos > 10 else "fairly_valued" if mos > -10 else "overvalued",
            )
            if len(by_ticker) >= 50:
                break

    stocks = sorted(by_ticker.values(), key=lambda x: x.score, reverse=True)[:50]
    result = ScreenerResponse(results=stocks, total=len(stocks))
    if stocks:
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


# Debug endpoints — keep for now, remove before public launch
@router.get("/debug/parquet-status")
async def debug_parquet_status():
    """Diagnostic: check if Parquet files exist on this Railway instance."""
    import os
    from pathlib import Path

    # Check db_integration's PARQUET_DIR
    try:
        from data_pipeline.nse_prices.db_integration import PARQUET_DIR, _parquet_path
        pdir = str(PARQUET_DIR)
        exists = PARQUET_DIR.exists()
        files = sorted([f.name for f in PARQUET_DIR.glob("*.parquet")]) if exists else []
        hal_path = _parquet_path("HAL.NS")
    except Exception as exc:
        return {"error": f"import failed: {exc}"}

    # Check DB connectivity
    db_status = "unknown"
    try:
        from backend.services.analysis_service import _get_pipeline_session, _db_dead_until
        import time
        if time.time() < _db_dead_until:
            db_status = f"COOLDOWN (expires in {int(_db_dead_until - time.time())}s)"
        else:
            sess = _get_pipeline_session()
            db_status = "CONNECTED" if sess else "None (no DATABASE_URL)"
            if sess:
                try:
                    sess.close()
                except Exception:
                    pass
    except Exception as exc:
        db_status = f"error: {exc}"

    # Check local assembler
    local_status = "unknown"
    try:
        from backend.services.local_data_service import assemble_local
        local_status = "importable"
    except Exception as exc:
        local_status = f"import failed: {exc}"

    return {
        "parquet_dir": pdir,
        "parquet_dir_exists": exists,
        "file_count": len(files),
        "sample_files": files[:5],
        "hal_exists": hal_path.exists(),
        "hal_path": str(hal_path),
        "cipla_exists": _parquet_path("CIPLA.NS").exists(),
        "db_status": db_status,
        "local_assembler": local_status,
        "cwd": os.getcwd(),
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
    }


@router.get("/debug/test-local/{ticker}")
async def debug_test_local(ticker: str):
    """Test local assembler directly — returns result or error."""
    ticker = ticker.upper().strip()
    import time as _t
    try:
        from backend.services.analysis_service import _get_pipeline_session
        t0 = _t.time()
        sess = _get_pipeline_session()
        db_time = _t.time() - t0
        if sess is None:
            return {"error": "session is None", "db_time_ms": round(db_time * 1000)}

        from backend.services.local_data_service import assemble_local
        t1 = _t.time()
        result = assemble_local(ticker, sess)
        asm_time = _t.time() - t1
        try:
            sess.close()
        except Exception:
            pass

        if result is None:
            return {"error": "assemble_local returned None", "db_time_ms": round(db_time * 1000), "asm_time_ms": round(asm_time * 1000)}

        return {
            "ok": True,
            "ticker": ticker,
            "price": result.get("price"),
            "source": result.get("_source"),
            "db_time_ms": round(db_time * 1000),
            "asm_time_ms": round(asm_time * 1000),
            "total_ms": round((db_time + asm_time) * 1000),
        }
    except Exception as exc:
        return {"error": str(exc), "type": type(exc).__name__}


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

    # --- Price history: DuckDB Parquet first, yfinance fallback ---
    _PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    _days = _PERIOD_DAYS.get(period, 30)
    prices: list[dict] = []
    try:
        from data_pipeline.nse_prices.db_integration import get_price_history
        _clean = ticker.replace(".NS", "").replace(".BO", "")
        df = get_price_history(_clean, _days)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                prices.append({
                    "date": str(row["date"])[:10],
                    "price": round(float(row["close"]), 2),
                })
    except Exception:
        pass

    # Fallback to yfinance if Parquet file doesn't exist
    if not prices:
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


@router.get("/analysis/{ticker}/fv-history")
async def get_fv_history_endpoint(
    ticker: str,
    years: int = Query(default=3, ge=1, le=5),
    user: dict = Depends(get_current_user_optional),
):
    """
    Historical YieldIQ fair value vs market price.

    Tier limits:
      - free      → 1 year max
      - starter   → 3 years max
      - pro       → 5 years max
    """
    ticker = ticker.upper().strip()

    tier = (user or {}).get("tier", "free")
    tier_order = {"free": 0, "starter": 1, "pro": 2}
    tier_level = tier_order.get(tier, 0)
    if tier_level == 0:
        years = min(years, 1)
    elif tier_level == 1:
        years = min(years, 3)
    # pro: no clamp beyond the Query's le=5

    # Pipeline DB session — same pattern as analysis_service._get_pipeline_session
    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception:
        PipelineSession = None

    if PipelineSession is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    db = PipelineSession()
    try:
        from data_pipeline.sources.fv_history import (
            get_fv_history,
            get_fv_history_summary,
        )
        data = get_fv_history(ticker, db, years)
        summary = get_fv_history_summary(ticker, db, years)

        if not data:
            return {
                "ticker": ticker,
                "has_data": False,
                "tier": tier,
                "tier_limited": tier_level == 0,
                "years_returned": 0,
                "data": [],
                "summary": summary,
                "message": (
                    "Historical fair value data is building up. "
                    "Analyse this stock regularly to grow the chart."
                ),
            }

        return {
            "ticker": ticker,
            "has_data": True,
            "tier": tier,
            "tier_limited": tier_level == 0,
            "years_returned": years,
            "data": data,
            "summary": summary,
        }
    finally:
        db.close()


@router.get("/analysis/{ticker}/financials")
async def get_financials_endpoint(
    ticker: str,
    period: str = Query(default="annual", pattern="^(annual|quarterly)$"),
    years: int = Query(default=5, ge=1, le=10),
    user: dict = Depends(get_current_user_optional),
):
    """
    Full financial statements (5y annual / 8q quarterly).

    Tier limits:
      - free       → 3 years max (annual); quarterly unaffected
      - starter+   → 5 years max
    """
    ticker = ticker.upper().strip()

    tier = (user or {}).get("tier", "free")
    tier_order = {"free": 0, "starter": 1, "pro": 2}
    tier_level = tier_order.get(tier, 0)
    tier_limited = tier_level == 0
    if period == "annual" and tier_level == 0:
        years = min(years, 3)
    elif period == "annual":
        years = min(years, 5)

    _cache_key = f"financials:{ticker}:{period}:{years}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    from backend.services.financials_service import FinancialsService
    svc = FinancialsService()
    try:
        result = svc.get_financials(ticker, period=period, years=years)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.financials").error(
            "Financials failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Financials unavailable")

    result["tier"] = tier
    result["tier_limited"] = tier_limited
    cache.set(_cache_key, result, ttl=86400)  # 30 min
    return result


@router.get("/analysis/{ticker}/peers")
async def get_peers_endpoint(
    ticker: str,
    user: dict = Depends(get_current_user_optional),
):
    """
    Peer comparison table for ``ticker``.

    YieldIQ score/grade/FV/MoS are read off the in-process cache — a
    peer's score is only populated if it has been analysed recently.
    Valuation multiples and quality metrics come from the DB, with a
    yfinance live fallback for tickers missing from the DB snapshot.
    """
    ticker = ticker.upper().strip()

    _cache_key = f"peers:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        from data_pipeline.db import Session as PipelineSession
    except Exception:
        PipelineSession = None

    db = PipelineSession() if PipelineSession is not None else None
    try:
        from backend.services.peers_service import PeersService
        svc = PeersService()
        result = svc.get_peer_comparison(ticker, db=db, cache=cache)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.peers").error(
            "Peer comparison failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Peer comparison unavailable")
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    if result.get("has_peers"):
        cache.set(_cache_key, result, ttl=86400)  # 30 min
    return result


@router.get("/analysis/{ticker}/dividends")
async def get_dividends_endpoint(
    ticker: str,
    user: dict = Depends(get_current_user_optional),
):
    """
    Live dividend data from yfinance (history + yield + payout).

    Coverage ratio is omitted here because the router has no
    access to the ``enriched`` dict. The same data is embedded in
    the main ``/analysis/{ticker}`` response under
    ``insights.dividend`` — use that when available.
    """
    ticker = ticker.upper().strip()

    _cache_key = f"dividends:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    from backend.services.dividend_service import DividendService
    try:
        result = DividendService().get_dividends(ticker, enriched=None)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.dividends").error(
            "Dividend endpoint failed for %s: %s", ticker, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Dividend data unavailable")

    cache.set(_cache_key, result, ttl=86400)  # 30 min
    return result


@router.get("/compare")
async def compare_stocks(
    ticker1: str,
    ticker2: str,
    user: dict = Depends(get_current_user),
):
    """Compare two stocks side by side."""
    ticker1 = ticker1.upper().strip()
    ticker2 = ticker2.upper().strip()

    # Get both analyses (uses cache if available)
    a1 = service.get_full_analysis(ticker1)
    a2 = service.get_full_analysis(ticker2)

    return {
        "stock1": {
            "ticker": a1.ticker,
            "company_name": a1.company.company_name,
            "sector": a1.company.sector,
            "price": a1.valuation.current_price,
            "fair_value": a1.valuation.fair_value,
            "mos": a1.valuation.margin_of_safety,
            "verdict": a1.valuation.verdict,
            "score": a1.quality.yieldiq_score,
            "piotroski": a1.quality.piotroski_score,
            "moat": a1.quality.moat,
            "moat_score": a1.quality.moat_score,
            "wacc": a1.valuation.wacc,
            "fcf_growth": a1.valuation.fcf_growth_rate,
            "confidence": a1.valuation.confidence_score,
            "roe": a1.quality.roe,
            "de_ratio": a1.quality.de_ratio,
        },
        "stock2": {
            "ticker": a2.ticker,
            "company_name": a2.company.company_name,
            "sector": a2.company.sector,
            "price": a2.valuation.current_price,
            "fair_value": a2.valuation.fair_value,
            "mos": a2.valuation.margin_of_safety,
            "verdict": a2.valuation.verdict,
            "score": a2.quality.yieldiq_score,
            "piotroski": a2.quality.piotroski_score,
            "moat": a2.quality.moat,
            "moat_score": a2.quality.moat_score,
            "wacc": a2.valuation.wacc,
            "fcf_growth": a2.valuation.fcf_growth_rate,
            "confidence": a2.valuation.confidence_score,
            "roe": a2.quality.roe,
            "de_ratio": a2.quality.de_ratio,
        },
        "winner": {
            "score": ticker1 if a1.quality.yieldiq_score > a2.quality.yieldiq_score else ticker2,
            "value": ticker1 if a1.valuation.margin_of_safety > a2.valuation.margin_of_safety else ticker2,
            "quality": ticker1 if a1.quality.piotroski_score > a2.quality.piotroski_score else ticker2,
            "moat": ticker1 if a1.quality.moat_score > a2.quality.moat_score else ticker2,
        }
    }


@router.get("/analysis/{ticker}/reverse-dcf")
async def get_reverse_dcf_endpoint(
    ticker: str,
    wacc: float | None = Query(default=None, ge=0.05, le=0.25, description="Override WACC (5%-25%)"),
    terminal_g: float | None = Query(default=None, ge=0.0, le=0.06, description="Override terminal growth (0%-6%)"),
    years: int = Query(default=10, ge=5, le=15),
    user: dict = Depends(get_current_user_optional),
):
    """
    Reverse DCF — what FCF growth rate is the market implying?
    Optional WACC and terminal growth overrides for sensitivity analysis.
    Returns implied growth, verdict, scenarios, and plain-English summary.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases
    ticker = TICKER_ALIASES.get(ticker, ticker)

    # Cache key includes overrides
    _cache_key = f"reverse_dcf:{ticker}:{wacc}:{terminal_g}:{years}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        result = service.get_reverse_dcf(
            ticker=ticker,
            wacc_override=wacc,
            terminal_g_override=terminal_g,
            years=years,
        )
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        cache.set(_cache_key, result, ttl=3600)
        return result
    except TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("yieldiq.reverse_dcf").error(f"Reverse DCF failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Reverse DCF computation failed")


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
        import logging
        logging.getLogger("yieldiq.analysis").error(
            f"Report generation failed for {ticker}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Report generation failed: {type(e).__name__}")
