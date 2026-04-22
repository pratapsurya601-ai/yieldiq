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
    # Mindtree merged into LTI → LTIMindtree (Nov 2022). Old ticker
    # LTI kept listing but was renamed LTIM which itself was later
    # relisted as LTIMINDTREE. Legacy user bookmarks + some of our
    # own TICKER_ALIASES in external scripts still hit LTIM.NS — it
    # exists on yfinance but returns stale/partial data. Sentry sees
    # 208+ events/day from this one symbol. Redirect to the canonical.
    "LTIM.NS":         "LTIMINDTREE.NS",
    "LTIM":            "LTIMINDTREE.NS",
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

    # Tier 0: in-memory RAW dict cache (fastest path — no Pydantic).
    # Set by the tier-2 DB-cache fast path below. Warm-warm requests
    # on the same worker return via this branch in ~5-10ms.
    _cache_key = f"analysis:{ticker}"
    _raw_cached = cache.get(_cache_key + ":raw")
    if _raw_cached:
        from fastapi.responses import JSONResponse as _JSONResponse
        # _raw_cached is already a dict with cached=True set.
        # Respect include_summary toggle via a shallow copy.
        if not include_summary and _raw_cached.get("ai_summary") is not None:
            _out = dict(_raw_cached)
            _out["ai_summary"] = None
            return _JSONResponse(content=_out, headers={"X-Cache": "HIT-MEM-RAW"})
        return _JSONResponse(content=_raw_cached, headers={"X-Cache": "HIT-MEM-RAW"})

    # Tier 1: in-memory Pydantic cache (legacy, for paths that set
    # the object form). Slower than tier-0 because FastAPI re-serializes.
    cached = cache.get(_cache_key)
    if cached:
        cached.cached = True
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
        # Return as JSONResponse so the X-Cache header is set ONCE.
        # Previously we mutated `response.headers["X-Cache"]` on the
        # Response param AND a parallel branch returned JSONResponse
        # with its own X-Cache header — FastAPI merged the two,
        # producing the comma-joined "HIT-MEM-RAW, MISS" bug.
        from fastapi.responses import JSONResponse as _JSONResponse
        from fastapi.encoders import jsonable_encoder as _je
        return _JSONResponse(
            content=_je(cached),
            headers={"X-Cache": "HIT-MEM"},
        )

    # Tier 2: persistent DB cache (shared across workers, survives restart).
    # Never raises — failures degrade to compute.
    try:
        _db_cached = analysis_cache_service.get_cached(ticker)
    except Exception:
        _db_cached = None
    if _db_cached:
        try:
            # FAST PATH — return the cached JSON directly without
            # re-validating through Pydantic or letting FastAPI
            # re-serialize the Pydantic object. Perf measurement showed
            # the warm-cache path was ~2.6s — almost all of that was
            # model_validate + FastAPI's response serialization on a
            # large AnalysisResponse payload. The payload was already
            # validated when originally cached (it passed validate_analysis
            # at compute time), so we can trust it.
            #
            # Schema tolerance (unknown keys stripped) is still applied
            # in case we've removed fields since the cache was written —
            # but this is a cheap dict filter, not model validation.
            from fastapi.responses import JSONResponse as _JSONResponse
            _cls_fields = set(AnalysisResponse.model_fields.keys())
            _clean = {k: v for k, v in _db_cached.items() if k in _cls_fields}
            _clean["cached"] = True
            if not include_summary:
                _clean["ai_summary"] = None
            # Populate tier-1 with the raw dict too. Next request on this
            # worker skips DB + all validation. We drop the Pydantic form
            # from tier-1 for the same reason — the warm-warm path is now
            # dict → JSONResponse, effectively zero-cost serialization.
            cache.set(_cache_key + ":raw", _clean, ttl=86400)
            return _JSONResponse(content=_clean, headers={"X-Cache": "HIT-DB-FAST"})
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analysis_cache: fast-path failed for %s (%s: %s) — recomputing + invalidating",
                ticker, type(_exc).__name__, _exc,
            )
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
            # Financials use the peer-median P/BV or P/E path, not DCF.
            # Skip the FCF-specific checks but keep ratio/MoS sanity
            # (defensive — a peer-path result should already be sane).
            _is_financial_path = (
                getattr(result.valuation, "valuation_model", "") == "pb_ratio"
            )
            # Zero fair value with positive price → validator fires
            # mos=-100% on these (e.g. PFC.NS, other NBFCs where
            # FCF-based DCF doesn't work). Caught by Sentry 18-Apr.
            # For financials this should not happen with the new
            # peer-band path, but if it does keep the data_limited
            # fallback as a safety net.
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
            # For financials valued via peer band, be slightly more
            # permissive — a deep-value PSU bank can legitimately sit
            # at ~60% undervalued; 95% is still outside the band.
            if abs(_mos) >= 95 and not _is_financial_path:
                _suspicious = True
            if _is_financial_path and abs(_mos) >= 95:
                # Tighter threshold for financials — the peer-band
                # method shouldn't produce >95% MoS; if it does,
                # inputs are bad.
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
        # Also populate tier-0 raw dict so subsequent requests on this
        # worker skip Pydantic re-validation + FastAPI serialization
        # entirely (the slow parts of the warm path).
        try:
            _raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.dict()
            _raw["cached"] = True
            cache.set(_cache_key + ":raw", _raw, ttl=86400)
        except Exception:
            pass

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

        if not include_summary:
            # Cache retains the full object (including any ai_summary the
            # service populated); only the response to this caller is trimmed.
            try:
                result = result.model_copy(update={"ai_summary": None})
            except Exception:
                result.ai_summary = None
        # Return as JSONResponse so the X-Cache=MISS header is the
        # only X-Cache value set on this response. Mutating the
        # `response: Response` param previously caused FastAPI to
        # merge it with JSONResponse-set headers from the fast paths,
        # which surfaced as "X-Cache: HIT-MEM-RAW, MISS" at the wire.
        from fastapi.responses import JSONResponse as _JSONResponse
        from fastapi.encoders import jsonable_encoder as _je
        return _JSONResponse(
            content=_je(result),
            headers={"X-Cache": "MISS"},
        )
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
    """Return Open Graph data for social sharing. No auth required.

    Cache-source unification (2026-04-22):
        Previously called `service.get_full_analysis()` directly and
        cached the result under its own `og:{ticker}` key. That meant
        og-data served a DIFFERENT canonical value than
        /public/stock-summary when the two computed in different
        contexts (cold worker, partial yfinance outage, etc.).

        INFY.NS and NESTLEIND.NS were observed returning fv=0/price=0
        /verdict=under_review via og-data while /public/stock-summary
        returned real numbers (fv=1916.74, score=76, undervalued) — the
        og: cache had poisoned zeros from an earlier failed compute,
        and the 1-hour TTL was re-poisoning itself every cycle.

        New path matches /public/stock-summary's tiered lookup:
            1. Local og: cache (1h) — fast path
            2. `analysis:{ticker}` tier-1 in-memory cache (24h)
            3. `analysis_cache_service.get_cached()` tier-2 Postgres
            4. `service.get_full_analysis()` live compute (last resort)

        Same source of truth as /public/stock-summary + the authed
        /analysis endpoint. Also adds a zero-poison guard: if the
        resolved payload has both fair_value and current_price == 0,
        we do NOT write it into the og: cache — a fresh compute gets
        to try again on the next request.
    """
    ticker = ticker.upper().strip()
    _cache_key = f"og:{ticker}"
    cached = cache.get(_cache_key)
    if cached:
        return cached

    try:
        # Tiered cache resolution — matches public/stock-summary so all
        # three endpoints (og-data, public stock-summary, authed analysis)
        # serve the same canonical AnalysisResponse.
        result = cache.get(f"analysis:{ticker}")
        if result is None or not hasattr(result, "valuation"):
            try:
                from backend.services import analysis_cache_service
                from backend.models.responses import AnalysisResponse
                _db_payload = analysis_cache_service.get_cached(ticker)
                if _db_payload:
                    result = AnalysisResponse(**_db_payload)
                    cache.set(f"analysis:{ticker}", result, ttl=86400)
            except Exception:
                result = None
        if result is None or not hasattr(result, "valuation"):
            # Last resort: live compute. Any output zeros here will be
            # caught by the zero-poison guard below rather than cached.
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
        # Zero-poison guard: if both fv and price ended up 0 (cold compute
        # failure, upstream data gap, etc.), skip the cache write so the
        # next request gets a fresh attempt. Previously the 1-hour TTL
        # on bad data created a self-perpetuating poison cycle for any
        # ticker that failed a single cold compute. Verdict-based cases
        # (real "under_review" with a known-bad reason) still cache —
        # they have a valid price and are legitimately labeled.
        if _fv == 0 and _px == 0:
            return og
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
        "model": "groq-llama-3.3-70b-versatile",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    cache.set(_summary_cache_key, payload, ttl=_AI_SUMMARY_CACHE_TTL_S)
    return payload


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


