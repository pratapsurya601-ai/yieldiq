"""dashboard/tabs/stock_analysis.py
Tab 1 — Single Stock Analysis.
Moved from app.py.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json as _json
import time as _time
from datetime import datetime, date as _date
from ui.cards import (
    snowflake_chart as _snowflake_chart,
    valuation_hero as _valuation_hero,
)

# Utility / formatting functions — loaded by file path to avoid utils/ name collision
import importlib.util as _ilu, pathlib as _pl
_dh_path = _pl.Path(__file__).resolve().parent.parent / "utils" / "data_helpers.py"
_dh_spec = _ilu.spec_from_file_location("_yiq_dh", _dh_path)
_dh_mod  = _ilu.module_from_spec(_dh_spec)
_dh_spec.loader.exec_module(_dh_mod)
CURRENCIES = _dh_mod.CURRENCIES
fmt = _dh_mod.fmt; fmts = _dh_mod.fmts
sig_human = _dh_mod.sig_human; mos_insight = _dh_mod.mos_insight
plain_kpi_label = _dh_mod.plain_kpi_label
KL = _dh_mod.KL; CL = _dh_mod.CL; apply_koyfin = _dh_mod.apply_koyfin
fetch_stock_data = _dh_mod.fetch_stock_data; get_fx_rate = _dh_mod.get_fx_rate
generate_ai_summary = _dh_mod.generate_ai_summary
show_upgrade_modal = _dh_mod.show_upgrade_modal
_render_relative_valuation_view = _dh_mod._render_relative_valuation_view

_cfg_path = _pl.Path(__file__).resolve().parent.parent.parent / "utils" / "config.py"
_cfg_spec = _ilu.spec_from_file_location("_yiq_cfg", _cfg_path)
_cfg_mod  = _ilu.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_cfg_mod)
FORECAST_YEARS = _cfg_mod.FORECAST_YEARS
LAUNCH_REGION  = _cfg_mod.LAUNCH_REGION
RESULTS_PATH   = _cfg_mod.RESULTS_PATH

# UI helpers
from ui.helpers import (
    render_empty_state, render_score_dial, ccard, ccard_end,
    FINANCIAL_TOOLTIPS, themed_metric,
)
from ui.report_generators import generate_dcf_report, generate_excel_dcf_model

# Tier-gate functions
from tier_gate import (
    can, tier, limit, can_analyse, record_analysis,
    can_download_report, record_report,
    can_download_pdf, record_pdf_report,
    check_ticker_allowed, upgrade_prompt, blur_and_lock,
    tier_badge_html, usage_bar_html,
    show_analysis_limit_modal, show_india_gate_message,
)

# Screener / model functions
from data.processor import compute_metrics
from models.forecaster import FCFForecaster, compute_confidence_score
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal, monte_carlo_valuation,
    sensitivity_analysis,
)
from screener.valuation_crosscheck import blend_dcf_pe, compute_pe_based_iv, get_eps
from screener.relative_valuation import check_ticker_dcf_eligibility, relative_valuation_only
from screener.scenarios import run_scenarios
from screener.ev_ebitda import run_ev_ebitda_analysis
from screener.piotroski import compute_piotroski_fscore
from screener.fcf_yield import compute_fcf_yield_analysis
from screener.historical_iv import compute_historical_iv
from screener.valuation_model import generate_valuation_summary as generate_investment_plan
from screener.sector_relative import compute_sector_relative

# Feature renderers
from features import (
    render_live_price_header, render_analyst_consensus,
    render_earnings_calendar,
)

# Portfolio / watchlist
from portfolio import add_to_watchlist, is_in_watchlist, get_watchlist

# Tab modules
from tabs import earnings_quality_tab, reverse_dcf_tab, moat_tab

# Onboarding
import importlib.util as _ilu, pathlib as _pl
_ob_path = _pl.Path(__file__).resolve().parent.parent / "onboarding.py"
_ob_spec = _ilu.spec_from_file_location("onboarding", _ob_path)
_ob_mod  = _ilu.module_from_spec(_ob_spec)
_ob_spec.loader.exec_module(_ob_mod)
ob_tooltip       = _ob_mod.tooltip
ob_show_tooltips = _ob_mod.show_tooltips

# Morning Brief
_mb_path = _pl.Path(__file__).resolve().parent.parent / "morning_brief.py"
_mb_spec = _ilu.spec_from_file_location("morning_brief", _mb_path)
_mb_mod  = _ilu.module_from_spec(_mb_spec)
_mb_spec.loader.exec_module(_mb_mod)
render_morning_brief     = _mb_mod.render_morning_brief
push_analysis_to_history = _mb_mod.push_analysis_to_history

# Admin analytics (track_event, track_analysis)
_aa_path = _pl.Path(__file__).resolve().parent.parent / "admin_analytics.py"
_aa_spec = _ilu.spec_from_file_location("admin_analytics", _aa_path)
_aa_mod  = _ilu.module_from_spec(_aa_spec)
_aa_spec.loader.exec_module(_aa_mod)
track_event    = _aa_mod.track_event
track_analysis = _aa_mod.track_analysis

# Yieldiq score (defined in app.py, now needs separate import)
import importlib as _il
_app_score_path = _pl.Path(__file__).resolve().parent.parent / "app.py"

APP_VERSION = "v6"


def _read_sidebar_vars():
    """Read sidebar variables from session_state."""
    _cur = st.session_state.get("sb_currency", "USD")
    return {
        "sym":           CURRENCIES[_cur]["symbol"],
        "to_code":       CURRENCIES[_cur]["code"],
        "cur_key":       _cur,
        "fx_rate":       st.session_state.get("_fx_rate_usd", 1.0),
        "fx_inr":        st.session_state.get("_fx_rate_inr", 1.0),
        "use_auto_wacc": st.session_state.get("sb_auto_wacc", True),
        "manual_wacc":   st.session_state.get("sb_manual_wacc", 10),
        "terminal_g":    st.session_state.get("sb_terminal_pct", 3) / 100,
        "forecast_yrs":  st.session_state.get("sb_forecast_yrs", FORECAST_YEARS),
        "run_mc":        st.session_state.get("sb_run_mc", False),
        "pro_mode":      st.session_state.get("pro_mode", False),
        "results_file":  None,
    }


def render() -> None:
    """Render the full Stock Analysis tab."""
    # ── Read sidebar variables from session_state ───────────────
    _sv = _read_sidebar_vars()
    sym           = _sv["sym"]
    to_code       = _sv["to_code"]
    cur_key       = _sv["cur_key"]
    fx_rate       = _sv["fx_rate"]
    fx_inr        = _sv["fx_inr"]
    use_auto_wacc = _sv["use_auto_wacc"]
    manual_wacc   = _sv["manual_wacc"]
    terminal_g    = _sv["terminal_g"]
    terminal_pct  = int(terminal_g * 100)
    forecast_yrs  = _sv["forecast_yrs"]
    run_mc        = _sv["run_mc"]
    pro_mode      = _sv["pro_mode"]
    results_file  = _sv["results_file"]

    # Functions that may not exist in all environments
    compute_ddm = None
    _sc_p = _pl.Path(__file__).resolve().parent.parent / "utils" / "scoring.py"
    _sc_s = _ilu.spec_from_file_location("_yiq_sc", _sc_p)
    _sc_m = _ilu.module_from_spec(_sc_s); _sc_s.loader.exec_module(_sc_m)
    compute_yieldiq_score = _sc_m.compute_yieldiq_score

    # ── Analysis page CSS polish ────────────────────────────────
    st.html("""<style>
    /* Smooth fade-in for analysis results */
    @keyframes yiq-fade { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
    .element-container { animation: yiq-fade 0.3s ease-out; }

    /* Section label style (VALUATION, SCENARIOS, etc.) */
    .yiq-section-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 11px; font-weight: 700;
        color: #94A3B8; letter-spacing: 0.14em;
        text-transform: uppercase; margin: 20px 0 10px;
        padding-left: 2px;
    }

    /* Plotly chart containers — subtle card wrapper */
    [data-testid="stPlotlyChart"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 8px;
        box-shadow: 0 1px 3px rgba(15,23,42,0.04);
        margin-bottom: 8px;
    }

    /* Metric cards — tighter spacing */
    [data-testid="stMetric"] {
        margin-bottom: 4px !important;
    }

    /* Better expander styling for analysis */
    [data-testid="stExpander"] {
        border: 1px solid #E2E8F0 !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        margin-bottom: 10px !important;
        box-shadow: 0 1px 3px rgba(15,23,42,0.03) !important;
    }
    [data-testid="stExpander"] summary {
        background: #FAFBFC !important;
        border-bottom: 1px solid #F1F5F9 !important;
    }
    [data-testid="stExpander"] summary:hover {
        background: #F0F4FF !important;
    }

    /* Dividers — subtler */
    [data-testid="stHorizontalRule"] hr,
    hr {
        border: none !important;
        border-top: 1px solid #F1F5F9 !important;
        margin: 16px 0 !important;
    }
    </style>""")

    # ── Original code from app.py (lines 2075–6665) ────────────
    sc1, sc2, sc3 = st.columns([2, 1, 3])
    with sc1:
        # ── Pre-fill from recent ticker click or popular pill ────
        _pf = st.session_state.pop("_prefill_ticker", None) or st.session_state.pop("ticker_input", None)
        if LAUNCH_REGION == "US":
            _default_ticker = _pf if _pf else "AAPL"
            _ticker_placeholder = "AAPL · MSFT · GOOGL · NVDA · JPM"
        else:
            _default_ticker = _pf if _pf else "TCS.NS"
            _ticker_placeholder = "TCS.NS · RELIANCE.NS · AAPL"
        ticker_input = st.text_input(
            "Ticker", value=_default_ticker,
            placeholder=_ticker_placeholder,
            label_visibility="collapsed"
        ).upper().strip()
    with sc2:
        analyse_btn = (
            st.button("🔍 Analyse this stock", width='stretch')
            or st.session_state.pop("_auto_analyse", False)
        )

    # Must be defined here — used by hero check below AND by redisplay logic later
    _has_results = (
        st.session_state.get("fin_ticker") and
        st.session_state.get("fin_enriched") is not None
    )

    # sc3 intentionally empty — clean layout

    # Show Morning Brief when:
    #   (a) no analysis triggered AND no cached results, OR
    #   (b) user explicitly navigated home via session state flag
    # Morning Brief only shows when explicitly navigated (sidebar Home click)
    # NOT as default — analysis results take priority
    _show_brief = st.session_state.get("_show_morning_brief", False)
    if analyse_btn or _has_results:
        st.session_state["_show_morning_brief"] = False
        _show_brief = False

    if not analyse_btn and not _has_results:
        # ── Empty state — search hero + quick picks ─────────
        st.markdown("""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            padding:32px 0 16px;">
  <div style="text-align:center;margin-bottom:32px;">
    <div style="font-size:32px;font-weight:900;color:#0F172A;
                letter-spacing:-1px;line-height:1.2;margin-bottom:8px;">
      Is this stock cheap or expensive?
    </div>
    <div style="font-size:15px;color:#64748B;font-weight:400;
                max-width:420px;margin:0 auto;line-height:1.6;">
      Enter any stock ticker to get institutional-grade DCF valuation,
      grade badges, and a plain English verdict in seconds.
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);
              gap:12px;max-width:640px;margin:0 auto 32px;">
    <div style="background:#F0FDF4;border:1px solid #BBF7D0;
                border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:24px;margin-bottom:8px;">\U0001f4ca</div>
      <div style="font-size:12px;font-weight:700;color:#15803D;
                  margin-bottom:4px;">DCF Valuation</div>
      <div style="font-size:11px;color:#166534;line-height:1.4;">
        Fair value estimate with margin of safety</div>
    </div>
    <div style="background:#EFF6FF;border:1px solid #BFDBFE;
                border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:24px;margin-bottom:8px;">\U0001f393</div>
      <div style="font-size:12px;font-weight:700;color:#1D4ED8;
                  margin-bottom:4px;">Grade Badges</div>
      <div style="font-size:11px;color:#1E40AF;line-height:1.4;">
        A/B/C/D for Valuation, Quality, Growth, Sentiment</div>
    </div>
    <div style="background:#FFF7ED;border:1px solid #FED7AA;
                border-radius:12px;padding:16px;text-align:center;">
      <div style="font-size:24px;margin-bottom:8px;">\U0001f4ac</div>
      <div style="font-size:12px;font-weight:700;color:#C2410C;
                  margin-bottom:4px;">Plain English</div>
      <div style="font-size:11px;color:#9A3412;line-height:1.4;">
        What it means in language anyone understands</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

        st.markdown(
            "<div style='text-align:center;font-size:11px;color:#94A3B8;"
            "letter-spacing:0.5px;margin-bottom:10px;'>"
            "POPULAR STOCKS \u2014 CLICK TO ANALYSE</div>",
            unsafe_allow_html=True,
        )
        # Popular stocks from country config
        try:
            from config.countries import get_active_country as _gac
            _country = _gac()
            _quick_picks = _country.get("popular_display", ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA", "JPM"])
        except Exception:
            _quick_picks = ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "TSLA", "JPM"]
        _qp_cols = st.columns(len(_quick_picks))
        for _qc, _qt in zip(_qp_cols, _quick_picks):
            with _qc:
                if st.button(_qt, key=f"qp_{_qt}", use_container_width=True):
                    st.session_state["_prefill_ticker"] = _qt
                    st.session_state["_auto_analyse"]   = True
                    st.session_state["_show_morning_brief"] = False
                    st.rerun()
    elif not analyse_btn and _show_brief:
        # ── Returning user navigated home — Morning Brief ────────
        render_morning_brief(
            watchlist_rows=get_watchlist(),
            sym=sym,
            has_prior_results=_has_results,
            theme=st.session_state.get("theme", "slate"),
        )


    # Re-render from session state if we already have results
    # This prevents page reset on any rerun (form submit, button click etc.)
    # NOTE: _has_results is defined earlier (before hero check) — do not redefine
    _should_analyse = analyse_btn and ticker_input
    _should_redisplay = (
        _has_results and
        not analyse_btn and
        not _show_brief
    )

    # Re-display from session state (after form submit / button click rerun)
    if _should_redisplay:
        ticker_input = st.session_state.get("fin_ticker", "")
        _should_analyse = True

    if _should_analyse and ticker_input:
        # ── Skip fetch/compute if redisplaying from session state ──
        _from_cache = (
            _should_redisplay and
            not analyse_btn and  # clicking Analyse always does fresh fetch
            st.session_state.get("fin_ticker") == ticker_input and
            st.session_state.get("fin_enriched") is not None and
            st.session_state.get("_dcf_res") is not None
        )

        if _from_cache:
            # ── Short-circuit for non-DCF tickers (from cache) ──────
            if not st.session_state.get("_dcf_eligible", True):
                _rel_val = st.session_state.get("_rel_val", {})
                raw      = st.session_state.get("fin_raw", {})
                _render_relative_valuation_view(
                    ticker=ticker_input,
                    rv=_rel_val or {},
                    raw=raw,
                    sym=st.session_state.get("fin_sym", "$"),
                    fx=st.session_state.get("fin_fx", 1.0),
                )
                st.stop()

            # Restore all computed variables from session state
            import pandas as _pd
            enriched        = st.session_state.get("fin_enriched", {})
            raw             = st.session_state.get("fin_raw", {})
            fx              = st.session_state.get("fin_fx", 1.0)
            to_code         = st.session_state.get("fin_to_code", "USD")
            sym             = st.session_state.get("fin_sym", "$")
            iv_d            = st.session_state.get("fin_iv_d", 0)
            mos_pct         = st.session_state.get("fin_mos_pct", 0)
            sig             = st.session_state.get("fin_signal", "N/A ⬜")
            dcf_res         = st.session_state.get("_dcf_res", {})
            forecast_result = st.session_state.get("_forecast_result", {})
            scenarios       = st.session_state.get("_scenarios", {})
            inv_plan        = st.session_state.get("_inv_plan", {
                "price_targets":{}, "holding_period":{},
                "fundamental":{"grade":"N/A","score":0}
            })
            confidence      = st.session_state.get("_confidence", {"grade":"N/A","score":0})
            price_hist      = st.session_state.get("_price_hist", _pd.DataFrame())
            wacc_data       = st.session_state.get("_wacc_data", {})
            use_auto_wacc   = st.session_state.get("_use_auto_wacc", True)
            forecast_yrs    = st.session_state.get("_forecast_yrs", 10)
            terminal_pct    = st.session_state.get("_terminal_pct", 3)
            _rf_rate_info   = st.session_state.get("_rf_rate_info", {})
            _insider_adj    = st.session_state.get("_insider_adj", 0.0)
            _insider_data   = raw.get("finnhub_insider", {})
            _insider_sent   = _insider_data.get("sentiment", "NEUTRAL")
            # Recompute derived display vars
            price_n         = enriched.get("price", 0)
            price_d         = price_n * fx
            iv_n            = iv_d / fx if fx else iv_d
            mos             = mos_pct / 100
            terminal_g      = terminal_pct / 100
            native_ccy      = raw.get("native_ccy", "USD")
            company_name    = raw.get("company_name", ticker_input)
            wacc            = enriched.get("wacc_used", 0.10)
            wacc_source     = enriched.get("wacc_source", "Auto CAPM")
            projected       = forecast_result.get("projections", [])
            terminal_norm   = forecast_result.get("terminal_fcf_norm", 0)
            pv_tv_d         = dcf_res.get("pv_tv", 0) * fx
            proj_d          = [v * fx for v in projected]
            pv_fcfs_d       = [v * fx for v in dcf_res.get("pv_fcfs", [])]
            fx_rate         = st.session_state.get("_fx_rate", 1.0)
            pt              = inv_plan.get("price_targets", {})
            hp              = inv_plan.get("holding_period", {})
            fs              = inv_plan.get("fundamental", {"grade":"N/A","score":0})
            suspicious      = dcf_res.get("suspicious", False)
            _show_plan      = can("action_plan")
            _show_quality   = can("quality_score")
            _show_scenarios = can("scenarios")
            _show_sensitive = can("sensitivity")
            _show_mc        = can("monte_carlo")
            mos_color = "#0D7A4E" if mos_pct>20 else "#B8972A" if mos_pct>0 else "#A62020"
            mos_w     = min(max(abs(mos_pct), 2), 100)
            _fs_color_map = {"STRONG":"#0D7A4E","GOOD":"#2563EB","AVERAGE":"#B8972A","WEAK":"#A62020"}
            _fs_color = _fs_color_map.get(fs.get("grade",""), "#4A5E7A")
            _fs_label = fs.get("grade", "N/A")
            # Use human language signal helper for colors
            _h_label_c, sig_fg, sig_bg, sig_bd = sig_human(sig)
            years_labels    = [f"Y{i+1}" for i in range(forecast_yrs)]
            # Derive vars that come from forecast_result
            growth_schedule = forecast_result.get("growth_schedule", [])
            base_growth     = forecast_result.get("base_growth", 0)
            fcf_base        = forecast_result.get("fcf_base", 0)
            if len(projected) > 0 and len(growth_schedule) > 0 and growth_schedule[0] > -1:
                fcf_base_for_scenarios = projected[0] / (1 + growth_schedule[0])
            else:
                fcf_base_for_scenarios = fcf_base if fcf_base > 0 else enriched.get("latest_fcf", 1e6)
            # Derive moat display vars from enriched
            moat_grade      = enriched.get("moat_grade", "None")
            moat_score      = enriched.get("moat_score", 0)
            _moat_result    = st.session_state.get("fin_moat", {})
            _moat_adj       = st.session_state.get("fin_moat_adj", {})
            native_ccy      = raw.get("native_ccy", "USD")
            company_name    = raw.get("company_name", ticker_input)
            # Restore wacc/terminal from enriched
            wacc            = enriched.get("wacc_used", enriched.get("wacc", 0.10))
            terminal_g      = enriched.get("terminal_g_used", terminal_g)
            wacc_source     = enriched.get("wacc_source", "Auto CAPM")
            # inv_plan sub-vars
            buy_d    = (pt.get("buy_price")    or 0) * fx
            tgt_d    = (pt.get("target_price") or 0) * fx
            sl_d     = (pt.get("stop_loss")    or 0) * fx
            upside   = ((tgt_d - price_d) / price_d * 100) if price_d > 0 else 0
            downside = pt.get("sl_pct", 15)
            rr       = pt.get("rr_ratio", 0)
            # Enriched sub-vars used in display
            shares             = enriched.get("shares", 0)
            shares_outstanding = enriched.get("shares", 0)
            total_debt         = enriched.get("total_debt", 0)
            total_cash         = enriched.get("total_cash", 0)
            current_price      = price_n
            _sector            = enriched.get("sector", "general")
            sector             = _sector
            _pe_iv             = enriched.get("pe_iv", 0)
            projected_fcfs     = projected
            moat_adj           = _moat_adj
            moat_summary       = enriched.get("moat_summary", "")
            moat_types         = enriched.get("moat_types", [])
            iv_delta_pct       = _moat_adj.get("iv_delta_pct", 0)
            mc_result          = st.session_state.get("_mc_result", {})
            _conf_warnings     = confidence.get("warnings", [])
            years              = forecast_yrs

        else:
            # ── TIER CHECK: daily limit ─────────────────────────
            if not can_analyse():
                show_analysis_limit_modal()
                st.stop()

            # ── TIER CHECK / REGION CHECK: market access ────────
            allowed, reason = check_ticker_allowed(ticker_input)
            if not allowed:
                if reason == "india_region":
                    # US launch mode — Indian tickers not yet available
                    st.info(
                        "🇮🇳 **Indian market stocks are coming soon.** "
                        "YieldIQ is currently serving US markets only. "
                        "Stay tuned for NSE/BSE coverage!",
                        icon="🚧",
                    )
                elif reason == "europe_region":
                    st.info(
                        "🌍 **European market stocks are coming soon.** "
                        "YieldIQ is currently serving US markets only.",
                        icon="🚧",
                    )
                elif reason == "india":
                    show_india_gate_message()
                else:
                    upgrade_prompt(reason)
                st.stop()

            # ── Multi-step progress card ──────────────────────────
            _prog_ph = st.empty()
            _PROG_STEPS = [
                "Fetching live price data",
                "Loading 5 years of financial statements",
                "Running AI growth forecast",
                "Computing DCF valuation + 8 quality checks",
                "Running Bear/Base/Bull scenario analysis",
            ]

            def _update_progress(step: int, detail: str = "") -> None:
                """Re-render the progress card at the given step index (0-based)."""
                _pct = min((step + 1) * 20, 100)
                _rows = ""
                for _si, _sl in enumerate(_PROG_STEPS):
                    if _si < step:
                        _ic, _col, _fw, _dots = "", "#059669", "500", ""
                    elif _si == step:
                        _ic, _col, _fw, _dots = "⏳", "#1D4ED8", "600", "…"
                    else:
                        _ic, _col, _fw, _dots = "◻", "#CBD5E1", "400", ""
                    _rows += (
                        f'<div style="display:flex;align-items:center;gap:10px;'
                        f'padding:5px 0;font-size:12px;color:{_col};font-weight:{_fw};">'
                        f'<span style="width:16px;text-align:center;">{_ic}</span>'
                        f'<span>{_sl}{_dots}</span></div>'
                    )
                _det = (
                    f'<div style="margin-top:10px;padding:8px 10px;background:#F8FAFC;'
                    f'border-radius:6px;font-size:11px;color:#475569;'
                    f'font-family:\'IBM Plex Mono\',monospace;">{detail}</div>'
                ) if detail else ""
                _prog_ph.markdown(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:14px;
            padding:22px 26px;box-shadow:0 4px 20px rgba(15,23,42,0.07);
            margin:16px 0;max-width:540px;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
    <div style="width:36px;height:36px;background:linear-gradient(135deg,#1D4ED8,#06B6D4);
                border-radius:9px;display:flex;align-items:center;justify-content:center;
                font-size:16px;flex-shrink:0;">🔍</div>
    <div>
      <div style="font-size:13px;font-weight:700;color:#0F172A;">
        Analyzing <code style="background:#EFF6FF;color:#1D4ED8;
        padding:1px 6px;border-radius:4px;font-size:12px;">{ticker_input}</code>
      </div>
      <div style="font-size:11px;color:#94A3B8;margin-top:1px;">
        Model-based analysis · not investment advice
      </div>
    </div>

  </div>
  <div style="height:4px;background:#E2E8F0;border-radius:2px;margin-bottom:16px;">
    <div style="height:100%;width:{_pct}%;
                background:linear-gradient(90deg,#1D4ED8,#06B6D4);
                border-radius:2px;transition:width 0.35s ease;"></div>
  </div>
  {_rows}
  {_det}
</div>
""", unsafe_allow_html=True)

            _update_progress(0)
            raw, price_hist, wacc_data, momentum_result = fetch_stock_data(ticker_input)

        if not _from_cache:
            if raw is None:
                # ── Retry: try appending .NS for Indian stocks entered without suffix ──
                if not ticker_input.endswith((".NS", ".BO")):
                    try:
                        _r2, _ph2, _wd2, _mr2 = fetch_stock_data(ticker_input + ".NS")
                        if _r2 is not None:
                            raw, price_hist, wacc_data, momentum_result = _r2, _ph2, _wd2, _mr2
                            ticker_input = ticker_input + ".NS"
                    except Exception:
                        pass

            if raw is None:
                # ── Last resort: try Finnhub directly for basic data ──
                try:
                    from data.collector import _fh_quote, _fh_profile, _fh_basic_financials, FINNHUB_KEY
                    if FINNHUB_KEY:
                        _fh_q = _fh_quote(ticker_input)
                        _fh_p = _fh_profile(ticker_input)
                        _fh_f = _fh_basic_financials(ticker_input)
                        _fh_price = _fh_q.get("price", 0) if _fh_q else 0
                        if _fh_price > 0:
                            if "_prog_ph" in dir():
                                try: _prog_ph.empty()
                                except Exception: pass
                            from ui.cards import inject_styles as _inject_card_styles, kpi_row as _kpi_row
                            _inject_card_styles()
                            st.warning(
                                f"**{ticker_input}**: Yahoo Finance is rate-limiting this server. "
                                f"Showing Finnhub data only — full DCF analysis unavailable.\n\n"
                                f"**Try again in 2\u20133 minutes** for the complete analysis."
                            )
                            _fh_co = (_fh_p or {}).get("company_name", ticker_input)
                            _fh_beta = (_fh_f or {}).get("beta", 0)
                            _fh_pe = (_fh_f or {}).get("pe_ttm", 0)
                            _fh_dy = (_fh_f or {}).get("div_yield_ttm", 0)
                            _kpi_row([
                                {"label": "Market Price", "value": f"{sym}{_fh_price:,.2f}"},
                                {"label": "P/E (TTM)", "value": f"{_fh_pe:.1f}\u00d7" if _fh_pe else "\u2014"},
                                {"label": "Beta", "value": f"{_fh_beta:.2f}" if _fh_beta else "\u2014"},
                                {"label": "Div Yield", "value": f"{_fh_dy*100:.2f}%" if _fh_dy else "\u2014"},
                            ])
                            st.caption(f"Data: Finnhub \u00b7 {_fh_co} \u00b7 Model output only, not investment advice.")
                            st.stop()
                except Exception:
                    pass

                if "_prog_ph" in dir():
                    try: _prog_ph.empty()
                    except Exception: pass
                # ── Common ticker alias suggestions ───────────────────────
                _ticker_suggestions: dict[str, str] = {
                    "GOOG":    "Try <b>GOOGL</b> — Alphabet Inc. Class A shares.",
                    "BRK":     "Try <b>BRK-B</b> — Berkshire Hathaway Class B.",
                    "BRKB":    "Try <b>BRK-B</b>.",
                    "FB":      "Meta Platforms now trades as <b>META</b>.",
                    "TWITTER": "Twitter is private. Try <b>META</b> or <b>SNAP</b>.",
                    "GOOGLE":  "Try <b>GOOGL</b> or <b>GOOG</b>.",
                }
                _sugg = _ticker_suggestions.get(ticker_input.upper(), "")
                _err_obj = st.session_state.get("_last_fetch_error", "")
                if "429" in str(_err_obj) or "rate" in str(_err_obj).lower():
                    _reason = "Data provider rate limit reached. Please wait 60 seconds."
                    _action = "→ Wait a moment, then try again"
                elif "connection" in str(_err_obj).lower() or "timeout" in str(_err_obj).lower():
                    _reason = "Could not reach the data provider. Check your internet connection."
                    _action = "→ Check your connection and try again"
                elif _sugg:
                    _reason = f"Ticker not found — possible alias detected."
                    _action = _sugg
                else:
                    _reason = (
                        "No data found for this ticker. "
                        "It may be delisted, private, or entered incorrectly. "
                        "Indian stocks need the suffix: <b>RELIANCE.NS</b>"
                    )
                    _action = "→ Double-check the symbol and try again"
                st.html(f"""
<div style="border-left:4px solid #DC2626;background:#FEF2F2;
            border-radius:0 12px 12px 0;padding:18px 22px;margin:16px 0;
            box-shadow:0 2px 8px rgba(220,38,38,0.07);">
  <div style="display:flex;align-items:flex-start;gap:14px;">
    <span style="font-size:22px;flex-shrink:0;">⚠️</span>
    <div>
      <div style="font-size:14px;font-weight:700;color:#991B1B;
                  margin-bottom:6px;font-family:'Inter',sans-serif;">
        Could not load data for
        <code style="background:rgba(220,38,38,0.1);color:#991B1B;
               padding:1px 6px;border-radius:4px;font-size:13px;">{ticker_input}</code>
      </div>
      <div style="font-size:13px;color:#7F1D1D;line-height:1.65;
                  font-family:'Inter',sans-serif;">{_reason}</div>
      <div style="margin-top:10px;font-size:12px;color:#1D4ED8;
                  font-weight:600;font-family:'Inter',sans-serif;">{_action}</div>
    </div>
  </div>
</div>
""")
                st.stop()

            # Record this analysis
            record_analysis()
            st.session_state["last_fetch_time"] = _time.time()
            # ── Track recent tickers ──────────────────────────────────
            _rt = st.session_state.get("recent_tickers", [])
            if ticker_input not in _rt:
                _rt.append(ticker_input)
            st.session_state["recent_tickers"] = _rt[-10:]  # keep last 10

        if not _from_cache:
            _price_n_tmp = (raw or {}).get("price", 0)
            _price_str   = f"{sym}{_price_n_tmp:,.2f}" if _price_n_tmp else ""
            _update_progress(1, f"{ticker_input}: {_price_str}" if _price_str else "")
            enriched   = compute_metrics(raw)
            _update_progress(2)
            forecaster = FCFForecaster()

            wacc = wacc_data.get("wacc", manual_wacc/100) if use_auto_wacc and wacc_data.get("auto_computed") else manual_wacc/100
            wacc_source = f"Auto CAPM ({wacc:.1%})" if use_auto_wacc and wacc_data.get("auto_computed") else f"Manual ({manual_wacc}%)"

            # ── Sector detection + industry WACC adjustment ────────
            # This is the critical step that was missing from the dashboard.
            # Detects sector from ticker, applies industry-appropriate WACC,
            # and stores sector in enriched for PE blending to use correctly.
            try:
                from models.industry_wacc import get_industry_wacc, detect_sector
                _yf_sector   = raw.get("sector_name", "") if raw else ""
                _sector_key  = detect_sector(ticker_input, _yf_sector)
                # Pass yf_sector so data/analytics cos (SPGI,MCO) don't fall into us_banks
                _ind_info    = get_industry_wacc(ticker=ticker_input, yf_sector=_yf_sector, capm_wacc=wacc)
                enriched["sector"]      = _sector_key
                enriched["sector_name"] = _ind_info.get("sector_name", _sector_key)
                # Only use industry WACC if auto mode is on
                if use_auto_wacc:
                    wacc       = _ind_info["wacc"]
                    terminal_g = _ind_info["terminal_growth"]
                    wacc_source = f"Industry-Adjusted ({wacc:.1%}, {_sector_key})"
            except Exception as _se:
                _sector_key = "general"
                enriched.setdefault("sector", "general")

            # ── Non-DCF eligibility check ──────────────────────────
            # Banks, REITs, and insurance companies skip DCF entirely.
            # Route them to relative valuation and stop here.
            _gics_sector = raw.get("sector_name", "") or enriched.get("sector_name", "")
            _dcf_eligible = check_ticker_dcf_eligibility(
                ticker_input,
                sector_key=_sector_key,
                gics_sector=_gics_sector,
            )
            if not _dcf_eligible:
                _update_progress(3, "Running relative valuation (non-DCF sector)…")
                _rel_val = relative_valuation_only(
                    ticker=ticker_input,
                    sector_key=_sector_key,
                    raw=raw,
                    gics_sector=_gics_sector,
                )
                _prog_ph.empty()
                # Compute FX for non-DCF view
                _native_ccy = raw.get("native_ccy", "USD")
                _fx_rv = get_fx_rate(_native_ccy, to_code)
                # Persist to session state so cache path works on rerun
                st.session_state["fin_ticker"]     = ticker_input
                st.session_state["fin_raw"]        = raw
                st.session_state["_dcf_eligible"]  = False
                st.session_state["_rel_val"]       = _rel_val
                st.session_state["fin_enriched"]   = enriched
                st.session_state["_dcf_res"]       = {"_non_dcf": True}
                st.session_state["fin_sym"]        = sym
                st.session_state["fin_fx"]         = _fx_rv
                st.session_state["fin_to_code"]    = to_code
                _render_relative_valuation_view(
                    ticker=ticker_input,
                    rv=_rel_val or {},
                    raw=raw,
                    sym=sym,
                    fx=_fx_rv,
                )
                st.stop()

            _update_progress(3)

            # ── Guard: skip DCF if financial statements are empty (Finnhub-only mode) ──
            _has_financials = (
                enriched.get("latest_revenue", 0) != 0
                or enriched.get("latest_fcf", 0) != 0
            )
            if not _has_financials:
                if "_prog_ph" in dir():
                    try: _prog_ph.empty()
                    except Exception: pass
                st.warning(
                    f"**{ticker_input}**: Yahoo Finance is temporarily rate-limiting this server. "
                    f"We got the price ({sym}{enriched.get('price', 0):,.2f}) and basic ratios from Finnhub, "
                    f"but financial statements are unavailable for DCF analysis.\n\n"
                    f"**Try again in 2\u20133 minutes** — the rate limit resets automatically."
                )
                from ui.cards import kpi_row as _kpi_row
                _fh_price = enriched.get('price', 0)
                _kpi_row([
                    {"label": "Market Price", "value": f"{sym}{_fh_price:,.2f}"},
                    {"label": "Beta", "value": f"{raw.get('fh_beta', 0):.2f}" if raw.get('fh_beta') else "\u2014"},
                    {"label": "Div Yield", "value": f"{raw.get('fh_div_yield', 0)*100:.2f}%" if raw.get('fh_div_yield') else "\u2014"},
                    {"label": "P/E (Finnhub)", "value": f"{raw.get('forward_pe', 0):.1f}\u00d7" if raw.get('forward_pe') else "\u2014"},
                ])
                st.caption("Model output only. Not investment advice. Full DCF requires financial statement data from Yahoo Finance.")
                st.stop()

            dcf_engine      = DCFEngine(discount_rate=wacc, terminal_growth=terminal_g)
            forecast_result = forecaster.predict(enriched, years=forecast_yrs)
            projected       = forecast_result["projections"]
            terminal_norm   = forecast_result["terminal_fcf_norm"]
            base_growth     = forecast_result["base_growth"]
            fcf_base        = forecast_result["fcf_base"]
            growth_schedule = forecast_result["growth_schedule"]
            _growth_str     = f"{base_growth:.1%} projected FCF growth" if base_growth else ""
            _update_progress(3, _growth_str)

            # Guard: estimate shares if still 0 at DCF time
            _dcf_shares = enriched.get("shares", 0)
            if _dcf_shares <= 0 and enriched.get("price", 0) > 0:
                # Try market_cap / price
                _mc_est = (raw or {}).get("finnhub_financials", {}).get("market_cap", 0)
                if not _mc_est:
                    _mc_est = enriched.get("price", 0) * 1e9  # rough: assume $1T for mega-caps
                _dcf_shares = _mc_est / enriched["price"] if enriched["price"] > 0 else 1e9
                enriched["shares"] = _dcf_shares
    
            dcf_res = dcf_engine.intrinsic_value_per_share(
                projected_fcfs=projected, terminal_fcf_norm=terminal_norm,
                total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                shares_outstanding=enriched["shares"],
                current_price=enriched["price"], ticker=ticker_input,
            )

            _update_progress(4)
            # Scenarios — use the SAME fcf_base the main forecaster used
            # Reconstruct it from projections[0] / (1 + growth_schedule[0])
            # to guarantee scenarios start from identical FCF base as main DCF
            if len(projected) > 0 and len(growth_schedule) > 0 and growth_schedule[0] > -1:
                fcf_base_for_scenarios = projected[0] / (1 + growth_schedule[0])
            else:
                fcf_base_for_scenarios = fcf_base if fcf_base > 0 else enriched.get("latest_fcf", 1e6)

            scenarios = run_scenarios(
                enriched=enriched,
                fcf_base=fcf_base_for_scenarios,
                base_growth=base_growth,
                base_wacc=wacc,
                base_terminal_g=terminal_g,
                total_debt=enriched["total_debt"],
                total_cash=enriched["total_cash"],
                shares=enriched["shares"],
                current_price=enriched["price"],
                years=forecast_yrs,
            )

            # Base IV and price (before moat adjustment)
            iv_n    = dcf_res.get("intrinsic_value_per_share", 0)
            price_n = enriched["price"]

            # ── PE Crosscheck — blend DCF with sector PE IV ────
            # Dashboard was using raw DCF only. Now blends like screener does.
            try:
                from screener.valuation_crosscheck import compute_pe_based_iv, blend_dcf_pe, get_eps
                _sector   = enriched.get("sector", "general")
                _reliable = enriched.get("dcf_reliable", True)
                _eps      = get_eps(enriched)
                _pe_iv    = compute_pe_based_iv(_eps, _sector, scenario="base",
                                                growth=enriched.get("revenue_growth", None))

                if _reliable and iv_n > 0 and _pe_iv > 0:
                    iv_n = blend_dcf_pe(iv_n, _pe_iv, _sector)
                elif _pe_iv > 0 and not _reliable:
                    # Banks/NBFCs: DCF unreliable — only use PE if EPS is credible
                    # Extra sanity: implied PE must be 5-60x
                    _implied_pe = enriched.get("price", 0) / _eps if _eps > 0 else 0
                    if 5 <= _implied_pe <= 60:
                        iv_n = _pe_iv
                    # else: leave iv_n = 0 so N/A is displayed
                enriched["pe_iv"]  = _pe_iv
                enriched["dcf_iv"] = dcf_res.get("intrinsic_value_per_share", 0)
            except Exception as _pe_err:
                enriched["pe_iv"]  = 0
                enriched["dcf_iv"] = iv_n

            # Moat — compute first, then adjust IV before investment plan
            iv_n_moat, moat_grade, moat_score, moat_adj = moat_tab.compute(
                enriched=enriched,
                wacc=wacc,
                base_growth=base_growth,
                terminal_g=terminal_g,
                iv_n=iv_n,
            )
            moat_types   = enriched.get("moat_types",   [])
            moat_summary = enriched.get("moat_summary", "")

            # ── Confidence-based IV haircut ────────────────────
            # When confidence flags major warnings, reduce IV to reflect
            # the uncertainty. This is the IB approach: widen the range
            # and reduce point estimate when data quality is poor.
            confidence     = compute_confidence_score(enriched)
            _conf_warnings = confidence.get("warnings", [])
            _iv_haircut = 1.0
            _rev_growth_conf = enriched.get("revenue_growth", 0) or 0
            for _w in _conf_warnings:
                if "DECLINING" in _w:
                    _iv_haircut *= 0.55   # revenue declining: cut IV 45%
                elif "spike" in _w.lower():
                    # Skip FCF spike haircut when revenue is structurally growing
                    # (e.g. NVDA: AI revenue surge is not a one-time item)
                    if _rev_growth_conf <= 0.40:
                        _iv_haircut *= 0.60   # genuine one-time FCF spike: cut IV 40%
                elif "decelerat" in _w.lower():
                    # Only haircut when growth has turned actually negative,
                    # not just slowing from high base (e.g. GOOGL maturing)
                    if _rev_growth_conf < 0:
                        _iv_haircut *= 0.80   # true revenue contraction: cut IV 20%
            if _iv_haircut < 1.0:
                iv_n_moat = iv_n_moat * _iv_haircut

            # Apply same moat + confidence adjustments to scenario IVs
            # so Bear/Base/Bull are consistent with the headline IV
            _moat_iv_delta  = moat_adj.get("iv_delta_pct", 0) / 100 if "moat_adj" in locals() else 0.0
            _moat_mult      = 1 + _moat_iv_delta
            _scenario_mult  = _moat_mult * _iv_haircut
            if _scenario_mult != 1.0:
                for _sname in scenarios:
                    scenarios[_sname]["iv"]      = scenarios[_sname]["iv"] * _scenario_mult
                    scenarios[_sname]["mos_pct"]  = margin_of_safety(
                        scenarios[_sname]["iv"], price_n) * 100
                    scenarios[_sname]["mos"]      = scenarios[_sname]["mos_pct"] / 100

            # Investment plan — use moat-adjusted IV so buy/target/SL reflect moat
            mos      = margin_of_safety(iv_n_moat, price_n)

            # Insider sentiment → small MoS nudge (10% weight)
            _insider_data = raw.get("finnhub_insider", {})
            _insider_sent = _insider_data.get("sentiment", "NEUTRAL")
            _INSIDER_ADJ  = {
                "STRONG BUY":  +0.04, "BUY": +0.02, "NEUTRAL": 0.0,
                "SELL": -0.02, "STRONG SELL": -0.04,
            }
            _insider_adj  = _INSIDER_ADJ.get(_insider_sent, 0.0)

            sig      = assign_signal(mos, dcf_res.get("suspicious", False), forecast_result.get("reliable", True), _insider_adj)
            inv_plan = generate_investment_plan(enriched, price_n, iv_n_moat, mos)
            _show_action_plan = can("action_plan")

            # Keep original iv_n for DCF display, use iv_n_moat for targets
            iv_n = iv_n_moat

            # MC
            mc_result = {}
            if run_mc:
                mc_result = monte_carlo_valuation(
                    enriched=enriched, forecaster=forecaster,
                    total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                    shares_outstanding=enriched["shares"], current_price=price_n, base_wacc=wacc,
                )

        # FX
        native_ccy = raw.get("native_ccy", "USD")
        fx = get_fx_rate(native_ccy, to_code)
        price_d = price_n * fx
        iv_d    = iv_n    * fx
        proj_d  = [v * fx for v in projected]
        pv_fcfs_d = [v * fx for v in dcf_res.get("pv_fcfs", [])]
        pv_tv_d   = dcf_res.get("pv_tv", 0) * fx

        # ── Save to session state for Financial Statements tab ─
        # ── End of fresh compute block ───────────────────────────

        # Store computed wacc/terminal_g INTO enriched for cache restore
        enriched["wacc_used"]      = wacc
        enriched["terminal_g_used"]= terminal_g
        enriched["wacc_source"]    = wacc_source
        # Live RF rate info — prefer from industry WACC (already adjusted),
        # fall back to CAPM wacc_data, then get directly from config cache
        _rf_info_store = (
            locals().get("_ind_info", {}).get("rf_rate_info")
            or wacc_data.get("rf_rate_info")
            or None
        )
        if _rf_info_store is None:
            try:
                _cfg_fetch_rf = _cfg_mod.fetch_risk_free_rate
                _is_ind = ticker_input.endswith(".NS") or ticker_input.endswith(".BO")
                _rf_info_store = _cfg_fetch_rf("india" if _is_ind else "us")
            except Exception:
                _rf_info_store = {}
        st.session_state["_rf_rate_info"] = _rf_info_store
        st.session_state["fin_enriched"]  = enriched
        st.session_state["fin_ticker"]    = ticker_input
        st.session_state["fin_fx"]        = fx
        st.session_state["fin_to_code"]   = to_code
        st.session_state["fin_sym"]       = sym
        st.session_state["fin_raw"]       = raw
        # Clear progress card
        if "_prog_ph" in dir():
            try:
                _prog_ph.empty()
            except Exception:
                pass
        # Save all computed vars so redisplay works after rerun
        st.session_state["_dcf_res"]       = dcf_res
        st.session_state["_mc_result"]      = st.session_state.get("_mc_result", {})
        st.session_state["_forecast_result"]= forecast_result
        st.session_state["_scenarios"]      = scenarios
        st.session_state["_inv_plan"]       = inv_plan
        st.session_state["_confidence"]     = confidence
        st.session_state["_price_hist"]     = price_hist
        st.session_state["_wacc_data"]      = wacc_data
        st.session_state["_use_auto_wacc"]  = use_auto_wacc
        st.session_state["_fx_rate"]        = fx_rate if "fx_rate" in dir() else 1.0
        st.session_state["_forecast_yrs"]   = forecast_yrs
        st.session_state["_terminal_pct"]   = terminal_pct
        st.session_state["_insider_adj"]    = _insider_adj

        # Use human language signal helper for colors
        _h_label_m, sig_fg, sig_bg, sig_bd = sig_human(sig)
        mos_pct   = mos * 100
        mos_color = "#0D7A4E" if mos_pct > 20 else "#B8972A" if mos_pct > 0 else "#A62020"
        st.session_state["fin_mos_pct"] = mos_pct
        st.session_state["fin_signal"]  = sig

        # ── Success micro-animation (only on fresh analysis, not cache) ──
        if not _from_cache:
            if "Undervalued" in sig or "Near Fair" in sig:
                st.markdown("<style>.main .block-container{animation:yiq-flash-green 1.8s ease-out;}</style>", unsafe_allow_html=True)
            elif "Overvalued" in sig:
                st.markdown("<style>.main .block-container{animation:yiq-flash-red 1.8s ease-out;}</style>", unsafe_allow_html=True)
        st.session_state["fin_iv_d"]    = iv_d
        # ── Push to Morning Brief history ─────────────────────
        _mb_name = enriched.get("company_name", ticker_input) or ticker_input
        push_analysis_to_history(ticker_input, _mb_name, price_d, iv_d, mos_pct, sig)
        st.session_state["_show_morning_brief"] = False   # show results, not brief
        # ── Analytics tracking ────────────────────────────────
        track_analysis(
            user_email=st.session_state.get("auth_email", ""),
            tier=tier(),
            ticker=ticker_input,
            signal=sig,
            mos_pct=mos_pct,
            wacc=wacc,
        )
        # ── Safe harbor ────────────────────────────────────
        st.caption(
            "All outputs are generated by a quantitative "
            "model using publicly available data. "
            "Past model accuracy does not predict "
            "future results. Not investment advice."
        )
        # ── VERDICT CARD ──────────────────────────────────
        _co_name = enriched.get("company_name", ticker_input)
        _fcf_raw = enriched.get("latest_fcf", 0) or 0
        _fcf_str = (f"{sym}{_fcf_raw/1e9:.0f}B" if abs(_fcf_raw) > 1e9
                    else f"{sym}{_fcf_raw/1e6:.0f}M")
        _fcf_g   = (enriched.get("fcf_growth", 0) or 0) * 100

        # Use iv_d (moat-adjusted DCF fair value) as the single source of truth
        _display_iv  = iv_d
        _display_mos = mos_pct

        if _display_mos >= 10:
            _summary = (
                f"{_co_name} generates {_fcf_str} in annual free cash. "
                f"At {sym}{price_d:,.0f}, our model estimates the stock "
                f"trades {_display_mos:.0f}% below fair value of {sym}{_display_iv:,.0f}. "
                f"FCF projected to grow {_fcf_g:.0f}% annually."
            )
        elif _display_mos >= -5:
            _summary = (
                f"{_co_name} generates {_fcf_str} in annual free cash. "
                f"At {sym}{price_d:,.0f}, the stock trades close to "
                f"the model\u2019s fair value of {sym}{_display_iv:,.0f}. "
                f"Thin margin of safety."
            )
        else:
            _summary = (
                f"{_co_name} generates {_fcf_str} in annual free cash. "
                f"At {sym}{price_d:,.0f}, the market prices in aggressive "
                f"growth. Model fair value: {sym}{_display_iv:,.0f} "
                f"\u2014 stock trades {abs(_display_mos):.0f}% above."
            )

        # Use actual YieldIQ score if computed later, otherwise estimate
        # Quick score estimate for verdict card (full score computed later)
        _ys_data = st.session_state.get("_yiq_score_data", {})
        _ys_comps = _ys_data.get("components", {})
        if not _ys_comps:
            # Estimate from available data
            _v_est = 40 if mos_pct >= 40 else 32 if mos_pct >= 25 else 22 if mos_pct >= 10 else 14 if mos_pct >= 0 else 7 if mos_pct >= -15 else 0
            _q_est = min(int((enriched.get("piotroski_score", 5) or 5) / 9 * 20) + 5, 30)
            _g_est = 20 if enriched.get("revenue_growth", 0) >= 0.20 else 15 if enriched.get("revenue_growth", 0) >= 0.10 else 10 if enriched.get("revenue_growth", 0) >= 0.05 else 5
            _s_est = 7
        else:
            _v_est = _ys_comps.get("Valuation (40pts)", 14)
            _q_est = _ys_comps.get("Business Quality (30pts)", 20)
            _g_est = _ys_comps.get("Growth (20pts)", 12)
            _s_est = _ys_comps.get("Sentiment (10pts)", 6)
        _breakdown = {
            "valuation": _v_est, "quality": _q_est,
            "growth": _g_est, "sentiment": _s_est,
        }

        # ── VALUATION HERO (new primary component) ────────
        _bear_iv = st.session_state.get("_scenarios", {}).get("Bear case", {}).get("iv", _display_iv * 0.7 / fx if fx else 0) * fx
        _bull_iv = st.session_state.get("_scenarios", {}).get("Bull case", {}).get("iv", _display_iv * 1.4 / fx if fx else 0) * fx
        _rev_g = enriched.get("revenue_growth", 0) * 100
        _fcf_m = enriched.get("op_margin", 0) * 100
        _conf_score = st.session_state.get("_confidence", {}).get("score", 70)
        _valuation_hero(
            ticker=ticker_input, company=_co_name,
            sector=enriched.get("sector_name", ""),
            price=float(price_d), fair_value=float(_display_iv),
            mos_pct=float(_display_mos), confidence=int(_conf_score),
            bear_iv=float(_bear_iv), bull_iv=float(_bull_iv),
            rev_growth=float(_rev_g), fcf_margin=float(_fcf_m),
            wacc=float(wacc * 100), terminal_g=float(terminal_g * 100),
            sym=sym,
        )

        # ═══════════════════════════════════════════════════
        # LAYER 1 — INSTANT VERDICT (above the fold)
        # Conviction Ring + AI Summary + Action Bar
        # ═══════════════════════════════════════════════════
        _layer1_c1, _layer1_c2 = st.columns([1, 3])
        with _layer1_c1:
            try:
                from ui.components.conviction_ring import render_conviction_ring
                _yiq_score = st.session_state.get("_yiq_score_data", {}).get("score", 50)
                render_conviction_ring(
                    yieldiq_score=int(_yiq_score),
                    confidence_score=int(_conf_score),
                )
            except Exception:
                pass

        with _layer1_c2:
            # AI Summary
            try:
                from ui.components.ai_summary import render_ai_summary
                _moat_g = enriched.get("moat_grade", "None") or "None"
                _fcf_g_pct = enriched.get("fcf_growth", 0) * 100
                render_ai_summary(
                    ticker=ticker_input,
                    company_name=_co_name,
                    mos=float(_display_mos),
                    moat=_moat_g,
                    fcf_growth=float(_fcf_g_pct),
                    confidence=int(_conf_score),
                )
            except Exception:
                pass

        # Action Bar
        try:
            from ui.components.action_bar import render_action_bar
            render_action_bar(ticker=ticker_input, current_price=float(price_d))
        except Exception:
            pass

        st.markdown("---")

        # ═══════════════════════════════════════════════════
        # LAYER 2 — THE STORY (first scroll)
        # Insight cards providing context
        # ═══════════════════════════════════════════════════

        # ── Learn Mode tips for Layer 1 ──────────────────
        try:
            from utils.learn_mode import learn_tip
            learn_tip("score")
            learn_tip("mos")
            learn_tip("confidence")
        except Exception:
            pass

        # ── MARKET MOOD (is the market expensive?) ──────
        _nifty_pe = 0
        try:
            import yfinance as _yf_mm
            _nifty = _yf_mm.Ticker("^NSEI")
            _nifty_info = _nifty.info
            _nifty_pe = _nifty_info.get("trailingPE", 0) or 0
        except Exception:
            pass
        if _nifty_pe > 0:
            if _nifty_pe > 25:
                _mm_icon, _mm_label, _mm_color = "🔴", "Market looks expensive", "#DC2626"
                _mm_msg = f"NIFTY 50 P/E is {_nifty_pe:.1f}x — above historical average (~22x). Valuations are stretched."
            elif _nifty_pe > 20:
                _mm_icon, _mm_label, _mm_color = "🟡", "Market fairly valued", "#D97706"
                _mm_msg = f"NIFTY 50 P/E is {_nifty_pe:.1f}x — near historical average. Neither cheap nor expensive."
            else:
                _mm_icon, _mm_label, _mm_color = "🟢", "Market looks cheap", "#059669"
                _mm_msg = f"NIFTY 50 P/E is {_nifty_pe:.1f}x — below historical average. Could be a good time to find bargains."
            st.html(
                f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:10px 20px;margin-bottom:12px;display:flex;align-items:center;gap:12px;">'
                f'<span style="font-size:16px;">{_mm_icon}</span>'
                f'<div style="font-size:11px;color:#64748B;">'
                f'<strong style="color:{_mm_color};">{_mm_label}</strong> · {_mm_msg}</div>'
                f'</div>'
            )

        # ── YIELDIQ QUICK SCORE (aggregated) ─────────────
        _qs_value = max(0, min(100, (_display_mos + 40) / 80 * 100))
        _qs_quality = max(0, min(100, (_piotroski / 9) * 100)) if enriched.get("piotroski_score") else 50
        _qs_growth = max(0, min(100, ((enriched.get("revenue_growth", 0) * 100 + 20) / 60 * 50 +
                                       (enriched.get("fcf_growth", 0) * 100 + 20) / 60 * 50)))
        _qs_total = int((_qs_value * 0.4 + _qs_quality * 0.3 + _qs_growth * 0.3))
        _qs_total = max(0, min(100, _qs_total))

        if _qs_total >= 75:
            _qs_color, _qs_bg, _qs_label = "#059669", "#F0FDF4", "Strong Opportunity"
        elif _qs_total >= 55:
            _qs_color, _qs_bg, _qs_label = "#1D4ED8", "#EFF6FF", "Worth Investigating"
        elif _qs_total >= 35:
            _qs_color, _qs_bg, _qs_label = "#D97706", "#FFFBEB", "Mixed Signals"
        else:
            _qs_color, _qs_bg, _qs_label = "#DC2626", "#FEF2F2", "Proceed With Caution"

        st.html(
            f'<div style="background:{_qs_bg};border:2px solid {_qs_color}30;border-radius:14px;'
            f'padding:16px 20px;margin-bottom:12px;display:flex;align-items:center;gap:16px;">'
            f'<div style="text-align:center;min-width:70px;">'
            f'<div style="font-size:36px;font-weight:900;color:{_qs_color};'
            f'font-family:IBM Plex Mono,monospace;line-height:1;">{_qs_total}</div>'
            f'<div style="font-size:9px;color:{_qs_color};opacity:0.7;">/100</div></div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;font-weight:700;color:{_qs_color};margin-bottom:4px;">'
            f'{_qs_label}</div>'
            f'<div style="display:flex;gap:12px;font-size:10px;color:#64748B;">'
            f'<span>Value: {_qs_value:.0f}</span>'
            f'<span>Quality: {_qs_quality:.0f}</span>'
            f'<span>Growth: {_qs_growth:.0f}</span></div>'
            f'</div>'
            f'<div style="font-size:10px;color:#94A3B8;text-align:right;">'
            f'Model output only<br>Not investment advice</div>'
            f'</div>'
        )

        # ── ONE-LINE VERDICT ──────────────────────────────
        if _display_mos > 30:
            _verdict_txt = f"Our model estimates this stock trades significantly below fair value — {_display_mos:.0f}% margin of safety."
            _verdict_clr, _verdict_bg = "#065F46", "#ECFDF5"
        elif _display_mos > 10:
            _verdict_txt = f"Stock appears to trade below estimated fair value by {_display_mos:.0f}%."
            _verdict_clr, _verdict_bg = "#16A34A", "#F0FDF4"
        elif _display_mos > -10:
            _verdict_txt = f"Stock trades near our estimated fair value ({_display_mos:+.0f}%)."
            _verdict_clr, _verdict_bg = "#D97706", "#FFFBEB"
        elif _display_mos > -30:
            _verdict_txt = f"Stock appears to trade above estimated fair value by {abs(_display_mos):.0f}%."
            _verdict_clr, _verdict_bg = "#DC2626", "#FEF2F2"
        else:
            _verdict_txt = f"Stock trades significantly above our model estimate — {abs(_display_mos):.0f}% premium."
            _verdict_clr, _verdict_bg = "#991B1B", "#FEF2F2"
        st.html(
            f'<div style="background:{_verdict_bg};border-left:4px solid {_verdict_clr};'
            f'border-radius:0 12px 12px 0;padding:12px 20px;margin-bottom:12px;">'
            f'<div style="font-size:13px;color:{_verdict_clr};font-weight:600;line-height:1.5;">'
            f'{_verdict_txt}</div>'
            f'<div style="font-size:10px;color:#94A3B8;margin-top:2px;">'
            f'Model output only — not investment advice</div></div>'
        )

        # ── PATIENCE METER ─────────────────────────────────
        if _display_mos > 0 and enriched.get("revenue_growth", 0) > 0:
            _rev_g_annual = enriched.get("revenue_growth", 0)
            _years_to_fv = abs(_display_mos) / (_rev_g_annual * 100) if _rev_g_annual > 0 else 99
            _years_to_fv = min(_years_to_fv, 10)
            if _years_to_fv < 2:
                _patience_color, _patience_label = "#059669", "Short wait"
                _patience_msg = f"At current growth ({_rev_g_annual*100:.0f}%/yr), the stock could reach fair value in ~{_years_to_fv:.1f} years."
            elif _years_to_fv < 5:
                _patience_color, _patience_label = "#D97706", "Moderate patience needed"
                _patience_msg = f"At current growth, reaching fair value may take ~{_years_to_fv:.0f} years. Good for medium-term investors."
            else:
                _patience_color, _patience_label = "#DC2626", "Long-term play"
                _patience_msg = f"Current growth suggests {_years_to_fv:.0f}+ years to reach fair value. Suitable for very patient investors only."
            st.html(f"""
            <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                        padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;gap:16px;
                        box-shadow:0 1px 3px rgba(0,0,0,0.04);">
              <div style="font-size:24px;">⏳</div>
              <div style="flex:1;">
                <div style="font-size:11px;font-weight:700;color:{_patience_color};
                            text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">
                  {_patience_label}</div>
                <div style="font-size:12px;color:#475569;line-height:1.5;">
                  {_patience_msg}</div>
              </div>
              <div style="text-align:right;">
                <div style="font-size:22px;font-weight:800;color:{_patience_color};
                            font-family:'IBM Plex Mono',monospace;">~{_years_to_fv:.1f}yr</div>
              </div>
            </div>
            """)

        # ── RED FLAG SCANNER ─────────────────────────────
        _red_flags = []
        _rev_g = enriched.get("revenue_growth", 0)
        _fcf_g = enriched.get("fcf_growth", 0)
        _op_margin = enriched.get("op_margin", 0)
        _de_ratio = enriched.get("debt_to_equity", 0) or 0
        _piotroski = enriched.get("piotroski_score", 5) or 5

        # Revenue growing but FCF shrinking
        if _rev_g > 0.05 and _fcf_g < -0.05:
            _red_flags.append(("Revenue growing but cash flow shrinking", "Revenue is up but free cash flow is declining — could indicate aggressive accounting or rising costs eating profits."))

        # High debt relative to equity
        if _de_ratio > 2.0:
            _red_flags.append(("High debt levels", f"Debt-to-equity ratio is {_de_ratio:.1f}x — significantly above healthy levels. High leverage increases risk of financial distress."))

        # Low Piotroski score
        if _piotroski <= 3:
            _red_flags.append(("Weak financial health", f"Piotroski F-Score is {_piotroski}/9 — indicates deteriorating fundamentals. Only 3 of 9 accounting signals are positive."))

        # Negative operating margin
        if _op_margin < 0:
            _red_flags.append(("Negative operating margins", f"Operating margin is {_op_margin*100:.1f}% — the company is losing money on its core operations."))

        # Revenue declining
        if _rev_g < -0.10:
            _red_flags.append(("Declining revenue", f"Revenue shrank {abs(_rev_g)*100:.0f}% — a significant contraction that could signal structural problems."))

        # "Too Good To Be True" — stock looks cheap but has hidden issues
        if _display_mos > 30 and _piotroski <= 4:
            _red_flags.append(("Cheap but weak fundamentals", "Stock appears significantly undervalued but has weak financial health. Cheap stocks are sometimes cheap for a reason — verify the business fundamentals."))

        # Insider selling while stock looks undervalued
        _ins_data = (raw or {}).get("finnhub_insider", {})
        _ins_net = _ins_data.get("net_shares_90d", 0) if isinstance(_ins_data, dict) else 0
        if _display_mos > 15 and _ins_net < -100000:
            _red_flags.append(("Insiders selling while stock looks undervalued", "Company executives are selling shares even though the model shows the stock is undervalued. Insiders may know something the market doesn't."))

        # Earnings growing but operating cash flow flat/declining
        _ocf_growth = enriched.get("ocf_growth", 0) or 0
        _ni_growth = enriched.get("ni_growth", 0) or 0
        if _ni_growth > 0.10 and _ocf_growth < 0:
            _red_flags.append(("Earnings growing but cash flow declining", f"Net income grew {_ni_growth*100:.0f}% but operating cash flow shrank. This divergence could indicate accounting manipulation or unsustainable growth."))

        if _red_flags:
            _flag_html = ""
            for _title, _desc in _red_flags:
                _flag_html += (
                    f'<div style="display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #FEE2E2;">'
                    f'<span style="color:#DC2626;font-size:16px;flex-shrink:0;">🚩</span>'
                    f'<div><div style="font-size:12px;font-weight:700;color:#991B1B;">{_title}</div>'
                    f'<div style="font-size:11px;color:#7F1D1D;line-height:1.5;margin-top:2px;">{_desc}</div></div></div>'
                )
            st.html(f"""
            <div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:12px;
                        padding:16px 20px;margin-bottom:12px;">
              <div style="font-size:11px;font-weight:700;color:#991B1B;
                          text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;
                          font-family:'IBM Plex Mono',monospace;">
                🚩 Red Flag Scanner — {len(_red_flags)} Warning{'s' if len(_red_flags) > 1 else ''} Detected</div>
              {_flag_html}
              <div style="font-size:10px;color:#B91C1C;margin-top:8px;">
                Red flags are data observations, not recommendations. Always do your own research.</div>
            </div>
            """)
        else:
            st.html("""
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;
                        padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">
              <span style="font-size:16px;">✅</span>
              <div style="font-size:12px;color:#166534;">
                <strong>No red flags detected.</strong> Financial indicators appear healthy based on available data.</div>
            </div>
            """)

        # ── RISK-REWARD RATIO ────────────────────────────
        _bear_iv_rr = st.session_state.get("_scenarios", {}).get("Bear case", {}).get("iv", 0) * fx
        _bull_iv_rr = st.session_state.get("_scenarios", {}).get("Bull case", {}).get("iv", 0) * fx
        if _bear_iv_rr > 0 and _bull_iv_rr > 0 and price_d > 0:
            _downside = abs(price_d - _bear_iv_rr)
            _upside = abs(_bull_iv_rr - price_d)
            _rr_ratio = _upside / _downside if _downside > 0 else 0
            if _rr_ratio >= 3:
                _rr_color, _rr_label = "#059669", "Excellent"
                _rr_msg = f"For every ₹1 of downside risk, there's ₹{_rr_ratio:.1f} of potential upside. Strongly favourable risk-reward."
            elif _rr_ratio >= 2:
                _rr_color, _rr_label = "#16A34A", "Good"
                _rr_msg = f"Risk-reward ratio of {_rr_ratio:.1f}:1 — upside potential outweighs downside risk."
            elif _rr_ratio >= 1:
                _rr_color, _rr_label = "#D97706", "Balanced"
                _rr_msg = f"Risk-reward ratio of {_rr_ratio:.1f}:1 — upside and downside are roughly balanced."
            else:
                _rr_color, _rr_label = "#DC2626", "Unfavourable"
                _rr_msg = f"Risk-reward ratio of {_rr_ratio:.1f}:1 — downside risk exceeds upside potential at current prices."

            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;gap:16px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="text-align:center;min-width:60px;">'
                f'<div style="font-size:22px;font-weight:900;color:{_rr_color};'
                f'font-family:IBM Plex Mono,monospace;">{_rr_ratio:.1f}:1</div>'
                f'<div style="font-size:9px;color:#94A3B8;text-transform:uppercase;'
                f'letter-spacing:0.06em;">Risk/Reward</div></div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_rr_color};'
                f'margin-bottom:2px;">{_rr_label} Risk-Reward</div>'
                f'<div style="font-size:11px;color:#475569;line-height:1.5;">{_rr_msg}</div>'
                f'</div>'
                f'<div style="text-align:right;font-size:10px;color:#94A3B8;line-height:1.6;">'
                f'Upside: {sym}{_upside:,.0f}<br>Downside: {sym}{_downside:,.0f}</div>'
                f'</div>'
            )

        # ── EMOTIONAL BIAS DETECTOR ──────────────────────
        try:
            from portfolio import is_in_watchlist, is_in_portfolio
            _owns_stock = is_in_portfolio(ticker_input) or is_in_watchlist(ticker_input)
            if _owns_stock and _display_mos < -10:
                st.html(
                    '<div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:12px;'
                    'padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;">'
                    '<div style="font-size:24px;">🧠</div>'
                    '<div style="flex:1;">'
                    '<div style="font-size:12px;font-weight:700;color:#9A3412;margin-bottom:2px;">'
                    'Bias Check — You own this stock</div>'
                    '<div style="font-size:11px;color:#7C2D12;line-height:1.5;">'
                    'Our model suggests this stock trades above estimated fair value, but you already '
                    'own it. Research shows investors rate stocks they own 40% more favourably. '
                    'Consider whether your analysis is objective.</div>'
                    '</div></div>'
                )
            elif _owns_stock and _display_mos > 20:
                st.html(
                    '<div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;'
                    'padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;">'
                    '<div style="font-size:24px;">🧠</div>'
                    '<div style="flex:1;">'
                    '<div style="font-size:12px;font-weight:700;color:#166534;margin-bottom:2px;">'
                    'Bias Check — Conviction confirmed</div>'
                    '<div style="font-size:11px;color:#14532D;line-height:1.5;">'
                    'You own this stock and our model agrees — it appears to trade below estimated fair value. '
                    'Your conviction aligns with the data.</div>'
                    '</div></div>'
                )
        except Exception:
            pass

        # ── VALUATION TREND (is it getting cheaper?) ─────
        _52w_high = ((raw or {}).get("fh_52w_high", 0) or 0) * fx
        _52w_low = ((raw or {}).get("fh_52w_low", 0) or 0) * fx
        if _52w_high > 0 and _52w_low > 0 and iv_d > 0:
            _price_range_pct = ((price_d - _52w_low) / (_52w_high - _52w_low) * 100) if (_52w_high - _52w_low) > 0 else 50
            _mos_at_high = ((iv_d - _52w_high) / _52w_high * 100) if _52w_high > 0 else 0
            _mos_at_low = ((iv_d - _52w_low) / _52w_low * 100) if _52w_low > 0 else 0

            if _price_range_pct < 25:
                _trend_icon, _trend_label = "📉", "Near 52-week low"
                _trend_color = "#059669"
                _trend_msg = f"Stock is near its 52-week low ({sym}{_52w_low:,.0f}). At the low, margin of safety would be {_mos_at_low:+.0f}%."
            elif _price_range_pct > 75:
                _trend_icon, _trend_label = "📈", "Near 52-week high"
                _trend_color = "#DC2626"
                _trend_msg = f"Stock is near its 52-week high ({sym}{_52w_high:,.0f}). At the high, margin of safety would be {_mos_at_high:+.0f}%."
            else:
                _trend_icon, _trend_label = "➡️", "Mid-range"
                _trend_color = "#64748B"
                _trend_msg = f"Trading in the middle of its 52-week range ({sym}{_52w_low:,.0f} — {sym}{_52w_high:,.0f})."

            _bar_pct = max(2, min(98, _price_range_pct))
            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:14px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
                f'<span style="font-size:20px;">{_trend_icon}</span>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_trend_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;">{_trend_label}</div>'
                f'<div style="font-size:11px;color:#64748B;">{_trend_msg}</div>'
                f'</div></div>'
                f'<div style="position:relative;height:8px;background:#F1F5F9;border-radius:4px;">'
                f'<div style="position:absolute;height:100%;width:{_bar_pct:.0f}%;'
                f'background:linear-gradient(90deg,#22C55E,#EAB308,#DC2626);border-radius:4px;"></div>'
                f'<div style="position:absolute;top:-3px;left:{_bar_pct:.0f}%;transform:translateX(-50%);'
                f'width:14px;height:14px;background:#0F172A;border-radius:50%;border:2px solid white;"></div>'
                f'</div>'
                f'<div style="display:flex;justify-content:space-between;margin-top:4px;">'
                f'<span style="font-size:9px;color:#94A3B8;">52W Low: {sym}{_52w_low:,.0f}</span>'
                f'<span style="font-size:9px;color:#94A3B8;">52W High: {sym}{_52w_high:,.0f}</span>'
                f'</div></div>'
            )

        # ── DIVIDEND INSIGHT ──────────────────────────────
        _div_yield = enriched.get("dividend_yield", 0) or 0
        _div_rate = (raw or {}).get("dividend_rate", 0) or 0
        if _div_yield > 0.005:  # more than 0.5%
            _div_pct = _div_yield * 100
            _fd_10y = (raw or {}).get("fh_10y_yield", 0) or 0.07  # India 10Y ~7%
            _div_vs_bond = "above" if _div_pct > _fd_10y * 100 else "below"
            _div_icon = "💰" if _div_pct > 3 else "📈"
            st.html(
                f'<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:12px;'
                f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;">'
                f'<div style="font-size:20px;">{_div_icon}</div>'
                f'<div style="flex:1;font-size:12px;color:#92400E;">'
                f'Dividend yield: <strong>{_div_pct:.2f}%</strong>'
                f' ({_div_vs_bond} the risk-free rate) · '
                f'Annual dividend: {sym}{_div_rate * fx:,.2f} per share'
                f'</div></div>'
            )

        # ── OWNERSHIP BREAKDOWN ──────────────────────────
        _inst_pct = enriched.get("institutional_pct", 0) or 0
        _insider_pct = enriched.get("insider_pct", 0) or 0
        if _inst_pct > 0 or _insider_pct > 0:
            _retail_pct = max(0, 100 - _inst_pct - _insider_pct)
            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:14px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:11px;font-weight:700;color:#94A3B8;'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;'
                f'font-family:IBM Plex Mono,monospace;">Ownership Breakdown</div>'
                f'<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin-bottom:8px;">'
                f'<div style="width:{_inst_pct:.0f}%;background:#1D4ED8;" title="Institutional {_inst_pct:.0f}%"></div>'
                f'<div style="width:{_insider_pct:.0f}%;background:#059669;" title="Insider {_insider_pct:.0f}%"></div>'
                f'<div style="width:{_retail_pct:.0f}%;background:#E2E8F0;" title="Retail {_retail_pct:.0f}%"></div>'
                f'</div>'
                f'<div style="display:flex;gap:16px;font-size:10px;color:#64748B;">'
                f'<span>🔵 Institutional {_inst_pct:.0f}%</span>'
                f'<span>🟢 Insider {_insider_pct:.0f}%</span>'
                f'<span>⚪ Retail {_retail_pct:.0f}%</span>'
                f'</div></div>'
            )

        # ── GROWTH RUNWAY ────────────────────────────────
        _rev_growth_pct = (enriched.get("revenue_growth", 0) or 0) * 100
        _fcf_growth_pct = (enriched.get("fcf_growth", 0) or 0) * 100
        _avg_growth = (_rev_growth_pct + _fcf_growth_pct) / 2
        if abs(_avg_growth) > 0.5:
            if _avg_growth > 20:
                _gr_icon, _gr_label, _gr_color = "🚀", "Hypergrowth", "#059669"
                _gr_msg = f"Revenue {_rev_growth_pct:+.0f}%, FCF {_fcf_growth_pct:+.0f}% — the company is growing rapidly. Typically commands a premium valuation."
            elif _avg_growth > 8:
                _gr_icon, _gr_label, _gr_color = "📈", "Strong Growth", "#16A34A"
                _gr_msg = f"Revenue {_rev_growth_pct:+.0f}%, FCF {_fcf_growth_pct:+.0f}% — healthy growth trajectory. The business is expanding consistently."
            elif _avg_growth > 2:
                _gr_icon, _gr_label, _gr_color = "➡️", "Stable Growth", "#64748B"
                _gr_msg = f"Revenue {_rev_growth_pct:+.0f}%, FCF {_fcf_growth_pct:+.0f}% — mature business with stable, predictable growth."
            elif _avg_growth > -5:
                _gr_icon, _gr_label, _gr_color = "⚠️", "Stagnating", "#D97706"
                _gr_msg = f"Revenue {_rev_growth_pct:+.0f}%, FCF {_fcf_growth_pct:+.0f}% — growth is slowing or flat. The company may need reinvention."
            else:
                _gr_icon, _gr_label, _gr_color = "📉", "Declining", "#DC2626"
                _gr_msg = f"Revenue {_rev_growth_pct:+.0f}%, FCF {_fcf_growth_pct:+.0f}% — the business is contracting. Value trap risk."

            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:20px;">{_gr_icon}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_gr_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">{_gr_label}</div>'
                f'<div style="font-size:11px;color:#475569;line-height:1.5;">{_gr_msg}</div>'
                f'</div></div>'
            )

        # ── MANAGEMENT EFFECTIVENESS ─────────────────────
        _roe = enriched.get("roe", 0) or 0
        _roce = enriched.get("roce", 0) or 0
        if _roe > 0:
            if _roe > 0.20:
                _mgmt_icon, _mgmt_label, _mgmt_color = "🏆", "Excellent Management", "#059669"
                _mgmt_msg = f"ROE of {_roe*100:.1f}% — management generates exceptional returns on shareholder equity."
            elif _roe > 0.12:
                _mgmt_icon, _mgmt_label, _mgmt_color = "👍", "Good Management", "#16A34A"
                _mgmt_msg = f"ROE of {_roe*100:.1f}% — management delivers solid returns above cost of equity."
            elif _roe > 0.06:
                _mgmt_icon, _mgmt_label, _mgmt_color = "➡️", "Average Management", "#D97706"
                _mgmt_msg = f"ROE of {_roe*100:.1f}% — returns are moderate. Management is not destroying value but not creating much either."
            else:
                _mgmt_icon, _mgmt_label, _mgmt_color = "👎", "Below Average", "#DC2626"
                _mgmt_msg = f"ROE of {_roe*100:.1f}% — returns below cost of equity. Management may be destroying shareholder value."

            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:20px;">{_mgmt_icon}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_mgmt_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">{_mgmt_label}</div>'
                f'<div style="font-size:11px;color:#475569;line-height:1.5;">{_mgmt_msg}</div>'
                f'</div></div>'
            )

        # ── CASH GENERATION QUALITY ──────────────────────
        _latest_fcf = enriched.get("latest_fcf", 0) or 0
        _latest_ni = enriched.get("latest_net_income", 0) or enriched.get("net_income", 0) or 0
        if _latest_fcf != 0 and _latest_ni != 0:
            _fcf_ni_ratio = _latest_fcf / _latest_ni if _latest_ni != 0 else 0
            if _fcf_ni_ratio > 1.2:
                _cq_icon, _cq_label, _cq_color = "💎", "Excellent Cash Conversion", "#059669"
                _cq_msg = f"FCF is {_fcf_ni_ratio:.1f}x net income — the company generates more cash than it reports as profit. High-quality earnings."
            elif _fcf_ni_ratio > 0.8:
                _cq_icon, _cq_label, _cq_color = "✅", "Good Cash Conversion", "#16A34A"
                _cq_msg = f"FCF is {_fcf_ni_ratio:.1f}x net income — cash earnings closely match reported profits. Healthy sign."
            elif _fcf_ni_ratio > 0.4:
                _cq_icon, _cq_label, _cq_color = "⚠️", "Moderate Cash Conversion", "#D97706"
                _cq_msg = f"FCF is only {_fcf_ni_ratio:.1f}x net income — a significant portion of reported profits isn't converting to cash. Watch for rising receivables or inventory."
            else:
                _cq_icon, _cq_label, _cq_color = "🚨", "Weak Cash Conversion", "#DC2626"
                _cq_msg = f"FCF is {_fcf_ni_ratio:.1f}x net income — very little of reported earnings turns into actual cash. This is a red flag for earnings quality."

            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:20px;">{_cq_icon}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_cq_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">{_cq_label}</div>'
                f'<div style="font-size:11px;color:#475569;line-height:1.5;">{_cq_msg}</div>'
                f'</div></div>'
            )

        # ── VOLATILITY INSIGHT ────────────────────────────
        _beta = (raw or {}).get("fh_beta", 0) or 0
        if _beta > 0:
            if _beta > 1.5:
                _vol_icon, _vol_label, _vol_color = "🌊", "High Volatility", "#DC2626"
                _vol_msg = f"Beta of {_beta:.2f} — this stock moves {(_beta-1)*100:.0f}% more than the market. Expect large swings. Not suitable for risk-averse investors."
            elif _beta > 1.1:
                _vol_icon, _vol_label, _vol_color = "📊", "Above Average Volatility", "#D97706"
                _vol_msg = f"Beta of {_beta:.2f} — slightly more volatile than the market. Moderate risk."
            elif _beta > 0.8:
                _vol_icon, _vol_label, _vol_color = "🛡️", "Average Volatility", "#64748B"
                _vol_msg = f"Beta of {_beta:.2f} — moves roughly in line with the market. Standard risk profile."
            else:
                _vol_icon, _vol_label, _vol_color = "🏰", "Low Volatility", "#059669"
                _vol_msg = f"Beta of {_beta:.2f} — less volatile than the market. Defensive stock, lower risk."

            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:20px;">{_vol_icon}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_vol_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">{_vol_label}</div>'
                f'<div style="font-size:11px;color:#475569;line-height:1.5;">{_vol_msg}</div>'
                f'</div></div>'
            )

        # ── COMPETITIVE MOAT INSIGHT ─────────────────────
        _moat_grade = enriched.get("moat_grade", "None") or "None"
        _moat_types = enriched.get("moat_types", []) or []
        _moat_score = enriched.get("moat_score", 0) or 0
        if _moat_grade != "None" and _moat_score > 0:
            _moat_icons = {"Wide": "🏰", "Narrow": "🔒", "None": "⚠️"}
            _moat_colors = {"Wide": "#059669", "Narrow": "#D97706", "None": "#DC2626"}
            _m_icon = _moat_icons.get(_moat_grade, "🔒")
            _m_color = _moat_colors.get(_moat_grade, "#64748B")
            _moat_desc = " · ".join(_moat_types[:3]) if _moat_types else "Based on financial metrics"
            st.html(
                f'<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                f'padding:14px 20px;margin-bottom:12px;display:flex;align-items:center;gap:14px;'
                f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                f'<div style="font-size:28px;">{_m_icon}</div>'
                f'<div style="flex:1;">'
                f'<div style="font-size:11px;font-weight:700;color:{_m_color};'
                f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">'
                f'{_moat_grade} Moat · {_moat_score}/100</div>'
                f'<div style="font-size:11px;color:#475569;">{_moat_desc}</div>'
                f'</div></div>'
            )

        # ── SECTOR CONTEXT CARD ───────────────────────────
        _sector_name = enriched.get("sector_name", "") or enriched.get("sector", "")
        if _sector_name and _sector_name != "general":
            _sector_pe = enriched.get("sector_pe", 0) or 0
            _stock_pe = enriched.get("pe_ratio", 0) or (raw or {}).get("pe_ratio", 0) or 0
            if _stock_pe > 0 and _sector_pe > 0:
                _pe_vs = ((_stock_pe / _sector_pe) - 1) * 100
                _pe_label = "premium" if _pe_vs > 0 else "discount"
                _pe_color = "#DC2626" if _pe_vs > 20 else "#D97706" if _pe_vs > 0 else "#059669"
                st.html(
                    f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;'
                    f'padding:12px 20px;margin-bottom:12px;display:flex;align-items:center;gap:16px;">'
                    f'<div style="font-size:20px;">🏭</div>'
                    f'<div style="flex:1;font-size:12px;color:#475569;">'
                    f'<strong>{_sector_name}</strong> sector average P/E: {_sector_pe:.1f}x · '
                    f'This stock: {_stock_pe:.1f}x '
                    f'(<span style="color:{_pe_color};font-weight:700;">{abs(_pe_vs):.0f}% {_pe_label}</span>)'
                    f'</div></div>'
                )

        # ── SIMILAR STOCKS (quick links) ─────────────────
        _sector_key = enriched.get("sector", "general")
        _SECTOR_PEERS = {
            "it_services": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
            "fmcg": ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS"],
            "pharma": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "LUPIN.NS"],
            "auto_oem": ["TATAMOTORS.NS", "MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS"],
            "banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
            "oil_gas": ["RELIANCE.NS", "ONGC.NS", "IOC.NS", "BPCL.NS", "GAIL.NS"],
            "metals": ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "NMDC.NS"],
            "power": ["NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "ADANIGREEN.NS", "NHPC.NS"],
            "telecom": ["BHARTIARTL.NS", "IDEA.NS", "TTML.NS"],
            "cement": ["ULTRACEMCO.NS", "SHREECEM.NS", "AMBUJACEM.NS", "ACC.NS", "DALMIACEM.NS"],
        }
        _peers = _SECTOR_PEERS.get(_sector_key, [])
        _peers = [p for p in _peers if p.replace(".NS", "").replace(".BO", "").upper() != ticker_input.replace(".NS", "").replace(".BO", "").upper()][:4]
        if _peers:
            _peer_btns = "".join(
                f'<span style="display:inline-block;padding:4px 12px;background:#F1F5F9;'
                f'border:1px solid #E2E8F0;border-radius:6px;font-size:11px;font-weight:600;'
                f'color:#475569;margin-right:6px;">{p.replace(".NS","")}</span>'
                for p in _peers
            )
            st.html(
                f'<div style="margin-bottom:12px;">'
                f'<span style="font-size:10px;color:#94A3B8;text-transform:uppercase;'
                f'letter-spacing:0.08em;margin-right:8px;">Similar stocks:</span>'
                f'{_peer_btns}</div>'
            )

        # ── EARNINGS ALERT BADGE ─────────────────────────
        _next_earn = (raw or {}).get("next_earnings_date", "")
        if not _next_earn:
            try:
                _ec = (raw or {}).get("finnhub_earnings_calendar", [])
                if _ec:
                    _next_earn = _ec[0].get("date", "")
            except Exception:
                pass
        if _next_earn:
            from datetime import datetime as _dt_earn, timedelta
            try:
                _edt = _dt_earn.strptime(str(_next_earn)[:10], "%Y-%m-%d")
                _days = (_edt - _dt_earn.now()).days
                if 0 <= _days <= 30:
                    _eicon = "🔴" if _days <= 7 else "🟡" if _days <= 14 else "🔵"
                    st.html(
                        f'<div style="background:linear-gradient(90deg,#EFF6FF,#F0F9FF);'
                        f'border:1px solid #BFDBFE;border-radius:12px;padding:14px 20px;'
                        f'margin-bottom:12px;display:flex;align-items:center;gap:14px;">'
                        f'<div style="font-size:28px;">{_eicon}</div>'
                        f'<div style="flex:1;">'
                        f'<div style="font-size:12px;font-weight:700;color:#1E40AF;margin-bottom:2px;">'
                        f'Earnings in {_days} day{"s" if _days != 1 else ""}</div>'
                        f'<div style="font-size:11px;color:#475569;">'
                        f'Watch for price volatility around earnings · {_next_earn[:10]}</div>'
                        f'</div></div>'
                    )
            except Exception:
                pass

        # ═══════════════════════════════════════════════════
        # LAYER 3 — DEEP ANALYSIS (Snowflake + Tabs)
        # ═══════════════════════════════════════════════════

        # ── SNOWFLAKE RADAR (Simply Wall St-style) ───────
        _snowflake_chart(
            mos_pct=float(_display_mos),
            piotroski=int(enriched.get("piotroski_score", 5) or 5),
            rev_growth=float(enriched.get("revenue_growth", 0) * 100),
            fcf_growth=float(enriched.get("fcf_growth", 0) * 100),
            op_margin=float(enriched.get("op_margin", 0) * 100),
            debt_to_equity=float(enriched.get("debt_to_equity", 0) or 0),
            moat_score=float(enriched.get("moat_score", 0) or 0),
            ticker=ticker_input,
        )
        # ── END VERDICT CARD ─────────────────────────────

        mos_w     = min(max(abs(mos_pct), 2), 100)
        pt        = inv_plan["price_targets"]
        hp        = inv_plan["holding_period"]
        fs        = inv_plan["fundamental"]
        # Tier-based display flags
        _show_plan      = can("action_plan")
        _show_quality   = can("quality_score")
        _show_scenarios = can("scenarios")
        _show_sensitive = can("sensitivity")
        _show_mc        = can("monte_carlo")
        suspicious = dcf_res.get("suspicious", False)

        # ── Variables needed by Valuation tab (used to be set inside _sub_ov) ──
        years_labels         = [f"Y{i+1}" for i in range(forecast_yrs)]
        years                = forecast_yrs
        growth_schedule      = forecast_result.get("growth_schedule", [])
        base_growth          = forecast_result.get("base_growth", 0)
        fcf_base             = forecast_result.get("fcf_base", 0)
        projected_fcfs       = projected
        native_ccy           = raw.get("native_ccy", "USD")   if raw else "USD"
        company_name         = raw.get("company_name", ticker_input) if raw else ticker_input
        shares_outstanding   = enriched.get("shares", 0)
        shares               = shares_outstanding
        total_debt           = enriched.get("total_debt", 0)
        total_cash           = enriched.get("total_cash", 0)
        current_price        = enriched.get("price", 0)
        _sector              = enriched.get("sector", "general")
        sector               = _sector
        _pe_iv               = enriched.get("pe_iv", 0)
        moat_adj             = st.session_state.get("fin_moat_adj", {})
        iv_delta_pct         = moat_adj.get("iv_delta_pct", 0)
        mc_result            = st.session_state.get("_mc_result", {})
        pv_tv_d              = dcf_res.get("pv_tv", 0) * fx
        proj_d               = [v * fx for v in projected]
        pv_fcfs_d            = [v * fx for v in dcf_res.get("pv_fcfs", [])]
        if len(projected) > 0 and len(growth_schedule) > 0 and growth_schedule[0] > -1:
            fcf_base_for_scenarios = projected[0] / (1 + growth_schedule[0])
        else:
            fcf_base_for_scenarios = fcf_base if fcf_base > 0 else enriched.get("latest_fcf", 1e6)

        # ══════════════════════════════════════════════════
        # PILL NAVIGATION
        # ══════════════════════════════════════════════════
        # Stable keys (no emojis) prevent serialisation issues across Streamlit versions
        _pill_options = [
            ("⚡ Overview",          "overview"),
            ("💰 DCF Model",        "dcf_model"),
            ("📊 Financials",       "financials"),
            ("📡 Consensus",        "consensus"),
            ("🤖 Ask AI",           "ask_ai"),
        ]
        if "active_section" not in st.session_state:
            st.session_state["active_section"] = "overview"

        # Segmented control CSS
        st.html("""<style>
        /* Pill navigation — segmented control style */
        .pill-nav [data-testid="stHorizontalBlock"] {
            background: #F1F5F9; border-radius: 12px; padding: 4px; gap: 4px !important;
        }
        .pill-nav .stButton > button {
            border-radius: 8px !important; border: none !important;
            font-size: 12px !important; font-weight: 600 !important;
            font-family: Inter, sans-serif !important;
            padding: 10px 8px !important; transition: all 0.15s !important;
            box-shadow: none !important;
        }
        .pill-nav .stButton > button[kind="primary"] {
            background: #0F172A !important; color: #FFFFFF !important;
            box-shadow: 0 2px 8px rgba(15,23,42,0.15) !important;
        }
        .pill-nav .stButton > button[kind="secondary"] {
            background: transparent !important; color: #64748B !important;
        }
        .pill-nav .stButton > button[kind="secondary"]:hover {
            background: #E2E8F0 !important; color: #0F172A !important;
            transform: none !important; box-shadow: none !important;
        }
        </style>""")

        with st.container():
            st.html('<div class="pill-nav">')
            _cols = st.columns(len(_pill_options))
            for _i, (_pill_label, _pill_key) in enumerate(_pill_options):
                with _cols[_i]:
                    if st.button(
                        _pill_label,
                        key=f"pill_{_i}",
                        width="stretch",
                        type="primary" if st.session_state["active_section"] == _pill_key else "secondary",
                    ):
                        st.session_state["active_section"] = _pill_key
                        st.rerun()
            st.html('</div>')
        _active = st.session_state["active_section"]

        # ══════════════════════════════════════════════════════════
        # QUICK STATS STRIP — only show on Summary tab
        # ══════════════════════════════════════════════════════════
        if raw and enriched and _active == "overview":
            _qs_pe      = (raw.get("forward_pe")
                          or raw.get("pe_ratio")
                          or (raw.get("finnhub_financials") or {}).get("pe_ttm")
                          or 0)
            # Sanity check: calculate P/E from price and EPS if available
            _eps_ttm = (raw.get("trailing_eps") or
                       (raw.get("finnhub_financials") or {}).get("eps_ttm") or 0)
            _price_pe = raw.get("price", 0) or 0
            if _eps_ttm > 0 and _price_pe > 0:
                _calc_pe = _price_pe / _eps_ttm
                # If calculated PE is reasonable and different from API PE, prefer it
                if 1 < _calc_pe < 500 and abs(_calc_pe - (_qs_pe or 999)) > 5:
                    _qs_pe = _calc_pe
            _qs_eveb    = raw.get("ev_to_ebitda")
            _qs_beta    = raw.get("fh_beta")
            # Calculate div yield from rate/price for accuracy (APIs return inconsistent formats)
            _div_rate = raw.get("dividend_rate", 0) or 0
            _price_for_dy = raw.get("price", 0) or 0
            if _div_rate > 0 and _price_for_dy > 0:
                _qs_div = _div_rate / _price_for_dy  # decimal: 0.0097 = 0.97%
            else:
                _raw_dy = raw.get("dividend_yield") or raw.get("fh_div_yield") or 0
                # Normalize: if > 0.20 it's a percentage, convert to decimal
                _qs_div = _raw_dy / 100 if _raw_dy > 0.20 else _raw_dy
            _qs_hi52    = (raw.get("fh_52w_high") or 0) * fx
            _qs_lo52    = (raw.get("fh_52w_low")  or 0) * fx
            _qs_fcf_raw = raw.get("yahoo_fcf_ttm") or 0
            _qs_mktcap  = (price_n * enriched.get("shares", 0)) if price_n else 0
            _qs_fcf_yld = (
                _qs_fcf_raw / _qs_mktcap * 100
                if _qs_mktcap > 0 and _qs_fcf_raw else None
            )

            with st.container(border=True):
                _qs_cols = st.columns(4)

                # P/E
                with _qs_cols[0]:
                    _qs_pe_str = f"{_qs_pe:.1f}×" if (_qs_pe and 0 < _qs_pe < 500) else "—"
                    _tm = st.session_state.get("theme", "slate")
                    themed_metric("P/E", _qs_pe_str, theme_name=_tm)
                    try:
                        from utils.learn_mode import learn_tip
                        learn_tip("pe_ratio")
                    except Exception:
                        pass

                # EV/EBITDA
                with _qs_cols[1]:
                    _qs_eveb_str = f"{_qs_eveb:.1f}\u00d7" if (_qs_eveb and 0 < _qs_eveb < 300) else "\u2014"
                    themed_metric("EV/EBITDA", _qs_eveb_str, theme_name=_tm)
                    try:
                        from utils.learn_mode import learn_tip
                        learn_tip("ev_ebitda")
                    except Exception:
                        pass

                # Div Yield
                with _qs_cols[2]:
                    _qs_div_str = f"{_qs_div * 100:.1f}%" if _qs_div else "\u2014"
                    themed_metric("Div Yield", _qs_div_str, theme_name=_tm)

                # Piotroski F-Score
                with _qs_cols[3]:
                    from screener.piotroski import compute_piotroski_fscore
                    piotroski_result = compute_piotroski_fscore(enriched)
                    f_score = piotroski_result.get('score', 0)
                    f_emoji = piotroski_result.get('grade_emoji', '\u26a0\ufe0f')

                    if f_score and f_score > 0:
                        themed_metric("\U0001f4aa F-Score", f"{f_score}/9", delta=f_emoji, theme_name=_tm)
                    else:
                        themed_metric("\U0001f4aa F-Score", "\u2014", theme_name=_tm)

        if _active == "overview":
            # ══════════════════════════════════════════════════════════
            # MOMENTUM ANALYSIS SECTION
            # ══════════════════════════════════════════════════════════
            _mr = momentum_result if 'momentum_result' in locals() else {}
            if _mr.get('momentum_score', 0) > 0:
              with st.expander("\U0001f4ca Momentum Analysis", expanded=False):
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Component Breakdown:**")
                    components = _mr.get('components', {})
                    
                    price_trend = components.get('price_trend', 0)
                    st.progress(price_trend / 100, text=f"Price Trend: {price_trend}/100")
                    
                    volume_score = components.get('volume', 0)
                    st.progress(volume_score / 100, text=f"Volume: {volume_score}/100")
                    
                    rsi_score = components.get('rsi', 0)
                    st.progress(rsi_score / 100, text=f"RSI: {rsi_score}/100")
                    
                    ma_score = components.get('ma_strength', 0)
                    st.progress(ma_score / 100, text=f"MA Strength: {ma_score}/100")
                
                with col2:
                    st.write("**Technical Indicators:**")
                    indicators = _mr.get('indicators', {})
                    
                    rsi = indicators.get('rsi_14')
                    if rsi:
                        rsi_status = "🔥 Overbought" if rsi > 70 else "❄️ Oversold" if rsi < 30 else "✅ Neutral"
                        st.write(f"• RSI (14): **{rsi:.1f}** {rsi_status}")
                    
                    ma_20 = indicators.get('ma_20')
                    if ma_20:
                        st.write(f"• MA (20): **${ma_20:,.2f}**")
                    
                    ma_50 = indicators.get('ma_50')
                    if ma_50:
                        st.write(f"• MA (50): **${ma_50:,.2f}**")
                    
                    ma_200 = indicators.get('ma_200')
                    if ma_200:
                        st.write(f"• MA (200): **${ma_200:,.2f}**")
                    
                    # Golden Cross
                    if ma_20 and ma_50:
                        if ma_20 > ma_50:
                            st.success("✅ Golden Cross: MA20 > MA50")
                        else:
                            st.error("⚠️ Death Cross: MA20 < MA50")
                
                st.divider()

            # ══════════════════════════════════════════════════════════
            # SHARED PREP — values used across all 4 layers
            # ══════════════════════════════════════════════════════════
            if not enriched:
                st.warning("Analysis data unavailable. Please run a new analysis.")
                st.stop()

            _display_name  = company_name if 'company_name' in dir() and company_name else ticker_input
            _h_label, sig_fg, sig_bg, sig_bd = sig_human(sig)
            _fs_color_map  = {"STRONG":"#0D7A4E","GOOD":"#2563EB","AVERAGE":"#B8972A","WEAK":"#A62020"}
            _fs_color      = _fs_color_map.get(fs.get("grade",""), "#4A5E7A")
            _fs_label      = fs.get("grade","N/A")
            mos_color      = "#0D7A4E" if mos_pct > 20 else "#B8972A" if mos_pct > 0 else "#A62020"
            mos_w          = min(max(abs(mos_pct), 2), 100)

            # ── revenue/margin/growth helpers ─────────────────────────
            _rev_growth    = enriched.get("revenue_growth", 0) * 100
            _op_margin     = enriched.get("op_margin", 0) * 100
            _fcf_growth    = enriched.get("fcf_growth", 0) * 100
            _moat_grade    = enriched.get("moat_grade", "N/A")
            _moat_score    = enriched.get("moat_score", 0)
            _moat_types    = (" · ".join(enriched.get("moat_types", [])[:2]) or "No identifiable moat")
            _moat_summary  = enriched.get("moat_summary", "") or ""
            _conf_warnings = confidence.get("warnings", [])
            suspicious     = dcf_res.get("suspicious", False)

            # ── quality / growth / risk plain signals ─────────────────
            _qual_label = {"STRONG":"Strong","GOOD":"Good","AVERAGE":"Average","WEAK":"Weak"}.get(_fs_label,"—")
            _qual_color = _fs_color

            _growth_label = (
                "Improving"   if _rev_growth > 10 and _fcf_growth > 5 else
                "Stable"      if _rev_growth > 0  and _fcf_growth > -5 else
                "Declining"
            )
            _growth_color = (
                "#0D7A4E" if _growth_label == "Improving" else
                "#1D4ED8" if _growth_label == "Stable"    else "#B91C1C"
            )

            _risk_label = (
                "Lower"  if _op_margin > 20 and _moat_grade in ("Wide","Narrow") else
                "Higher" if _op_margin < 8  or suspicious else
                "Moderate"
            )
            _risk_color = (
                "#0D7A4E" if _risk_label == "Lower"   else
                "#B91C1C" if _risk_label == "Higher"  else "#B45309"
            )

            _val_label = (
                "Undervalued" if mos_pct > 10 else
                "Near model fair value" if mos_pct > -10 else
                "Overvalued"
            )
            _val_color = (
                "#0D7A4E" if _val_label == "Undervalued" else
                "#1D4ED8" if _val_label == "Near model fair value" else "#B91C1C"
            )

            # ── moat plain description ────────────────────────────────
            _moat_plain = {
                "Wide":   "Strong competitive advantage",
                "Narrow": "Some competitive advantage",
                "None":   "No clear competitive advantage",
            }.get(_moat_grade, "Competitive advantage unknown")

            # ── 📌 Add to Watchlist ───────────────────────────────
            _in_wl    = is_in_watchlist(ticker_input)
            _wl_label = " Already in Watchlist — click to update" if _in_wl else "📌 Add to Watchlist"
            with st.expander(_wl_label, expanded=False):
                _wl_c1, _wl_c2 = st.columns(2)
                with _wl_c1:
                    _wl_target = st.number_input(
                        "Model Alert Threshold",
                        value=float(round(iv_d, 2)),
                        min_value=0.0,
                        step=0.5,
                        key="wl_target_price",
                        help="Pre-filled with your DCF intrinsic value estimate",
                    )
                with _wl_c2:
                    _wl_mos_thresh = st.slider(
                        "Alert when model MoS reaches",
                        min_value=10, max_value=50,
                        value=20, step=5,
                        format="%d%%",
                        key="wl_mos_thresh",
                    )
                _wl_notes = st.text_area(
                    "Notes (optional)",
                    value="",
                    key="wl_notes",
                    placeholder="Why I'm watching this… e.g. waiting for Q3 results",
                    height=80,
                )
                if st.button("💾 Save to Watchlist", key="wl_save_btn",
                             width='stretch', type="primary"):
                    _wl_ok = add_to_watchlist(
                        ticker               = ticker_input,
                        company_name         = company_name,
                        added_price          = price_d,
                        target_price         = _wl_target,
                        alert_mos_threshold  = float(_wl_mos_thresh),
                        notes                = _wl_notes,
                    )
                    if _wl_ok:
                        st.success(f" **{ticker_input}** saved to watchlist! Switch to the 📊 Watchlist tab to track it.")
                        track_event(st.session_state.get("auth_email",""), tier(), "watchlist_add", {"ticker": ticker_input})
                    else:
                        st.error("Could not save to watchlist — please try again.")

            # model warnings
            if suspicious:
                st.warning("⚠️ Our model flagged unusual patterns in this company's financials. Treat this analysis with extra caution.")
            for _w in _conf_warnings:
                st.warning(f"⚠️ {_w}")

            # ══════════════════════════════════════════════════════════
            # LAYER 2b — YieldIQ Composite Score
            # ══════════════════════════════════════════════════════════
            _ys_pio    = enriched.get("piotroski_score") or int(fs.get("score", 50) / 100 * 9)
            _ys_pt     = (raw.get("finnhub_price_target") or {}) if raw else {}
            _ys_pt_mean = float(_ys_pt.get("mean", 0)) * fx if _ys_pt.get("mean") else 0
            _ys_upside  = ((_ys_pt_mean - price_d) / price_d * 100) if price_d and _ys_pt_mean else 0
            _ys = compute_yieldiq_score(
                mos_pct        = mos_pct,
                piotroski      = int(_ys_pio) if _ys_pio else 0,
                moat_grade     = moat_grade,
                rev_growth     = _rev_growth,
                analyst_upside = _ys_upside,
            )
            st.session_state["_yiq_score_data"] = _ys
            _grade_colors = {
                "A+": "#16a34a", "A": "#22c55e", "B+": "#65a30d", "B": "#84cc16",
                "C+": "#ca8a04", "C": "#f59e0b", "D": "#dc2626",
            }
            _gc = _grade_colors.get(_ys["grade"], "#94a3b8")

            if not pro_mode:
                pass  # Snowflake chart above already shows quality scores
            else:
                st.html('<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin:16px 0 8px;padding-left:2px;">YieldIQ Composite Score</div>')
            _ysc1, _ysc2 = st.columns([1, 2]) if pro_mode else (st.empty(), st.empty())
            with _ysc1:
                st.html(
                    f'<div style="text-align:center;padding:24px 16px;border-radius:14px;'
                    f'background:#FFFFFF;border:2px solid {_gc};'
                    f'box-shadow:0 2px 12px rgba(15,23,42,0.06);">'
                    f'<div style="font-size:52px;font-weight:900;color:{_gc};line-height:1;">'
                    f'{_ys["score"]}</div>'
                    f'<div style="font-size:22px;font-weight:800;color:{_gc};margin-top:6px;">'
                    f'{_ys["grade"]}</div>'
                    f'<div style="font-size:10px;color:#94A3B8;margin-top:8px;'
                    f'text-transform:uppercase;letter-spacing:.1em;'
                    f'font-family:IBM Plex Mono,monospace;">YieldIQ Score</div>'
                    f'</div>'
                )
            with _ysc2:
                for _comp_lbl, _comp_pts in _ys["components"].items():
                    _comp_max = int(_comp_lbl.split("(")[1].replace("pts)", "")) or 1
                    st.progress(
                        _comp_pts / _comp_max,
                        text=f"{_comp_lbl}: **{_comp_pts}** / {_comp_max}",
                    )
            # Contextual note when valuation score is 0
            if _ys["components"].get("Valuation (40pts)", 0) == 0 and mos_pct is not None:
                _mos_str = f"{mos_pct:+.1f}%"
                st.caption(
                    f"ℹ️ Valuation: 0 / 40 pts — the stock trades {_mos_str} vs the model's fair value estimate. "
                    "Valuation points require the stock to trade at or below the model estimate (margin of safety ≥ −15%). "
                    "This reflects current pricing, not business quality."
                )
            st.caption(
                "⚠️ YieldIQ Score is a model output combining DCF, fundamentals, "
                "growth, and analyst data. It is not investment advice."
            )

            # ══════════════════════════════════════════════════════════
            # LAYER 3 — Why? (plain-language expandable, Simple mode only)
            # ══════════════════════════════════════════════════════════
            if not pro_mode:
                with st.expander("💡 Why These Signals? — Plain English Explanation"):
                    _why_val = (
                        f"Our model estimates this stock's fair value at {fmts(iv_d, sym)}. "
                        f"At the current price of {fmts(price_d, sym)}, it appears **{_val_label.lower()}** "
                        f"by around {abs(mos_pct):.0f}%."
                        if abs(mos_pct) > 2 else
                        f"The stock is trading very close to our estimated fair value of {fmts(iv_d, sym)}."
                    )
                    _why_qual = (
                        f"We rate this company's financial health as **{_qual_label}** "
                        f"(score: {fs.get('score',0)}/100). "
                        + ("It shows strong profitability, low debt, and consistent cash generation." if _fs_label == "STRONG" else
                           "It shows solid fundamentals with some areas to watch." if _fs_label == "GOOD" else
                           "It has average financial health — neither particularly strong nor weak." if _fs_label == "AVERAGE" else
                           "It shows some financial weaknesses worth monitoring.")
                    )
                    _why_growth = (
                        f"Revenue is growing at **{_rev_growth:.1f}%** and cash flows are "
                        + ("growing strongly" if _fcf_growth > 10 else
                           "roughly stable" if _fcf_growth > -5 else
                           "under pressure")
                        + f" ({_fcf_growth:.1f}% growth). This signals **{_growth_label.lower()}** momentum."
                    )
                    _why_moat = (
                        f"**Competitive advantage:** {_moat_plain}. "
                        + (f"This is supported by: {_moat_types}." if _moat_types and _moat_grade != "None" else "")
                    )
                    _why_risk = (
                        f"We rate the risk as **{_risk_label.lower()}**. "
                        + ("The company has healthy margins and a strong competitive position." if _risk_label == "Lower" else
                           "There are some risks to watch, but the fundamentals are broadly solid." if _risk_label == "Moderate" else
                           "The company has thin margins or unusual financial patterns — exercise caution.")
                    )

                    st.markdown("**📊 Valuation**  \n" + _why_val)
                    st.markdown("**🏢 Company quality**  \n" + _why_qual)
                    st.markdown("**📈 Growth**  \n" + _why_growth)
                    st.markdown("**🔰 Competitive strength**  \n" + _why_moat)
                    st.markdown("**⚡ Risk**  \n" + _why_risk)

                    if _moat_summary:
                        st.markdown(f"*{_moat_summary[:200]}{'...' if len(_moat_summary) > 200 else ''}*")

            # ══════════════════════════════════════════════════════════
            # LAYER 3c — AI Analysis Summary (Premium / Pro only)
            # ══════════════════════════════════════════════════════════
            if can("action_plan"):
                with st.expander("🤖 AI Analysis Summary — Plain English", expanded=False):
                    with st.spinner("Generating AI analysis…"):
                        _ai_pf_score = (
                            st.session_state.get("_last_pf_score") or
                            int(fs.get("score", 50) / 100 * 9)   # rough proxy from fund score
                        )
                        _ai_text = generate_ai_summary(
                            ticker          = ticker_input,
                            company_name    = company_name,
                            price           = price_d,
                            iv              = iv_d,
                            mos_pct         = mos_pct,
                            signal          = sig,
                            piotroski_score = _ai_pf_score,
                            wacc            = wacc,
                            rev_growth      = enriched.get("revenue_growth", 0),
                            fcf_growth      = enriched.get("fcf_growth", 0),
                            op_margin       = enriched.get("op_margin", 0),
                            moat_grade      = moat_grade,
                            sym             = sym,
                        )
                    # Graceful fallback if AI fails
                    if not _ai_text or "error" in _ai_text.lower()[:50] or "INVALID" in _ai_text[:80]:
                        _ai_text = (
                            f"{company_name} ({ticker_input}) trades at {fmts(price_d, sym)} versus our "
                            f"estimated fair value of {fmts(iv_d, sym)}, implying the stock is "
                            f"{'trading at a discount' if mos_pct > 0 else 'trading at a premium'} "
                            f"of {abs(mos_pct):.0f}% to the model estimate.\n\n"
                            f"The company has a Piotroski F-Score of {_ai_pf_score}/9 and a "
                            f"{'wide' if moat_grade in ('Wide','Narrow') else 'limited'} competitive moat. "
                            f"Revenue growth is {enriched.get('revenue_growth',0)*100:.1f}% with "
                            f"operating margins of {enriched.get('op_margin',0)*100:.1f}%.\n\n"
                            f"This is a model-generated summary. Not investment advice."
                        )
                    _ai_safe = _ai_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    # Split into paragraphs for nicer rendering
                    _ai_paras = [p.strip() for p in _ai_safe.split("\n\n") if p.strip()]
                    _ai_paras_html = "".join(
                        f'<p style="margin:0 0 12px;line-height:1.8;font-size:13px;color:#334155;">{p}</p>'
                        for p in _ai_paras
                    )
                    st.html(f"""
                    <div style="padding:16px 20px;
                                background:linear-gradient(135deg,#F8FAFC,#F4F6F9);
                                border-left:3px solid #7C3AED;
                                border-radius:0 8px 8px 0;">
                      <div style="font-size:11px;font-weight:700;color:#7C3AED;
                                  text-transform:uppercase;letter-spacing:0.12em;
                                  margin-bottom:12px;display:flex;align-items:center;gap:6px;">
                        <span>🤖</span>
                        <span>AI Analysis — Powered by Groq</span>
                      </div>
                      {_ai_paras_html}
                    </div>
                    """)
            else:
                st.html("""
                <div style="padding:10px 14px;background:#F8FAFC;
                            border:1px dashed #CBD5E1;border-radius:8px;
                            font-size:12px;color:#94A3B8;margin-bottom:4px;">
                  🤖 <strong style="color:#64748B;">AI Analysis Summary</strong>
                  — Available on Starter &amp; Pro plans
                  <a href="#" style="color:#7C3AED;margin-left:8px;font-weight:600;">
                    Upgrade →
                  </a>
                </div>
                """)

            # ══════════════════════════════════════════════════════════
            # LAYER 4 — Advanced Analysis (all hidden)
            # ══════════════════════════════════════════════════════════
            with (st.expander("📊 Live Price, Analyst Views & Earnings — Detailed Data") if pro_mode else st.empty()):
                render_live_price_header(ticker=ticker_input, sym=sym, fx=fx, refresh_every=60)
                ccard("What do professional analysts say?", "#7C3AED")
                render_analyst_consensus(ticker=ticker_input, current_price=price_d, sym=sym, fx=fx, raw_data=raw)
                ccard_end()
                ccard("Upcoming earnings & past surprises", "#0891B2")
                render_earnings_calendar(ticker=ticker_input, sym=sym, raw_data=raw)
                ccard_end()

            with (st.expander("📋 Detailed Financial Metrics & Key Ratios") if pro_mode else st.empty()):
                k1,k2,k3,k4 = st.columns(4)
                _dcf_iv_d = enriched.get("dcf_iv", 0) * fx
                _pe_iv_d  = enriched.get("pe_iv",  0) * fx
                k1.metric("Current price",        fmts(price_d, sym))
                k2.metric("Estimated fair value", fmts(iv_d, sym),
                          delta=f"DCF:{fmts(_dcf_iv_d,sym)} | PE:{fmts(_pe_iv_d,sym)}" if _pe_iv_d > 0 else None,
                          delta_color="off")
                k3.metric("Discount to fair value", f"{mos_pct:.1f}%",
                          help=FINANCIAL_TOOLTIPS["Margin of Safety"])
                k4.metric("Model confidence", f"{confidence['grade']} ({confidence['score']}/100)")
                k5,k6,k7,k8 = st.columns(4)
                k5.metric("Revenue growth",       f"{_rev_growth:.1f}%")
                k6.metric("Profit margin",        f"{_op_margin:.1f}%")
                k7.metric("Cash flow growth",     f"{_fcf_growth:.1f}%",
                          help=FINANCIAL_TOOLTIPS["FCF"])
                k8.metric("Required return rate", f"{wacc:.1%}",
                          help=FINANCIAL_TOOLTIPS["WACC"])
                if pro_mode:
                    _pq1, _pq2, _pq3, _pq4 = st.columns(4)
                    _pq1.metric("Enterprise Value",  fmt(dcf_res.get("enterprise_value", 0) * fx, sym))
                    _pq2.metric("PV Terminal Value", fmt(pv_tv_d, sym),
                                help=FINANCIAL_TOOLTIPS["Terminal Value"])
                    _pq3.metric("TV % of EV",        f"{dcf_res.get('tv_pct_of_ev', 0):.0%}")
                    _pq4.metric("Equity Value",      fmt(dcf_res.get("equity_value", 0) * fx, sym))

            # ── Legal compliance disclaimer banner ────────────────────
            st.html("""
<div style="margin:10px 0 6px;padding:8px 16px;background:#FFFBEB;
            border:1px solid #FDE68A;border-radius:6px;text-align:center;">
  <span style="font-size:11px;color:#92400E;font-family:'Inter',sans-serif;line-height:1.4;">
    ⚠️ <strong>Model output only — not investment advice.</strong>
    YieldIQ is not a registered investment adviser.
    All signals reflect mathematical model comparisons, not personalised model outputs.
    See full disclaimer in the <strong>Guide</strong> tab.
  </span>
</div>
""")

            if use_auto_wacc and wacc_data.get("auto_computed"):
                with st.expander(f"🔢 Required Return Rate ({wacc:.1%}) — How WACC Was Calculated"):
                    w1,w2,w3,w4,w5 = st.columns(5)
                    w1.metric("Required return (WACC)",    f"{wacc_data['wacc']:.1%}",
                              help=FINANCIAL_TOOLTIPS["WACC"])
                    w1.caption("Higher WACC = more conservative (lower) intrinsic value estimate")
                    w2.metric("Expected equity return",    f"{wacc_data['re']:.1%}")
                    w3.metric("Volatility vs market (Beta)", f"{wacc_data['beta']:.2f}")
                    w4.metric("Risk-free rate",             f"{wacc_data['rf']:.1%}")
                    w5.metric("Cost of debt",               f"{wacc_data['rd']:.1%}")

        if _active == "dcf_model":
            if not st.session_state.get("fin_enriched"):
                st.info("Run an analysis first to see this section.")
                st.stop()

            # (Old valuation summary card removed — replaced by Valuation Hero above tabs)


            # ══════════════════════════════════════════════════════════
            # INTERACTIVE DCF ENGINE — Centerpiece Feature
            # Users adjust assumptions → fair value updates instantly
            # ══════════════════════════════════════════════════════════
            st.html('<div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin:20px 0 10px;padding-left:2px;'
                    'font-family:IBM Plex Mono,monospace;">🔧 Interactive DCF Engine</div>')

            with st.container(border=True):
                st.html('<div style="font-size:12px;color:#475569;margin-bottom:12px;">'
                        'Adjust assumptions below to see how fair value changes. '
                        'The model recalculates instantly.</div>')

                _eng_c1, _eng_c2, _eng_c3 = st.columns(3)

                with _eng_c1:
                    _eng_wacc = st.slider(
                        "Discount Rate (WACC)",
                        min_value=5.0, max_value=18.0,
                        value=float(round(wacc * 100, 1)),
                        step=0.5, format="%.1f%%",
                        key="_dcf_eng_wacc",
                        help="Higher discount rate = more conservative (lower) fair value"
                    )

                with _eng_c2:
                    _eng_tg = st.slider(
                        "Terminal Growth Rate",
                        min_value=1.0, max_value=5.0,
                        value=float(round(terminal_g * 100, 1)),
                        step=0.5, format="%.1f%%",
                        key="_dcf_eng_tg",
                        help="Long-run perpetual growth rate (typically 2-3%)"
                    )

                with _eng_c3:
                    _eng_growth_adj = st.slider(
                        "Growth Adjustment",
                        min_value=-50, max_value=50,
                        value=0, step=5, format="%+d%%",
                        key="_dcf_eng_growth",
                        help="Scale projected FCFs up or down to test different growth scenarios"
                    )

                # Learn Mode tips for DCF Engine
                try:
                    from utils.learn_mode import learn_tip
                    learn_tip("wacc")
                    learn_tip("dcf")
                except Exception:
                    pass

                # ── Recalculate fair value with adjusted assumptions ──
                _eng_wacc_dec = _eng_wacc / 100
                _eng_tg_dec = _eng_tg / 100
                _eng_growth_mult = 1 + (_eng_growth_adj / 100)

                _eng_proj = [fcf * _eng_growth_mult for fcf in projected]
                _eng_term = terminal_norm * _eng_growth_mult

                try:
                    _eng_dcf = DCFEngine(discount_rate=_eng_wacc_dec, terminal_growth=_eng_tg_dec)
                    _eng_result = _eng_dcf.intrinsic_value_per_share(
                        projected_fcfs=_eng_proj, terminal_fcf_norm=_eng_term,
                        total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                        shares_outstanding=enriched["shares"],
                        current_price=enriched["price"], ticker=ticker_input,
                    )
                    _eng_iv = _eng_result.get("iv_per_share", 0) * fx
                    if _eng_iv <= 0:
                        _eng_iv = iv_d  # fallback if engine returns 0
                except Exception:
                    _eng_iv = iv_d  # fallback to base case
                _eng_mos = ((_eng_iv - price_d) / price_d * 100) if price_d > 0 else 0

                # Color based on valuation
                if _eng_mos >= 10:
                    _eng_color, _eng_label = "#059669", "Discount to estimated fair value"
                elif _eng_mos >= -10:
                    _eng_color, _eng_label = "#D97706", "Near estimated fair value"
                else:
                    _eng_color, _eng_label = "#DC2626", "Premium to estimated fair value"

                # ── Display result ──
                _eng_r1, _eng_r2, _eng_r3 = st.columns(3)
                with _eng_r1:
                    st.html(f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;'
                            f'padding:16px;text-align:center;">'
                            f'<div style="font-size:10px;color:#94A3B8;font-weight:700;'
                            f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;'
                            f'font-family:IBM Plex Mono,monospace;">Adjusted Fair Value</div>'
                            f'<div style="font-size:28px;font-weight:900;color:{_eng_color};'
                            f'font-family:IBM Plex Mono,monospace;">{sym}{_eng_iv:,.0f}</div>'
                            f'</div>')
                with _eng_r2:
                    st.html(f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;'
                            f'padding:16px;text-align:center;">'
                            f'<div style="font-size:10px;color:#94A3B8;font-weight:700;'
                            f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;'
                            f'font-family:IBM Plex Mono,monospace;">Implied Upside/Downside</div>'
                            f'<div style="font-size:28px;font-weight:900;color:{_eng_color};'
                            f'font-family:IBM Plex Mono,monospace;">{_eng_mos:+.1f}%</div>'
                            f'</div>')
                with _eng_r3:
                    _eng_diff = _eng_iv - iv_d
                    _eng_diff_pct = ((_eng_iv / iv_d - 1) * 100) if iv_d > 0 else 0
                    _eng_diff_color = "#059669" if _eng_diff >= 0 else "#DC2626"
                    st.html(f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;'
                            f'padding:16px;text-align:center;">'
                            f'<div style="font-size:10px;color:#94A3B8;font-weight:700;'
                            f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;'
                            f'font-family:IBM Plex Mono,monospace;">vs Base Case ({sym}{iv_d:,.0f})</div>'
                            f'<div style="font-size:28px;font-weight:900;color:{_eng_diff_color};'
                            f'font-family:IBM Plex Mono,monospace;">{_eng_diff_pct:+.1f}%</div>'
                            f'</div>')

                st.html(f'<div style="text-align:center;margin-top:10px;font-size:12px;color:{_eng_color};'
                        f'font-weight:600;">{_eng_label}</div>'
                        f'<div style="text-align:center;margin-top:4px;font-size:10px;color:#94A3B8;">'
                        f'Base case: {sym}{iv_d:,.0f} · Current price: {sym}{price_d:,.2f}</div>')

            # ── Live RF Rate assumptions banner ────────────────────────
            _rf_ui = st.session_state.get("_rf_rate_info", {})
            if _rf_ui:
                _rf_src_icon = "🟢" if _rf_ui.get("source") == "live" else "🟡"
                _rf_mkt      = "US 10Y" if _rf_ui.get("market") == "us" else "India 10Y"
                _rf_adj_val  = _rf_ui.get("wacc_adj", 0.0)
                _rf_adj_s    = f"  ·  WACC adj {_rf_adj_val:+.2%}" if _rf_adj_val else ""
                _rf_env      = _rf_ui.get("environment", "")
                _rf_env_clr  = "#DC2626" if "Tight" in _rf_env else "#059669" if "Loose" in _rf_env else "#64748B"
                st.html(f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;
                            padding:8px 16px;margin-bottom:12px;display:flex;align-items:center;
                            gap:18px;flex-wrap:wrap;font-size:12px;">
                  <span style="color:#64748B;font-weight:600;">⚙️ DCF Assumptions</span>
                  <span style="color:#475569;">{_rf_src_icon} Risk-Free Rate:
                    <b style="color:#0F172A;font-family:'IBM Plex Mono',monospace;">
                      {_rf_ui.get('rate_pct', 0):.2f}% ({_rf_mkt})
                    </b>
                  </span>
                  <span style="color:#475569;">WACC: <b style="color:#0F172A;font-family:'IBM Plex Mono',monospace;">{wacc:.2%}</b></span>
                  <span style="color:#475569;">Terminal g: <b style="color:#0F172A;font-family:'IBM Plex Mono',monospace;">{terminal_g:.2%}</b></span>
                  <span style="color:{_rf_env_clr};">{_rf_env}{_rf_adj_s}</span>
                </div>
                """)

            # ══════════════════════════════════════════════════════════
            # SECTION 2 — Scenario Cards (Bull / Base / Bear)
            # ══════════════════════════════════════════════════════════
            st.html('<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin:14px 0 8px;padding-left:2px;">Scenarios</div>')

            _sc_cols = st.columns(3)
            _sc_cfg = [
                ("🐻 Bear case",    "Cautious outlook",        scenarios.get("Bear 🐻",  {}), "#B91C1C", "#FEF2F2", "#FECACA"),
                ("📊 Base case",    "Most likely outcome",     scenarios.get("Base 📊",  {}), "#1D4ED8", "#EFF6FF", "#BFDBFE"),
                ("🐂 Bull case",    "Optimistic outlook",      scenarios.get("Bull 🐂",  {}), "#0D7A4E", "#F0FDF4", "#BBF7D0"),
            ]
            for _col, (_sc_name, _sc_desc, _sc_data, _sc_c, _sc_bg, _sc_bd) in zip(_sc_cols, _sc_cfg):
                _sc_iv  = (_sc_data.get("iv", 0) or 0) * fx
                _sc_mos = _sc_data.get("mos_pct", 0) or 0
                _sc_lbl = (
                    "Undervalued"   if _sc_mos > 10 else
                    "Near model fair value" if _sc_mos > -10 else
                    "Overvalued"
                )
                _sc_card = (
                    '<div style="background:#FFFFFF;border:1px solid SCBD;border-top:3px solid SCC;'
                    'border-radius:10px;padding:16px 18px;height:100%;">'
                    '<div style="font-size:13px;font-weight:700;color:SCC;margin-bottom:4px;">SCNAME</div>'
                    '<div style="font-size:11px;color:#94A3B8;margin-bottom:12px;">SCDESC</div>'
                    '<div style="font-size:22px;font-weight:700;color:#0F172A;margin-bottom:4px;">SCIV</div>'
                    '<div style="font-size:12px;color:#64748B;margin-bottom:8px;">Estimated fair value</div>'
                    '<div style="display:inline-block;padding:3px 10px;background:SCBG;'
                    'border:1px solid SCBD;border-radius:12px;">'
                    '<span style="font-size:12px;font-weight:600;color:SCC;">SCLBL · SCMOS%</span>'
                    '</div>'
                    '</div>'
                )
                _sc_card = (
                    _sc_card
                    .replace("SCNAME", _sc_name)
                    .replace("SCDESC", _sc_desc)
                    .replace("SCIV",   fmts(_sc_iv, sym) if _sc_iv else "—")
                    .replace("SCMOS",  f"{_sc_mos:+.0f}")
                    .replace("SCLBL",  _sc_lbl)
                    .replace("SCC",    _sc_c)
                    .replace("SCBG",   _sc_bg)
                    .replace("SCBD",   _sc_bd)
                )
                _col.html(_sc_card)

            # ══════════════════════════════════════════════════════════
            # SECTION 3 — Key Insights (plain English, Simple mode only)
            # ══════════════════════════════════════════════════════════
            _insights = []

            if mos_pct > 20:
                _insights.append(("🟢", f"The stock appears meaningfully undervalued — our model estimates a {mos_pct:.0f}% discount to fair value."))
            elif mos_pct > 5:
                _insights.append(("🟡", f"The stock looks modestly undervalued by around {mos_pct:.0f}% based on our cash flow model."))
            elif mos_pct > -5:
                _insights.append(("🔵", "The stock is trading close to what our model considers fair value."))
            else:
                _insights.append(("🔴", f"The stock may be trading above fair value — our model suggests it is {abs(mos_pct):.0f}% above its estimated worth."))

            _bull_iv = (scenarios.get("Bull 🐂", {}).get("iv", 0) or 0) * fx
            _bear_iv = (scenarios.get("Bear 🐻", {}).get("iv", 0) or 0) * fx
            if _bull_iv > 0 and _bear_iv > 0:
                _range_pct = ((_bull_iv - _bear_iv) / price_d * 100) if price_d > 0 else 0
                if _range_pct > 50:
                    _insights.append(("⚡", "The valuation is sensitive to assumptions — bull and bear cases are far apart. Treat the estimate with appropriate caution."))
                else:
                    _insights.append(("", "Bull and bear scenarios are relatively close together, suggesting moderate uncertainty in the estimate."))

            _rev_g = enriched.get("revenue_growth", 0) * 100
            _fcf_g = enriched.get("fcf_growth", 0) * 100
            if _rev_g > 15:
                _insights.append(("📈", f"Revenue is growing strongly ({_rev_g:.0f}%), which supports a higher fair value estimate."))
            elif _rev_g > 0:
                _insights.append(("📊", f"Revenue is growing at a moderate pace ({_rev_g:.0f}%), reflected in the base case estimate."))
            else:
                _insights.append(("📉", "Revenue growth has been slow or negative, which limits upside in our model."))

            _moat_g = enriched.get("moat_grade", "None")
            if _moat_g == "Wide":
                _insights.append(("🔰", "The company has a strong competitive advantage, which adds a premium to the fair value estimate."))
            elif _moat_g == "Narrow":
                _insights.append(("🔰", "The company has some competitive advantages, providing modest support to the valuation."))

            if confidence.get("score", 0) < 50:
                _insights.append(("⚠️", "Model confidence is lower than usual — the estimate may be less reliable for this stock."))

            if not pro_mode:
                st.html('<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                        'letter-spacing:0.14em;margin:16px 0 8px;padding-left:2px;">Key insights</div>')
                _ins_html = '<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:16px 20px;margin-bottom:8px;">'
                for _icon, _txt in _insights[:5]:
                    _ins_html += (
                        '<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;'
                        'border-bottom:1px solid #F8FAFC;">'
                        '<span style="font-size:16px;flex-shrink:0;margin-top:1px;">' + _icon + '</span>'
                        '<span style="font-size:13px;color:#334155;line-height:1.6;">' + _txt + '</span>'
                        '</div>'
                    )
                _ins_html += '</div>'
                st.html(_ins_html)

            # ══════════════════════════════════════════════════════════
            # SECTION 4 — Price Chart (compact)
            # ══════════════════════════════════════════════════════════
            if not price_hist.empty:
                with st.expander("📈 Price History Chart with Fair Value Line", expanded=True):
                    phd = price_hist.copy()
                    for col in ["Open","High","Low","Close"]:
                        phd[col] = phd[col] * fx

                # Build candle + volume data for lightweight-charts
                _candles = []
                _volumes = []
                for _, row in phd.iterrows():
                    try:
                        _dt = row["Date"]
                        if hasattr(_dt, "strftime"):
                            _ts = _dt.strftime("%Y-%m-%d")
                        else:
                            _ts = str(_dt)[:10]
                        _o = float(row["Open"])
                        _h = float(row["High"])
                        _l = float(row["Low"])
                        _c = float(row["Close"])
                        _v = float(row.get("Volume", 0))
                        if _o > 0 and _h > 0:
                            _candles.append({"time":_ts,"open":round(_o,4),"high":round(_h,4),"low":round(_l,4),"close":round(_c,4)})
                            _volumes.append({"time":_ts,"value":_v,"color":"#10b981" if _c>=_o else "#ef4444"})
                    except Exception:
                        continue

                # MA20
                _ma20 = []
                if len(phd) >= 20:
                    phd["_ma"] = phd["Close"].rolling(20).mean()
                    for _, row in phd.dropna(subset=["_ma"]).iterrows():
                        try:
                            _dt = row["Date"]
                            _ts = _dt.strftime("%Y-%m-%d") if hasattr(_dt,"strftime") else str(_dt)[:10]
                            _ma20.append({"time":_ts,"value":round(float(row["_ma"]),4)})
                        except Exception:
                            continue

                # IV line + buy/sell markers
                _iv_val   = round(iv_d, 4) if iv_d > 0 else 0
                _iv_label = f"YIQ IV  {sym}{iv_d:,.2f}" if iv_d > 0 else ""

                # MA50 and MA200
                _ma50, _ma200 = [], []
                if len(phd) >= 50:
                    phd["_ma50"] = phd["Close"].rolling(50).mean()
                    for _, row in phd.dropna(subset=["_ma50"]).iterrows():
                        try:
                            _dt = row["Date"]
                            _ts = _dt.strftime("%Y-%m-%d") if hasattr(_dt,"strftime") else str(_dt)[:10]
                            _ma50.append({"time":_ts,"value":round(float(row["_ma50"]),4)})
                        except Exception: continue
                if len(phd) >= 200:
                    phd["_ma200"] = phd["Close"].rolling(200).mean()
                    for _, row in phd.dropna(subset=["_ma200"]).iterrows():
                        try:
                            _dt = row["Date"]
                            _ts = _dt.strftime("%Y-%m-%d") if hasattr(_dt,"strftime") else str(_dt)[:10]
                            _ma200.append({"time":_ts,"value":round(float(row["_ma200"]),4)})
                        except Exception: continue

                # 52-week high/low for shaded band
                _52w_high = float(phd["High"].tail(252).max()) if len(phd) >= 20 else 0
                _52w_low  = float(phd["Low"].tail(252).min())  if len(phd) >= 20 else 0

                # Serialize all data for JS
                import json as _json
                _candles_js  = _json.dumps(_candles)
                _volumes_js  = _json.dumps(_volumes)
                _ma20_js     = _json.dumps(_ma20)
                _ma50_js     = _json.dumps(_ma50)
                _ma200_js    = _json.dumps(_ma200)
                _markers_js  = "[]"
                _ticker_js   = _json.dumps(ticker_input)
                _sym_js      = _json.dumps(sym)

                # ── Clean chart: price + MA20 + IV fair value line ─────
                st.components.v1.html(f"""
<!DOCTYPE html>
<html>
<head>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #FFFFFF; font-family: 'Inter', system-ui, sans-serif; }}
  #wrap {{ position: relative; width: 100%; }}
  #main-chart {{ width: 100%; height: 320px; }}
  #vol-chart  {{ width: 100%; height: 60px; margin-top: 1px; }}

  /* Toolbar */
  #toolbar {{
    display: flex; align-items: center; gap: 6px;
    padding: 8px 12px 6px; background: #FFFFFF;
    border-bottom: 1px solid #F1F5F9;
    flex-wrap: wrap;
  }}
  .ticker-label {{
    font-size: 13px; font-weight: 700; color: #0F172A;
    margin-right: 6px; letter-spacing: -0.01em;
  }}
  .price-label {{
    font-size: 13px; font-weight: 600; color: #0F172A;
    font-family: 'IBM Plex Mono', monospace;
    margin-right: 10px;
  }}
  .tb-btn {{
    font-size: 11px; font-weight: 500; padding: 3px 8px;
    border: 1px solid #E2E8F0; border-radius: 4px;
    background: #FFFFFF; color: #475569; cursor: pointer;
    letter-spacing: 0.04em; transition: all 0.1s;
  }}
  .tb-btn:hover  {{ background: #EFF6FF; border-color: #BFDBFE; color: #1D4ED8; }}
  .tb-btn.active {{ background: #1D4ED8; color: #FFFFFF; border-color: #1D4ED8; }}
  .tb-sep {{ width: 1px; height: 14px; background: #E2E8F0; margin: 0 2px; }}

  /* OHLC legend — fixed top-right, no overlap */
  #ohlc-legend {{
    position: absolute; top: 44px; right: 12px;
    background: rgba(255,255,255,0.92);
    border: 1px solid #E2E8F0; border-radius: 6px;
    padding: 5px 10px; font-size: 11px; color: #475569;
    font-family: 'IBM Plex Mono', monospace;
    line-height: 1.7; pointer-events: none;
    display: none; z-index: 10;
    box-shadow: 0 2px 8px rgba(15,23,42,0.08);
  }}

  /* IV badge — bottom-left of chart */
  #iv-badge {{
    position: absolute; bottom: 68px; left: 12px;
    background: rgba(29,78,216,0.08);
    border: 1px solid rgba(29,78,216,0.25); border-radius: 4px;
    padding: 3px 8px; font-size: 11px; font-weight: 600;
    color: #1D4ED8; pointer-events: none; z-index: 10;
    font-family: 'IBM Plex Mono', monospace;
  }}

  /* Caption row */
  #caption {{
    padding: 5px 12px; font-size: 11px; color: #94A3B8;
    border-top: 1px solid #F1F5F9; background: #FAFBFD;
  }}
</style>
</head>
<body>
<div id="wrap">
  <div id="toolbar">
    <span class="ticker-label">{ticker_input}</span>
    <span class="price-label" id="cur-price">{fmts(price_d, sym)}</span>
    <div class="tb-sep"></div>
    <button class="tb-btn" onclick="setRange('1M',this)">1M</button>
    <button class="tb-btn" onclick="setRange('3M',this)">3M</button>
    <button class="tb-btn" onclick="setRange('6M',this)">6M</button>
    <button class="tb-btn active" onclick="setRange('1Y',this)">1Y</button>
    <div class="tb-sep"></div>
    <button class="tb-btn active" id="ma-btn" onclick="toggleMA(this)">MA20</button>
    <button class="tb-btn active" id="iv-btn" onclick="toggleIV(this)">Fair Value</button>
  </div>

  <div id="main-chart"></div>
  <div id="vol-chart"></div>
  <div id="ohlc-legend"></div>
  {'<div id="iv-badge">Fair value ' + fmts(iv_d, sym) + '</div>' if iv_d > 0 else ''}
  <div id="caption">Price data · MA20 (20-day average) · Fair value line · For informational purposes only</div>
</div>

<script>
const candleData  = {_candles_js};
const volumeData  = {_volumes_js};
const ma20Data    = {_ma20_js};
const markers     = [];
const ivVal       = {_iv_val};
const sym         = {_sym_js};

// ── Main chart ────────────────────────────────────────────────
const chart = LightweightCharts.createChart(
  document.getElementById('main-chart'), {{
    width:  document.getElementById('main-chart').offsetWidth,
    height: 320,
    layout: {{
      background: {{ color: '#FFFFFF' }},
      textColor:  '#64748B',
      fontSize:   11,
      fontFamily: "'Inter', system-ui, sans-serif",
    }},
    grid: {{
      vertLines: {{ color: '#F8FAFC' }},
      horzLines: {{ color: '#F1F5F9' }},
    }},
    crosshair: {{
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: {{ color: '#94A3B8', width: 1, style: 3, labelBackgroundColor: '#334155' }},
      horzLine: {{ color: '#94A3B8', width: 1, style: 3, labelBackgroundColor: '#334155' }},
    }},
    rightPriceScale: {{
      borderColor: '#F1F5F9',
      scaleMargins: {{ top: 0.08, bottom: 0.08 }},
    }},
    timeScale: {{
      borderColor:     '#F1F5F9',
      timeVisible:     true,
      secondsVisible:  false,
      fixLeftEdge:     true,
      fixRightEdge:    true,
    }},
    handleScroll:   {{ mouseWheel: true, pressedMouseMove: true }},
    handleScale:    {{ mouseWheel: true, pinch: true }},
  }}
);

// ── Candlestick series ────────────────────────────────────────
const candleSeries = chart.addCandlestickSeries({{
  upColor:          '#10b981',
  downColor:        '#ef4444',
  borderUpColor:    '#059669',
  borderDownColor:  '#dc2626',
  wickUpColor:      '#10b981',
  wickDownColor:    '#ef4444',
  priceLineVisible: false,
}});
candleSeries.setData(candleData);

// ── MA20 ──────────────────────────────────────────────────────
const maSeries = chart.addLineSeries({{
  color:            '#64748b',
  lineWidth:        1,
  lineStyle:        LightweightCharts.LineStyle.Dashed,
  priceLineVisible: false,
  lastValueVisible: false,
  title:            'MA20',
}});
maSeries.setData(ma20Data);

// ── MA50 ──────────────────────────────────────────────────
const ma50Data = {_ma50_js};
const ma50Series = chart.addLineSeries({{
  color:            '#3b82f6',
  lineWidth:        1.5,
  lineStyle:        LightweightCharts.LineStyle.Solid,
  priceLineVisible: false,
  lastValueVisible: true,
  title:            'MA50',
}});
if (ma50Data.length > 0) ma50Series.setData(ma50Data);

// ── MA200 ─────────────────────────────────────────────────
const ma200Data = {_ma200_js};
const ma200Series = chart.addLineSeries({{
  color:            '#f59e0b',
  lineWidth:        1.5,
  lineStyle:        LightweightCharts.LineStyle.Solid,
  priceLineVisible: false,
  lastValueVisible: true,
  title:            'MA200',
}});
if (ma200Data.length > 0) ma200Series.setData(ma200Data);

// ── 52-week high/low shaded band ─────────────────────────
const hiVal = {_52w_high}; const loVal = {_52w_low};
if (hiVal > 0 && candleData.length > 0) {{
  const firstT = candleData[0].time;
  const lastT  = candleData[candleData.length-1].time;
  // high zone (top 5% of 52w range)
  const hiSeries = chart.addLineSeries({{
    color:'rgba(16,185,129,0.0)',lineWidth:0,priceLineVisible:false,lastValueVisible:false,
  }});
  hiSeries.setData([{{time:firstT,value:hiVal}},{{time:lastT,value:hiVal}}]);
  // low zone
  const loSeries = chart.addLineSeries({{
    color:'rgba(239,68,68,0.0)',lineWidth:0,priceLineVisible:false,lastValueVisible:false,
  }});
  loSeries.setData([{{time:firstT,value:loVal}},{{time:lastT,value:loVal}}]);
}}

// ── Fair value (IV) line ──────────────────────────────────────
let ivSeries = null;
if (ivVal > 0 && candleData.length > 0) {{
  ivSeries = chart.addLineSeries({{
    color:            '#1D4ED8',
    lineWidth:        2,
    lineStyle:        LightweightCharts.LineStyle.Dashed,
    priceLineVisible: false,
    lastValueVisible: true,
    title:            'Fair Value',
  }});
  ivSeries.setData([
    {{ time: candleData[0].time,                    value: ivVal }},
    {{ time: candleData[candleData.length - 1].time, value: ivVal }},
  ]);
}}

// ── Volume chart ──────────────────────────────────────────────
const volChart = LightweightCharts.createChart(
  document.getElementById('vol-chart'), {{
    width:  document.getElementById('vol-chart').offsetWidth,
    height: 60,
    layout: {{ background: {{ color: '#FFFFFF' }}, textColor: '#94A3B8', fontSize: 10 }},
    grid:   {{ vertLines: {{ color: '#F8FAFC' }}, horzLines: {{ visible: false }} }},
    rightPriceScale: {{
      borderColor:   '#F1F5F9',
      scaleMargins:  {{ top: 0.1, bottom: 0 }},
      drawTicks:     false,
    }},
    timeScale: {{
      borderColor:    '#F1F5F9',
      timeVisible:    false,
      fixLeftEdge:    true,
      fixRightEdge:   true,
    }},
    crosshair: {{ horzLine: {{ visible: false }} }},
    handleScroll: false,
    handleScale:  false,
  }}
);
const volSeries = volChart.addHistogramSeries({{
  priceFormat:  {{ type: 'volume' }},
  priceScaleId: 'volume',
}});
volSeries.setData(volumeData);

// ── Sync crosshair ────────────────────────────────────────────
chart.subscribeCrosshairMove(p => {{
  if (p.time) volChart.setCrosshairPosition(0, p.time, volSeries);
  else        volChart.clearCrosshairPosition();
}});
// ── Sync time scale ───────────────────────────────────────────
chart.timeScale().subscribeVisibleLogicalRangeChange(r => {{
  if (r) volChart.timeScale().setVisibleLogicalRange(r);
}});
volChart.timeScale().subscribeVisibleLogicalRangeChange(r => {{
  if (r) chart.timeScale().setVisibleLogicalRange(r);
}});

// ── OHLC Legend (fixed position, no overlap) ──────────────────
const legend = document.getElementById('ohlc-legend');
chart.subscribeCrosshairMove(p => {{
  if (!p.time || !p.seriesData) {{ legend.style.display = 'none'; return; }}
  const d = p.seriesData.get(candleSeries);
  if (!d) {{ legend.style.display = 'none'; return; }}
  legend.style.display = 'block';
  const chg    = d.close - d.open;
  const chgPct = (chg / d.open * 100).toFixed(2);
  const clr    = chg >= 0 ? '#10b981' : '#ef4444';
  legend.innerHTML =
    '<span style="color:#94A3B8;">' + p.time + '</span><br>' +
    'O <b>' + sym + d.open.toFixed(2)  + '</b>  ' +
    'H <b>' + sym + d.high.toFixed(2)  + '</b>  ' +
    'L <b>' + sym + d.low.toFixed(2)   + '</b>  ' +
    'C <b style="color:' + clr + '">'  + sym + d.close.toFixed(2) + '</b>  ' +
    '<span style="color:' + clr + '">(' + (chg >= 0 ? '+' : '') + chgPct + '%)</span>';
}});

// ── Time range buttons ────────────────────────────────────────
function setRange(r, btn) {{
  document.querySelectorAll('.tb-btn').forEach(b => {{
    if (['1M','3M','6M','1Y'].includes(b.textContent)) b.classList.remove('active');
  }});
  btn.classList.add('active');
  const last = candleData[candleData.length - 1].time;
  const d    = new Date(last);
  let from;
  if      (r === '1M') {{ d.setMonth(d.getMonth() - 1);          from = d.toISOString().slice(0,10); }}
  else if (r === '3M') {{ d.setMonth(d.getMonth() - 3);          from = d.toISOString().slice(0,10); }}
  else if (r === '6M') {{ d.setMonth(d.getMonth() - 6);          from = d.toISOString().slice(0,10); }}
  else                 {{ d.setFullYear(d.getFullYear() - 1);     from = d.toISOString().slice(0,10); }}
  chart.timeScale().setVisibleRange({{ from, to: last }});
}}

// ── Toggle MA20 ───────────────────────────────────────────────
let maVisible = true;
function toggleMA(btn) {{
  maVisible = !maVisible;
  maSeries.applyOptions({{ visible: maVisible }});
  btn.classList.toggle('active', maVisible);
}}

// ── Toggle IV line ────────────────────────────────────────────
let ivVisible = true;
function toggleIV(btn) {{
  ivVisible = !ivVisible;
  if (ivSeries) ivSeries.applyOptions({{ visible: ivVisible }});
  const badge = document.getElementById('iv-badge');
  if (badge) badge.style.display = ivVisible ? 'block' : 'none';
  btn.classList.toggle('active', ivVisible);
}}

// ── Fit content on load ───────────────────────────────────────
chart.timeScale().fitContent();

// ── Responsive resize ────────────────────────────────────────
const ro = new ResizeObserver(() => {{
  const w = document.getElementById('main-chart').offsetWidth;
  chart.applyOptions({{ width: w }});
  volChart.applyOptions({{ width: w }});
}});
ro.observe(document.getElementById('wrap'));
</script>
</body>
</html>
""", height=470, scrolling=False)
    
            # ── Historical + Projected FCF
            # ══════════════════════════════════════════════════════════
            # SECTION 5 — Advanced Analysis (all in expanders)
            # ══════════════════════════════════════════════════════════
            st.html('<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin:16px 0 8px;padding-left:2px;">Advanced analysis</div>')

            with st.expander("📈 FCF History & 10-Year Cash Flow Projections"):
                cf_df_plot = enriched.get("cf_df", pd.DataFrame())
                hist_fcfs  = []
                hist_yrs   = []

                if not cf_df_plot.empty and "fcf" in cf_df_plot.columns:
                    valid_hist = cf_df_plot[cf_df_plot["fcf"].abs() > 1e6]
                    if not valid_hist.empty:
                        hist_fcfs = (valid_hist["fcf"] * fx / 1e9).tolist()
                        hist_yrs  = [str(int(y)) for y in valid_hist["year"].tolist()]

                # Use calendar year labels for projected FCF so x-axis is consistent
                import datetime as _dt
                _base_yr   = int(hist_yrs[-1]) + 1 if hist_yrs else _dt.datetime.now().year + 1
                proj_labels = [str(_base_yr + i) for i in range(forecast_yrs)]
                all_labels  = hist_yrs + proj_labels

                fig_fcf = go.Figure()

                # ── Shaded projected region ──────────────────────────────
                if hist_yrs and proj_labels and len(hist_yrs) + len(proj_labels) > 0:
                    _sep_x = len(hist_yrs) / (len(hist_yrs) + len(proj_labels))
                    fig_fcf.add_shape(
                        type="rect", xref="paper", yref="paper",
                        x0=_sep_x, x1=1.0, y0=0, y1=1,
                        fillcolor="rgba(16,185,129,0.04)",
                        line=dict(width=0), layer="below",
                    )

                # ── Historical bars ──────────────────────────────────────
                if hist_fcfs:
                    fig_fcf.add_trace(go.Bar(
                        x=hist_yrs, y=hist_fcfs,
                        marker=dict(
                            color=["#3b82f6" if v >= 0 else "#ef4444" for v in hist_fcfs],
                            opacity=0.88, line=dict(width=0),
                        ),
                        name="Historical FCF",
                        text=[f"${abs(v):.1f}B" for v in hist_fcfs],
                        textposition="outside",
                        textfont=dict(size=9, color="#8b949e", family="IBM Plex Mono"),
                        hovertemplate=f"<b>%{{x}}</b><br>FCF: {sym}%{{y:.2f}}B<extra>Historical</extra>",
                    ))

                # ── Projected bars ───────────────────────────────────────
                proj_vals = [v / 1e9 for v in proj_d]
                fig_fcf.add_trace(go.Bar(
                    x=proj_labels, y=proj_vals,
                    marker=dict(
                        color=["#10b981" if v >= 0 else "#ef4444" for v in proj_vals],
                        opacity=0.88, line=dict(width=0),
                    ),
                    name="Projected FCF",
                    text=[f"${abs(v):.1f}B" for v in proj_vals],
                    textposition="outside",
                    textfont=dict(size=9, color="#8b949e", family="IBM Plex Mono"),
                    hovertemplate=f"<b>%{{x}}</b><br>FCF: {sym}%{{y:.2f}}B<extra>Projected</extra>",
                ))

                # ── Growth rate overlay (secondary y-axis) ───────────────
                growth_pct = [g * 100 for g in growth_schedule]
                fig_fcf.add_trace(go.Scatter(
                    x=proj_labels, y=growth_pct,
                    yaxis="y2",
                    line=dict(color="#f59e0b", width=2, dash="dot"),
                    mode="lines+markers",
                    marker=dict(size=5, color="#f59e0b", symbol="circle"),
                    name="Growth %",
                    hovertemplate="<b>%{x}</b><br>Growth: %{y:.1f}%<extra>Growth Rate</extra>",
                ))

                # ── Dashed separator + dual annotation ───────────────────
                if hist_yrs and proj_labels:
                    _sep = len(hist_yrs) / (len(hist_yrs) + len(proj_labels))
                    fig_fcf.add_shape(
                        type="line", xref="paper", yref="paper",
                        x0=_sep, x1=_sep, y0=0, y1=0.92,
                        line=dict(color="#30363d", width=1.5, dash="dash"),
                    )
                    fig_fcf.add_annotation(
                        xref="paper", yref="paper",
                        x=_sep - 0.02, y=0.97,
                        text="← Historical",
                        showarrow=False,
                        font=dict(color="#8b949e", size=9, family="Inter"),
                        xanchor="right",
                    )
                    fig_fcf.add_annotation(
                        xref="paper", yref="paper",
                        x=_sep + 0.02, y=0.97,
                        text="Forecast →",
                        showarrow=False,
                        font=dict(color="#10b981", size=9, family="Inter"),
                        xanchor="left",
                    )

                apply_koyfin(fig_fcf, height=340, extra_kw=dict(
                    barmode="group",
                    showlegend=True,
                    yaxis=dict(
                        title=dict(text=f"{to_code}B", font=dict(size=11, color="#8b949e")),
                        gridcolor="#21262d", linecolor="#30363d", zeroline=True,
                        zerolinecolor="#30363d", tickfont=dict(color="#8b949e", size=10),
                    ),
                    yaxis2=dict(
                        title=dict(text="YoY Growth %", font=dict(size=11, color="#f59e0b")),
                        overlaying="y", side="right",
                        gridcolor="rgba(0,0,0,0)", ticksuffix="%",
                        tickfont=dict(color="#f59e0b", size=10), zeroline=False,
                    ),
                    xaxis=dict(
                        type="category", gridcolor="#21262d", linecolor="#30363d",
                        zeroline=False, tickfont=dict(color="#8b949e", size=10), tickangle=-30,
                    ),
                    legend=dict(
                        orientation="h", x=0.0, y=-0.18,
                        bgcolor="rgba(0,0,0,0)", borderwidth=0,
                        font=dict(color="#8b949e", size=11),
                    ),
                ))
                st.plotly_chart(fig_fcf, width="stretch", config={
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                    "toImageButtonOptions": {"filename": f"FCF_{ticker_input}", "scale": 2},
                })

                # ── THREE SCENARIOS
            with st.expander("📊 Fair Value vs Market Price — Bull / Base / Bear Scenarios"):
                # ── IV vs Price ────────────────────────────────────────
                c1, c2 = st.columns(2)
                with c1:
                    ccard("Estimated fair value vs current price", "#10b981")
                    iv_color = "#10b981" if iv_d > price_d else "#ef4444"

                    # Show all 3 scenario IVs + current price
                    bar_x = ["Price"] + [s.split()[0] for s in scenarios.keys()]
                    bar_y = [price_d] + [sdata["iv"] * fx for sdata in scenarios.values()]
                    bar_c = ["#3b82f6"] + [sdata["color"] for sdata in scenarios.values()]

                    # Horizontal bullet gauge: Bear → Base → Bull + price marker
                    _bear_val = scenarios.get("Bear 🐻", {}).get("iv", 0) * fx or price_d * 0.7
                    _base_val = scenarios.get("Base 📊", {}).get("iv", 0) * fx or iv_d
                    _bull_val = scenarios.get("Bull 🐂", {}).get("iv", 0) * fx or price_d * 1.4
                    _min_v = min(_bear_val, price_d) * 0.92
                    _max_v = max(_bull_val, price_d) * 1.05

                    fig_iv = go.Figure()

                    # ── Continuous gradient zone (Bear → Bull) ───────────
                    # Use a filled scatter as the gradient bar background
                    _zone_xs = [_min_v, _bear_val, _base_val, _bull_val, _max_v]
                    _zone_cs = [
                        "rgba(239,68,68,0.35)",
                        "rgba(239,68,68,0.25)",
                        "rgba(245,158,11,0.25)",
                        "rgba(16,185,129,0.25)",
                        "rgba(16,185,129,0.35)",
                    ]
                    for i in range(len(_zone_xs) - 1):
                        fig_iv.add_shape(
                            type="rect", xref="x", yref="paper",
                            x0=_zone_xs[i], x1=_zone_xs[i+1], y0=0.15, y1=0.85,
                            fillcolor=_zone_cs[i], line=dict(width=0), layer="below",
                        )

                    # ── Bear / Base / Bull tick marks ────────────────────
                    for _sv, _slabel, _scolor in [
                        (_bear_val, f"Bear<br>{fmts(_bear_val,sym)}", "#ef4444"),
                        (_base_val, f"Base<br>{fmts(_base_val,sym)}", "#f59e0b"),
                        (_bull_val, f"Bull<br>{fmts(_bull_val,sym)}", "#10b981"),
                    ]:
                        fig_iv.add_shape(type="line", xref="x", yref="paper",
                            x0=_sv, x1=_sv, y0=0.15, y1=0.85,
                            line=dict(color=_scolor, width=1, dash="dot"),
                        )
                        fig_iv.add_annotation(
                            x=_sv, y=1.0, xref="x", yref="paper",
                            text=_slabel, showarrow=False,
                            font=dict(color=_scolor, size=9, family="IBM Plex Mono"),
                            align="center",
                        )

                    # ── Current price — thick gold marker ────────────────
                    fig_iv.add_shape(type="line", xref="x", yref="paper",
                        x0=price_d, x1=price_d, y0=0.0, y1=1.0,
                        line=dict(color="#f59e0b", width=4),
                        layer="above",
                    )
                    fig_iv.add_annotation(
                        x=price_d, y=0.05, xref="x", yref="paper",
                        text=f"▲ {fmts(price_d,sym)}",
                        showarrow=False,
                        font=dict(color="#f59e0b", size=11, family="IBM Plex Mono"),
                        align="center",
                    )

                    # ── MoS % as large overlay text ───────────────────────
                    _mos_txt = f"{mos_pct:+.1f}% vs base"
                    _mos_col = "#10b981" if mos_pct > 0 else "#ef4444"
                    fig_iv.add_annotation(
                        xref="paper", yref="paper", x=0.5, y=0.5,
                        text=f"<b>{_mos_txt}</b>",
                        showarrow=False,
                        font=dict(color=_mos_col, size=13, family="IBM Plex Mono"),
                        align="center",
                        bgcolor="rgba(13,17,23,0.7)",
                        bordercolor=_mos_col, borderwidth=1, borderpad=4,
                    )

                    # ── Invisible scatter for hover ───────────────────────
                    fig_iv.add_trace(go.Scatter(
                        x=[_bear_val, _base_val, _bull_val, price_d],
                        y=[0.5, 0.5, 0.5, 0.5],
                        mode="markers", marker=dict(color="rgba(0,0,0,0)", size=8),
                        text=[f"Bear: {fmts(_bear_val,sym)}", f"Base: {fmts(_base_val,sym)}",
                              f"Bull: {fmts(_bull_val,sym)}", f"Price: {fmts(price_d,sym)}"],
                        hovertemplate="%{text}<extra></extra>",
                    ))
                    apply_koyfin(fig_iv, height=200, extra_kw=dict(
                        showlegend=False,
                        xaxis=dict(
                            title=f"{to_code}/share", range=[_min_v, _max_v],
                            gridcolor="rgba(0,0,0,0)", tickfont=dict(color="#8b949e", size=10),
                            showgrid=False,
                        ),
                        yaxis=dict(visible=False, range=[0, 1]),
                        margin=dict(t=48, b=36, l=20, r=20),
                    ))
                    st.plotly_chart(fig_iv, width="stretch", config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"iv_vs_price","scale":2}})
                    ccard_end()

                with c2:
                    ccard("Where does the fair value come from?", "#f59e0b")
                    # ── True Waterfall chart ─────────────────────────────
                    _sum_pv_fcfs = sum(v/1e9 for v in pv_fcfs_d)
                    _pv_tv       = pv_tv_d / 1e9
                    _ev          = _sum_pv_fcfs + _pv_tv
                    _debt        = -(enriched.get("total_debt", 0) * fx / 1e9)
                    _cash        = enriched.get("total_cash", 0) * fx / 1e9
                    _eq_val      = _ev + _debt + _cash
                    _shares_b    = enriched.get("shares", 1) / 1e9
                    _iv_per_sh   = iv_d  # already in display currency

                    fig_wf = go.Figure(go.Waterfall(
                        name="DCF Build-up",
                        orientation="v",
                        measure=[
                            "relative", "relative", "total",
                            "relative", "relative", "total",
                        ],
                        x=["PV of FCFs", "Terminal Value", "Enterprise Value",
                           "Less Debt", "Plus Cash", "Equity Value"],
                        y=[_sum_pv_fcfs, _pv_tv, 0,
                           _debt, _cash, 0],
                        text=[
                            f"{sym}{_sum_pv_fcfs:.1f}B",
                            f"{sym}{_pv_tv:.1f}B",
                            f"{sym}{_ev:.1f}B",
                            f"{sym}{abs(_debt):.1f}B",
                            f"{sym}{_cash:.1f}B",
                            f"{sym}{_eq_val:.1f}B",
                        ],
                        textposition="inside",
                        textfont=dict(size=9, color="#e6edf3", family="IBM Plex Mono"),
                        hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
                        increasing=dict(marker=dict(color="#10b981", line=dict(width=0))),
                        decreasing=dict(marker=dict(color="#ef4444", line=dict(width=0))),
                        totals=dict(marker=dict(color="#00b4d8", line=dict(width=0))),
                        connector=dict(
                            line=dict(color="#30363d", width=1, dash="dot"),
                            visible=True,
                        ),
                    ))
                    # ── Add IV/share annotation ───────────────────────────
                    fig_wf.add_annotation(
                        xref="paper", yref="paper", x=0.5, y=1.06,
                        text=f"Intrinsic Value / share: <b>{fmts(_iv_per_sh, sym)}</b>",
                        showarrow=False,
                        font=dict(color="#f59e0b", size=12, family="IBM Plex Mono"),
                    )
                    apply_koyfin(fig_wf, height=360, extra_kw=dict(
                        showlegend=False,
                        yaxis=dict(
                            title=f"{to_code}B",
                            gridcolor="#21262d", tickfont=dict(color="#8b949e", size=10),
                        ),
                        xaxis=dict(tickfont=dict(color="#8b949e", size=10)),
                        margin=dict(t=54, b=16, l=56, r=16),
                    ))
                    st.plotly_chart(fig_wf, width="stretch", config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"dcf_waterfall","scale":2}})
                    ccard_end()

                # ── SIMPLE MODE nudge ──────────────────────────
                if not pro_mode:
                    # ═══════════════════════════════════════════════════
                    # LAYER 4 — PRO MODE (Advanced signals)
                    # ═══════════════════════════════════════════════════
                    st.html(
                        '<div style="padding:18px 24px;background:linear-gradient(135deg,#F8FAFC,#EFF6FF);'
                        'border:1px solid #DBEAFE;border-radius:12px;text-align:center;margin:16px 0;">'
                        '<div style="font-size:14px;font-weight:600;color:#1E40AF;margin-bottom:4px;">'
                        '⚡ Want deeper analysis?</div>'
                        '<div style="font-size:13px;color:#64748B;line-height:1.6;">'
                        'Switch to <strong>Pro mode</strong> in the sidebar to unlock '
                        'Sensitivity, Monte Carlo, Market Expectations, EV/EBITDA, and more.</div></div>'
                    )

                # ── FIXED Sensitivity Heatmap (Pro only)
            with (st.expander("🎯 Sensitivity Analysis — How WACC & Growth Rate Affect Fair Value") if pro_mode else st.empty()):
                # ── FIXED Sensitivity Heatmap ──────────────────────────
                # ── TIER CHECK: sensitivity ───────────────────────────
                if not _show_sensitive:
                    blur_and_lock("sensitivity")
                else:
                    sa_df = sensitivity_analysis(
                    projected_fcfs=projected, terminal_fcf_norm=terminal_norm,
                    total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                    shares_outstanding=enriched["shares"], current_price=price_n,
                )
                    sa_display = (sa_df * fx).round(0)

                    # Find base-case cell indices for highlight border
                    _sa_cols = sa_display.columns.tolist()
                    _sa_rows = sa_display.index.tolist()

                    def _parse_sa_val(v):
                        """Parse sensitivity header in ANY format → float.
                        Handles: 'g=1', 'wacc=9.5', '1%', '1.0', '9', '3.0%'
                        """
                        import re as _re
                        s = str(v).strip()
                        # Extract the numeric part after '=' if present
                        if '=' in s:
                            s = s.split('=')[-1].strip()
                        # Remove any non-numeric characters except '.' and '-'
                        s = s.replace('%', '').replace(' ', '')
                        # Extract first number found
                        m = _re.search(r'-?\d+\.?\d*', s)
                        if m:
                            try:
                                return float(m.group())
                            except ValueError:
                                return 0.0
                        return 0.0

                    _base_col_idx = min(range(len(_sa_cols)), key=lambda i: abs(_parse_sa_val(_sa_cols[i]) - terminal_g * 100)) if _sa_cols else 0
                    _base_row_idx = min(range(len(_sa_rows)), key=lambda i: abs(_parse_sa_val(_sa_rows[i]) - wacc * 100)) if _sa_rows else 0

                    fig_sa = go.Figure(go.Heatmap(
                        z=sa_display.values.astype(float),
                        x=[str(c) for c in _sa_cols],
                        y=[str(r) for r in _sa_rows],
                        colorscale=[
                            [0.0,  "#7f1d1d"],
                            [0.25, "#ef4444"],
                            [0.45, "#f59e0b"],
                            [0.55, "#fbbf24"],
                            [0.70, "#10b981"],
                            [1.0,  "#064e3b"],
                        ],
                        zmid=price_d * fx if iv_d > 0 else None,
                        text=[[f"{sym}{v:,.0f}" if not np.isnan(v) else "N/A"
                               for v in row] for row in sa_display.values],
                        texttemplate="%{text}",
                        textfont=dict(size=11, color="#e6edf3", family="IBM Plex Mono"),
                        hovertemplate="WACC: %{y}<br>Terminal g: %{x}<br>IV: %{text}<extra></extra>",
                        showscale=True,
                        colorbar=dict(
                            tickfont=dict(color="#8b949e", size=10),
                            title=dict(text=f"IV ({to_code})", font=dict(color="#8b949e", size=11)),
                            thickness=10, bgcolor="#161b22",
                            bordercolor="#30363d", borderwidth=1,
                        ),
                    ))
                    # Highlight base-case cell
                    fig_sa.add_shape(type="rect",
                        xref="x", yref="y",
                        x0=_base_col_idx - 0.5, x1=_base_col_idx + 0.5,
                        y0=_base_row_idx - 0.5, y1=_base_row_idx + 0.5,
                        line=dict(color="#ffffff", width=2),
                    )
                    fig_sa.add_annotation(
                        text=f"Base case  ·  Current price {fmts(price_d, sym)}",
                        xref="paper", yref="paper", x=0.0, y=1.06,
                        font=dict(color="#8b949e", size=11, family="IBM Plex Mono"),
                        showarrow=False, xanchor="left",
                    )
                    fig_sa.add_annotation(
                        text="Darker green = more undervalued  ·  Red = overvalued",
                        xref="paper", yref="paper", x=1.0, y=1.06,
                        font=dict(color="#8b949e", size=9, family="Inter"),
                        showarrow=False, xanchor="right",
                    )
                    apply_koyfin(fig_sa, height=300, extra_kw=dict(
                        margin=dict(t=44, b=44, l=64, r=90),
                        xaxis=dict(title="Terminal Growth Rate →",
                                   tickfont=dict(size=11, color="#8b949e")),
                        yaxis=dict(title="← WACC",
                                   tickfont=dict(size=11, color="#8b949e")),
                    ))
                    st.plotly_chart(fig_sa, width="stretch", config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"sensitivity","scale":2}})
                    st.caption(f"White border = base case  ·  Green = undervalued  ·  Red = overvalued  ·  Values in {to_code}")
                    ccard_end()

                # ── Monte Carlo (Pro mode + must have results)
                if _show_mc and pro_mode and run_mc and mc_result and mc_result.get("iv_values") is not None:
                    with st.expander("🎲 Monte Carlo Simulation — Probability Range of 1,000 Outcomes"):
                        if True:  # data already validated above
                            mc_arr = mc_result["iv_values"] * fx
                            fig_mc = go.Figure()
                            fig_mc.add_trace(go.Histogram(
                            x=mc_arr, nbinsx=60,
                            marker=dict(color="#3b82f6", opacity=0.85, line=dict(width=0.5, color="#1d4ed8")),
                            name="IV Distribution",
                            ))
                            fig_mc.add_vline(x=price_d, line=dict(color="#ef4444", width=2, dash="dash"),
                                     annotation_text=f"Price {fmts(price_d, sym)}", annotation_font_color="#ef4444")
                            fig_mc.add_vline(x=mc_result["median_iv"]*fx, line=dict(color="#10b981", width=2, dash="dot"),
                                     annotation_text=f"Median IV {fmts(mc_result['median_iv']*fx, sym)}",
                                     annotation_font_color="#10b981")
                            apply_koyfin(fig_mc, height=240, extra_kw=dict(
                                        showlegend=False,
                                        xaxis=dict(title=f"IV ({to_code})", gridcolor="#21262d"),
                                        yaxis=dict(title="Frequency", gridcolor="#21262d"),
                                    ))
                            st.plotly_chart(fig_mc, width="stretch", config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"monte_carlo","scale":2}})
                            mc1,mc2,mc3,mc4,mc5 = st.columns(5)
                            mc1.metric("Median IV",   fmts(mc_result["median_iv"]*fx, sym))
                            mc2.metric("Bear (P10)",  fmts(mc_result["p10"]*fx, sym))
                            mc3.metric("Bull (P90)",  fmts(mc_result["p90"]*fx, sym))
                            mc4.metric("Std Dev",     fmts(mc_result["std_iv"]*fx, sym))
                            mc5.metric("P(Undervalued)", f"{mc_result['prob_undervalued']:.0%}")

                # ── Reverse DCF
            with (st.expander("💡 What Is The Market Pricing In? — Implied Growth Analysis") if pro_mode else st.empty()):
                reverse_dcf_tab.render(
                    enriched=enriched, price_n=price_n, wacc=wacc,
                    terminal_g=terminal_g, forecast_yrs=forecast_yrs,
                    fx=fx, sym=sym,
                )

                # ── EV/EBITDA Multiples
            with (st.expander("⚖️ Peer Comparison — EV/EBITDA & P/E vs Similar Companies") if pro_mode else st.empty()):
                try:
                    ev_res = run_ev_ebitda_analysis(
                        enriched=enriched,
                        current_price=price_n,
                        fx=fx,
                    )

                    if not ev_res.get("applicable"):
                        st.info(f"ℹ️ {ev_res.get('reason', 'EV/EBITDA not applicable for this sector')}")
                    else:
                        ev_colour_map = {"green":("🟢","#0D7A4E","#ECFDF5","#BBF7D0"),
                                         "amber":("🟡","#B45309","#FFFBEB","#FDE68A"),
                                         "red":  ("🔴","#B91C1C","#FEF2F2","#FECACA")}
                        ev_emoji, ev_txt_c, ev_bg_c, ev_bd_c = ev_colour_map.get(
                            ev_res["verdict_colour"], ev_colour_map["amber"])

                        # Verdict banner
                        st.html(f"""
                        <div style="padding:14px 20px;background:{ev_bg_c};
                                    border:1.5px solid {ev_bd_c};border-radius:10px;
                                    margin-bottom:16px;">
                          <div style="font-size:13px;font-weight:700;color:{ev_txt_c};
                                      text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">
                            {ev_emoji} {ev_res['verdict']}
                          </div>
                          <div style="font-size:13px;color:#0F172A;line-height:1.7;">
                            {ev_res['summary']}
                          </div>
                          {f'<div style="font-size:12px;color:#94A3B8;margin-top:6px;">{ev_res["sector_note"]}</div>' if ev_res.get("sector_note") else ""}
                        </div>
                        """)

                        # Metrics row
                        em1, em2, em3, em4, em5 = st.columns(5)
                        em1.metric(
                            "Current EV/EBITDA",
                            f"{ev_res['current_multiple']:.1f}×",
                            help="Enterprise Value ÷ EBITDA at today's market price"
                        )
                        _live_peer = ev_res.get("live_peer_median")
                        em2.metric(
                            "Live peer median",
                            f"{_live_peer:.1f}×" if _live_peer else "Fetching…",
                            delta=f"{(ev_res['current_multiple']/_live_peer - 1)*100:+.0f}% vs peers" if _live_peer else None,
                            delta_color="inverse",
                            help="Current EV/EBITDA of sector peers (live from Yahoo Finance)"
                        )
                        em3.metric(
                            "Damodaran median",
                            f"{ev_res['sector_median']}×",
                            delta=f"{ev_res['multiple_pct']*100:+.0f}% vs long-run",
                            delta_color="inverse",
                            help="Damodaran NYU Jan 2025 long-run sector median — mean reversion target"
                        )
                        _peer_iv = ev_res.get("peer_iv", 0)
                        em4.metric(
                            f"IV at peer median",
                            fmts(_peer_iv, sym) if _peer_iv else "—",
                            help=f"Fair value at current peer multiple ({_live_peer:.0f}×)" if _live_peer else "Peer IV"
                        )
                        em5.metric(
                            f"IV at Damodaran",
                            fmts(ev_res['median_iv'], sym),
                            delta=f"{ev_res['mos_at_median']*100:+.1f}% MoS",
                            delta_color="normal",
                            help=f"Fair value at long-run median ({ev_res['sector_median']}×) — mean reversion scenario"
                        )

                        # Multiple gauge bar chart
                        bear_m  = ev_res["sector_bear"]
                        med_m   = ev_res["sector_median"]
                        bull_m  = ev_res["sector_bull"]
                        curr_m  = ev_res["current_multiple"]

                        fig_ev = go.Figure()

                        # Shaded zones
                        fig_ev.add_vrect(x0=0,      x1=bear_m, fillcolor="#ECFDF5", opacity=0.4, line_width=0)
                        fig_ev.add_vrect(x0=bear_m, x1=med_m,  fillcolor="#FFFBEB", opacity=0.4, line_width=0)
                        fig_ev.add_vrect(x0=med_m,  x1=bull_m, fillcolor="#FEF2F2", opacity=0.4, line_width=0)

                        # Zone labels
                        mid_cheap  = bear_m / 2
                        mid_fair   = (bear_m + med_m) / 2
                        mid_exp    = (med_m + bull_m) / 2
                        for x, label in [(mid_cheap,"Cheap"),(mid_fair,"Fair"),(mid_exp,"Expensive")]:
                            fig_ev.add_annotation(x=x, y=0.9, text=label, showarrow=False,
                                font=dict(size=11, color="#94A3B8"),
                                yref="paper", xanchor="center")

                        # Sector lines
                        for xval, label, clr, dash in [
                            (bear_m, f"Bear {bear_m}×", "#10B981", "dot"),
                            (med_m,  f"Median {med_m}×", "#3B82F6", "solid"),
                            (bull_m, f"Bull {bull_m}×",  "#EF4444", "dot"),
                        ]:
                            fig_ev.add_vline(x=xval, line=dict(color=clr, width=2, dash=dash),
                                annotation_text=label, annotation_font=dict(color=clr, size=11))

                        # Current multiple marker
                        ev_marker_clr = "#0D7A4E" if curr_m <= med_m else "#B91C1C"
                        fig_ev.add_trace(go.Scatter(
                            x=[curr_m], y=[0.5], mode="markers+text",
                            marker=dict(size=18, color=ev_marker_clr, symbol="diamond"),
                            text=[f"{curr_m:.1f}×"], textposition="top center",
                            textfont=dict(size=12, color=ev_marker_clr, family="IBM Plex Mono"),
                            name=f"{ticker_input} today",
                        ))

                        # Bear/Median/Bull IV values
                        ev_iv_x = [ev_res["bear_iv"]/fx, ev_res["median_iv"]/fx, ev_res["bull_iv"]/fx]
                        ev_scenarios = [
                            (bear_m,  f"Bear: {fmts(ev_res['bear_iv'],sym)}",   "#10B981"),
                            (med_m,   f"Base: {fmts(ev_res['median_iv'],sym)}", "#3B82F6"),
                            (bull_m,  f"Bull: {fmts(ev_res['bull_iv'],sym)}",   "#EF4444"),
                        ]
                        for xv, lbl, clr in ev_scenarios:
                            fig_ev.add_annotation(x=xv, y=0.15, text=lbl, showarrow=False,
                                font=dict(size=10, color=clr, family="IBM Plex Mono"),
                                yref="paper", xanchor="center")

                        # Add live peer median line if available
                        _live_m = ev_res.get("live_peer_median")
                        if _live_m:
                            fig_ev.add_vline(
                                x=_live_m,
                                line=dict(color="#8B5CF6", width=2.5, dash="dashdot"),
                                annotation_text=f"Live peers {_live_m:.1f}×",
                                annotation_font=dict(color="#8B5CF6", size=11),
                            )

                        max_x = max(bull_m * 1.3, curr_m * 1.1)
                        apply_koyfin(fig_ev, height=200, extra_kw=dict(
                            margin=dict(t=44, b=20, l=30, r=30),
                            xaxis=dict(title="EV/EBITDA Multiple", range=[0, max_x],
                                       gridcolor="#21262d", ticksuffix="×",
                                       tickfont=dict(color="#8b949e")),
                            yaxis=dict(visible=False, range=[0, 1]),
                            showlegend=False,
                        ))
                        st.plotly_chart(fig_ev, width="stretch",
                                        config={"displayModeBar": False})

                        # Bear/Median/Bull table
                        # Build scenario table with peer IV
                        _piv   = ev_res.get("peer_iv", 0)
                        _lpm   = ev_res.get("live_peer_median")
                        _scenarios  = ["Bear (trough)",   "Live peers (now)", "Damodaran (long-run)", "Bull (premium)"]
                        _multiples  = [f"{bear_m}×",
                                       f"{_lpm:.1f}×" if _lpm else "—",
                                       f"{med_m}×",
                                       f"{bull_m}×"]
                        _ivs        = [
                            fmts(ev_res['bear_iv'], sym),
                            fmts(_piv, sym) if _piv else "—",
                            fmts(ev_res['median_iv'], sym),
                            fmts(ev_res['bull_iv'], sym),
                        ]
                        _vs_today   = [
                            f"{(ev_res['bear_iv']/price_d - 1)*100:+.1f}%",
                            f"{(_piv/price_d - 1)*100:+.1f}%" if _piv and price_d else "—",
                            f"{(ev_res['median_iv']/price_d - 1)*100:+.1f}%",
                            f"{(ev_res['bull_iv']/price_d - 1)*100:+.1f}%",
                        ]
                        _benchmark  = ["Damodaran bear", "Current market", "Damodaran median", "Damodaran bull"]
                        ev_tbl = pd.DataFrame({
                            "Scenario":      _scenarios,
                            "EV/EBITDA":     _multiples,
                            f"IV ({sym})":   _ivs,
                            "vs today":      _vs_today,
                            "Benchmark":     _benchmark,
                        })
                        st.dataframe(ev_tbl, width='stretch', hide_index=True)

                        # Peer breakdown
                        _peers = ev_res.get("peer_data", {}).get("peers", [])
                        _valid_peers = [p for p in _peers if p.get("valid")]
                        if _valid_peers:
                            with st.expander(f"📊 Peer Multiples — {len(_valid_peers)} Comparable Companies"):
                                peer_tbl = pd.DataFrame([
                                    {"Peer": p["ticker"],
                                     "EV/EBITDA": f"{p['multiple']:.1f}×" if p.get("multiple") else "N/A"}
                                    for p in _peers
                                ])
                                st.dataframe(peer_tbl, width='stretch', hide_index=True)
                                st.caption("Live data from Yahoo Finance · Refreshed every hour")

                        st.caption(
                            f"Damodaran NYU Jan 2025 long-run median · "
                            f"Live peers: Yahoo Finance · "
                            f"EBITDA: {ev_res['ebitda_method']}"
                        )

                except Exception as _ev_err:
                    st.warning(f"EV/EBITDA could not run: {_ev_err}")
                    st.exception(_ev_err)

                # ── Historical Fair Value Chart
            with (st.expander("📅 Historical Fair Value vs Actual Price — Model Track Record") if pro_mode else st.empty()):
                try:
                    hist = compute_historical_iv(
                        enriched=enriched,
                        current_price=price_n,
                        current_iv=iv_n,
                        wacc=wacc,
                        terminal_g=terminal_g,
                        forecast_yrs=forecast_yrs,
                        fx=fx,
                    )

                    if not hist["available"]:
                        st.info(f"ℹ️ {hist.get('reason','Historical data not available')}")
                    else:
                        # Summary banner
                        mos = hist["current_mos"]
                        if mos > 0.15:
                            hv_bg, hv_bd, hv_tc = "#ECFDF5","#A7F3D0","#065F46"
                            hv_icon = "🟢"
                        elif mos < -0.15:
                            hv_bg, hv_bd, hv_tc = "#FEF2F2","#FECACA","#991B1B"
                            hv_icon = "🔴"
                        else:
                            hv_bg, hv_bd, hv_tc = "#FFFBEB","#FDE68A","#92400E"
                            hv_icon = "🟡"

                        st.html(f"""
                        <div style="padding:12px 18px;background:{hv_bg};
                                    border:1.5px solid {hv_bd};border-radius:10px;
                                    margin-bottom:16px;font-size:13px;
                                    color:{hv_tc};line-height:1.7;">
                          {hv_icon} {hist['summary']}
                        </div>
                        """)

                        # ── Main chart ────────────────────────────────────
                        labels   = hist["labels"]
                        iv_hist  = hist["iv_history"]
                        curr_px  = hist["current_price"]

                        fig_hv = go.Figure()

                        # ±20% band around fair value (buy/sell zones)
                        iv_upper = [v * 1.20 for v in iv_hist]
                        iv_lower = [v * 0.80 for v in iv_hist]

                        # Green zone (below fair value = buy zone)
                        fig_hv.add_trace(go.Scatter(
                            x=labels + labels[::-1],
                            y=iv_upper + iv_lower[::-1],
                            fill="toself",
                            fillcolor="rgba(5,150,105,0.08)",
                            line=dict(color="rgba(0,0,0,0)"),
                            showlegend=False,
                            hoverinfo="skip",
                            name="±20% band",
                        ))

                        # Upper band line (overvalued threshold)
                        fig_hv.add_trace(go.Scatter(
                            x=labels, y=iv_upper,
                            mode="lines",
                            line=dict(color="rgba(220,38,38,0.3)", width=1, dash="dot"),
                            name="+20% (overvalued)",
                            showlegend=True,
                        ))

                        # Lower band line (undervalued threshold)
                        fig_hv.add_trace(go.Scatter(
                            x=labels, y=iv_lower,
                            mode="lines",
                            line=dict(color="rgba(5,150,105,0.3)", width=1, dash="dot"),
                            name="−20% (undervalued)",
                            showlegend=True,
                        ))

                        # Fair value line (main model output)
                        fig_hv.add_trace(go.Scatter(
                            x=labels, y=iv_hist,
                            mode="lines+markers",
                            line=dict(color="#2563EB", width=2.5),
                            marker=dict(size=7, color="#2563EB",
                                        line=dict(color="#FFFFFF", width=2)),
                            name="Model fair value",
                            hovertemplate=f"Fair value: {sym}%{{y:,.0f}}<extra></extra>",
                        ))

                        # Current price horizontal line
                        fig_hv.add_hline(
                            y=curr_px,
                            line=dict(color="#EF4444", width=2, dash="solid"),
                            annotation_text=f"Today's price: {fmts(curr_px, sym)}",
                            annotation_font=dict(color="#EF4444", size=11),
                        )

                        # Current price dot on "Today" bar
                        if "Today" in labels:
                            today_idx = labels.index("Today")
                            fig_hv.add_trace(go.Scatter(
                                x=["Today"], y=[curr_px],
                                mode="markers",
                                marker=dict(size=14, color="#EF4444",
                                            symbol="diamond",
                                            line=dict(color="#FFFFFF", width=2)),
                                name="Current price",
                                hovertemplate=f"Current price: {sym}{curr_px:,.0f}<extra></extra>",
                            ))

                        # Shade over/under valued regions
                        apply_koyfin(fig_hv, height=260, extra_kw=dict(
                            margin=dict(t=44, b=40, l=60, r=80),
                            xaxis=dict(title="Year", gridcolor="#21262d",
                                       tickfont=dict(size=11, color="#8b949e")),
                            yaxis=dict(title=f"Price per share ({sym})",
                                       gridcolor="#21262d",
                                       tickfont=dict(size=11, color="#8b949e"),
                                       tickprefix=sym),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="left", x=0, font=dict(size=11, color="#8b949e")),
                            hovermode="x unified",
                        ))
                        st.plotly_chart(fig_hv, width="stretch",
                                        config={"displayModeBar": True,
                                                "modeBarButtonsToRemove": ["lasso2d","select2d"],
                                                "toImageButtonOptions": {"filename": f"historical_iv_{ticker_input}", "scale": 2}})

                        # Summary metrics
                        hm1, hm2, hm3, hm4 = st.columns(4)
                        first_iv = iv_hist[0] if iv_hist else 0
                        curr_iv  = iv_hist[-1] if iv_hist else 0
                        iv_cagr  = ((curr_iv / first_iv) ** (1 / max(len(iv_hist)-1, 1)) - 1) if first_iv > 0 else 0

                        hm1.metric(
                            f"Fair value {hist['labels'][0]}",
                            fmts(first_iv, sym),
                            help="Model fair value in the earliest year available"
                        )
                        hm2.metric(
                            "Fair value today",
                            fmts(curr_iv, sym),
                            delta=f"{iv_cagr*100:+.1f}% CAGR",
                            help="Fair value CAGR reflects FCF growth over the period"
                        )
                        hm3.metric(
                            "Current price",
                            fmts(curr_px, sym),
                            delta=f"{mos*100:+.1f}% vs fair value",
                            delta_color="inverse",
                        )
                        hm4.metric(
                            "Model trend",
                            hist["model_trend"].title(),
                            help="Whether our fair value estimate has been rising or falling"
                        )

                        st.caption(
                            "Fair value computed using actual FCF for each historical year "
                            "with same WACC and terminal growth as today's model. "
                            "Not a backtest — shows what our model would have estimated at the time."
                        )

                except Exception as _hv_err:
                    st.warning(f"Historical fair value could not run: {_hv_err}")
                    st.exception(_hv_err)

                # ── Dividend Discount Model
            with (st.expander("💰 DDM — Dividend-Based Valuation (for Income Investors)") if pro_mode else st.empty()):
                # Collect dividend yield from all possible sources
                _div_y1 = enriched.get("dividend_yield", 0) or 0
                _div_y2 = raw.get("dividend_yield", 0) or 0
                _div_r1 = enriched.get("dividend_rate", 0) or 0
                _div_r2 = raw.get("dividend_rate", 0) or 0
                _div_yield_raw = _div_y1 or _div_y2 or 0
                _div_rate_raw  = _div_r1 or _div_r2 or 0
                # Normalize: Yahoo sometimes returns yield as integer % (e.g. 276 = 2.76%)
                # div yield normalized to decimal at source (collector.py)
                pass
                if _div_yield_raw == 0 and _div_rate_raw > 0 and price_n > 0:
                    _div_yield_raw = _div_rate_raw / price_n
                if _div_yield_raw > 0:
                    enriched["dividend_yield"] = _div_yield_raw
                if _div_rate_raw > 0:
                    enriched["dividend_rate"] = _div_rate_raw

                if _div_yield_raw >= 0.005:
                    try:
                        ddm = compute_ddm(
                            enriched=enriched,
                            current_price=price_n,
                            dcf_iv=iv_n,
                            wacc=wacc,
                            fx=fx,
                        )
                        if not ddm["applicable"]:
                            st.info(f"DDM not applicable: {ddm['not_applicable_reason']}")
                        else:
                            sc = ddm["sustainability_colour"]
                            sc_map = {"green":("#065F46","#ECFDF5","#A7F3D0",""),
                                      "amber":("#92400E","#FFFBEB","#FDE68A","⚠️"),
                                      "red":  ("#991B1B","#FEF2F2","#FECACA","🚨")}
                            sc_tc,sc_bg,sc_bd,sc_icon = sc_map.get(sc, sc_map["amber"])
                            st.html(
                                f'''<div style="padding:12px 18px;background:{sc_bg};border:1.5px solid {sc_bd};border-radius:10px;margin-bottom:16px;">
                                <div style="font-size:13px;font-weight:700;color:{sc_tc};margin-bottom:4px;">{sc_icon} {ddm["sustainability_msg"]}</div>
                                <div style="font-size:13px;color:#0F172A;line-height:1.7;">{ddm["summary"]}</div></div>''',
                            )
                            dm1,dm2,dm3,dm4,dm5 = st.columns(5)
                            dm1.metric("Dividend yield",  f"{ddm['div_yield']*100:.2f}%")
                            dm2.metric("Annual dividend", fmts(ddm['div_rate'], sym))
                            dm3.metric("DDM fair value",  fmts(ddm['ddm_iv'], sym), help=ddm['model_used'])
                            dm4.metric("Blended IV",      fmts(ddm['blended_iv'], sym),
                                       delta=f"{ddm['mos_blended']*100:+.1f}% MoS", delta_color="normal")
                            dm5.metric("Payout ratio",    f"{ddm['payout_ratio']*100:.0f}%")
                            st.html(
                                f'''<div style="display:flex;gap:24px;padding:10px 14px;background:#F8FAFC;
                                border:1px solid #E2E8F0;border-radius:8px;margin:8px 0;font-size:13px;">
                                <span>📈 <b>Near-term growth:</b> {ddm["g_high"]*100:.1f}%</span>
                                <span>→</span>
                                <span>📉 <b>Stable growth:</b> {ddm["g_stable"]*100:.1f}%</span>
                                <span style="margin-left:auto;color:#64748B;">{ddm["growth_method"][:45]}</span></div>''',
                            )
                            scen_rows = []
                            for sname, sdata in ddm["scenarios"].items():
                                scen_rows.append({
                                    "Scenario": sname,
                                    "Growth": f"{sdata['g_high']*100:.1f}% → {sdata['g_stable']*100:.1f}%",
                                    f"IV ({sym})": fmts(sdata["iv"], sym),
                                    "MoS": f"{sdata['mos']*100:+.1f}%",
                                })
                            scen_rows.append({"Scenario":"── DCF","Growth":"—",
                                f"IV ({sym})":fmts(ddm["dcf_iv"],sym),"MoS":f"{ddm['mos_dcf']*100:+.1f}%"})
                            scen_rows.append({"Scenario":"⭐ Blended",
                                "Growth":f"{ddm['ddm_weight']:.0%} DDM / {ddm['dcf_weight']:.0%} DCF",
                                f"IV ({sym})":fmts(ddm["blended_iv"],sym),"MoS":f"{ddm['mos_blended']*100:+.1f}%"})
                            st.dataframe(pd.DataFrame(scen_rows), width='stretch', hide_index=True)
                            st.caption(f"Model: {ddm['model_used']} · Required return: {ddm['re']*100:.1f}% · "
                                       f"Blend: {ddm['ddm_weight']:.0%} DDM / {ddm['dcf_weight']:.0%} DCF")
                    except Exception as _ddm_err:
                        st.warning(f"DDM could not run: {_ddm_err}")
                        import traceback; st.code(traceback.format_exc())

                        # ── FCF Yield vs Bond Yield
            with (st.expander("🛡️ Risk-Adjusted Return — FCF Yield vs Risk-Free Bond Rate") if pro_mode else st.empty()):
                # ── FCF Yield vs Bond Yield ────────────────────────────
                try:
                    fy = compute_fcf_yield_analysis(
                        enriched=enriched,
                        current_price=price_n,
                        fx=fx,
                    )

                    YIELD_COLOURS = {
                        "🟢": ("#059669","#ECFDF5","#A7F3D0"),
                        "🔵": ("#2563EB","#EFF6FF","#BFDBFE"),
                        "🟡": ("#D97706","#FFFBEB","#FDE68A"),
                        "🟠": ("#EA580C","#FFF7ED","#FED7AA"),
                        "🔴": ("#DC2626","#FEF2F2","#FECACA"),
                        "⚪": ("#64748B","#F8FAFC","#E2E8F0"),
                    }
                    fy_emoji = fy["verdict_emoji"]
                    fy_txt_c, fy_bg_c, fy_bd_c = YIELD_COLOURS.get(fy_emoji, YIELD_COLOURS["⚪"])

                    # Verdict banner
                    st.html(f"""
                    <div style="padding:14px 20px;background:{fy_bg_c};
                                border:1.5px solid {fy_bd_c};border-radius:10px;
                                margin-bottom:16px;">
                      <div style="font-size:13px;font-weight:700;color:{fy_txt_c};
                                  text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">
                        {fy_emoji} {fy['verdict']}
                      </div>
                      <div style="font-size:13px;color:#0F172A;line-height:1.7;">
                        {fy['summary']}
                      </div>
                    </div>
                    """)

                    # 5 key metrics
                    ym1,ym2,ym3,ym4,ym5 = st.columns(5)
                    ym1.metric(
                        "FCF Yield",
                        f"{fy['fcf_yield']*100:.1f}%",
                        help="Free Cash Flow per share ÷ Current price. "
                             "Higher = more cash earned per dollar invested."
                    )
                    ym2.metric(
                        "Bond Yield",
                        f"{fy['bond_yield']*100:.1f}%",
                        help=f"Risk-free rate: {fy['bond_source']}"
                    )
                    ym3.metric(
                        "Equity Risk Premium",
                        f"{fy['erp']*100:+.1f}%",
                        delta="vs bonds",
                        delta_color="normal" if fy['erp'] > 0 else "inverse",
                        help="FCF Yield minus Bond Yield. Positive = stock pays more than bonds. "
                             "Negative = bonds pay more — you're not being compensated for equity risk."
                    )
                    ym4.metric(
                        f"vs {fy.get('index_label','S&P 500')} avg",
                        f"{fy.get('vs_index', fy.get('vs_sp500',0))*100:+.1f}%",
                        help=f"{fy.get('index_label','S&P 500')} average FCF yield is ~{fy.get('index_avg_fcf_yield', fy['sp500_avg_fcf_yield'])*100:.1f}%. "
                             f"Positive = this stock is cheaper than the index average on FCF basis."
                    )
                    ym5.metric(
                        "Payback period",
                        f"{fy['payback_years']:.0f} yrs" if fy['payback_years'] and fy['payback_years'] < 100 else "100+ yrs",
                        help="Years of current FCF needed to equal the price you pay today. "
                             "Lower is better. S&P 500 average is ~28 years."
                    )

                    # Yield comparison bar chart
                    ctx = fy["context"]
                    fig_fy = go.Figure()

                    bar_colours = [c["colour"] for c in ctx]
                    fig_fy.add_trace(go.Bar(
                        x=[c["label"] for c in ctx],
                        y=[c["value"] * 100 for c in ctx],
                        marker_color=bar_colours,
                        text=[f"{c['value']*100:.1f}%" for c in ctx],
                        textposition="outside",
                        textfont=dict(size=12, family="IBM Plex Mono"),
                    ))

                    # Bond yield reference line
                    fig_fy.add_hline(
                        y=fy["bond_yield"] * 100,
                        line=dict(color="#EF4444", width=2, dash="dot"),
                        annotation_text=f"Bond yield {fy['bond_yield']*100:.1f}%",
                        annotation_font=dict(color="#EF4444", size=11),
                    )

                    # S&P 500 average line
                    fig_fy.add_hline(
                        y=fy["sp500_avg_fcf_yield"] * 100,
                        line=dict(color="#3B82F6", width=1.5, dash="dash"),
                        annotation_text=f"S&P 500 avg {fy['sp500_avg_fcf_yield']*100:.1f}%",
                        annotation_font=dict(color="#3B82F6", size=11),
                    )

                    from utils.chart_layouts import style_fig as _style_fig
                    _style_fig(fig_fy, height=260)
                    fig_fy.update_layout(
                        margin=dict(t=30, b=20, l=40, r=80),
                        yaxis=dict(title="Yield (%)", ticksuffix="%"),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_fy, width="stretch",
                                    config={"displayModeBar": False})

                    # Shareholder yield breakdown
                    if fy["div_yield"] > 0 or fy["buyback_yield"] > 0:
                        st.html("""
                        <div style="font-size:12px;font-weight:700;color:#475569;
                                    text-transform:uppercase;letter-spacing:.07em;
                                    margin-bottom:8px;">Shareholder yield breakdown</div>
                        """)
                        sy1, sy2, sy3 = st.columns(3)
                        sy1.metric("FCF yield",      f"{fy['fcf_yield']*100:.1f}%")
                        sy2.metric("Dividend yield", f"{fy['div_yield']*100:.2f}%")
                        sy3.metric("Total sh. yield",f"{fy['total_sh_yield']*100:.1f}%",
                                   help="FCF yield + dividend yield — total cash return to shareholders")

                    # Key insight box
                    if fy["erp"] < 0:
                        st.html(f"""
                        <div style="padding:12px 16px;background:#FFF7ED;
                                    border:1px solid #FED7AA;border-radius:8px;
                                    font-size:13px;color:#9A3412;margin-top:8px;">
                          ⚠️ <strong>Important context:</strong> This metric does NOT mean the stock is
                          a bad investment. Growth stocks often have low FCF yields because the market
                          is paying for future growth. The question is: <em>is the growth assumption
                          priced into the stock actually going to materialise?</em>
                          Check the <strong>Reverse DCF</strong> above to see what growth rate is implied.
                        </div>
                        """)
                    else:
                        st.html(f"""
                        <div style="padding:12px 16px;background:#ECFDF5;
                                    border:1px solid #A7F3D0;border-radius:8px;
                                    font-size:13px;color:#065F46;margin-top:8px;">
                           <strong>Key insight:</strong> This stock earns more in free cash flow than
                          risk-free bonds. You are being compensated for taking equity risk.
                          This is the foundation of a value investment thesis.
                        </div>
                        """)

                    _idx_lbl = fy.get('index_label','S&P 500')
                    _idx_yld = fy.get('index_avg_fcf_yield', fy['sp500_avg_fcf_yield'])
                    st.caption(f"Bond yield: {fy['bond_source']} · "
                               f"{_idx_lbl} avg FCF yield: ~{_idx_yld*100:.1f}% (long-run) · "
                               f"FCF: Yahoo Finance")

                except Exception as _fy_err:
                    st.warning(f"FCF Yield analysis could not run: {_fy_err}")
                    st.exception(_fy_err)
                ccard_end()

                # ── Quality (Bloomberg-grade redesign)
        if _active == "financials":
            if not enriched:
                st.warning("Analysis data unavailable. Please run a new analysis.")
            else:
                earnings_quality_tab.render(enriched)

        if _active == "consensus":
            if not st.session_state.get("fin_enriched"):
                st.info("Run an analysis first to see this section.")
                st.stop()

            # ══════════════════════════════════════════════════════════
            # DISAGREEMENT ENGINE — Where YieldIQ differs from Wall Street
            # ══════════════════════════════════════════════════════════
            _pt_data = raw.get("finnhub_price_target", {}) if raw else {}
            _rec_trend = raw.get("finnhub_rec_trend", []) if raw else []
            _analyst_mean = float(_pt_data.get("mean", 0)) * fx if _pt_data.get("mean") else 0
            if _analyst_mean > 0 and iv_d > 0:
                _diff_pct = ((iv_d - _analyst_mean) / _analyst_mean * 100)
                if abs(_diff_pct) > 15:
                    if _diff_pct > 15:
                        _dis_color, _dis_bg = "#166534", "#F0FDF4"
                        _dis_msg = (
                            f"Wall Street average target is {sym}{_analyst_mean:,.0f}. "
                            f"YieldIQ model estimates {sym}{iv_d:,.0f} — "
                            f"**{abs(_diff_pct):.0f}% higher** than analyst consensus. "
                            f"Our model sees more value than the street."
                        )
                    else:
                        _dis_color, _dis_bg = "#991B1B", "#FEF2F2"
                        _dis_msg = (
                            f"Wall Street average target is {sym}{_analyst_mean:,.0f}. "
                            f"YieldIQ model estimates {sym}{iv_d:,.0f} — "
                            f"**{abs(_diff_pct):.0f}% lower** than analyst consensus. "
                            f"Analysts may have conflicts — banks rarely issue sell ratings on clients."
                        )
                    st.html(
                        f'<div style="background:{_dis_bg};border:1px solid {"#BBF7D0" if _diff_pct > 0 else "#FECACA"};'
                        f'border-radius:12px;padding:16px 20px;margin-bottom:16px;">'
                        f'<div style="font-size:11px;font-weight:700;color:{_dis_color};'
                        f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;'
                        f'font-family:IBM Plex Mono,monospace;">'
                        f'⚡ Model vs Wall Street — {abs(_diff_pct):.0f}% Disagreement</div>'
                        f'<div style="font-size:13px;color:#334155;line-height:1.7;">{_dis_msg}</div>'
                        f'<div style="font-size:10px;color:#94A3B8;margin-top:6px;">'
                        f'Model estimates are not recommendations. Always do your own research.</div>'
                        f'</div>'
                    )

            if _pt_data and _pt_data.get("mean"):
                ccard("🎯 Analyst Price Target Distribution", "#0f4c75")
                _pt_mean  = float(_pt_data.get("mean",   0)) * fx
                _pt_high  = float(_pt_data.get("high",   0)) * fx
                _pt_low   = float(_pt_data.get("low",    0)) * fx
                _pt_count = int(_pt_data.get("count",    0))
                _pt_src   = _pt_data.get("source", "")

                import plotly.graph_objects as _go_pt

                # ── Range bar: low → mean → high vs current price ──
                _pt_fig = _go_pt.Figure()

                # Range bar (low to high)
                _pt_fig.add_trace(_go_pt.Bar(
                    x=[_pt_high - _pt_low],
                    y=["Price Targets"],
                    base=[_pt_low],
                    orientation="h",
                    marker_color="rgba(59,130,246,0.18)",
                    marker_line=dict(color="rgba(59,130,246,0.5)", width=1.5),
                    name="PT Range",
                    hovertemplate=f"Low: {sym}{_pt_low:,.2f}<br>High: {sym}{_pt_high:,.2f}<extra></extra>",
                ))
                # Mean price target dot
                _pt_fig.add_trace(_go_pt.Scatter(
                    x=[_pt_mean],
                    y=["Price Targets"],
                    mode="markers+text",
                    marker=dict(size=14, color="#2563EB", symbol="diamond"),
                    text=[f"Mean {sym}{_pt_mean:,.2f}"],
                    textposition="top center",
                    textfont=dict(size=11, color="#1D4ED8"),
                    name="Consensus Mean",
                    hovertemplate=f"Consensus Mean: {sym}{_pt_mean:,.2f}<extra></extra>",
                ))
                # Current price line
                _pt_fig.add_vline(
                    x=price_d,
                    line_color="#059669",
                    line_width=2,
                    line_dash="dash",
                    annotation_text=f"Current {sym}{price_d:,.2f}",
                    annotation_position="top right",
                    annotation_font=dict(size=11, color="#059669"),
                )
                _pt_upside = (((_pt_mean - price_d) / price_d) * 100) if price_d else 0
                from utils.chart_layouts import style_fig as _style_fig, T as _T
                _style_fig(_pt_fig, height=170,
                           title_txt=f"Analyst PT: {sym}{_pt_low:,.2f} – {sym}{_pt_high:,.2f}"
                                     f"  ·  {_pt_count} analysts"
                                     + (f"  ·  {_pt_upside:+.1f}% upside to mean" if _pt_upside else ""))
                _pt_fig.update_layout(
                    margin=dict(t=40, b=20, l=10, r=20),
                    showlegend=False,
                    xaxis=dict(title=f"Price ({sym})", tickformat=",.0f"),
                    yaxis=dict(showticklabels=False, showgrid=False),
                )
                st.plotly_chart(_pt_fig, width='stretch')

                # Upside callout badge
                if _pt_upside:
                    _up_c = "#065F46" if _pt_upside > 15 else "#1E40AF" if _pt_upside > 0 else "#7F1D1D"
                    _up_bg = "#D1FAE5" if _pt_upside > 15 else "#DBEAFE" if _pt_upside > 0 else "#FEE2E2"
                    st.html(
                        f'<div style="display:inline-block;background:{_up_bg};color:{_up_c};'
                        f'font-size:12px;font-weight:700;padding:5px 14px;border-radius:14px;">'
                        f'{"📈" if _pt_upside > 0 else "📉"} '
                        f'{_pt_upside:+.1f}% consensus upside to mean · {_pt_count} analyst{"s" if _pt_count != 1 else ""}'
                        f'</div>'
                    )

                # Recommendation trend (stacked bar — last 4 months)
                if _rec_trend:
                    _rt_periods  = [r.get("period", "") for r in _rec_trend[-4:]]
                    _rt_sb  = [r.get("strongBuy",  0) for r in _rec_trend[-4:]]
                    _rt_b   = [r.get("buy",        0) for r in _rec_trend[-4:]]
                    _rt_h   = [r.get("hold",       0) for r in _rec_trend[-4:]]
                    _rt_s   = [r.get("sell",       0) for r in _rec_trend[-4:]]
                    _rt_ss  = [r.get("strongSell", 0) for r in _rec_trend[-4:]]

                    _rt_fig = _go_pt.Figure(data=[
                        _go_pt.Bar(name="Strong Buy",  x=_rt_periods, y=_rt_sb,  marker_color="#059669"),
                        _go_pt.Bar(name="Buy",         x=_rt_periods, y=_rt_b,   marker_color="#34d399"),
                        _go_pt.Bar(name="Hold",        x=_rt_periods, y=_rt_h,   marker_color="#d1d5db"),
                        _go_pt.Bar(name="Sell",        x=_rt_periods, y=_rt_s,   marker_color="#fca5a5"),
                        _go_pt.Bar(name="Strong Sell", x=_rt_periods, y=_rt_ss,  marker_color="#dc2626"),
                    ])
                    _style_fig(_rt_fig, height=220, title_txt="Analyst Recommendation Trend")
                    _rt_fig.update_layout(
                        barmode="stack",
                        margin=dict(t=36, b=20, l=10, r=10),
                        legend=dict(orientation="h", y=-0.25, x=0),
                        yaxis=dict(title="# Analysts"),
                    )
                    st.plotly_chart(_rt_fig, width='stretch')

                ccard_end()
                st.markdown("---")

            # ── SIMPLE MODE nudge for consensus ──────────────────
            if not pro_mode:
                st.html(
                    '<div style="padding:18px 24px;background:linear-gradient(135deg,#F8FAFC,#EFF6FF);'
                    'border:1px solid #DBEAFE;border-radius:12px;text-align:center;margin:16px 0;">'
                    '<div style="font-size:14px;font-weight:600;color:#1E40AF;margin-bottom:4px;">'
                    '⚡ More insights in Pro mode</div>'
                    '<div style="font-size:13px;color:#64748B;line-height:1.6;">'
                    'Switch to <strong>Pro mode</strong> to see Insider Activity, '
                    'Institutional Ownership, and Sector Peers.</div></div>'
                )

            # ══════════════════════════════════════════════════════════
            # SECTION — Insider Activity (Pro only)
            # ══════════════════════════════════════════════════════════
            ccard("🔍 Insider Activity", "#1a1a2e")

            _ins      = raw.get("finnhub_insider", {}) if raw else {}
            _ins_sent = _ins.get("sentiment", "NEUTRAL")
            _ins_net  = _ins.get("net_shares_90d", 0)
            _ins_txns = _ins.get("transactions", [])
            _ins_mo   = _ins.get("monthly_net", {})

            _SENT_CFG = {
                "STRONG BUY":  ("#065F46", "#D1FAE5", "🟢"),
                "BUY":         ("#1E40AF", "#DBEAFE", "🔵"),
                "NEUTRAL":     ("#374151", "#F3F4F6", "⚪"),
                "SELL":        ("#92400E", "#FEF3C7", "🟡"),
                "STRONG SELL": ("#7F1D1D", "#FEE2E2", "🔴"),
            }
            _s_fg, _s_bg, _s_ico = _SENT_CFG.get(_ins_sent, ("#374151", "#F3F4F6", "⚪"))
            _net_dir = "net bought" if _ins_net >= 0 else "net sold"
            _net_abs = abs(_ins_net)

            # Sentiment badge + 90-day net summary
            if _ins:
                _net_color   = '#059669' if _ins_net >= 0 else '#DC2626'
                _net_sign    = '+' if _ins_net >= 0 else ''
                _wacc_nudge  = f'&nbsp;·&nbsp;WACC nudge: {_insider_adj:+.2%}' if _insider_adj != 0 else ''
                st.html(
                    f'<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:16px;">'
                    f'<div style="background:{_s_bg};color:{_s_fg};font-size:13px;font-weight:700;'
                    f'padding:8px 18px;border-radius:20px;letter-spacing:.04em;">'
                    f'{_s_ico} Insider Sentiment: {_ins_sent}</div>'
                    f'<div style="font-size:13px;color:#475569;">'
                    f'90-day net: <b style="color:{_net_color};">'
                    f'{_net_sign}{_ins_net:,} shares {_net_dir}</b>'
                    f'{_wacc_nudge}</div></div>'
                )
            else:
                st.info("Insider transaction data unavailable (requires Finnhub API key).")

            if _ins_txns:
                # ── Last 5 transactions table ─────────────────────
                st.html("""
                <div style="font-size:12px;font-weight:700;color:#475569;
                            text-transform:uppercase;letter-spacing:.07em;
                            margin-bottom:6px;">Recent Transactions (Last 5)</div>
                """)
                _tbl_rows = ""
                for _t in _ins_txns[:5]:
                    _t_color = "#059669" if _t["type"] == "Buy" else "#DC2626"
                    _t_price = f"${_t['price']:,.2f}" if _t["price"] > 0 else "—"
                    _t_val   = f"${_t['value']/1e6:.2f}M" if _t["value"] >= 1e6 \
                                else f"${_t['value']:,.0f}" if _t["value"] > 0 else "—"
                    _t_name  = (_t["name"] or "Unknown")[:28]
                    _tbl_rows += f"""
                    <tr>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                 font-size:12px;color:#0F172A;">{_t_name}</td>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                 font-size:12px;color:#0F172A;">{_t['date']}</td>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;">
                        <span style="background:{'#D1FAE5' if _t['type']=='Buy' else '#FEE2E2'};
                                     color:{_t_color};font-size:11px;font-weight:700;
                                     padding:2px 8px;border-radius:10px;">{_t['type']}</span>
                      </td>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                 font-size:12px;color:#0F172A;text-align:right;">
                        {_t['shares']:,}</td>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                 font-size:12px;color:#0F172A;text-align:right;">
                        {_t_price}</td>
                      <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                 font-size:12px;color:#475569;text-align:right;">
                        {_t_val}</td>
                    </tr>"""
                st.html(f"""
                <div style="overflow-x:auto;border-radius:8px;border:1px solid #E2E8F0;">
                  <table style="width:100%;border-collapse:collapse;">
                    <thead>
                      <tr style="background:#F8FAFC;">
                        <th style="padding:7px 10px;text-align:left;font-size:11px;
                                   color:#64748B;font-weight:600;white-space:nowrap;">
                          INSIDER</th>
                        <th style="padding:7px 10px;text-align:left;font-size:11px;
                                   color:#64748B;font-weight:600;">DATE</th>
                        <th style="padding:7px 10px;text-align:left;font-size:11px;
                                   color:#64748B;font-weight:600;">TYPE</th>
                        <th style="padding:7px 10px;text-align:right;font-size:11px;
                                   color:#64748B;font-weight:600;">SHARES</th>
                        <th style="padding:7px 10px;text-align:right;font-size:11px;
                                   color:#64748B;font-weight:600;">PRICE</th>
                        <th style="padding:7px 10px;text-align:right;font-size:11px;
                                   color:#64748B;font-weight:600;">VALUE</th>
                      </tr>
                    </thead>
                    <tbody>{_tbl_rows}</tbody>
                  </table>
                </div>
                """)

                # ── Net buying/selling bar chart (12 months) ──────
                if _ins_mo:
                    import plotly.graph_objects as _go_ins
                    _sorted_mo = sorted(_ins_mo.items())
                    _mo_labels = [m for m, _ in _sorted_mo]
                    _mo_values = [v for _, v in _sorted_mo]
                    _mo_colors = ["#059669" if v >= 0 else "#DC2626" for v in _mo_values]
                    _fig_ins = _go_ins.Figure(
                        _go_ins.Bar(
                            x=_mo_labels, y=_mo_values,
                            marker_color=_mo_colors,
                            text=[f"{v:+,.0f}" for v in _mo_values],
                            textposition="outside",
                            textfont_size=10,
                        )
                    )
                    _fig_ins.update_layout(
                    )
                    _style_fig(_fig_ins, height=260,
                               title_txt="Monthly Net Insider Share Activity (12M)")
                    _fig_ins.update_layout(
                        margin=dict(t=40, b=30, l=50, r=20),
                        yaxis=dict(title="Net Shares"),
                        showlegend=False,
                    )
                    _fig_ins.add_hline(y=0, line_color="#94A3B8", line_width=1)
                    st.plotly_chart(_fig_ins, width='stretch')

            st.markdown("---")

            # ══════════════════════════════════════════════════════════
            # SECTION — Smart Money (Institutional Ownership)
            # ══════════════════════════════════════════════════════════
            ccard("🏛️ Smart Money — Institutional Ownership", "#0f2942")

            _inst = raw.get("finnhub_institutional", {}) if raw else {}

            if _inst:
                # Persist snapshot to DB so history chart can be built over time
                try:
                    save_institutional_ownership(ticker_input, _inst)
                except Exception:
                    pass

                _it_pct      = _inst.get("total_pct", 0)
                _it_qoq      = _inst.get("qoq_change_pct", 0)
                _it_trend    = _inst.get("trend", "STABLE")
                _it_accum    = _inst.get("accumulation", False)
                _it_avg5     = _inst.get("avg_top5_chg", 0)
                _it_num      = _inst.get("num_holders", 0)
                _it_quarter  = _inst.get("quarter", "")
                _it_holders  = _inst.get("holders", [])

                _TREND_CFG = {
                    "ACCUMULATING": ("#065F46", "#D1FAE5", "📈"),
                    "DISTRIBUTING": ("#7F1D1D", "#FEE2E2", "📉"),
                    "STABLE":       ("#1E3A5F", "#DBEAFE", "➡️"),
                }
                _it_fg, _it_bg, _it_ico = _TREND_CFG.get(_it_trend, ("#374151", "#F3F4F6", "➡️"))
                _qoq_sign = "+" if _it_qoq >= 0 else ""

                # Metric row
                _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                _mc1.metric(
                    "Institutional Ownership",
                    f"{_it_pct:.1f}%",
                    help=f"% of shares outstanding held by {_it_num} reporting institutions"
                )
                _mc2.metric(
                    "QoQ Change",
                    f"{_qoq_sign}{_it_qoq:.2f}%",
                    delta=f"{'▲ Accumulating' if _it_qoq > 0 else '▼ Distributing' if _it_qoq < 0 else 'Stable'}",
                    delta_color="normal" if _it_qoq > 0 else "inverse" if _it_qoq < 0 else "off",
                    help="QoQ change in total institutional share count"
                )
                _mc3.metric(
                    "Top-5 Avg Change",
                    f"{'+' if _it_avg5 >= 0 else ''}{_it_avg5:.1f}%",
                    help="Average QoQ position change across top-5 holders"
                )
                _mc4.metric(
                    "# Institutions",
                    f"{_it_num:,}",
                    help="Number of institutions reporting positions this quarter"
                )

                # Trend badge + optional Institutional Accumulation badge
                _badges_html = f"""
                <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;
                            margin:10px 0 14px;">
                  <span style="background:{_it_bg};color:{_it_fg};font-size:12px;
                               font-weight:700;padding:5px 14px;border-radius:14px;
                               letter-spacing:.03em;">
                    {_it_ico} {_it_trend}
                    {f' · as of {_it_quarter}' if _it_quarter else ''}
                  </span>
                """
                if _it_accum:
                    _badges_html += """
                  <span style="background:#FEF9C3;color:#713F12;font-size:12px;
                               font-weight:700;padding:5px 14px;border-radius:14px;
                               border:1px solid #FDE68A;letter-spacing:.03em;">
                    ⭐ Institutional Accumulation
                  </span>
                """
                _badges_html += "</div>"
                st.html(_badges_html)

                # Top-5 holders table
                if _it_holders:
                    st.html("""
                    <div style="font-size:12px;font-weight:700;color:#475569;
                                text-transform:uppercase;letter-spacing:.07em;
                                margin-bottom:6px;">Top-5 Institutional Holders</div>
                    """)
                    _h_rows = ""
                    for _h in _it_holders:
                        _h_chg = _h.get("change_pct", 0)
                        _h_chg_clr = "#059669" if _h_chg > 0 else "#DC2626" if _h_chg < 0 else "#64748B"
                        _h_chg_sym = "▲" if _h_chg > 0 else "▼" if _h_chg < 0 else "—"
                        _h_sh_chg  = _h.get("change_shares", 0)
                        _h_sh_sign = "+" if _h_sh_chg >= 0 else ""
                        _h_rows += f"""
                        <tr>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:12px;color:#0F172A;font-weight:500;">
                            {_h.get('name','')[:35]}</td>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:12px;color:#0F172A;text-align:right;">
                            {_h.get('shares', 0):,}</td>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:12px;color:#0F172A;text-align:right;">
                            {_h.get('share_pct', 0):.3f}%</td>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:12px;text-align:right;font-weight:600;
                                     color:{_h_chg_clr};">
                            {_h_chg_sym} {abs(_h_chg):.1f}%</td>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:12px;color:{_h_chg_clr};text-align:right;">
                            {_h_sh_sign}{_h_sh_chg:,}</td>
                          <td style="padding:6px 10px;border-bottom:1px solid #E2E8F0;
                                     font-size:11px;color:#94A3B8;text-align:right;">
                            {_h.get('filing_date','')}</td>
                        </tr>"""
                    st.html(f"""
                    <div style="overflow-x:auto;border-radius:8px;border:1px solid #E2E8F0;">
                      <table style="width:100%;border-collapse:collapse;">
                        <thead>
                          <tr style="background:#F8FAFC;">
                            <th style="padding:7px 10px;text-align:left;font-size:11px;
                                       color:#64748B;font-weight:600;">INSTITUTION</th>
                            <th style="padding:7px 10px;text-align:right;font-size:11px;
                                       color:#64748B;font-weight:600;">SHARES HELD</th>
                            <th style="padding:7px 10px;text-align:right;font-size:11px;
                                       color:#64748B;font-weight:600;">% FLOAT</th>
                            <th style="padding:7px 10px;text-align:right;font-size:11px;
                                       color:#64748B;font-weight:600;">QoQ CHG %</th>
                            <th style="padding:7px 10px;text-align:right;font-size:11px;
                                       color:#64748B;font-weight:600;">SHARES ΔQoQ</th>
                            <th style="padding:7px 10px;text-align:right;font-size:11px;
                                       color:#64748B;font-weight:600;">FILED</th>
                          </tr>
                        </thead>
                        <tbody>{_h_rows}</tbody>
                      </table>
                    </div>
                    """)

                # Ownership trend chart from DB history
                _hist = get_institutional_history(ticker_input, quarters=8)
                if len(_hist) >= 2:
                    import plotly.graph_objects as _go_inst
                    _hist_rev = list(reversed(_hist))   # oldest → newest for chart
                    _h_quarters = [r["quarter"] for r in _hist_rev]
                    _h_pcts     = [r["total_pct"] for r in _hist_rev]
                    _h_qoq      = [r["qoq_change"] for r in _hist_rev]

                    _fig_inst = _go_inst.Figure()
                    _fig_inst.add_trace(_go_inst.Scatter(
                        x=_h_quarters, y=_h_pcts,
                        mode="lines+markers+text",
                        name="Institutional %",
                        line=dict(color="#2563EB", width=2.5),
                        marker=dict(size=7, color="#2563EB"),
                        text=[f"{p:.1f}%" for p in _h_pcts],
                        textposition="top center",
                        textfont_size=10,
                        fill="tozeroy",
                        fillcolor="rgba(37,99,235,0.08)",
                        yaxis="y",
                    ))
                    _fig_inst.add_trace(_go_inst.Bar(
                        x=_h_quarters, y=_h_qoq,
                        name="QoQ Δ%",
                        marker_color=["#059669" if v >= 0 else "#DC2626" for v in _h_qoq],
                        opacity=0.7,
                        yaxis="y2",
                    ))
                    _style_fig(_fig_inst, height=270,
                               title_txt="Institutional Ownership Trend")
                    _fig_inst.update_layout(
                        margin=dict(t=40, b=30, l=50, r=60),
                        legend=dict(orientation="h", y=-0.15, x=0),
                        yaxis=dict(title="Total Ownership %", ticksuffix="%"),
                        yaxis2=dict(
                            title="QoQ Δ%", overlaying="y", side="right",
                            showgrid=False, ticksuffix="%",
                            zeroline=True, zerolinecolor=_T()["text3"],
                        ),
                    )
                    st.plotly_chart(_fig_inst, width='stretch')
                elif len(_hist) == 1:
                    st.caption("📊 Ownership trend chart will appear after multiple quarters of data have been recorded.")

            else:
                st.info("Institutional ownership data unavailable (requires Finnhub API key or this endpoint may need a paid plan).")

            st.markdown("---")

            # ── Sector / Peer Comparison (existing content) ───────
            ccard("How does this stock compare to its peers?", "#0f4c75")
            try:
                sr = compute_sector_relative(
                    enriched=enriched,
                    current_price=price_n,
                    current_iv=iv_n,
                    current_mos=mos,
                    fx=fx,
                )

                SR_COLOURS = {
                    "#059669": ("#ECFDF5","#A7F3D0"),
                    "#2563EB": ("#EFF6FF","#BFDBFE"),
                    "#D97706": ("#FFFBEB","#FDE68A"),
                    "#EA580C": ("#FFF7ED","#FED7AA"),
                    "#DC2626": ("#FEF2F2","#FECACA"),
                }
                sr_tc  = sr["verdict_colour"]
                sr_bg, sr_bd = SR_COLOURS.get(sr_tc, ("#F8FAFC","#E2E8F0"))

                # Verdict banner
                st.html(f"""
                <div style="padding:12px 18px;background:{sr_bg};
                            border:1.5px solid {sr_bd};border-radius:10px;
                            margin-bottom:16px;">
                  <div style="font-size:13px;font-weight:700;color:{sr_tc};
                              text-transform:uppercase;letter-spacing:.05em;
                              margin-bottom:4px;">
                    {sr['verdict_emoji']} {sr['verdict']}
                  </div>
                  <div style="font-size:13px;color:#0F172A;line-height:1.7;">
                    {sr['summary']}
                  </div>
                </div>
                """)

                # ── Screener stats panel ──────────────────────────
                screen = sr.get("screener", {})
                if screen.get("available"):
                    sc1, sc2, sc3, sc4 = st.columns(4)
                    sc1.metric(
                        "Sector rank",
                        f"#{screen['rank']} of {screen['rank_of']}",
                        help=f"Ranked by margin of safety vs {screen['total_stocks']} stocks in {sr['sector_name']}"
                    )
                    sc2.metric(
                        "Percentile",
                        f"{screen['percentile']:.0f}th",
                        delta="cheaper than peers" if screen["percentile"] > 60 else
                              "pricier than peers" if screen["percentile"] < 40 else "in line",
                        delta_color="normal" if screen["percentile"] > 60 else
                                    "inverse" if screen["percentile"] < 40 else "off",
                        help="What % of sector peers are cheaper than this stock"
                    )
                    sc3.metric(
                        "Sector median MoS",
                        f"{screen['median_mos']:+.1f}%",
                        help="Median margin of safety across all stocks in this sector"
                    )
                    sc4.metric(
                        "Sector BUY signals",
                        f"{screen['buy_pct']:.0f}%",
                        help=f"% of sector at discount to model estimate. Premium: {screen['sell_pct']:.0f}%"
                    )

                    # Sector signal distribution bar
                    total_known = screen["buy_pct"] + screen["sell_pct"] + screen.get("watch_pct", 0)
                    st.html(f"""
                    <div style="margin:12px 0 8px;font-size:12px;font-weight:700;
                                color:#475569;text-transform:uppercase;letter-spacing:.07em;">
                      Sector signal distribution ({screen['total_stocks']} stocks)
                    </div>
                    <div style="display:flex;height:20px;border-radius:6px;overflow:hidden;gap:2px;">
                      <div style="width:{screen['buy_pct']}%;background:#059669;
                                  display:flex;align-items:center;justify-content:center;
                                  font-size:12px;color:#fff;font-weight:700;min-width:0;">
                        {'BUY ' + str(round(screen['buy_pct'])) + '%' if screen['buy_pct'] > 8 else ''}
                      </div>
                      <div style="width:{screen.get('watch_pct',0)}%;background:#2563EB;
                                  min-width:0;"></div>
                      <div style="flex:1;background:#E2E8F0;min-width:0;"></div>
                      <div style="width:{screen['sell_pct']}%;background:#DC2626;
                                  display:flex;align-items:center;justify-content:center;
                                  font-size:12px;color:#fff;font-weight:700;min-width:0;">
                        {'PREMIUM ' + str(round(screen['sell_pct'])) + '%' if screen['sell_pct'] > 8 else ''}
                      </div>
                    </div>
                    <div style="display:flex;gap:16px;margin-top:4px;font-size:12px;color:#64748B;">
                      <span>🟢 BUY {screen['buy_pct']:.0f}%</span>
                      <span>🔴 SELL {screen['sell_pct']:.0f}%</span>
                      <span>⚪ Other {100-screen['buy_pct']-screen['sell_pct']:.0f}%</span>
                    </div>
                    """)

                    # Top picks in sector
                    top = screen.get("top_picks")
                    if top is not None and not top.empty:
                        with st.expander(f"🏆 Top Picks in {sr['sector_name']} — Ranked by Margin of Safety"):
                            st.dataframe(
                                top.rename(columns={
                                    "ticker":"Ticker",
                                    "price":"Price",
                                    "intrinsic_value":"Fair Value",
                                    "margin_of_safety":"MoS %",
                                    "signal":"Signal",
                                    "fundamental_grade":"Quality",
                                }),
                                width='stretch',
                                hide_index=True,
                            )

                # ── Live peer comparison ──────────────────────────
                peers            = sr.get("peer_metrics", [])
                curr             = sr.get("current_metrics", {})
                _peer_grp_label  = sr.get("peer_group_label", "sector peers")

                if peers or curr:
                    st.html(f"""
                    <div style="margin:16px 0 8px;font-size:12px;font-weight:700;
                                color:#475569;text-transform:uppercase;letter-spacing:.07em;">
                      Head-to-head — {_peer_grp_label}
                    </div>
                    """)

                    # Build comparison table
                    all_rows = []
                    # Current stock first
                    all_rows.append({
                        "Ticker": f"⭐ {curr['ticker']}",
                        "Price/Earnings": f"{curr['pe']:.1f}×" if curr.get("pe") else "—",
                        "Company Value Multiple": f"{curr['ev_ebitda']:.1f}×" if curr.get("ev_ebitda") else "—",
                        "Cash Yield": f"{curr['fcf_yield']:.1f}%" if curr.get("fcf_yield") else "—",
                        "Market Cap ($B)": f"${curr['mktcap_b']:.0f}B" if curr.get("mktcap_b") else "—",
                        "MoS% (analysed stock only)": f"{curr.get('mos_pct',0):+.1f}%",
                    })
                    for p in peers:
                        all_rows.append({
                            "Ticker": p["ticker"],
                            "Price/Earnings": f"{p['pe']:.1f}×" if p.get("pe") else "—",
                            "Company Value Multiple": f"{p['ev_ebitda']:.1f}×" if p.get("ev_ebitda") else "—",
                            "Cash Yield": f"{p['fcf_yield']:.1f}%" if p.get("fcf_yield") else "—",
                            "Market Cap ($B)": f"${p['mktcap_b']:.0f}B" if p.get("mktcap_b") else "—",
                            "MoS% (analysed stock only)": "n/a",
                        })

                    # Peer medians row
                    pm_pe  = sr.get("peer_median_pe")
                    pm_ev  = sr.get("peer_median_ev")
                    pm_fcf = sr.get("peer_median_fcf")
                    all_rows.append({
                        "Ticker": "── Peer median ──",
                        "Price/Earnings": f"{pm_pe:.1f}×" if pm_pe else "—",
                        "Company Value Multiple": f"{pm_ev:.1f}×" if pm_ev else "—",
                        "Cash Yield": f"{pm_fcf:.1f}%" if pm_fcf else "—",
                        "Market Cap ($B)": "—",
                        "MoS% (analysed stock only)": "n/a",
                    })

                    if all_rows:
                        peer_df = pd.DataFrame(all_rows)
                        st.dataframe(peer_df, width='stretch', hide_index=True)

                        # vs peers callout
                        pe_vs   = sr.get("pe_vs_peers")
                        ev_vs   = sr.get("ev_vs_peers")
                        # Guard: discard ratios that are clearly garbage (>500% diff = bad data)
                        if pe_vs is not None and abs(pe_vs) > 5:
                            pe_vs = None
                        if ev_vs is not None and abs(ev_vs) > 5:
                            ev_vs = None
                        if pe_vs is not None or ev_vs is not None:
                            msgs = []
                            if pe_vs is not None:
                                msgs.append(
                                    f"Price vs peers: {pe_vs*100:+.0f}%"
                                    f" — {'more expensive' if pe_vs > 0 else 'cheaper' } than similar companies"
                                )
                            if ev_vs is not None:
                                msgs.append(
                                    f"Company value vs peers: {ev_vs*100:+.0f}%"
                                    f" — {'more expensive' if ev_vs > 0 else 'cheaper'} than similar companies"
                                )
                            if msgs:
                                clr = "#065F46" if (pe_vs or 0) < -0.10 else "#991B1B" if (pe_vs or 0) > 0.20 else "#92400E"
                                bg  = "#ECFDF5" if (pe_vs or 0) < -0.10 else "#FEF2F2" if (pe_vs or 0) > 0.20 else "#FFFBEB"
                                st.html(f"""
                                <div style="padding:8px 14px;background:{bg};
                                            border-radius:8px;font-size:12px;color:{clr};">
                                  {" · ".join(msgs)}
                                </div>
                                """)

                        if not peers:
                            st.caption("💡 Live peer data unavailable — run with internet connection for head-to-head comparison")
                        else:
                            st.caption(
                                f"Peers selected by market cap and sector classification ({_peer_grp_label}). "
                                "Margin of Safety (MoS%) is only computed for the analysed stock."
                            )
                            st.caption("Live peer data: Yahoo Finance — MoS only computed for analysed stock")

            except Exception as _sr_err:
                st.warning(f"Sector relative valuation could not run: {_sr_err}")
            ccard_end()


        # ── Ask AI Analyst tab ─────────────────────────────────
        if _active == "ask_ai":
            try:
                import sys as _sys_ai
                from pathlib import Path as _Path_ai
                _dash_ai = str(_Path_ai(__file__).parent)
                if _dash_ai not in _sys_ai.path:
                    _sys_ai.path.insert(0, _dash_ai)
                from ai_chat import render_ai_chat as _render_ai_chat, build_stock_context as _build_ctx

                # Build analysis_data dict from variables in scope
                _ai_data = {
                    "ticker":                 ticker_input,
                    "company_name":           enriched.get("company_name", ticker_input),
                    "sector":                 enriched.get("sector",        ""),
                    "sym":                    sym,
                    "price":                  price_d,
                    "iv":                     iv_d,
                    "mos_pct":                mos_pct,
                    "signal":                 sig,
                    "wacc":                   wacc,
                    "terminal_g":             terminal_g,
                    "fcf_growth":             enriched.get("fcf_growth",      0),
                    "revenue_growth":         enriched.get("revenue_growth",  0),
                    "op_margin":              enriched.get("op_margin",       0),
                    "gross_margin":           enriched.get("gross_margin",    0),
                    "net_margin":             enriched.get("net_margin",      0),
                    "roe":                    enriched.get("roe",             0),
                    "roce":                   enriched.get("roce",            0),
                    "de_ratio":               enriched.get("de_ratio",        0),
                    "moat_score":             enriched.get("moat_score",      0),
                    "moat_grade":             enriched.get("moat_grade",      ""),
                    "moat_types":             enriched.get("moat_types",      []),
                    "piotroski_score":        enriched.get("piotroski_score", None),
                    "earnings_quality_grade": enriched.get("earnings_quality_grade", ""),
                    "earnings_quality_score": enriched.get("earnings_quality_score", None),
                    "forward_pe":             enriched.get("forward_pe",      0),
                    "ev_ebitda":              enriched.get("ev_ebitda",       0),
                    "fcf_yield":              enriched.get("fcf_yield",       0),
                    "scenarios":              scenarios,
                    "earnings_track_record":  raw.get("earnings_track_record", {}),
                }
                _render_ai_chat(_ai_data)
                st.caption(
                    "⚠️ Model output only — not investment advice. "
                    "YieldIQ is not a registered investment adviser. "
                    "Past model performance does not predict future results."
                )
            except Exception as _ai_err:
                st.error(f"AI chat error: {_ai_err}")

        # ── Download Section ───────────────────────────────────
        st.markdown("---")
        st.html("""
        <div style="font-size:13px;font-weight:700;color:#475569;text-transform:uppercase;
                    letter-spacing:0.04em;margin-bottom:12px;">⬇️ Export & Download</div>
        """)
        dl1, dl2, dl3 = st.columns(3)

        report_data = {
            "price": price_d, "iv": iv_d, "mos_pct": mos_pct,
            "signal": sig, "wacc": wacc, "term_g": terminal_g,
            "rev_growth": enriched.get("revenue_growth", 0),
            "fcf_growth": enriched.get("fcf_growth", 0),
            "op_margin":  enriched.get("op_margin", 0),
            "fund_grade": fs["grade"], "fund_score": fs["score"],
            "entry_signal": pt.get("entry_signal", ""),
            "buy_price": (pt.get("buy_price") or 0) * fx,
            "target_price": (pt.get("target_price") or 0) * fx,
            "stop_loss": (pt.get("stop_loss") or 0) * fx,
            "sl_pct": pt.get("sl_pct", 15),
            "rr_ratio": pt.get("rr_ratio", 0),
            "holding_period": hp.get("label", "N/A"),
            "sum_pv_fcfs": dcf_res.get("sum_pv_fcfs", 0) * fx,
            "pv_tv": pv_tv_d,
            "ev": dcf_res.get("enterprise_value", 0) * fx,
            "debt": enriched["total_debt"] * fx,
            "cash": enriched["total_cash"] * fx,
            "equity": dcf_res.get("equity_value", 0) * fx,
            "shares": enriched["shares"],
            "bear_iv": scenarios.get("Bear 🐻", {}).get("iv", 0) * fx,
            "bull_iv": scenarios.get("Bull 🐂", {}).get("iv", 0) * fx,
            "dcf_only_iv": enriched.get("dcf_iv", 0) * fx,
        }

        # Sensitivity table for Excel
        sa_df_for_excel = sensitivity_analysis(
            projected_fcfs=projected, terminal_fcf_norm=terminal_norm,
            total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
            shares_outstanding=enriched["shares"], current_price=price_n,
        )

        with dl1:
            report_bytes = generate_dcf_report(ticker_input, report_data, scenarios, sym)
            st.download_button(
                "📄 Download DCF Report (.txt)",
                data=report_bytes,
                file_name=f"DCF_{ticker_input}_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain",
                width='stretch',
            )

        with dl2:
            # ── TIER CHECK: report download ────────────────────
            _can_dl, _dl_reason = can_download_report()
            if not _can_dl and limit("reports_per_month") == 0:
                # Free tier — upgrade not yet available
                st.info(
                    "💳 **Pro upgrade coming soon.** "
                    "Email hello@yieldiq.app to get early access."
                )
            elif not _can_dl:
                st.warning(f"📄 {_dl_reason}")
                st.caption(f"Extra reports: ${limit('report_cost'):.2f} each")
                show_report_upsell()
            else:
                # ── Complete 14-Sheet Hedge Fund Model ─────────────
                st.caption(f"📄 {_dl_reason}")
            if _can_dl:
                try:
                    import sys as _sys
                    from pathlib import Path as _Path
                    _project_root = str(_Path(__file__).parent.parent)
                    if _project_root not in _sys.path:
                        _sys.path.insert(0, _project_root)
                    from generate_dcf_excel import generate_institutional_dcf
                    from generate_hf_excel import build_hedge_fund_sheets
                    from generate_portfolio_excel import build_portfolio_sheets
                    import io as _io
                    from openpyxl import load_workbook as _lwb

                    _hf_bytes = generate_institutional_dcf(
                    ticker=ticker_input, enriched=enriched, dcf_res=dcf_res,
                    forecast_result=forecast_result, scenarios=scenarios,
                    wacc_data=wacc_data, wacc=wacc, terminal_g=terminal_g,
                    forecast_yrs=forecast_yrs, sym=sym, to_code=to_code, fx=fx,
                    )
                    _wb = _lwb(filename=_io.BytesIO(_hf_bytes))
                    _wb = build_hedge_fund_sheets(
                    wb=_wb, ticker=ticker_input, enriched=enriched,
                    dcf_res=dcf_res, forecast_result=forecast_result,
                    scenarios=scenarios, wacc_data=wacc_data,
                    wacc=wacc, terminal_g=terminal_g,
                    forecast_yrs=forecast_yrs, sym=sym, fx=fx,
                    )
                    _port_capital = st.session_state.get("portfolio_capital", 10_000_000)
                    _wb = build_portfolio_sheets(
                    wb=_wb, ticker=ticker_input, enriched=enriched,
                    dcf_res=dcf_res, forecast_result=forecast_result,
                    scenarios=scenarios, wacc_data=wacc_data,
                    wacc=wacc, terminal_g=terminal_g,
                    forecast_yrs=forecast_yrs, sym=sym, fx=fx,
                    portfolio_size=_port_capital,
                    )
                    _buf = _io.BytesIO()
                    _wb.save(_buf)
                    if st.download_button(
                        "🏦 Download Complete HF Model (14 Sheets)",
                        data=_buf.getvalue(),
                        file_name=f"{ticker_input}_HedgeFund_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width='stretch',
                    ):
                        record_report()
                        track_event(st.session_state.get("auth_email",""), tier(), "report_download", {"ticker": ticker_input})
                except Exception as _e:
                    st.error(f"HF model error: {str(_e)}")
            st.html(f"""
            <div style="padding:14px 16px;background:#F8FAFC;border:1px solid #E2E8F0;
                        border-radius:8px;text-align:center;">
              <div style="font-size:12px;color:#475569;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.04em;">Analysis as of</div>
              <div style="font-size:13px;font-weight:600;color:#475569;font-family:'IBM Plex Mono',monospace;">
                {datetime.now().strftime('%d %b %Y %H:%M')}
              </div>
              <div style="font-size:12px;color:#64748B;margin-top:6px;">14 sheets: DCF · WACC · FCFF<br>Scenarios · Monte Carlo · Reverse DCF<br>Risk-Reward · Portfolio System</div>
            </div>
            """)

        with dl3:
            # ── PDF Report download ─────────────────────────────
            _can_pdf, _pdf_reason = can_download_pdf()
            if not _can_pdf and limit("pdf_reports_per_month") == 0:
                st.info(
                    "💳 **Pro upgrade coming soon.** "
                    "Email hello@yieldiq.app to get early access."
                )
            elif not _can_pdf:
                st.warning(f"📑 {_pdf_reason}")
                st.caption(f"Extra PDFs: ${limit('pdf_report_cost'):.2f} each")
            else:
                st.caption(f"📑 {_pdf_reason}")
            if _can_pdf:
                try:
                    import sys as _sys2
                    from pathlib import Path as _Path2
                    _dashboard_root = str(_Path2(__file__).parent)
                    if _dashboard_root not in _sys2.path:
                        _sys2.path.insert(0, _dashboard_root)
                    from pdf_report import generate_pdf_report as _gen_pdf
                    _pdf_bytes = _gen_pdf(
                        ticker=ticker_input,
                        enriched=enriched,
                        raw=raw,
                        dcf_res=dcf_res,
                        forecast_result=forecast_result,
                        scenarios=scenarios,
                        inv_plan=inv_plan,
                        wacc_data=wacc_data,
                        wacc=wacc,
                        terminal_g=terminal_g,
                        forecast_yrs=forecast_yrs,
                        sym=sym,
                        to_code=to_code,
                        fx=fx,
                        price_d=price_d,
                        iv_d=iv_d,
                        mos_pct=mos_pct,
                        sig=sig,
                    )
                    if st.download_button(
                        "📑 Download PDF Report (4 pages)",
                        data=_pdf_bytes,
                        file_name=f"{ticker_input}_YieldIQ_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        width='stretch',
                    ):
                        record_pdf_report()
                        track_event(st.session_state.get("auth_email",""), tier(), "pdf_download", {"ticker": ticker_input})
                except Exception as _pdf_e:
                    st.error(f"PDF error: {str(_pdf_e)}")
            st.html(f"""
            <div style="padding:14px 16px;background:#F8FAFC;border:1px solid #E2E8F0;
                        border-radius:8px;text-align:center;">
              <div style="font-size:12px;color:#475569;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.04em;">Report contents</div>
              <div style="font-size:12px;color:#64748B;margin-top:4px;">
                4 pages: Overview · DCF Model<br>Quality Score · Valuation Summary<br>
                <span style="color:#0F2942;font-weight:600;">Starter 5/mo · Pro Unlimited</span>
              </div>
            </div>
            """)

        # ── Full DCF Audit ─────────────────────────────────────
        with st.expander("🔬 Full DCF Model Details — Assumptions & Technical Breakdown"):
            detail = {
                "── MODEL INPUTS ─────────────": "",
                "Required return rate (WACC)":  f"{wacc:.2%}",
                "Long-run growth rate":         f"{terminal_g:.2%}",
                "Starting cash flow growth":    f"{base_growth:.2%}",
                "Cash flow base method":        forecast_result.get("fcf_base_method",""),
                "── HOW WE BUILT THE VALUE ───": "",
                "Present value of cash flows":  fmt(dcf_res.get("sum_pv_fcfs",0)*fx, sym),
                "Terminal value (raw)":         fmt(dcf_res.get("terminal_value",0)*fx, sym),
                "Present value of terminal":    fmt(pv_tv_d, sym),
                "Terminal value % of total":    f"{dcf_res.get('tv_pct_of_ev',0):.0%}",
                "Total enterprise value":       fmt(dcf_res.get("enterprise_value",0)*fx, sym),
                "Less: total debt":             fmt(enriched["total_debt"]*fx, sym),
                "Plus: cash held":              fmt(enriched["total_cash"]*fx, sym),
                "Equity value":                 fmt(dcf_res.get("equity_value",0)*fx, sym),
                "Shares outstanding":           f"{enriched['shares']/1e9:.3f}B",
                "── RESULT ───────────────────": "",
                "Estimated fair value/share":   fmts(iv_d, sym),
                "Current price":                fmts(price_d, sym),
                "Margin of Safety":             f"{mos_pct:+.1f}%",
                "Model verdict": (
                    f"Undervalued by {mos_pct:.1f}%"   if mos_pct >= 5  else
                    f"Overvalued by {abs(mos_pct):.1f}%" if mos_pct <= -5 else
                    "Fairly valued (within ±5%)"
                ),
                "Signal (raw)":                 sig,
                "FX rate used":                 f"1 {native_ccy} = {fx:.6f} {to_code}  (live rate)",
                "Price in native currency":     f"{native_ccy} {price_n:,.2f}",
                "Fair value in native ccy":     f"{native_ccy} {iv_n:,.2f}",
            }
            detail_clean = {k: str(v) if not isinstance(v, str) else v
                           for k, v in detail.items()}
            st.dataframe(pd.DataFrame.from_dict(detail_clean, orient="index", columns=["Value"]),
                         width='stretch')


from ui.helpers import mini_sparkline  # moved to helpers


from ui.helpers import render_fin_table  # moved to helpers

