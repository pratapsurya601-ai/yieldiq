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
    AnalystConsensus, AnalystRatingDistribution, AnalystPriceTarget,
    AnalystEpsEstimate,
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
# PR #316: sanity-bound shares before both DCF and cache storage so
# `equity_value ÷ stored_shares` always equals `iv_raw_pre_moat`.
from backend.validators.shares_outstanding import shares_or_warn
# Per-ticker overrides for unusual businesses (conglomerates, holdcos,
# turnarounds, pre-profit names). Surfaces honest "model approximate"
# caveats. ROADMAP: build sum-of-parts engine for RELIANCE/ITC/holdcos.
# Currently surfaces caveat banner. See: ticker_overrides.py.
from backend.services.analysis.ticker_overrides import get_override as _get_ticker_override

# ── Import existing engines (NO rewrites) ─────────────────────
from data.collector import StockDataCollector
from data.processor import compute_metrics
from data.validator import validate_stock_data
from models.forecaster import (
    FCFForecaster,
    compute_confidence_score,
    compute_confidence_score_v2,
    confidence_v2_enabled,
)
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal, buffett_mos_pct,
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

# Phase C.2 PR 2 (2026-05-25): hard-import the canonical scoring
# function. The prior `try/except Exception: def compute_yieldiq_score`
# block hid a 4-line MOCK with different weights (40/30/20/10, no
# moat awareness) under the same symbol name. The dashboard package
# ships in the backend Docker image — if this import ever fails it
# is a deploy bug that must surface at boot, not be papered over
# with a divergent scoring formula at runtime. See
# docs/diagnostics/phase-c-score-formula-2026-05-25.md §4 Quirk #3.
from dashboard.utils.scoring import compute_yieldiq_score


# ── Subpackage siblings (constants/utils/db/narrative) ────
from backend.services.analysis.constants import (
    FINANCIAL_COMPANIES,
    INVENTORY_HEAVY_TICKERS,
    is_cyclical,
    is_bank_like,
    is_etf,
    is_fmcg_sector,
    is_reit,
    is_invit,
    is_realty_developer,
    is_regulated_utility,
    is_defense_psu,
    get_brand_moat_multiplier,
    COMPANY_NAME_OVERRIDES,
    _PB_MEDIANS,
    _NBFC_TICKERS,
    is_top_private_bank,
    TOP_PRIVATE_BANK_COE,
    TOP_PRIVATE_BANKS,
    NEVER_SUPER_CYCLICAL,
    TICKER_SECTOR_OVERRIDES,
    _INSURANCE_TICKERS,
)


def _try_insurance_appraisal(ticker: str, shares):
    """Thin wrapper around
    ``insurance_appraisal_service.get_appraisal_fair_value_for_ticker``
    that swallows exceptions so a broken DB / missing migration never
    crashes the analysis pipeline — at worst the ticker falls through
    to the existing P/BV path (which is the current production
    behaviour pre-PR).
    """
    try:
        from backend.services.insurance_appraisal_service import (
            get_appraisal_fair_value_for_ticker,
        )
        return get_appraisal_fair_value_for_ticker(ticker, shares)
    except Exception as exc:
        import logging as _log
        _log.getLogger("yieldiq.analysis").warning(
            "[%s] insurance_appraisal lookup failed: %s: %s",
            ticker, type(exc).__name__, exc,
        )
        return None

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
    display_mos,
    _yf_compute_roe_from_statements,
    _normalize_pct,
    _compute_roe_fallback,
    _build_structured_flags,
    _debt_ebitda_label,
    _safe_float,
    _safe_div_1e7,
)
from backend.services.analysis.ipo_framework import (
    MIN_ANNUAL_REPORTS_FOR_DCF as _IPO_MIN_ANNUAL_REPORTS,
    compute_sector_relative_fv as _ipo_compute_sector_relative_fv,
    is_recent_ipo as _ipo_is_recent_ipo,
    ipo_caveat as _ipo_caveat,
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
    _fetch_de_ratio,
)
from backend.services.analysis.narrative import NarrativeMixin

# ── Tier 2 cohort valuation (Layer B Week 1) ─────────────────────
# Feature-flagged via TIER2_ENABLED env var (default False).  When
# the flag is False this import is a no-op — the routing branch
# below short-circuits before calling any Tier 2 code.  See
# docs/design/valuation-architecture-simplification.md §2.2 and
# backend/services/tier2_cohort_valuation_service.py for the math.
from backend.services.tier2_cohort_valuation_service import (
    compute_tier2_fair_value,
    is_tier2_skip_sector,
    tier2_caveat,
    tier2_enabled,
)


def _fetch_tier2_peer_metrics_map(
    peer_tickers: list[str],
) -> dict[str, dict]:
    """Read cached ROCE / Piotroski / market_cap_cr for the given peers
    from the `tier2_peer_metrics` table (populated by
    `scripts/enrich_tier2_peer_metrics.py`).

    Returns a dict keyed by the EXACT peer ticker string used in
    DIRECT_PEERS (e.g. ``TCS.NS``). Peers missing from the table simply
    won't appear in the dict — callers MUST default missing peers to
    the Tail bucket (current behaviour, no regression).

    Read-only and best-effort: any DB failure returns {} so the caller
    falls back to the pre-existing Tail-default path.
    """
    if not peer_tickers:
        return {}
    try:
        from backend.services.analysis.db import _get_pipeline_session
        from sqlalchemy import text as _text
    except Exception:
        return {}
    db = _get_pipeline_session()
    if db is None:
        return {}
    try:
        rows = db.execute(_text("""
            SELECT ticker, roce_pct, piotroski,
                   market_cap_cr, quality_bucket
            FROM tier2_peer_metrics
            WHERE ticker = ANY(:tickers)
        """), {"tickers": list(peer_tickers)}).mappings().all()
        return {r["ticker"]: dict(r) for r in rows}
    except Exception as exc:
        import logging as _l
        _l.getLogger("yieldiq.analysis").debug(
            "tier2_peer_metrics fetch failed: %s", exc,
        )
        return {}
    finally:
        try:
            db.close()
        except Exception:
            pass


