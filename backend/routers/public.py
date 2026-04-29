# backend/routers/public.py
# ═══════════════════════════════════════════════════════════════
# Public (no-auth) API endpoints for SEO pages, landing page,
# and shareable content. All endpoints cached aggressively.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
import time as _time
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.services.cache_service import cache
from backend.middleware.auth import get_current_user, is_superuser

logger = logging.getLogger("yieldiq.public")

router = APIRouter(prefix="/api/v1/public", tags=["public"])


# ─────────────────────────────────────────────────────────────────
# Screener column mapping (module-level so CI guards can import it).
#
# NOTE (2026-04-25 incident): pe_ratio/pb_ratio/ev_ebitda were previously
# mapped to ``rh.*`` (the latest_ratio CTE) but that CTE only projects
# roe / roce / de_ratio. The columns actually live on the latest_mm CTE
# (sourced from ``market_metrics``). Filters touching pe_ratio etc.
# therefore raised psycopg2.errors.UndefinedColumn → HTTP 400 →
# silent "No stocks match" in the UI. Promoting the map to module
# scope lets ``test_screener_column_mapping.py`` probe each alias
# against the live schema in CI.
# ─────────────────────────────────────────────────────────────────
SCREENER_FIELD_MAP: dict[str, str] = {
    "pe_ratio":       "mm.pe_ratio",
    "pb_ratio":       "mm.pb_ratio",
    "ev_ebitda":      "mm.ev_ebitda",
    "roe":            "rh.roe",
    "roce":           "rh.roce",
    "de_ratio":       "rh.de_ratio",
    "market_cap_cr":  "mm.market_cap_cr",
    "mcap":           "mm.market_cap_cr",   # alias
    "mos":            "fv.mos_pct",
    "score":          "fv.confidence",
    "sector":         "s.sector",
}


