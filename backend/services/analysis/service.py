# backend/services/analysis/service.py
# ═══════════════════════════════════════════════════════════════
# AnalysisService — the orchestrator. Imports every engine module
# (data/, screener/, models/) and composes the full AnalysisResponse.
# Pure relocation from the historical analysis_service.py monolith;
# sibling modules (constants, utils, db, narrative) provide the
# primitives this file consumes.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure project root is on path so existing imports work
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# Dashboard also needs to be on path for some utilities
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.models.responses import (
    AnalysisResponse, ValuationOutput, QualityOutput,
    InsightCards, BulkDealItem, CompanyInfo, ScenariosOutput, ScenarioCase,
    PriceLevels, ScreenerStock, RedFlag, AnalyticalNoteOutput,
    PeerCapDetails,
)
# feat/peer-cap (2026-04-27): peer-multiple sanity ceiling.
# Compares DCF FV against sector peer-median P/E + EV/EBITDA (P/B
# for banks). When DCF > 1.5× peer-implied, cap at 1.5× peer-implied
# and surface the audit trail via `peer_cap_details`.
from backend.services.peer_cap_service import compute_peer_cap as _compute_peer_cap
# PR #69: contextual disclaimer system — attaches 1–5 rule-based
# notes (premium brand / conglomerate / regulated utility / etc.)
# to every analysis payload. Purely additive, never influences FV.
from backend.services.analytical_notes import compute_notes as _compute_analytical_notes
# CACHE_VERSION is stamped into the computation_inputs snapshot so the
# audit trail records exactly which code generation produced an FV.
from backend.services.cache_service import CACHE_VERSION

# ── Import existing engines (NO rewrites) ─────────────────────
from data.collector import StockDataCollector
from data.processor import compute_metrics
from data.validator import validate_stock_data
from models.forecaster import FCFForecaster, compute_confidence_score
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal,
)
from screener.piotroski import compute_piotroski_fscore
from screener.moat_engine import compute_moat_score, apply_moat_adjustments
from screener.earnings_quality import compute_earnings_quality
from screener.valuation_crosscheck import blend_dcf_pe, compute_pe_based_iv, get_eps
from screener.valuation_model import (
    generate_valuation_summary, score_fundamentals,
)
from screener.scenarios import run_scenarios
from screener.reverse_dcf import run_reverse_dcf
from screener.fcf_yield import compute_fcf_yield_analysis
from screener.ev_ebitda import run_ev_ebitda_analysis
from screener.momentum import calculate_momentum
from config.countries import get_active_country

# Optional imports (may need streamlit mock)
try:
    from dashboard.utils.scoring import compute_yieldiq_score
except Exception:
    def compute_yieldiq_score(mos_pct, piotroski, moat_grade, rev_growth, analyst_upside=0):
        _v = max(0, min(100, (mos_pct + 40) / 80 * 40))
        _q = max(0, min(100, (piotroski / 9) * 30))
        _g = max(0, min(100, (rev_growth * 100 + 20) / 60 * 20))
        _s = max(0, min(100, analyst_upside * 10))
        _total = int(_v + _q + _g + _s)
        return {"score": max(0, min(100, _total)), "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D" if _total >= 20 else "F"}


# ── Subpackage siblings (constants/utils/db/narrative) ────
from backend.services.analysis.constants import (
    FINANCIAL_COMPANIES,
    INVENTORY_HEAVY_TICKERS,
    is_cyclical,
    COMPANY_NAME_OVERRIDES,
    _PB_MEDIANS,
    _NBFC_TICKERS,
)

# ── NBFC WACC floor ─────────────────────────────────────────────
# BAJFINANCE and peers route through the P/B financial-company
# valuation path, which means DCFEngine (and its NBFC premium at
# screener/dcf_engine.py:92-108) never runs for them. Their surfaced
# WACC therefore comes straight from models.forecaster.compute_wacc,
# a pure CAPM output with no NBFC awareness — which lands ~9.8% for
# BAJFINANCE's beta/rf/debt mix and fails canary gate 4.
#
# Fix: apply a 0.11 floor to the reported `wacc` field for every
# ticker in `_NBFC_TICKERS` after `compute_wacc` returns, but BEFORE
# the P/B vs DCF split. The floor is deliberately NOT propagated into
# `compute_financial_fair_value` (P/B valuation) — fair value stays
# identical, only the surfaced `wacc` field moves. This is a cosmetic
# correction to the reported cost of capital, not a valuation change.
NBFC_WACC_FLOOR = 0.11
from backend.services.analysis.utils import (
    _canonicalize_ticker,
    _resolve_sector,
    _get_adjusted_fcf,
    _get_financial_sub_type,
    _clamp_ev_ebitda,
    _enforce_scenario_order,
    _yf_compute_roe_from_statements,
    _normalize_pct,
    _compute_roe_fallback,
    _build_structured_flags,
    _debt_ebitda_label,
)
from backend.services.analysis.db import (
    _get_pipeline_session,
    _query_ttm_financials,
    _query_latest_annual_financials,
    _query_normalized_fcf,
    _query_shareholding,
    _query_promoter_pledge,
    _query_earnings_date,
    _query_bulk_deals,
    _fetch_roce_inputs,
    _fetch_bank_metrics_inputs,
    _fetch_current_assets,
)
from backend.services.analysis.narrative import NarrativeMixin