def _build_tier2_peers_from_sector_relative(
    ticker: str,
) -> list[dict]:
    """Best-effort builder of a peer list for Tier 2 from existing
    sector_relative DIRECT_PEERS + the live yfinance peer fetcher.

    Returns [] on any failure — Tier 2 then returns None and the
    caller falls back to generic DCF.

    Quality fields (roce / piotroski / market_cap_cr) are joined in
    from the ``tier2_peer_metrics`` cache table when present so that
    quality bucketing actually fires for the curated cohort. Peers
    missing from the cache fall through to the historical
    all-fields-None path → Tail bucket (no regression vs flag-off
    pre-cache behaviour).
    """
    try:
        from screener.sector_relative import (
            get_peers_for_ticker, _fetch_peer_metrics,
        )
    except Exception:
        return []
    peers = get_peers_for_ticker(ticker)
    if not peers:
        return []
    try:
        live = _fetch_peer_metrics(peers, exclude_ticker=ticker)
    except Exception:
        live = []

    # Pull the cached quality metrics for ALL curated peer tickers
    # (not just the ones the live fetcher returned, in case the live
    # row uses a slightly different ticker form).
    metrics_map = _fetch_tier2_peer_metrics_map(peers)

    out: list[dict] = []
    for row in live or []:
        peer_t = row.get("ticker")
        # Look up by exact key first, then by the .NS-suffixed form
        # (DIRECT_PEERS stores .NS / .BO; live fetcher sometimes
        # strips suffixes).
        cached = (
            metrics_map.get(peer_t)
            or metrics_map.get(f"{peer_t}.NS")
            or metrics_map.get(f"{peer_t}.BO")
            or {}
        )

        def _num(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        out.append({
            "ticker": peer_t,
            "pe": row.get("pe"),
            "ev_ebitda": row.get("ev_ebitda"),
            "roce": _num(cached.get("roce_pct")),
            "piotroski": (
                int(cached["piotroski"])
                if cached.get("piotroski") is not None else None
            ),
            "market_cap_cr": _num(cached.get("market_cap_cr")),
        })
    return out


def compute_tier2_for_ticker(
    ticker: str,
    sector: Optional[str] = None,
) -> Optional[dict]:
    """Standalone Tier 2 cohort fair-value computation for a single ticker.

    This is the wiring helper consumed by the Tier 2 head-to-head
    reconciliation harness (``scripts/tier2_head_to_head.py``). It is
    DELIBERATELY decoupled from the main ``analyze_stock`` routing tree
    so the harness can compute a Tier 2 FV on demand without bumping
    CACHE_VERSION, without flipping ``TIER2_ENABLED``, and without
    exercising the ~115 lines of cohort plumbing inside the live
    request path.

    Contract:
      * Returns ``{"fair_value": float, "confidence_score": int,
                   "bucket": str, ...}`` on success (full dict from
        ``compute_tier2_fair_value`` plus a flattened ``bucket`` key
        promoted out of ``_meta`` for harness convenience).
      * Returns ``None`` for skip-sectors (banking / NBFC / insurance /
        regulated utilities / REITs / ETFs / holdcos), unknown tickers,
        loss-making tickers, cohort size < 5 even after widening, or
        ANY data-source / DB failure.
      * Never raises. Every error path degrades to ``None`` and logs
        at DEBUG so the harness keeps marching across the universe.

    Args:
      ticker : bare or .NS/.BO-suffixed symbol. Canonicalized to the
               same form used everywhere else in the analysis service.
      sector : optional sector override; if omitted the helper resolves
               it via the same ``_resolve_sector`` plumbing used by the
               live analysis path.
    """
    import logging as _log
    _logger = _log.getLogger("yieldiq.analysis.tier2_helper")

    if not ticker:
        return None

    try:
        clean_ticker = _canonicalize_ticker(ticker)
    except Exception:
        clean_ticker = ticker

    try:
        # ── Fetch raw + enriched financials for the ticker itself ──
        try:
            raw = StockDataCollector(clean_ticker).get_all()
        except Exception as exc:
            _logger.debug(
                "tier2_helper[%s]: collector failed: %s: %s",
                clean_ticker, type(exc).__name__, exc,
            )
            return None
        if not raw:
            return None

        try:
            enriched = compute_metrics(raw) or {}
        except Exception:
            enriched = raw or {}

        # ── Sector resolution + skip-sector short-circuit ──
        _raw_sector = enriched.get("sector") or raw.get("sector")
        try:
            resolved_sector = sector or _resolve_sector(
                _raw_sector, clean_ticker,
            )
        except Exception:
            resolved_sector = sector or _raw_sector

        if is_tier2_skip_sector(resolved_sector):
            _logger.debug(
                "tier2_helper[%s]: skip-sector %s",
                clean_ticker, resolved_sector,
            )
            return None

        # ── Piotroski (best-effort; falls back to None → Tail) ──
        try:
            _piotroski = compute_piotroski_fscore(enriched)
            if isinstance(_piotroski, dict):
                _piotroski = (
                    _piotroski.get("fscore") or _piotroski.get("score")
                )
        except Exception:
            _piotroski = None

        price = enriched.get("price", 0) or raw.get("price", 0) or 0
        eps = (
            enriched.get("diluted_eps")
            or raw.get("trailingEps")
            or enriched.get("eps")
            or raw.get("fh_eps_ttm")
        )
        shares = enriched.get("shares") or raw.get("shares", 0) or 0
        try:
            mcap_cr = (float(price or 0) * float(shares or 0)) / 1e7
        except (TypeError, ValueError):
            mcap_cr = 0.0

        financials = {
            "eps": eps,
            "ebitda": (
                enriched.get("ebitda") or enriched.get("latest_ebitda")
            ),
            "shares": shares,
            "roce": enriched.get("roce_pct") or enriched.get("roce"),
            "piotroski": _piotroski,
            "market_cap_cr": mcap_cr,
            "bvps": (
                enriched.get("book_value_per_share")
                or enriched.get("bvps")
            ),
            "net_debt_cr": (
                (enriched.get("total_debt", 0) or 0)
                - (enriched.get("total_cash", 0) or 0)
            ) / 1e7,
            "current_price": price,
        }

        # ── Peer cohort via the shared sector-relative helper ──
        try:
            peers = _build_tier2_peers_from_sector_relative(clean_ticker)
        except Exception as exc:
            _logger.debug(
                "tier2_helper[%s]: peer build failed: %s",
                clean_ticker, exc,
            )
            peers = []

        # ── Cohort FV ──
        result = compute_tier2_fair_value(
            ticker=clean_ticker,
            sector=resolved_sector,
            financials=financials,
            peers=peers,
        )
        if not result:
            return None

        bucket = (result.get("_meta") or {}).get("bucket")
        out = dict(result)
        out["bucket"] = bucket
        return out
    except Exception as exc:  # final defensive net — never raise
        _logger.debug(
            "tier2_helper[%s]: unexpected failure: %s: %s",
            clean_ticker, type(exc).__name__, exc,
        )
        return None


def _build_implied_assumptions_dict(
    rdcf: dict | None,
    enriched: dict,
    ticker: str,
    current_price: float,
    wacc: float,
    terminal_g: float,
    rev_cagr_3y: float | None,
) -> dict | None:
    """Build the rich-framing implied-assumptions payload (additive).

    Layered on top of the existing reverse_dcf_service so the surface
    cost is one extra dict per analysis response. Failures degrade to
    None — the frontend hides the card when the field is missing, so
    a partial / broken implied-assumptions block never blocks the
    rest of the analysis response.

    The implied-growth number we surface is taken from `rdcf` when
    available (byte-identical to the existing
    `valuation.reverse_dcf_implied_growth` / `insights.reverse_dcf_*`
    fields). When the upstream rdcf is empty (skipped for financials,
    holdcos, etc.) we fall back to the standalone solver — same math,
    just rerouted so the implied number is internally consistent.
    """
    try:
        from backend.services.reverse_dcf_service import (
            compute_implied_assumptions,
            implied_assumptions_to_dict,
        )

        # Pull historical anchor from the same source the rest of the
        # response uses so the card never diverges from the Quality
        # metric chip ("Revenue CAGR (3y)") on the same page.
        hist = rev_cagr_3y if rev_cagr_3y is not None else enriched.get("revenue_cagr_3y")
        hist = float(hist) if hist is not None else 0.0

        # Consensus — the existing pipeline does not carry a separate
        # "analyst revenue CAGR consensus" field. We pass None so the
        # card's "vs consensus" headline degrades to the historical-
        # anchor variant ("vs trailing X%"). A future enhancement can
        # wire a consensus source (Finnhub estimates, broker scrape)
        # through the same field.
        consensus = enriched.get("consensus_revenue_cagr")
        consensus_val = float(consensus) if consensus is not None else None

        base_fcf = float(
            enriched.get("normalized_fcf_base")
            or enriched.get("latest_fcf")
            or 0.0
        )
        shares = float(enriched.get("shares") or 0.0)
        total_debt = float(enriched.get("total_debt") or 0.0)
        total_cash = float(enriched.get("total_cash") or 0.0)
        current_revenue = enriched.get("latest_revenue")
        current_margin = enriched.get("op_margin") or enriched.get("fcf_margin")
        historical_margin = enriched.get("normalized_fcf_margin")

        result = compute_implied_assumptions(
            current_price=float(current_price),
            base_fcf=base_fcf,
            shares=shares,
            historical_revenue_cagr_3y=hist,
            consensus_revenue_cagr=consensus_val,
            wacc=float(wacc),
            terminal_growth=float(terminal_g),
            current_margin=(float(current_margin) if current_margin is not None else None),
            historical_margin=(float(historical_margin) if historical_margin is not None else None),
            sector=enriched.get("sector"),
            total_debt=total_debt,
            total_cash=total_cash,
            current_revenue=(float(current_revenue) if current_revenue is not None else None),
            ticker=ticker,
        )
        return implied_assumptions_to_dict(result)
    except Exception as exc:
        # Never let an additive surface 500 the response. The
        # observability mirror lives behind the structured logger so
        # we still see failures in prod without affecting payload
        # construction.
        try:
            import logging as _ia_log
            _ia_log.getLogger("yieldiq.analysis.implied_assumptions").warning(
                "implied_assumptions[%s] build failed (%s: %s) -- returning None",
                ticker, type(exc).__name__, exc,
            )
        except Exception:
            pass
        return None


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
            # promote the verdict to "data_limited". Previously only the
            # public /stock-summary endpoint applied this gate (via
            # check_and_quarantine), so the authed /analysis endpoint
            # kept shipping the raw bad-DCF verdict to admin callers and
            # the canary harness. That caused gate-5 false positives and
            # 606 Sentry events on TMPV. Promoting verdict here keeps the
            # full response shape (admin can still see all fields + the
            # data_issues list above) but signals the state consistently
            # across all endpoints so downstream code (canary's
            # _has_no_dcf, frontend render branches) handles it correctly.
            #
            # FIX-ANTHEM-500 (2026-06-09, P0): the prior emission of
            # "under_review" violated ValuationOutput.verdict's Literal[…]
            # in backend/models/responses.py (allowed set is
            # undervalued|fairly_valued|overvalued|avoid|data_limited|
            # unavailable). The downstream re-validation path (FastAPI
            # response_model serialization + Pydantic model reconstruction)
            # raised ValidationError → 500 on every cache-miss recompute
            # for tickers that hit this branch (ANTHEM observed in
            # Railway logs). Same precedent as confidence_service.py
            # L644-673 Audit#7 P0 fix — clamp to a valid literal rather
            # than widening the enum (which would touch validators,
            # og-data, push, email-alerts, analytics, and every cached
            # row). Frontend already handles `data_limited` correctly
            # (see frontend/src/lib/verdict.ts: "Insufficient Data" /
            # "warn" tone) so user impact is graceful — the response
            # surfaces with caveat + data_issues instead of a 500.
            if not vr.ok and vr.severity == "critical":
                try:
                    if getattr(result, "valuation", None) is not None:
                        result.valuation.verdict = "data_limited"
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

        # ── Bulls Say / Bears Say (P0 #4, 2026-05-25) ─────────────
        # Generate 3-bullet structured narratives from the assembled
        # response. Pure rules + templates (no LLM cost), SEBI-safe
        # by construction (verified in test_bulls_bears_generator).
        # Failures are non-fatal — frontend renders an empty state.
        try:
            from backend.services.analysis.bulls_bears_generator import (
                generate_bulls_bears,
            )
            # v_238: pass the FV compute timestamp so the generator
            # can stamp the panel with "Updated <Month YYYY>" (matches
            # the dated-note convention competitor research notes use).
            _val = getattr(result, "valuation", None)
            _computed_at = getattr(_val, "fair_value_computed_at", None)
            bb = generate_bulls_bears(
                valuation=_val,
                quality=getattr(result, "quality", None),
                insights=getattr(result, "insights", None),
                scenarios=getattr(result, "scenarios", None),
                ar_signals=None,  # not currently surfaced on AnalysisResponse
                computed_at=_computed_at,
            )
            _updates = {
                "bulls_say": bb.get("bulls") or None,
                "bears_say": bb.get("bears") or None,
                "bull_case_narrative": bb.get("bull_case_narrative"),
                "bear_case_narrative": bb.get("bear_case_narrative"),
                "thesis_updated": bb.get("thesis_updated"),
            }
            try:
                for _k, _v in _updates.items():
                    setattr(result, _k, _v)
            except Exception:
                result = result.model_copy(update=_updates)
        except Exception as _bbe:
            import logging as _bbl
            _bbl.getLogger("yieldiq.bulls_bears").warning(
                f"bulls/bears generation crashed for {ticker}: "
                f"{type(_bbe).__name__}: {_bbe}"
            )

        # ── The Honest Card (Phase 3 manifesto, 2026-05-25) ───────
        # Build the radical-transparency panel. Pure rules + templates
        # (no LLM), SEBI-safe by construction. Non-fatal on failure —
        # frontend simply hides the section when honest_card is None.
        try:
            from backend.services.analysis.honest_card_generator import (
                generate_honest_card,
            )
            from backend.models.responses import HonestCardOutput
            hc = generate_honest_card(
                valuation=getattr(result, "valuation", None),
                quality=getattr(result, "quality", None),
                insights=getattr(result, "insights", None),
                scenarios=getattr(result, "scenarios", None),
                company=getattr(result, "company", None),
            )
            hc_out = HonestCardOutput(**hc.to_dict())
            try:
                result.honest_card = hc_out
            except Exception:
                result = result.model_copy(update={"honest_card": hc_out})
        except Exception as _hce:
            import logging as _hcl
            _hcl.getLogger("yieldiq.honest_card").warning(
                f"honest card generation crashed for {ticker}: "
                f"{type(_hce).__name__}: {_hce}"
            )

        # ── Peer context for inline comparison sliders (Phase-3) ───
        # Pulls the same peer rows used by the Peers tab and reduces
        # them to {metric: {value, median, p5, p95, n}}. Pure helper
        # with a defensive try — never blocks the response on failure.
        peer_context_block: dict[str, dict] = {}
        try:
            from backend.services.peers_service import PeersService
            from backend.services.analysis.peer_context import build_peer_context
            try:
                from data_pipeline.db import Session as _PipelineSession
            except Exception:
                _PipelineSession = None
            _peer_db = _PipelineSession() if _PipelineSession is not None else None
            try:
                peer_payload = PeersService().get_peer_comparison(
                    ticker=ticker,
                    db=_peer_db,
                    cache=getattr(self, "cache", None),
                )
            finally:
                if _peer_db is not None:
                    try:
                        _peer_db.close()
                    except Exception:
                        pass
            if peer_payload and peer_payload.get("has_peers"):
                peer_context_block = build_peer_context(
                    ticker, peer_payload.get("peers") or []
                )
            if peer_context_block:
                try:
                    result.peer_context = peer_context_block
                except Exception:
                    result = result.model_copy(
                        update={"peer_context": peer_context_block}
                    )
        except Exception as _pce:
            import logging as _pcl
            _pcl.getLogger("yieldiq.peer_context").warning(
                f"peer_context build crashed for {ticker} "
                f"(non-fatal, slider falls back to naked values): "
                f"{type(_pce).__name__}: {_pce}"
            )

        # ── Worry Index (Phase-3, 2026-05-25) ─────────────────────
        # 0-100 emotional risk composite + tier copy. Computed AFTER
        # peer_context so the valuation-stretch sub-score can read
        # peer-relative PE. Failures are non-fatal — frontend skips
        # the gauge if the field is absent.
        try:
            from backend.services.analysis.worry_index import compute_worry_index
            wi = compute_worry_index(
                valuation=getattr(result, "valuation", None),
                quality=getattr(result, "quality", None),
                insights=getattr(result, "insights", None),
                peer_context=peer_context_block or None,
            )
            wi_dict = wi.to_dict()
            try:
                result.worry_index = wi_dict
            except Exception:
                result = result.model_copy(update={"worry_index": wi_dict})
        except Exception as _wie:
            import logging as _wil
            _wil.getLogger("yieldiq.worry_index").warning(
                f"worry_index compute crashed for {ticker}: "
                f"{type(_wie).__name__}: {_wie}"
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

        # ── Day-24 (2026-05-20): per-step latency instrumentation ─
        # Populates a dict that's attached to AnalysisResponse._timings
        # so the Day-26 perf dashboard can answer "which step dominates
        # the 2.7s cold p50?" Adds < 100ns per call (perf_counter).
        # NOT a behaviour change; pure observability.
        import time as _time_t  # local alias — `_time` is reassigned downstream in Step 1
        _t_inner_start = _time_t.perf_counter()
        _t_step = _t_inner_start
        _timings_steps: dict[str, int] = {}

        def _record_step(name: str) -> None:
            nonlocal _t_step
            now = _time_t.perf_counter()
            _timings_steps[name] = int((now - _t_step) * 1000)
            _t_step = now

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
            # Capture to Sentry so we see when local DB+Parquet assembly is
            # broken (typically Neon pipeline drift or a parquet snapshot
            # gone stale). The yfinance fallback below masks this as a
            # latency regression rather than an error in metrics.
            try:
                import sentry_sdk as _sentry
                _sentry.set_tag("ticker", ticker)
                _sentry.set_tag("stage", "local_assembler")
                _sentry.capture_exception(_local_exc)
            except Exception:
                pass

        # Fallback: yfinance collector (slow but comprehensive)
        #
        # Day-23 (2026-05-20) — tightened the retry chain.
        # Previously: 3 attempts × ~15s yfinance call + 3s + 6s sleeps
        #             = ~54s worst case. Confirmed live: 30+ tickers
        #             in analysis_cache historically took 45-62s here
        #             (BLACKBUCK, CARRARO, AIIL, MFSL, TINNARUBR,
        #             HDFCBANK, INFY, etc.).
        # Now:        2 attempts × ~15s + 1s sleep + 15s total wall-
        #             time guard = ~17s worst case before falling
        #             through to data_limited verdict. The data_
        #             limited path is HONEST UX vs. a 60s spinner.
        #
        # If yfinance is genuinely flaky for a ticker (auth flip,
        # NSE/BSE outage), 2 attempts catches transient failures
        # without burning the user's patience.
        if raw is None:
            _data_source = "yfinance"
            _last_yf_exc: Exception | None = None
            _yf_t_start = _time.perf_counter()
            _YF_WALL_BUDGET_S = 15.0
            for _attempt in range(2):
                # Wall-time guard — abort the retry loop if we've
                # already spent the budget on previous attempts.
                if (_time.perf_counter() - _yf_t_start) > _YF_WALL_BUDGET_S:
                    break
                try:
                    collector = StockDataCollector(ticker)
                    raw = collector.get_all()
                    if raw is not None:
                        break
                except Exception as _yf_exc:
                    _last_yf_exc = _yf_exc
                if raw is None and _attempt < 1:
                    # Single 1s backoff between the 2 attempts. This
                    # used to be 3s + 6s = 9s of pure sleep. Profile
                    # data shows the second attempt rarely succeeds
                    # if the first failed within the same wall-clock
                    # window — yfinance auth flips don't recover in
                    # 1-9s anyway. Keep the wall-time guard above
                    # honest.
                    _time.sleep(1.0)
            # All 3 yfinance attempts exhausted — capture so we can see
            # data-source outage patterns (yfinance auth flips, BSE delistings).
            if raw is None and _last_yf_exc is not None:
                try:
                    import sentry_sdk as _sentry
                    _sentry.set_tag("ticker", ticker)
                    _sentry.set_tag("stage", "yfinance_collector_exhausted")
                    _sentry.capture_exception(_last_yf_exc)
                except Exception:
                    pass

        _record_step("step1_fetch")

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

        _record_step("step2_validate")

        # ── Step 3: Compute metrics ───────────────────────────
        enriched = compute_metrics(raw)
        # PR #316: reconcile shares with the trusted post-normalization
        # column. `financials.shares_outstanding` is stored in mixed units
        # (lakh / crore / raw) across rows because of legacy ingest paths;
        # `shares_outstanding_raw` is the PR#136 normalizer output and is
        # always a real raw count. When present and plausible, prefer it
        # so downstream `equity_value ÷ shares` and `price × shares`
        # ratios stop being 100× off. Falls through silently for
        # yfinance-sourced `raw` (collector sets the field to None).
        _shares_raw_trusted = shares_or_warn(
            ticker, raw.get("shares_outstanding_raw")
        )
        if _shares_raw_trusted is not None:
            _shares_legacy = float(enriched.get("shares") or 0)
            if _shares_legacy <= 0 or abs(
                _shares_raw_trusted - _shares_legacy
            ) / max(_shares_raw_trusted, 1.0) > 0.01:
                import logging as _sh_log
                _sh_log.getLogger("yieldiq.analysis").info(
                    "[%s] shares reconciled: legacy=%.0f → raw=%.0f "
                    "(ratio %.2fx)",
                    ticker, _shares_legacy, _shares_raw_trusted,
                    (_shares_raw_trusted / _shares_legacy)
                    if _shares_legacy > 0 else float("nan"),
                )
            enriched["shares"] = _shares_raw_trusted
            enriched["shares_outstanding_source"] = "db_normalized_raw"
        # PR-DET-1: pinned price snapshot — do not recompute MoS on read.
        # `price` captured here is the SAME value used as both the response
        # `current_price` field (see ValuationOutput below) and the MoS
        # denominator (see `mos_pct = ((iv - price) / price * 100)` further
        # down). Any downstream code that needs "the price" must read this
        # local — never re-fetch from market_data, otherwise displayed
        # current_price and MoS will silently drift apart.
        price = enriched.get("price", 0) or 0
        # PR INFY-PRICE-CASCADE (2026-04-30): override yfinance-sourced
        # price with the canonical cascade (live_quotes → daily_prices →
        # yfinance). yfinance .info `currentPrice` produced INFY ₹0,
        # INFY ₹1,09,652, SBIN ₹1,069 in production; live_quotes for
        # the same windows had ₹1,188 / ₹819. Single source of truth
        # for the `price` snapshot used by both the response
        # `current_price` AND the MoS denominator below.
        # Task #197 (2026-05-24, feat/as-of-plumbing): also surface the
        # live_quotes.as_of timestamp so the freshness chip reads actual
        # quote age (5-15m) instead of analysis-recompute age (5h). The
        # `_live_quote_as_of` local is consumed by the ValuationOutput
        # build site further down (see `as_of=` field). None when the
        # cascade resolved from daily_prices / yfinance instead.
        _live_quote_as_of: str | None = None
        try:
            from backend.services.market_data_service import (
                get_canonical_price_with_meta,
            )
            _canonical_px, _live_quote_as_of = get_canonical_price_with_meta(
                ticker, yf_fallback=price
            )
            if _canonical_px is not None and _canonical_px > 0:
                if abs((_canonical_px or 0) - (price or 0)) > 0.01:
                    import logging as _px_log
                    _px_log.getLogger("yieldiq.analysis").info(
                        "[%s] price overridden by canonical cascade: "
                        "yf=%.2f → canonical=%.2f",
                        ticker, float(price or 0), float(_canonical_px),
                    )
                price = _canonical_px
                # Keep enriched in sync so downstream consumers
                # (market_cap, ev/ebitda denominators) see the same
                # value.
                enriched["price"] = _canonical_px
        except Exception as _px_exc:
            import logging as _px_log
            _px_log.getLogger("yieldiq.analysis").warning(
                "[%s] canonical price cascade failed (using yfinance "
                "fallback %.2f): %s",
                ticker, float(price or 0), _px_exc,
            )
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
        # ETF carve-out (PR #325 follow-up, 2026-05-18). ETFs (NIFTYBEES,
        # BANKBEES, GOLDBEES, ICICIB22 …) have NO operating fundamentals
        # by design — no revenue, no PAT, and the "shares" field is the
        # trust's units, which yfinance doesn't populate for most BeES /
        # AMC-branded ETFs. Without this carve-out the gate below fires
        # `verdict=unavailable` with market_cap=0, which then trips the
        # `market_cap_inr < 10 Cr` critical bound in validators.py and
        # the public stock-summary route quarantines as
        # `validation_critical` — bypassing the ETF short-circuit
        # (etf_nav_based) added in PR #325. Treat any allow-list /
        # keyword-detected ETF as "has fundamentals enough to proceed"
        # so the ETF branch at line ~826 can short-circuit cleanly.
        if not _has_any_fundamentals and is_etf(ticker):
            _has_any_fundamentals = True
        # PR P1-COVERAGE (2026-05-02): recently-IPO'd tickers (e.g.
        # INDIANHUME, CELLO) carry valid market_metrics rows (mcap > 0,
        # live price) but have ZERO annual_financials rows. Pre-fix
        # they tripped the gate above and 404'd. Rescue them by
        # consulting market_metrics directly: if a non-zero market cap
        # exists we know the instrument is live & investable, even
        # without 5-year fundamentals. Downstream renders as
        # "Under review — limited data" instead of unavailable.
        if not _has_any_fundamentals:
            try:
                # NOTE: _get_pipeline_session is already imported at module top
                # (line 141). Re-importing here would shadow the global, making
                # Python treat it as local — so other usages elsewhere in this
                # function raise UnboundLocalError when this branch doesn't fire.
                # Hotfix #312 — DO NOT add `from ...db import _get_pipeline_session` here.
                from sqlalchemy import text as _text
                _bare = ticker.replace(".NS", "").replace(".BO", "")
                _sess = _get_pipeline_session()
                if _sess is not None:
                    try:
                        _row = _sess.execute(_text(
                            "SELECT market_cap_cr FROM market_metrics "
                            "WHERE ticker = :t AND market_cap_cr > 0 LIMIT 1"
                        ), {"t": _bare}).first()
                        if _row and _row[0] and float(_row[0]) > 0:
                            _has_any_fundamentals = True
                            _data_issues = list(_data_issues) + [
                                "Limited financial history — recently listed; "
                                "showing market data only."
                            ]
                    finally:
                        try:
                            _sess.close()
                        except Exception:
                            pass
            except Exception:
                # Defensive: never block the response over a fallback DB hit.
                pass
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

        # Detect financial companies (NBFC/Bank/Insurance) via the
        # unified is_bank_like classifier (constants.is_bank_like). It
        # accepts ticker + sector + industry signals so yfinance sector
        # mis-tags (e.g. CAPITALSFB.NS surfacing as "Chemicals") cannot
        # smuggle a bank into the FCF-DCF path. Keeping clean_ticker as
        # the legacy variable name because it threads through 30+ call
        # sites; semantics now match Prism/Hex and Piotroski exactly.
        clean_ticker = ticker.replace('.NS', '').replace('.BO', '')
        _raw_enriched_sector = (
            enriched.get("sector_name")
            or raw.get("sector_name")
            or raw.get("sector")
        )
        # Ticker-based sector override (added 2026-05-18, cement M&A
        # truncation PR). yfinance surfaces a handful of large-cap
        # Indian names with wrong sector strings — AMBUJACEM lands as
        # "General/Diversified" rather than "Cement", silently bypassing
        # every cement-specific code path that reads off the sector
        # string for routing (is_etf / is_regulated_utility /
        # is_bank_like all take a sector argument). TICKER_SECTOR_OVERRIDES
        # is the curated allow-list of known mistags; look up bare and
        # suffixed forms before falling back to the yfinance-derived
        # value. Note: _resolve_sector (utils.py) already consumes the
        # same dict for the display-facing CompanyInfo.sector field and
        # for downstream cyclical detection at line ~648, so this is the
        # third (and only remaining) consumer that needed wiring.
        _override_sector = (
            TICKER_SECTOR_OVERRIDES.get(clean_ticker.upper())
            or TICKER_SECTOR_OVERRIDES.get(ticker.upper())
        )
        _enriched_sector = _override_sector or _raw_enriched_sector
        _enriched_industry = raw.get("industry") or enriched.get("industry")
        is_financial = is_bank_like(
            ticker, _enriched_sector, _enriched_industry,
        )

        # ── Regulated-utility classifier (PR feat/regulated-utility-dcf-engine) ──
        # CERC / PNGRB / state-tariff-regulated utilities (POWERGRID,
        # NTPC, NHPC, PFC, RECLTD, GAIL, TORNTPOWER, ADANIENSOL,
        # ADANITRANS, IRFC, IEX, SJVN, HUDCO) must NOT use generic FCF-
        # DCF. See docs/design/regulated-utility-dcf-fix.md for the
        # failure trace; pre-PR POWERGRID printed FV ₹59.66 vs CMP ₹291
        # (−79.5% MoS) because regulated capex erodes FCF while debt is
        # then subtracted again at the equity-value step. The
        # regulated_utility_valuation_service uses a rate-base /
        # justified-P/B path instead. We intentionally short-circuit
        # BEFORE the is_financial branch even when a ticker is in both
        # sets (PFC / RECLTD / IRFC / HUDCO are in
        # _NBFC_INSURANCE_BANKLIKE for Piotroski bank-mode but value
        # via the regulated path).
        # ── ETF classifier (audit Step 2, PR feat/etf-asset-type-classifier) ──
        # ETFs (NIFTYBEES, BANKBEES, LIQUIDBEES, GOLDBEES, ICICIB22 …)
        # are NOT operating businesses — they hold a basket of underlying
        # securities and their fair value is the iNAV / NAV of those
        # holdings published daily by the issuer. Running the generic
        # FCF-DCF (or P/B, or peer-cap) path produces structurally
        # nonsense FVs. We short-circuit BEFORE is_regulated_utility,
        # is_financial, recent-IPO and the DCF branch entirely. ETF wins
        # over every other classifier — an ETF that happens to hold
        # utility stocks must still be valued as an ETF, not as a utility.
        _etf_security_type = (
            raw.get("quoteType")
            or enriched.get("quoteType")
            or raw.get("security_type")
            or enriched.get("security_type")
        )
        is_etf_ticker = is_etf(
            ticker,
            sector=_enriched_sector,
            industry=_enriched_industry,
            security_type=_etf_security_type,
        )

        # ── REIT classifier (PR #333) ─────────────────────────────
        # Mirrors the ETF pattern. Indian REITs (EMBASSY, MINDSPACE,
        # BROOKFIELD, NEXUS) are SEBI pass-through trusts and produce
        # structurally wrong FVs through generic FCF-DCF. Routed BEFORE
        # is_regulated_utility_ticker — REIT wins over every other
        # classifier (a REIT must never be P/B-modelled as a developer
        # or rate-base-modelled as a utility).
        is_reit_ticker = (
            False if is_etf_ticker
            else is_reit(
                ticker, _enriched_sector, _enriched_industry,
            )
        )

        # ── InvIT classifier (Day-110c, 2026-05-23) ───────────────
        # InvITs (Infrastructure Investment Trusts) are structurally
        # identical to REITs for valuation purposes (>=90% mandatory
        # distribution, no organic compounding). The cohort module
        # (sector_overrides.py) provides sub-segment-aware fair-yield
        # anchoring. The PR #333 REIT short-circuit branch is reused
        # via the ``_is_reit_or_invit`` gate below — InvITs join the
        # no-DCF / distribution-yield path. The sub-segment is
        # surfaced in _meta under reit_invit_cohort.
        is_invit_ticker = (
            False if (is_etf_ticker or is_reit_ticker)
            else is_invit(
                ticker, _enriched_sector, _enriched_industry,
            )
        )
        # The PR #333 short-circuit consumes ``is_reit_ticker``;
        # extending it here folds InvITs into the same no-DCF path
        # without touching the ~15 downstream call sites. Where the
        # caller needs to know REIT-vs-InvIT specifically (eg the
        # _meta sub-segment), it consults ``is_invit_ticker``.
        _is_reit_or_invit = bool(is_reit_ticker or is_invit_ticker)
        is_reit_ticker = _is_reit_or_invit

        is_regulated_utility_ticker = (
            False if (is_etf_ticker or is_reit_ticker)
            else is_regulated_utility(
                ticker, _enriched_sector, _enriched_industry,
            )
        )

        # ── Realty developer classifier (Approach C, 2026-05-18) ──
        # Per docs/design/realty-developers-dcf-fix.md. Listed Indian
        # residential / mixed-use developers (DLF, GODREJPROP, LODHA,
        # OBEROIRLTY, PRESTIGE, PHOENIXLTD, SOBHA, BRIGADE, MAHLIFE,
        # KEYSTONE, MACROTECH, NCC, SHRIRAMPROP, SUNTECK). REITs are
        # excluded — they have their own classifier above which wins.
        # The actual routing additionally requires a curation row in
        # realty_land_bank_inputs (see Step 6 branch). Without that row
        # the ticker silently falls through to the existing Tier 2
        # generic path — this is why no CACHE_VERSION bump is required.
        is_realty_developer_ticker = (
            False if (is_etf_ticker or is_reit_ticker or is_regulated_utility_ticker)
            else is_realty_developer(
                ticker, _enriched_sector, _enriched_industry,
            )
        )
        _realty_land_bank_input = None
        if is_realty_developer_ticker:
            try:
                from backend.services.realty_valuation_service import (
                    fetch_land_bank_input as _fetch_lb,
                )
                _realty_land_bank_input = _fetch_lb(ticker)
            except Exception as _lb_exc:  # noqa: BLE001
                import logging as _lb_log
                _lb_log.getLogger("yieldiq.analysis").warning(
                    "[%s] fetch_land_bank_input failed: %s: %s",
                    ticker, type(_lb_exc).__name__, _lb_exc,
                )
                _realty_land_bank_input = None
        # The branch downstream only fires when BOTH the classifier
        # matches AND a curation row exists.
        is_realty_branch_active = bool(
            is_realty_developer_ticker and _realty_land_bank_input
        )
        # Pre-init so the valuation_model label assignment near the
        # end of the function can reference it for non-insurance tickers
        # without NameError.
        _appraisal_val_result = None

        # ── Defense PSU analyst-opinion flag (2026-05-18) ────────
        # Per docs/design/defense-psu-dcf-fix.md (Approach D — NO-FIX).
        # We compute DCF normally; only the *output* is decorated:
        # `analyst_opinion_required` flag, an explanatory caveat in
        # `data_issues`, and a 0.7× confidence-score downgrade so the
        # frontend renders the low-confidence badge. No WACC / terminal
        # growth / FCF base / multiple is changed.
        is_defense_psu_ticker = is_defense_psu(
            ticker, _enriched_sector, _enriched_industry,
        )

        _record_step("step3_metrics")

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
            # feat/transparency (2026-05-02): provenance for the
            # market-cap hero number / freshness widget. Market cap is
            # derived live as `price × shares`, so its as-of timestamp
            # matches the price pull. Source surfaces which data path
            # provided the share count.
            market_cap_as_of=_ts,
            market_cap_source="live_price_x_shares",
            shares_outstanding_source=_data_source,
        )

        _record_step("step4_company")

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

                # ── Peak-phase detection (2026-05-19 Day-5 + Day-6) ──
                # The 3-year normalized FCF is peak-biased when the
                # most recent years are at a supercycle high. Day-5
                # added a 5y check; Day-6 extends to 10y because for
                # commodities like VEDL where ALL of 2020-2025 is peak,
                # even the 5y mean stays elevated. The 10y window
                # reaches back into 2016-2019 (mid/down cycle) for a
                # genuinely through-cycle anchor.
                #
                # Decision logic: use the LARGEST window where peak
                # detection fires (most through-cycle), but only if
                # 3y is materially above. If 3y > 5y > 10y, the cycle
                # peak is multi-year and we want the longest reference.
                try:
                    _peak_5y = _query_normalized_fcf(ticker, years=5)
                    _peak_10y = _query_normalized_fcf(ticker, years=10)
                    _3y_fcf = float(_norm["fcf"])
                    _5y_fcf = (
                        float(_peak_5y["fcf"])
                        if _peak_5y and _peak_5y.get("fcf") else None
                    )
                    _10y_fcf = (
                        float(_peak_10y["fcf"])
                        if _peak_10y and _peak_10y.get("fcf") else None
                    )

                    _chosen_window = None
                    _chosen_fcf = None

                    # Check 10y first (most through-cycle)
                    if _10y_fcf and _10y_fcf > 0 and _3y_fcf > _10y_fcf * 1.50:
                        _chosen_window = "10y"
                        _chosen_fcf = _10y_fcf
                    # Else check 5y
                    elif _5y_fcf and _5y_fcf > 0 and _3y_fcf > _5y_fcf * 1.35:
                        _chosen_window = "5y"
                        _chosen_fcf = _5y_fcf

                    if _chosen_window and _chosen_fcf:
                        enriched["latest_fcf"] = _chosen_fcf
                        enriched["_cyclical_peak_detected"] = True
                        enriched["_cyclical_peak_3y_ratio"] = round(
                            _3y_fcf / _chosen_fcf, 3
                        )
                        _fcf_data_source = (
                            f"normalized_{_chosen_window}_peak_capped"
                        )
                        _normalized_fcf_meta["peak_capped"] = True
                        _normalized_fcf_meta["fallback_window"] = _chosen_window
                except Exception:
                    pass

        # ── NSE XBRL TTM preference (feat/wire-quarterly-xbrl-to-analysis) ──
        # For the 41 NIFTY-50 tickers whose Ind-AS quarterly P&L is
        # in `company_quarterly_results`, prefer the audited XBRL TTM
        # for revenue + PAT over yfinance's noisy series (yfinance
        # fires ttm_fcf=0 on ~77% of cache). Only swap in when we have
        # a full 4-quarter window — partial windows would understate
        # TTM and trip the canary FV-stability gates.
        #
        # FCF is NOT taken from XBRL (the quarterly filing doesn't
        # carry a cash-flow statement) — the existing yfinance /
        # annual-fallback FCF path below still runs. Follow-up PR
        # will parse the cash-flow XBRL and add ttm_fcf here.
        _ttm_source = "yfinance"
        _quarterly_last_filed_at: str | None = None
        if _normalized_fcf_meta is not None:
            # Cyclical path already populated revenue/PAT/FCF from the
            # normalized 3y FCF helper above. Reflect that in the
            # provenance label instead of leaving the default "yfinance",
            # which misleadingly suggests the noisy yfinance TTM ladder
            # was used (it wasn't — XBRL TTM is intentionally skipped
            # for cyclicals because normalized 3y avoids single-year
            # spikes/troughs that distort the cycle).
            _ttm_source = "normalized_3y"
        else:
            from backend.services.quarterly_results_service import (
                resolve_ttm_for_analysis as _resolve_ttm_for_analysis,
            )
            _ttm_resolution = _resolve_ttm_for_analysis(
                ticker,
                query_ttm_financials=_query_ttm_financials,
                query_latest_annual_financials=_query_latest_annual_financials,
            )
            _ttm_source = _ttm_resolution["ttm_source"]
            _quarterly_last_filed_at = _ttm_resolution["quarterly_last_filed_at"]
            _fcf_data_source = _ttm_resolution["fcf_data_source"]
            for _k, _v in _ttm_resolution["enriched_updates"].items():
                enriched[_k] = _v
            # When XBRL TTM owns revenue+PAT, the FCF leg is still
            # filled from the latest annual row (XBRL doesn't carry
            # a cash-flow statement). TODO(follow-up PR): parse
            # cash-flow XBRL and surface ttm_fcf from filings.
            _annual_fcf_fallback = _ttm_resolution.get("annual_fcf_fallback")
            if (
                _annual_fcf_fallback
                and _annual_fcf_fallback.get("fcf") is not None
                and not enriched.get("latest_fcf")
            ):
                enriched["latest_fcf"] = _annual_fcf_fallback["fcf"]

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

        # ── Top private banks COE cap (P1, 2026-04-30) ──────────
        # HDFCBANK / ICICIBANK / KOTAKBANK / AXISBANK have lower
        # cost of equity than the generic CAPM 12-13% landing
        # (mature deposit franchise). Cap surfaced WACC at 11%.
        # Banks route through compute_financial_fair_value (P/BV
        # peer median), so the cap is surface-only here; the
        # fair-value lift is applied separately in
        # financial_valuation_service via TOP_PRIVATE_BANK_PB_BUMP.
        if is_top_private_bank(clean_ticker) and wacc > TOP_PRIVATE_BANK_COE:
            import logging as _tpb_log
            _tpb_log.getLogger("yieldiq.analysis").info(
                "Top private bank COE cap: %s %.4f -> %.4f",
                clean_ticker, wacc, TOP_PRIVATE_BANK_COE,
            )
            wacc = TOP_PRIVATE_BANK_COE
            if isinstance(wacc_data, dict):
                wacc_data["wacc"] = TOP_PRIVATE_BANK_COE
                wacc_data["top_private_bank_coe_applied"] = True

        # ── Day-107c (2026-05-23) ASHOKLEY CV WACC floor at 11% ──
        # ASHOKLEY (commercial-vehicle pure-play) has CV-cycle beta
        # closer to 1.3-1.5 in commodity-linked freight downturns.
        # The default CAPM landing of ~10% understates risk; floor
        # WACC at 0.11 so the DCF spread reflects the cycle premium.
        # 2W / 4W auto OEMs do NOT get a floor — their betas land in
        # the 1.0-1.2 band where default WACC is appropriate.
        _AUTO_CV_WACC_FLOOR = 0.11
        if clean_ticker == "ASHOKLEY" and wacc < _AUTO_CV_WACC_FLOOR:
            import logging as _ashok_log
            _ashok_log.getLogger("yieldiq.analysis").info(
                "ASHOKLEY CV WACC floor applied: %.4f -> %.4f",
                wacc, _AUTO_CV_WACC_FLOOR,
            )
            wacc = _AUTO_CV_WACC_FLOOR
            if isinstance(wacc_data, dict):
                wacc_data["wacc"] = _AUTO_CV_WACC_FLOOR
                wacc_data["auto_cv_wacc_floor_applied"] = True

        # ── Day-107b (2026-05-23) FMCG cohort WACC tighten ────────
        # FMCG balance sheets (HUL / NESTLEIND / ITC / BRITANNIA /
        # DABUR / MARICO / COLPAL / GODREJCP / EMAMILTD / TATACONSUM
        # / VBL) are net-cash with beta 0.5-0.7. CAPM systematically
        # over-charges them by 50-150bps. Tighten to a floor of
        # 8.5%. See sector_overrides.py for cohort membership SSOT.
        try:
            from backend.services.analysis.sector_overrides import (
                fmcg_wacc_floor as _fmcg_wacc_floor,
            )
            _fmcg_wacc_target = _fmcg_wacc_floor(clean_ticker)
            if _fmcg_wacc_target is not None and wacc > _fmcg_wacc_target:
                _wacc_pre = wacc
                wacc = _fmcg_wacc_target
                if isinstance(wacc_data, dict):
                    wacc_data["wacc"] = _fmcg_wacc_target
                    wacc_data["fmcg_cohort_wacc_floor_applied"] = True
        except Exception:
            pass

        country = get_active_country()
        terminal_g = country.get("default_terminal_growth", 0.025)
        if terminal_g >= wacc:
            terminal_g = wacc - 0.02

        # Per-ticker terminal_growth override (e.g. TITAN wide-moat compounder
        # at 6% vs 4% default). See ticker_overrides.py. Bounded below WACC
        # to keep DCF math sane.
        try:
            _tg_override_entry = _get_ticker_override(ticker)
        except Exception:
            _tg_override_entry = None
        if _tg_override_entry:
            _tg_val = _tg_override_entry.get("terminal_growth_override")
            if _tg_val is not None:
                _tg_val = float(_tg_val)
                if _tg_val >= wacc:
                    _tg_val = wacc - 0.02
                terminal_g = _tg_val

        # ── Day-21 (2026-05-20): Hospital / Pharma-CDMO terminal-g lift ──
        # Bug B fix. The Day-16/Day-19 lift blocks inside
        # FCFForecaster.predict() were structurally orphaned: they
        # mutated a LOCAL _g_terminal_eff variable that was never
        # propagated to DCFEngine(terminal_growth=...) at L1898. So the
        # lift had ZERO effect on TV computation despite the code
        # paths existing. This block runs HERE — where terminal_g is
        # finalised before DCFEngine construction — and is therefore
        # the actual single source of truth for TV's g parameter.
        #
        # Design (mirrors models/forecaster.py exactly):
        #   - _HOSPITAL_CHAIN_TICKERS: lift TG to 0.055 (defensive,
        #     Indian healthcare nominal-spend CAGR 12-15%)
        #   - _PHARMA_CDMO_TICKERS:    lift TG to 0.045 (long-duration
        #     contracts, between hospitals and generic-pharma)
        # Both still respect the wacc - 0.02 safety guard above so
        # Gordon model can't blow up.
        try:
            _bare_ticker_tg = (ticker or "").replace(".NS", "").replace(".BO", "").upper()
            _HOSPITAL_CHAIN_TICKERS_INLINE = {
                "MAXHEALTH", "FORTIS", "MEDANTA", "KIMS",
                "NH", "APOLLOHOSP", "ASTERDM", "RAINBOW",
                "VIJAYA", "AGARWALEYE",
            }
            _PHARMA_CDMO_TICKERS_INLINE = {
                "DIVISLAB", "SYNGENE", "COHANCE",
                "ANTHEM", "SAGILITY", "IKS",
            }
            # ── Day-84 (2026-05-22) Pharma FRANCHISE quality cohort ──
            # Audit 2026-05-20: MANKIND FV ₹1,046 vs CMP ₹2,584
            # (−59.5%). The terminal_growth_override of 0.05 alone is
            # not enough to bridge the gap between vanilla DCF and the
            # design-doc target band [₹1,500, ₹1,800]. Premium Indian
            # pharma franchises (domestic OTC + branded chronic-care
            # MNCs) deserve the same terminal-g treatment as hospital
            # chains because their pricing power, revenue durability,
            # and India healthcare nominal-spend tailwind are
            # structurally comparable to the hospital sub-bucket.
            # Set is identical to forecaster.py _PHARMA_FRANCHISE_
            # TICKERS_TG — both blocks must stay in sync.
            # Order matters: franchise tier is evaluated BEFORE CDMO
            # so DIVISLAB (in both sets) picks up the franchise lift
            # (0.055) rather than the looser CDMO lift (0.045).
            _PHARMA_FRANCHISE_TICKERS_INLINE = {
                "MANKIND", "SUNPHARMA", "CIPLA", "TORNTPHARM", "DRREDDY",
                "DIVISLAB", "ABBOTINDIA", "GLAND", "GLAXO", "PFIZER",
                "SANOFI", "AJANTPHARM", "ERIS",
            }
            if _bare_ticker_tg in _HOSPITAL_CHAIN_TICKERS_INLINE and terminal_g < 0.055:
                _tg_proposed = 0.055
                if _tg_proposed < wacc - 0.02:  # safety guard preserved
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[hospital-chain-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(Indian healthcare nominal-spend tailwind)"
                    ]
            elif _bare_ticker_tg in _PHARMA_FRANCHISE_TICKERS_INLINE and terminal_g < 0.055:
                _tg_proposed = 0.055
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[pharma-franchise-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(domestic-OTC + branded chronic-care franchise durability)"
                    ]
            elif _bare_ticker_tg in _PHARMA_CDMO_TICKERS_INLINE and terminal_g < 0.045:
                _tg_proposed = 0.045
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[pharma-cdmo-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(contract-services revenue durability)"
                    ]
            # ── Day-107c (2026-05-23) Auto OEM cohort: segment TG lift ──
            # Indian auto OEMs are cyclical but ride a structural per-
            # capita-ownership tailwind. Two-wheeler penetration in
            # India is ~2-tier (rural under-served); 4W passenger and
            # CV are mid-cycle commodity-linked. The default 2.5% TG
            # (or per-country override ~4%) understates the long-run
            # nominal demand CAGR. Lift TG per segment:
            #   - 2W (BAJAJ-AUTO/HEROMOTOCO/EICHERMOT/TVSMOTOR) → 5.0%
            #     Under-penetrated; export tailwinds (BAJAJ, TVS).
            #   - 4W passenger (MARUTI/TATAMOTORS/M&M)         → 4.5%
            #     Mid-cycle; EV transition + premiumization.
            #   - CV (ASHOKLEY)                                 → 4.0%
            #     Commodity-linked freight demand; tightest band.
            #   - Auto ancillaries / tires (MOTHERSON/BOSCHLTD/
            #     MRF/APOLLOTYRE)                                → 4.0%
            #     Tier-2; tracks 4W cycle without secular lift.
            # Safety guard `terminal_g < target` only lifts (never cuts).
            _AUTO_2W_TICKERS_INLINE = {
                "BAJAJ-AUTO", "BAJAJAUTO", "HEROMOTOCO",
                "EICHERMOT", "TVSMOTOR",
            }
            _AUTO_4W_TICKERS_INLINE = {
                "MARUTI", "TATAMOTORS", "M&M", "MM",
            }
            _AUTO_CV_TICKERS_INLINE = {"ASHOKLEY"}
            _AUTO_ANCILLARY_TICKERS_INLINE = {
                "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
            }
            if _bare_ticker_tg in _AUTO_2W_TICKERS_INLINE and terminal_g < 0.050:
                _tg_proposed = 0.050
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[auto-2w-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(India 2W per-capita ownership tailwind)"
                    ]
            elif _bare_ticker_tg in _AUTO_4W_TICKERS_INLINE and terminal_g < 0.045:
                _tg_proposed = 0.045
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[auto-4w-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(India 4W passenger premiumization + EV transition)"
                    ]
            elif _bare_ticker_tg in _AUTO_CV_TICKERS_INLINE and terminal_g < 0.040:
                _tg_proposed = 0.040
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[auto-cv-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(India CV freight cycle)"
                    ]
            elif _bare_ticker_tg in _AUTO_ANCILLARY_TICKERS_INLINE and terminal_g < 0.040:
                _tg_proposed = 0.040
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[auto-anc-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(auto ancillary/tire 4W cycle)"
                    ]
        except Exception:
            pass

        # ── Day-107a (2026-05-23) IT-services Tier-1 TG lift ──
        # TCS/INFY/HCLTECH/WIPRO/TECHM lift terminal_g to 0.045.
        # Separate try-block so the auto elif chain above doesn't
        # preclude IT tickers. Mirrors Day-84 pharma TG-lift shape.
        try:
            _IT_SERVICES_TIER1_TICKERS_INLINE = {
                "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
            }
            if (
                _bare_ticker_tg in _IT_SERVICES_TIER1_TICKERS_INLINE
                and terminal_g < 0.045
            ):
                _tg_proposed = 0.045
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[it-services-tier1-tg-lifted] terminal_g raised "
                        f"to {terminal_g:.3f} (multi-year deal-book "
                        f"visibility)"
                    ]
        except Exception:
            pass

        # ── Day-107b (2026-05-23) FMCG sector cohort TG lift ──
        # Separate try-block so the auto-cohort elif-chain above
        # doesn't preclude FMCG tickers from being lifted. The
        # fmcg_terminal_growth() helper returns None for non-FMCG
        # tickers so this is a safe no-op outside the cohort.
        # Tier mix:
        #   - Top franchise leaders (HUL/NESTLE/BRITANNIA) → 5.0%
        #   - ITC (cigarette tail risk discount)            → 4.5%
        #   - Tier-2 (DABUR/MARICO/COLPAL/GODREJCP)         → 4.5%
        #   - Tier-3 (EMAMI/TATACONSUM/VBL)                 → 4.0%
        # Runs AFTER the Day-107b WACC tighten so the
        # ``terminal_g < wacc - 0.02`` guard uses the tightened WACC.
        try:
            from backend.services.analysis.sector_overrides import (
                fmcg_terminal_growth as _fmcg_tg,
            )
            _fmcg_tg_target = _fmcg_tg(ticker)
            if _fmcg_tg_target is not None and terminal_g < _fmcg_tg_target:
                _tg_proposed = _fmcg_tg_target
                if _tg_proposed < wacc - 0.02:
                    terminal_g = _tg_proposed
                    _data_issues = list(_data_issues) + [
                        f"[fmcg-cohort-tg-lifted] terminal_g raised to {terminal_g:.3f} "
                        f"(India household-consumption baseline + franchise durability)"
                    ]
        except Exception:
            pass

        # ── Day-107c (2026-05-23) Auto OEM cycle-stage detection ──
        # Autos are deeply cyclical. Trailing EBITDA margin can be
        # 150%+ of 5y median at cycle peaks (e.g. BAJAJ-AUTO FY24 ~22%
        # vs 5y median ~17%) or <50% at troughs (e.g. TATAMOTORS
        # FY20 COVID-trough ~3% vs 5y median ~8%). The DCF engine
        # anchored on trailing margin will over/under-shoot at the
        # extremes. We detect cycle-stage here and surface a flag so
        # the bear-floor block below can apply the Day-51 pattern
        # (`min(0.6 × fv, 0.4 × price)`) when in a deep trough.
        _AUTO_COHORT_ALL_INLINE = {
            "MARUTI", "TATAMOTORS", "M&M", "MM", "BAJAJ-AUTO", "BAJAJAUTO",
            "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMOTOR",
            "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
        }
        _auto_cohort_member = False
        _auto_cycle_stage = "neutral"
        try:
            _auto_bare = (ticker or "").replace(".NS", "").replace(".BO", "").upper()
            if _auto_bare in _AUTO_COHORT_ALL_INLINE:
                _auto_cohort_member = True
                _trailing_margin = (
                    enriched.get("ebitda_margin")
                    or enriched.get("ebitda_margin_ttm")
                    or 0
                )
                _median_margin = (
                    enriched.get("ebitda_margin_5y_median")
                    or 0
                )
                if _trailing_margin and _median_margin and _median_margin > 0:
                    _ratio = float(_trailing_margin) / float(_median_margin)
                    if _ratio > 1.5:
                        _auto_cycle_stage = "peak"
                        _data_issues = list(_data_issues) + [
                            f"[auto-cycle-peak] trailing margin "
                            f"{float(_trailing_margin):.3f} is "
                            f"{_ratio:.2f}x 5y median "
                            f"{float(_median_margin):.3f}; "
                            f"DCF input may overshoot mid-cycle FV"
                        ]
                    elif _ratio < 0.5:
                        _auto_cycle_stage = "trough"
                        _data_issues = list(_data_issues) + [
                            f"[auto-cycle-trough] trailing margin "
                            f"{float(_trailing_margin):.3f} is "
                            f"{_ratio:.2f}x 5y median "
                            f"{float(_median_margin):.3f}; "
                            f"bear-floor will engage"
                        ]
        except Exception:
            pass

        # ── Day-107a (2026-05-23) IT-services margin sanity flag ────
        # Cohort has been in 22-26% EBIT-margin band for a decade.
        # Forecast input > 30% is structurally implausible → flag as
        # data_limited so downstream consumers show the badge.
        try:
            _IT_SERVICES_COHORT_TICKERS_INLINE = {
                "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
                "LTIM", "PERSISTENT", "MPHASIS", "COFORGE", "BSOFT",
            }
            if _bare_ticker_tg in _IT_SERVICES_COHORT_TICKERS_INLINE:
                _term_margin = None
                try:
                    _enr = locals().get("enriched", None) or {}
                    _term_margin = _enr.get("terminal_ebit_margin")
                    if _term_margin is None:
                        _term_margin = _enr.get("ebit_margin_terminal")
                except Exception:
                    _term_margin = None
                if (
                    _term_margin is not None
                    and float(_term_margin) > 0.30
                ):
                    _data_issues = list(_data_issues) + [
                        f"[it-services-margin-sanity] terminal EBIT margin "
                        f"input {float(_term_margin):.1%} exceeds 30% "
                        f"ceiling (cohort band 22-26% for a decade — "
                        f"flag as data_limited)"
                    ]
        except Exception:
            pass

        forecast_yrs = 10

        # PR #168: track whether the cyclical-trough anchor fires so
        # downstream scenario assembly + (later) hex axes can react.
        _trough_anchor_fired = False
        _trough_anchor_bear_iv: float | None = None
        _trough_anchor_bull_iv: float | None = None

        # FIX-ANTHEM-500-BUG2 (2026-06-09, P0): defensive initialization
        # of the scenario-band locals so the dcf_collapse_safety_net call
        # at L3344-3345 (`float(bull_iv or 0)`, `float(bear_iv or 0)`)
        # can never raise UnboundLocalError. In the generic-DCF `else`
        # branch at L2405-, `bear_iv` / `bull_iv` are ONLY assigned when
        # one of {_post_demerger_route, _tier2_result, _auto_bear_floor}
        # fires. ANTHEM's path hit the generic DCF block with none of
        # those triggers — so `bull_iv` reached the safety-net call
        # un-initialized → UnboundLocalError → the `except Exception`
        # at L3482 swallowed it and logged "dcf_collapse_safety_net
        # failed for ANTHEM.NS: cannot access local variable 'bull_iv'
        # where it is not associated with a value". The chain then
        # continued and tripped Bug 3 downstream. `iv` itself does NOT
        # need this treatment because the engine paths above always
        # assign it (or short-circuit to 0.0 on ETF/REIT), but bear_iv
        # /bull_iv have multiple don't-fire paths in the generic
        # else-branch. Initialize to 0.0 sentinel so the `or 0` fall-
        # through at the safety-net call site behaves as intended.
        bear_iv: float = 0.0
        bull_iv: float = 0.0

        _record_step("step5_wacc_forecast")

        # ── Step 6: Valuation (rate-base / P/B / DCF) ─────────────
        # Branch priority:
        #   1. is_regulated_utility_ticker — rate-base (Gordon
        #      justified-P/B). Bypasses DCFEngine entirely. Falls
        #      through to data_limited (NOT generic DCF) if BVPS is
        #      missing.
        #   2. is_financial — sector-appropriate P/BV / P/E peer-band.
        #   3. else — standard FCF-DCF via DCFEngine.
        _regulated_val_result = None
        if is_etf_ticker:
            # ETF short-circuit — skip DCF / scenarios / peer_cap /
            # recent-IPO / financial-valuation entirely. The fair value
            # of an ETF is the NAV / iNAV of its underlying basket,
            # published daily by the issuer; there is no operating-
            # business cash flow to project.
            iv = 0.0
            iv_raw = 0.0
            bear_iv = 0.0
            bull_iv = 0.0
            dcf_res = {
                "intrinsic_value_per_share": 0.0,
                "warnings": [
                    "Valuation: ETFs are valued by NAV (net asset "
                    "value) of their underlying holdings, not by DCF."
                ],
                "reliability_score": 0,
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
            _bvps = 0
            _data_issues.append(
                "ETFs are valued by NAV (net asset value) of their "
                "underlying holdings, not by DCF. For NAV/iNAV refer "
                "to the issuer's daily disclosure."
            )
        elif is_reit_ticker:
            # REIT short-circuit (PR #333) — skip DCF / scenarios /
            # peer_cap / recent-IPO / financial-valuation entirely.
            # Indian REITs are SEBI-regulated pass-through trusts that
            # distribute >=90% of NDCF as DPU and do NOT compound
            # retained earnings. Their fair value is NAV/unit (net
            # asset value of the underlying property portfolio)
            # disclosed quarterly by the trust, plus DPU yield — there
            # is no operating-business cash flow to project. Generic
            # DCF mis-prices them by ~50% on the low side because
            # project-level debt is subtracted from an already-small
            # pass-through cash flow EV. See
            # docs/design/reit-valuation-fix.md §2 for the full
            # structural explanation.
            iv = 0.0
            iv_raw = 0.0
            bear_iv = 0.0
            bull_iv = 0.0
            dcf_res = {
                "intrinsic_value_per_share": 0.0,
                "warnings": [
                    "Valuation: REITs are valued by NAV (net asset "
                    "value of underlying properties) plus DPU yield, "
                    "not by DCF."
                ],
                "reliability_score": 0,
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
            _bvps = 0
            _data_issues.append(
                "REITs are valued by NAV (net asset value of the "
                "underlying properties) plus DPU yield, not by DCF. "
                "Refer to the issuer's daily NAV disclosure."
            )
        elif is_regulated_utility_ticker:
            # Defaults — always defined regardless of which path runs.
            bear_iv = round(price * 0.75, 2) if price > 0 else 0
            bull_iv = round(price * 1.25, 2) if price > 0 else 0
            iv = round(price, 2) if price > 0 else 0
            _val_method = ""
            _bvps = 0

            try:
                from backend.services.regulated_utility_valuation_service import (
                    compute_regulated_utility_fair_value,
                )
                _ru_company = {
                    "current_price": price,
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                    "market_cap": price * (enriched.get("shares", 0) or 0),
                }
                _ru_fin = {
                    "priceToBook": raw.get("priceToBook") or enriched.get("pb_ratio"),
                    "total_equity": enriched.get("total_equity") or raw.get("total_equity"),
                    "book_value_per_share": enriched.get("book_value_per_share"),
                    "bvps": enriched.get("bvps"),
                    "roe": (
                        raw.get("returnOnEquity")
                        or enriched.get("roe")
                    ),
                    "returnOnEquity": raw.get("returnOnEquity"),
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                }
                _regulated_val_result = compute_regulated_utility_fair_value(
                    ticker=ticker,
                    company_info=_ru_company,
                    financials=_ru_fin,
                )
            except Exception as _ru_exc:
                import logging as _ru_log
                _ru_log.getLogger("yieldiq.analysis").warning(
                    "[%s] regulated_utility_valuation failed: %s: %s",
                    ticker, type(_ru_exc).__name__, _ru_exc,
                )
                _regulated_val_result = None

            if _regulated_val_result and _regulated_val_result.get("fair_value", 0) > 0:
                iv = float(_regulated_val_result["fair_value"])
                bear_iv = float(_regulated_val_result.get("bear_case", bear_iv))
                bull_iv = float(_regulated_val_result.get("bull_case", bull_iv))
                _val_method = (
                    f"{_regulated_val_result.get('method', 'rate_base_gordon')} "
                    f"(regulated utility)"
                )
                _bvps = float(_regulated_val_result.get("_meta", {}).get("bvps", 0) or 0)
            else:
                # No BVPS → honestly surface as data_limited rather than
                # silently routing through generic DCF (which is the
                # whole reason this branch exists).
                _data_issues.append(
                    "[data_limited] No book value per share available "
                    "for regulated utility — rate-base valuation not "
                    "possible."
                )

            iv_raw = iv
            dcf_res = {
                "intrinsic_value_per_share": iv,
                "warnings": (
                    [f"Valuation: {_val_method}"] if _val_method else []
                ),
                # Reliability ≥ 70 floor matches the existing gate in
                # routers/analysis.py and the design-doc acceptance
                # criterion (POWERGRID reliability_score >= 70).
                "reliability_score": (
                    int(_regulated_val_result.get("confidence_score", 70))
                    if _regulated_val_result else 50
                ),
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
        elif is_realty_branch_active:
            # ── Realty developer Approach-C branch ──────────────
            # Per docs/design/realty-developers-dcf-fix.md §5.
            #   FV = (BVPS × sector_peer_PB) + uplift_per_share
            # PHOENIXLTD additionally gets a 60%-weighted NOI ×
            # cap-rate annuity overlay (§5.5). Routes BEFORE
            # is_financial. Falls through to data_limited (NOT
            # generic DCF) if BVPS is missing — same discipline as
            # the regulated_utility branch.
            bear_iv = round(price * 0.75, 2) if price > 0 else 0
            bull_iv = round(price * 1.25, 2) if price > 0 else 0
            iv = round(price, 2) if price > 0 else 0
            _val_method = ""
            _bvps = 0
            _realty_val_result = None
            try:
                from backend.services.realty_valuation_service import (
                    compute_realty_fair_value,
                )
                _realty_fin = {
                    "current_price": price,
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                    "priceToBook": raw.get("priceToBook") or enriched.get("pb_ratio"),
                    "total_equity": enriched.get("total_equity") or raw.get("total_equity"),
                    "book_value_per_share": enriched.get("book_value_per_share"),
                    "bvps": enriched.get("bvps"),
                    # PHOENIXLTD annuity overlay inputs (best-effort —
                    # absence is fine; the overlay degrades gracefully).
                    "operating_income_ttm": (
                        enriched.get("operating_income_ttm")
                        or enriched.get("operating_income")
                        or raw.get("operatingIncome")
                    ),
                    "ebit_ttm": enriched.get("ebit_ttm"),
                    "annuity_noi_ttm": enriched.get("annuity_noi_ttm"),
                }
                _realty_val_result = compute_realty_fair_value(
                    ticker=ticker,
                    financials=_realty_fin,
                    land_bank_input=_realty_land_bank_input,
                )
            except Exception as _re_exc:  # noqa: BLE001
                import logging as _re_log
                _re_log.getLogger("yieldiq.analysis").warning(
                    "[%s] realty_valuation failed: %s: %s",
                    ticker, type(_re_exc).__name__, _re_exc,
                )
                _realty_val_result = None

            if _realty_val_result and _realty_val_result.get("fair_value", 0) > 0:
                iv = float(_realty_val_result["fair_value"])
                bear_iv = float(_realty_val_result.get("bear_case", bear_iv))
                bull_iv = float(_realty_val_result.get("bull_case", bull_iv))
                _val_method = (
                    f"{_realty_val_result.get('method', 'pb_plus_land_bank')} "
                    f"(realty developer, FY={_realty_val_result.get('_meta', {}).get('reporting_fy', '?')})"
                )
                _bvps = float(_realty_val_result.get("_meta", {}).get("bvps", 0) or 0)
            else:
                _data_issues.append(
                    "[data_limited] No book value per share available "
                    "for realty developer — Approach-C valuation not "
                    "possible."
                )

            iv_raw = iv
            dcf_res = {
                "intrinsic_value_per_share": iv,
                "warnings": (
                    [f"Valuation: {_val_method}"] if _val_method else []
                ),
                "reliability_score": (
                    int(_realty_val_result.get("confidence_score", 70))
                    if _realty_val_result else 50
                ),
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
        elif (
            # ── Insurance Appraisal-Value branch ──────────────────
            # Routes life insurers (HDFCLIFE / SBILIFE / ICICIPRULI /
            # LICI) through the EV + N×VNB engine *only when* the
            # operator has loaded a row into ``insurance_appraisal_
            # inputs`` via the admin UI. When no row exists,
            # ``get_appraisal_fair_value_for_ticker`` returns None and
            # this branch falls through to the existing P/BV path
            # (``is_financial`` below) — so production output stays
            # byte-identical until the first row of EV data is loaded.
            # See docs/design/insurance-dcf-fix.md §3 Approach A and
            # backend/services/insurance_appraisal_service.py.
            clean_ticker.upper() in _INSURANCE_TICKERS
            and (
                _appraisal_val_result := _try_insurance_appraisal(
                    ticker=ticker,
                    shares=enriched.get("shares") or raw.get("shares", 0),
                )
            )
        ):
            bear_iv = float(_appraisal_val_result.get("bear_case") or 0)
            bull_iv = float(_appraisal_val_result.get("bull_case") or 0)
            iv = float(_appraisal_val_result.get("fair_value") or 0)
            iv_raw = iv
            _bvps = 0
            _val_method = "appraisal_value (insurance EV + N×VNB)"
            _meta_app = _appraisal_val_result.get("_meta") or {}
            dcf_res = {
                "intrinsic_value_per_share": iv,
                "warnings": [
                    f"Valuation: {_val_method} — N={_meta_app.get('n_multiplier')}, "
                    f"EV/share=₹{_meta_app.get('ev_per_share')}, "
                    f"VNB/share=₹{_meta_app.get('vnb_per_share')}"
                ],
                "reliability_score": int(
                    _appraisal_val_result.get("confidence_score", 80)
                ),
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
            if _meta_app.get("period_end"):
                _data_issues.append(
                    f"Appraisal Value derived from operator-curated EV/VNB inputs "
                    f"as-of {_meta_app['period_end']}."
                )
        elif is_financial:
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
            #
            # SKIPPED for lenders (Banking, NBFC) — for balance-sheet
            # lenders EPS is net-interest-income on the loan book, not
            # free cash to equity, and EPS×fixed-multiple produced
            # absurd FVs (e.g. MUTHOOTFIN ≈ 3×CMP). When P/BV cannot
            # be computed we surface this as `data_limited` rather
            # than emitting a misleading P/E-derived FV.
            # Kept for Insurance because P/EV reporting is sparse and
            # P/E is a reasonable secondary anchor for insurers.
            if iv <= 0 and _sub_type == "Insurance":
                _eps = (enriched.get("diluted_eps")
                        or raw.get("trailingEps")
                        or enriched.get("eps")
                        or raw.get("fh_eps_ttm") or 0)
                _sector_pe = 18
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

                # ── Day-109a (2026-05-23): Banking cohort overlay ──
                # Layered on top of the existing Day-76 PB-ratio path.
                # Banks don't get DCF; they get tier-anchored P/BV with
                # ROE/asset-quality overlays. When the ticker is in the
                # Day-109a banking cohort AND we have a valid BVPS, we
                # rebuild the fair value from the cohort anchor (tier-1
                # private 3.0x, PSU 1.2x, tier-2 1.8x) lifted by the
                # ROE-quality boost (+20% when ROE>=16% AND GNPA<=2%).
                # Optional GNPA / provision_coverage flow through from
                # the financials dict; when absent the boost degrades to
                # 1.0 (no penalty), the stress flag never fires, and we
                # simply use the cohort anchor — strictly additive to
                # the existing Day-76 behaviour.
                try:
                    from backend.services.analysis.sector_overrides import (
                        is_banking_cohort_ticker as _is_bank_cohort,
                        banking_pb_anchor as _bank_pb_anchor,
                        banking_pb_band as _bank_pb_band,
                        banking_roe_quality_boost as _bank_roe_boost,
                        banking_stress_flag as _bank_stress,
                        banking_tier as _bank_tier_fn,
                    )
                    if _is_bank_cohort(clean_ticker):
                        _b_anchor = _bank_pb_anchor(clean_ticker)
                        _b_bvps = _bvps if (_bvps and _bvps > 0) else None
                        _b_roe = _fv_fin.get("roe")
                        _b_gnpa = (
                            enriched.get("gnpa_pct")
                            or raw.get("gnpa_pct")
                        )
                        _b_pcr = (
                            enriched.get("provision_coverage")
                            or raw.get("provision_coverage")
                        )
                        if _b_anchor is not None and _b_bvps is not None:
                            _b_boost = _bank_roe_boost(
                                clean_ticker, _b_roe, _b_gnpa,
                            )
                            _b_fair_pb = _b_anchor * _b_boost
                            _b_low, _b_high = _bank_pb_band(clean_ticker)
                            # Clamp to cohort band so the boost can't
                            # over-shoot the tier ceiling.
                            _b_fair_pb_clamped = max(
                                _b_low, min(_b_high, _b_fair_pb),
                            )
                            _b_iv = round(_b_bvps * _b_fair_pb_clamped, 2)
                            _b_bear = round(_b_bvps * _b_low, 2)
                            _b_bull = round(_b_bvps * _b_high, 2)
                            iv = _b_iv
                            bear_iv = _b_bear
                            bull_iv = _b_bull
                            _val_method = (
                                f"pb_ratio (Day-109a banking cohort: "
                                f"{_bank_tier_fn(clean_ticker)} anchor "
                                f"{_b_anchor:.1f}x × boost {_b_boost:.2f})"
                            )
                            if _bank_stress(
                                clean_ticker, _b_gnpa, _b_pcr,
                            ):
                                _data_issues.append(
                                    "[data_limited] stressed book — "
                                    "Day-109a banking cohort flag: "
                                    "GNPA > 5% or provision coverage "
                                    "< 60% (PB anchor still applied)."
                                )
                            # NIM (informational only). Surface the
                            # bank-metrics NIM when available so the
                            # frontend can render alongside the PB
                            # band — not a knob, just transparency.
                            _b_nim_info = (
                                enriched.get("nim")
                                or raw.get("nim")
                            )
                            if _b_nim_info is not None:
                                try:
                                    _data_issues.append(
                                        f"[info] trailing NIM "
                                        f"{float(_b_nim_info):.2f}% "
                                        "(Day-109a banking cohort, "
                                        "informational only)."
                                    )
                                except Exception:
                                    pass
                except Exception as _bank_cohort_exc:
                    import logging as _bc_log
                    _bc_log.getLogger("yieldiq.analysis").debug(
                        "[%s] Day-109a banking cohort overlay skipped: "
                        "%s: %s",
                        ticker, type(_bank_cohort_exc).__name__,
                        _bank_cohort_exc,
                    )

            # Lender-only data_limited tag (feat/route-banks-nbfcs-to-pb-always):
            # If every P/B path failed for a Banking / NBFC ticker and we
            # are about to fall through to method 5 ("Insufficient data"
            # → iv=price, fairly_valued), surface this as data_limited so
            # downstream verdict logic does NOT call it "fairly_valued".
            # This guarantees a bank/NBFC without BVPS is honestly
            # flagged rather than mis-rated.
            if (
                _sub_type in ("Banking", "NBFC")
                and (not _financial_val_result or
                     _financial_val_result.get("fair_value", 0) <= 0)
                and _val_method in ("", "Insufficient data")
            ):
                _data_issues.append(
                    "[data_limited] No book value per share available "
                    f"for {_sub_type} — P/B valuation not possible."
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
            # ── Tier 2 cohort valuation (Layer B W1; feature-flagged) ──
            # When TIER2_ENABLED=true and the ticker is NOT in any
            # sector-engine / skip path (banks, utilities, REITs, ETFs,
            # holdcos handled by branches above), try the quality-
            # bucketed sector cohort engine BEFORE generic DCF.  If
            # Tier 2 succeeds, we populate iv/bear/bull from its result
            # in the same shape as regulated_utility / financial paths.
            # If Tier 2 returns None (cohort < 5 peers, missing EPS,
            # peer median out of band) we fall through to generic DCF
            # — no breaking change vs current state when the flag is
            # off or the cohort is data-limited.
            # ── Day-73 Bug D: post-demerger relative-valuation route ──
            # ITCHOTELS (Jan-2025 demerger) and ABLBL (recent demerger)
            # were returning FV=0 / verdict="fairly_valued" / revenue_cagr_3y=null
            # because generic DCF cannot stitch pre/post-demerger bases
            # — the trailing FCF series is mathematically meaningless
            # across a structural-break boundary. Route these names
            # through the IPO framework's existing peer-multiple path
            # (compute_sector_relative_fv) instead. Gate: a structural
            # break is on file AND <8 quarters (~2y) have elapsed since
            # the event. After 8 quarters of post-event standalone
            # financials are on hand, generic DCF resumes naturally
            # (the gate evaluates False, this block is skipped).
            # See backend/services/analysis/ipo_framework.py for the
            # peer-multiple math reused here.
            _post_demerger_route = False
            _post_demerger_meta: dict | None = None
            try:
                from backend.services.corporate_actions_service import (
                    has_structural_break as _pdr_has_break,
                    quarters_since_event as _pdr_quarters_since,
                )
                _pdr_active = (
                    _pdr_has_break(ticker)
                    and (_pdr_quarters_since(ticker) or 99) < 8
                    and not is_financial
                    and not is_regulated_utility_ticker
                    and not is_etf_ticker
                    and not is_reit_ticker
                    and price
                    and price > 0
                )
            except Exception:
                _pdr_active = False
            if _pdr_active:
                try:
                    from backend.services.sector_percentile import (
                        compute_sector_cohort as _pdr_cohort_fn,
                    )
                    _pdr_sess = _get_pipeline_session()
                    _pdr_cohort_rows: list[dict] = []
                    if _pdr_sess is not None:
                        try:
                            _pdr_cohort_rows = _pdr_cohort_fn(
                                sector_label=enriched.get("sector_name")
                                or raw.get("sector_name")
                                or raw.get("sector")
                                or "",
                                db_session=_pdr_sess,
                                industry_label=raw.get("industry")
                                or enriched.get("industry"),
                            ) or []
                        finally:
                            try:
                                _pdr_sess.close()
                            except Exception:
                                pass
                    _pdr_shares = float(enriched.get("shares") or 0) or 0
                    _pdr_eps_ttm: float | None = None
                    _pdr_rev_ps: float | None = None
                    if _pdr_shares > 0:
                        _pdr_pat = enriched.get("latest_pat")
                        _pdr_rev = enriched.get("latest_revenue")
                        if _pdr_pat is not None:
                            try:
                                _pdr_eps_ttm = float(_pdr_pat) / _pdr_shares
                            except Exception:
                                _pdr_eps_ttm = None
                        if _pdr_rev is not None:
                            try:
                                _pdr_rev_ps = float(_pdr_rev) / _pdr_shares
                            except Exception:
                                _pdr_rev_ps = None
                    _pdr_result = _ipo_compute_sector_relative_fv(
                        eps_ttm=_pdr_eps_ttm,
                        revenue_per_share=_pdr_rev_ps,
                        cohort=_pdr_cohort_rows,
                        price=float(price),
                    )
                    if _pdr_result and (_pdr_result.get("fair_value") or 0) > 0:
                        iv = float(_pdr_result["fair_value"])
                        iv_raw = iv
                        bear_iv = round(iv * 0.80, 2)
                        bull_iv = round(iv * 1.20, 2)
                        _post_demerger_route = True
                        _post_demerger_meta = _pdr_result
                        _data_issues.append(
                            "Post-demerger relative valuation: peer "
                            f"multiples (method={_pdr_result.get('method')}, "
                            f"n_peers={_pdr_result.get('n_peers', 0)}) — "
                            "DCF requires ≥8 quarters of standalone "
                            "fundamentals."
                        )
                        import logging as _pdr_log
                        _pdr_log.getLogger("yieldiq.analysis").info(
                            "POST_DEMERGER_ROUTE: %s iv=%.2f price=%.2f "
                            "method=%s n_peers=%d quarters_since_event=%s",
                            ticker, iv, float(price),
                            _pdr_result.get("method"),
                            int(_pdr_result.get("n_peers") or 0),
                            _pdr_quarters_since(ticker),
                        )
                except Exception as _pdr_exc:
                    import logging as _pdr_log2
                    _pdr_log2.getLogger("yieldiq.analysis").warning(
                        "[%s] post_demerger_route failed: %s: %s",
                        ticker, type(_pdr_exc).__name__, _pdr_exc,
                    )
                    _post_demerger_route = False

            _tier2_result = None
            _tier2_attempted = False
            if tier2_enabled():
                _tier2_attempted = True
                try:
                    _tier2_sector = (
                        _enriched_sector
                        or _resolve_sector(_raw_sector, clean_ticker)
                    )
                    if not is_tier2_skip_sector(_tier2_sector):
                        # Piotroski may not have run yet (it runs in the
                        # parallel step below). Compute it cheaply here
                        # for the bucket decision; falls back to None on
                        # any failure (peer → Tail bucket).
                        try:
                            _tier2_piotroski = compute_piotroski_fscore(
                                enriched,
                            )
                            if isinstance(_tier2_piotroski, dict):
                                _tier2_piotroski = _tier2_piotroski.get(
                                    "fscore"
                                ) or _tier2_piotroski.get("score")
                        except Exception:
                            _tier2_piotroski = None

                        _tier2_eps = (
                            enriched.get("diluted_eps")
                            or raw.get("trailingEps")
                            or enriched.get("eps")
                            or raw.get("fh_eps_ttm")
                        )
                        _tier2_shares = (
                            enriched.get("shares")
                            or raw.get("shares", 0)
                        )
                        _tier2_mcap_cr = (
                            (float(price or 0) * float(_tier2_shares or 0))
                            / 1e7
                        )
                        _tier2_financials = {
                            "eps": _tier2_eps,
                            "ebitda": enriched.get("ebitda")
                                or enriched.get("latest_ebitda"),
                            "shares": _tier2_shares,
                            "roce": enriched.get("roce_pct")
                                or enriched.get("roce"),
                            "piotroski": _tier2_piotroski,
                            "market_cap_cr": _tier2_mcap_cr,
                            "bvps": enriched.get("book_value_per_share")
                                or enriched.get("bvps"),
                            "net_debt_cr": (
                                (enriched.get("total_debt", 0) or 0)
                                - (enriched.get("total_cash", 0) or 0)
                            ) / 1e7,
                            "current_price": price,
                        }
                        _tier2_peers = _build_tier2_peers_from_sector_relative(
                            ticker,
                        )
                        _tier2_result = compute_tier2_fair_value(
                            ticker=ticker,
                            sector=_tier2_sector,
                            financials=_tier2_financials,
                            peers=_tier2_peers,
                        )
                except Exception as _t2_exc:
                    import logging as _t2_log
                    _t2_log.getLogger("yieldiq.analysis").warning(
                        "[%s] tier2_cohort_valuation failed: %s: %s",
                        ticker, type(_t2_exc).__name__, _t2_exc,
                    )
                    _tier2_result = None

            # --- Standard DCF for non-financials ---
            # NOTE on Tier 2 ordering: when TIER2_ENABLED=true and the
            # cohort engine produced a valid FV above, we still let
            # generic DCF run (defensive — its side effects on
            # `projected` / `growth_schedule` are consumed downstream
            # by scenarios / reverse-DCF) and then OVERRIDE iv / bear_iv
            # / bull_iv / dcf_res with the Tier 2 result at the end of
            # this branch.  This avoids reshuffling ~115 lines of
            # indentation in this hot path; the override block lives
            # just before the `# ── Growth-stock override ──` marker.
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

            # ── Tier 2 cohort override (Layer B W1; feature-flagged) ──
            # If TIER2_ENABLED is on and the cohort engine produced a
            # valid FV in the pre-DCF block above, REPLACE the DCF iv /
            # bear_iv / bull_iv / dcf_res with the Tier 2 result here.
            # Generic DCF was allowed to run first (so projections /
            # growth_schedule are available for downstream scenarios /
            # reverse-DCF), but the FV that surfaces in the response
            # is the cohort number.
            if (
                _tier2_result is not None
                and _tier2_result.get("fair_value", 0) > 0
                and not _post_demerger_route
            ):
                iv = float(_tier2_result["fair_value"])
                iv_raw = iv
                bear_iv = float(_tier2_result.get("bear_case", iv * 0.75))
                bull_iv = float(_tier2_result.get("bull_case", iv * 1.25))
                _tier2_method = _tier2_result.get("method", "cohort_pe")
                _data_issues.append(
                    tier2_caveat(_tier2_result.get("_meta", {}))
                )
                dcf_res = {
                    "intrinsic_value_per_share": iv,
                    "warnings": [f"Valuation: {_tier2_method} (Tier 2)"],
                    "reliability_score": int(
                        _tier2_result.get("confidence_score", 70)
                    ),
                    "tv_pct_of_ev": 0,
                    "sum_pv_fcfs": 0,
                    "pv_tv": 0,
                    "enterprise_value": 0,
                    "equity_value": 0,
                }
                # Day-51 (2026-05-20): canary gate-3 fix for cyclicals
                # routed through Tier-2 cohort after trough anchor fires.
                #
                # Without this re-clamp, trough_anchor_bear_iv stays
                # pinned to 0.85 * price (computed when DCF was producing
                # near-zero), but iv was just overridden to the Tier-2
                # cohort FV which can be substantially below price.
                # Result: bear (0.85 × price) > base (cohort FV) →
                # canary gate-3 scenario_dispersion FAIL.
                # Observed in canary 2026-05-20 on HINDALCO, HINDZINC,
                # COROMANDEL, GUJGASLTD — all metals/cement/gas where
                # the cohort engine produced a base FV well under price.
                #
                # Fix: when Tier-2 overrides iv after the trough anchor
                # fired, re-anchor the bear/bull band so it can never
                # bracket above/below the new base. Cap bear at 95% of
                # the new iv (so bear ≤ base is guaranteed); floor bull
                # at 105% of the new iv (so bull ≥ base is guaranteed).
                # Still respects the original "cycle-priced-in" intent
                # by keeping the band tied to price where possible.
                if _trough_anchor_fired and price > 0:
                    _trough_anchor_bear_iv = round(
                        min(0.85 * price, iv * 0.95), 2,
                    )
                    _trough_anchor_bull_iv = round(
                        max(1.10 * price, iv * 1.05), 2,
                    )

        # ── Day-107c (2026-05-23) Auto cohort cycle-trough bear-floor ──
        # When a cohort member is detected as cycle-trough (trailing
        # EBITDA margin < 50% of 5y median) apply the Day-51 cyclical
        # bear-floor pattern: bear_iv = min(0.6 × current_fv,
        # 0.4 × current_price). This prevents the bear case rendering
        # at ~0 when the engine is anchored on a COVID-2020-style
        # trough margin. Apply ONLY when the existing bear_iv would
        # be lower than this floor (max() preserves upside).
        if (
            _auto_cohort_member
            and _auto_cycle_stage == "trough"
            and iv > 0
            and price > 0
        ):
            try:
                _auto_bear_floor = round(min(0.6 * iv, 0.4 * price), 2)
                if bear_iv < _auto_bear_floor:
                    _data_issues = list(_data_issues) + [
                        f"[auto-cycle-trough-bear-floor] bear raised from "
                        f"{bear_iv:.2f} to {_auto_bear_floor:.2f} "
                        f"(min(0.6*fv, 0.4*price) — cycle-trough)"
                    ]
                    bear_iv = _auto_bear_floor
            except Exception:
                pass

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

        _record_step("step6_valuation")

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

        # fcf_base for scenarios (only for tickers that ran a real DCF —
        # financials and regulated utilities both skip this).
        _skip_dcf_downstream = bool(
            is_financial or is_regulated_utility_ticker or is_etf_ticker
            or is_reit_ticker
        )
        _fcf_base_for_scen = None
        if not _skip_dcf_downstream:
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
            # Confidence v2 Phase 1 is gated behind CONFIDENCE_V2=1
            # (see docs/design/confidence-metric-v2.md §8 — rollback is
            # an env-flag flip, no redeploy). Default OFF preserves v1
            # behavior exactly; canary is a no-op with the flag unset.
            try:
                if confidence_v2_enabled():
                    # Tag the engine the rest of the pipeline picked so
                    # sector_engine_match can score it. is_financial is
                    # the only branch decided this far up; downstream
                    # paths override `valuation_model` later. Keep both.
                    if not enriched.get("primary_engine"):
                        enriched["primary_engine"] = (
                            "pb_ratio" if is_financial else "dcf"
                        )
                    return compute_confidence_score_v2(enriched)
                return compute_confidence_score(enriched)
            except Exception:
                return {"score": 50}

        def _run_scenarios():
            # Skip DCF-scenario engine for financials AND regulated
            # utilities — both paths produce iv via a non-DCF route, and
            # running run_scenarios on enriched FCFs would resurrect the
            # very FCF-DCF mis-valuation this PR was built to escape.
            if _skip_dcf_downstream:
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

        # ── feat/recent-ipo-sector-relative-valuation (2026-05-17) ───
        # Recent IPOs (<3 years listed, or <3 annual reports on file)
        # don't have enough audited FCF history for the generic DCF to
        # produce a defensible FV. WAAREEINDO (listed 2024) and ETERNAL
        # (Zomato, listed 2021) were the canonical garbage-FV cases.
        # When detected, we replace the DCF FV with a sector-relative
        # FV derived from cohort P/E (or a coarse P/S fallback when the
        # ticker is pre-profit). The verdict is capped at `data_limited`
        # unless the deviation from price is >30% in either direction
        # (clear-signal threshold). Non-IPO tickers (RELIANCE, INFY,
        # everything else on the canary list) skip this block entirely.
        _is_recent_ipo = False
        _ipo_listing_date: str | None = None
        _ipo_sector_rel: dict | None = None
        try:
            _listing_date_raw = (
                raw.get("listing_date") if isinstance(raw, dict) else None
            )
            # Data-side fallback: count annual rows already in `enriched`.
            _income_df_for_ipo = enriched.get("income_df")
            _n_annual = 0
            if _income_df_for_ipo is not None and hasattr(
                _income_df_for_ipo, "shape"
            ):
                try:
                    _n_annual = int(_income_df_for_ipo.shape[0])
                except Exception:
                    _n_annual = 0
            _data_side_recent = _n_annual > 0 and _n_annual < _IPO_MIN_ANNUAL_REPORTS
            # Pass sector so the recent-IPO window can widen for pharma
            # (60 months vs the 36-month default — see ipo_framework
            # _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR, PR feat/pharma-dcf-fix).
            _ipo_sector = enriched.get("sector") or raw.get("sector")
            if (
                _ipo_is_recent_ipo(ticker, _listing_date_raw, sector=_ipo_sector)
                or _data_side_recent
            ):
                _is_recent_ipo = True
                _ipo_listing_date = _listing_date_raw
            # ── Named-ticker IPO-routing escape hatch ─────────────
            # 2026-05-18 prod regression: PR #320 widened the pharma
            # IPO window to 60mo, which routed MANKIND through
            # compute_sector_relative_fv. The pharma cohort P/E median
            # (~17x) materially under-prices MANKIND's domestic-OTC
            # franchise; FV collapsed from ₹1,244 (pre-PR DCF) to
            # ₹1,046 (post-PR cohort PE × EPS). For named tickers
            # where we have a calibrated terminal_growth_override and
            # the cohort median is a known mis-fit, force the DCF
            # path so the override + R&D candidate actually take
            # effect. See ticker_overrides.py `skip_ipo_routing`.
            if _is_recent_ipo:
                try:
                    _ipo_skip_entry = _get_ticker_override(ticker)
                    if _ipo_skip_entry and _ipo_skip_entry.get(
                        "skip_ipo_routing"
                    ):
                        _is_recent_ipo = False
                        _ipo_listing_date = None
                except Exception:
                    pass
        except Exception:
            _is_recent_ipo = False

        if (
            _is_recent_ipo
            and not is_financial
            and not is_regulated_utility_ticker
            and not is_etf_ticker
            and not is_reit_ticker
            and price
            and price > 0
        ):
            try:
                from backend.services.sector_percentile import (
                    compute_sector_cohort as _ipo_cohort_fn,
                )
                _sess_ipo = _get_pipeline_session()
                _cohort_rows: list[dict] = []
                if _sess_ipo is not None:
                    try:
                        _cohort_rows = _ipo_cohort_fn(
                            sector_label=enriched.get("sector_name")
                            or raw.get("sector_name")
                            or raw.get("sector")
                            or "",
                            db_session=_sess_ipo,
                            industry_label=raw.get("industry")
                            or enriched.get("industry"),
                        ) or []
                    finally:
                        try:
                            _sess_ipo.close()
                        except Exception:
                            pass
                # Derive eps_ttm + revenue_per_share from enriched.
                _shares_ipo = float(enriched.get("shares") or 0) or 0
                _eps_ttm = None
                _rev_ps = None
                if _shares_ipo > 0:
                    _pat_ipo = enriched.get("latest_pat")
                    _rev_ipo = enriched.get("latest_revenue")
                    if _pat_ipo is not None:
                        try:
                            _eps_ttm = float(_pat_ipo) / _shares_ipo
                        except Exception:
                            _eps_ttm = None
                    if _rev_ipo is not None:
                        try:
                            _rev_ps = float(_rev_ipo) / _shares_ipo
                        except Exception:
                            _rev_ps = None
                _ipo_sector_rel = _ipo_compute_sector_relative_fv(
                    eps_ttm=_eps_ttm,
                    revenue_per_share=_rev_ps,
                    cohort=_cohort_rows,
                    price=float(price),
                )
                # Substitute FV when the helper produced one. Otherwise
                # leave the DCF iv as-is and let the downstream verdict
                # logic flip to data_limited via the IPO note.
                if _ipo_sector_rel.get("fair_value"):
                    iv = float(_ipo_sector_rel["fair_value"])
                    iv_raw = iv
            except Exception:
                # Recent-IPO override must never break analysis.
                _ipo_sector_rel = None

        # ── Brand-moat premium overlay (PR feat/fmcg-brand-moat-overlay) ──
        # Curated per-ticker multiplier for the FMCG brand-permanence
        # tail (NESTLE/Maggi, BRITANNIA/Good Day, MARICO/Parachute,
        # GODREJCP/Cinthol-Goodknight, PIDILITIND/Fevicol, GILLETTE/
        # razors, ...). Generic DCF with terminal_g=4% and ~17.9x
        # terminal multiple cannot reach the 50-70x P/E that markets
        # pay for these names; the overlay closes the gap without
        # disturbing the ~half of FMCG that the generic engine values
        # correctly (HUL, ITC, DABUR, COLPAL, PGHH, AKZOINDIA — NOT in
        # the curated dict). Belt-and-braces sector gate: the
        # multiplier is ONLY applied when the resolved sector is FMCG,
        # so a wrongly-classified ticker can never get the premium
        # outside the intended cohort. See docs/design/fmcg-dcf-fix.md.
        try:
            if (
                iv
                and iv > 0
                and not is_financial
                and not is_etf_ticker
                and not is_regulated_utility_ticker
                and is_fmcg_sector(_enriched_sector)
            ):
                _bm_mult = get_brand_moat_multiplier(ticker)
                if _bm_mult > 1.0:
                    _iv_pre_premium = iv
                    iv = round(iv * _bm_mult, 2)
                    bear_iv = round(bear_iv * _bm_mult, 2)
                    bull_iv = round(bull_iv * _bm_mult, 2)
                    _data_issues.append(
                        f"Brand-moat premium applied: {_bm_mult:.2f}x "
                        f"(was ₹{_iv_pre_premium:.0f})"
                    )
        except Exception:
            # The overlay must never break analysis. Leave FV as-is.
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
            if locals().get("_post_demerger_route"):
                # Post-demerger relative valuation (Day-73 Bug D): same
                # rationale as the recent-IPO branch below — peer-cap is
                # a DCF-overshoot heuristic and a category error here.
                _pc = None
            elif _is_recent_ipo:
                # Recent IPOs are valued sector-relative, not via DCF —
                # the peer-cap (which assumes a DCF FV needs taming)
                # would be a category error.
                _pc = None
            elif is_regulated_utility_ticker:
                # Regulated utilities are valued via rate-base, not DCF.
                # The peer-cap heuristic is calibrated for FCF-DCF
                # over-shoots and would silently re-introduce the very
                # mis-valuation this PR was built to escape.
                _pc = None
            elif is_reit_ticker:
                # REITs short-circuit to data_limited with iv=0 — the
                # peer-cap would compute against a zero FV and is
                # meaningless in any case (REITs are valued by NAV +
                # DPU yield, see is_reit_ticker branch in Step 6).
                _pc = None
            elif _trough_anchor_fired:
                # Finding A (audit 2026-05-18): when the cyclical-trough
                # anchor fired (iv was pinned to 0.95*price because the
                # raw DCF residue was <0.2*price), running peer-cap on
                # top trims FV down to peer-median × 1.5 — but the peer
                # set during a sector trough is *also* depressed, so the
                # cap re-introduces the very cycle-bottom signal the
                # anchor was built to escape. Worse, bear/bull are
                # already pinned to the anchored 0.85/1.10 band at L2573
                # below, so a peer-capped base case (typically 0.6-0.8x
                # of price) leaves base OUTSIDE the bear/bull band — an
                # inconsistent story on the frontend (e.g. TATASTEEL
                # bear=134, base=168, bull=230 on 2026-05-18 prod).
                # Skip peer-cap when the anchor fired.
                _pc = None
            elif iv and iv > 0 and not is_financial:
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

        # ── DCF-collapse safety net (feat/dcf-collapse-safety-net) ─
        # Day-1 reconciliation (2026-05-19) showed 301 "we're too
        # low" outliers, with the worst at sub-rupee FVs on ₹300-₹400
        # stocks (INDIACEM ₹0.77 vs ₹405, etc.) — broken generic DCF
        # collapsing the terminal value to near-zero. This block
        # catches those + the 37 "too high" symmetric cases by
        # checking FV/price ratio AFTER peer-cap has had its say.
        #
        # Conservative gates (see backend/services/dcf_collapse_safety_net.py):
        #   • Only fires when ratio outside [0.1, 5.0].
        #   • Never fires on dedicated sector engines (rate_base /
        #     pb_ratio / appraisal_value / REIT / ETF / holdco /
        #     realty / recent-IPO sector-relative).
        #   • Never fires on cyclical-trough sectors (the trough
        #     anchor at L1746 owns those — would double-correct).
        #
        # On success: swap in Tier 2 cohort FV + tag
        #   `_fair_value_source = "tier2_fallback"` + audit caveat.
        # On Tier 2 also unavailable: set `_dcf_collapse_unrescued`
        # so the verdict block below forces `data_limited` rather
        # than shipping a dishonest "Notably Undervalued at ₹0.77".
        #
        # Sector-scope: * (universal — applies to every generic-DCF
        # ticker that escaped the existing sector branches).
        _dcf_collapse_unrescued = False
        try:
            from backend.services.dcf_collapse_safety_net import (
                attempt_tier2_fallback as _dcf_safety_fallback,
                clamp_inflated_scenarios as _dcf_clamp_inflated,
                is_fv_unreasonable as _dcf_is_unreasonable,
            )

            # ── Phase B.2 (2026-05-24): bull sanity pre-clamp ───────
            # Day-107a IT-services WACC drop (0.1114 → 0.098) inflated
            # the WIPRO/HCLTECH/TECHM generic DCF — bulls landed at
            # 33× CMP, bases at 4× CMP. The base inflation tripped the
            # safety net's INFLATED_RATIO_HI=3.5 gate, the Tier-2/
            # platform/story rescue rungs ALL returned None (the IT
            # cohort itself has the broken-low-WACC contagion), and
            # `_dcf_collapse_unrescued=True` forced verdict=data_limited
            # on three of the top-7 IT names. Phase B.0 diagnostic
            # `docs/diagnostics/phase-b-cache-paths-2026-05-24.md` §4
            # recommended option (b): pre-clamp at the bull-side
            # `> 5× CMP` boundary. When bull is implausibly inflated we
            # proportionally clamp base+bear too so the band stays
            # ordered and the iv check below sees a sane base FV.
            if price and price > 0:
                _clamp = _dcf_clamp_inflated(
                    base_fv=float(iv),
                    bull_fv=float(bull_iv or 0),
                    bear_fv=float(bear_iv or 0),
                    current_price=float(price),
                )
                if _clamp is not None:
                    _bc, _ubc, _brc, _clamp_reason = _clamp
                    iv = _bc
                    bull_iv = _ubc
                    bear_iv = _brc
                    _data_issues = list(_data_issues) + [
                        f"[dcf_collapse_safety_net] {_clamp_reason}. "
                        "Likely cause: too-low sector WACC. Scenarios "
                        "re-anchored to current price band to avoid "
                        "data_limited fallout."
                    ]

            # Mirror the same engine-label logic the response builder
            # uses below so the safety net sees the actual engine that
            # produced `iv`. This must stay in sync with the
            # `valuation_method` derivation around L3725-3733.
            if is_etf_ticker:
                _engine_now = "etf_nav_based"
            elif is_reit_ticker:
                _engine_now = "reit_nav_dpu_required"
            elif is_regulated_utility_ticker:
                _engine_now = "rate_base"
            elif locals().get("_post_demerger_route"):
                # Day-73 Bug D: post-demerger relative valuation — the
                # safety net's [0.1, 5.0] FV/CMP gate is calibrated for
                # DCF over/under-shoot and is not meaningful here.
                _engine_now = "relative_post_demerger"
            elif locals().get("_is_recent_ipo") and locals().get("_fair_value_source") == "sector_relative_recent_ipo":
                _engine_now = "sector_relative_recent_ipo"
            elif is_financial:
                _engine_now = "pb_ratio"
            else:
                _engine_now = _fair_value_source  # "dcf" or "peer_capped"

            _sector_now = (
                (locals().get("_enriched_sector") if isinstance(locals().get("_enriched_sector"), str) else None)
                or (enriched.get("sector_name") if isinstance(enriched, dict) else None)
                or (raw.get("sector_name") if isinstance(raw, dict) else None)
                or (raw.get("sector") if isinstance(raw, dict) else None)
                or (company.sector if getattr(company, "sector", None) else None)
            )

            if _dcf_is_unreasonable(iv, price):
                # Build a minimal financials + peers payload for Tier 2.
                _shares_sn = float(enriched.get("shares") or 0) or 0
                _pat_sn = enriched.get("latest_pat")
                _eps_sn: Optional[float] = None
                if _shares_sn > 0 and _pat_sn is not None:
                    try:
                        _eps_sn = float(_pat_sn) / _shares_sn
                    except Exception:
                        _eps_sn = None
                # Day-20 (2026-05-20): added "revenue" + "latest_revenue"
                # fields. Without these, the safety-net's 3rd rung (Story
                # DCF) immediately returns None at the rev0 <= 0 guard in
                # compute_story_dcf_fair_value. Live measurement confirmed:
                # DELHIVERY recomputed at v121, safety net fired, all 3
                # rungs returned None, but the data_issues caveat showed
                # the rescue chain ran — Story-DCF couldn't fire because
                # the _fin_sn dict had no revenue field. The downstream
                # net_debt field is _Cr-denominated so revenue stays in
                # paise/rupees (engine handles the Cr conversion).
                _revenue_raw = enriched.get("revenue") or enriched.get("latest_revenue")
                _fin_sn = {
                    "eps": _eps_sn,
                    "ebitda": enriched.get("ebitda"),
                    "revenue": _revenue_raw,
                    "latest_revenue": _revenue_raw,
                    "shares": _shares_sn,
                    "roce": enriched.get("roce") or enriched.get("roce_pct"),
                    "piotroski": piotroski.get("score") if isinstance(piotroski, dict) else None,
                    "market_cap_cr": (
                        (float(enriched.get("market_cap") or 0) / 1e7)
                        if enriched.get("market_cap") else None
                    ),
                    "bvps": enriched.get("bvps"),
                    "net_debt_cr": (
                        (float(enriched.get("total_debt") or 0) - float(enriched.get("total_cash") or 0)) / 1e7
                    ),
                    "current_price": float(price) if price else None,
                }

                # Peer list: best-effort. The safety-net path is
                # additive; if peer enrichment isn't available here
                # we pass [] and let Tier 2 surface "no cohort" → None.
                _peer_sn: list[dict] = []
                try:
                    from backend.services.peer_cap_service import (
                        fetch_peer_records_for_ticker as _fetch_peers_sn,
                    )
                    _peer_sn = list(_fetch_peers_sn(ticker) or [])
                except Exception:
                    _peer_sn = []

                _sn_result = _dcf_safety_fallback(
                    ticker=ticker,
                    current_fv=float(iv),
                    current_price=float(price) if price else 0.0,
                    sector=_sector_now,
                    sector_engine_used=_engine_now,
                    financials=_fin_sn,
                    peers=_peer_sn,
                )

                if _sn_result is not None:
                    _new_fv, _sn_source = _sn_result
                    _data_issues = list(_data_issues) + [
                        f"[dcf_collapse_safety_net] DCF FV (₹{float(iv):.2f}) "
                        f"was unreasonable vs price (₹{float(price):.2f}); "
                        f"substituted rescued FV (₹{_new_fv:.2f}). "
                        f"Source: {_sn_source}."
                    ]
                    iv = round(float(_new_fv), 2)
                    # Preserve the rung-specific engine string emitted by
                    # the safety net (one of:
                    #   "tier2_fallback_after_dcf_collapse",
                    #   "platform_ps_after_dcf_collapse",
                    #   "story_dcf_after_dcf_collapse")
                    # so the frontend StoryDcfBadge / Platform badge can
                    # fire and so analytics know WHICH rung rescued.
                    # Day-10 fix — Day-7 had collapsed all three to the
                    # generic "tier2_fallback" string, suppressing the
                    # downstream badge.
                    _fair_value_source = _sn_source or "tier2_fallback"
                elif _engine_now in ("dcf", "peer_capped"):
                    # Tier 2 also couldn't compute — honestly surface
                    # as data_limited. The verdict block below reads
                    # `_dcf_collapse_unrescued` and forces the verdict.
                    _dcf_collapse_unrescued = True
                    _data_issues = list(_data_issues) + [
                        "[data_limited] DCF produced unreasonable FV vs "
                        "price; sector-relative fallback also unavailable. "
                        "Manual review needed."
                    ]
        except Exception as _sn_exc:  # noqa: BLE001
            # The safety net must NEVER break analysis. Log and move on.
            try:
                import logging as _logging
                _logging.getLogger("yieldiq.analysis").warning(
                    "dcf_collapse_safety_net failed for %s: %s",
                    ticker, _sn_exc,
                )
            except Exception:
                pass

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

        # Phase C.2 PR 1 (2026-05-25): the prior TypeError fallback ran
        # a DIFFERENT scoring formula (40/30/20 envelopes, no sentiment)
        # that diverged from the canonical compute_yieldiq_score. Since
        # the 2026-04-30 hardening (decimal-or-percent rev_growth guard,
        # None-safe analyst_upside) the canonical function tolerates
        # every input shape the pipeline emits, so the fallback is
        # unreachable. Removing it eliminates the silent-divergence
        # quirk documented in phase-c-score-formula-2026-05-25.md §4 #2.
        # On the unlikely event of a future TypeError, surface it as a
        # logged exception with a defensive zero-score (verdict will
        # already gate via data_limited) rather than producing a
        # divergent score under the same field name.
        try:
            yiq_score = compute_yieldiq_score(
                mos_pct=mos_pct,
                piotroski=piotroski.get("score", 0),
                moat_grade=moat_result.get("grade", "None"),
                rev_growth=enriched.get("revenue_growth", 0),
                analyst_upside=_analyst_upside,
            )
        except TypeError as _te:
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").exception(
                "scoring TypeError for ticker=%s (compute_yieldiq_score "
                "rejected inputs: mos=%r pio=%r moat=%r rev=%r upside=%r). "
                "Returning zero score — investigate the upstream guard.",
                ticker, mos_pct,
                piotroski.get("score", 0),
                moat_result.get("grade", "None"),
                enriched.get("revenue_growth", 0),
                _analyst_upside,
            )
            yiq_score = {"score": 0, "grade": "D", "components": {}}

        _record_step("step7_quality")

        # ── Step 8: Scenarios ─────────────────────────────────
        # `scenarios_raw` was computed in the parallel wave above
        # (empty dict for financials by design).

        def _sc(key):
            d = scenarios_raw.get(key, {})
            _raw = d.get("mos_pct", 0)
            _disp, _clamp = display_mos(_raw)
            _iv = d.get("iv", 0) or 0
            _bmos = buffett_mos_pct(_iv, price)
            return ScenarioCase(
                iv=_iv,
                mos_pct=(_disp if _disp is not None else 0),
                buffett_mos_pct=round(_bmos, 1) if _bmos is not None else None,
                mos_clamped=_clamp,
                growth=d.get("growth", 0), wacc=d.get("wacc", wacc),
                term_g=d.get("term_g", terminal_g),
            )

        _record_step("step8_scenarios")

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
        # Fetch shareholding once and reuse below (perf: avoids a 2nd
        # DB roundtrip at the shareholding-breakdown block ~line 1995).
        _sh_data = _query_shareholding(ticker)
        if _promoter_pledge is None:
            # Fall back to ShareholdingPattern DB table
            _promoter_pledge = _sh_data.get("promoter_pledge_pct") if _sh_data else None
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

        _record_step("step9_insights")

        # ── Step 10: Verdict ──────────────────────────────────
        _conf_score = confidence.get("score", 50)

        # ── Null-CAGR data-limited gate v2 (deferred) ────────────
        # The proper gate runs AFTER `_rev_cagr_3y` / `_rev_cagr_5y`
        # are computed at ~line 1782. Prior in-place gate (49e5add)
        # over-fired because it tried to recompute CAGR from
        # `enriched["income_df"]` too early in the pipeline. See the
        # post-CAGR override block below for the v2 implementation.
        _null_cagr_gate_tripped = False

        # ── DCF-collapse safety-net verdict override ─────────────
        # When the safety net engaged AND Tier 2 also couldn't help,
        # the only honest verdict is data_limited. Take this branch
        # BEFORE the normal verdict tree below so the caveat already
        # appended in _data_issues lines up with the verdict on the
        # response.  See backend/services/dcf_collapse_safety_net.py.
        if locals().get("_dcf_collapse_unrescued"):
            verdict = "data_limited"
        elif is_financial:
            # Financial companies: simple MoS verdict, NEVER "avoid"
            if iv <= 0:
                verdict = "data_limited"
            elif mos_pct > 15:
                verdict = "undervalued"
            elif mos_pct > -15:
                verdict = "fairly_valued"
            else:
                verdict = "overvalued"
        # ── Confidence-based data_limited gate (tightened 2026-05-24) ──
        # Prior behaviour: any ticker with `_conf_score < 35` (or label in
        # {"low","unusable"}) AND `|mos|>40` was forced to `data_limited`,
        # even when the DCF engine produced a complete, well-formed
        # valuation (iv > 0, scenarios present, wacc/growth all populated).
        # That hid honest computed numbers on names like LT.NS (conf=33,
        # MoS=-43.7%, FV=2211.55, bear/base/bull all populated) under a
        # "we can't compute" label.
        #
        # New rule: `data_limited` requires BOTH (a) low confidence AND
        # (b) at least one of the scenarios genuinely missing (iv<=0 OR
        # bear/base/bull <= 0). When the engine produced a full scenario
        # triangle the verdict reverts to the standard MoS bands below;
        # low confidence on its own is surfaced via the frontend's
        # `shouldGateVerdict` helper (Day-91) which renders the
        # "Under Review" pill + caution chip without erasing the numbers.
        elif (
            _confidence in ("low", "unusable")
            and abs(mos_pct) > 40
            and clean_ticker not in INVENTORY_HEAVY_TICKERS
            and (
                iv <= 0
                or (bear_iv or 0) <= 0
                or (bull_iv or 0) <= 0
            )
        ):
            verdict = "data_limited"
        elif (
            _conf_score < 35
            and abs(mos_pct) > 40
            and clean_ticker not in INVENTORY_HEAVY_TICKERS
            and (
                iv <= 0
                or (bear_iv or 0) <= 0
                or (bull_iv or 0) <= 0
            )
        ):
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

        # ── Earnings date (unified service: NSE → yfinance) ─
        # feat/earnings-calendar-unification: route every surface
        # through earnings_calendar_service so the Summary card,
        # Discover strip and Home strip can never disagree about
        # the next reporting date. The service also adds a yfinance
        # fallback so Nifty-50 stocks no longer show "Not scheduled"
        # on days when the NSE event-calendar API blanks (incident
        # 2026-05-17). Finnhub remains a final fallback for the
        # est_eps field only (no date — the service supersedes it).
        from backend.services.earnings_calendar_service import (
            get_next_earnings_dict as _unified_next_earnings,
        )
        _earnings_pipeline_db = _get_pipeline_session()
        _earnings: dict | None = None
        if _earnings_pipeline_db is not None:
            try:
                _earnings = _unified_next_earnings(ticker, _earnings_pipeline_db)
            except Exception:
                _earnings = None
            finally:
                try:
                    _earnings_pipeline_db.close()
                except Exception:
                    pass
        _earnings_date = (
            _earnings.get("date") if _earnings
            else (raw.get("finnhub_next_earnings") or {}).get("date")
        )
        earnings_days_until = _earnings.get("days_until") if _earnings else None
        _earnings_confirmed = _earnings.get("confirmed") if _earnings else None
        _earnings_source = _earnings.get("source") if _earnings else (
            "finnhub" if (raw.get("finnhub_next_earnings") or {}).get("date") else None
        )
        _earnings_fiscal_period = _earnings.get("fiscal_period") if _earnings else None

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
        # Day-92 (2026-05-22): regulated utilities (NTPC, POWERGRID,
        # NLCINDIA, JSWENERGY, NTPCGREEN, IREDA, ...) route through
        # `regulated_utility_valuation_service` which short-circuits the
        # generic DCF. That means `scenarios_raw` (built from DCF cash
        # flows by `run_scenarios`) is empty/zero for these tickers, and
        # the non-financial branch below would build _sc_bear_pre off
        # `scenarios_raw["Bear case"]` → bear_iv=0. `_enforce_scenario_order`
        # then accepts (0 <= base <= bull) as "ordered" and ships bear=₹0
        # to the public stock-summary endpoint (audit #4 2026-05-22 found
        # NTPC + POWERGRID with bear_case=0.0).
        #
        # The regulated-utility engine itself ALREADY produces sensible
        # bear/bull (0.75/1.25 of base — Gordon ± tariff true-up band)
        # and writes them into bear_iv / bull_iv up at L1546-1547. So the
        # fix is structural: treat the regulated_utility branch like the
        # financial branch — build _sc_bear_pre / _sc_bull_pre directly
        # off bear_iv / bull_iv instead of rebuilding from scenarios_raw.
        # Additionally apply the same defensive floor Day-56 introduced
        # for cyclicals: bear must be at least 0.85 * price (mid-cycle
        # pessimism floor for a bond-like regulated cash flow) and bull
        # must be at least 1.10 * price. These floors only widen the
        # band, never tighten it (we take min for bear-cap below iv,
        # max for bull above iv).
        _is_regulated_utility_engine = bool(
            locals().get("is_regulated_utility_ticker", False)
            and locals().get("_regulated_val_result")
            and float(_regulated_val_result.get("fair_value", 0) or 0) > 0
        )
        if is_financial or _is_regulated_utility_engine:
            # For regulated utilities, apply a defensive floor mirroring
            # the Day-56 cyclical pattern so bear never collapses to ₹0
            # and bull always has visible upside vs price. Floors only
            # widen the band — they never override a tighter engine
            # result that's already above the floors.
            if _is_regulated_utility_engine and price > 0:
                _ru_bear_floor = round(min(0.85 * price, iv * 0.95), 2)
                _ru_bull_floor = round(max(1.10 * price, iv * 1.05), 2)
                # Engine produces 0.75*base / 1.25*base. Take the wider
                # band (engine vs floor) on each side so the floor only
                # kicks in when the engine's own values would push bear
                # close to zero (e.g. low-WACC utilities where the engine
                # collapsed or the result was overwritten downstream).
                if bear_iv <= 0 or bear_iv < _ru_bear_floor * 0.5:
                    # Engine bear missing or implausibly low → use floor.
                    bear_iv = _ru_bear_floor
                if bull_iv <= 0 or bull_iv < iv:
                    bull_iv = _ru_bull_floor
                import logging as _ru_floor_log
                _ru_floor_log.getLogger("yieldiq.analysis").info(
                    "REGULATED_UTILITY_BEAR_FLOOR: %s price=%.2f iv=%.2f "
                    "bear=%.2f bull=%.2f (floor bear=%.2f bull=%.2f)",
                    ticker, price, iv, bear_iv, bull_iv,
                    _ru_bear_floor, _ru_bull_floor,
                )
            _bear_raw = ((bear_iv - price) / price * 100) if price > 0 else 0
            _bull_raw = ((bull_iv - price) / price * 100) if price > 0 else 0
            _bear_d, _bear_c = display_mos(_bear_raw)
            _bull_d, _bull_c = display_mos(_bull_raw)
            _bear_bmos = buffett_mos_pct(bear_iv, price)
            _bull_bmos = buffett_mos_pct(bull_iv, price)
            _sc_bear_pre = ScenarioCase(
                iv=bear_iv,
                mos_pct=round(_bear_d if _bear_d is not None else 0, 1),
                buffett_mos_pct=round(_bear_bmos, 1) if _bear_bmos is not None else None,
                mos_clamped=_bear_c,
                growth=0, wacc=round(wacc, 4), term_g=round(terminal_g, 4),
            )
            _sc_bull_pre = ScenarioCase(
                iv=bull_iv,
                mos_pct=round(_bull_d if _bull_d is not None else 0, 1),
                buffett_mos_pct=round(_bull_bmos, 1) if _bull_bmos is not None else None,
                mos_clamped=_bull_c,
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
                # Day-53c (2026-05-21): generalize the Day-51 re-clamp.
                # Any iv override AFTER the trough anchor fires (Tier-2
                # cohort, growth-stock override, future overrides) can
                # push base below the trough-anchor bear floor → gate-3
                # scenario_dispersion FAIL (bear > base). Day-51 patched
                # only the Tier-2 path; canary 2026-05-21 still failed
                # on GUJGASLTD/HINDZINC/COROMANDEL coming through other
                # paths. Re-clamping here at the point of USE catches
                # every path: by the time we're rendering scenarios,
                # iv is final, so anchoring bear/bull off iv (not the
                # stale trough-anchor values) is universally correct.
                if price > 0:
                    _bear_iv_val = round(min(_trough_anchor_bear_iv, iv * 0.95), 2)
                    _bull_iv_val = round(
                        max(_trough_anchor_bull_iv or round(price * 1.10, 2), iv * 1.05),
                        2,
                    )
                else:
                    _bear_iv_val = _trough_anchor_bear_iv
                    _bull_iv_val = _trough_anchor_bull_iv or round(price * 1.10, 2)
                _t_bear_raw = ((_bear_iv_val - price) / price * 100) if price > 0 else 0
                _t_bull_raw = ((_bull_iv_val - price) / price * 100) if price > 0 else 0
                _t_bear_d, _t_bear_c = display_mos(_t_bear_raw)
                _t_bull_d, _t_bull_c = display_mos(_t_bull_raw)
                _t_bear_bmos = buffett_mos_pct(_bear_iv_val, price)
                _t_bull_bmos = buffett_mos_pct(_bull_iv_val, price)
                _sc_bear_pre = ScenarioCase(
                    iv=_bear_iv_val,
                    mos_pct=round(_t_bear_d if _t_bear_d is not None else 0, 1),
                    buffett_mos_pct=round(_t_bear_bmos, 1) if _t_bear_bmos is not None else None,
                    mos_clamped=_t_bear_c,
                    growth=round(base_growth, 4),
                    wacc=round(wacc, 4), term_g=round(terminal_g, 4),
                )
                _sc_bull_pre = ScenarioCase(
                    iv=_bull_iv_val,
                    mos_pct=round(_t_bull_d if _t_bull_d is not None else 0, 1),
                    buffett_mos_pct=round(_t_bull_bmos, 1) if _t_bull_bmos is not None else None,
                    mos_clamped=_t_bull_c,
                    growth=round(base_growth, 4),
                    wacc=round(wacc, 4), term_g=round(terminal_g, 4),
                )
        _base_d, _base_c = display_mos(mos_pct)
        _base_bmos = buffett_mos_pct(iv, price)
        _sc_base_pre = ScenarioCase(
            iv=round(iv, 2),
            mos_pct=round(_base_d if _base_d is not None else 0, 1),
            buffett_mos_pct=round(_base_bmos, 1) if _base_bmos is not None else None,
            mos_clamped=_base_c,
            growth=round(base_growth, 4),
            wacc=round(wacc, 4), term_g=round(terminal_g, 4),
        )
        _scenarios_clamped = _enforce_scenario_order(
            bear=_sc_bear_pre, base=_sc_base_pre, bull=_sc_bull_pre, price=price,
        )

        # Finding C (audit 2026-05-18): secondary bear-floor guard for
        # cyclicals. The primary cyclical-trough anchor (L1762) only
        # fires when iv < 0.2 * price; tickers in the "0.2-0.5 twilight"
        # (e.g. IOC at iv/price=0.37 on 2026-05-18 prod) bypass the
        # anchor but the DCF engine can still emit a near-zero bear
        # case (IOC shipped bear=₹1.59 on a ₹131.81 stock). The
        # _enforce_scenario_order check accepts it because 1.59 <= 49.36
        # <= 117.87 is "ordered". This is the exact display pathology
        # PR #168 was built to prevent.
        #
        # Clamp the bear case to 0.5 * price for cyclicals when it
        # falls below that floor. Skip the trough-anchor branch (already
        # pinned bear to 0.85 * price upstream — different, stronger
        # rescue path). We deliberately do NOT re-run
        # `_enforce_scenario_order` here: if the underlying base FV is
        # itself below 0.5 * price (e.g. IOC base ~0.37 * price) the
        # re-clamp would force bear back down to 0.80 * base and
        # re-introduce the very ₹0-bear pathology this floor is
        # designed to prevent. Accepting bear >= base in pathological
        # cases is preferable to bear == ₹1.59 on the public page;
        # the base FV itself being too low is a separate engine
        # investigation (see Finding B in the audit).
        if (
            price > 0
            and is_cyclical(ticker, _resolved_sector_for_cycle)
            and not _trough_anchor_fired
            and _scenarios_clamped.bear.iv < 0.5 * price
        ):
            # Day-56 (2026-05-21): respect scenario ordering when the
            # bear-floor would push bear above base. The original
            # comment (Finding C 2026-05-18) deliberately allowed
            # bear >= base because the alternative was bear=₹1.59 on
            # tickers like IOC where base FV < 0.5*price. Canary 2026-
            # 05-20 caught this on HINDZINC/COROMANDEL/GUJGASLTD —
            # gate-3 scenario_dispersion FAILs because bear > base.
            #
            # Fix: floor bear at min(0.5*price, 0.95*base) instead of
            # just 0.5*price. For HINDZINC (base 307, price 630) the
            # original gave bear=315 > base; this gives
            # min(315, 291.7) = 291.7 — still meaningfully above the
            # ₹0 pathology the Finding-C guard was built to prevent,
            # AND strictly below base so the scenarios always order.
            #
            # For IOC (base 49.36, price 131.81) the original would
            # have given bear=65.9, this gives min(65.9, 46.9) = 46.9
            # — slightly below base, but far above the ₹1.59 the bare
            # engine produces. Strictly better in every direction.
            _floor_bear_iv = round(min(0.5 * price, iv * 0.95), 2)
            _floor_bear_raw = ((_floor_bear_iv - price) / price * 100)
            _floor_bear_d, _floor_bear_c = display_mos(_floor_bear_raw)
            _floor_bear_bmos = buffett_mos_pct(_floor_bear_iv, price)
            _floored_bear = ScenarioCase(
                iv=_floor_bear_iv,
                mos_pct=round(_floor_bear_d if _floor_bear_d is not None else 0, 1),
                buffett_mos_pct=round(_floor_bear_bmos, 1) if _floor_bear_bmos is not None else None,
                mos_clamped=_floor_bear_c,
                growth=_scenarios_clamped.bear.growth,
                wacc=_scenarios_clamped.bear.wacc,
                term_g=_scenarios_clamped.bear.term_g,
            )
            import logging as _bear_floor_log
            _bear_floor_log.getLogger("yieldiq.analysis").info(
                "CYCLICAL_BEAR_FLOOR: %s bear=%.2f below 0.5*price=%.2f; "
                "clamping bear to %.2f (base=%.2f, bull=%.2f preserved)",
                ticker, _scenarios_clamped.bear.iv, 0.5 * price,
                _floor_bear_iv, _scenarios_clamped.base.iv,
                _scenarios_clamped.bull.iv,
            )
            _scenarios_clamped = ScenariosOutput(
                bear=_floored_bear,
                base=_scenarios_clamped.base,
                bull=_scenarios_clamped.bull,
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
        #
        # Task #264 (2026-06-09): caller-side verdict gate as well as
        # the inner gate in store_today_fair_value(). Belt-and-braces —
        # the inner gate is the authoritative skip rule (NON_CHARTABLE_VERDICTS)
        # but skipping the threading.Thread spawn entirely when we already
        # know the row will be rejected saves a session checkout +
        # connection round-trip on Neon's free-tier connection budget.
        # composite-spine 2026-06-12: the fair_value_history write was
        # RELOCATED from here to after the verdict is finalized (after the
        # composite-headline re-band + the Layer-C confidence verdict gate).
        # Previously it ran here on the raw single-stage DCF `iv` + the
        # pre-gate DCF verdict — so the historical record (and everything
        # that reads it: the public /calibration page, the backtest, the
        # FV-vs-price chart) was permanently DCF-only even though the
        # headline served to users was meant to be the composite. The write
        # now lives at the "DEFERRED FV-HISTORY WRITE (composite-spine)"
        # block below, using the final _headline_fv / mos_pct / verdict.
        # See docs/ENGINE_ROOT_CAUSE_2026-06-12.md.

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
        # Delegates to the unified is_bank_like (constants.py) so this
        # block agrees with `is_financial` above and with Prism/Hex.
        _is_bank_like = bool(
            is_financial
            or is_bank_like(ticker, company.sector, _industry)
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
        # FIX-AUDIT5-P1-ASSET-TURNOVER-UNIT (Task#87, 2026-05-22):
        # Same unit-mismatch family as FIX-ROCE-UNIT-MISMATCH above.
        # `enriched.latest_revenue` is in Crores, but
        # `_total_assets = enriched.get("total_assets") or _ta_db or 0`
        # picks the raw-INR yfinance value first (e.g. TCS.NS = 1.82e12).
        # The resulting ratio (~1e-7) trips PR #498's [0.001, 100] sanity
        # gate and returns None, so RELIANCE/TATASTEEL/ULTRACEMCO/TCS/INFY
        # all render "n/a" despite clean DB data.
        #
        # Fix: prefer DB-sourced _ta_db (Crores) over enriched.total_assets
        # so revenue and total_assets share the same unit. Mirrors the
        # _ta_for_roce / _cl_for_roce pattern at line 3536.
        _ta_for_at = _ta_db if _ta_db is not None else _total_assets
        _asset_turnover = _at(
            enriched.get("latest_revenue") or enriched.get("revenue"),
            _ta_for_at,
        )

        # ── Audit#5 P1 de_ratio null-safety (2026-05-22) ──────
        # ``enriched["de_ratio"]`` comes from data/collector.py:1668
        # which coerces ``info.get("debtToEquity")`` to ``0`` whenever
        # the yfinance field is missing. That made TATASTEEL /
        # ADANIPORTS / RELIANCE / NTPC etc. render as "net cash"
        # in the ratio grid despite carrying material debt (audit
        # found 17/17 universe tickers at 0.0).
        #
        # Resolution order:
        #   1. ``ratio_history.de_ratio`` (XBRL-pipeline truth, same
        #      source the screener uses).
        #   2. ``enriched["de_ratio"]`` ONLY when it's a credible
        #      non-zero value, OR when total_debt is also genuinely
        #      zero (cash-rich IT names like TCS / INFY stay at 0).
        #   3. ``None`` — frontend renders "—".
        #
        # Bank D/E (Day-111b, 2026-05-23): banks ARE now special-
        # cased in ``financials_service._compute_de_ratio`` —
        # commercial banks get D/E = (total_liab - equity) / equity
        # so deposits + borrowings (the dominant interest-bearing
        # liabilities) land in the numerator. HDFCBANK previously
        # surfaced ~0.95 (total_debt / equity, excludes deposits);
        # now lands at ~7-8, matching Screener.in. Done in the
        # financials service so the same value flows through every
        # caller (ratios grid, AI description, sector page).
        _de_db = _fetch_de_ratio(ticker)
        _de_enriched = enriched.get("de_ratio")
        if _de_db is not None:
            _de_resolved: float | None = _de_db
        elif _de_enriched is None:
            _de_resolved = None
        else:
            try:
                _de_f = float(_de_enriched)
            except (TypeError, ValueError):
                _de_f = None
            if _de_f is None or _de_f != _de_f:
                _de_resolved = None
            elif _de_f == 0.0 and (_total_debt or 0) > 0:
                # yfinance returned 0 but the balance sheet says
                # there IS debt — the 0 is the null-cast bug, not
                # a real zero. Surface as None.
                _de_resolved = None
            else:
                _de_resolved = _de_f

        _rev_cagr_3y = None
        _rev_cagr_5y = None
        try:
            _inc = enriched.get("income_df")
            if _inc is not None and hasattr(_inc, "empty") and not _inc.empty \
                    and "revenue" in _inc.columns:
                _rev_series = _inc["revenue"].dropna().tolist()
                # FIX-HDFC-MERGER-CAGR (2026-05-18): route through
                # corporate_actions_service so tickers with a seeded
                # STRUCTURAL break (REVERSE_MERGER / MERGER / DEMERGER
                # / SCHEME_OF_ARRANGEMENT / MATERIAL_ACQUISITION) inside
                # the trailing window get the merger fiscal year
                # truncated out of the CAGR base. Non-seeded tickers
                # fall through to plain compute_revenue_cagr (byte-
                # identical). See
                # docs/design/hdfc-merger-growth-normalization.md.
                try:
                    from backend.services.corporate_actions_service import (
                        compute_cagr_structural_aware as _cagr_sa,
                    )
                    _latest_pe = enriched.get("latest_period_end")
                    _rev_cagr_3y = _cagr_sa(
                        ticker, "revenue", 3,
                        series=_rev_series,
                        latest_period_end=_latest_pe,
                    )
                    _rev_cagr_5y = _cagr_sa(
                        ticker, "revenue", 5,
                        series=_rev_series,
                        latest_period_end=_latest_pe,
                    )
                except Exception:
                    # Defensive: any failure in the overlay falls back
                    # to the legacy plain-CAGR path so we never regress
                    # a working ticker because the overlay misbehaves.
                    _rev_cagr_3y = _rcagr(_rev_series, 3)
                    _rev_cagr_5y = _rcagr(_rev_series, 5)
        except Exception:
            pass

        # ── DB-backed CAGR fallback (null-CAGR data_limited fix,
        #    2026-06-13) ────────────────────────────────────────────
        # The income_df above is only as deep as whatever source served
        # this ticker. The local-DB assembler caps annual rows at
        # LIMIT 5 and the yfinance collector frequently returns only a
        # TTM / 1-2yr income statement for thin-coverage mid-caps. When
        # that leaves BOTH 3y and 5y CAGR None, the downstream null-CAGR
        # gate (FIX 1 below) forces data_limited — even for names that
        # have ≥3 years of genuine annual revenue in the financials DB
        # and a fully-formed, sound DCF (e.g. AARTIIND: 11 annual rows
        # FY2018→FY2026, complete scenario triangle, FV/price ~0.31).
        #
        # Fix: when (and only when) a CAGR is still missing, recompute it
        # from `v_financials_unified` — the reconciliation view that
        # emits exactly one DE-DUPED row per (ticker, fiscal_year),
        # already collapsing the cf_has_duplicate_fy / cf_is_corrupt
        # cohort (e.g. AARTIIND's duplicate FY2023 & FY2024 rows). This
        # is ADDITIVE: it can only fill a None CAGR, never overwrite a
        # value income_df already produced. Genuinely thin nano-caps
        # (no/too-few annual rows in the view) get [] back → CAGR stays
        # None → they correctly STAY data_limited. The ±80% clamp below
        # still nulls out any mixed-unit / restructuring artifact.
        if _rev_cagr_3y is None or _rev_cagr_5y is None:
            try:
                import logging as _cagr_fb_logging
                from backend.services.analysis.db import (
                    _fetch_annual_revenue_series,
                )
                _cagr_fb_log = _cagr_fb_logging.getLogger("yieldiq.analysis")
                _db_rev_series = _fetch_annual_revenue_series(ticker)
                # compute_revenue_cagr requires the full (years + 1)
                # window of consecutive non-None values; <4 rows can
                # never yield a 3y CAGR, <6 a 5y CAGR. The helper itself
                # returns None below the threshold, so the len guards
                # are purely to skip the call.
                if len(_db_rev_series) >= 4 and _rev_cagr_3y is None:
                    _db_cagr_3y = _rcagr(_db_rev_series, 3)
                    if _db_cagr_3y is not None:
                        _rev_cagr_3y = _db_cagr_3y
                        _cagr_fb_log.info(
                            "cagr_db_fallback.filled_3y ticker=%s n=%d",
                            ticker, len(_db_rev_series),
                        )
                if len(_db_rev_series) >= 6 and _rev_cagr_5y is None:
                    _db_cagr_5y = _rcagr(_db_rev_series, 5)
                    if _db_cagr_5y is not None:
                        _rev_cagr_5y = _db_cagr_5y
                        _cagr_fb_log.info(
                            "cagr_db_fallback.filled_5y ticker=%s n=%d",
                            ticker, len(_db_rev_series),
                        )
            except Exception:
                # Never let the fallback regress a ticker: any failure
                # leaves the income_df-derived CAGR (possibly None)
                # untouched, preserving pre-fix behaviour exactly.
                pass

        # Sanity clamp: CAGR outside ±80% is almost certainly a data
        # artifact (currency conversion error, one-off spinoff/demerger,
        # bad yfinance row). Audit feedback: HCLTECH showed -75.5% 3y
        # CAGR, but its real 3y CAGR is +7-10%. Clamp to None so the
        # UI renders "—" instead of an obviously-wrong reading. Real
        # business CAGR outside ±80% for established companies would
        # have a manual review anyway (likely a special situation).
        #
        # Task #244 (2026-05-29): widened ±50% → ±80% so a single
        # restructuring fiscal year (e.g. WIPRO FY23 segment
        # reorganisation where the trailing 3y/5y windows pick up a
        # one-off base distortion of ~55-65%) does not null out both
        # CAGR series and trip the downstream null-CAGR gate at
        # data_limited. The HCLTECH-class -75% artifact is still caught
        # by the wider bound. The narrower ±50% bound previously
        # collapsed restructured-FY tickers to data_limited even when
        # the rest of the engine had produced a complete valuation.
        def _sanitize_cagr(v):
            if v is None:
                return None
            try:
                return None if abs(float(v)) > 0.80 else v
            except (TypeError, ValueError):
                return None
        _rev_cagr_3y = _sanitize_cagr(_rev_cagr_3y)
        _rev_cagr_5y = _sanitize_cagr(_rev_cagr_5y)

        # ── P0 BATCH A1 (2026-05-02) ─────────────────────────────
        # Three verdict-logic fixes that need post-CAGR / post-ROCE
        # context: (1) null-CAGR gate v2, (2) cross-pillar moat
        # sanity, (3) score-MoS dominance. Bellwether allowlist
        # exempts top private banks + never-super-cyclical names.
        _bare_ticker_p0 = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
        _is_bellwether_p0 = (
            _bare_ticker_p0 in TOP_PRIVATE_BANKS
            or _bare_ticker_p0 in NEVER_SUPER_CYCLICAL
        )
        import logging as _p0_logging
        _p0_log = _p0_logging.getLogger("yieldiq.analysis")

        # FIX 1 — Null-CAGR gate v2. When BOTH revenue_cagr_3y and
        # revenue_cagr_5y are None the model has no growth signal at
        # all; force data_limited regardless of where the verdict
        # block above landed. Peer-cap / DCF outputs are retained for
        # the audit trail.
        #
        # 2026-05-24 — STOP ZEROING iv/mos_pct here. Earlier behaviour
        # wrote iv=0 to the cache payload, so any downstream consumer
        # reading payload->valuation->>fair_value (SQL screener, audit
        # tooling, OG-card path) saw FV=0 even though the engine had
        # computed a real number. The summary projection layer already
        # gates FV display on verdict=="data_limited" + base_case
        # fallback (see backend/services/summary_projection.py); the
        # destructive zero-out only hid the canonical computed value
        # from the rest of the system. Keep iv/mos_pct intact; the
        # verdict flag is the truthful signal.
        if (
            not is_financial
            and not _is_bellwether_p0
            and _rev_cagr_3y is None
            and _rev_cagr_5y is None
        ):
            verdict = "data_limited"
            _null_cagr_gate_tripped = True
            _p0_log.info("null_cagr_gate.tripped ticker=%s", ticker)

        # FIX 2 — Cross-pillar moat sanity. Declining 5y revenue (CAGR
        # < 0) overrides any moat to None. ROCE < WACC downgrades the
        # moat one level (Wide -> Moderate -> Narrow -> None). The
        # bellwether allowlist is exempt — explicit ratings stand.
        if not _is_bellwether_p0:
            try:
                _moat_pre = moat_result.get("grade")
                _roce_dec = (
                    (_roce_val / 100.0)
                    if (_roce_val is not None and _roce_val > 1.5)
                    else _roce_val
                )
                if _moat_pre in ("Wide", "Moderate", "Narrow"):
                    if _rev_cagr_5y is not None and _rev_cagr_5y < 0:
                        moat_result["grade"] = "None"
                        moat_result["downgrade_reason"] = (
                            f"5y revenue CAGR {_rev_cagr_5y:.1%} (declining business)"
                        )
                        _p0_log.info(
                            "moat_sanity.downgraded ticker=%s reason=rev_cagr_neg",
                            ticker,
                        )
                    elif (
                        _roce_dec is not None
                        and wacc is not None
                        and _roce_dec < wacc
                    ):
                        if _moat_pre == "Wide":
                            moat_result["grade"] = "Moderate"
                        elif _moat_pre == "Moderate":
                            moat_result["grade"] = "Narrow"
                        elif _moat_pre == "Narrow":
                            moat_result["grade"] = "None"
                        moat_result["downgrade_reason"] = (
                            f"ROCE {_roce_dec * 100:.1f}% < WACC {wacc * 100:.1f}% "
                            f"(no economic moat)"
                        )
                        _p0_log.info(
                            "moat_sanity.downgraded ticker=%s reason=roce_lt_wacc",
                            ticker,
                        )
            except Exception:
                pass

        # FIX 3 — Score-MoS dominance. Per the methodology page, the
        # composite score must track the model rather than the screen.
        # Cap composite based on |MoS| magnitude so a deeply overvalued
        # name cannot ride moat/Piotroski to a misleading score.
        #
        # EXEMPTION (2026-05-03): tickers with an explicit
        # ``model_caveat`` override (conglomerates like ITC/RELIANCE,
        # holdcos, turnarounds) are bypassed. We've already declared the
        # DCF approximate for these names — the cap-vs-screen dominance
        # argument doesn't apply when the model itself is acknowledged
        # as a poor fit. Resolve the override here (it is also resolved
        # again later for the caveat banner; both call sites are cheap
        # dict lookups).
        try:
            _override = _get_ticker_override(ticker)
        except Exception:
            _override = None

        # Auto-detect holding companies / SPVs / pure investment vehicles
        # (structural data-quality fix #4, 2026-05-17). When no explicit
        # override is set but the ticker pattern-matches a holdco (curated
        # set or revenue/industry/market-cap heuristics), synthesise a
        # skip-style override so the existing skip codepath below sets
        # verdict=data_limited, zeroes FV, and surfaces the SOTP caveat.
        # Curated entries in ticker_overrides.py (e.g. BAJAJHLDNG) keep
        # their richer caveat copy — auto-detect only fires when no
        # explicit override is present.
        if not _override:
            try:
                from backend.services.analysis.constants import (
                    is_holding_company as _is_holding_co,
                )
                _holdco_rev = enriched.get("latest_revenue", 0) or 0
                _holdco_shares = enriched.get("shares", 0) or 0
                _holdco_mcap = float(price or 0) * float(_holdco_shares)
                _holdco_sector = (
                    enriched.get("sector_name")
                    or enriched.get("sector")
                    or raw.get("sector_name")
                    or raw.get("sector")
                )
                _holdco_industry = (
                    raw.get("industry") or enriched.get("industry")
                )
                _holdco_nic = (
                    raw.get("nic_code") or enriched.get("nic_code")
                )
                if _is_holding_co(
                    ticker,
                    sector=_holdco_sector,
                    industry=_holdco_industry,
                    revenue_cr=float(_holdco_rev),
                    market_cap_cr=float(_holdco_mcap),
                    nic_code=_holdco_nic,
                ):
                    _override = {
                        "model": "skip",
                        "model_caveat": (
                            "This is a holding company / SPV. Its value "
                            "is driven by stakes in underlying operating "
                            "businesses, not by its own cash flow. "
                            "Standard DCF does not apply — use a "
                            "sum-of-parts (SOTP) analyst report."
                        ),
                        "valuation_method": "holding_company_sotp_required",
                        "auto_detected": True,
                    }
            except Exception as _exc_holdco:
                logger.warning(
                    "holding-co auto-detect failed for %s: %s",
                    ticker, _exc_holdco,
                )

        _skip_dominance_cap = bool(
            _override and _override.get("model_caveat")
        )
        try:
            if (
                mos_pct is not None
                and yiq_score
                and "score" in yiq_score
                and not _skip_dominance_cap
            ):
                _mos_abs = abs(mos_pct)
                if _mos_abs > 50:
                    _composite_max = 40
                elif _mos_abs > 30:
                    _composite_max = 50
                elif _mos_abs > 15:
                    _composite_max = 65
                else:
                    _composite_max = 100
                _orig_score = int(yiq_score.get("score", 0) or 0)
                if _orig_score > _composite_max:
                    yiq_score["score"] = _composite_max
                    # Re-derive grade band from capped score.
                    _cap = _composite_max
                    yiq_score["grade"] = (
                        "A" if _cap >= 75
                        else "B" if _cap >= 55
                        else "C" if _cap >= 35
                        else "D" if _cap >= 20
                        else "F"
                    )
                    _p0_log.info(
                        "score_mos_dominance.capped ticker=%s mos=%.1f orig=%d cap=%d",
                        ticker, mos_pct, _orig_score, _composite_max,
                    )
        except Exception:
            pass

        # ── Phase C.3 (2026-05-25): build score_breakdown ─────────────
        # Surface the same components the canonical scoring function
        # already emits in `yiq_score["components"]` plus any post-
        # compute modifier (currently just the MoS-dominance cap) so
        # the frontend "Why this score?" panel can render an
        # auditable explanation. Field-additive only; existing
        # numeric `yieldiq_score` is unchanged. See
        # docs/diagnostics/phase-c-score-formula-2026-05-25.md.
        _score_breakdown: dict | None = None
        try:
            _comp_raw = (yiq_score or {}).get("components") or {}
            if _comp_raw:
                # Map: canonical-name -> (weight_max, source_tag)
                _comp_meta = {
                    "Business Quality (50pts)": (50, "piotroski+moat"),
                    "Growth (20pts)": (20, "revenue_growth"),
                    "Valuation (20pts)": (20, "mos_pct"),
                    "Sentiment (10pts)": (10, "analyst_upside"),
                }
                _comps: list[dict] = []
                _base_total = 0
                for _cn, _cp in _comp_raw.items():
                    _w, _src = _comp_meta.get(_cn, (0, ""))
                    _pts = int(_cp or 0)
                    _base_total += _pts
                    _comps.append({
                        "name": _cn,
                        "weight_max": _w,
                        "points": _pts,
                        "source": _src,
                    })
                _mods: list[dict] = []
                _final = int(yiq_score.get("score", _base_total))
                # Modifier: MoS-dominance cap (if it fired)
                _orig_for_mod = locals().get("_orig_score")
                if (
                    _orig_for_mod is not None
                    and _final < _orig_for_mod
                ):
                    _mods.append({
                        "name": "MoS-dominance cap",
                        "delta": _final - _orig_for_mod,
                        "reason": (
                            f"|MoS|={abs(mos_pct):.0f}% — composite "
                            f"capped at {_final}."
                        ),
                    })
                _score_breakdown = {
                    "components": _comps,
                    "modifiers": _mods,
                    "base_score": _base_total,
                    "final_score": _final,
                    "note": (
                        "Score is floored, not rounded. See "
                        "docs/diagnostics/phase-c-score-formula-"
                        "2026-05-25.md."
                    ),
                }
        except Exception as _sb_exc:
            import logging as _sb_log
            _sb_log.getLogger("yieldiq.analysis").debug(
                "score_breakdown build failed for %s: %s",
                ticker, _sb_exc,
            )
            _score_breakdown = None

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
        # Reuse the shareholding dict fetched earlier in the red-flag
        # block (perf: dedupe — avoids a 2nd identical DB roundtrip).
        _sh = _sh_data or {}
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

        # ── Promoter-holding override (fix/promoter-extractor) ──
        # The NSE master API reports a single `pr_and_prgrp` figure.
        # Foreign promoters (BAT in ITC, Unilever in HUL, Suzuki in
        # MARUTI) file under "Public" / "FPI" categories on Indian
        # filings, so the API returns ~0% and the UI mislabels the
        # stock as "Low stake". Indian private banks (HDFCBANK,
        # ICICIBANK, AXISBANK) have no designated promoter under RBI
        # norms — the same 0% surfaces as "Low stake" instead of the
        # correct "No promoter (RBI norms)" label.
        # Hand-curated overrides in data_pipeline/data/promoter_overrides.json
        # patch both cases: they overwrite promoter_pct and attach a
        # `promoter_holding_type` / `promoter_entity` pair the frontend
        # uses to render the right label. Override is intentionally
        # applied LAST so it wins over both the NSE feed and the
        # yfinance fallback.
        try:
            from data_pipeline.sources.promoter_overrides import (
                apply_promoter_override,
            )
            apply_promoter_override(ticker, _sh)
        except Exception as _po_exc:
            logger.debug(
                "promoter-override merge failed for %s: %s",
                ticker, _po_exc,
            )

        # Inform downstream consumers that a financial was valued via
        # the peer-band path — helps users interpret the fair value
        # (and disables some FCF-based red flags in the UI).
        if is_financial and locals().get("_financial_val_result"):
            _method = _financial_val_result.get("method", "p_bv_peer")
            _data_issues.append(
                f"[info] Valued via {_method} peer band — DCF not "
                f"meaningful for financials."
            )
        # Regulated-utility analogue: surface the rate-base path so
        # users understand why FV doesn't reconcile with reported FCF.
        if is_regulated_utility_ticker and locals().get("_regulated_val_result"):
            _method = _regulated_val_result.get("method", "rate_base_gordon")
            _data_issues.append(
                f"[info] Valued via {_method} — regulated utility, "
                "FCF-DCF is not meaningful (capex is the rate base)."
            )

        # Defense-PSU analyst-opinion caveat. We did not change the
        # DCF math — this caveat explains *why* the displayed FV may
        # diverge from street consensus by 30-60% on names like BDL /
        # COCHINSHIP / BEML. See docs/design/defense-psu-dcf-fix.md.
        if is_defense_psu_ticker:
            _data_issues.append(
                "Defense PSUs trade on order-book visibility "
                "(Make-in-India). Trailing-financials DCF may "
                "understate forward earnings. Consider street "
                "consensus alongside our model FV."
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
                "valuation_model": (
                    "etf_nav_based" if is_etf_ticker
                    else (
                        "reit_nav_dpu_required" if is_reit_ticker
                        else (
                            "rate_base" if is_regulated_utility_ticker
                            else ("pb_ratio" if is_financial else "dcf")
                        )
                    )
                ),
                "is_financial": bool(is_financial),
                "is_regulated_utility": bool(is_regulated_utility_ticker),
                "is_reit": bool(is_reit_ticker),
                "cache_version": CACHE_VERSION,
            }
            # ── Day-110c: REIT/InvIT cohort sub-segment + implied
            # fair price (distribution-yield anchored). Surfaced in
            # _computation_inputs so canary_diff + admin pages can
            # see the new anchor without changing the user-facing
            # valuation_model (which stays "reit_nav_dpu_required").
            try:
                from backend.services.analysis.sector_overrides import (
                    is_reit_invit_cohort_ticker,
                    reit_invit_subsegment,
                    reit_invit_fair_yield,
                    compute_distribution_yield_fair_value,
                )
                if is_reit_invit_cohort_ticker(ticker):
                    _seg = reit_invit_subsegment(ticker)
                    _yld = reit_invit_fair_yield(ticker)
                    # Best-effort: try to derive annual distribution per
                    # unit from dividend_yield * price as proxy. If the
                    # enriched payload exposes a more precise
                    # ``annual_distribution_per_unit``, prefer that.
                    _dist = (
                        enriched.get("annual_distribution_per_unit")
                        if isinstance(enriched, dict) else None
                    )
                    if _dist is None:
                        _dy = (
                            (enriched.get("dividend_yield")
                             if isinstance(enriched, dict) else None)
                            or raw.get("dividendYield")
                        )
                        try:
                            if _dy is not None and price > 0:
                                _dyf = float(_dy)
                                # yfinance returns this as decimal or
                                # percent depending on field; >1 → %.
                                if _dyf > 1.0:
                                    _dyf = _dyf / 100.0
                                _dist = _dyf * float(price)
                        except (TypeError, ValueError):
                            _dist = None
                    _cohort_meta = {
                        "subsegment": _seg,
                        "fair_yield_anchor": (
                            float(_yld[0]) if _yld else None
                        ),
                        "fair_yield_band": (
                            [float(_yld[1][0]), float(_yld[1][1])]
                            if _yld else None
                        ),
                        "is_invit": bool(is_invit_ticker),
                    }
                    _dy_fv = compute_distribution_yield_fair_value(
                        ticker, _dist, distribution_cagr_3y=None,
                    )
                    if _dy_fv is not None:
                        _cohort_meta["implied_fair_price"] = (
                            _dy_fv["implied_fair_price"]
                        )
                        _cohort_meta["implied_fair_price_boosted"] = (
                            _dy_fv["implied_fair_price_boosted"]
                        )
                        _cohort_meta["annual_distribution_per_unit"] = (
                            _dy_fv["annual_distribution_per_unit"]
                        )
                    else:
                        _cohort_meta["data_status"] = (
                            "distribution_data_unavailable_phase2"
                        )
                    _computation_inputs["reit_invit_cohort"] = _cohort_meta
            except Exception:
                # Never fail the response on cohort metadata; the
                # short-circuit branch above already produced a safe
                # reit_nav_dpu_required verdict.
                pass

            # ── A3 sector-engine wiring (2026-06-13) ──────────────────
            # Populate the sector-specific input sub-blocks the
            # per-engine FV helpers in backend/routers/analysis.py read
            # (`bank_deepened` / `insurance` / `nbfc`). Until now the
            # cold-compute path NEVER wrote these, so the snapshot stored
            # in analysis_cache.payload carried no sector inputs and the
            # router-boundary resolver (`_resolve_sector_primary_fv`)
            # could only fire for banks (which self-merge from the DB)
            # — insurers and NBFCs always abstained to None even when
            # their ingested data (insurance_appraisal_inputs migration
            # 046, the bank KPI table) was present.
            #
            # Mirrors the REIT/InvIT cohort precedent directly above:
            # every block is wrapped in its own try/except → leaves the
            # key ABSENT on any failure or missing data. Strict superset
            # — a generic (non-bank / non-insurer / non-NBFC) stock's
            # _computation_inputs is byte-for-byte unchanged because each
            # block's applicability gate rejects it before any key is set.
            #
            # bank_deepened: reuse the warm-path merge helper so the
            # snapshot block matches exactly what the engine consumes —
            # NIM / CASA / PCR / GNPA / cost-income (decimals) from the
            # payload quality fields computed above (_bm_nim etc., as
            # 0-100 percents) plus the bank_operational_kpis DB row, and
            # book-value-per-share / ROE / payout. The engine gate still
            # requires NIM, so a lender with no NIM data leaves the block
            # absent (honest abstain) rather than emitting a P/B-only
            # decomposition with no incremental signal.
            try:
                if bool(locals().get("_is_bank_like")):
                    from backend.routers.analysis import (
                        _merge_bank_deepened_inputs as _a3_merge_bank,
                    )
                    _a3_quality = {
                        "is_bank": True,
                        "nim": locals().get("_bm_nim"),
                        "casa": locals().get("_bm_casa"),
                        "cost_to_income": locals().get("_bm_cost_to_income"),
                        "roe": enriched.get("roe"),
                        "book_value_per_share": enriched.get(
                            "book_value_per_share"
                        ),
                        "payout_ratio": enriched.get("payout_ratio"),
                        "shares_outstanding": enriched.get("shares"),
                    }
                    _a3_valuation = {
                        "current_price": float(price or 0) or None,
                        "discount_rate": float(wacc or 0) or None,
                        "wacc": float(wacc or 0) or None,
                        "terminal_growth": float(terminal_g or 0) or None,
                    }
                    _a3_bank_block = _a3_merge_bank(
                        ticker,
                        {},          # no pre-existing snapshot block
                        _a3_quality,
                        _a3_valuation,
                        {},          # insights not yet built at this point
                    )
                    # Only persist when NIM resolved — that is the engine
                    # gate. Without it the block adds nothing over P/B and
                    # the router resolver would abstain anyway.
                    if _a3_bank_block and _a3_bank_block.get("nim_pct"):
                        _computation_inputs["bank_deepened"] = _a3_bank_block
            except Exception:
                # Never fail the response on sector wiring. The bank
                # route degrades to the headline P/B FV exactly as before.
                pass

            # insurance: EV + (VNB × multiple). Source the latest row
            # from insurance_appraisal_inputs (migration 046). The table
            # stores EV / VNB in INR Crores. The engine that consumes
            # this block (`_compute_insurance_fv` → compute_ev_vnb_
            # appraisal via EVVNBInputs) takes EV / VNB in ₹ CRORES and
            # shares_outstanding in CRORE-count, and produces ₹/share
            # directly (verified by test_insurance_ev_vnb: 157,000 Cr /
            # 215 Cr-sh = ₹730/sh). So NO ×1e7 conversion — we pass the
            # Crore figures straight through, with `enriched["shares"]`
            # (Crore-count, Indian convention) as the share base. (Note:
            # this is a DIFFERENT path from get_appraisal_fair_value_for_
            # ticker, which converts to absolute INR for a separate
            # FairValueResult producer — do not conflate the two.)
            # Multiple is the calibrated select_vnb_multiple; the engine
            # clamps / defaults defensively if it is absent.
            try:
                from backend.services.insurance_appraisal_service import (
                    is_ev_vnb_applicable as _a3_ins_applicable,
                    load_latest_appraisal_inputs as _a3_load_ins,
                    select_vnb_multiple as _a3_vnb_mult,
                )
                _a3_ins_sector = (
                    enriched.get("sector")
                    or (raw.get("sector") if isinstance(raw, dict) else None)
                )
                if _a3_ins_applicable(ticker, _a3_ins_sector):
                    _a3_ins_row = _a3_load_ins(ticker)
                    _a3_ev_cr = (
                        _a3_ins_row.get("embedded_value_cr")
                        if isinstance(_a3_ins_row, dict) else None
                    )
                    if _a3_ev_cr and float(_a3_ev_cr) > 0:
                        _a3_vnb_cr = (
                            _a3_ins_row.get("value_new_business_cr") or 0.0
                        )
                        _a3_shares = float(enriched.get("shares") or 0) or None
                        _a3_mult = None
                        try:
                            _a3_mult = _a3_vnb_mult(ticker)
                        except Exception:
                            _a3_mult = None
                        _a3_ins_block = {
                            # ₹ Crores straight through — engine works in
                            # Crore EV / Crore-shares → ₹/share.
                            "embedded_value": float(_a3_ev_cr),
                            "new_business_value": float(_a3_vnb_cr),
                            "shares_outstanding": _a3_shares,
                        }
                        if _a3_mult and float(_a3_mult) > 0:
                            _a3_ins_block["vnb_multiple"] = float(_a3_mult)
                        _computation_inputs["insurance"] = {
                            k: v for k, v in _a3_ins_block.items()
                            if v is not None
                        }
            except Exception:
                pass

            # nbfc: ABSTAIN (TODO). The NBFC ROA engine
            # (_compute_nbfc_fv) gates on `average_assets_inr_cr` in INR
            # Crores. The only balance-sheet figures in scope here
            # (enriched.total_assets / total_equity) are in MIXED units —
            # raw INR from yfinance vs Crores from the DB rollup — and
            # selecting/normalizing the wrong one would silently fabricate
            # a wrong fair value (worse than abstaining). The engine's
            # other inputs (yield-on-assets / cost-of-funds / credit-cost)
            # come from nbfc_roa_service segment defaults, but avg-assets
            # is the binding gate and we cannot source it unit-safely yet.
            # TODO(A3-nbfc): once a unit-normalized average_assets_inr_cr /
            # average_equity_inr_cr is available on `enriched` (Crores,
            # 2y-average), populate computation_inputs["nbfc"] here mirror-
            # ing the insurance block. Leaving the key ABSENT keeps the
            # router resolver honestly at None for NBFC tickers.
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

        # ── Finnhub analyst consensus (2026-04-29, feat/analyst) ─
        # Additive third-party block: full rating distribution +
        # price-target high/low/median + EPS consensus. Wraps in
        # try/except so a Finnhub outage NEVER fails the analysis
        # response — the worst case is coverage_count=0, which the
        # frontend already handles. NOT cached in CACHE_VERSION;
        # the underlying fetcher uses endpoint_cache (24h TTL) keyed
        # by ticker so the live current price can still flow into
        # vs_current_pct on every request.
        _analyst_consensus: Optional[AnalystConsensus] = None
        try:
            from backend.services.finnhub_analyst_service import (
                fetch_analyst_consensus as _fetch_consensus,
            )
            _consensus = _fetch_consensus(
                ticker, current_price=price
            )
            if _consensus is not None:
                _rd = _consensus.get("rating_distribution")
                _pt_a = _consensus.get("price_target")
                _eps_a = _consensus.get("eps_estimate")
                _analyst_consensus = AnalystConsensus(
                    coverage_count=int(
                        _consensus.get("coverage_count", 0) or 0
                    ),
                    rating_distribution=(
                        AnalystRatingDistribution(**_rd) if _rd else None
                    ),
                    consensus_rating=_consensus.get("consensus_rating"),
                    price_target=(
                        AnalystPriceTarget(**_pt_a) if _pt_a else None
                    ),
                    eps_estimate=(
                        AnalystEpsEstimate(**_eps_a) if _eps_a else None
                    ),
                    as_of=_consensus.get("as_of"),
                    source=_consensus.get("source", "Finnhub"),
                )
        except Exception as _exc:  # noqa: BLE001
            import logging as _logging
            _logging.getLogger("yieldiq.analysis").warning(
                "analyst_consensus fetch failed for %s: %s", ticker, _exc
            )
            _analyst_consensus = None

        # P0 MoS standardization (2026-05-02): clamp the displayed MoS
        # to [-100, +200]. Raw mos_pct stays in `margin_of_safety` for
        # canary-diff / alerts; display fields use the clamped value.
        _mos_display, _mos_was_clamped = display_mos(mos_pct)
        if _mos_display is None:
            _mos_display = 0.0

        # ── Per-ticker overrides for unusual businesses ──────────
        # Conglomerates (RELIANCE, ITC), holding cos (BAJAJHLDNG,
        # TATAINVEST), turnarounds (VEDL), and pre-profit names
        # (ETERNAL, PAYTM, POLICYBZR, NYKAA, OLAELEC) surface honest
        # "model approximate" caveats. The BAJAJHLDNG class skips DCF
        # entirely (pure holdco — DCF on holdco itself is meaningless).
        # ROADMAP: build SOTP engine for the conglomerates. Caveat
        # banner is the bridge. See ticker_overrides.py.
        # ── Recent-IPO verdict cap (feat/recent-ipo-sector-relative) ─
        # When the IPO override fired, cap the verdict at `data_limited`
        # unless the sector-relative deviation produced a clear signal
        # (>30% above/below cohort-implied FV). Surface a caveat note
        # so the frontend renders the "Recent IPO" badge + tooltip.
        if _is_recent_ipo:
            _hint = (
                _ipo_sector_rel.get("verdict_hint") if _ipo_sector_rel else None
            )
            if _hint in ("undervalued", "overvalued"):
                verdict = _hint
            else:
                verdict = "data_limited"
            _fair_value_source = "sector_relative_recent_ipo"
            try:
                _ipo_msg = _ipo_caveat(ticker, _ipo_listing_date or "")
                _data_issues = list(_data_issues) + [
                    f"[recent_ipo] {_ipo_msg}"
                ]
            except Exception:
                pass

        # ── ETF final-state pin ──────────────────────────────────
        # ETF short-circuit was set up at the top of Step 6. Force the
        # final verdict / iv / MoS into the data_limited shape here so
        # any intermediate adjustments (moat delta, scenario MoS, etc.)
        # do not re-introduce a non-zero FV. The frontend gates
        # FV/MoS/score-derived UI on verdict=="data_limited".
        if is_etf_ticker:
            verdict = "data_limited"
            iv = 0.0
            mos_pct = 0.0
            try:
                _mos_display = 0.0
            except Exception:
                pass

        # ── REIT final-state pin (PR #333) ───────────────────────
        # Same shape as the ETF pin above. REIT short-circuit was set
        # up at the top of Step 6; force the final verdict / iv / MoS
        # into the data_limited shape so any intermediate adjustments
        # do not re-introduce a non-zero FV. The frontend gates
        # FV/MoS/score-derived UI on verdict=="data_limited".
        if is_reit_ticker:
            verdict = "data_limited"
            iv = 0.0
            mos_pct = 0.0
            try:
                _mos_display = 0.0
            except Exception:
                pass

        # NOTE: _override was resolved earlier (before the Score-MoS
        # dominance cap) so the cap can be exempted for caveated names.
        # Reuse that result here.
        # Track whether the override marks this as a holding-co skip so
        # we can surface the SOTP-required valuation_method on the wire.
        _holdco_skip = False
        if _override:
            _caveat_msg = _override.get("model_caveat")
            if _override.get("model") == "skip":
                # Don't emit FV — model isn't appropriate for this business.
                # Use the existing `data_limited` verdict (the frontend
                # already suppresses FV/MoS/score-derived UI for it; see
                # AnalysisBody.tsx verdictDataLimited gate). The caveat
                # banner explains *why* the model is skipped.
                verdict = "data_limited"
                iv = 0.0
                mos_pct = 0.0
                _mos_display = 0.0
                if _override.get("valuation_method") == "holding_company_sotp_required":
                    _holdco_skip = True
                if _caveat_msg:
                    _data_issues = list(_data_issues) + [
                        f"[model_caveat] {_caveat_msg}"
                    ]
            elif _caveat_msg:
                # Compute FV but tag with caveat + lower confidence ceiling
                _data_issues = list(_data_issues) + [
                    f"[model_caveat] {_caveat_msg}"
                ]
                try:
                    _conf_now = int(confidence.get("score", 50))
                    confidence["score"] = min(_conf_now, 50)
                except Exception:
                    pass

        # ── Benchmark reconciliation caveat (Layer A safety net) ──
        # Appends a generic data_issue if our FV diverges materially
        # from analyst consensus for this ticker. Never reveals the
        # consensus number itself. Failure modes degrade silently —
        # this must never break the analysis path.
        try:
            from backend.services import benchmark_reconciliation_service as _brs
            _binfo = _brs.is_ticker_flagged(ticker)
            _bcaveat = _brs.caveat_text(_binfo)
            if _bcaveat:
                _data_issues = list(_data_issues) + [f"[benchmark_caveat] {_bcaveat}"]
        except Exception:
            # Reconciliation is best-effort; never break analysis on it.
            pass

        # ── Layer C — Confidence Framework scores (PR 1) ─────
        # Purely additive: compute the three 0-100 scores after
        # valuation_method has been finalised, log them, and pass
        # them to ValuationOutput below. PR 2 will read them back
        # out for the verdict-intensity gate; PR 1 changes no
        # behavior.
        try:
            from backend.services.confidence_service import compute_all_scores as _cf_all
            _cf_method = (
                "etf_nav_based" if is_etf_ticker
                else ("reit_nav_dpu_required" if is_reit_ticker
                else ("holding_company_sotp_required" if _holdco_skip
                else ("rate_base" if is_regulated_utility_ticker
                else ("pb_ratio" if is_financial
                else ("sector_relative_recent_ipo"
                      if _fair_value_source == "sector_relative_recent_ipo"
                      else ("peer_capped"
                            if _fair_value_source == "peer_capped"
                            else "dcf"))))))
            )
            _cf_sector = (
                enriched.get("sector")
                or (raw.get("sector") if isinstance(raw, dict) else None)
            )
            _cf_flags = {
                "analyst_opinion_required": bool(is_defense_psu_ticker),
                "data_limited": bool(verdict == "data_limited"),
                "dcf_unreliable": not bool(enriched.get("dcf_reliable", True)),
            }
            # FV history: best-effort. None on the hot path is fine —
            # compute_valuation_stability_score returns a neutral 70.
            _cf_fv_hist = None
            try:
                from backend.services.fv_accuracy_service import (
                    get_recent_fv_history as _cf_fvh,
                )
                _cf_fv_hist = _cf_fvh(ticker, limit=4)  # type: ignore[misc]
            except Exception:
                _cf_fv_hist = None
            # T2.7 (2026-06-09): assemble base_inputs/base_verdict for
            # the 4th sensitivity pillar. Best-effort — if any DCF
            # variable isn't in scope (financial / regulated / ETF /
            # holdco paths), the sensitivity function returns None and
            # the response stays valid. tax_rate is not maintained as
            # a local in this scope; default to 0.25 (standard Indian
            # corporate rate) so the perturbation still bites.
            _cf_base_inputs = None
            _cf_base_verdict = None
            try:
                _cf_base_inputs = {
                    "wacc": float(wacc),
                    "fcf_growth": float(enriched.get("fcf_growth", 0.0) or 0.0),
                    "terminal_growth": float(terminal_g),
                    "tax_rate": 0.25,
                    "current_fv": float(iv or 0.0),
                    "current_price": float(price or 0.0),
                }
                _cf_base_verdict = verdict if isinstance(verdict, str) else None
            except Exception:
                _cf_base_inputs = None
                _cf_base_verdict = None

            # T1.6 (2026-06-10): 5th composite-agreement pillar reads
            # the composite_components dict from composite_iv_service.
            # The composite itself is injected onto the response at the
            # router boundary (_inject_composite_iv_model), which runs
            # AFTER this service.py compute returns — so the composite
            # isn't in scope here. We rebuild it locally from the same
            # inputs (cheap pure-Python derivation, no I/O) so the 5th
            # pillar is populated on the cold path. Best-effort — when
            # the composite path can't fire (missing DCF FV, single-
            # estimator branch, etc.) the score returns None and the
            # response stays valid.
            _cf_composite_components = None
            try:
                from backend.services.composite_iv_service import (
                    compute_composite_iv as _cf_compute_composite,
                    composite_to_dict as _cf_comp_to_dict,
                )
                _cf_stock_kind = None
                if bool(locals().get("_holdco_skip", False)):
                    _cf_stock_kind = "holdco"
                elif bool(is_financial):
                    _cf_stock_kind = "bank"
                _cf_analyst_avg = None
                _cf_consensus = (
                    enriched.get("analyst_consensus")
                    if isinstance(enriched, dict) else None
                )
                if isinstance(_cf_consensus, dict):
                    _cf_pt = _cf_consensus.get("price_target") or {}
                    _cf_analyst_avg = _cf_pt.get("mean") or _cf_pt.get("median")
                if _cf_analyst_avg is None and isinstance(enriched, dict):
                    _cf_analyst_avg = enriched.get("wall_street_avg_target")
                _cf_multiples_fv = (
                    enriched.get("multiples_based_fv")
                    if isinstance(enriched, dict) else None
                )
                # FIX 2026-06-12 (composite-spine): pass routing args by
                # KEYWORD. Previously these were positional, so _cf_stock_kind
                # / _cf_sector / ticker landed in the three_stage_fv / ddm_fv
                # / epv_fv float slots (PR #813 Phase-C extended the signature
                # but never updated this call site). The string values failed
                # _coerce_pos_float -> None, silently zeroing the Phase-C
                # estimator inputs AND leaving stock_kind/sector/ticker unset
                # so bank/holdco routing never fired. See
                # docs/ENGINE_ROOT_CAUSE_2026-06-12.md.
                _cf_composite_obj = _cf_compute_composite(
                    iv,
                    _cf_multiples_fv,
                    _cf_analyst_avg,
                    stock_kind=_cf_stock_kind,
                    sector=_cf_sector,
                    ticker=ticker,
                )
                if _cf_composite_obj is not None:
                    _cf_composite_components = _cf_comp_to_dict(_cf_composite_obj)
            except Exception:
                _cf_composite_components = None

            # ── Composite as headline source of truth ─────────────────
            # (composite-spine 2026-06-12 — see docs/ENGINE_ROOT_CAUSE_2026-06-12.md)
            #
            # Until now the multi-estimator composite was a read-time display
            # garnish: verdict, MoS, and fair_value_history all ran on the
            # raw single-stage DCF (`iv`), which systematically OVERSHOT
            # high-growth names and UNDERSHOT quality/consumer names (the
            # signed, sector-clustered bias the 10-stock backtest surfaced).
            # The corrective estimators (analyst consensus, multiples) existed
            # in-DB, fresh, and were discarded.
            #
            # We now repoint the HEADLINE fair value + MoS + verdict to the
            # composite when it is available and positive. The DCF stays the
            # scenario-triangle base (bear/base/bull remain DCF) and is
            # preserved on `composite_components.components.dcf` for the
            # transparency panel. data_limited / avoid / unavailable verdicts
            # are PASSTHROUGH — the re-band only touches the standard
            # under / fair / over decision so the existing data-quality and
            # DCF-collapse gates above keep their authority.
            #
            # Placed BEFORE the confidence verdict gate (Layer C) so the gate
            # operates on the composite-based verdict and can still apply its
            # confidence-driven downgrade on top.
            _headline_fv = iv
            _headline_source = "dcf"
            _dcf_fv_audit = iv  # preserve raw DCF for the breakdown / logs
            _PASSTHROUGH_VERDICTS = {"data_limited", "avoid", "unavailable"}
            try:
                _spine_obj = locals().get("_cf_composite_obj")
                _spine_val = (
                    float(_spine_obj.value)
                    if (_spine_obj is not None and _spine_obj.value)
                    else None
                )
            except Exception:
                _spine_val = None
            if (
                _spine_val is not None
                and _spine_val > 0
                and price and price > 0
                and verdict not in _PASSTHROUGH_VERDICTS
            ):
                _headline_fv = _spine_val
                _headline_source = "composite"
                mos_pct = (_spine_val - price) / price * 100.0
                try:
                    _mos_display, _mos_was_clamped = display_mos(mos_pct)
                except Exception:
                    pass
                # Re-band verdict from composite MoS using the SAME ±15
                # bands as the DCF verdict tree above (financial +
                # non-financial share the band edges; the non-financial
                # branch can resolve to "avoid" only when dcf is unreliable —
                # we keep "overvalued" here since a positive composite is by
                # construction a usable estimate).
                if mos_pct > 15:
                    verdict = "undervalued"
                elif mos_pct > -15:
                    verdict = "fairly_valued"
                else:
                    verdict = "overvalued"

            _cf_scores = _cf_all(
                ticker,
                enriched=enriched,
                raw=raw if isinstance(raw, dict) else None,
                valuation_method=_cf_method,
                sector=_cf_sector,
                is_recent_ipo=bool(locals().get("_is_recent_ipo", False)),
                fv_history=_cf_fv_hist,
                extra_flags=_cf_flags,
                base_inputs=_cf_base_inputs,
                base_verdict=_cf_base_verdict,
                composite_components=_cf_composite_components,
            )
            import logging as _cf_log
            _cf_log.getLogger("yieldiq.confidence").info(
                "[%s] confidence_scores dq=%d mc=%d vs=%d sens=%s agree=%s (method=%s sector=%s)",
                ticker,
                _cf_scores["data_quality"],
                _cf_scores["model_confidence"],
                _cf_scores["valuation_stability"],
                _cf_scores.get("sensitivity"),
                _cf_scores.get("composite_agreement"),
                _cf_method, _cf_sector,
            )
        except Exception as _cf_exc:  # pragma: no cover — defensive
            import logging as _cf_log
            _cf_log.getLogger("yieldiq.confidence").warning(
                "[%s] confidence-scores compute failed: %s: %s",
                ticker, type(_cf_exc).__name__, _cf_exc,
            )
            _cf_scores = {
                "data_quality": None,
                "model_confidence": None,
                "valuation_stability": None,
                "sensitivity": None,
                "composite_agreement": None,
            }
            _cf_method = locals().get("_cf_method") or "dcf"

        # ── Layer C — Confidence verdict gate (PR #376 wiring) ───
        # Apply extreme FV/price-ratio override + intensity cap based
        # on the three Layer-C scores computed above. Carve-outs for
        # rate-base / appraisal / NAV / SOTP engines are handled by
        # the gate itself (`_RATIO_OVERRIDE_CARVEOUTS`). Defensive:
        # any failure here must NOT break analysis — log and proceed
        # with the original verdict.
        try:
            from backend.services.confidence_service import (
                _apply_confidence_verdict_gate as _vg_apply,
            )
            _vg_before = verdict
            # Phase C.2 (2026-06-10): verdict gate now consumes
            # composite_intrinsic_value when available, falling back
            # to the DCF-only `iv` when composite is missing/zero.
            # The DCF fair_value field on the response (valuation.fair_value)
            # is UNCHANGED — only the gate's FV input swaps. See
            # cache_invalidation_manifest entry
            # `v_phase_c_2_verdict_gate_composite_consumption_2026_06_10`
            # and bridge contract test
            # `test_verdict_gate_composite_consumption.py` for the
            # pre-pinned behavior.
            #
            # Edge cases (covered by the bridge contract):
            #   * composite=0      -> fall back to iv (truthiness check)
            #   * composite=None   -> fall back to iv (None check)
            #   * composite=None AND iv=None/0 -> gate sees None and
            #     returns the upstream verdict ("unavailable") unchanged
            #     because "unavailable" is a passthrough verdict.
            _vg_fair_value = iv
            try:
                _vg_composite_value = (
                    _cf_composite_obj.value
                    if (
                        "_cf_composite_obj" in locals()
                        and _cf_composite_obj is not None
                    )
                    else None
                )
            except Exception:
                _vg_composite_value = None
            if _vg_composite_value is not None and _vg_composite_value:
                _vg_fair_value = float(_vg_composite_value)
            _vg_new_verdict, _vg_new_issues = _vg_apply(
                verdict,
                _cf_scores.get("data_quality"),
                _cf_scores.get("model_confidence"),
                _cf_scores.get("valuation_stability"),
                _data_issues,
                fair_value=_vg_fair_value,
                current_price=price,
                valuation_model=_cf_method,
            )
            if _vg_new_verdict != _vg_before:
                import logging as _vg_log
                _vg_log.getLogger("yieldiq.confidence").info(
                    "[%s] verdict gate: %s -> %s (mc=%s dq=%s vs=%s method=%s gate_fv=%.4f dcf_fv=%.4f px=%.4f composite=%s)",
                    ticker, _vg_before, _vg_new_verdict,
                    _cf_scores.get("model_confidence"),
                    _cf_scores.get("data_quality"),
                    _cf_scores.get("valuation_stability"),
                    _cf_method,
                    float(_vg_fair_value or 0.0),
                    float(iv or 0.0),
                    float(price or 0.0),
                    "yes" if _vg_fair_value != iv else "no",
                )
            verdict = _vg_new_verdict
            _data_issues = _vg_new_issues
        except Exception as _vg_exc:  # pragma: no cover — defensive
            import logging as _vg_log
            _vg_log.getLogger("yieldiq.confidence").warning(
                "[%s] verdict gate failed: %s: %s",
                ticker, type(_vg_exc).__name__, _vg_exc,
            )

        # ── DEFERRED FV-HISTORY WRITE (composite-spine 2026-06-12) ─────────
        # Relocated from ~line 4192 so the historical record stores the
        # FINAL composite-based headline (after the composite re-band AND the
        # Layer-C confidence verdict gate), not the raw single-stage DCF.
        # This is what makes the public /calibration page, the FV-vs-price
        # chart, and the backtest measure the engine users actually see.
        # Async daemon thread — DB round-trips never block the response.
        try:
            from data_pipeline.sources.fv_history import NON_CHARTABLE_VERDICTS
            _verdict_str = str(verdict) if verdict is not None else ""
            _is_chartable = (
                _headline_fv and _headline_fv > 0
                and price and price > 0
                and _verdict_str not in NON_CHARTABLE_VERDICTS
            )
            if _is_chartable:
                import threading as _fv_threading
                # ROOT CAUSE #13 (2026-06-11): persist score + grade so
                # peers_service can populate the peer SCORE column from the
                # DB fallback when the in-process cache is cold.
                _yiq_score_val: int | None = None
                try:
                    _raw_score = yiq_score.get("score", None)
                    if _raw_score is not None:
                        _yiq_score_val = int(_raw_score)
                except (TypeError, ValueError, AttributeError):
                    _yiq_score_val = None
                _yiq_grade_val: str | None = None
                try:
                    _raw_grade = yiq_score.get("grade", None)
                    if _raw_grade is not None:
                        _yiq_grade_val = str(_raw_grade)[:4]
                except (TypeError, AttributeError):
                    _yiq_grade_val = None
                _fv_args = dict(
                    ticker=ticker,
                    fv=float(_headline_fv),  # composite headline (else DCF)
                    price=float(price),
                    mos=float(mos_pct),      # composite-derived MoS
                    verdict=_verdict_str,    # composite-rebanded + gated
                    wacc=float(wacc),
                    confidence=int(confidence.get("score", 50)),
                    yieldiq_score=_yiq_score_val,
                    grade=_yiq_grade_val,
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
        # ──────────────────────────────────────────────────────────────────

        # Day-24: record Step 10 and finalise timings just before the
        # response is built. total_inner_ms is wall-clock for the entire
        # _get_full_analysis_inner call (excludes outer get_full_analysis
        # validators + AI narrative + translations layers).
        try:
            _record_step("step10_verdict")
            _timings_steps["total_inner_ms"] = int(
                (_time_t.perf_counter() - _t_inner_start) * 1000
            )
        except Exception:
            pass

        return AnalysisResponse(
            ticker=ticker,
            company=company,
            timings_ms=_timings_steps if _timings_steps else None,
            # Task #197: top-level mirror of valuation.as_of so frontend
            # surfaces that don't unwrap `valuation` (AnalysisHero) can
            # read freshness directly.
            as_of=_live_quote_as_of,
            valuation=ValuationOutput(
                # composite-spine 2026-06-12: headline FV is the composite
                # when available (else raw DCF). DCF preserved on
                # composite_components.dcf + _dcf_fv_audit.
                fair_value=round(_headline_fv, 2),
                current_price=round(price, 2),
                margin_of_safety=round(mos_pct, 1),
                # Step B: true Buffett MoS = (FV - CP) / FV * 100.
                # Additive alongside the legacy upside-% field above.
                buffett_mos_pct=(
                    round(_b, 1) if (_b := buffett_mos_pct(_headline_fv, price)) is not None else None
                ),
                margin_of_safety_display=round(min(_mos_display, 80), 1),
                mos_is_extreme=mos_pct > 80,
                mos_clamped=_mos_was_clamped,
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
                    # Defense-PSU 0.7× downgrade per
                    # docs/design/defense-psu-dcf-fix.md — applied on
                    # top of whichever upstream confidence the pipeline
                    # would have returned. int() floor matches the
                    # field's declared type (ValuationOutput.confidence_score).
                    int(round((
                        _regulated_val_result["confidence_score"]
                        if is_regulated_utility_ticker
                        and locals().get("_regulated_val_result")
                        else (
                            _financial_val_result["confidence_score"]
                            if is_financial and locals().get("_financial_val_result")
                            else confidence.get("score", 50)
                        )
                    ) * (0.7 if is_defense_psu_ticker else 1.0)))
                ),
                wacc_industry_min=round(max(0.06, wacc - 0.02), 4),
                wacc_industry_max=round(min(0.16, wacc + 0.02), 4),
                fcf_growth_historical_avg=round(enriched.get("fcf_growth", 0) * 0.9, 4),
                tv_pct_of_ev=round(dcf_res.get("tv_pct_of_ev", 0) * 100, 1),
                dcf_reliable=(
                    False
                    if (is_financial or is_regulated_utility_ticker)
                    else enriched.get("dcf_reliable", True)
                ),
                # HOTFIX 2026-05-18: include realty + insurance branches.
                # Previously the chain fell through to "dcf" for both
                # realty (PR #356) and insurance appraisal (PR #357)
                # tickers, so even when the engines fired the response
                # mislabeled the method. UI confidence chips + reconciliation
                # gate read this field; mislabel hid that the new engines
                # were actually running.
                valuation_model=(
                    "etf_nav_based" if is_etf_ticker
                    else (
                        "reit_nav_dpu_required" if is_reit_ticker
                        else (
                            "holding_company_sotp_required" if _holdco_skip
                            else (
                                "rate_base" if is_regulated_utility_ticker
                                else (
                                    "pb_plus_land_bank" if is_realty_branch_active
                                    else (
                                        "appraisal_value"
                                        if (
                                            clean_ticker.upper()
                                            in _INSURANCE_TICKERS
                                            and _appraisal_val_result
                                        )
                                        else (
                                            "pb_ratio" if is_financial else "dcf"
                                        )
                                    )
                                )
                            )
                        )
                    )
                ),
                reliability_score=dcf_res.get("reliability_score", 100),
                pv_fcfs=round(dcf_res.get("sum_pv_fcfs", 0), 0),
                pv_terminal=round(dcf_res.get("pv_tv", 0), 0),
                enterprise_value=round(dcf_res.get("enterprise_value", 0), 0),
                equity_value=round(dcf_res.get("equity_value", 0), 0),
                fcf_data_source=_fcf_data_source,
                ttm_source=_ttm_source,
                quarterly_last_filed_at=_quarterly_last_filed_at,
                # feat/freshness-stamps: compute timestamp marks when
                # the price was pulled from upstream (yfinance/NSE
                # Parquet). Both are delayed — frontend renders as
                # "Delayed", never "Live". See FreshnessStamp.tsx.
                current_price_as_of=_ts,
                # Task #197 (feat/as-of-plumbing): mirrors live_quotes.as_of
                # for the row that supplied current_price (None when the
                # cascade fell through to daily_prices / yfinance). The
                # frontend FreshnessStamp uses this to pick the right
                # color tier — recent (<30m) = green, 30m-4h = yellow,
                # >4h = red. Falls back to current_price_as_of when null.
                as_of=_live_quote_as_of,
                # feat/transparency (2026-05-02): per-number provenance.
                # Additive only — does NOT influence FV/MoS/scoring math.
                # Surfaced in hero tooltips + freshness widget.
                current_price_source=_data_source,
                fair_value_computed_at=_ts,
                valuation_engine_used=(
                    "relative_post_demerger"
                    if locals().get("_post_demerger_route")
                    else "sector_relative_recent_ipo"
                    if _fair_value_source == "sector_relative_recent_ipo"
                    else (
                        "peer_capped"
                        if _fair_value_source == "peer_capped"
                        else (
                            # feat/dcf-collapse-safety-net: pass the
                            # rung-specific engine string through so the
                            # frontend StoryDcfBadge / Platform-PS badge
                            # fires and analytics know WHICH rung
                            # rescued the FV. Day-10 fix — was
                            # collapsed to "tier2_fallback".
                            _fair_value_source
                            if _fair_value_source in (
                                "tier2_fallback",
                                "tier2_fallback_after_dcf_collapse",
                                "platform_ps_after_dcf_collapse",
                                "story_dcf_after_dcf_collapse",
                            )
                            else ("pb_residual_income" if is_financial else "dcf")
                        )
                    )
                ),
                # feat/peer-cap (2026-04-27): peer-multiple sanity
                # ceiling. fair_value_source flips to "peer_capped"
                # when the cap fires; details carry the audit trail.
                # IPO override surfaces via `valuation_engine_used`;
                # `fair_value_source` stays inside its Literal contract.
                fair_value_source=(
                    "dcf"
                    if _fair_value_source == "sector_relative_recent_ipo"
                    else _fair_value_source
                ),
                peer_cap_details=_peer_cap_details,
                # Defense-PSU NO-FIX flag — see Approach D in
                # docs/design/defense-psu-dcf-fix.md. None (not False)
                # for non-defense tickers so the frontend can three-
                # state-render: missing / explicitly-False / True.
                analyst_opinion_required=(
                    True if is_defense_psu_ticker else None
                ),
                # Layer C — Confidence Framework (PR 1). Additive
                # only; PR 2 will gate verdict intensity on these.
                data_quality_score=_cf_scores.get("data_quality"),
                model_confidence_score=_cf_scores.get("model_confidence"),
                valuation_stability_score=_cf_scores.get("valuation_stability"),
                # T2.7 (2026-06-09): 4th confidence pillar. None for
                # holdcos / banks / missing-base-inputs by design.
                confidence_sensitivity=_cf_scores.get("sensitivity"),
                # T1.6 (2026-06-10): 5th confidence pillar — agreement
                # among composite IV constituent estimators. None when
                # composite has <2 components (single-estimator path).
                confidence_composite_agreement=_cf_scores.get("composite_agreement"),
            ),
            quality=QualityOutput(
                yieldiq_score=yiq_score.get("score", 0),
                grade=yiq_score.get("grade", "C"),
                score_breakdown=_score_breakdown,
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
                de_ratio=_de_resolved,
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
                promoter_holding_type=_sh.get("promoter_holding_type"),
                promoter_entity=_sh.get("promoter_entity"),
                fii_pct=_sh.get("fii_pct"),
                dii_pct=_sh.get("dii_pct"),
                public_pct=_sh.get("public_pct"),
                # Bank-native metrics — None for non-banks. See
                # docs/bank_data_availability.md for the coverage matrix.
                is_bank=_is_bank_like,
                # ── Holdco propagation (2026-06-09) ───────────────
                # Single source of truth for "this is a pure holding
                # company". Read here, branched on in Honest Card,
                # Worry Index, ELI15 thesis, and Pulse Spectrum. The
                # `_holdco_skip` flag is set above when the override
                # routes through the SOTP skip path; the
                # `HOLDING_COMPANIES` membership check is the
                # belt-and-braces fallback for auto-detected names.
                is_holdco=bool(
                    _holdco_skip
                    or (
                        (ticker or "")
                        .replace(".NS", "")
                        .replace(".BO", "")
                        .upper()
                        in __import__(
                            "backend.services.analysis.constants",
                            fromlist=["HOLDING_COMPANIES"],
                        ).HOLDING_COMPANIES
                    )
                ),
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
                # feat/transparency (2026-05-02): provenance for the
                # revenue-CAGR hero metric. Window prefers the 5y view
                # when present, else 3y, else None. Source mirrors the
                # upstream data path used by the analysis pipeline.
                revenue_cagr_window=(
                    "5y" if _rev_cagr_5y is not None
                    else ("3y" if _rev_cagr_3y is not None else None)
                ),
                revenue_source=_data_source,
                # Reverse-DCF upstream normalisation (Option B per
                # docs/design/reverse-dcf-normalization.md, v2 2026-05-18).
                # Read from enriched stashes populated by
                # models/forecaster._compute_fcf_base during predict().
                # normalized_fcf_cr converts the raw-rupee anchor
                # (1e7 rupees = 1 Cr) into the ₹ Crore convention used
                # by the rest of QualityOutput. Both reads are
                # wrapped via _safe_float so any non-finite / non-
                # coercible value degrades to None instead of raising
                # inside QualityOutput construction (the failure mode
                # that took down PR #305).
                fcf_margin_5y=_safe_float(
                    enriched.get("normalized_fcf_margin")
                ),
                normalized_fcf_cr=_safe_div_1e7(
                    enriched.get("normalized_fcf_base")
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
                earnings_confirmed=_earnings_confirmed,
                earnings_source=_earnings_source,
                earnings_fiscal_period=_earnings_fiscal_period,
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
            analyst_consensus=_analyst_consensus,
            timestamp=_ts,
            computation_inputs=_computation_inputs,
            # ── Implied Assumptions extension (2026-06-10) ─────
            # AlphaSpread-style "what does the market expect?" framing
            # built from the same rdcf solver output we already compute
            # above. No second solver pass — we read the implied number
            # straight off `rdcf` (or, when consensus growth is present
            # but rdcf is missing the growth axis, fall back to a thin
            # delegating compute). Purely additive — the assignment is
            # `or None` so any KeyError / unexpected None silently
            # degrades to a hidden card rather than a 500.
            implied_assumptions=_build_implied_assumptions_dict(
                rdcf=rdcf,
                enriched=enriched,
                ticker=ticker,
                current_price=price,
                wacc=wacc,
                terminal_g=terminal_g,
                rev_cagr_3y=_rev_cagr_3y,
            ),
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