async def _build_yieldiq50() -> ScreenerResponse:
    """Build the YieldIQ 50 ScreenerResponse (no HTTP concerns).

    Split out from the HTTP handler so internal callers (e.g.
    get_top_pick) can consume the pydantic model directly, without
    the JSONResponse wrapping the HTTP endpoint applies for cache
    headers.
    """
    _cache_key = f"yieldiq50:{date.today().isoformat()}"

    # RAW dict cache — rebuild ScreenerResponse from the dict so the
    # return type is stable for all callers. HTTP handler adds cache
    # headers separately; internal callers get the model.
    _raw = cache.get(_cache_key + ":raw")
    if _raw is not None:
        try:
            return ScreenerResponse(**_raw)
        except Exception:
            # Corrupt/old raw cache — fall through and rebuild.
            pass

    cached = cache.get(_cache_key)
    if cached:
        try:
            _dump = cached.model_dump(mode="json") if hasattr(cached, "model_dump") else cached
            cache.set(_cache_key + ":raw", _dump, ttl=86400)
        except Exception:
            pass
        return cached

    by_ticker: dict[str, ScreenerStock] = {}
    # Merge in priority order; first-seen wins per ticker.
    for source in (_load_screener_csv(), _load_cached_analyses()):
        for s in source:
            if s.ticker and s.ticker not in by_ticker:
                by_ticker[s.ticker] = s

    # 2026-04-21 fix: previous behaviour returned 1 stock when CSV +
    # warm cache were both empty. Discover page looked broken. Add a
    # 3rd source: query fair_value_history + stocks directly from DB
    # so YieldIQ 50 always has the actual top-50 by score, even on a
    # cold cache.
    if len(by_ticker) < 50:
        try:
            from data_pipeline.db import Session as _S
            from sqlalchemy import text as _t
            if _S is not None:
                _db = _S()
                try:
                    rows = _db.execute(_t("""
                        WITH latest_fv AS (
                          SELECT DISTINCT ON (ticker)
                            ticker, fair_value, price, mos_pct, verdict
                          FROM fair_value_history
                          ORDER BY ticker, date DESC
                        )
                        SELECT
                          fv.ticker,
                          s.company_name,
                          s.sector,
                          fv.mos_pct,
                          fv.verdict
                        FROM latest_fv fv
                        JOIN stocks s ON s.ticker = fv.ticker
                        WHERE fv.mos_pct IS NOT NULL
                          AND s.is_active = TRUE
                        ORDER BY fv.mos_pct DESC NULLS LAST
                        LIMIT 80
                    """)).fetchall()
                    for r in rows:
                        t = r[0]
                        if t in by_ticker:
                            continue
                        # Score not persisted in fair_value_history;
                        # synthesize a reasonable proxy from MoS so the
                        # row renders without "—".
                        mos = float(r[3]) if r[3] is not None else 0.0
                        synth_score = min(95, max(35, int(50 + mos * 0.5)))
                        by_ticker[t] = ScreenerStock(
                            ticker=t,
                            company_name=r[1] or t,
                            score=synth_score,
                            margin_of_safety=round(mos, 1),
                            moat=None,
                            sector=r[2] or None,
                            verdict=r[4] or (
                                "undervalued" if mos > 10
                                else "fairly_valued" if mos > -10
                                else "overvalued"
                            ),
                        )
                        if len(by_ticker) >= 50:
                            break
                finally:
                    _db.close()
        except Exception:
            pass  # never block the response on the DB fallback

    # Re-fetch each known ticker against the LIVE PG-cached row so we
    # never serve a stale score/MoS once the live cache has fresher data.
    # Iterates only over tickers we already discovered above (CSV +
    # warm cache) — no static seed list any more.
    for t in list(by_ticker.keys()):
        try:
            cached_payload = analysis_cache_service.get_cached(t)
        except Exception:
            cached_payload = None
        if not cached_payload:
            continue
        try:
            v = cached_payload.get("valuation", {}) or {}
            q = cached_payload.get("quality", {}) or {}
            c = cached_payload.get("company", {}) or {}
            live_mos = v.get("margin_of_safety")
            live_score = q.get("yieldiq_score")
            if live_mos is None or live_score is None:
                continue
            prev = by_ticker[t]
            by_ticker[t] = ScreenerStock(
                ticker=t,
                company_name=c.get("company_name") or prev.company_name,
                score=int(live_score),
                margin_of_safety=round(float(live_mos), 1),
                moat=q.get("moat") or prev.moat,
                sector=c.get("sector") or prev.sector,
                verdict=v.get("verdict") or (
                    "undervalued" if live_mos > 10 else "fairly_valued" if live_mos > -10 else "overvalued"
                ),
            )
        except Exception:
            # Best-effort — keep the pre-override row from the source merge
            continue

    stocks = sorted(by_ticker.values(), key=lambda x: x.score, reverse=True)[:50]
    result = ScreenerResponse(results=stocks, total=len(stocks))
    if stocks:
        # PR-DISCOVER-CONSISTENCY: TTL was 24h. Audit found Discover
        # served ITC at static 38% MoS all day even after the SEO page
        # showed live -1.7%. Root cause: this cache was set at the
        # first morning request when analysis_cache for ITC was empty,
        # so the static seed won and got frozen for 24h. Shortening to
        # 5 min lets the per-ticker override (lines ~722-750) re-run
        # frequently — within 5 min of any user-triggered analysis,
        # Discover reflects the updated MoS.
        cache.set(_cache_key, result, ttl=300)
        try:
            cache.set(_cache_key + ":raw", result.model_dump(mode="json"), ttl=300)
        except Exception:
            pass
    return result


