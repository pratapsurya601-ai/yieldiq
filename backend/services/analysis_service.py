# backend/services/analysis_service.py
# ═══════════════════════════════════════════════════════════════
# Wraps existing screener/, models/, data/ logic for FastAPI.
# CRITICAL: Imports from existing modules. Does NOT rewrite logic.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure project root is on path so existing imports work
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# Dashboard also needs to be on path for some utilities
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.models.responses import (
    AnalysisResponse, ValuationOutput, QualityOutput,
    InsightCards, CompanyInfo, ScenariosOutput, ScenarioCase,
    PriceLevels, ScreenerStock,
)

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
        return {"score": max(0, min(100, _total)), "grade": "A" if _total >= 80 else "B" if _total >= 60 else "C" if _total >= 40 else "D"}


class AnalysisService:
    """Orchestrates full stock analysis using existing engines."""

    def get_full_analysis(self, ticker: str) -> AnalysisResponse:
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

        # ── Step 1: Fetch data (with retry for rate-limited .NS stocks) ─
        import time as _time
        raw = None
        for _attempt in range(3):
            try:
                collector = StockDataCollector(ticker)
                raw = collector.get_all()
                if raw is not None:
                    break
            except Exception:
                pass
            if raw is None and _attempt < 2:
                _time.sleep(3 + _attempt * 3)  # 3s, 6s delays

        # ── Step 2: Validate ──────────────────────────────────
        validation = validate_stock_data(ticker, raw)
        _raw_confidence = validation.confidence if validation else "medium"
        _confidence = _raw_confidence if _raw_confidence in ("high", "medium", "low", "unusable") else "medium"
        _data_issues = (validation.issues + validation.warnings) if validation else []

        if raw is None or (validation and not validation.show_dcf):
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
        price = enriched.get("price", 0)
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        # ── Step 4: Build company info ────────────────────────
        company = CompanyInfo(
            ticker=ticker,
            company_name=raw.get("company_name", ticker),
            sector=enriched.get("sector_name", raw.get("sector_name", "")),
            currency="INR",  # India-first launch
            market_cap=price * enriched.get("shares", 0),
        )

        # ── Step 5: WACC + Forecast ───────────────────────────
        forecaster = FCFForecaster()
        try:
            from models.forecaster import compute_wacc as _compute_wacc
            wacc_data = _compute_wacc(raw, is_indian)
            wacc = wacc_data.get("wacc", 0.10)
        except Exception:
            wacc_data = {}
            wacc = 0.10

        country = get_active_country()
        terminal_g = country.get("default_terminal_growth", 0.025)
        if terminal_g >= wacc:
            terminal_g = wacc - 0.02

        forecast_yrs = 10
        forecast_result = forecaster.predict(enriched, years=forecast_yrs)
        projected = forecast_result.get("projections", [])
        growth_schedule = forecast_result.get("growth_schedule", [])
        base_growth = forecast_result.get("base_growth", 0)

        if not projected or all(v <= 0 for v in projected):
            projected = [enriched.get("latest_fcf", 1e6)] * forecast_yrs

        terminal_norm = float(sum(projected[-3:]) / 3) if len(projected) >= 3 else projected[-1] if projected else 0

        # ── Step 6: Run DCF ───────────────────────────────────
        dcf_engine = DCFEngine(discount_rate=wacc, terminal_growth=terminal_g)
        dcf_res = dcf_engine.intrinsic_value_per_share(
            projected_fcfs=projected,
            terminal_fcf_norm=terminal_norm,
            total_debt=enriched.get("total_debt", 0),
            total_cash=enriched.get("total_cash", 0),
            shares_outstanding=enriched.get("shares", 1),
            current_price=price,
            ticker=ticker,
        )
        iv_raw = dcf_res.get("intrinsic_value_per_share", 0)

        # PE crosscheck blend
        try:
            eps = get_eps(enriched)
            sector = enriched.get("sector", "general")
            pe_iv = compute_pe_based_iv(eps, sector, "base", enriched.get("revenue_growth", 0))
            iv = blend_dcf_pe(iv_raw, pe_iv, sector)
        except Exception:
            iv = iv_raw

        mos_pct = margin_of_safety(iv, price) * 100 if price > 0 else 0

        # ── Step 7: Quality checks ────────────────────────────
        piotroski = compute_piotroski_fscore(enriched)
        moat_result = compute_moat_score(enriched, wacc)
        try:
            eq_result = compute_earnings_quality(enriched)
        except Exception:
            eq_result = {"score": 0, "grade": "N/A"}

        try:
            momentum_result = calculate_momentum(
                collector.get_price_history() if hasattr(collector, "get_price_history") else None
            )
        except Exception:
            momentum_result = {"momentum_score": 0, "grade": "N/A"}

        fund_result = score_fundamentals(enriched)
        confidence = compute_confidence_score(enriched)

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
            yiq_score = {"score": _total, "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D"}

        # ── Step 8: Scenarios ─────────────────────────────────
        try:
            fcf_base = projected[0] / (1 + growth_schedule[0]) if projected and growth_schedule and growth_schedule[0] > -1 else enriched.get("latest_fcf", 1e6)
            scenarios_raw = run_scenarios(
                enriched=enriched, fcf_base=fcf_base,
                base_growth=base_growth, base_wacc=wacc,
                base_terminal_g=terminal_g,
                total_debt=enriched.get("total_debt", 0),
                total_cash=enriched.get("total_cash", 0),
                shares=enriched.get("shares", 1),
                current_price=price, years=forecast_yrs,
            )
        except Exception:
            scenarios_raw = {}

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

        try:
            rdcf = run_reverse_dcf(enriched, price, wacc, terminal_g)
        except Exception:
            rdcf = {}

        try:
            fcf_yield = compute_fcf_yield_analysis(enriched, price)
        except Exception:
            fcf_yield = {}

        try:
            eveb = run_ev_ebitda_analysis(enriched, price, fetch_peers=False)
        except Exception:
            eveb = {}

        # Red flags from DCF edge cases
        _red_flags = dcf_res.get("warnings", [])
        if enriched.get("unreliable_reason"):
            _red_flags.append(enriched["unreliable_reason"])

        # ── Step 10: Verdict ──────────────────────────────────
        if mos_pct > 10:
            verdict = "undervalued"
        elif mos_pct > -10:
            verdict = "fairly_valued"
        elif enriched.get("dcf_reliable", True):
            verdict = "overvalued"
        else:
            verdict = "avoid"

        # ── Assemble response ─────────────────────────────────
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
                bear_case=_sc("Bear case").iv or _sc("Bear 🐻").iv,
                base_case=round(iv, 2),
                bull_case=_sc("Bull case").iv or _sc("Bull 🐂").iv,
                wacc=round(wacc * 100, 1),
                terminal_growth=round(terminal_g * 100, 1),
                fcf_growth_rate=round(enriched.get("fcf_growth", 0) * 100, 1),
                confidence_score=confidence.get("score", 50),
                wacc_industry_min=round(max(6, wacc * 100 - 2), 1),
                wacc_industry_max=round(min(16, wacc * 100 + 2), 1),
                fcf_growth_historical_avg=round(enriched.get("fcf_growth", 0) * 90, 1),
                tv_pct_of_ev=round(dcf_res.get("tv_pct_of_ev", 0) * 100, 1),
                dcf_reliable=enriched.get("dcf_reliable", True),
                reliability_score=dcf_res.get("reliability_score", 100),
                pv_fcfs=round(dcf_res.get("sum_pv_fcfs", 0), 0),
                pv_terminal=round(dcf_res.get("pv_tv", 0), 0),
                enterprise_value=round(dcf_res.get("enterprise_value", 0), 0),
                equity_value=round(dcf_res.get("equity_value", 0), 0),
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
                roe=enriched.get("roe"),
                de_ratio=enriched.get("de_ratio"),
            ),
            insights=InsightCards(
                patience_months=hp.get("min_months"),
                red_flag_count=len(_red_flags),
                red_flags=_red_flags[:5],
                earnings_date=raw.get("finnhub_next_earnings", {}).get("date"),
                earnings_est_eps=raw.get("finnhub_next_earnings", {}).get("eps_estimate"),
                wall_street_avg_target=(raw.get("finnhub_price_target") or {}).get("mean"),
                wall_street_target_count=(raw.get("finnhub_price_target") or {}).get("count"),
                insider_net_sentiment=(raw.get("finnhub_insider") or {}).get("sentiment"),
                market_expectations_growth=rdcf.get("implied_growth"),
                fcf_yield=fcf_yield.get("fcf_yield"),
                ev_ebitda=eveb.get("current_ev_ebitda") or enriched.get("ev_to_ebitda"),
                reverse_dcf_implied_growth=rdcf.get("implied_growth"),
            ),
            scenarios=ScenariosOutput(
                bear=_sc("Bear case") if scenarios_raw.get("Bear case") else _sc("Bear 🐻"),
                base=ScenarioCase(iv=round(iv, 2), mos_pct=round(mos_pct, 1), growth=round(base_growth, 4), wacc=round(wacc, 4), term_g=round(terminal_g, 4)),
                bull=_sc("Bull case") if scenarios_raw.get("Bull case") else _sc("Bull 🐂"),
            ),
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
            timestamp=_ts,
        )

    def get_ai_summary(self, ticker: str, analysis: AnalysisResponse) -> str:
        """Generate AI summary using existing Gemini/Groq integration."""
        try:
            from dashboard.utils.data_helpers import generate_ai_summary
            return generate_ai_summary(
                ticker, analysis.company.company_name,
                analysis.valuation.margin_of_safety,
                analysis.quality.moat,
                analysis.valuation.fcf_growth_rate,
                analysis.valuation.confidence_score,
            ) or ""
        except Exception:
            return ""