class TickerNotFoundError(Exception):
    """Raised when the data provider returns no data for a ticker —
    i.e. the ticker symbol is invalid, unlisted, or misspelled.
    The router maps this to HTTP 404; anything else becomes 500."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Ticker not found: {ticker}")


class AnalysisService(NarrativeMixin):
    """Orchestrates full stock analysis using existing engines."""

    def get_full_analysis(self, ticker: str) -> AnalysisResponse:
        """Public entry — validates output before returning."""
        # FIX-BUG-A (2026-04-22): bare Indian tickers (e.g. "TCS") get
        # misrouted to the US pipeline because is_indian relies on the
        # .NS/.BO suffix (see line ~1478). Normalize known Indian
        # symbols to their .NS form at the API entrypoint so downstream
        # code (sector resolve, currency, XBRL lookups) sees the
        # canonical form. Falls through unchanged for genuinely US
        # tickers (AAPL, MSFT, etc.) that aren't in the known set.
        ticker = _canonicalize_ticker(ticker)
        result = self._get_full_analysis_inner(ticker)
        try:
            from backend.services.validators import validate_analysis, log_validation
            vr = validate_analysis(result)
            log_validation(ticker, vr)
            # Attach validation metadata for frontend (optional, non-breaking)
            if vr.issues:
                # Stuff into data_issues field which is already on the response
                try:
                    existing = list(getattr(result, "data_issues", []) or [])
                    existing.extend([f"[{vr.severity}] {iss}" for iss in vr.issues])
                    result.data_issues = existing
                except Exception:
                    pass
            # FIX-TMPV-VERDICT (2026-04-22): when validators flag a critical
            # issue (e.g. TATAMOTORS→TMPV post-demerger with fv/cmp≈5.6),
            # promote the verdict to "under_review". Previously only the
            # public /stock-summary endpoint applied this gate (via
            # check_and_quarantine), so the authed /analysis endpoint
            # kept shipping the raw bad-DCF verdict to admin callers and
            # the canary harness. That caused gate-5 false positives and
            # 606 Sentry events on TMPV. Promoting verdict here keeps the
            # full response shape (admin can still see all fields + the
            # data_issues list above) but signals the state consistently
            # across all endpoints so downstream code (canary's
            # _has_no_dcf, frontend render branches) handles it correctly.
            if not vr.ok and vr.severity == "critical":
                try:
                    if getattr(result, "valuation", None) is not None:
                        result.valuation.verdict = "under_review"
                except Exception:
                    pass
        except Exception as _ve:
            import logging as _vl
            _vl.getLogger("yieldiq.validators").warning(f"Validator crashed for {ticker}: {_ve}")

        # ── Narrative AI summary (feat/ai-narrative-summary) ─────
        # One-sentence plain-English conclusion ("undervalued by X%,
        # standout strength, concern") rendered above the Prism hex.
        # Generated once per cold compute and baked into
        # AnalysisResponse.ai_summary so the cache tiers (tier-0 raw,
        # tier-1 pydantic, tier-2 Postgres analysis_cache.payload)
        # carry it forward for all warm reads. Gracefully degrades
        # to None on any failure — frontend hides the component in
        # that case.
        try:
            if not getattr(result, "ai_summary", None):
                narrative = self.generate_narrative_summary(ticker, result)
                if narrative:
                    try:
                        result.ai_summary = narrative
                    except Exception:
                        result = result.model_copy(update={"ai_summary": narrative})
        except Exception as _ne:
            import logging as _nl
            _nl.getLogger("yieldiq.ai_summary").warning(
                f"narrative summary generation crashed for {ticker}: "
                f"{type(_ne).__name__}: {_ne}"
            )

        # ── Multilingual translations (Phase 0 — review-gated) ──────
        # Dark-launched: only populates when MULTILINGUAL_SUMMARIES_ENABLED
        # is set in the environment AND native-speaker review of the
        # samples committed under docs/multilingual_samples_for_review.md
        # has signed off. Default behaviour is unchanged.
        try:
            translations = self.get_ai_summary_translations(
                ticker,
                result,
                english_summary=getattr(result, "ai_summary", None),
            )
            if translations:
                try:
                    result.ai_summary_translations = translations
                except Exception:
                    result = result.model_copy(
                        update={"ai_summary_translations": translations}
                    )
        except Exception as _me:
            import logging as _ml
            _ml.getLogger("yieldiq.ai_summary").warning(
                f"multilingual translation crashed for {ticker} "
                f"(non-fatal, English summary intact): "
                f"{type(_me).__name__}: {_me}"
            )
        return result

    def _get_full_analysis_inner(self, ticker: str) -> AnalysisResponse:
        """
        Main analysis pipeline:
        1. Fetch data (collector)
        2. Validate (validator)
        3. Compute metrics (processor)
        4. Forecast FCF (forecaster)
        5. Run DCF (dcf_engine)
        6. Run quality checks (piotroski, moat, earnings quality)
        7. Run scenarios (scenarios)
        8. Generate insights (valuation_model, reverse_dcf, etc.)
        9. Map to response model
        """
        _ts = datetime.now().isoformat()

        # ── Step 1: Fetch data ────────────────────────────────
        # Try local DB + Parquet first (~100ms). Fall back to
        # yfinance collector (~20-30s) only if local data is
        # insufficient (ticker not in DB, no Parquet file, etc).
        import time as _time
        raw = None
        _data_source = "unknown"

        try:
            from backend.services.local_data_service import assemble_local
            _local_db = _get_pipeline_session()
            if _local_db is not None:
                try:
                    raw = assemble_local(ticker, _local_db)
                    if raw is not None:
                        _data_source = "local_db_parquet"
                        import logging as _lds_log
                        _lds_log.getLogger("yieldiq.analysis").info(
                            "[%s] served from local DB+Parquet (fast path)", ticker
                        )
                finally:
                    try:
                        _local_db.close()
                    except Exception:
                        pass
        except Exception as _local_exc:
            import logging as _lds_log
            _lds_log.getLogger("yieldiq.analysis").warning(
                "[%s] local assembler EXCEPTION: %s: %s",
                ticker, type(_local_exc).__name__, _local_exc
            )

        # Fallback: yfinance collector (slow but comprehensive)
        if raw is None:
            _data_source = "yfinance"
            for _attempt in range(3):
                try:
                    collector = StockDataCollector(ticker)
                    raw = collector.get_all()
                    if raw is not None:
                        break
                except Exception:
                    pass
                if raw is None and _attempt < 2:
                    # Retry backoff between yfinance attempts. This used to
                    # block the FastAPI event loop because the enclosing
                    # `get_full_analysis` is a SYNC function called directly
                    # from async route handlers. As of PR #83 (2026-04-25
                    # health audit) every call site in
                    # `backend/routers/analysis.py` wraps this entry point
                    # in `asyncio.to_thread(...)`, so the sleep now sleeps
                    # in a worker thread and never stalls the loop. If you
                    # ever invoke `get_full_analysis` directly from an
                    # `async def` again, push it through `to_thread` first.
                    _time.sleep(3 + _attempt * 3)  # 3s, 6s delays

        # ── Step 2: Validate ──────────────────────────────────
        validation = validate_stock_data(ticker, raw)
        _raw_confidence = validation.confidence if validation else "medium"
        _confidence = _raw_confidence if _raw_confidence in ("high", "medium", "low", "unusable") else "medium"
        _data_issues = (validation.issues + validation.warnings) if validation else []

        # No data at all after 3 retries → ticker doesn't exist on any
        # data provider. Signal the router so it returns 404 instead of
        # producing an all-zeros response that the frontend mistakes
        # for a valid but-terrible stock.
        #
        # yfinance sometimes returns a `raw` dict with every identifying
        # field set to None (observed for TATAMOTORS.NS and ZOMATO.NS
        # after Yahoo 404s) — not actually None. Treat that as "not
        # found" too.
        _has_any_useful = isinstance(raw, dict) and any(
            raw.get(k) for k in (
                "currentPrice", "regularMarketPrice", "current_price",
                "shortName", "longName", "company_name", "symbol", "ticker",
            )
        )
        if raw is None or not _has_any_useful:
            raise TickerNotFoundError(ticker)

        # Raw data exists but validation vetoed running DCF (e.g. the
        # company is a bank/NBFC that needs a different model, or data
        # is too incomplete). Return a 200 with a low-confidence
        # response so the frontend can render a degraded card.
        if validation and not validation.show_dcf:
            return AnalysisResponse(
                ticker=ticker,
                company=CompanyInfo(ticker=ticker, company_name=ticker),
                valuation=ValuationOutput(
                    fair_value=0, current_price=0, margin_of_safety=0,
                    verdict="avoid", confidence_score=0, dcf_reliable=False,
                ),
                quality=QualityOutput(),
                insights=InsightCards(),
                data_confidence=_confidence,
                data_issues=_data_issues,
                timestamp=_ts,
            )

        # ── Step 3: Compute metrics ───────────────────────────
        enriched = compute_metrics(raw)
        # PR-DET-1: pinned price snapshot — do not recompute MoS on read.
        # `price` captured here is the SAME value used as both the response
        # `current_price` field (see ValuationOutput below) and the MoS
        # denominator (see `mos_pct = ((iv - price) / price * 100)` further
        # down). Any downstream code that needs "the price" must read this
        # local — never re-fetch from market_data, otherwise displayed
        # current_price and MoS will silently drift apart.
        price = enriched.get("price", 0) or 0
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        # ── Data-quality sanity checks ────────────────────────
        # Trip "unavailable" when yfinance returned partial/stale data
        # that would render as ₹0 cards. Covers:
        #   (a) Missing/zero/tiny price (classic)
        #   (b) Price exists but no fundamentals at all (delisted /
        #       renamed tickers — e.g. ZOMATO→ETERNAL, stale cache)
        _shares = enriched.get("shares", 0) or 0
        _latest_revenue = enriched.get("latest_revenue", 0) or 0
        _latest_pat = enriched.get("latest_pat", 0) or 0
        _has_any_fundamentals = (
            _latest_revenue > 0 or _latest_pat != 0 or _shares > 0
        )
        if not price or price < 1 or not _has_any_fundamentals:
            _issue = (
                "Price data unavailable \u2014 try again in 60 seconds."
                if not price or price < 1
                else "Financial data unavailable for this ticker. "
                "It may be delisted, renamed, or data may be stale."
            )
            return AnalysisResponse(
                ticker=ticker,
                company=CompanyInfo(
                    ticker=ticker,
                    company_name=raw.get("company_name", ticker) if raw else ticker,
                ),
                valuation=ValuationOutput(
                    fair_value=0, current_price=0, margin_of_safety=0,
                    verdict="unavailable", confidence_score=0, dcf_reliable=False,
                ),
                quality=QualityOutput(),
                insights=InsightCards(),
                data_confidence="unusable",
                data_issues=[_issue],
                timestamp=_ts,
            )

        # Detect financial companies (NBFC/Bank/Insurance)
        clean_ticker = ticker.replace('.NS', '').replace('.BO', '')
        is_financial = clean_ticker in FINANCIAL_COMPANIES

        # ── Step 4: Build company info ────────────────────────
        _raw_sector = enriched.get("sector_name", raw.get("sector_name", ""))
        _display_name = COMPANY_NAME_OVERRIDES.get(ticker, raw.get("company_name", ticker))
        # Exchange detection: .NS → NSE, .BO → BSE
        _exchange = raw.get("exchange", "")
        if not _exchange:
            _exchange = "NSE" if ticker.endswith(".NS") else "BSE" if ticker.endswith(".BO") else ""
        _industry = raw.get("industry", enriched.get("industry", ""))
        _country = "India" if is_indian else raw.get("country", "")

        company = CompanyInfo(
            ticker=ticker,
            company_name=_display_name,
            exchange=_exchange,
            sector=_resolve_sector(_raw_sector, clean_ticker),
            industry=_industry,
            country=_country,
            currency="INR" if is_indian else "USD",
            market_cap=price * enriched.get("shares", 0),
        )

        # ── Step 5: WACC + Forecast ───────────────────────────
        # Try TTM data from local DB first, then annual, then yfinance.
        # USD-reporting tickers (HCLTECH, INFY, WIPRO etc.) used to bypass
        # this path entirely — now the Financials.currency column lets
        # _query_ttm_financials / _query_latest_annual_financials convert
        # USD rows to INR before returning.
        _fcf_data_source = "yfinance"
        _normalized_fcf_meta: dict | None = None
        # ── Cyclical override: smooth FCF over 3 annual prints ───
        # Steel / O&G / Metals / RELIANCE etc. routinely print a
        # near-zero or deeply negative TTM FCF at cycle bottoms; the
        # raw value drives DCF intrinsic value to ~0 and the verdict
        # logic (service.py:1110-1134) flips to `data_limited`. For
        # the names enumerated in CYCLICAL_TICKERS (or sectors in
        # CYCLICAL_SECTORS) we substitute a 3y mean annual FCF.
        # Non-cyclicals continue to use TTM — averaging there would
        # mask real degradation in compounders.
        _resolved_sector_for_cycle = _resolve_sector(
            raw.get("sector"), clean_ticker,
        )
        if not is_financial and is_cyclical(ticker, _resolved_sector_for_cycle):
            _norm = _query_normalized_fcf(ticker, years=3)
            if _norm and _norm.get("fcf") is not None:
                _fcf_data_source = _norm.get("source") or "normalized_3y"
                enriched["latest_fcf"] = _norm["fcf"]
                if _norm.get("revenue") is not None:
                    enriched["latest_revenue"] = _norm["revenue"]
                if _norm.get("pat") is not None:
                    enriched["latest_pat"] = _norm["pat"]
                _normalized_fcf_meta = {
                    "years_used": _norm.get("years_used"),
                    "fcf_years": _norm.get("fcf_years"),
                }

        if _normalized_fcf_meta is None:
            _ttm_data = _query_ttm_financials(ticker)
            if _ttm_data:
                _fcf_data_source = "ttm"
                if _ttm_data.get("fcf") is not None:
                    enriched["latest_fcf"] = _ttm_data["fcf"]
                if _ttm_data.get("revenue") is not None:
                    enriched["latest_revenue"] = _ttm_data["revenue"]
                if _ttm_data.get("pat") is not None:
                    enriched["latest_pat"] = _ttm_data["pat"]
            else:
                _annual_data = _query_latest_annual_financials(ticker)
                if _annual_data:
                    _fcf_data_source = "annual"
                    if _annual_data.get("fcf") is not None and not enriched.get("latest_fcf"):
                        enriched["latest_fcf"] = _annual_data["fcf"]

        # Apply FCF floor for capex-heavy companies (e.g. RELIANCE, MARUTI, TITAN, HUL)
        _pat = None
        _raw_fcf = enriched.get("latest_fcf", 0) or 0

        # 1. income_df net_income (MOST RELIABLE -- always populated by compute_metrics)
        _income_df = enriched.get("income_df")
        if _income_df is not None and hasattr(_income_df, 'empty') and not _income_df.empty:
            if "net_income" in _income_df.columns:
                try:
                    _ni = float(_income_df["net_income"].iloc[-1] or 0)
                    if _ni > 0:
                        _pat = _ni
                except Exception:
                    pass

        # 2. net_margin x revenue
        if not _pat or _pat <= 0:
            _rev = enriched.get("latest_revenue", 0) or 0
            _nm = enriched.get("net_margin", 0) or 0
            if _rev > 0 and _nm > 0:
                _pat = _rev * _nm

        # 3. yahoo_fcf_ttm
        if not _pat or _pat <= 0:
            _yf = raw.get("yahoo_fcf_ttm", 0) or 0
            if _yf > 0:
                _pat = _yf

        # 4. EBITDA x 0.60
        if not _pat or _pat <= 0:
            _eb = raw.get("ebitda") or enriched.get("ebitda", 0) or 0
            if _eb > 0:
                _pat = _eb * 0.60

        # 5. EPS x shares
        if not _pat or _pat <= 0:
            _eps = raw.get("trailingEps") or 0
            _shares = enriched.get("shares") or raw.get("shares", 0) or 0
            if _eps > 0 and _shares > 0:
                _pat = _eps * _shares

        _adjusted_fcf = _get_adjusted_fcf(_raw_fcf, _pat, is_financial)
        if _adjusted_fcf is not None and _adjusted_fcf != _raw_fcf and not is_financial:
            enriched["latest_fcf"] = _adjusted_fcf

        forecaster = FCFForecaster()
        try:
            from models.forecaster import compute_wacc as _compute_wacc
            wacc_data = _compute_wacc(raw, is_indian, enriched=enriched)
            wacc = wacc_data.get("wacc", 0.10)
        except Exception:
            wacc_data = {"beta": 1.0, "beta_source": "fallback"}
            wacc = 0.10

        # ── NBFC WACC floor (surface-only, zero FV drift) ──────
        # Applies to every ticker in `_NBFC_TICKERS`. Uses max(), not
        # set — NBFCs whose CAPM already exceeds 0.11 are unchanged.
        # Only the reported `wacc` / `wacc_data["wacc"]` fields are
        # floored; `compute_financial_fair_value` below is P/B-based
        # and does not consume `wacc`, so fair value is invariant.
        if clean_ticker in _NBFC_TICKERS and wacc < NBFC_WACC_FLOOR:
            import logging as _nbfc_log
            _nbfc_log.getLogger("yieldiq.analysis").info(
                "NBFC WACC floor applied: %s %.4f -> %.4f",
                clean_ticker, wacc, NBFC_WACC_FLOOR,
            )
            wacc = NBFC_WACC_FLOOR
            if isinstance(wacc_data, dict):
                wacc_data["wacc"] = NBFC_WACC_FLOOR
                wacc_data["wacc_floor_applied"] = True

        country = get_active_country()
        terminal_g = country.get("default_terminal_growth", 0.025)
        if terminal_g >= wacc:
            terminal_g = wacc - 0.02

        forecast_yrs = 10

        # PR #168: track whether the cyclical-trough anchor fires so
        # downstream scenario assembly + (later) hex axes can react.
        _trough_anchor_fired = False
        _trough_anchor_bear_iv: float | None = None
        _trough_anchor_bull_iv: float | None = None

        # ── Step 6: Valuation (P/B for financials, DCF for others) ──
        if is_financial:
            # Defaults — always defined regardless of which P/B path runs
            bear_iv = round(price * 0.75, 2) if price > 0 else 0
            bull_iv = round(price * 1.25, 2) if price > 0 else 0
            iv = round(price, 2) if price > 0 else 0

            # --- P/B RATIO VALUATION for banks/NBFCs/insurance ---
            _sub_type = _get_financial_sub_type(clean_ticker)
            _pb_median = _PB_MEDIANS.get(_sub_type, 2.5)
            _val_method = ""

            # Method 1: Derive BVPS from priceToBook (most reliable)
            # collector.py never puts "bookValue" into raw — derive it
            _pb_live = raw.get("priceToBook") or enriched.get("pb_ratio")
            _bvps = 0
            if _pb_live and _pb_live > 0 and price > 0:
                _bvps = price / _pb_live

            # Method 2: total_equity / shares from balance sheet
            if not _bvps or _bvps <= 0:
                _equity = (enriched.get("total_equity")
                           or raw.get("total_equity") or 0)
                _shares = enriched.get("shares") or raw.get("shares", 0)
                if _equity and _shares and _shares > 0:
                    _bvps = _equity / _shares

            if _bvps and _bvps > 0:
                iv = round(_bvps * _pb_median, 2)
                # PR-BANKSC: bear was hard-coded `_bvps * 1.5` which
                # coincidentally equals base when peer P/B median ≈ 1.5
                # (e.g. HDFCBANK), producing bear=base=₹542 — flat
                # scenario display. Match the bull's structure: discount
                # 30% off base (mirror of bull's +40%).
                bear_iv = round(_bvps * _pb_median * 0.7, 2)
                bull_iv = round(_bvps * _pb_median * 1.4, 2)
                _val_method = f"P/B × {_pb_median} ({_sub_type})"
            else:
                iv = 0

            # Method 3: PE-based fallback if P/B gave 0
            if iv <= 0:
                _eps = (enriched.get("diluted_eps")
                        or raw.get("trailingEps")
                        or enriched.get("eps")
                        or raw.get("fh_eps_ttm") or 0)
                _sector_pe = {"Banking": 15, "NBFC": 20, "Insurance": 18}.get(_sub_type, 15)
                if _eps and _eps > 0:
                    iv = round(_eps * _sector_pe, 2)
                    bear_iv = round(_eps * (_sector_pe * 0.7), 2)
                    bull_iv = round(_eps * (_sector_pe * 1.3), 2)
                    _val_method = f"P/E × {_sector_pe} ({_sub_type})"

            # Method 4: Analyst target
            if iv <= 0:
                _analyst_tgt = ((raw.get("finnhub_price_target") or {}).get("mean", 0)
                                or raw.get("targetMeanPrice", 0))
                if _analyst_tgt and _analyst_tgt > 0:
                    iv = round(_analyst_tgt * 0.85, 2)
                    bear_iv = round(_analyst_tgt * 0.60, 2)
                    bull_iv = round(_analyst_tgt * 1.10, 2)
                    _val_method = "Analyst consensus (adjusted)"

            # Method 5: NEVER ₹0 — use current price = fairly valued
            if iv <= 0 and price > 0:
                iv = round(price, 2)
                bear_iv = round(price * 0.75, 2)
                bull_iv = round(price * 1.25, 2)
                _val_method = "Insufficient data"

            # Safety: ensure bear/bull always defined for financials
            if bear_iv <= 0 and iv > 0:
                bear_iv = round(iv * 0.75, 2)
            if bull_iv <= 0 and iv > 0:
                bull_iv = round(iv * 1.25, 2)

            # ── Sector-appropriate peer-median override ─────────
            # For tickers that belong to a known peer group (psu_banks,
            # private_banks, growth_nbfc, govt_nbfc, life_insurance, etc.)
            # the peer-median P/BV or P/E approach gives a much more
            # realistic fair value than the single hardcoded multiplier
            # used above — and crucially, one that survives the sanity
            # gate in routers/analysis.py for PFC/REC/IRFC/LICI.
            _financial_val_result = None
            try:
                from backend.services.financial_valuation_service import (
                    compute_financial_fair_value,
                )
                _fv_company = {
                    "current_price": price,
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                    "market_cap": price * (enriched.get("shares", 0) or 0),
                }
                _fv_fin = {
                    "priceToBook": raw.get("priceToBook") or enriched.get("pb_ratio"),
                    "total_equity": enriched.get("total_equity") or raw.get("total_equity"),
                    "pat": enriched.get("latest_pat") or _pat,
                    "latest_pat": enriched.get("latest_pat") or _pat,
                    "diluted_eps": enriched.get("diluted_eps"),
                    "eps_diluted": enriched.get("diluted_eps"),
                    "trailingEps": raw.get("trailingEps"),
                    "eps": enriched.get("eps"),
                    "fh_eps_ttm": raw.get("fh_eps_ttm"),
                    # Prefer yfinance's industry-standard returnOnEquity over our
                    # PAT/total_equity computation. The computed value gets
                    # distorted by merger accounting (HDFCBANK post-HDFC Ltd
                    # merger went from 17% to 7.8% on paper because equity
                    # base inflated 2.5x overnight). yfinance uses TTM PAT /
                    # avg equity which absorbs the structural shift correctly.
                    #
                    # Fallback chain (2026-04-21 expansion):
                    # 1. raw.returnOnEquity (yfinance .info — best when present)
                    # 2. _yf_compute_roe_from_statements — manual NI/avgEq from
                    #    yfinance financials + balance_sheet. Catches SBIN,
                    #    KOTAKBANK, HINDUNILVR where .info returns None.
                    # 3. enriched.roe (our PAT/total_equity from filings)
                    "roe": (
                        raw.get("returnOnEquity")
                        or _yf_compute_roe_from_statements(ticker)
                        or enriched.get("roe")
                    ),
                    "returnOnEquity": raw.get("returnOnEquity"),
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                }
                _financial_val_result = compute_financial_fair_value(
                    ticker=ticker,
                    company_info=_fv_company,
                    financials=_fv_fin,
                    shareholding=None,
                )
            except Exception as _fv_exc:
                import logging as _fv_log
                _fv_log.getLogger("yieldiq.analysis").warning(
                    "[%s] financial_valuation failed: %s: %s",
                    ticker, type(_fv_exc).__name__, _fv_exc,
                )
                _financial_val_result = None

            if _financial_val_result and _financial_val_result.get("fair_value", 0) > 0:
                iv = float(_financial_val_result["fair_value"])
                bear_iv = float(_financial_val_result.get("bear_case", bear_iv))
                bull_iv = float(_financial_val_result.get("bull_case", bull_iv))
                _val_method = (
                    f"{_financial_val_result.get('method', 'p_bv_peer')} "
                    f"(peer median)"
                )

            iv_raw = iv
            dcf_res = {
                "intrinsic_value_per_share": iv,
                "warnings": [f"Valuation: {_val_method}"] if _val_method else [],
                "reliability_score": 75 if _bvps and _bvps > 0 else 50,
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
        else:
            # --- Standard DCF for non-financials ---
            forecast_result = forecaster.predict(enriched, years=forecast_yrs)
            projected = forecast_result.get("projections", [])
            growth_schedule = forecast_result.get("growth_schedule", [])
            base_growth = forecast_result.get("base_growth", 0)

            if not projected or all(v <= 0 for v in projected):
                projected = [enriched.get("latest_fcf", 1e6)] * forecast_yrs

            terminal_norm = float(sum(projected[-3:]) / 3) if len(projected) >= 3 else projected[-1] if projected else 0

            # PR-D2: pass sector/sub_sector so DCFEngine can apply the
            # NBFC funding-cost premium (+50bps) to the discount rate.
            # Without these kwargs the adjustment is dead code.
            dcf_engine = DCFEngine(
                discount_rate=wacc,
                terminal_growth=terminal_g,
                sector=enriched.get("sector"),
                sub_sector=enriched.get("sub_sector"),
                ticker=ticker,
            )
            dcf_res = dcf_engine.intrinsic_value_per_share(
                projected_fcfs=projected,
                terminal_fcf_norm=terminal_norm,
                total_debt=enriched.get("total_debt", 0),
                total_cash=enriched.get("total_cash", 0),
                shares_outstanding=enriched.get("shares", 1),
                current_price=price,
                ticker=ticker,
                beta=wacc_data.get("beta"),
            )
            iv_raw = dcf_res.get("intrinsic_value_per_share", 0)

            # Enrich the DCF_TRACE with upstream context so production
            # blow-ups (HCLTECH FV ₹6,075) can be diagnosed without
            # reproducing locally.
            try:
                from screener.dcf_engine import DCF_TRACES
                if ticker in DCF_TRACES:
                    DCF_TRACES[ticker]["fcf_source"] = _fcf_data_source
                    if _normalized_fcf_meta is not None:
                        DCF_TRACES[ticker]["fcf_normalized_years_used"] = (
                            _normalized_fcf_meta.get("years_used")
                        )
                        DCF_TRACES[ticker]["fcf_normalized_years"] = (
                            _normalized_fcf_meta.get("fcf_years")
                        )
                    DCF_TRACES[ticker]["enriched_latest_fcf"] = float(enriched.get("latest_fcf") or 0)
                    DCF_TRACES[ticker]["enriched_latest_revenue"] = float(enriched.get("latest_revenue") or 0)
                    DCF_TRACES[ticker]["enriched_latest_pat"] = float(enriched.get("latest_pat") or 0)
                    DCF_TRACES[ticker]["enriched_op_margin"] = float(enriched.get("op_margin") or 0)
                    DCF_TRACES[ticker]["yahoo_fcf_ttm"] = float(raw.get("yahoo_fcf_ttm") or 0)
                    DCF_TRACES[ticker]["fin_multiplier"] = float(raw.get("fin_multiplier") or 1.0)
                    cands = enriched.get("_fcf_candidates") or {}
                    DCF_TRACES[ticker]["fcf_candidates"] = {k: float(v) for k, v in cands.items()}
                    DCF_TRACES[ticker]["fcf_base_source"] = enriched.get("_fcf_base_source", "unknown")
            except Exception:
                pass

            # PE crosscheck blend
            try:
                eps = get_eps(enriched)
                sector = enriched.get("sector", "general")
                pe_iv = compute_pe_based_iv(eps, sector, "base", enriched.get("revenue_growth", 0))
                iv = blend_dcf_pe(iv_raw, pe_iv, sector)
            except Exception:
                iv = iv_raw

            # ── Cyclicals at cycle bottom: trough anchor ─────────
            # Trigger: ticker is in CYCLICAL_TICKERS or sector in
            # CYCLICAL_SECTORS, AND DCF resolved to an iv/price ratio
            # below the validator's [0.2, 5.0] band. This catches:
            #   (a) iv == 0 from dcf_engine equity_value <= 0
            #       short-circuit (debt-heavy cyclical at trough)
            #   (b) tiny-positive iv from a real DCF compute that
            #       still produces an absurd fair_value_ratio
            #       (TATASTEEL observed at 10.19/210 = 0.0485 in
            #       Sentry; validator quarantines as under_review).
            # Fallback: anchor iv to 0.95 * price. Verdict logic
            # then produces "fairly_valued" — the honest read for a
            # cyclical at trough whose long-run economics aren't
            # broken (steel/metals/O&G with positive normalized 3y
            # FCF but high debt drag in cycle-bottom equity calc).
            # Non-cyclicals (compounders) are untouched — gate is
            # is_cyclical() which checks both ticker set and sector.
            if (
                is_cyclical(ticker, _resolved_sector_for_cycle)
                and price > 0
                and iv < 0.2 * price
            ):
                _pre_anchor_iv = iv
                iv = round(price * 0.95, 2)
                if not _fcf_data_source.endswith("+trough_anchor"):
                    _fcf_data_source = f"{_fcf_data_source}+trough_anchor"
                # PR #168: propagate the anchor to scenarios so the bear
                # / bull cases don't render as ₹0 on the frontend (the
                # raw cycle-bottom DCF that produced iv<0.2*price also
                # produces bear≈0/bull≈0 from the same engine; without
                # propagation _enforce_scenario_order leaves bear at 0
                # because 0 <= base <= bull is technically "ordered").
                # Anchor band: bear at 0.85*price (mid-cycle pessimism),
                # base at 0.95*price (current anchor), bull at 1.10*price
                # (mid-cycle recovery). These are honest "cycle has
                # priced in" reads, not engine output.
                _trough_anchor_fired = True
                _trough_anchor_bear_iv = round(price * 0.85, 2)
                _trough_anchor_bull_iv = round(price * 1.10, 2)
                import logging as _trough_log
                _trough_log.getLogger("yieldiq.analysis").info(
                    "CYCLICAL_TROUGH_ANCHOR: %s iv=%.2f / price=%.2f "
                    "(ratio=%.4f) below 0.2 floor; anchoring iv to %.2f "
                    "(0.95*price); scenarios anchored bear=%.2f bull=%.2f",
                    ticker, _pre_anchor_iv, price,
                    _pre_anchor_iv / price if price > 0 else 0.0, iv,
                    _trough_anchor_bear_iv, _trough_anchor_bull_iv,
                )

        # ── Growth-stock override ─────────────────────────────
        # For pre-profit companies (FCF<=0 or PAT<=0) with real revenue,
        # the standard DCF produces ~0 fair value. Route to a reverse
        # P/S multiple so users see a principled number, not 'data_limited'.
        # All logging inside the growth module. No external logger refs
        # (previous attempt broke every ticker with NameError).
        try:
            from models.growth_valuation import (
                should_use_growth_path,
                compute_growth_valuation,
            )
            _mcap_for_growth = price * (enriched.get("shares", 0) or 0)
            if should_use_growth_path(enriched, _mcap_for_growth):
                _gv = compute_growth_valuation(
                    enriched=enriched,
                    market_cap=_mcap_for_growth,
                    sector=enriched.get("sector", "general"),
                    ticker=ticker,
                )
                if _gv and (_gv.get("fair_value") or 0) > 0:
                    iv = float(_gv["fair_value"])
        except Exception:
            pass

        mos_pct = margin_of_safety(iv, price) * 100 if price > 0 else 0

        # ── Step 7: Quality checks & insight sub-computes (PARALLEL) ──
        # All of these are pure reads over `enriched` / `raw` / scalar
        # inputs already computed above. They don't mutate self or share
        # state, so we run them concurrently on a ThreadPool to cut
        # cold-path wall-time.
        #
        # Intentional ordering note:
        #   * Scenarios, reverse_dcf, fcf_yield, ev_ebitda are all
        #     independent of quality results → safe to parallelize.
        #   * Moat's IV delta is applied AFTER gather (serially), so
        #     the final displayed `iv` reflects the moat delta.
        #   * mos_pct is computed from the pre-adjustment iv to match
        #     the original sequential behavior exactly.
        #
        # Fallback: if the executor path raises, we fall back to
        # sequential execution (same logic, same order) so production
        # stays correct even if threads misbehave.
        import time as _pt_time
        import logging as _pt_log
        _pt_logger = _pt_log.getLogger("yieldiq.analysis")

        # Prepare inputs for momentum (needs collector price history if
        # yfinance path was used; local path doesn't have a collector).
        try:
            _price_history_for_momentum = (
                collector.get_price_history()
                if "collector" in locals() and hasattr(collector, "get_price_history")
                else None
            )
        except Exception:
            _price_history_for_momentum = None

        # fcf_base for scenarios (non-financial only)
        _fcf_base_for_scen = None
        if not is_financial:
            try:
                _fcf_base_for_scen = (
                    projected[0] / (1 + growth_schedule[0])
                    if projected and growth_schedule and growth_schedule[0] > -1
                    else enriched.get("latest_fcf", 1e6)
                )
            except Exception:
                _fcf_base_for_scen = enriched.get("latest_fcf", 1e6)

        # --- Sequential fallback helpers (pure functions) ---
        def _run_piotroski():
            try:
                return compute_piotroski_fscore(enriched)
            except Exception:
                return {"score": 0, "grade": ""}

        def _run_moat():
            try:
                return compute_moat_score(enriched, wacc)
            except Exception:
                return {"score": 0, "grade": "None"}

        def _run_eq():
            try:
                return compute_earnings_quality(enriched)
            except Exception:
                return {"score": 0, "grade": "N/A"}

        def _run_momentum():
            try:
                return calculate_momentum(_price_history_for_momentum)
            except Exception:
                return {"momentum_score": 0, "grade": "N/A"}

        def _run_fund():
            try:
                return score_fundamentals(enriched)
            except Exception:
                return {"score": 0, "grade": "N/A"}

        def _run_confidence():
            try:
                return compute_confidence_score(enriched)
            except Exception:
                return {"score": 50}

        def _run_scenarios():
            if is_financial:
                return {}
            try:
                return run_scenarios(
                    enriched=enriched, fcf_base=_fcf_base_for_scen,
                    base_growth=base_growth, base_wacc=wacc,
                    base_terminal_g=terminal_g,
                    total_debt=enriched.get("total_debt", 0),
                    total_cash=enriched.get("total_cash", 0),
                    shares=enriched.get("shares", 1),
                    current_price=price, years=forecast_yrs,
                )
            except Exception:
                return {}

        def _run_rdcf():
            try:
                return run_reverse_dcf(enriched, price, wacc, terminal_g)
            except Exception:
                return {}

        def _run_fcf_yield():
            try:
                return compute_fcf_yield_analysis(enriched, price)
            except Exception:
                return {}

        def _run_eveb():
            try:
                return run_ev_ebitda_analysis(enriched, price, fetch_peers=False)
            except Exception:
                return {}

        _sub_jobs = {
            "piotroski": _run_piotroski,
            "moat": _run_moat,
            "eq": _run_eq,
            "momentum": _run_momentum,
            "fund": _run_fund,
            "confidence": _run_confidence,
            "scenarios": _run_scenarios,
            "rdcf": _run_rdcf,
            "fcf_yield": _run_fcf_yield,
            "eveb": _run_eveb,
        }

        _results: dict = {}
        _parallel_ok = False
        _t_par_start = _pt_time.monotonic()
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(
                max_workers=min(10, len(_sub_jobs)),
                thread_name_prefix=f"yiq-{ticker}",
            ) as _ex:
                _futs = {k: _ex.submit(fn) for k, fn in _sub_jobs.items()}
                for _k, _f in _futs.items():
                    _results[_k] = _f.result()
            _parallel_ok = True
        except Exception as _par_exc:
            _pt_logger.warning(
                "[%s] parallel sub-compute failed (%s: %s) — falling back sequential",
                ticker, type(_par_exc).__name__, _par_exc,
            )
            _results = {}

        if not _parallel_ok:
            # Sequential fallback — same logic, same order
            _t_seq_start = _pt_time.monotonic()
            for _k, _fn in _sub_jobs.items():
                _results[_k] = _fn()
            _pt_logger.info(
                "[%s] compute_ms_sequential=%d",
                ticker, int((_pt_time.monotonic() - _t_seq_start) * 1000),
            )
        else:
            _pt_logger.info(
                "[%s] compute_ms_parallel=%d",
                ticker, int((_pt_time.monotonic() - _t_par_start) * 1000),
            )

        piotroski = _results["piotroski"]
        moat_result = _results["moat"]
        eq_result = _results["eq"]
        momentum_result = _results["momentum"]
        fund_result = _results["fund"]
        confidence = _results["confidence"]
        scenarios_raw = _results["scenarios"]
        rdcf = _results["rdcf"]
        fcf_yield = _results["fcf_yield"]
        eveb = _results["eveb"]

        # Apply moat IV adjustment for non-financial stocks (serial —
        # mutates iv which feeds yiq_score / inv_plan / mos_pct below).
        if not is_financial and moat_result.get("grade") not in ("None", "N/A (Financial)"):
            try:
                moat_adj = apply_moat_adjustments(
                    moat_result=moat_result, wacc=wacc, base_growth=base_growth,
                    terminal_g=terminal_g, iv=iv_raw,
                    sector=enriched.get("sector", "general"),
                )
                _iv_delta = moat_adj.get("iv_delta_pct", 0) / 100
                iv = round(iv * (1 + _iv_delta), 2)
                iv_raw = iv
            except Exception:
                pass

        # ── feat/peer-cap (2026-04-27): peer-multiple sanity ceiling ─
        # If DCF FV is more than 1.5× the lower of peer-median
        # P/E-implied / EV/EBITDA-implied (or P/B-implied for banks),
        # cap the displayed FV at 1.5× peer-implied. Purely additive:
        # leaves `iv` untouched when no peers are available, the
        # multiple isn't tripped, or the DB is unreachable. Does NOT
        # change wacc / scenarios / dcf_res — the cap is a render-time
        # ceiling on the headline number, with the audit trail in
        # `_peer_cap_details` for the frontend tooltip.
        _fair_value_source: str = "dcf"
        _peer_cap_details: PeerCapDetails | None = None
        try:
            if iv and iv > 0 and not is_financial:
                _pc = _compute_peer_cap(ticker)
            elif iv and iv > 0 and is_financial:
                # Financials still get the peer-cap check, routed
                # through the bank P/B path inside the service.
                _pc = _compute_peer_cap(ticker)
            else:
                _pc = None
            if _pc and _pc.get("peer_fv", 0) > 0:
                _peer_fv = float(_pc["peer_fv"])
                _ceiling = 1.5 * _peer_fv
                if _ceiling < iv:
                    _peer_cap_details = PeerCapDetails(
                        uncapped_fv=round(float(iv), 2),
                        peer_fv=round(_peer_fv, 2),
                        ceiling_fv=round(_ceiling, 2),
                        method=_pc["method"],
                        n_peers=int(_pc["n_peers"]),
                        median_pe=_pc.get("median_pe"),
                        median_ev_ebitda=_pc.get("median_ev_ebitda"),
                        median_pb=_pc.get("median_pb"),
                        sector=_pc.get("sector"),
                        industry=_pc.get("industry"),
                    )
                    iv = round(_ceiling, 2)
                    _fair_value_source = "peer_capped"
        except Exception:
            # Cap failure must never break analysis. Leave FV as-is.
            _peer_cap_details = None
            _fair_value_source = "dcf"

        # CRITICAL FIX (FIX1): mos_pct MUST be recomputed from the
        # post-adjustment `iv` so that the displayed MoS reconciles
        # with the displayed `fair_value` via (FV-CMP)/CMP. Prior
        # behaviour preserved a "pre-moat" MoS even though the
        # displayed FV reflected the moat delta — users saw e.g.
        # FV ₹3,223 with MoS −0.1% when the math demands +24.8%.
        # PR-DET-1: pinned price snapshot — do not recompute MoS on read.
        # `price` here is the snapshot taken at write-time (Step 3 above);
        # never substitute a freshly-fetched market price in this expression
        # or the cached current_price will not reconcile with cached MoS.
        mos_pct = ((iv - price) / price * 100) if price > 0 else 0

        # Analyst upside: (target - price) / price * 100
        _analyst_target = (raw.get("finnhub_price_target") or {}).get("mean", 0) or 0
        _analyst_upside = ((_analyst_target - price) / price * 100) if price > 0 and _analyst_target > 0 else 0

        try:
            yiq_score = compute_yieldiq_score(
                mos_pct=mos_pct,
                piotroski=piotroski.get("score", 0),
                moat_grade=moat_result.get("grade", "None"),
                rev_growth=enriched.get("revenue_growth", 0),
                analyst_upside=_analyst_upside,
            )
        except TypeError as _te:
            # Fallback: calculate inline if function signature doesn't match
            _v = max(0, min(40, int((mos_pct + 40) / 80 * 40)))
            _q = max(0, min(30, int(piotroski.get("score", 0) / 9 * 20 + (10 if moat_result.get("grade") == "Wide" else 7 if moat_result.get("grade") == "Narrow" else 0))))
            _g = max(0, min(20, int(enriched.get("revenue_growth", 0) * 100)))
            _total = max(0, min(100, _v + _q + _g))
            yiq_score = {"score": _total, "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D" if _total >= 20 else "F"}

        # ── Step 8: Scenarios ─────────────────────────────────
        # `scenarios_raw` was computed in the parallel wave above
        # (empty dict for financials by design).

        def _sc(key):
            d = scenarios_raw.get(key, {})
            return ScenarioCase(
                iv=d.get("iv", 0), mos_pct=d.get("mos_pct", 0),
                growth=d.get("growth", 0), wacc=d.get("wacc", wacc),
                term_g=d.get("term_g", terminal_g),
            )

        # ── Step 9: Insights ──────────────────────────────────
        try:
            inv_plan = generate_valuation_summary(enriched, price, iv, mos_pct / 100)
            pt = inv_plan.get("price_targets", {})
            hp = inv_plan.get("holding_period", {})
        except Exception:
            inv_plan = {}
            pt = {}
            hp = {}

        # rdcf / fcf_yield / eveb already computed in the parallel wave
        # above — they only need (enriched, price, wacc, terminal_g),
        # none of which change between there and here.

        # Red flags from DCF edge cases
        _red_flags = dcf_res.get("warnings", [])

        # Remove IPO-related flags — they indicate data completeness, not business risk
        _red_flags = [
            f for f in _red_flags
            if not any(kw in f.lower() for kw in ('ipo', 'ipo_date', 'listing_date', 'unknown ipo'))
        ]

        # For financial companies, remove "Loss Company" / negative FCF flags
        if is_financial:
            _red_flags = [
                f for f in _red_flags
                if 'loss company' not in f.lower()
                and 'negative fcf' not in f.lower()
                and 'zero fcf' not in f.lower()
            ]

        if enriched.get("unreliable_reason"):
            _red_flags.append(enriched["unreliable_reason"])

        # Promoter pledge red flags
        _promoter_pledge = raw.get("promoter_pledge_pct")
        if _promoter_pledge is None:
            # Try fetching from enriched data or shareholding
            _promoter_pledge = enriched.get("promoter_pledge_pct")
        if _promoter_pledge is None:
            # Fall back to ShareholdingPattern DB table
            _promoter_pledge = _query_promoter_pledge(ticker)
        if _promoter_pledge is not None:
            try:
                _pledge_val = float(_promoter_pledge)
                if _pledge_val > 25:
                    _red_flags.append(
                        f"CRITICAL: Promoter pledge {_pledge_val:.1f}% — very high risk"
                    )
                elif _pledge_val > 10:
                    _red_flags.append(
                        f"Promoter pledge {_pledge_val:.1f}% — elevated risk"
                    )
            except (ValueError, TypeError):
                pass

        # ── Step 10: Verdict ──────────────────────────────────
        _conf_score = confidence.get("score", 50)

        if is_financial:
            # Financial companies: simple MoS verdict, NEVER "avoid"
            if iv <= 0:
                verdict = "data_limited"
            elif mos_pct > 15:
                verdict = "undervalued"
            elif mos_pct > -15:
                verdict = "fairly_valued"
            else:
                verdict = "overvalued"
        elif _confidence in ("low", "unusable") and abs(mos_pct) > 40 and clean_ticker not in INVENTORY_HEAVY_TICKERS:
            verdict = "data_limited"
        elif _conf_score < 35 and abs(mos_pct) > 40 and clean_ticker not in INVENTORY_HEAVY_TICKERS:
            verdict = "data_limited"
        elif mos_pct > 15:
            verdict = "undervalued"
        elif mos_pct > -15:
            verdict = "fairly_valued"
        elif enriched.get("dcf_reliable", True):
            verdict = "overvalued"
        else:
            verdict = "avoid"

        # ── Verdict hysteresis: dampen near-threshold flips ───
        # Bug from 2026-04-20 audit: same ticker (HCLTECH) showed
        # Fair -> Over -> Under across 15-min reloads. Two causes:
        # 1. MoS recompute gives slightly different value each run
        # 2. ±15% boundary is hard, so 14.8 vs 15.2 flips verdict
        #
        # Mitigation: if there's a recent fair_value_history verdict and
        # the new mos is within 2pp of a threshold, keep the prior verdict.
        try:
            from data_pipeline.db import Session as _PG_Session
            from sqlalchemy import text as _hys_text
            if _PG_Session is not None and verdict in ("undervalued", "fairly_valued", "overvalued"):
                _hys_db = _PG_Session()
                try:
                    _prev = _hys_db.execute(_hys_text("""
                        SELECT verdict, mos_pct FROM fair_value_history
                        WHERE ticker = :t
                          AND date >= CURRENT_DATE - INTERVAL '7 days'
                          AND verdict IN ('undervalued', 'fairly_valued', 'overvalued')
                        ORDER BY date DESC LIMIT 1
                    """), {"t": ticker}).fetchone()
                finally:
                    _hys_db.close()
                if _prev and _prev[0] and _prev[0] != verdict and _prev[1] is not None:
                    _prev_v, _prev_m = _prev[0], float(_prev[1])
                    # Within 2pp of either ±15% boundary?
                    near_pos = abs(mos_pct - 15) <= 2.0
                    near_neg = abs(mos_pct + 15) <= 2.0
                    if near_pos or near_neg:
                        # And the flip is across exactly the nearby threshold?
                        flipped_pos = (_prev_m > 15) != (mos_pct > 15)
                        flipped_neg = (_prev_m > -15) != (mos_pct > -15)
                        if (near_pos and flipped_pos) or (near_neg and flipped_neg):
                            verdict = _prev_v
        except Exception:
            pass  # never block the response on hysteresis lookup

        # ── Earnings date (NSE first, Finnhub fallback) ─────
        _earnings = _query_earnings_date(ticker)
        _earnings_date = (
            _earnings.get("date") if _earnings
            else (raw.get("finnhub_next_earnings") or {}).get("date")
        )
        earnings_days_until = _earnings.get("days_away") if _earnings else None

        # ── Bulk deals for insider activity ──────────────────
        _bulk_deals_raw = _query_bulk_deals(ticker, days=90)
        _bulk_deals = [
            BulkDealItem(
                date=d["date"], client=d["client"], deal_type=d["deal_type"],
                qty_lakh=d["qty_lakh"], price=d["price"], category=d["category"],
            )
            for d in _bulk_deals_raw
        ]

        # ── Assemble response ─────────────────────────────────
        # Build the canonical scenarios object FIRST. ValuationOutput
        # flat fields (bear_case/base_case/bull_case) MUST read from the
        # same clamped output as ScenariosOutput — otherwise the public
        # stock-summary endpoint (which serialises the flat fields)
        # diverges from the authed /analysis endpoint (which serialises
        # scenarios.*.iv). BHARTIARTL surfaced this: bull DCF undershot
        # base when terminal_g sat close to WACC, and the pre-clamp
        # flat field got bull < base while the clamped scenarios had
        # bull >= base * 1.05. Canary gate 1 (single_source_of_truth)
        # + gate 3 (dispersion) both fired for that one row.
        if is_financial:
            _sc_bear_pre = ScenarioCase(
                iv=bear_iv,
                mos_pct=round((bear_iv - price) / price * 100, 1) if price > 0 else 0,
                growth=0, wacc=round(wacc, 4), term_g=round(terminal_g, 4),
            )
            _sc_bull_pre = ScenarioCase(
                iv=bull_iv,
                mos_pct=round((bull_iv - price) / price * 100, 1) if price > 0 else 0,
                growth=0, wacc=round(wacc, 4), term_g=round(terminal_g, 4),
            )
        else:
            _sc_bear_pre = _sc("Bear case") if scenarios_raw.get("Bear case") else _sc("Bear 🐻")
            _sc_bull_pre = _sc("Bull case") if scenarios_raw.get("Bull case") else _sc("Bull 🐂")
            # PR #168: when the cyclical-trough anchor fired, the raw
            # scenario engine produced bear/bull from the same broken
            # cycle-bottom DCF that triggered the anchor in the first
            # place — values are typically 0/0 or a few rupees. Replace
            # them with the anchored band so the frontend shows an
            # honest "cycle has priced in" read instead of ₹0 and a
            # stray bull-only number from _enforce_scenario_order.
            if _trough_anchor_fired and _trough_anchor_bear_iv is not None:
                _bear_iv_val = _trough_anchor_bear_iv
                _bull_iv_val = _trough_anchor_bull_iv or round(price * 1.10, 2)
                _sc_bear_pre = ScenarioCase(
                    iv=_bear_iv_val,
                    mos_pct=round((_bear_iv_val - price) / price * 100, 1) if price > 0 else 0,
                    growth=round(base_growth, 4),
                    wacc=round(wacc, 4), term_g=round(terminal_g, 4),
                )
                _sc_bull_pre = ScenarioCase(
                    iv=_bull_iv_val,
                    mos_pct=round((_bull_iv_val - price) / price * 100, 1) if price > 0 else 0,
                    growth=round(base_growth, 4),
                    wacc=round(wacc, 4), term_g=round(terminal_g, 4),
                )
        _sc_base_pre = ScenarioCase(
            iv=round(iv, 2), mos_pct=round(mos_pct, 1),
            growth=round(base_growth, 4),
            wacc=round(wacc, 4), term_g=round(terminal_g, 4),
        )
        _scenarios_clamped = _enforce_scenario_order(
            bear=_sc_bear_pre, base=_sc_base_pre, bull=_sc_bull_pre, price=price,
        )

        _bear_case = _scenarios_clamped.bear.iv
        _base_case = _scenarios_clamped.base.iv
        _bull_case = _scenarios_clamped.bull.iv

        # ── Dividend data (one yfinance .info call, ~1s) ─────
        # Swallowed — never blocks the main response.
        _dividend_data = None
        try:
            from backend.services.dividend_service import DividendService
            from backend.models.responses import DividendData, DividendFYItem
            # Pass the collector's raw info dict to avoid a duplicate
            # yfinance .info call (~20s saved per cold request).
            _div_result = DividendService().get_dividends(
                ticker=ticker, enriched=enriched, yf_info=raw
            )
            _fy_items = [
                DividendFYItem(**item)
                for item in _div_result.get("fy_history", [])
            ]
            _dividend_kwargs = {
                k: v for k, v in _div_result.items() if k != "fy_history"
            }
            _dividend_data = DividendData(fy_history=_fy_items, **_dividend_kwargs)
        except Exception as _div_exc:
            import logging as _div_log
            _div_log.getLogger("yieldiq.dividends").debug(
                "Dividend embed failed for %s: %s", ticker, _div_exc
            )

        # ── Structured red flags for the deep-dive UI ────────
        # MOVED (FIX-DAY3-STRENGTHS 2026-04-22): the build call was
        # here originally, but the newer info-flag rules (ROCE,
        # revenue CAGR, interest coverage, D/E) need values that
        # service.py only computes later in the function (roce_val,
        # rev_cagr_3y, ...). We defer the build until after those
        # are injected into ``enriched``. See the call further down
        # labelled "DEFERRED STRUCTURED FLAG BUILD".
        _structured_flags: list = []

        # ── Forward-fill fair value history (async) ─────────
        # Writes one row per ticker per day. Runs in a daemon thread so
        # the Aiven DB round-trips (3 queries + 1 write after the DCF
        # smoothing commit) don't block the analysis response. If the
        # thread dies mid-write the response has already been returned;
        # worst case is a missing history row for that tick.
        try:
            if iv and iv > 0 and price and price > 0:
                import threading as _fv_threading
                _fv_args = dict(
                    ticker=ticker,
                    fv=float(iv),
                    price=float(price),
                    mos=float(mos_pct),
                    verdict=str(verdict),
                    wacc=float(wacc),
                    confidence=int(confidence.get("score", 50)),
                )

                def _bg_store_fv():
                    try:
                        from data_pipeline.sources.fv_history import (
                            store_today_fair_value,
                        )
                        _db = _get_pipeline_session()
                        if _db is None:
                            return
                        try:
                            store_today_fair_value(db=_db, **_fv_args)
                        finally:
                            _db.close()
                    except Exception:
                        pass  # already logged by store_today_fair_value

                _fv_threading.Thread(
                    target=_bg_store_fv, daemon=True, name=f"fv-store-{ticker}"
                ).start()
        except Exception as _fv_exc:
            import logging as _fv_log
            _fv_log.getLogger("yieldiq.fv_history").debug(
                "FV history store skipped for %s: %s", ticker, _fv_exc
            )
        # ──────────────────────────────────────────────────────

        # ── Extended quality ratios ───────────────────────────
        # ROCE, Debt/EBITDA (with band label), Interest Coverage,
        # Enterprise Value. Every metric is Optional — None flows
        # through to the frontend which renders "—".
        #
        # FIX-XBRL-ROCE (2026-04): pull EBIT + Total Assets +
        # Current Liabilities together from the pipeline DB so that
        # the ROCE denominator is populated even when the yfinance-
        # sourced `enriched` dict happens to lack these fields.
        _ebit_val, _ta_db, _cl_db, _interest_exp = _fetch_roce_inputs(ticker)

        _total_assets = enriched.get("total_assets") or _ta_db or 0
        _total_debt = enriched.get("total_debt") or 0
        _total_cash = enriched.get("total_cash") or 0
        _ebitda = enriched.get("ebitda") or 0
        _shares = enriched.get("shares") or 0
        _current_liab = enriched.get("current_liabilities") or _cl_db or 0

        # ── FIX-ROCE-UNIT-MISMATCH (2026-04-22) ────────────────
        # The vars above mix two unit systems:
        #   - _ebit_val (from XBRL pipeline) is in INR Crores
        #   - enriched.total_assets (from yfinance) is in raw INR
        # yfinance's total_assets for TCS.NS = 1,823,720,000,000 (raw
        # INR = ₹1.82 trillion = ₹182,372 Cr). Mixed with EBIT=66,714
        # (Cr), the ratio becomes 66714 / 1.82e12 × 100 ≈ 10⁻⁹ %,
        # rounds to 0.0, then the sanity guard turns 0.0 into None →
        # flagships show "—" for ROCE despite perfect DB data.
        #
        # Fix: for the ROCE compute specifically, prefer the DB-
        # sourced TA / CL (which match _ebit_val's Crore unit) over
        # enriched when the DB has them. Other ratios (debt_ebitda,
        # EV, etc.) keep the original _total_assets for backward
        # compatibility — they use debt/cash from enriched so their
        # own unit contract is intact.
        _ta_for_roce = _ta_db if _ta_db is not None else (enriched.get("total_assets") or 0)
        _cl_for_roce = _cl_db if _cl_db is not None else (enriched.get("current_liabilities") or 0)

        # Sector-based "bank / NBFC / Financial" detection — leverage
        # and interest-coverage ratios are not meaningful for these.
        _sector_str = (company.sector or "").lower()
        _is_bank_like = bool(
            is_financial
            or "bank" in _sector_str
            or "financial" in _sector_str
            or ticker.upper().endswith(("BANK.NS", "BANK.BO"))
        )

        # ROCE uses the textbook capital-employed denominator:
        #   EBIT / (Total Assets − Current Liabilities)  [returns %]
        # Falls back to ebit / total_assets when current_liabilities
        # is missing so we don't regress coverage for tickers lacking
        # that field.
        from backend.services.ratios_service import (
            compute_roce as _compute_roce,
            compute_debt_to_ebitda as _compute_debt_ebitda,
            compute_interest_coverage as _compute_int_cov,
        )
        _roce_val: float | None = _compute_roce(
            _ebit_val, _ta_for_roce, _cl_for_roce
        )
        # Fallback path: primary returned None (often because
        # current_liabilities isn't on file for older `financials`
        # rows). Use the looser EBIT/Total Assets definition so we
        # keep coverage. Must guard against EBIT<=0 though — otherwise
        # tickers with missing/zero EBIT render as misleading "0.0% Weak"
        # (e.g. RELIANCE appeared as 0% on the analysis page).
        if (
            _roce_val is None
            and _ebit_val is not None
            and _ebit_val > 0
            and _ta_for_roce > 0
        ):
            _rounded = round(_ebit_val / _ta_for_roce * 100, 1)
            # Sanity guard: if the rounded value is EXACTLY 0.0, the
            # underlying ratio was <0.05% — effectively noise. Returning
            # 0.0% to the UI looks like "Weak" to users; "—" is more
            # honest (audit feedback: HCLTECH/TCS/INFY/ITC all showed
            # 0.0% because tiny EBIT/TA rounded down, misleading users
            # into thinking the business had zero return on capital).
            _roce_val = _rounded if _rounded > 0 else None

        # Banks / NBFCs: Debt/EBITDA and Interest Coverage are not
        # meaningful (deposits ≠ debt, interest expense is revenue).
        # Return None so the frontend renders "—" with a banker note.
        if _is_bank_like:
            _debt_ebitda_val = None
            _debt_ebitda_lbl = None
            _interest_cov_val = None
        else:
            _debt_ebitda_val = _compute_debt_ebitda(_total_debt, _ebitda)
            _debt_ebitda_lbl = _debt_ebitda_label(_debt_ebitda_val)
            _interest_cov_val = _compute_int_cov(_ebit_val, _interest_exp)

        # ── Bank-native metrics (feat/bank-prism-metrics 2026-04-21) ──
        # For banks we fill a small set of fields that DO apply:
        #   roa, cost_to_income, advances_yoy (proxy), deposits_yoy (proxy),
        #   revenue_yoy_bank, pat_yoy_bank, nim (when XBRL Sch A/B lands).
        #
        # All default to None for non-banks, so the QualityOutput contract
        # is unchanged for the existing 950+ non-bank tickers — canary-
        # diff sees an additive change only. See docs/bank_data_availability.md
        # for the coverage matrix.
        _bm_roa: float | None = None
        _bm_cost_to_income: float | None = None
        _bm_advances_yoy: float | None = None      # proxy: total_assets YoY
        _bm_deposits_yoy: float | None = None      # proxy: total_liab YoY
        _bm_revenue_yoy: float | None = None
        _bm_pat_yoy: float | None = None
        _bm_nim: float | None = None
        # Absolute bank metrics we cannot source yet — kept as explicit
        # None so the schema is stable and the frontend can render "—".
        _bm_car: float | None = None               # TODO: NSE XBRL Sch XI
        _bm_nnpa: float | None = None              # TODO: NSE XBRL Sch XVIII
        _bm_casa: float | None = None              # TODO: NSE XBRL Sch V

        if _is_bank_like:
            from backend.services.ratios_service import (
                compute_roa as _compute_roa,
                compute_cost_to_income as _compute_c2i,
                compute_yoy_growth as _compute_yoy,
                compute_nim as _compute_nim,
            )
            _bm = _fetch_bank_metrics_inputs(ticker)
            if _bm is not None:
                # ROA — prefer the pre-computed `financials.roa` (already a
                # percent). Fall back to net_income / total_assets if the
                # rollup row is missing but the raw numbers are there.
                _bm_roa = _bm.get("roa")
                if _bm_roa is None:
                    _bm_roa = _compute_roa(
                        _bm.get("net_income"), _bm.get("total_assets"),
                    )

                # Cost-to-Income — opex / revenue (revenue here is the XBRL
                # `total_income` surrogate since the split into
                # interest/non-interest income is not extracted yet).
                _bm_cost_to_income = _compute_c2i(
                    _bm.get("operating_expense"), _bm.get("revenue"),
                )

                # YoY series — "newest first", so [0] vs [1] is the latest
                # FY vs. the prior FY.
                _rev_series = _bm.get("revenue_series") or []
                _pat_series = _bm.get("net_income_series") or []
                _ta_series = _bm.get("total_assets_series") or []
                _tl_series = _bm.get("total_liab_series") or []

                if len(_rev_series) >= 2:
                    _bm_revenue_yoy = _compute_yoy(_rev_series[0], _rev_series[1])
                if len(_pat_series) >= 2:
                    _bm_pat_yoy = _compute_yoy(_pat_series[0], _pat_series[1])
                if len(_ta_series) >= 2:
                    # Total assets YoY as a proxy for advances YoY — loans
                    # are the dominant asset for a commercial bank. When
                    # Sch VII advances extraction lands, replace with the
                    # real advances series.
                    # TODO(NSE-XBRL-Sch-VII): swap to real advances series.
                    _bm_advances_yoy = _compute_yoy(_ta_series[0], _ta_series[1])
                if len(_tl_series) >= 2:
                    # Total liabilities YoY as a proxy for deposits YoY —
                    # deposits are the dominant liability. Replace with
                    # Schedule V deposits when extraction lands.
                    # TODO(NSE-XBRL-Sch-V): swap to real deposits series.
                    _bm_deposits_yoy = _compute_yoy(_tl_series[0], _tl_series[1])

                # NIM — will return None today (inputs are NULL), surfaces
                # as soon as Schedule A/B extraction populates them.
                _bm_nim = _compute_nim(
                    _bm.get("interest_earned"),
                    _bm.get("interest_expended"),
                    _bm.get("total_assets"),
                )
                # TODO(NSE-XBRL-Sch-XI): populate _bm_car from Schedule XI
                # (Capital Adequacy). Until then CAR stays None and the
                # frontend renders "—". The hex_service Safety axis
                # already handles the bank branch independently.
                # TODO(NSE-XBRL-Sch-XVIII): populate _bm_nnpa from
                # Schedule XVIII (Asset Classification).
                # TODO(NSE-XBRL-Sch-V-split): populate _bm_casa from
                # Schedule V (Deposits — current/savings/term split).

        # ── Phase 2.1 ratios ─────────────────────────────────
        # All new fields are Optional in QualityOutput; when data is
        # missing they stay None and render as "—" in the frontend.
        from backend.services.ratios_service import (
            compute_current_ratio as _cr,
            compute_asset_turnover as _at,
            compute_revenue_cagr as _rcagr,
        )

        # FIX-CURRENT-RATIO-UNIT (2026-04-22): same pattern as ROCE.
        # enriched.current_assets is in raw INR (trillions), DB
        # current_liabilities is in Crores. Mixing them produces either
        # None (when enriched.cl is missing — common) or a nonsense
        # ratio. Prefer DB values for both inputs when available so the
        # ratio stays unit-consistent.
        _ca_db = _fetch_current_assets(ticker)
        _ca_for_ratio = _ca_db if _ca_db is not None else enriched.get("current_assets")
        _cl_for_ratio = _cl_db if _cl_db is not None else enriched.get("current_liabilities")
        _current_ratio = _cr(_ca_for_ratio, _cl_for_ratio)
        _asset_turnover = _at(
            enriched.get("latest_revenue") or enriched.get("revenue"),
            _total_assets,
        )
        _rev_cagr_3y = None
        _rev_cagr_5y = None
        try:
            _inc = enriched.get("income_df")
            if _inc is not None and hasattr(_inc, "empty") and not _inc.empty \
                    and "revenue" in _inc.columns:
                _rev_series = _inc["revenue"].dropna().tolist()
                _rev_cagr_3y = _rcagr(_rev_series, 3)
                _rev_cagr_5y = _rcagr(_rev_series, 5)
        except Exception:
            pass
        # Sanity clamp: CAGR outside ±50% is almost certainly a data
        # artifact (currency conversion error, one-off spinoff/demerger,
        # bad yfinance row). Audit feedback: HCLTECH showed -75.5% 3y
        # CAGR, but its real 3y CAGR is +7-10%. Clamp to None so the
        # UI renders "—" instead of an obviously-wrong -75%. Real
        # business CAGR outside ±50% for established companies would
        # have a manual review anyway (likely a special situation).
        def _sanitize_cagr(v):
            if v is None:
                return None
            try:
                return None if abs(float(v)) > 0.50 else v
            except (TypeError, ValueError):
                return None
        _rev_cagr_3y = _sanitize_cagr(_rev_cagr_3y)
        _rev_cagr_5y = _sanitize_cagr(_rev_cagr_5y)

        # ── DEFERRED STRUCTURED FLAG BUILD (FIX-DAY3-STRENGTHS) ──
        # Inject newly-computed ratios into ``enriched`` so the
        # info-flag rules in utils._add_flags can read them. These
        # keys were not previously on enriched (they live on the
        # QualityOutput object instead), so overwriting is safe.
        # ROCE is written as-is (already a percent, e.g. 36.9).
        # CAGRs are written as decimals (the convention used
        # elsewhere in enriched, e.g. enriched['revenue_growth']).
        try:
            enriched["roce"] = _roce_val
            enriched["revenue_cagr_3y"] = _rev_cagr_3y
            enriched["revenue_cagr_5y"] = _rev_cagr_5y
            enriched["interest_coverage"] = _interest_cov_val
            # debt_to_equity: derive if missing. enriched may already
            # have it from yfinance info.
            if enriched.get("debt_to_equity") is None:
                _eq = enriched.get("total_equity") or 0
                _td = enriched.get("total_debt") or 0
                if _eq and _eq > 0:
                    enriched["debt_to_equity"] = _td / _eq
            enriched["ticker"] = ticker
            # Tag regulated utilities for downstream analytical notes.
            # Mirrors REGULATED_UTILITY_TICKERS in models/industry_wacc.py.
            try:
                from models.industry_wacc import REGULATED_UTILITY_TICKERS
                _t_bare = ticker.upper().replace(".NS", "").replace(".BO", "")
                enriched["is_regulated_utility"] = _t_bare in REGULATED_UTILITY_TICKERS
            except Exception:
                enriched["is_regulated_utility"] = False
        except Exception:
            pass

        try:
            _structured_flags = _build_structured_flags(
                enriched=enriched,
                piotroski=piotroski,
                moat_result=moat_result,
                is_financial=is_financial,
                existing_flags=_red_flags,
                price=price,
                mos_pct=mos_pct,
            )
        except Exception:
            _structured_flags = []

        # Enterprise Value in Crores: market_cap_cr + debt − cash.
        # market_cap not in enriched — derive from price × shares.
        _ent_val_cr: float | None = None
        try:
            _mcap_cr = (float(price) * float(_shares)) / 1e7 if _shares else None
            if _mcap_cr is not None:
                _ent_val_cr = round(_mcap_cr + _total_debt - _total_cash, 0)
        except Exception:
            _ent_val_cr = None

        # ── Shareholding breakdown ────────────────────────────
        # Aiven shareholding_pattern table is the primary source.
        # If promoter_pct is missing, fall back to yfinance
        # `heldPercentInsiders` which maps closely to promoter holding
        # for Indian listings (not a perfect match — US-registered
        # names may report SEC-defined insiders, so only use when the
        # primary source is empty).
        _sh = _query_shareholding(ticker) or {}
        if _sh.get("promoter_pct") is None:
            try:
                _yf_insiders = None
                # 1) already-fetched yfinance info in `raw`
                for _k in ("heldPercentInsiders", "held_percent_insiders"):
                    if raw.get(_k) is not None:
                        _yf_insiders = float(raw.get(_k))
                        break
                # 2) last-resort live yfinance lookup (cheap, cached by yf)
                if _yf_insiders is None:
                    try:
                        import yfinance as _yf
                        _info = _yf.Ticker(ticker).info or {}
                        _v = _info.get("heldPercentInsiders")
                        if _v is not None:
                            _yf_insiders = float(_v)
                    except Exception:
                        _yf_insiders = None
                if _yf_insiders is not None:
                    # yfinance returns decimal (0.623 → 62.3%)
                    _sh["promoter_pct"] = round(_yf_insiders * 100.0, 1)
            except Exception:
                pass

        # Inform downstream consumers that a financial was valued via
        # the peer-band path — helps users interpret the fair value
        # (and disables some FCF-based red flags in the UI).
        if is_financial and locals().get("_financial_val_result"):
            _method = _financial_val_result.get("method", "p_bv_peer")
            _data_issues.append(
                f"[info] Valued via {_method} peer band — DCF not "
                f"meaningful for financials."
            )

        # ── FV stability snapshot (v35) ──────────────────────────
        # Pin every input that shaped the displayed `iv` into the
        # response (and therefore into analysis_cache.payload). Warm
        # cache hits return the cached payload byte-for-byte, so the
        # snapshot lets us reproduce the FV later without re-fetching
        # yfinance/Aiven (which drift between cold computes and were
        # the root cause of ITC/HCLTECH/INFY shifting between cache
        # states). All values are pre-computed scalars already used
        # above — this block does NOT re-fetch or re-derive.
        try:
            _ci_revenue = (
                enriched.get("latest_revenue")
                or enriched.get("revenue")
                or 0
            )
            if hasattr(_ci_revenue, "__iter__") and not isinstance(_ci_revenue, (str, bytes)):
                # `revenue` may be a Series/list — take the most recent
                try:
                    _ci_revenue = float(list(_ci_revenue)[-1])
                except Exception:
                    _ci_revenue = 0
            _computation_inputs = {
                "code_version": "fv-stability-v1",
                "computed_at": _ts,
                "data_source": _data_source,
                "current_price": float(price or 0),
                "shares_outstanding": float(enriched.get("shares") or 0),
                "revenue_ttm": float(_ci_revenue or 0),
                "ebit_ttm": float(enriched.get("ebit") or 0),
                "fcf_ttm": float(enriched.get("latest_fcf") or 0),
                "pat_ttm": float(enriched.get("latest_pat") or 0),
                "total_debt": float(enriched.get("total_debt") or 0),
                "total_cash": float(enriched.get("total_cash") or 0),
                "wacc": float(wacc or 0),
                "terminal_growth": float(terminal_g or 0),
                "base_growth": float(base_growth or 0),
                "iv_raw_pre_moat": float(locals().get("iv_raw") or 0),
                "iv_post_moat": float(iv or 0),
                "moat_grade": moat_result.get("grade", "None"),
                "valuation_model": "pb_ratio" if is_financial else "dcf",
                "is_financial": bool(is_financial),
                "cache_version": CACHE_VERSION,
            }
        except Exception:
            _computation_inputs = None

        # ── PR #69: contextual analytical notes ──────────────────
        # Rule-based flags (premium brand / conglomerate / cyclical
        # trough / post-merger / regulated utility / high-P/E /
        # ADR). Pattern-matched — no hardcoded ticker maintenance
        # beyond the tiny conglomerate allowlist. Purely additive;
        # failure here must never break the response.
        _analytical_notes: list[AnalyticalNoteOutput] = []
        try:
            _note_enriched = dict(enriched) if isinstance(enriched, dict) else {}
            _note_enriched.setdefault("ticker", ticker)
            _note_metrics: dict = {}
            _raw_notes = _compute_analytical_notes(
                _note_enriched,
                {"ticker": ticker, "sector": company.sector},
                _note_metrics,
            )
            _analytical_notes = [
                AnalyticalNoteOutput(**n.to_dict()) for n in _raw_notes
            ]
        except Exception:
            _analytical_notes = []

        return AnalysisResponse(
            ticker=ticker,
            company=company,
            valuation=ValuationOutput(
                fair_value=round(iv, 2),
                current_price=round(price, 2),
                margin_of_safety=round(mos_pct, 1),
                margin_of_safety_display=round(min(mos_pct, 80), 1),
                mos_is_extreme=mos_pct > 80,
                mos_extreme_note=(
                    "Model shows significant undervaluation. "
                    "This may reflect sector-specific factors. "
                    "Verify assumptions before acting."
                ) if mos_pct > 80 else None,
                verdict=verdict,
                bear_case=_bear_case,
                base_case=_base_case,
                bull_case=_bull_case,
                # All rates returned as DECIMALS (0.12 for 12%) — frontend multiplies by 100 for display
                wacc=round(wacc, 4),
                terminal_growth=round(terminal_g, 4),
                fcf_growth_rate=round(enriched.get("fcf_growth", 0), 4),
                confidence_score=(
                    _financial_val_result["confidence_score"]
                    if is_financial and locals().get("_financial_val_result")
                    else confidence.get("score", 50)
                ),
                wacc_industry_min=round(max(0.06, wacc - 0.02), 4),
                wacc_industry_max=round(min(0.16, wacc + 0.02), 4),
                fcf_growth_historical_avg=round(enriched.get("fcf_growth", 0) * 0.9, 4),
                tv_pct_of_ev=round(dcf_res.get("tv_pct_of_ev", 0) * 100, 1),
                dcf_reliable=False if is_financial else enriched.get("dcf_reliable", True),
                valuation_model="pb_ratio" if is_financial else "dcf",
                reliability_score=dcf_res.get("reliability_score", 100),
                pv_fcfs=round(dcf_res.get("sum_pv_fcfs", 0), 0),
                pv_terminal=round(dcf_res.get("pv_tv", 0), 0),
                enterprise_value=round(dcf_res.get("enterprise_value", 0), 0),
                equity_value=round(dcf_res.get("equity_value", 0), 0),
                fcf_data_source=_fcf_data_source,
                # feat/freshness-stamps: compute timestamp marks when
                # the price was pulled from upstream (yfinance/NSE
                # Parquet). Both are delayed — frontend renders as
                # "Delayed", never "Live". See FreshnessStamp.tsx.
                current_price_as_of=_ts,
                # feat/peer-cap (2026-04-27): peer-multiple sanity
                # ceiling. fair_value_source flips to "peer_capped"
                # when the cap fires; details carry the audit trail.
                fair_value_source=_fair_value_source,
                peer_cap_details=_peer_cap_details,
            ),
            quality=QualityOutput(
                yieldiq_score=yiq_score.get("score", 0),
                grade=yiq_score.get("grade", "C"),
                piotroski_score=piotroski.get("score", 0),
                piotroski_grade=piotroski.get("grade", ""),
                earnings_quality_grade=eq_result.get("grade", "N/A"),
                earnings_quality_score=eq_result.get("score", 0),
                moat=moat_result.get("grade", "None"),
                moat_score=moat_result.get("score", 0),
                momentum_score=momentum_result.get("momentum_score", 0),
                momentum_grade=momentum_result.get("grade", "N/A"),
                fundamental_score=fund_result.get("score", 0),
                fundamental_grade=fund_result.get("grade", "N/A"),
                # ROE/ROCE: return as PERCENTAGE (frontend displays directly with %)
                # yfinance returns decimals (0.23), Aiven sometimes percentages — normalize.
                roe=_normalize_pct(enriched.get("roe") or _compute_roe_fallback(enriched)),
                de_ratio=enriched.get("de_ratio"),
                roce=_normalize_pct(_roce_val),
                debt_ebitda=_debt_ebitda_val,
                debt_ebitda_label=_debt_ebitda_lbl,
                interest_coverage=_interest_cov_val,
                enterprise_value=_ent_val_cr,
                current_ratio=_current_ratio,
                asset_turnover=_asset_turnover,
                revenue_cagr_3y=_rev_cagr_3y,
                revenue_cagr_5y=_rev_cagr_5y,
                promoter_pct=_sh.get("promoter_pct"),
                promoter_pledge_pct=_sh.get("promoter_pledge_pct"),
                fii_pct=_sh.get("fii_pct"),
                dii_pct=_sh.get("dii_pct"),
                public_pct=_sh.get("public_pct"),
                # Bank-native metrics — None for non-banks. See
                # docs/bank_data_availability.md for the coverage matrix.
                is_bank=_is_bank_like,
                roa=_bm_roa,
                cost_to_income=_bm_cost_to_income,
                advances_yoy=_bm_advances_yoy,
                deposits_yoy=_bm_deposits_yoy,
                revenue_yoy_bank=_bm_revenue_yoy,
                pat_yoy_bank=_bm_pat_yoy,
                nim=_bm_nim,
                car=_bm_car,
                nnpa=_bm_nnpa,
                casa=_bm_casa,
                # feat/freshness-stamps: most recent filing period_end
                # from the enriched bundle. Key names vary across data
                # paths (local DB vs yfinance collector); probe a few.
                latest_filing_period_end=(
                    enriched.get("latest_period_end")
                    or enriched.get("period_end")
                    or enriched.get("latest_filing_period_end")
                    or None
                ),
            ),
            insights=InsightCards(
                patience_months=hp.get("min_months"),
                red_flag_count=len(_red_flags),
                red_flags=_red_flags[:5],
                red_flags_structured=_structured_flags,
                dividend=_dividend_data,
                earnings_date=_earnings_date,
                earnings_est_eps=raw.get("finnhub_next_earnings", {}).get("eps_estimate"),
                earnings_days_until=earnings_days_until,
                wall_street_avg_target=(raw.get("finnhub_price_target") or {}).get("mean"),
                wall_street_target_count=(raw.get("finnhub_price_target") or {}).get("count"),
                insider_net_sentiment=(raw.get("finnhub_insider") or {}).get("sentiment"),
                market_expectations_growth=rdcf.get("implied_growth"),
                fcf_yield=fcf_yield.get("fcf_yield"),
                ev_ebitda=_clamp_ev_ebitda(eveb.get("current_ev_ebitda") or enriched.get("ev_to_ebitda")),
                reverse_dcf_implied_growth=rdcf.get("implied_growth"),
                bulk_deals=_bulk_deals,
                # feat/freshness-stamps: Finnhub's /price-target
                # endpoint doesn't expose a last-updated field on the
                # free tier. Stamp with the compute timestamp whenever
                # any target data is present; otherwise None so the
                # frontend won't render a misleading freshness line.
                analyst_target_as_of=(
                    _ts
                    if (raw.get("finnhub_price_target") or {}).get("mean")
                    else None
                ),
            ),
            scenarios=_scenarios_clamped,
            price_levels=PriceLevels(
                entry_signal=assign_signal(mos_pct / 100, reliability_score=dcf_res.get("reliability_score", 100)),
                discount_zone=pt.get("buy_price"),
                model_estimate=pt.get("target_price"),
                downside_range=pt.get("stop_loss"),
                risk_reward_ratio=pt.get("rr_ratio"),
                holding_period=hp.get("label"),
            ),
            data_confidence=_confidence,
            data_issues=_data_issues,
            analytical_notes=_analytical_notes,
            timestamp=_ts,
            computation_inputs=_computation_inputs,
        )


    def get_reverse_dcf(
        self,
        ticker: str,
        wacc_override: float | None = None,
        terminal_g_override: float | None = None,
        years: int = 10,
    ) -> dict:
        """
        Compute reverse DCF analysis for a ticker.
        Optionally allows user-adjustable WACC and terminal growth.
        Runs full analysis pipeline to get enriched data, then
        runs reverse DCF with specified (or default) assumptions.
        """
        # Run full analysis to populate enriched dict (uses cache)
        analysis = self.get_full_analysis(ticker)

        # Get raw enriched data — we need to re-fetch to get the dict
        # since AnalysisResponse doesn't expose it. Use cache.
        import logging as _log
        logger = _log.getLogger("yieldiq.reverse_dcf")

        # Re-run the enrichment step (fast, uses local assembler + cache)
        try:
            from backend.services.local_data_service import assemble_local
            _db = _get_pipeline_session()
            raw = None
            if _db is not None:
                try:
                    raw = assemble_local(ticker, _db)
                except Exception:
                    raw = None
                finally:
                    try:
                        _db.close()
                    except Exception:
                        pass
            if raw is None:
                from data.collector import StockDataCollector
                raw = StockDataCollector(ticker).get_all()
        except Exception as exc:
            logger.warning(f"[{ticker}] Failed to assemble raw data: {exc}")
            return {"ticker": ticker, "error": "Unable to fetch company data"}

        try:
            # compute_metrics is imported at top of this module
            enriched = compute_metrics(raw)
        except Exception as exc:
            logger.warning(f"[{ticker}] compute_metrics failed: {exc}")
            enriched = raw

        # Use override values or pull from analysis
        wacc = wacc_override if wacc_override is not None else analysis.valuation.wacc
        terminal_g = terminal_g_override if terminal_g_override is not None else analysis.valuation.terminal_growth
        current_price = analysis.valuation.current_price

        try:
            result = run_reverse_dcf(enriched, current_price, wacc, terminal_g, years=years)
            return result
        except Exception as exc:
            logger.warning(f"[{ticker}] reverse DCF failed: {exc}")
            return {"ticker": ticker, "error": str(exc)}