@router.get("/yieldiq50", response_model=ScreenerResponse)
async def get_yieldiq50(response: Response, user: dict = Depends(get_current_user)):
    """Top 50 undervalued high-quality stocks. Cached for 5 minutes.

    Sources are merged (not exclusive) and deduped by ticker:
      1. Real screener CSV output (highest priority — real scores)
      2. Warm AnalysisResponse cache (real scores from recent runs)

    On a cold cache (no screener CSV, no warm in-process entries) we
    return an empty list with HTTP 200 — frontend should treat
    `total == 0` as "warming, check back shortly".

    HTTP-layer concern: when the raw dict cache is warm, set edge
    cache headers so Vercel/CDN can reuse responses. Auth-gated data,
    so private. 1h max-age is fine since the list is recomputed daily.
    The underlying data build is delegated to _build_yieldiq50 so that
    internal callers (get_top_pick) get a typed ScreenerResponse and
    are not affected by this HTTP-only wrapping.
    """
    _cache_key = f"yieldiq50:{date.today().isoformat()}"
    if cache.get(_cache_key + ":raw") is not None:
        response.headers["X-Cache"] = "HIT-MEM-RAW"
        response.headers["Cache-Control"] = "private, max-age=3600"
    return await _build_yieldiq50()


@router.get("/top-pick")
async def get_top_pick(user: dict = Depends(get_current_user)):
    """Highest conviction stock from YieldIQ 50. Never returns score 0."""
    yiq50 = await _build_yieldiq50()

    # Defensive: `_build_yieldiq50` can return a bare dict or a cached
    # JSONResponse on rare fallback paths (e.g. a stale raw-cache entry
    # that failed ScreenerResponse rehydration). Guard against both
    # rather than crash with 'JSONResponse' object has no attribute 'results'.
    results = getattr(yiq50, "results", None)
    if results is None and isinstance(yiq50, dict):
        results = yiq50.get("results")
    if not results:
        return None

    # Filter for valid high-conviction stocks
    valid = [
        r for r in results
        if getattr(r, "score", 0) > 50 and getattr(r, "margin_of_safety", 0) > 5
    ]

    if valid:
        # Sort by combined conviction: 60% score + 40% MoS (capped at 50)
        best = max(valid, key=lambda r: getattr(r, "score", 0) * 0.6 + min(getattr(r, "margin_of_safety", 0), 50) * 0.4)
        return {
            "ticker": getattr(best, "ticker", ""),
            "company_name": getattr(best, "company_name", ""),
            "score": getattr(best, "score", 0),
            "mos": getattr(best, "margin_of_safety", 0),
            "moat": getattr(best, "moat", ""),
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

    # --- Price history ---
    # Source priority:
    #   1. DuckDB Parquet  (fastest; local file, <50ms)
    #   2. `daily_prices` Postgres table (bhavcopy-sourced, daily refresh)
    #   3. yfinance live  (emergency fallback; Sentry-tagged so we can
    #      track how often bhavcopy coverage is missing)
    _PERIOD_DAYS = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    _days = _PERIOD_DAYS.get(period, 30)
    prices: list[dict] = []
    _clean = ticker.replace(".NS", "").replace(".BO", "")

    # Helper to guard against NaN/inf leaking into JSON. `float(nan)`
    # round-trips fine in Python but FastAPI's JSONEncoder raises
    # "Out of range float values are not JSON compliant: nan" on
    # serialize. Sentry was catching ~36 events/week from this on
    # chart-data alone. Return None for non-finite values so the
    # frontend can render a gap in the line chart cleanly.
    import math as _math
    def _num(v):
        try:
            f = float(v)
            return round(f, 2) if _math.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    # 1. Parquet (primary)
    try:
        from data_pipeline.nse_prices.db_integration import get_price_history
        df = get_price_history(_clean, _days)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _p = _num(row["close"])
                if _p is None:
                    continue  # skip rows with NaN close
                prices.append({
                    "date": str(row["date"])[:10],
                    "price": _p,
                })
    except Exception:
        pass

    # 2. Postgres daily_prices (secondary — fed by NSE bhavcopy loader)
    if not prices:
        try:
            from data_pipeline.db import Session as _PipelineSession
            if _PipelineSession is not None:
                from sqlalchemy import text
                from datetime import date as _date, timedelta as _td
                _sess = _PipelineSession()
                try:
                    _start = _date.today() - _td(days=_days)
                    rows = _sess.execute(
                        text(
                            "SELECT trade_date, close_price "
                            "FROM daily_prices "
                            "WHERE ticker = :t AND trade_date >= :start "
                            "ORDER BY trade_date ASC"
                        ),
                        {"t": _clean, "start": _start},
                    ).mappings().all()
                    for r in rows:
                        _p = _num(r["close_price"])
                        if _p is None:
                            continue
                        prices.append({
                            "date": str(r["trade_date"])[:10],
                            "price": _p,
                        })
                finally:
                    try:
                        _sess.close()
                    except Exception:
                        pass
        except Exception:
            pass

    # 3. Fallback to yfinance only if neither parquet nor daily_prices had rows.
    # Warning log + Sentry tag so we can monitor how often this path fires.
    if not prices:
        try:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "chart-data fell back to yfinance for %s (parquet + daily_prices both empty)",
                ticker,
            )
            try:
                import sentry_sdk as _sentry_sdk
                _sentry_sdk.set_tag("data_source", "yfinance_fallback")
                _sentry_sdk.set_tag("endpoint", "chart-data")
            except Exception:
                pass

            import yfinance as yf
            hist = yf.Ticker(ticker).history(period=yf_period)
            if hist is not None and not hist.empty:
                hist = hist.reset_index()
                for _, row in hist.iterrows():
                    _p = _num(row["Close"])
                    if _p is None:
                        continue
                    prices.append({
                        "date": row["Date"].strftime("%Y-%m-%d"),
                        "price": _p,
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
                _v = _num(row.get("revenue", 0))
                if _v is None:
                    continue
                revenue_list.append({
                    "year": str(row.get("year", "")),
                    "value": round(_v),
                })

        fcf_list: list[dict] = []
        cf_df = collector.get_cashflow_history()
        if cf_df is not None and not cf_df.empty:
            for _, row in cf_df.iterrows():
                _v = _num(row.get("fcf", 0))
                if _v is None:
                    continue
                fcf_list.append({
                    "year": str(row.get("year", "")),
                    "value": round(_v),
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

    # Two-tier cache: tier 1 in-memory (per-worker, fast), tier 2
    # endpoint_cache DB table (shared, survives redeploys). Both keyed
    # by ticker + years since the response shape depends on years.
    # fv-history is safe to cache long (history only grows forward, and
    # the chart smooths over any 1-day staleness).
    _fvh_cache_key = f"fv-history:{ticker}:{years}"
    _mem_hit = cache.get(_fvh_cache_key)
    if _mem_hit is not None:
        _mem_hit_out = dict(_mem_hit)
        _mem_hit_out["tier"] = tier
        _mem_hit_out["tier_limited"] = tier_level == 0
        return _mem_hit_out

    from backend.services import endpoint_cache_service as _ecs
    _db_hit = _ecs.get(_fvh_cache_key)
    if _db_hit is not None:
        # Populate tier-1 so subsequent hits on this worker skip the DB
        cache.set(_fvh_cache_key, _db_hit, ttl=3600)
        _db_hit_out = dict(_db_hit)
        _db_hit_out["tier"] = tier
        _db_hit_out["tier_limited"] = tier_level == 0
        return _db_hit_out

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
            _empty = {
                "ticker": ticker,
                "has_data": False,
                "years_returned": 0,
                "data": [],
                "summary": summary,
                "message": (
                    "Historical fair value data is building up. "
                    "Analyse this stock regularly to grow the chart."
                ),
            }
            # Cache the empty-state too — cheaper than re-running the query
            # every request. Shorter TTL (1h) so we recheck soon after a
            # seed.
            cache.set(_fvh_cache_key, _empty, ttl=3600)
            try:
                _ecs.set(_fvh_cache_key, _empty, ttl_hours=1)
            except Exception:
                pass
            return {**_empty, "tier": tier, "tier_limited": tier_level == 0}

        _full = {
            "ticker": ticker,
            "has_data": True,
            "years_returned": years,
            "data": data,
            "summary": summary,
        }
        cache.set(_fvh_cache_key, _full, ttl=3600)
        try:
            _ecs.set(_fvh_cache_key, _full, ttl_hours=6)
        except Exception:
            pass
        return {**_full, "tier": tier, "tier_limited": tier_level == 0}
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

    # Tier 1: in-memory
    cached = cache.get(_cache_key)
    if cached:
        return cached

    # Tier 2: persistent endpoint_cache. Survives Railway redeploys.
    # Tier info varies by user so we re-stamp it per response; the
    # underlying statement rows are shared across tiers.
    from backend.services import endpoint_cache_service as _ecs
    _db_hit = _ecs.get(_cache_key)
    if _db_hit is not None:
        cache.set(_cache_key, _db_hit, ttl=86400)
        _out = dict(_db_hit)
        _out["tier"] = tier
        _out["tier_limited"] = tier_limited
        return _out

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

    # Persist WITHOUT tier stamping so other users of the same ticker
    # can reuse the row. The tier annotation below is response-only.
    cache.set(_cache_key, result, ttl=86400)
    try:
        _ecs.set(_cache_key, result, ttl_hours=24)
    except Exception:
        pass

    result["tier"] = tier
    result["tier_limited"] = tier_limited
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