def validate_screener_column_mapping(dsn: str | None) -> list[str]:
    """Probe each SCREENER_FIELD_MAP entry against the live PG schema.

    Issues one ``SELECT <col_expr> FROM <table> LIMIT 1`` per alias,
    using the real CTE source table for each prefix. Returns a list of
    human-readable failure strings (empty list = all good). Used by
    both the CI parity test and the FastAPI startup self-test wired
    in ``backend/main.py``.

    This is intentionally tolerant of an empty / missing DSN: the
    caller (startup hook) decides whether to log or no-op. The CI
    test skips entirely when no DSN is available.
    """
    if not dsn:
        return ["no DSN provided"]
    # Map our CTE alias prefix → real underlying table for the probe.
    _PREFIX_TABLE = {
        "rh": "ratio_history",
        "mm": "market_metrics",
        "fv": "fair_value_history",
        "s":  "stocks",
    }
    failures: list[str] = []
    try:
        import psycopg2  # local import — keep module import light
    except Exception as exc:  # pragma: no cover - psycopg2 always present in CI
        return [f"psycopg2 import failed: {exc!r}"]

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        return [f"could not connect to DB: {exc!r}"]
    try:
        conn.autocommit = True
        for alias, col_expr in SCREENER_FIELD_MAP.items():
            try:
                prefix, _, col = col_expr.partition(".")
                if not col:
                    failures.append(f"{alias}: malformed mapping {col_expr!r}")
                    continue
                table = _PREFIX_TABLE.get(prefix)
                if not table:
                    failures.append(
                        f"{alias} → {col_expr}: unknown CTE prefix {prefix!r}"
                    )
                    continue
                with conn.cursor() as cur:
                    cur.execute(f"SELECT {col} FROM {table} LIMIT 1")
                    cur.fetchone()
            except Exception as exc:
                failures.append(f"{alias} → {col_expr}: {exc!r}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return failures


# ─────────────────────────────────────────────────────────────────
# JSON-safety helper (Sentry PYTHON-FASTAPI-6V):
# FastAPI/Pydantic's JSON encoder runs the stdlib json module with
# allow_nan=False semantics — any NaN / Inf in the response dict
# raises ValueError at serialization time and the client sees a 500.
# This recursive sanitizer converts non-finite floats to None while
# preserving real zeros and every other value unchanged. It runs as
# defensive middleware; compute-site fixes still apply upstream.
# ─────────────────────────────────────────────────────────────────
def _nan_to_none(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, dict):
        return {k: _nan_to_none(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_nan_to_none(x) for x in v]
    return v


# ─────────────────────────────────────────────────────────────────
# Debug probe — direct call into _fetch_roce_inputs with no caching,
# no compute, no wrappers. Returns exactly what the function yields
# so we can tell if the gap is pipeline vs read vs somewhere else.
#
# HARDENED 2026-04-22: superuser-only. Previously public; returned
# internal DB shape (column names, enriched vs DB values, session
# status) which is dev-grade info-disclosure. Now gated to
# SUPERUSER_EMAILS env list. Non-superusers get 404 (no acknowledgement
# the endpoint exists at all) to avoid signalling its presence.
# Schedule for removal after 1 week of stable ROCE values in prod;
# until then, kept for debugging regressions.
# ─────────────────────────────────────────────────────────────────
@router.get("/roce-probe/{ticker}")
async def roce_probe(
    ticker: str,
    user: dict = Depends(get_current_user),
):
    """Superuser-only probe: raw output of _fetch_roce_inputs PLUS the
    enriched-dict values that get mixed in downstream. Lets ops debug
    why _compute_roce in the main flow yields a different answer than
    a direct probe (unit mismatch, cache staleness, pipeline gap)."""
    if not is_superuser(user):
        # 404 rather than 403 so non-admins can't enumerate the endpoint
        raise HTTPException(status_code=404, detail="Not found")
    import traceback
    from backend.services.analysis_service import (
        _fetch_roce_inputs, _get_pipeline_session,
    )
    try:
        sess = _get_pipeline_session()
        session_ok = sess is not None
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
    except Exception as exc:
        return {
            "ticker": ticker,
            "session_ok": False,
            "session_error": f"{type(exc).__name__}: {exc}",
        }

    # Pull the same `enriched` dict the analysis pipeline uses, so we
    # can see whether its total_assets / current_liabilities values
    # (which take priority over _ta_db / _cl_db in get_full_analysis)
    # are poisoning the ROCE compute with a wrong unit or stale value.
    enriched_probe = {}
    try:
        # Match exactly what analysis_service.get_full_analysis does:
        #   raw = StockDataCollector(ticker).get_all()
        #   enriched = compute_metrics(raw)
        from data.collector import StockDataCollector
        from data.processor import compute_metrics
        raw = StockDataCollector(ticker).get_all() or {}
        enriched_full = compute_metrics(raw) or {}
        enriched_probe = {
            "total_assets": enriched_full.get("total_assets"),
            "current_liabilities": enriched_full.get("current_liabilities"),
            "total_debt": enriched_full.get("total_debt"),
            "ebitda": enriched_full.get("ebitda"),
            "roe": enriched_full.get("roe"),
            "roce": enriched_full.get("roce"),
            "ebit": enriched_full.get("ebit"),
        }
    except Exception as exc:
        enriched_probe = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        ebit, ta, cl, interest = _fetch_roce_inputs(ticker)
        denom = None
        roce_pct = None
        if ta is not None and cl is not None:
            denom = ta - cl
            if ebit is not None and denom and denom > 0:
                roce_pct = round(ebit / denom * 100, 2)

        # Now simulate what get_full_analysis actually computes:
        # _total_assets = enriched.total_assets OR _ta_db OR 0
        # _current_liab = enriched.current_liabilities OR _cl_db OR 0
        _ta_final = enriched_probe.get("total_assets") or ta or 0
        _cl_final = enriched_probe.get("current_liabilities") or cl or 0
        from backend.services.ratios_service import compute_roce as _c_roce
        _roce_as_main_flow = _c_roce(ebit, _ta_final, _cl_final)

        return {
            "ticker": ticker,
            "session_ok": session_ok,
            # From _fetch_roce_inputs (DB values in Crores)
            "db_ebit": ebit,
            "db_total_assets": ta,
            "db_current_liabilities": cl,
            "db_interest_expense": interest,
            "db_capital_employed": denom,
            "db_roce_pct": roce_pct,
            # From data.collector / yfinance (units may differ!)
            "enriched": enriched_probe,
            # What the main flow actually computes (mixing both)
            "main_flow_ta_used": _ta_final,
            "main_flow_cl_used": _cl_final,
            "main_flow_roce_pct": _roce_as_main_flow,
        }
    except Exception as exc:
        return {
            "ticker": ticker,
            "session_ok": session_ok,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _cached_json(content, s_maxage: int, swr: int = 3600, extra_headers: dict | None = None):
    """Wrap content in a JSONResponse with Vercel-edge Cache-Control.

    `s-maxage` applies to shared caches only (Vercel edge, CDNs) so
    browsers still revalidate; `stale-while-revalidate` lets the
    edge serve stale for `swr` seconds while refreshing in the
    background. Both values are in seconds.

    `extra_headers` lets callers stamp observability headers (e.g.
    X-Source) without losing the Cache-Control contract.
    """
    headers = {
        "Cache-Control": f"public, s-maxage={s_maxage}, stale-while-revalidate={swr}",
    }
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(content=content, headers=headers)


# ── Helpers ───────────────────────────────────────────────────

def _get_db_session():
    """Get a pipeline DB session (Aiven Postgres). Returns None on failure."""
    try:
        from backend.services.analysis_service import _get_pipeline_session
        return _get_pipeline_session()
    except Exception:
        return None


def _safe_close(session) -> None:
    if session:
        try:
            session.close()
        except Exception:
            pass


def _extract_analysis_summary(result) -> dict:
    """Extract a flat summary dict from a full AnalysisResponse object.

    Single-Source-of-Truth contract (PR1):
        Every value MUST be a direct read from the AnalysisResponse the
        analysis pipeline produced. NO local computation, NO synthesised
        fallbacks. If the SEO frontend asks for a field that is not on
        AnalysisResponse, return None here and log — that field must be
        added to the canonical schema in a follow-up PR; we do NOT
        materialise it locally because that re-creates the very drift
        we just deleted.
    """
    v = result.valuation
    q = result.quality
    c = result.company
    return {
        "ticker": result.ticker,
        "company_name": c.company_name,
        "sector": c.sector,
        "industry": getattr(c, "industry", ""),
        "exchange": getattr(c, "exchange", "NSE"),
        "currency": getattr(c, "currency", "INR"),
        "fair_value": round(v.fair_value, 2),
        "current_price": round(v.current_price, 2),
        "mos": round(v.margin_of_safety, 1),
        "verdict": v.verdict,
        "score": q.yieldiq_score,
        "grade": q.grade,
        "moat": q.moat,
        "piotroski": q.piotroski_score,
        "bear_case": round(v.bear_case, 2),
        "base_case": round(v.base_case, 2),
        "bull_case": round(v.bull_case, 2),
        "wacc": round(v.wacc, 4),
        "confidence": v.confidence_score,
        # PR-EXTRACT-FIX (2026-04-19): `if x else None` treats 0.0 as
        # missing, which hid real zero-debt cash-rich IT names (TCS,
        # INFY reliably have de_ratio ≈ 0 and were rendering "—").
        # Use `is not None` so genuine zeros pass through.
        "roe": round(q.roe, 2) if q.roe is not None else None,
        "de_ratio": round(q.de_ratio, 2) if q.de_ratio is not None else None,
        # Phase 2.1 ratios — Optional; None renders as "—" on frontend.
        # ROCE sentinel guard: the ratios_service computation returns
        # None for bad inputs, but some older cached payloads carry
        # 0.0 as a leaked sentinel (before FIX2). Collapse those to
        # None here so the UI doesn't render a misleading "0.0% Weak"
        # chip for companies that have real ROCE > 0 the next cache cycle.
        "roce": (lambda r: None if r is None or abs(r) < 0.05 else r)(
            getattr(q, "roce", None)
        ),
        "debt_ebitda": getattr(q, "debt_ebitda", None),
        "interest_coverage": getattr(q, "interest_coverage", None),
        "current_ratio": getattr(q, "current_ratio", None),
        "asset_turnover": getattr(q, "asset_turnover", None),
        "revenue_cagr_3y": getattr(q, "revenue_cagr_3y", None),
        "revenue_cagr_5y": getattr(q, "revenue_cagr_5y", None),
        "ev_ebitda": (getattr(result, "insights", None) and getattr(result.insights, "ev_ebitda", None)),
        "market_cap": c.market_cap,
        # ── Peer-multiple sanity ceiling disclosure ───────────────
        # Mirror the authed endpoint surface (PR #136) so the SEO
        # frontend can render the same "FV capped at 1.5× peer median"
        # explanatory tooltip without re-deriving anything. Always emit
        # `fair_value_source` (defaults "dcf"); only emit
        # `peer_cap_details` when the cap actually fired.
        "fair_value_source": getattr(v, "fair_value_source", "dcf"),
        "peer_cap_details": (
            v.peer_cap_details.model_dump()
            if getattr(v, "peer_cap_details", None) is not None
            else None
        ),
        "ai_summary_snippet": (
            result.ai_summary[:200] + "..." if result.ai_summary and len(result.ai_summary) > 200
            else result.ai_summary
        ),
        "last_updated": result.timestamp,
    }


# ═══════════════════════════════════════════════════════════════
# TASK 5 — Landing page endpoints
# ═══════════════════════════════════════════════════════════════

@router.get("/recent-activity")
async def get_recent_activity(limit: int = Query(default=10, le=20)):
    """
    Recent analyses from fair_value_history for the live activity feed.
    No auth required. 5-minute cache.
    """
    _cache_key = f"public:recent-activity:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=60, swr=300)

    results = []
    db = _get_db_session()
    if db:
        try:
            from data_pipeline.models import FairValueHistory
            rows = (
                db.query(FairValueHistory)
                .order_by(FairValueHistory.date.desc(), FairValueHistory.id.desc())
                .limit(limit)
                .all()
            )
            for r in rows:
                display = r.ticker.replace(".NS", "").replace(".BO", "")
                verdict_text = (r.verdict or "").replace("_", " ")
                results.append({
                    "ticker": r.ticker,
                    "display_ticker": display,
                    "company_name": display,  # will be enriched below
                    "fair_value": r.fair_value,
                    "price": r.price,
                    "mos_pct": r.mos_pct,
                    "verdict": verdict_text,
                    "date": r.date.isoformat() if r.date else None,
                })
            # Enrich company names from analysis cache
            for item in results:
                cached_analysis = cache.get(f"analysis:{item['ticker']}")
                if cached_analysis and hasattr(cached_analysis, "company"):
                    item["company_name"] = cached_analysis.company.company_name
        except Exception as e:
            logger.warning(f"recent-activity DB query failed: {e}")
        finally:
            _safe_close(db)

    # Fallback: scan cache if DB unavailable
    if not results:
        for key in list(cache._store.keys()):
            if not key.startswith("analysis:"):
                continue
            val = cache.get(key)
            if val and hasattr(val, "valuation"):
                display = val.ticker.replace(".NS", "").replace(".BO", "")
                results.append({
                    "ticker": val.ticker,
                    "display_ticker": display,
                    "company_name": val.company.company_name,
                    "fair_value": round(val.valuation.fair_value, 2),
                    "price": round(val.valuation.current_price, 2),
                    "mos_pct": round(val.valuation.margin_of_safety, 1),
                    "verdict": val.valuation.verdict.replace("_", " "),
                    "date": val.timestamp[:10] if val.timestamp else None,
                })
            if len(results) >= limit:
                break

    cache.set(_cache_key, results, ttl=300)
    # 1 min fresh at edge, 5 min stale-while-revalidate — list updates
    # every few minutes as new analyses stream in.
    return _cached_json(results, s_maxage=60, swr=300)


@router.get("/demo-cards")
async def get_demo_cards():
    """
    Return up to 4 cached analyses for the hero rotating demo card.
    No auth required. 2-minute cache.
    """
    _cache_key = "public:demo-cards"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=120, swr=600)

    # Preferred tickers for the demo card rotation
    preferred = ["ITC.NS", "RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]
    cards = []

    for ticker in preferred:
        val = cache.get(f"analysis:{ticker}")
        if val and hasattr(val, "valuation"):
            v = val.valuation
            q = val.quality
            cards.append({
                "ticker": val.ticker,
                "display_ticker": ticker.replace(".NS", ""),
                "company_name": val.company.company_name,
                "sector": val.company.sector,
                "current_price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "grade": q.grade,
                "moat": q.moat,
                "bear_case": round(v.bear_case, 2),
                "base_case": round(v.base_case, 2),
                "bull_case": round(v.bull_case, 2),
            })
        if len(cards) >= 4:
            break

    cache.set(_cache_key, cards, ttl=120)
    return _cached_json(cards, s_maxage=120, swr=600)


# ═══════════════════════════════════════════════════════════════
# TASK 1 — Stock SEO page endpoints
# ═══════════════════════════════════════════════════════════════

@router.get("/stock-summary/{ticker}")
async def get_stock_summary(ticker: str):
    """
    Public stock summary for SEO pages. No auth required.

    Single-Source-of-Truth (PR1, 2026-04-19):
        Reads exclusively from `analysis_cache` (persisted v35 payload).
        NEVER recomputes locally — that path was the cause of the public/
        authed FV drift (HCLTECH, etc.). If the cache is empty for a
        ticker, we return a 503 "data under review" payload rather than
        synthesizing a different number than the authed endpoint.

        All fields the SEO page renders are sourced from the canonical
        AnalysisResponse schema. Any field the SEO page wants that is NOT
        in the cache schema must be added to AnalysisResponse — it cannot
        be back-doored here without re-introducing the drift bug.

    Cache: edge s-maxage=600, swr=3600. X-Source header for observability.
    """
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases (e.g. ZOMATO.NS → ETERNAL.NS)
    try:
        from backend.routers.analysis import TICKER_ALIASES
        ticker = TICKER_ALIASES.get(ticker, ticker)
    except Exception:
        pass

    _cache_key = f"public:stock-summary:{ticker}"
    # version_keyed=True: prefix the storage key with v{CACHE_VERSION}
    # so a CACHE_VERSION bump retires this entire generation of
    # rendered summaries instead of leaving them shielded by their
    # 1-hour TTL. See cache_service.py + docs/cache_layer_audit.md.
    _cached_summary = cache.get(_cache_key, version_keyed=True)
    if _cached_summary is not None:
        return _cached_json(
            _cached_summary,
            s_maxage=600,
            swr=3600,
            extra_headers={"X-Source": "analysis_cache_v35", "X-Cache": "HIT"},
        )

    # Resolve the canonical AnalysisResponse from the same place the
    # authed endpoint serves it. Tier 1 is the in-memory cache (warm
    # path); tier 2 is the persistent analysis_cache table (survives
    # Railway redeploys). Both are populated only by the analysis
    # service, never by this router.
    analysis_cached = cache.get(f"analysis:{ticker}")
    if analysis_cached is None or not hasattr(analysis_cached, "valuation"):
        try:
            from backend.services import analysis_cache_service
            from backend.models.responses import AnalysisResponse
            _db_payload = analysis_cache_service.get_cached(ticker)
            if _db_payload:
                analysis_cached = AnalysisResponse(**_db_payload)
                # Populate tier-1 so subsequent requests on this worker
                # skip the DB round-trip.
                cache.set(f"analysis:{ticker}", analysis_cached, ttl=86400)
        except Exception as _exc:
            logger.info(
                "stock-summary: analysis_cache tier-2 lookup failed for %s: %s",
                ticker, _exc,
            )

    # HOTFIX-CACHE-MISS (2026-04-19): Cache miss on BOTH tiers.
    #
    # Original PR1 behaviour was a hard 503 "under_review" here, on the
    # theory that the warmer/nightly job populates the cache and any
    # recompute on this path would re-introduce the SoT drift bug.
    #
    # In practice that left every post-CACHE_VERSION-bump window
    # (including the v40→v41 bump on 2026-04-19) serving 503 to every
    # real visitor for ~30 min while warmup ground through top-500.
    # When SERVICE_WARMUP_TOKEN is stale (which it was after the
    # JWT_SECRET rotation), the 503 window is indefinite.
    #
    # Safer design: fall through to the same analysis_service.get_full_analysis
    # that the authed endpoint uses, cache the result to analysis_cache so
    # subsequent hits are SoT-consistent, and return. This is NOT a new
    # source of truth — it's the SAME source of truth, evaluated lazily
    # instead of depending on a background job to front-fill it.
    #
    # The SoT invariant PR1 protects is: "public and authed serve
    # identical values for every shared field." That still holds as
    # long as both endpoints call the same analysis service. They do.
    if analysis_cached is None or not hasattr(analysis_cached, "valuation"):
        try:
            # HOTFIX-2: get_full_analysis is a SYNC method on AnalysisService,
            # not a module-level async function. Mirror how the authed
            # router invokes it (see backend/routers/analysis.py:24 for
            # the singleton instance pattern).
            from backend.services.analysis_service import AnalysisService
            import time as _time
            _svc = AnalysisService()
            logger.info(
                "stock-summary cache miss for %s — lazy-recompute fallback", ticker
            )
            _compute_start = _time.monotonic()
            analysis_cached = _svc.get_full_analysis(ticker)
            _compute_ms = int((_time.monotonic() - _compute_start) * 1000)
            # Best-effort persist so the next hit is a straight cache read.
            # If persist fails, the response is still correct; we just lose
            # the warm-path optimization on this worker.
            try:
                from backend.services import analysis_cache_service
                # save_cached signature is (ticker, payload, compute_ms) —
                # previously we passed only 2 args, which threw
                # "missing 1 required positional argument: 'compute_ms'"
                # on every cache miss and silently lost the write-back.
                analysis_cache_service.save_cached(
                    ticker, analysis_cached.model_dump(), _compute_ms
                )
            except Exception as _persist_exc:
                logger.warning(
                    "stock-summary lazy-recompute persist failed for %s: %s",
                    ticker, _persist_exc,
                )
            # Tier-1 populate so this worker serves subsequent hits warm.
            cache.set(f"analysis:{ticker}", analysis_cached, ttl=86400)
        except Exception as _compute_exc:
            # Compute genuinely failed (delisted, no data, upstream outage).
            # Return the original under_review payload so the UI has a
            # deterministic shape to render.
            logger.warning(
                "stock-summary lazy-recompute failed for %s: %s",
                ticker, _compute_exc,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "status": "under_review",
                    "ticker": ticker,
                    "message": "Analysis is being prepared for this ticker. Please check back shortly.",
                    "last_validated_at": "",
                    "reason": "cache_miss_recompute_failed",
                    "issue_count": 0,
                },
                headers={
                    "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
                    "X-Source": "analysis_cache_v35",
                    "X-Cache": "MISS-FAIL",
                },
            )

    # Quarantine gate — same as the authed endpoint. If validators flag
    # this payload, return the under_review structure WITHOUT caching it
    # under the clean key.
    from backend.services.validators import check_and_quarantine
    quarantine = check_and_quarantine(ticker, analysis_cached)
    if quarantine is not None:
        return quarantine

    # FIX-AI-SUMMARY-FLAGSHIPS (2026-04-21): attach ai_summary snippet if
    # one is cached (populated by the /analysis/{ticker}/summary endpoint
    # on first authed request, or by scripts/warm_ai_summaries.py on the
    # flagship warmup job). NON-BLOCKING: never calls the LLM on the
    # request path, so public-endpoint latency stays ~200ms. If no summary
    # is cached yet, ai_summary_snippet will be null on this response --
    # the warmup job is responsible for populating it.
    try:
        from backend.services.analysis_service import AnalysisService as _AS
        analysis_cached = _AS().ensure_ai_summary(ticker, analysis_cached)
    except Exception as _ai_exc:
        logger.info(
            "stock-summary: ensure_ai_summary non-fatal for %s: %s",
            ticker, _ai_exc,
        )

    summary = _extract_analysis_summary(analysis_cached)
    cache.set(_cache_key, summary, ttl=3600, version_keyed=True)
    return _cached_json(
        summary,
        s_maxage=600,
        swr=3600,
        extra_headers={"X-Source": "analysis_cache_v35", "X-Cache": "MISS"},
    )


@router.get("/promoter-pledge/{ticker}")
async def get_promoter_pledge(ticker: str):
    """
    Promoter pledge series + latest snapshot for a ticker.

    Indian governance signal #1. Pledge data lives in ``promoter_pledges``
    (populated by ``scripts/ingest_pledges.py``). Returned shape:

      {
        "ticker": "RCOM",
        "latest": {
          "as_of_date": "2026-01-31",
          "pledged_pct": 80.0,
          "promoter_group_pct": 21.97,
          "pledged_shares": 4400000000,
          "source_url": "https://www.bseindia.com/..."
        } | null,
        "history": [{"as_of_date": ..., "pledged_pct": ...}, ...],
        "change_90d_pp": 15.0 | null
      }

    Additive surface — no CACHE_VERSION bump required. Public; no auth.
    1-hour CDN cache (pledge filings are infrequent).
    """
    t = (ticker or "").strip().upper()
    if not t:
        raise HTTPException(status_code=400, detail="ticker required")

    _cache_key = f"public:promoter-pledge:{t}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=3600, swr=7200)

    try:
        from backend.services.promoter_pledge_service import (
            get_latest_pledge,
            get_pledge_history,
            compute_pledge_change_pp,
        )
    except Exception as exc:
        logger.warning("promoter-pledge import failed: %s", exc)
        raise HTTPException(status_code=503, detail="pledge service unavailable")

    latest = get_latest_pledge(t)
    history = get_pledge_history(t, months=24)
    change_90d = compute_pledge_change_pp(t, lookback_days=90)

    payload = {
        "ticker": t,
        "latest": (latest.to_dict() if latest else None),
        "history": [
            {
                "as_of_date": r.as_of_date.isoformat(),
                "pledged_pct": r.pledged_pct,
                "promoter_group_pct": r.promoter_group_pct,
            }
            for r in history
        ],
        "change_90d_pp": (round(change_90d, 3) if change_90d is not None else None),
    }
    cache.set(_cache_key, payload, ttl=3600, version_keyed=False)
    return _cached_json(payload, s_maxage=3600, swr=7200)


@router.get("/all-tickers")
async def get_all_tickers():
    """
    All tickers with last update date — for sitemap generation + universe
    quality scans. Merges FairValueHistory (stocks users have analyzed)
    with NSE_UNIVERSE (the curated pipeline coverage list) so that new
    tickers appear in scans even before any user has analyzed them.
    No auth required. 24-hour cache.
    """
    _cache_key = "public:all-tickers"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=86400, swr=172800)

    tickers = []
    seen_symbols: set[str] = set()

    # Source 1: fair_value_history table
    db = _get_db_session()
    if db:
        try:
            from sqlalchemy import func
            from data_pipeline.models import FairValueHistory
            rows = (
                db.query(
                    FairValueHistory.ticker,
                    func.max(FairValueHistory.date).label("last_updated"),
                )
                .group_by(FairValueHistory.ticker)
                .all()
            )
            for r in rows:
                display = r.ticker.replace(".NS", "").replace(".BO", "")
                if display in seen_symbols:
                    continue
                seen_symbols.add(display)
                tickers.append({
                    "ticker": display,
                    "full_ticker": r.ticker,
                    "last_updated": r.last_updated.isoformat() if r.last_updated else None,
                })
        except Exception as e:
            logger.warning(f"all-tickers DB query failed: {e}")
        finally:
            _safe_close(db)

    # Source 2: analysis cache (additional coverage)
    for key in list(cache._store.keys()):
        if key.startswith("analysis:") and ".NS" in key:
            t = key.replace("analysis:", "")
            display = t.replace(".NS", "").replace(".BO", "")
            if display in seen_symbols:
                continue
            seen_symbols.add(display)
            tickers.append({
                "ticker": display,
                "full_ticker": t,
                "last_updated": None,
            })

    # Source 3: NSE_UNIVERSE (curated pipeline coverage — ~100 large-caps)
    # Ensures every tracked ticker appears in scans even if no user has
    # analyzed it yet. This is what the universe-scan workflow iterates.
    try:
        from data_pipeline.pipeline import NSE_UNIVERSE
        for t in NSE_UNIVERSE:
            display = t.replace(".NS", "").replace(".BO", "")
            if display in seen_symbols:
                continue
            seen_symbols.add(display)
            tickers.append({
                "ticker": display,
                "full_ticker": f"{display}.NS",
                "last_updated": None,
            })
    except Exception as e:
        logger.warning(f"all-tickers NSE_UNIVERSE merge failed: {e}")

    # Source 4 (added 2026-04-21 after GSC showed only 264/4549 stocks
    # were indexed): every active row from the `stocks` table. The
    # sitemap consumer needs the full universe — Phase A added ~1,500
    # BSE-only tickers that had no FairValueHistory yet, and pre-Phase-A
    # NSE tickers without analyses were also missing.
    db2 = _get_db_session()
    if db2:
        try:
            from sqlalchemy import text as _t
            rows = db2.execute(_t(
                "SELECT ticker FROM stocks WHERE is_active = TRUE"
            )).fetchall()
            for r in rows:
                t = r[0]
                if not t:
                    continue
                display = t.replace(".NS", "").replace(".BO", "")
                if display in seen_symbols:
                    continue
                seen_symbols.add(display)
                tickers.append({
                    "ticker": display,
                    "full_ticker": t if (t.endswith(".NS") or t.endswith(".BO")) else f"{t}.NS",
                    "last_updated": None,
                })
        except Exception as e:
            logger.warning(f"all-tickers stocks-table merge failed: {e}")
        finally:
            _safe_close(db2)

    cache.set(_cache_key, tickers, ttl=86400)
    return _cached_json(tickers, s_maxage=86400, swr=172800)


# ═══════════════════════════════════════════════════════════════
# TASK 2 — Index dashboard endpoints
# ═══════════════════════════════════════════════════════════════

INDICES: dict[str, dict] = {
    "nifty50": {
        "name": "Nifty 50 Valuation Dashboard",
        "description": "All 50 Nifty 50 stocks ranked by DCF fair value",
        "tickers": [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
            "SBIN.NS", "ICICIBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
            "WIPRO.NS", "AXISBANK.NS", "KOTAKBANK.NS", "LT.NS", "SUNPHARMA.NS",
            "HCLTECH.NS", "NESTLEIND.NS", "ASIANPAINT.NS", "ULTRACEMCO.NS", "ADANIENT.NS",
            "ADANIPORTS.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "COALINDIA.NS",
            "BHARTIARTL.NS", "DIVISLAB.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS",
            "HINDUNILVR.NS", "TATASTEEL.NS", "TECHM.NS", "APOLLOHOSP.NS", "BRITANNIA.NS",
            "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "INDUSINDBK.NS", "GRASIM.NS", "JSWSTEEL.NS",
            "BPCL.NS", "HINDALCO.NS", "M&M.NS", "TRENT.NS", "BEL.NS",
            "SHRIRAMFIN.NS", "ETERNAL.NS", "HAL.NS", "DMART.NS", "TATACONSUM.NS",
        ],
    },
    "nifty-bank": {
        "name": "Nifty Bank Valuation Dashboard",
        "description": "All Nifty Bank stocks ranked by DCF fair value",
        "tickers": [
            "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS",
            "SBIN.NS", "INDUSINDBK.NS", "BANDHANBNK.NS", "FEDERALBNK.NS",
            "BAJFINANCE.NS", "BAJAJFINSV.NS", "CHOLAFIN.NS", "SHRIRAMFIN.NS",
        ],
    },
    "nifty-it": {
        "name": "Nifty IT Valuation Dashboard",
        "description": "All Nifty IT stocks ranked by DCF fair value",
        "tickers": [
            "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
            "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "LTTS.NS",
        ],
    },
}


@router.get("/index-dashboard/{index_id}")
async def get_index_dashboard(index_id: str):
    """
    Valuation data for all stocks in an index. No auth required.
    15-minute cache.
    """
    if index_id not in INDICES:
        raise HTTPException(status_code=404, detail=f"Index '{index_id}' not found")

    _cache_key = f"public:index:{index_id}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=300, swr=3600)

    config = INDICES[index_id]
    stocks = []

    # ── Quality gate ────────────────────────────────────────────
    # Hide any stock whose USER-FACING fair_value / price ratio is
    # suspicious. This is the number on screen — if it's > 3x or
    # > 150% MoS, it's almost certainly a unit/conversion bug.
    # (e.g. HCLTECH showing FV ₹6,075 vs price ₹1,434, +268% MoS).
    # We deliberately do NOT check the raw DCF IV because that's
    # pre-blend/pre-cap and legitimately diverges for overvalued
    # quality names after the PE blend.
    def _is_suspicious(fv: float, price: float, mos: float) -> str | None:
        if price > 0 and fv > 0:
            ratio = fv / price
            if ratio > 3.0:
                return f"FV={ratio:.1f}x price"
            if ratio < 0.15:
                return f"FV={ratio:.2f}x price"
        if abs(mos) > 200:
            return f"MoS={mos:.0f}%"
        return None

    hidden: list[dict] = []

    for ticker in config["tickers"]:
        # Try analysis cache
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            v = analysis.valuation
            q = analysis.quality
            c = analysis.company

            _reason = _is_suspicious(
                float(v.fair_value or 0),
                float(v.current_price or 0),
                float(v.margin_of_safety or 0),
            )
            if _reason:
                hidden.append({
                    "ticker": ticker,
                    "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                    "reason": _reason,
                })
                continue

            stocks.append({
                "ticker": ticker,
                "display_ticker": ticker.replace(".NS", "").replace(".BO", ""),
                "company_name": c.company_name,
                "sector": c.sector,
                "current_price": round(v.current_price, 2),
                "fair_value": round(v.fair_value, 2),
                "mos": round(v.margin_of_safety, 1),
                "verdict": v.verdict,
                "score": q.yieldiq_score,
                "grade": q.grade,
                "moat": q.moat,
                "market_cap": c.market_cap,
            })

    # Sort by score descending
    stocks.sort(key=lambda x: x.get("score", 0), reverse=True)

    result = {
        "index_id": index_id,
        "index_name": config["name"],
        "description": config["description"],
        "total_stocks": len(config["tickers"]),
        "available_stocks": len(stocks),
        "hidden_for_quality": hidden,
        "stocks": stocks,
        "summary": {
            "undervalued": sum(1 for s in stocks if s["verdict"] == "undervalued"),
            "fairly_valued": sum(1 for s in stocks if s["verdict"] == "fairly_valued"),
            "overvalued": sum(1 for s in stocks if s["verdict"] in ("overvalued", "avoid")),
            "most_undervalued": max(stocks, key=lambda x: x["mos"]) if stocks else None,
            "most_overvalued": min(stocks, key=lambda x: x["mos"]) if stocks else None,
        },
    }

    cache.set(_cache_key, result, ttl=900)
    return _cached_json(result, s_maxage=300, swr=3600)


# ═══════════════════════════════════════════════════════════════
# TASK 3 — Public compare endpoint
# ═══════════════════════════════════════════════════════════════

@router.get("/compare")
async def public_compare(
    ticker1: str = Query(...),
    ticker2: str = Query(...),
):
    """
    Public stock comparison. No auth required. 1-hour cache.
    """
    t1 = ticker1.upper().strip()
    t2 = ticker2.upper().strip()
    if not t1.endswith(".NS") and not t1.endswith(".BO"):
        t1 = f"{t1}.NS"
    if not t2.endswith(".NS") and not t2.endswith(".BO"):
        t2 = f"{t2}.NS"

    # Resolve aliases
    try:
        from backend.routers.analysis import TICKER_ALIASES
        t1 = TICKER_ALIASES.get(t1, t1)
        t2 = TICKER_ALIASES.get(t2, t2)
    except Exception:
        pass

    # Sorted key for consistent caching
    pair = tuple(sorted([t1, t2]))
    _cache_key = f"public:compare:{pair[0]}:{pair[1]}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    def _flatten(analysis) -> dict:
        v = analysis.valuation
        q = analysis.quality
        c = analysis.company
        ev_ebitda = None
        try:
            ev_ebitda = getattr(analysis, "insights", None) and getattr(analysis.insights, "ev_ebitda", None)
        except Exception:
            ev_ebitda = None
        return {
            "ticker": analysis.ticker,
            "display_ticker": analysis.ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": c.company_name,
            "sector": c.sector,
            "price": round(v.current_price, 2),
            "current_price": round(v.current_price, 2),
            "fair_value": round(v.fair_value, 2),
            "mos": round(v.margin_of_safety, 1),
            "verdict": v.verdict,
            "score": q.yieldiq_score,
            "grade": q.grade,
            "piotroski": q.piotroski_score,
            "moat": q.moat,
            "moat_score": q.moat_score,
            "wacc": round(v.wacc, 4),
            "fcf_growth": round(v.fcf_growth_rate, 4) if v.fcf_growth_rate else None,
            "confidence": v.confidence_score,
            "roe": round(q.roe, 2) if q.roe else None,
            "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
            "market_cap": c.market_cap,
        }

    def _get_stock_data(ticker: str) -> dict | None:
        from backend.services.validators import check_and_quarantine
        # Try cache first
        analysis = cache.get(f"analysis:{ticker}")
        if analysis and hasattr(analysis, "valuation"):
            if check_and_quarantine(ticker, analysis) is not None:
                return None
            return _flatten(analysis)
        # Try running analysis
        try:
            from backend.services.analysis_service import AnalysisService
            result = AnalysisService().get_full_analysis(ticker)
            if check_and_quarantine(ticker, result) is not None:
                return None
            return _flatten(result)
        except Exception:
            return None

    s1 = _get_stock_data(t1)
    s2 = _get_stock_data(t2)

    if not s1 or not s2:
        missing = t1 if not s1 else t2
        raise HTTPException(status_code=404, detail=f"Could not get data for {missing}")

    # Determine winners
    def _winner(key: str, higher_is_better: bool = True):
        v1, v2 = s1.get(key), s2.get(key)
        if v1 is None or v2 is None:
            return "tie"
        if higher_is_better:
            return "stock1" if v1 > v2 else "stock2" if v2 > v1 else "tie"
        return "stock1" if v1 < v2 else "stock2" if v2 < v1 else "tie"

    winner = {
        "score": _winner("score"),
        "value": _winner("mos"),
        "quality": _winner("piotroski"),
        "moat": _winner("moat_score"),
    }

    # Overall winner
    w1 = sum(1 for v in winner.values() if v == "stock1")
    w2 = sum(1 for v in winner.values() if v == "stock2")
    overall = "stock1" if w1 > w2 else "stock2" if w2 > w1 else "tie"

    result = {
        "stock1": s1,
        "stock2": s2,
        "winner": winner,
        "overall_winner": overall,
        "stock1_wins": w1,
        "stock2_wins": w2,
        "total_metrics": len(winner),
    }

    cache.set(_cache_key, result, ttl=3600)
    return result

# ---------------------------------------------------------------
# Earnings Calendar � public endpoint
# ---------------------------------------------------------------

@router.get("/earnings-calendar")
async def get_earnings_calendar(
    days: int = Query(default=14, le=60),
    limit: int = Query(default=100, le=500),
):
    """
    Upcoming earnings announcements from NSE event calendar.
    No auth required. 1-hour cache.
    """
    _cache_key = f"public:earnings:{days}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    events = []
    db = _get_db_session()
    if db:
        try:
            from data_pipeline.models import UpcomingEarnings, Stock
            cutoff = date.today() + timedelta(days=days)
            today = date.today()

            rows = (
                db.query(UpcomingEarnings, Stock)
                .outerjoin(Stock, UpcomingEarnings.ticker == Stock.ticker)
                .filter(UpcomingEarnings.event_date >= today)
                .filter(UpcomingEarnings.event_date <= cutoff)
                .order_by(UpcomingEarnings.event_date.asc())
                .limit(limit)
                .all()
            )

            for ue, stock in rows:
                display = ue.ticker.replace(".NS", "").replace(".BO", "")
                days_away = (ue.event_date - today).days
                events.append({
                    "ticker": ue.ticker,
                    "display_ticker": display,
                    "company_name": (stock.company_name if stock else display),
                    "sector": (stock.sector if stock else None),
                    "event_date": ue.event_date.isoformat(),
                    "event_type": ue.event_type or "Financial Results",
                    "purpose": ue.purpose or "",
                    "days_away": days_away,
                })
        except Exception as e:
            logger.warning(f"earnings-calendar query failed: {e}")
        finally:
            _safe_close(db)

    result = {
        "total": len(events),
        "window_days": days,
        "by_date": _group_earnings_by_date(events),
        "events": events,
    }
    cache.set(_cache_key, result, ttl=3600)
    return result


def _group_earnings_by_date(events: list) -> list:
    """Group events by date for calendar view."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for e in events:
        grouped[e["event_date"]].append(e)
    return [
        {"date": d, "count": len(items), "tickers": [e["display_ticker"] for e in items[:10]]}
        for d, items in sorted(grouped.items())
    ]

# ---------------------------------------------------------------
# Pre-built Screens � public landing pages (SEO)
# ---------------------------------------------------------------

SCREENS: dict[str, dict] = {
    "high-roce": {
        "name": "High ROCE Stocks",
        "description": "Indian stocks with ROCE > 20% � capital-efficient businesses",
        "h1": "High ROCE Stocks (ROCE > 20%)",
        "intro": "Companies generating 20%+ return on capital employed. High ROCE indicates efficient capital allocation and pricing power.",
        "filter": lambda s: (s.get("roce") or 0) >= 20,
        "sort_key": "roce",
        "sort_desc": True,
    },
    "low-pe-quality": {
        "name": "Low P/E Quality Stocks",
        "description": "P/E < 20 + Piotroski F-Score >= 7 � value with quality",
        "h1": "Low P/E Quality Stocks (P/E < 20, F-Score \u2265 7)",
        "intro": "Combines value (low P/E) with quality (high Piotroski F-Score). Filters out value traps by requiring strong fundamentals.",
        "filter": lambda s: ((s.get("pe_ratio") or 999) < 20) and ((s.get("piotroski") or 0) >= 7),
        "sort_key": "score",
        "sort_desc": True,
    },
    "debt-free": {
        "name": "Debt-Free Stocks",
        "description": "Indian stocks with Debt-to-Equity < 0.2 � minimal leverage risk",
        "h1": "Debt-Free Indian Stocks (D/E < 0.2)",
        "intro": "Companies with virtually no debt on the balance sheet. Lower financial risk during downturns and rising rate environments.",
        "filter": lambda s: (s.get("de_ratio") is not None) and (s.get("de_ratio") < 0.2),
        "sort_key": "score",
        "sort_desc": True,
    },
    "undervalued-quality": {
        "name": "Undervalued Quality Stocks",
        "description": "YieldIQ Score >= 70 + Margin of Safety >= 20% � high-quality undervalued",
        "h1": "Undervalued Quality Stocks (Score \u2265 70, MoS \u2265 20%)",
        "intro": "Stocks with strong YieldIQ quality scores trading at meaningful discounts to fair value.",
        "filter": lambda s: ((s.get("score") or 0) >= 70) and ((s.get("mos") or 0) >= 20),
        "sort_key": "mos",
        "sort_desc": True,
    },
    "wide-moat": {
        "name": "Wide Moat Stocks",
        "description": "Indian companies with sustainable competitive advantages",
        "h1": "Wide Moat Stocks (Indian Equities)",
        "intro": "Companies with durable competitive advantages \u2014 brand pricing power, network effects, switching costs, or scale economies.",
        "filter": lambda s: s.get("moat") == "Wide",
        "sort_key": "score",
        "sort_desc": True,
    },
    "high-piotroski": {
        "name": "High Piotroski F-Score Stocks",
        "description": "Indian stocks with Piotroski F-Score 8 or 9 � top financial strength",
        "h1": "High Piotroski F-Score Stocks (F-Score 8-9)",
        "intro": "Joseph Piotroski\'s 9-point fundamental quality score. Companies scoring 8-9 show consistent profitability, efficiency, and balance sheet strength.",
        "filter": lambda s: (s.get("piotroski") or 0) >= 8,
        "sort_key": "piotroski",
        "sort_desc": True,
    },
}


@router.get("/screens")
async def list_screens():
    """List all available pre-built screens."""
    return [
        {
            "slug": slug,
            "name": cfg["name"],
            "description": cfg["description"],
        }
        for slug, cfg in SCREENS.items()
    ]


@router.get("/screens/{slug}")
async def get_screen(slug: str, limit: int = Query(default=50, le=200)):
    """
    Run a pre-built screen against the analysis cache.
    No auth required. 30-min cache.
    """
    if slug not in SCREENS:
        raise HTTPException(status_code=404, detail=f"Screen \'{slug}\' not found")

    _cache_key = f"public:screen:{slug}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    cfg = SCREENS[slug]
    candidates = []

    # Scan analysis cache for matching tickers
    for key in list(cache._store.keys()):
        if not key.startswith("analysis:") or ".NS" not in key:
            continue
        val = cache.get(key)
        if not val or not hasattr(val, "valuation"):
            continue
        v = val.valuation
        q = val.quality
        c = val.company
        # Compute pe_ratio if possible
        pe_ratio = None
        try:
            if v.current_price and getattr(v, "eps_ttm", None):
                pe_ratio = v.current_price / v.eps_ttm
        except Exception:
            pass

        stock_data = {
            "ticker": val.ticker,
            "display_ticker": val.ticker.replace(".NS", "").replace(".BO", ""),
            "company_name": c.company_name,
            "sector": c.sector,
            "current_price": round(v.current_price, 2),
            "fair_value": round(v.fair_value, 2),
            "mos": round(v.margin_of_safety, 1),
            "verdict": v.verdict,
            "score": q.yieldiq_score,
            "grade": q.grade,
            "moat": q.moat,
            "piotroski": q.piotroski_score,
            "roe": round(q.roe, 2) if q.roe else None,
            "roce": round(q.roce, 2) if getattr(q, "roce", None) else None,
            "de_ratio": round(q.de_ratio, 2) if q.de_ratio else None,
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
            "market_cap": c.market_cap,
        }
        if cfg["filter"](stock_data):
            candidates.append(stock_data)

    # Sort
    candidates.sort(key=lambda x: x.get(cfg["sort_key"]) or 0, reverse=cfg["sort_desc"])
    candidates = candidates[:limit]

    result = {
        "slug": slug,
        "name": cfg["name"],
        "description": cfg["description"],
        "h1": cfg["h1"],
        "intro": cfg["intro"],
        "total": len(candidates),
        "stocks": candidates,
    }
    # PERF (egress): bumped 1800s -> 7200s (2h). Pre-built screens are
    # rebuilt on CACHE_VERSION bumps and the underlying analysis_cache
    # only refreshes every 24h on the hot path; 30 min was wastefully
    # short for a public-tier listing endpoint.
    cache.set(_cache_key, result, ttl=7200)
    # PERF (egress): wrap with Vercel-edge Cache-Control so repeat
    # /public/screens/{slug} hits are absorbed by the CDN. SEO landing
    # surfaces hit this hot - caching at the edge for 15 min with SWR=1h
    # eliminates the bulk of backend requests on this path.
    return _cached_json(result, s_maxage=900, swr=3600)


# ═══════════════════════════════════════════════════════════════
# Risk stats — drawdown, volatility, beta, returns
# ═══════════════════════════════════════════════════════════════

@router.get("/dupont/{ticker}")
async def get_dupont_analysis(ticker: str, years: int = Query(default=5, ge=3, le=10)):
    """
    DuPont decomposition of ROE over the last N years.

    ROE = Net Margin x Asset Turnover x Equity Multiplier
        = (PAT / Revenue) x (Revenue / Assets) x (Assets / Equity)

    Returns historical decomposition so user can see which lever
    (profitability, efficiency, or leverage) drives the return.

    No auth. 24-hour cache.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:dupont:{clean}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    db = _get_db_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        from data_pipeline.models import Financials, Stock
        from datetime import date as _date

        cutoff = _date.today().replace(year=_date.today().year - years)
        rows = (
            db.query(Financials)
            .filter(Financials.ticker == clean)
            .filter(Financials.period_type == "annual")
            .filter(Financials.period_end >= cutoff)
            .order_by(Financials.period_end.desc())
            .limit(years)
            .all()
        )

        if not rows:
            raise HTTPException(status_code=404, detail=f"No financial history for {clean}")

        # Company info
        stock = db.query(Stock).filter(Stock.ticker == clean).first()
        company_name = stock.company_name if stock else clean

        decomposition = []
        for r in rows:
            revenue = r.revenue or 0
            pat = r.pat or 0
            total_assets = r.total_assets or 0
            total_equity = r.total_equity or 0

            if revenue > 0 and total_assets > 0 and total_equity > 0:
                net_margin = pat / revenue
                asset_turnover = revenue / total_assets
                equity_multiplier = total_assets / total_equity
                roe = net_margin * asset_turnover * equity_multiplier

                # Also compute ROA as a sanity check
                roa = pat / total_assets if total_assets > 0 else 0

                decomposition.append({
                    "period_end": r.period_end.isoformat(),
                    "fy": f"FY{r.period_end.year}" if r.period_end.month <= 3 else f"FY{r.period_end.year + 1}",
                    "revenue_cr": round(revenue / 1e7, 1),
                    "pat_cr": round(pat / 1e7, 1),
                    "total_assets_cr": round(total_assets / 1e7, 1),
                    "total_equity_cr": round(total_equity / 1e7, 1),
                    "net_margin_pct": round(net_margin * 100, 2),
                    "asset_turnover": round(asset_turnover, 2),
                    "equity_multiplier": round(equity_multiplier, 2),
                    "roe_pct": round(roe * 100, 2),
                    "roa_pct": round(roa * 100, 2),
                })

        if not decomposition:
            raise HTTPException(status_code=404, detail=f"Insufficient financial data for {clean}")

        # Sort chronologically for display (oldest first)
        decomposition.sort(key=lambda x: x["period_end"])

        # Compute trend commentary
        commentary = _dupont_commentary(decomposition)

        result = {
            "ticker": ticker,
            "display_ticker": clean,
            "company_name": company_name,
            "years": len(decomposition),
            "periods": decomposition,
            "latest": decomposition[-1] if decomposition else None,
            "commentary": commentary,
        }
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"dupont failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="DuPont analysis failed")
    finally:
        _safe_close(db)


def _dupont_commentary(periods: list[dict]) -> str:
    """Generate plain-English commentary on DuPont trends."""
    if len(periods) < 2:
        return ""

    latest = periods[-1]
    oldest = periods[0]

    margin_delta = latest["net_margin_pct"] - oldest["net_margin_pct"]
    turnover_delta = latest["asset_turnover"] - oldest["asset_turnover"]
    leverage_delta = latest["equity_multiplier"] - oldest["equity_multiplier"]
    roe_delta = latest["roe_pct"] - oldest["roe_pct"]

    parts: list[str] = []

    if roe_delta > 1:
        parts.append(f"ROE improved by {roe_delta:.1f} pp over {len(periods)} years.")
    elif roe_delta < -1:
        parts.append(f"ROE declined by {abs(roe_delta):.1f} pp over {len(periods)} years.")
    else:
        parts.append(f"ROE stable at ~{latest['roe_pct']:.0f}%.")

    # Dominant driver
    drivers = []
    if abs(margin_delta) > 1:
        dir_ = "improving" if margin_delta > 0 else "declining"
        drivers.append(f"net margin {dir_} ({oldest['net_margin_pct']:.1f}% \u2192 {latest['net_margin_pct']:.1f}%)")
    if abs(turnover_delta) > 0.1:
        dir_ = "improving" if turnover_delta > 0 else "declining"
        drivers.append(f"asset turnover {dir_} ({oldest['asset_turnover']:.2f}x \u2192 {latest['asset_turnover']:.2f}x)")
    if abs(leverage_delta) > 0.2:
        dir_ = "rising" if leverage_delta > 0 else "falling"
        drivers.append(f"leverage {dir_} ({oldest['equity_multiplier']:.2f}x \u2192 {latest['equity_multiplier']:.2f}x)")

    if drivers:
        parts.append("Driven by " + ", ".join(drivers) + ".")

    # High leverage warning
    if latest["equity_multiplier"] > 4:
        parts.append("High financial leverage (equity multiplier > 4x) amplifies returns but also risk.")

    return " ".join(parts)


@router.get("/news/{ticker}")
async def get_ticker_news(ticker: str, days: int = Query(default=14, ge=1, le=60)):
    """
    Combined news + BSE filings for a single ticker.
    No auth, 1-hour cache.
    Returns up to 30 items sorted by recency.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:news:{clean}:{days}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from backend.services.news_service import fetch_all_news_for_ticker, summarize_filings
        items = fetch_all_news_for_ticker(clean, days=days)
        ai_summary = summarize_filings(items, max_items=5) if items else None
        result = {
            "ticker": ticker,
            "display_ticker": clean,
            "count": len(items),
            "items": items[:30],
            "ai_summary": ai_summary,
        }
        cache.set(_cache_key, result, ttl=3600)
        return result
    except Exception as e:
        logger.warning(f"news fetch failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="News unavailable")


@router.get("/news")
async def get_news_feed(days: int = Query(default=7, ge=1, le=30), limit: int = Query(default=50, le=100)):
    """
    Aggregated BSE corporate filings feed (latest across all stocks).
    No auth, 30-min cache.
    """
    _cache_key = f"public:news-feed:{days}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        # PERF (egress): edge-cache repeat hits via CDN.
        return _cached_json(cached, s_maxage=900, swr=3600)

    try:
        from backend.services.news_service import fetch_bse_filings
        items = fetch_bse_filings(ticker=None, days=days, limit=limit)
        result = {
            "count": len(items),
            "items": items,
        }
        # PERF (egress): bumped 1800s -> 7200s (2h) - BSE filings update
        # at most a few times per day; 30 min was wastefully short.
        cache.set(_cache_key, result, ttl=7200)
        return _cached_json(result, s_maxage=900, swr=3600)
    except Exception as e:
        logger.warning(f"news feed failed: {e}")
        raise HTTPException(status_code=500, detail="News feed unavailable")


@router.get("/backtest/screen/{slug}")
async def backtest_screen_endpoint(
    slug: str,
    years: int = Query(default=3, ge=1, le=5),
    rebalance: str = Query(default="quarterly", pattern="^(monthly|quarterly|yearly)$"),
):
    """
    Backtest the CURRENT constituents of a pre-built screen.
    No auth, 24-hour cache.

    Answers: "The kinds of stocks this filter picks — how have
    they done over the last N years vs Nifty?"

    Note: NOT a true rolling backtest (which would re-run the filter
    at each historical date). Survivorship bias present — disclosed to user.
    """
    if slug not in SCREENS:
        raise HTTPException(status_code=404, detail=f"Screen '{slug}' not found")

    rebalance_days = {"monthly": 21, "quarterly": 63, "yearly": 252}[rebalance]

    _cache_key = f"public:backtest:{slug}:{years}:{rebalance}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    # Get current screen constituents
    screen_data = await get_screen(slug, limit=50)
    stocks = screen_data.get("stocks", [])
    if not stocks:
        raise HTTPException(status_code=503, detail="Screen has no current constituents (cache warming)")

    tickers = [s["ticker"] for s in stocks]

    try:
        from backend.services.backtest_service import backtest_tickers
        result = backtest_tickers(
            tickers=tickers,
            years=years,
            rebalance_days=rebalance_days,
            include_benchmark=True,
        )
        if result.get("error"):
            raise HTTPException(status_code=503, detail=result["error"])

        result["screen_slug"] = slug
        result["screen_name"] = SCREENS[slug]["name"]
        result["constituents"] = [
            {"ticker": s["ticker"], "display_ticker": s["display_ticker"], "company_name": s["company_name"]}
            for s in stocks[:20]
        ]
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"backtest failed for {slug}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Backtest computation failed")


@router.get("/technicals/{ticker}")
async def get_technicals_endpoint(ticker: str, days: int = Query(default=365, ge=60, le=730)):
    """
    Technical indicators (SMA, RSI, MACD, Bollinger) from Parquet history.

    Factual reference data, not buy/sell signals.
    No auth, 1-hour cache.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:technicals:{clean}:{days}"
    cached = cache.get(_cache_key)
    if cached is not None:
        # Existing cache entries populated before the NaN sanitization
        # may still contain NaN/Inf — sanitize on read so a stale cache
        # doesn't 500 the encoder.
        return _nan_to_none(cached)

    try:
        from data_pipeline.nse_prices.db_integration import get_technical_indicators
        result = get_technical_indicators(clean, days=days)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No price history for {clean}")
        result["ticker"] = ticker
        # NaN/Inf from pandas (insufficient history → SMA/RSI undefined,
        # MACD div-by-zero on flat series, etc.) is not JSON-compliant
        # and explodes Starlette's encoder. Coerce before caching so
        # both fresh + cached responses are clean.
        result = _nan_to_none(result)
        cache.set(_cache_key, result, ttl=3600)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"technicals failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="Technical indicators unavailable")


@router.get("/risk-stats/{ticker}")
async def get_risk_stats_endpoint(ticker: str, years: int = Query(default=3, ge=1, le=10)):
    """
    Risk statistics from Parquet price history.
    No auth required. 24-hour cache.

    Returns volatility, max drawdown, beta vs Nifty, returns, etc.
    """
    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")
    _cache_key = f"public:risk-stats:{clean}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        # Sanitize on read too: existing cache entries populated before
        # this fix may still contain NaN/Inf and would 500 the encoder.
        return _nan_to_none(cached)

    try:
        from data_pipeline.nse_prices.db_integration import get_risk_stats
        result = get_risk_stats(clean, benchmark_ticker="NIFTYBEES", years=years)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No price history for {clean}")
        result["ticker"] = ticker
        # Belt-and-suspenders: root cause fixed at compute site, but
        # defend the JSON encoder from any future regression that
        # reintroduces NaN/Inf (div-by-zero, empty .mean()/.std(), etc.)
        # See Sentry PYTHON-FASTAPI-6V.
        result = _nan_to_none(result)
        cache.set(_cache_key, result, ttl=86400)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"risk-stats failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="Risk stats unavailable")


@router.get("/price-history/{ticker}")
async def get_price_history_endpoint(
    ticker: str,
    start: str | None = Query(default=None, description="YYYY-MM-DD, defaults to 10Y ago"),
    end: str | None = Query(default=None, description="YYYY-MM-DD, defaults to today"),
):
    """Long-range OHLC price history spanning PG live table and Parquet archive.

    Unlike ``/technicals`` which reads only the per-ticker Parquet cache,
    this endpoint unions the authoritative PG ``daily_prices`` table
    (2016→today) with the Parquet archive populated by Phase B
    (2004-2015). Use this for 10Y+ charts.

    No auth. 1-hour cache.
    """
    from datetime import date as _date, timedelta as _td

    ticker = ticker.upper().strip()
    clean = ticker.replace(".NS", "").replace(".BO", "")

    # Sensible defaults — 10Y window to today
    if not end:
        end = _date.today().isoformat()
    if not start:
        start = (_date.today() - _td(days=365 * 10)).isoformat()

    _cache_key = f"public:price-history:{clean}:{start}:{end}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    try:
        from backend.services.price_history_service import get_price_history
        df = get_price_history(clean, start=start, end=end)
    except Exception as e:
        logger.warning(f"price-history failed for {clean}: {e}")
        raise HTTPException(status_code=500, detail="Price history unavailable")

    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No price history for {clean}")

    out = {
        "ticker": ticker,
        "start": start,
        "end": end,
        "rows": int(len(df)),
        "series": [
            {
                "date": (r["trade_date"].isoformat() if hasattr(r["trade_date"], "isoformat") else str(r["trade_date"])),
                "open": float(r["open_price"]) if r.get("open_price") is not None else None,
                "high": float(r["high_price"]) if r.get("high_price") is not None else None,
                "low": float(r["low_price"]) if r.get("low_price") is not None else None,
                "close": float(r["close_price"]) if r.get("close_price") is not None else None,
                "volume": int(r["volume"]) if r.get("volume") else None,
            }
            for r in df.to_dict(orient="records")
        ],
    }
    cache.set(_cache_key, out, ttl=3600)
    return out


@router.get("/screener/query")
async def screener_query(
    filters: str | None = Query(
        default=None,
        description=(
            "Comma-separated filter triples in the form `field op value`. "
            "Supported ops: < > <= >= = !=. "
            "Fields: pe_ratio, pb_ratio, ev_ebitda, roe, roce, "
            "de_ratio, market_cap_cr, mos, score, sector. "
            "Example: pe_ratio<20,roce>15,market_cap_cr>1000"
        ),
    ),
    sort: str = Query(default="mos", description="Sort field (prefix with - for desc)"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Flexible public stock screener — no auth required, 5-min cache.

    Powers shareable SEO URLs like
      /api/v1/public/screener/query?filters=pe_ratio<20,roce>15
      /screen/cheap-quality     -> frontend slug -> this endpoint

    Joins ``stocks`` (name, sector, mcap) with ``ratio_history`` (latest
    annual) and ``fair_value_history`` (latest MoS) so a single query
    returns the same shape as the frontend screener table.
    """
    import re
    import hashlib

    _key_parts = (filters or "", sort, limit, offset)
    _cache_key = "public:screener:" + hashlib.sha1(
        repr(_key_parts).encode()
    ).hexdigest()
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    # ── parse filters ──────────────────────────────────────────────
    # NOTE (P0-#1 fix, 2026-04-22): fair_value_history real columns are
    # ``mos_pct`` (not ``mos``) and there is NO ``score`` column — the
    # authoritative schema is in scripts/migrate.py::create_fair_value_history
    # and backend/routers/analysis.py line 730. The previous mapping
    # pointed ``fv.mos``/``fv.score`` at non-existent columns, so EVERY
    # call to this endpoint raised ``psycopg2.errors.UndefinedColumn``
    # and returned HTTP 500 — which the frontend swallowed as
    # "No stocks match", falsely telling users no cheap-and-quality
    # stocks exist. We map ``mos`` -> ``mos_pct`` and retire ``score``
    # (confidence is the closest persisted analogue; expose it so the
    # public /screener/fields contract still has 10 fields).
    # Source of truth lives at module scope as ``SCREENER_FIELD_MAP``
    # so CI guards (test_screener_column_mapping.py) can import and
    # probe it against the live schema. Local alias kept for readability.
    _ALLOWED_FIELDS: dict[str, str] = SCREENER_FIELD_MAP
    _ALLOWED_OPS = {"<", ">", "<=", ">=", "=", "!="}
    _TRIPLE_RE = re.compile(r"^([a-z_]+)\s*(<=|>=|!=|<|>|=)\s*(.+)$", re.I)

    where_clauses: list[str] = ["s.is_active = TRUE"]
    where_params: list = []
    parsed_filters: dict[str, list[tuple[str, str]]] = {}
    if filters:
        for raw in filters.split(","):
            raw = raw.strip()
            if not raw:
                continue
            m = _TRIPLE_RE.match(raw)
            if not m:
                raise HTTPException(status_code=400, detail=f"bad filter: {raw!r}")
            field, op, val = m.group(1).lower(), m.group(2), m.group(3).strip()
            if field not in _ALLOWED_FIELDS:
                raise HTTPException(status_code=400, detail=f"unknown field: {field}")
            if op not in _ALLOWED_OPS:
                raise HTTPException(status_code=400, detail=f"bad op: {op}")
            col = _ALLOWED_FIELDS[field]
            # Cast value safely
            if field == "sector":
                where_clauses.append(f"LOWER({col}) {op} LOWER(%s)")
                where_params.append(val.strip("'\""))
            else:
                try:
                    where_params.append(float(val))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"bad numeric: {val}")
                where_clauses.append(f"{col} {op} %s")
            parsed_filters.setdefault(field, []).append((op, val))

    # ── sort order ─────────────────────────────────────────────────
    sort_col = sort.lstrip("-")
    sort_dir = "DESC" if sort.startswith("-") or sort in ("mos", "score") else "ASC"
    _SORT_MAP = {
        "mos": "fv.mos_pct DESC NULLS LAST",
        "score": "fv.confidence DESC NULLS LAST",
        "market_cap_cr": "mm.market_cap_cr DESC NULLS LAST",
        "pe_ratio": "mm.pe_ratio ASC NULLS LAST",
        "roe": "rh.roe DESC NULLS LAST",
        "roce": "rh.roce DESC NULLS LAST",
        "ticker": "s.ticker ASC",
    }
    order_by = _SORT_MAP.get(sort_col, "fv.mos_pct DESC NULLS LAST")

    # ── query ──────────────────────────────────────────────────────
    import os
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DB unavailable")

    sql = f"""
        WITH latest_ratio AS (
          -- ratio_history owns ROE / ROCE / D-E etc. It also carries
          -- pe_ratio / pb_ratio / ev_ebitda columns (see RatioHistory
          -- ORM in data_pipeline/models.py) but for screener filters we
          -- prefer the daily-fresh values from market_metrics (mm alias)
          -- so thresholds match the values rendered in result rows.
          -- This CTE therefore projects only the quality ratios that
          -- are sourced from ratio_history.
          SELECT DISTINCT ON (ticker) ticker, roe, roce, de_ratio
          FROM ratio_history
          WHERE period_type='annual'
          ORDER BY ticker, period_end DESC
        ),
        latest_mm AS (
          -- market_metrics owns market_cap_cr + pe/pb/ev-ebitda ratios.
          -- close_price lives on daily_prices. LATERAL-JOIN the latest
          -- price onto each ticker so the public contract keeps both.
          SELECT DISTINCT ON (mm.ticker)
                 mm.ticker, mm.market_cap_cr,
                 mm.pe_ratio, mm.pb_ratio, mm.ev_ebitda,
                 dp.close_price
          FROM market_metrics mm
          LEFT JOIN LATERAL (
            SELECT close_price FROM daily_prices dp2
            WHERE dp2.ticker = mm.ticker
            ORDER BY dp2.trade_date DESC
            LIMIT 1
          ) dp ON TRUE
          ORDER BY mm.ticker, mm.trade_date DESC
        ),
        latest_fv AS (
          SELECT DISTINCT ON (ticker) ticker, mos_pct, confidence, verdict, fair_value
          FROM fair_value_history
          ORDER BY ticker, date DESC
        )
        SELECT s.ticker, s.company_name, s.sector,
               mm.pe_ratio, mm.pb_ratio, mm.ev_ebitda,
               rh.roe, rh.roce, rh.de_ratio,
               mm.market_cap_cr, mm.close_price,
               fv.mos_pct AS mos, fv.confidence AS score, fv.verdict, fv.fair_value
        FROM stocks s
        LEFT JOIN latest_ratio rh ON rh.ticker = s.ticker
        LEFT JOIN latest_mm mm    ON mm.ticker = s.ticker
        LEFT JOIN latest_fv fv    ON fv.ticker = s.ticker
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """
    params = where_params + [limit, offset]

    # Defensive DB execution (P0-#1 fix 2026-04-22):
    # Historically any psycopg2 error on a new filter combination bubbled
    # as a raw 500, which the frontend swallowed into the "No stocks
    # match" empty state — making users believe no cheap-and-quality
    # stocks exist. We now translate driver-level errors into a 400 with
    # the offending filter set so (a) the frontend can show a distinct
    # "screener failed" message and (b) the error surfaces in Sentry
    # with enough context to debug. True DB-outage errors still 503.
    try:
        conn = psycopg2.connect(url)
    except Exception as _conn_exc:
        logger.warning("screener DB connect failed: %s", _conn_exc)
        raise HTTPException(status_code=503, detail="DB unavailable") from _conn_exc
    try:
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        except psycopg2.Error as _pg_exc:
            # Roll back so the connection can be reused for the count
            # query — but we're closing immediately anyway in finally.
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(
                "screener query failed (filters=%r sort=%r): %s",
                filters, sort, _pg_exc,
            )
            # pgcode 22xxx = data exception (cast/overflow), 42xxx = syntax.
            # Anything else is a genuine server problem — bubble as 500.
            _code = getattr(_pg_exc, "pgcode", "") or ""
            if _code.startswith(("22", "42")):
                raise HTTPException(
                    status_code=400,
                    detail=f"screener query rejected by DB: {_code or 'type/syntax error'}. "
                           f"Check filter values are numeric where expected.",
                ) from _pg_exc
            raise HTTPException(
                status_code=500,
                detail="screener query failed — try different filters",
            ) from _pg_exc
        # Total count — MUST dedupe the joined tables just like the main
        # query above, otherwise ratio_history (multi-period) and
        # market_metrics (multi-listing) inflate COUNT(*) 2-4×. We reuse
        # the same CTE pattern as the list query so count and list stay
        # consistent. See design note in backend/routers/screener.py.
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM ("
                f"  WITH latest_ratio AS ("
                f"    SELECT DISTINCT ON (ticker) ticker, pe_ratio, pb_ratio, "
                f"           ev_ebitda, roe, roce, de_ratio "
                f"    FROM ratio_history WHERE period_type='annual' "
                f"    ORDER BY ticker, period_end DESC"
                f"  ),"
                f"  latest_mm AS ("
                f"    SELECT DISTINCT ON (mm.ticker) mm.ticker, mm.market_cap_cr "
                f"    FROM market_metrics mm "
                f"    ORDER BY mm.ticker, mm.trade_date DESC"
                f"  ),"
                f"  latest_fv AS ("
                f"    SELECT DISTINCT ON (ticker) ticker, mos_pct, confidence, verdict, fair_value "
                f"    FROM fair_value_history ORDER BY ticker, date DESC"
                f"  )"
                f"  SELECT 1 FROM stocks s "
                f"  LEFT JOIN latest_ratio rh ON rh.ticker = s.ticker "
                f"  LEFT JOIN latest_mm mm    ON mm.ticker = s.ticker "
                f"  LEFT JOIN latest_fv fv    ON fv.ticker = s.ticker "
                f"  WHERE {' AND '.join(where_clauses)}"
                f") _sub",
                where_params,
            )
            total = cur.fetchone()[0]
        except psycopg2.Error as _pg_exc2:
            # Row query already succeeded — fall back to the returned
            # row count as a best-effort total so the user at least sees
            # their matches. Don't fail the whole request over a count.
            logger.warning("screener count query failed: %s", _pg_exc2)
            try:
                conn.rollback()
            except Exception:
                pass
            total = len(rows)
    finally:
        conn.close()

    # Coerce Decimals → float, dates → iso
    import decimal
    import datetime as _dt
    def _clean(v):
        if isinstance(v, decimal.Decimal):
            return float(v)
        if isinstance(v, (_dt.date, _dt.datetime)):
            return v.isoformat()
        return v
    out_rows = [{k: _clean(v) for k, v in r.items()} for r in rows]

    payload = {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "filters_applied": parsed_filters,
        "results": out_rows,
    }
    cache.set(_cache_key, payload, ttl=300)
    return payload


@router.get("/screener/fields")
async def screener_fields():
    """Metadata: which fields the screener accepts, with human labels."""
    return {
        "fields": [
            {"key": "pe_ratio",      "label": "P/E",                "type": "number"},
            {"key": "pb_ratio",      "label": "P/B",                "type": "number"},
            {"key": "ev_ebitda",     "label": "EV/EBITDA",          "type": "number"},
            {"key": "roe",           "label": "ROE %",              "type": "number"},
            {"key": "roce",          "label": "ROCE %",             "type": "number"},
            {"key": "de_ratio",      "label": "Debt/Equity",        "type": "number"},
            {"key": "market_cap_cr", "label": "Market Cap (Cr)",    "type": "number"},
            {"key": "mos",           "label": "Margin of Safety %", "type": "number"},
            {"key": "score",         "label": "YieldIQ Score",      "type": "number"},
            {"key": "sector",        "label": "Sector",             "type": "string"},
        ],
        "ops": ["<", ">", "<=", ">=", "=", "!="],
        "sort_keys": ["mos", "score", "market_cap_cr", "pe_ratio", "roe", "roce", "ticker"],
        "example": "pe_ratio<20,roce>15,market_cap_cr>1000",
    }


@router.get("/top-tickers")
async def get_public_top_tickers(limit: int = 500):
    """Public list of active NSE tickers sorted by market_cap_cr DESC.

    Used by the cache-warmup workflow (which runs under a service
    token that isn't in the admin allow-list) so it doesn't need
    admin privileges to fetch the warm-set.

    Read-only, non-sensitive: just a ticker list.
    """
    limit = max(1, min(int(limit), 2000))
    _key = f"public:top-tickers:{limit}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=3600, swr=14400)
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            # DISTINCT ON dedupes cross-listing rows in market_metrics
            # (same ticker on NSE+BSE → two mm rows → duplicated output).
            # See design note in backend/routers/screener.py.
            rows = sess.execute(_t(
                "WITH mm_dedup AS ("
                "  SELECT DISTINCT ON (ticker) ticker, market_cap_cr "
                "  FROM market_metrics "
                "  ORDER BY ticker, trade_date DESC"
                ") "
                "SELECT s.ticker "
                "FROM stocks s "
                "LEFT JOIN mm_dedup mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT :lim"
            ), {"lim": limit}).fetchall()
            tickers = [r[0] for r in rows if r and r[0]]
            out = {"count": len(tickers), "tickers": tickers}
            cache.set(_key, out, ttl=3600)
            return _cached_json(out, s_maxage=3600, swr=14400)
        finally:
            sess.close()
    except Exception as exc:
        logger.warning(f"public top-tickers failed: {exc}")
        return {"count": 0, "tickers": []}


@router.get("/near-52w-lows")
async def get_near_52w_lows(limit: int = 6, max_distance_pct: float = 25.0, min_score: int = 35):
    """Stocks trading close to their 52-week low with strong fundamentals.

    Factual filter — NOT a recommendation.
    - Loads the top 400 by market cap from market_metrics
    - Joins live_quotes for current price
    - Computes 52w low via Parquet (data_pipeline.nse_prices.db_integration)
    - Filters: within `max_distance_pct` of 52w low AND yieldiq_score >= min_score
    - Returns sorted by proximity to low, ascending

    Cached 1hr. Response capped at `limit`.
    """
    limit = max(1, min(int(limit), 20))
    max_distance_pct = max(0.0, min(float(max_distance_pct), 50.0))
    min_score = max(0, min(int(min_score), 100))
    _key = f"public:near-52w-lows:{limit}:{int(max_distance_pct)}:{min_score}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=300, swr=3600)

    out = {"count": 0, "stocks": [], "disclaimer": "Model estimate. Not investment advice."}
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        from data_pipeline.nse_prices.db_integration import get_52w_high_low

        sess = Session()
        try:
            # Top 400 by market cap that have an analysis_cache entry
            # (strong-fundamentals proxy — scored stocks only). Left-join
            # live_quotes for current price in one pass. DISTINCT ON
            # dedupes cross-listing duplicates in market_metrics (same
            # ticker listed on NSE+BSE → two mm rows → two result rows).
            rows = sess.execute(_t(
                "SELECT ticker, company_name, price, score FROM ("
                "  SELECT DISTINCT ON (s.ticker) "
                "         s.ticker, s.company_name, "
                "         lq.price AS price, "
                "         (ac.payload->'quality'->>'yieldiq_score')::int AS score, "
                "         COALESCE(mm.market_cap_cr, 0) AS mcap "
                "  FROM stocks s "
                "  LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "  LEFT JOIN live_quotes lq "
                "    ON lq.ticker = s.ticker OR lq.ticker = s.ticker || '.NS' "
                "  LEFT JOIN analysis_cache ac "
                "    ON ac.ticker = s.ticker OR ac.ticker = s.ticker || '.NS' "
                "  WHERE s.is_active = TRUE "
                "    AND ac.ticker IS NOT NULL "
                "    AND lq.price IS NOT NULL "
                "  ORDER BY s.ticker, COALESCE(mm.market_cap_cr, 0) DESC"
                ") t "
                "ORDER BY mcap DESC "
                "LIMIT 400"
            )).fetchall()
        finally:
            sess.close()

        candidates: list[dict] = []
        for r in rows:
            try:
                ticker = r[0]
                company = r[1] or ticker
                price = float(r[2]) if r[2] else None
                score = int(r[3]) if r[3] is not None else 0
                if price is None or price <= 0 or score < min_score:
                    continue
                clean = ticker.replace(".NS", "").replace(".BO", "")
                high_low = get_52w_high_low(clean)
                if not high_low:
                    continue
                w52_high, w52_low = high_low
                if not w52_low or w52_low <= 0:
                    continue
                distance_pct = (price - w52_low) / w52_low * 100.0
                if distance_pct > max_distance_pct:
                    continue
                candidates.append({
                    "ticker": ticker,
                    "company_name": company,
                    "price": round(price, 2),
                    "w52_low": round(float(w52_low), 2),
                    "w52_high": round(float(w52_high), 2) if w52_high else None,
                    "distance_pct": round(distance_pct, 2),
                    "yieldiq_score": score,
                })
            except Exception:
                continue

        candidates.sort(key=lambda c: c["distance_pct"])
        out = {
            "count": min(len(candidates), limit),
            "stocks": candidates[:limit],
            "disclaimer": "Factual filter based on 52-week price history + model fundamental scores. Model estimate. Not investment advice.",
        }
        cache.set(_key, out, ttl=3600)
    except Exception as exc:
        logger.warning(f"near-52w-lows failed: {exc}")
    return _cached_json(out, s_maxage=300, swr=3600)


@router.get("/lowest-pe")
async def get_lowest_pe(limit: int = 6, min_score: int = 35, max_pe: float = 60.0):
    """Stocks with the lowest P/E ratio that still pass fundamental quality.

    Factual composition — NOT a recommendation. Reads market_metrics.pe_ratio
    and joins analysis_cache.yieldiq_score for the quality filter.
    """
    limit = max(1, min(int(limit), 20))
    min_score = max(0, min(int(min_score), 100))
    max_pe = max(1.0, min(float(max_pe), 200.0))
    _key = f"public:lowest-pe:{limit}:{min_score}:{int(max_pe)}"
    cached = cache.get(_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=300, swr=3600)

    out = {"count": 0, "stocks": [], "disclaimer": "Model estimate. Not investment advice."}
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text as _t
        sess = Session()
        try:
            # DISTINCT ON (s.ticker) dedupes cross-listing duplicates:
            # market_metrics can have two rows per ticker when the same
            # company is listed on NSE+BSE (e.g. BPCL appeared twice in
            # prod before this change). Subquery wrapper so the final
            # ORDER BY pe_ratio still sorts globally after dedupe.
            rows = sess.execute(_t(
                "SELECT ticker, company_name, pe_ratio, score FROM ("
                "  SELECT DISTINCT ON (s.ticker) "
                "         s.ticker, s.company_name, "
                "         mm.pe_ratio, "
                "         (ac.payload->'quality'->>'yieldiq_score')::int AS score "
                "  FROM stocks s "
                "  JOIN market_metrics mm ON mm.ticker = s.ticker "
                "  JOIN analysis_cache ac "
                "    ON ac.ticker = s.ticker OR ac.ticker = s.ticker || '.NS' "
                "  WHERE s.is_active = TRUE "
                "    AND mm.pe_ratio IS NOT NULL "
                "    AND mm.pe_ratio > 0 "
                "    AND mm.pe_ratio <= :max_pe "
                "    AND (ac.payload->'quality'->>'yieldiq_score')::int >= :min_score "
                "  ORDER BY s.ticker, mm.pe_ratio ASC"
                ") t "
                "ORDER BY pe_ratio ASC "
                "LIMIT :lim"
            ), {"max_pe": max_pe, "min_score": min_score, "lim": limit}).fetchall()
        finally:
            sess.close()

        stocks = []
        for r in rows:
            try:
                stocks.append({
                    "ticker": r[0],
                    "company_name": r[1] or r[0],
                    "pe_ratio": round(float(r[2]), 2),
                    "yieldiq_score": int(r[3]),
                })
            except Exception:
                continue
        out = {
            "count": len(stocks),
            "stocks": stocks,
            "disclaimer": "Factual filter: lowest P/E stocks with YieldIQ score >= {0}. Model estimate. Not investment advice.".format(min_score),
        }
        cache.set(_key, out, ttl=3600)
    except Exception as exc:
        logger.warning(f"lowest-pe failed: {exc}")
    return _cached_json(out, s_maxage=300, swr=3600)


# ═══════════════════════════════════════════════════════════════
# Historical financials / ratios / peers — migration-005 tables
# ═══════════════════════════════════════════════════════════════

def _normalize_ticker(ticker: str) -> str:
    """Apply same normalization as stock-summary: upper, .NS suffix,
    alias resolution. Returns the resolved full ticker (e.g. ETERNAL.NS).
    """
    t = (ticker or "").upper().strip()
    if not t.endswith(".NS") and not t.endswith(".BO"):
        t = f"{t}.NS"
    try:
        from backend.routers.analysis import TICKER_ALIASES
        t = TICKER_ALIASES.get(t, t)
    except Exception:
        pass
    return t


def _data_unavailable_payload(ticker: str, reason: str) -> JSONResponse:
    """Consistent 503 payload when the underlying table is missing or
    the DB session can't be obtained. Used by the historical endpoints
    so the frontend gets a deterministic shape instead of a 500."""
    return JSONResponse(
        status_code=503,
        content={
            "status": "data_not_populated",
            "ticker": ticker,
            "message": "Historical data is not yet populated for this endpoint.",
            "reason": reason,
        },
        headers={
            "Cache-Control": "public, s-maxage=60, stale-while-revalidate=120",
        },
    )


@router.get("/financials/{ticker}")
async def get_historical_financials(
    ticker: str,
    period: str = Query(default="annual", pattern="^(annual|quarterly)$"),
    years: int = Query(default=10, ge=1, le=15),
):
    """
    Historical raw financials (P&L / BS / CF) from the `financials` table.
    No auth. 1-hour cache.
    """
    full_ticker = _normalize_ticker(ticker)
    clean = full_ticker.replace(".NS", "").replace(".BO", "")

    _cache_key = f"public:financials:{full_ticker}:{period}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=3600, swr=7200)

    db = _get_db_session()
    if db is None:
        return _data_unavailable_payload(full_ticker, "db_session_unavailable")

    try:
        from data_pipeline.models import Financials
        limit_rows = years if period == "annual" else years * 4
        rows = (
            db.query(Financials)
            .filter(Financials.ticker == clean)
            .filter(Financials.period_type == period)
            .order_by(Financials.period_end.desc())
            .limit(limit_rows)
            .all()
        )

        if not rows:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "ticker": full_ticker,
                    "message": f"No {period} financial history for {clean}",
                },
                headers={"Cache-Control": "public, s-maxage=300, stale-while-revalidate=600"},
            )

        currency = rows[0].currency or "INR"
        periods = []
        for r in rows:
            periods.append({
                "period_end": r.period_end.isoformat() if r.period_end else "",
                "period_type": r.period_type or period,
                "revenue": r.revenue,
                "ebitda": r.ebitda,
                "ebit": r.ebit,
                "pat": r.pat,
                "eps_diluted": r.eps_diluted,
                "cfo": r.cfo,
                "capex": r.capex,
                "free_cash_flow": r.free_cash_flow,
                "total_assets": r.total_assets,
                "total_equity": r.total_equity,
                "total_debt": r.total_debt,
                "cash_and_equivalents": r.cash_and_equivalents,
                "shares_outstanding": r.shares_outstanding,
                "roe": r.roe,
                "roa": r.roa,
                "debt_to_equity": r.debt_to_equity,
                "gross_margin": r.gross_margin,
                "operating_margin": r.operating_margin,
                "net_margin": r.net_margin,
                "fcf_margin": r.fcf_margin,
                "revenue_growth_yoy": r.revenue_growth_yoy,
                "pat_growth_yoy": r.pat_growth_yoy,
            })

        result = {
            "ticker": full_ticker,
            "currency": currency,
            "periods": periods,
        }
        cache.set(_cache_key, result, ttl=3600)
        return _cached_json(result, s_maxage=3600, swr=7200)
    except Exception as exc:
        logger.warning(f"financials history failed for {clean}: {exc}", exc_info=True)
        return _data_unavailable_payload(full_ticker, "query_failed")
    finally:
        _safe_close(db)


@router.get("/ratios-history/{ticker}")
async def get_ratios_history(
    ticker: str,
    years: int = Query(default=10, ge=1, le=15),
    period: str = Query(default="annual", pattern="^(annual|quarterly)$"),
):
    """
    Time-series derived ratios from the `ratio_history` table.
    No auth. 1-hour cache.
    """
    full_ticker = _normalize_ticker(ticker)
    clean = full_ticker.replace(".NS", "").replace(".BO", "")

    _cache_key = f"public:ratios-history:{full_ticker}:{period}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=3600, swr=7200)

    db = _get_db_session()
    if db is None:
        return _data_unavailable_payload(full_ticker, "db_session_unavailable")

    try:
        from data_pipeline.models import RatioHistory
        limit_rows = years if period == "annual" else years * 4
        rows = (
            db.query(RatioHistory)
            .filter(RatioHistory.ticker == clean)
            .filter(RatioHistory.period_type == period)
            .order_by(RatioHistory.period_end.desc())
            .limit(limit_rows)
            .all()
        )

        if not rows:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "ticker": full_ticker,
                    "message": f"No {period} ratio history for {clean}",
                },
                headers={"Cache-Control": "public, s-maxage=300, stale-while-revalidate=600"},
            )

        periods = []
        for r in rows:
            periods.append({
                "period_end": r.period_end.isoformat() if r.period_end else "",
                "period_type": r.period_type or period,
                "roe": r.roe,
                "roce": r.roce,
                "roa": r.roa,
                "de_ratio": r.de_ratio,
                "debt_ebitda": r.debt_ebitda,
                "interest_cov": r.interest_cov,
                "gross_margin": r.gross_margin,
                "operating_margin": r.operating_margin,
                "net_margin": r.net_margin,
                "fcf_margin": r.fcf_margin,
                "revenue_yoy": r.revenue_yoy,
                "ebitda_yoy": r.ebitda_yoy,
                "pat_yoy": r.pat_yoy,
                "fcf_yoy": r.fcf_yoy,
                "pe_ratio": r.pe_ratio,
                "pb_ratio": r.pb_ratio,
                "ev_ebitda": r.ev_ebitda,
                "dividend_yield": r.dividend_yield,
                "market_cap_cr": r.market_cap_cr,
                "current_ratio": r.current_ratio,
                "asset_turnover": r.asset_turnover,
            })

        result = {"ticker": full_ticker, "periods": periods}
        cache.set(_cache_key, result, ttl=3600)
        return _cached_json(result, s_maxage=3600, swr=7200)
    except Exception as exc:
        logger.warning(f"ratios-history failed for {clean}: {exc}", exc_info=True)
        return _data_unavailable_payload(full_ticker, "query_failed")
    finally:
        _safe_close(db)


@router.get("/peers/{ticker}")
async def get_peers(
    ticker: str,
    limit: int = Query(default=5, ge=1, le=10),
):
    """
    Peer group from the `peer_groups` table, enriched with each peer's
    latest analysis cache snapshot (company_name, fair_value, score, etc.)
    and a ratio_history fallback for pe_ratio / roe when analysis_cache
    is absent.

    No auth. 30-min in-memory cache; edge s-maxage=900, swr=3600.
    """
    full_ticker = _normalize_ticker(ticker)
    clean = full_ticker.replace(".NS", "").replace(".BO", "")

    _cache_key = f"public:peers:{full_ticker}:{limit}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=900, swr=3600)

    db = _get_db_session()
    if db is None:
        return _data_unavailable_payload(full_ticker, "db_session_unavailable")

    try:
        from data_pipeline.models import PeerGroup, RatioHistory
        rows = (
            db.query(PeerGroup)
            .filter(PeerGroup.ticker == clean)
            .order_by(PeerGroup.rank.asc())
            .limit(limit)
            .all()
        )

        if not rows:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "ticker": full_ticker,
                    "message": f"No peers computed for {clean}",
                },
                headers={"Cache-Control": "public, s-maxage=300, stale-while-revalidate=600"},
            )

        peers_out: list[dict] = []
        for peer in rows:
            peer_clean = (peer.peer_ticker or "").replace(".NS", "").replace(".BO", "")
            peer_full = peer.peer_ticker if peer.peer_ticker and (
                peer.peer_ticker.endswith(".NS") or peer.peer_ticker.endswith(".BO")
            ) else f"{peer_clean}.NS"

            # Primary enrichment: in-memory analysis cache
            company_name = None
            fair_value = None
            current_price = None
            mos = None
            verdict = None
            score = None
            moat = None
            roe = None
            pe_ratio = None

            analysis = cache.get(f"analysis:{peer_full}")
            if analysis is None:
                # Tier-2: persistent analysis_cache
                try:
                    from backend.services import analysis_cache_service
                    from backend.models.responses import AnalysisResponse
                    payload = analysis_cache_service.get_cached(peer_full)
                    if payload:
                        analysis = AnalysisResponse(**payload)
                except Exception:
                    analysis = None

            if analysis is not None and hasattr(analysis, "valuation"):
                v = analysis.valuation
                q = analysis.quality
                c = analysis.company
                company_name = c.company_name
                fair_value = round(v.fair_value, 2) if v.fair_value is not None else None
                current_price = round(v.current_price, 2) if v.current_price is not None else None
                mos = round(v.margin_of_safety, 1) if v.margin_of_safety is not None else None
                verdict = v.verdict
                score = q.yieldiq_score
                moat = q.moat
                roe = round(q.roe, 2) if q.roe is not None else None
                # pe_ratio not directly on QualityOutput — derive from price/EPS if available
                try:
                    eps_ttm = getattr(v, "eps_ttm", None)
                    if current_price and eps_ttm:
                        pe_ratio = round(current_price / eps_ttm, 2)
                except Exception:
                    pe_ratio = None

            # Fallback: pull pe_ratio / roe from latest ratio_history row
            if pe_ratio is None or roe is None:
                try:
                    rh = (
                        db.query(RatioHistory)
                        .filter(RatioHistory.ticker == peer_clean)
                        .filter(RatioHistory.period_type == "annual")
                        .order_by(RatioHistory.period_end.desc())
                        .first()
                    )
                    if rh is not None:
                        if pe_ratio is None:
                            pe_ratio = rh.pe_ratio
                        if roe is None:
                            roe = rh.roe
                except Exception:
                    pass

            peers_out.append({
                "peer_ticker": peer.peer_ticker,
                "rank": peer.rank,
                "sector": peer.sector,
                "sub_sector": peer.sub_sector,
                "mcap_ratio": peer.mcap_ratio,
                "company_name": company_name or peer_clean,
                "fair_value": fair_value,
                "current_price": current_price,
                "margin_of_safety": mos,
                "verdict": verdict,
                "score": score,
                "moat": moat,
                "roe": roe,
                "pe_ratio": pe_ratio,
            })

        result = {"ticker": full_ticker, "peers": peers_out}
        cache.set(_cache_key, result, ttl=1800)
        return _cached_json(result, s_maxage=900, swr=3600)
    except Exception as exc:
        logger.warning(f"peers failed for {clean}: {exc}", exc_info=True)
        return _data_unavailable_payload(full_ticker, "query_failed")
    finally:
        _safe_close(db)


# ---------------------------------------------------------------
# IPO calendar — public endpoint
# ---------------------------------------------------------------
# NOTE: This is a curated stub list. There is no `ipos` table in
# the pipeline schema yet. Replace the in-memory list with a real
# DB query once an IPO ingestion job is in place (proposed: scrape
# NSE/BSE upcoming-issues page nightly into a new `ipos` table).
# Until then this gives the SEO surface a stable shape to render.

_IPO_STUB: list[dict] = [
    # ── Upcoming ──────────────────────────────────────────────
    {
        "symbol": "NSDL", "company_name": "National Securities Depository Ltd",
        "issue_size_cr": 4500.0, "price_band_min": 760.0, "price_band_max": 800.0,
        "ipo_open_date": "2026-04-28", "ipo_close_date": "2026-04-30",
        "listing_date": None, "status": "upcoming", "exchange": "NSE",
        "sector": "Financial Services",
    },
    {
        "symbol": "TATACAP", "company_name": "Tata Capital Ltd",
        "issue_size_cr": 15000.0, "price_band_min": 310.0, "price_band_max": 326.0,
        "ipo_open_date": "2026-05-05", "ipo_close_date": "2026-05-07",
        "listing_date": None, "status": "upcoming", "exchange": "NSE",
        "sector": "Financial Services",
    },
    {
        "symbol": "LGELECT", "company_name": "LG Electronics India Ltd",
        "issue_size_cr": 8500.0, "price_band_min": 1080.0, "price_band_max": 1108.0,
        "ipo_open_date": "2026-05-12", "ipo_close_date": "2026-05-14",
        "listing_date": None, "status": "upcoming", "exchange": "NSE",
        "sector": "Consumer Durables",
    },
    {
        "symbol": "PHYSICSWALLAH", "company_name": "PhysicsWallah Ltd",
        "issue_size_cr": 4600.0, "price_band_min": 103.0, "price_band_max": 109.0,
        "ipo_open_date": "2026-05-18", "ipo_close_date": "2026-05-20",
        "listing_date": None, "status": "upcoming", "exchange": "NSE",
        "sector": "Education",
    },
    {
        "symbol": "ZEPTO", "company_name": "Kiranakart Technologies (Zepto) Ltd",
        "issue_size_cr": 6800.0, "price_band_min": 0.0, "price_band_max": 0.0,
        "ipo_open_date": "2026-06-02", "ipo_close_date": "2026-06-04",
        "listing_date": None, "status": "upcoming", "exchange": "NSE",
        "sector": "Consumer Internet",
    },
    # ── Recent (already listed) ───────────────────────────────
    {
        "symbol": "SWIGGY", "company_name": "Swiggy Ltd",
        "issue_size_cr": 11327.0, "price_band_min": 371.0, "price_band_max": 390.0,
        "ipo_open_date": "2025-11-06", "ipo_close_date": "2025-11-08",
        "listing_date": "2025-11-13", "status": "recent", "exchange": "NSE",
        "sector": "Consumer Internet",
    },
    {
        "symbol": "HEXT", "company_name": "Hexaware Technologies Ltd",
        "issue_size_cr": 8750.0, "price_band_min": 674.0, "price_band_max": 708.0,
        "ipo_open_date": "2026-02-12", "ipo_close_date": "2026-02-14",
        "listing_date": "2026-02-19", "status": "recent", "exchange": "NSE",
        "sector": "IT Services",
    },
    {
        "symbol": "NTPCGREEN", "company_name": "NTPC Green Energy Ltd",
        "issue_size_cr": 10000.0, "price_band_min": 102.0, "price_band_max": 108.0,
        "ipo_open_date": "2025-11-19", "ipo_close_date": "2025-11-22",
        "listing_date": "2025-11-27", "status": "recent", "exchange": "NSE",
        "sector": "Power",
    },
    {
        "symbol": "VISHALMEGA", "company_name": "Vishal Mega Mart Ltd",
        "issue_size_cr": 8000.0, "price_band_min": 74.0, "price_band_max": 78.0,
        "ipo_open_date": "2025-12-11", "ipo_close_date": "2025-12-13",
        "listing_date": "2025-12-18", "status": "recent", "exchange": "NSE",
        "sector": "Retail",
    },
    {
        "symbol": "WAAREE", "company_name": "Waaree Energies Ltd",
        "issue_size_cr": 4321.0, "price_band_min": 1427.0, "price_band_max": 1503.0,
        "ipo_open_date": "2025-10-21", "ipo_close_date": "2025-10-23",
        "listing_date": "2025-10-28", "status": "recent", "exchange": "NSE",
        "sector": "Renewable Energy",
    },
]


@router.get("/ipos")
async def get_ipo_calendar(
    status: str = Query(default="upcoming", pattern="^(upcoming|recent|all)$"),
):
    """List of IPOs (upcoming and recently listed).

    NOTE: Returns a curated stub list — there is no IPO ingestion job
    yet. The shape is stable so frontend can render against it; swap
    the body for a real DB query once data lands.
    """
    _cache_key = f"public:ipos:{status}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    if status == "all":
        items = list(_IPO_STUB)
    else:
        items = [i for i in _IPO_STUB if i["status"] == status]

    items.sort(key=lambda x: x.get("ipo_open_date") or "")

    result = {
        "status_filter": status,
        "total": len(items),
        "ipos": items,
        "source": "curated_stub",  # caller-visible signal that this is placeholder data
    }
    cache.set(_cache_key, result, ttl=3600)
    return _cached_json(result, s_maxage=3600, swr=7200)


@router.get("/ipos/{symbol}")
async def get_ipo_detail(symbol: str):
    """Single IPO detail page payload."""
    sym = symbol.upper().strip()
    _cache_key = f"public:ipo:{sym}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    match = next((i for i in _IPO_STUB if i["symbol"].upper() == sym), None)
    if not match:
        raise HTTPException(status_code=404, detail="IPO not found")

    cache.set(_cache_key, match, ttl=3600)
    return _cached_json(match, s_maxage=3600, swr=7200)


# ---------------------------------------------------------------
# Segment revenue — public endpoint
# ---------------------------------------------------------------

@router.get("/segments/{ticker}")
async def get_segment_revenue(ticker: str, years: int = Query(default=5, ge=1, le=10)):
    """Time series of segment-level revenue parsed from XBRL `raw_data`.

    Returns a uniform shape:
        {ticker, segments: [{name, points: [{period_end, revenue_cr}]}]}

    Empty `segments` list when no segment data is found (the common
    case for companies that don't disclose segments).
    """
    clean = ticker.replace(".NS", "").replace(".BO", "").upper()
    full_ticker = clean if clean.endswith((".NS", ".BO")) else f"{clean}.NS"

    _cache_key = f"public:segments:{full_ticker}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return cached

    db = _get_db_session()
    series: dict[str, list[dict]] = {}
    if db:
        try:
            from data_pipeline.models import Financials
            from backend.services.segment_revenue_service import extract_segments

            rows = (
                db.query(Financials)
                .filter(Financials.ticker == full_ticker)
                .filter(Financials.period_type == "annual")
                .order_by(Financials.period_end.desc())
                .limit(years)
                .all()
            )

            for f in rows:
                period = f.period_end.isoformat() if f.period_end else None
                segs = extract_segments(f.raw_data, period_end=period, period_type="annual")
                for s in segs:
                    series.setdefault(s["name"], []).append({
                        "period_end": s["period_end"],
                        "revenue_cr": s["revenue_cr"],
                    })
        except Exception as exc:
            logger.warning(f"segments query failed for {full_ticker}: {exc}")
        finally:
            _safe_close(db)

    # Sort each segment's points by date ascending.
    segments_out = []
    for name, pts in series.items():
        pts_sorted = sorted(pts, key=lambda p: p.get("period_end") or "")
        segments_out.append({"name": name, "points": pts_sorted})
    segments_out.sort(key=lambda s: s["name"])

    result = {
        "ticker": full_ticker,
        "display_ticker": clean,
        "years": years,
        "segments": segments_out,
    }
    cache.set(_cache_key, result, ttl=3600)
    return _cached_json(result, s_maxage=3600, swr=7200)


# ═══════════════════════════════════════════════════════════════
# Dividend history — corporate_actions feed
# ═══════════════════════════════════════════════════════════════
import re as _re  # noqa: E402  (kept local — only used by this endpoint)

# Parses "DIVIDEND - RS 5 PER SHARE", "FINAL DIVIDEND RS.2.50/-",
# "INTERIM DIVIDEND - RE 1/-", "DIVIDEND-12.50%" etc. Captures the
# first numeric amount; percentage forms are ignored (face-value
# dependent, not safe to assume ₹10).
_DIV_AMOUNT_RE = _re.compile(
    r"(?:RS|INR|RE|\u20B9)\.?\s*([0-9]+(?:\.[0-9]+)?)",
    _re.IGNORECASE,
)


def _parse_dividend_amount(text_blob: str | None) -> float | None:
    """Extract the per-share dividend amount from an NSE corporate-action
    subject line. Returns None if no rupee amount can be parsed."""
    if not text_blob:
        return None
    m = _DIV_AMOUNT_RE.search(text_blob)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except (TypeError, ValueError):
        return None
    # Sanity bound — Indian per-share dividends rarely exceed ₹2000;
    # anything above that is almost always a misparse.
    if v <= 0 or v > 2000:
        return None
    return v


@router.get("/dividends/{ticker}")
async def get_dividend_history(
    ticker: str,
    years: int = Query(default=10, ge=1, le=25),
):
    """Dividend history for a ticker from the `corporate_actions` table.

    No auth. 6-hour edge cache + 1-hour in-memory cache — the underlying
    NSE corporate-actions feed only updates daily.
    """
    full_ticker = _normalize_ticker(ticker)
    clean = full_ticker.replace(".NS", "").replace(".BO", "")

    _cache_key = f"public:dividends:{full_ticker}:{years}"
    cached = cache.get(_cache_key)
    if cached is not None:
        return _cached_json(cached, s_maxage=21600, swr=86400)

    db = _get_db_session()
    if db is None:
        return _data_unavailable_payload(full_ticker, "db_session_unavailable")

    try:
        from data_pipeline.models import CorporateAction
        cutoff = date.today() - timedelta(days=int(years) * 366)
        rows = (
            db.query(CorporateAction)
            .filter(CorporateAction.ticker == clean)
            .filter(CorporateAction.ex_date.isnot(None))
            .filter(CorporateAction.ex_date >= cutoff)
            .order_by(CorporateAction.ex_date.desc())
            .all()
        )

        # Filter for dividend rows (NSE puts type in action_type / remarks).
        dividends: list[dict] = []
        for r in rows:
            blob = " ".join(filter(None, [
                (r.action_type or ""),
                (r.remarks or ""),
            ])).upper()
            if "DIVIDEND" not in blob:
                continue
            amount = _parse_dividend_amount(blob)
            dividends.append({
                "ex_date": r.ex_date.isoformat(),
                "amount": amount,
            })

        # Total paid over last 5 calendar years (sum of parseable amounts).
        five_yr_cutoff = date.today() - timedelta(days=5 * 366)
        total_5y: float = 0.0
        any_5y = False
        for d in dividends:
            try:
                ex_d = date.fromisoformat(d["ex_date"])
            except ValueError:
                continue
            if ex_d >= five_yr_cutoff and d["amount"] is not None:
                total_5y += float(d["amount"])
                any_5y = True

        result = {
            "ticker": full_ticker,
            "count": len(dividends),
            "total_paid_5y": round(total_5y, 2) if any_5y else None,
            "dividends": dividends,
        }
        cache.set(_cache_key, result, ttl=3600)
        return _cached_json(result, s_maxage=21600, swr=86400)
    except Exception as exc:
        logger.warning(f"dividends failed for {clean}: {exc}", exc_info=True)
        return _data_unavailable_payload(full_ticker, "query_failed")
    finally:
        _safe_close(db)


# ─────────────────────────────────────────────────────────────────
# Ticker index — slim JSON dump used by the client-side fuzzy search.
# Returns every known instrument (stocks + ETFs + MFs) with just the
# fields the search UI needs. ~90 KB uncompressed, ~20 KB gzipped.
#
# Called ONCE by the frontend build script (scripts/build_ticker_index.mjs)
# which writes the result to public/tickers.json. Not hit on every
# keystroke — keystrokes hit the bundled static JSON + Fuse.js in-browser.
# ─────────────────────────────────────────────────────────────────
@router.get("/tickers-index")
async def tickers_index():
    from datetime import datetime, timezone
    from backend.services.ticker_search import INDIAN_STOCKS, MUTUAL_FUNDS, ETFS

    tickers: list[dict] = []
    for s in INDIAN_STOCKS + ETFS + MUTUAL_FUNDS:
        t = s["ticker"]
        tickers.append({
            "ticker": t,
            "display_ticker": t.replace(".NS", "").replace(".BO", ""),
            "company_name": s["name"],
            "type": s.get("type", "stock"),
            "keywords": s.get("keywords", []),
        })
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(tickers),
        "tickers": tickers,
    }
    # Long s-maxage: this list only changes on deploys. The frontend
    # build script bakes it into public/tickers.json anyway.
    return _cached_json(payload, s_maxage=3600, swr=86400)


# ─────────────────────────────────────────────────────────────────
# Performance Retrospective (Task 12) — SCAFFOLDING endpoint.
#
# Public, no-auth, edge-cached for 1h. Returns the summary dict
# defined in retrospective_service.summarize_for_period.
#
# In the scaffolding PR this endpoint serves a HARDCODED sample
# payload so the frontend can render the layout. Phase 2 will swap
# the sample for a real DB-backed summary; the response shape is
# stable and the frontend should not need changes.
#
# Why public/anonymous: the whole point of the retrospective is
# radical transparency. Putting it behind auth defeats the trust-
# building purpose. SEBI compliance is handled by the descriptive-
# only framing + caveat, not by access control.
# ─────────────────────────────────────────────────────────────────
@router.get("/retrospective")
async def public_retrospective(
    period: str = Query("Q1FY26", description="Period label e.g. Q1FY26"),
    window: int = Query(90, ge=30, le=365, description="Outcome window in days"),
    benchmark: str = Query(
        "auto",
        description=(
            "Benchmark mode: 'auto' (sector-aware, default), "
            "'nifty500' (legacy single-benchmark), or an explicit "
            "Yahoo ticker like '^CNXIT' for a sector deep-dive."
        ),
    ),
):
    """Public Performance Retrospective summary.

    Returns the summary payload defined in
    backend.services.retrospective_service.summarize_for_period.

    The ``benchmark`` query parameter selects how the model's picks
    are compared:

      * ``auto`` (default) — each prediction is compared against its
        sector's index (Nifty IT for IT picks, Nifty Bank for banks,
        etc.). Response gains a ``sector_breakdown`` field.
      * ``nifty500`` — legacy single-benchmark behaviour. Response
        shape is byte-identical to pre-sector versions.
      * any other string — treated as an explicit ticker; useful for
        sector deep-dives like ``?benchmark=^CNXIT``.

    Wiring (Phase 2):
      • Resolve `period` label → (start_date, end_date).
      • Call summarize_for_period(...) — DB-backed when
        model_predictions_history has rows in the window.
      • is_sample=False when n_predictions > 0; True (with sample
        payload) when the table is empty (e.g. before backfill runs).
    """
    from datetime import date as _date, timedelta as _td
    from backend.services.retrospective_service import summarize_for_period

    # ── Period resolution: accept "QnFYyy" or "last90d" ─────────
    start_d, end_d = _resolve_period_label(period)

    disclaimer = (
        "Past results are not indicative of future returns. Sample "
        "size, survivorship-bias and look-ahead-bias caveats apply. "
        "See /methodology/performance for the full methodology. "
        "SEBI: descriptive only, not advisory."
    )

    try:
        payload = summarize_for_period(
            start_d, end_d, window=window, benchmark=benchmark,
        )
    except Exception as exc:
        logger.warning("summarize_for_period failed: %s", exc)
        payload = None

    if payload is None or payload.get("n_predictions", 0) == 0:
        # No real data yet — fall back to sample payload for layout
        # preview, with is_sample=True so the frontend banner shows.
        sample = {
            "period": {
                "start": start_d.isoformat(),
                "end":   end_d.isoformat(),
                "label": period,
            },
            "window_days": window,
            "mos_threshold": 30.0,
            "n_predictions": 47,
            "mean_return":   12.4,
            "median_return": 9.8,
            "hit_rate":         0.638,
            "outperform_rate":  0.553,
            "benchmark": (
                {"ticker": "auto", "return_pct": 6.2, "mode": "auto"}
                if benchmark == "auto"
                else {"ticker": "NIFTY500.NS", "return_pct": 6.2}
            ),
            "sector_breakdown": (
                [
                    {"sector": "IT Services", "benchmark_ticker": "^CNXIT",
                     "n": 8, "mean_return": 14.2,
                     "benchmark_return": 8.4, "outperform_rate": 0.625},
                    {"sector": "Banks", "benchmark_ticker": "^NSEBANK",
                     "n": 12, "mean_return": 11.0,
                     "benchmark_return": 7.1, "outperform_rate": 0.583},
                    {"sector": "Pharma", "benchmark_ticker": "^CNXPHARMA",
                     "n": 7, "mean_return": 13.8,
                     "benchmark_return": 9.5, "outperform_rate": 0.571},
                    {"sector": "FMCG", "benchmark_ticker": "^CNXFMCG",
                     "n": 6, "mean_return":  9.4,
                     "benchmark_return": 5.8, "outperform_rate": 0.667},
                    {"sector": "Auto", "benchmark_ticker": "^CNXAUTO",
                     "n": 5, "mean_return":  6.1,
                     "benchmark_return": 4.2, "outperform_rate": 0.600},
                ]
                if benchmark == "auto"
                else None
            ),
            "winners": [
                {"ticker": "POWERGRID.NS",  "return_pct": 38.2},
                {"ticker": "BHARTIARTL.NS", "return_pct": 31.7},
                {"ticker": "SUNPHARMA.NS",  "return_pct": 27.4},
                {"ticker": "ITC.NS",        "return_pct": 24.1},
                {"ticker": "HDFCBANK.NS",   "return_pct": 21.8},
            ],
            "losers": [
                {"ticker": "ZOMATO.NS",    "return_pct": -18.3},
                {"ticker": "PAYTM.NS",     "return_pct": -14.2},
                {"ticker": "VEDL.NS",      "return_pct":  -9.5},
                {"ticker": "ADANIENT.NS",  "return_pct":  -6.8},
                {"ticker": "TATASTEEL.NS", "return_pct":  -3.1},
            ],
            "is_sample": True,
            "last_updated": None,
            "disclaimer": disclaimer,
        }
        return _cached_json(sample, s_maxage=3600, swr=21600)

    # Real data path
    payload["is_sample"] = False
    payload["disclaimer"] = disclaimer
    # last_updated = max recorded_at in the window (best-effort)
    try:
        from sqlalchemy import text as _text
        from backend.services.analysis.db import _get_pipeline_session
        _s = _get_pipeline_session()
        if _s is not None:
            try:
                row = _s.execute(
                    _text(
                        "SELECT MAX(recorded_at) FROM model_predictions_history "
                        "WHERE prediction_date BETWEEN :a AND :b"
                    ),
                    {"a": start_d, "b": end_d},
                ).fetchone()
                payload["last_updated"] = (
                    row[0].isoformat() if row and row[0] else None
                )
            finally:
                _s.close()
    except Exception:
        payload["last_updated"] = None

    return _cached_json(payload, s_maxage=3600, swr=21600)


def _resolve_period_label(label: str):
    """Map 'Q1FY26' / 'Q4FY25' / 'last30d' / 'last90d' to (start, end) dates."""
    from datetime import date as _date, timedelta as _td
    label = (label or "").strip()
    if label.lower().startswith("last") and label.lower().endswith("d"):
        try:
            n = int(label[4:-1])
            today = _date.today()
            return today - _td(days=n), today
        except Exception:
            pass
    # QnFYyy (Indian fiscal year, Apr-Mar; FY label = end calendar year mod 100)
    import re
    m = re.match(r"Q([1-4])FY(\d{2})$", label.upper())
    if m:
        q = int(m.group(1))
        fy_end_yy = int(m.group(2))
        fy_end_year = 2000 + fy_end_yy
        # Q1: Apr-Jun of (fy_end_year - 1); Q4: Jan-Mar of fy_end_year
        if q == 1:
            return _date(fy_end_year - 1, 4, 1), _date(fy_end_year - 1, 6, 30)
        if q == 2:
            return _date(fy_end_year - 1, 7, 1), _date(fy_end_year - 1, 9, 30)
        if q == 3:
            return _date(fy_end_year - 1, 10, 1), _date(fy_end_year - 1, 12, 31)
        return _date(fy_end_year, 1, 1), _date(fy_end_year, 3, 31)
    # Default fallback: trailing 90 days
    today = _date.today()
    return today - _td(days=90), today



# ═══════════════════════════════════════════════════════════════
# Reverse-DCF (public, anonymous-accessible)
# ═══════════════════════════════════════════════════════════════
# Given current price as the *target*, what implied growth / margin
# is the market pricing in? Reads inputs (FCF, revenue, WACC, debt,
# cash, shares) out of the existing analysis_cache payload — never
# recomputes from raw data here, so it stays SoT-consistent with the
# forward DCF without going through analysis/service.py.
#
# Returns null on cache miss / loss-makers (frontend hides the
# panel) rather than 503'ing — this is purely additive UI.
# ───────────────────────────────────────────────────────────────
@router.get("/reverse-dcf/{ticker}")
async def get_reverse_dcf_public(ticker: str):
    ticker = ticker.upper().strip()
    if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
        ticker = f"{ticker}.NS"

    # Resolve aliases (ZOMATO.NS → ETERNAL.NS, etc.)
    try:
        from backend.routers.analysis import TICKER_ALIASES
        ticker = TICKER_ALIASES.get(ticker, ticker)
    except Exception:
        pass

    cache_key = f"public:reverse-dcf:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _cached_json(
            cached, s_maxage=600, swr=3600,
            extra_headers={"X-Source": "reverse_dcf_v1", "X-Cache": "HIT"},
        )

    # ── Pull AnalysisResponse from the SoT cache (tier-1, then DB) ─
    analysis = cache.get(f"analysis:{ticker}")
    if analysis is None or not hasattr(analysis, "valuation"):
        try:
            from backend.services import analysis_cache_service
            from backend.models.responses import AnalysisResponse
            payload = analysis_cache_service.get_cached(ticker)
            if payload:
                analysis = AnalysisResponse(**payload)
        except Exception as exc:
            logger.info(
                "reverse-dcf: analysis_cache lookup failed for %s: %s",
                ticker, exc,
            )

    if analysis is None or not hasattr(analysis, "valuation"):
        # No cached analysis → no reverse DCF. Frontend hides panel.
        return JSONResponse(
            status_code=200,
            content=None,
            headers={
                "Cache-Control": "public, s-maxage=120, stale-while-revalidate=600",
                "X-Source": "reverse_dcf_v1",
                "X-Cache": "MISS-NO-INPUTS",
            },
        )

    # Inputs: prefer computation_inputs (fresh post-v35 cache) and
    # fall back to ValuationOutput fields when the older cached
    # payload doesn't carry it. Loss-makers / data-limited tickers
    # silently degrade to None.
    valuation = analysis.valuation
    ci = getattr(analysis, "computation_inputs", None) or {}
    current_price = float(getattr(valuation, "current_price", 0) or ci.get("current_price") or 0)
    wacc = float(getattr(valuation, "wacc", 0) or ci.get("wacc") or 0)
    current_fcf = float(ci.get("fcf_ttm") or 0)
    current_revenue = float(ci.get("revenue_ttm") or 0)
    total_debt = float(ci.get("total_debt") or 0)
    total_cash = float(ci.get("total_cash") or 0)
    shares = float(ci.get("shares_outstanding") or 0)
    terminal_g = float(getattr(valuation, "terminal_growth", 0) or ci.get("terminal_growth") or 0.04)
    # PR #168: unit-mismatch guard.
    # `fcf_ttm` is stored in raw rupees (yfinance native unit, ~1e10
    # for an Indian large-cap) while `revenue_ttm` reaches us via
    # `enriched.latest_revenue` which the data pipeline normalises to
    # ₹ Crores (~1e5 for the same large-cap). Dividing them directly
    # produced absurd margin displays — TATASTEEL surfaced as
    # "8,675,878.4% margins" pre-fix (18.8e9 / 216,840 = 86,758, ×100
    # for percent rendering). Detection: a real FCF margin sits inside
    # ±50%; if the raw ratio exceeds 100x that, we're in unit-mismatch
    # territory and revenue needs the ₹Cr -> ₹ raw conversion (×1e7).
    # Renormalising `current_revenue` (rather than just `current_margin`)
    # also fixes the iso-FV margin solver inside compute_reverse_dcf
    # which divides `current_fcf` by `current_revenue` internally.
    if current_revenue > 0:
        _raw_margin = current_fcf / current_revenue
        if abs(_raw_margin) > 50.0:
            current_revenue = current_revenue * 1e7
            current_margin = current_fcf / current_revenue
        elif current_fcf != 0 and abs(_raw_margin) < 1e-4:
            current_revenue = current_revenue / 1e7
            current_margin = current_fcf / current_revenue
        else:
            current_margin = _raw_margin
    else:
        current_margin = 0.0

    historical_revenue_cagr = None
    historical_fcf_margin = None
    try:
        q = analysis.quality
        historical_revenue_cagr = (
            getattr(q, "revenue_cagr_5y", None)
            or getattr(q, "revenue_cagr_3y", None)
        )
        if historical_revenue_cagr is not None and historical_revenue_cagr > 1.0:
            # Stored as percent on some legacy payloads (e.g. 12 not 0.12)
            historical_revenue_cagr = historical_revenue_cagr / 100.0
    except Exception:
        pass

    try:
        from backend.services.reverse_dcf_service import compute_reverse_dcf
        result = compute_reverse_dcf(
            ticker=ticker,
            current_price=current_price,
            wacc=wacc,
            current_fcf=current_fcf,
            current_margin=current_margin,
            current_revenue=current_revenue,
            total_debt=total_debt,
            total_cash=total_cash,
            shares=shares,
            terminal_g=terminal_g,
            historical_revenue_cagr=historical_revenue_cagr,
            historical_fcf_margin=historical_fcf_margin,
        )
    except Exception as exc:
        logger.warning("reverse-dcf compute failed for %s: %s", ticker, exc)
        result = None

    if result is None:
        return JSONResponse(
            status_code=200,
            content=None,
            headers={
                "Cache-Control": "public, s-maxage=120, stale-while-revalidate=600",
                "X-Source": "reverse_dcf_v1",
                "X-Cache": "MISS-INSUFFICIENT",
            },
        )

    # Sanitize NaN / Inf and cache
    safe = _nan_to_none(result)
    cache.set(cache_key, safe, ttl=3600)
    return _cached_json(
        safe, s_maxage=600, swr=3600,
        extra_headers={"X-Source": "reverse_dcf_v1", "X-Cache": "MISS"},
    )
