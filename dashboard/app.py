# dashboard/app.py  v5
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Dashboard
# New in v5:
#   1. Fixed sensitivity heatmap text sizing
#   2. Fixed historical FCF chart (no grey bars)
#   3. Bear/Base/Bull scenario analysis
#   4. DCF Report PDF download per stock
#   5. Excel export with buy/sell/SL formatted
#   6. Larger investment plan card
#   7. Scenario comparison chart
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import sys, os, io, requests
from datetime import datetime
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Force cache clear on deploy — prevents stale data after code fixes
_APP_CACHE_VERSION = "v6_shares_fix"
if st.session_state.get("_cache_version") != _APP_CACHE_VERSION:
    st.cache_data.clear()
    # Also clear collector.py's disk cache
    import pathlib as _pathlib, shutil as _shutil
    _disk_cache_dir = _pathlib.Path.home() / ".yieldiq_cache"
    if _disk_cache_dir.exists():
        _shutil.rmtree(_disk_cache_dir, ignore_errors=True)
    st.session_state["_cache_version"] = _APP_CACHE_VERSION

from features import (
    render_live_price_header,
    render_analyst_consensus,
    render_earnings_calendar,
    render_comparison_watchlist,
)
from portfolio import (
    render_portfolio_tab, init_db, is_in_portfolio,
    init_watchlist_db, add_to_watchlist, is_in_watchlist,
    get_watchlist, remove_from_watchlist,
    init_institutional_db, save_institutional_ownership, get_institutional_history,
    init_sheets_db,
)
import importlib.util as _ob_ilu, pathlib as _ob_pl
_ob_path = _ob_pl.Path(__file__).parent / "onboarding.py"
_ob_spec = _ob_ilu.spec_from_file_location("onboarding", _ob_path)
_ob_mod  = _ob_ilu.module_from_spec(_ob_spec)
_ob_spec.loader.exec_module(_ob_mod)
init_onboarding_db   = _ob_mod.init_onboarding_db
maybe_show_wizard    = _ob_mod.maybe_show_wizard
render_resume_button = _ob_mod.render_resume_button
ob_tooltip           = _ob_mod.tooltip
ob_show_tooltips     = _ob_mod.show_tooltips

# Morning Brief landing page
_mb_path = _ob_pl.Path(__file__).parent / "morning_brief.py"
_mb_spec = _ob_ilu.spec_from_file_location("morning_brief", _mb_path)
_mb_mod  = _ob_ilu.module_from_spec(_mb_spec)
_mb_spec.loader.exec_module(_mb_mod)
render_morning_brief      = _mb_mod.render_morning_brief
push_analysis_to_history  = _mb_mod.push_analysis_to_history

# Admin analytics
_aa_path = _ob_pl.Path(__file__).parent / "admin_analytics.py"
_aa_spec = _ob_ilu.spec_from_file_location("admin_analytics", _aa_path)
_aa_mod  = _ob_ilu.module_from_spec(_aa_spec)
_aa_spec.loader.exec_module(_aa_mod)
init_analytics_db        = _aa_mod.init_analytics_db
track_analysis           = _aa_mod.track_analysis
track_event              = _aa_mod.track_event
render_admin_dashboard   = _aa_mod.render_admin_dashboard

from tabs.backtest_tab import render as render_backtest_tab, init_backtest_db
from tabs import earnings_quality_tab, reverse_dcf_tab, moat_tab, compare_tab
from tabs.earnings_tab import render_earnings_tab
from sector_dashboard import render_sector_dashboard, init_sector_db
from sector_heatmap import render_sector_heatmap
import alerts as _alerts_mod
init_sector_db()
init_backtest_db()
init_db()                      # ensure portfolio DB exists on startup
init_watchlist_db()            # ensure watchlist table exists on startup
init_institutional_db()        # ensure institutional_ownership_history table exists
init_sheets_db()               # ensure user_sheets_settings table exists
_alerts_mod.init_alerts_db()   # ensure price_alerts table exists on startup
init_onboarding_db()           # ensure user_onboarding table exists on startup
init_analytics_db()            # ensure analytics.db tables exist on startup

from data.collector import StockDataCollector
from data.processor import compute_metrics
from models.forecaster import FCFForecaster, compute_wacc, compute_confidence_score
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal,
    sensitivity_analysis, monte_carlo_valuation
)
from screener.momentum import MomentumScorer, calculate_momentum
from screener.scenarios import run_scenarios
from screener.valuation_model import generate_valuation_summary as generate_investment_plan
from screener.reverse_dcf import run_reverse_dcf
from screener.ev_ebitda import run_ev_ebitda_analysis
from screener.piotroski import compute_piotroski_fscore as _piotroski_raw
from screener.fcf_yield import compute_fcf_yield_analysis as _fcf_yield_raw
from screener.historical_iv import compute_historical_iv as _hist_iv_raw

from datetime import date as _date


_sc_path = _ob_pl.Path(__file__).parent / "utils" / "scoring.py"
_sc_spec = _ob_ilu.spec_from_file_location("_yiq_scoring", _sc_path)
_sc_mod  = _ob_ilu.module_from_spec(_sc_spec)
_sc_spec.loader.exec_module(_sc_mod)
compute_yieldiq_score = _sc_mod.compute_yieldiq_score


@st.cache_data(ttl=86400, show_spinner=False)
def compute_piotroski_fscore(enriched_json: str):
    """Cached Piotroski — invalidates daily. Pass enriched as JSON string."""
    import json
    return _piotroski_raw(json.loads(enriched_json))

@st.cache_data(ttl=86400, show_spinner=False)
def compute_fcf_yield_analysis(enriched: dict, current_price: float,
                                fx: float = 1.0):
    return _fcf_yield_raw(enriched=enriched, current_price=current_price, fx=fx)

@st.cache_data(ttl=86400, show_spinner=False)
def compute_historical_iv(enriched: dict, current_price: float,
                           current_iv: float, wacc: float, terminal_g: float,
                           forecast_yrs: int = 10, fx: float = 1.0):
    return _hist_iv_raw(
        enriched=enriched,
        current_price=current_price,
        current_iv=current_iv,
        wacc=wacc,
        terminal_g=terminal_g,
        forecast_yrs=forecast_yrs,
        fx=fx,
    )
# ═══════════════════════════════════════════════════════════════
# INITIALIZE RESULT VARIABLES
# ═══════════════════════════════════════════════════════════════
momentum_result = {'momentum_score': 0, 'grade': 'N/A', 'composite_score': 0}
dcf_res = {}
forecast_result = {}
scenarios = {}
wacc_data = {}
enriched = {}
fin_enriched = {}

from screener.earnings_quality import compute_earnings_quality
from screener.sector_relative import compute_sector_relative
from screener.ddm import compute_ddm
from screener.relative_valuation import (
    check_ticker_dcf_eligibility,
    relative_valuation_only,
)
# Note: ev_ebitda, moat_engine loaded lazily inside analysis block
_cfg_path = _ob_pl.Path(__file__).parent.parent / "utils" / "config.py"
_cfg_spec = _ob_ilu.spec_from_file_location("_yiq_config", _cfg_path)
_cfg_mod  = _ob_ilu.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_cfg_mod)
FORECAST_YEARS = _cfg_mod.FORECAST_YEARS
RESULTS_PATH   = _cfg_mod.RESULTS_PATH
LAUNCH_REGION  = _cfg_mod.LAUNCH_REGION
from ui.helpers import (
    render_skeleton_card, render_empty_state,
    add_tooltip, inject_tooltip_css, FINANCIAL_TOOLTIPS,
)
from ui.styles import (
    inject_theme_css, inject_fonts, inject_main_css,
    inject_typography_css, inject_sidebar_nav_css,
)
# tier_gate lives in the same folder as app.py — use a path-safe import
import importlib.util as _ilu, pathlib as _pl
_tg_path = _pl.Path(__file__).parent / "tier_gate.py"
_tg_spec = _ilu.spec_from_file_location("tier_gate", _tg_path)
_tg_mod  = _ilu.module_from_spec(_tg_spec)
_tg_spec.loader.exec_module(_tg_mod)

init_tier            = _tg_mod.init_tier
tier                 = _tg_mod.tier
is_free              = _tg_mod.is_free
is_premium           = _tg_mod.is_premium
is_pro               = _tg_mod.is_pro
can                  = _tg_mod.can
limit                = _tg_mod.limit
can_analyse          = _tg_mod.can_analyse
record_analysis      = _tg_mod.record_analysis
can_download_report  = _tg_mod.can_download_report
record_report        = _tg_mod.record_report
can_download_pdf     = _tg_mod.can_download_pdf
record_pdf_report    = _tg_mod.record_pdf_report
can_run_screener     = _tg_mod.can_run_screener
record_screener      = _tg_mod.record_screener
check_ticker_allowed = _tg_mod.check_ticker_allowed
upgrade_prompt            = _tg_mod.upgrade_prompt
blur_and_lock             = _tg_mod.blur_and_lock
tier_badge_html           = _tg_mod.tier_badge_html
usage_bar_html            = _tg_mod.usage_bar_html
show_analysis_limit_modal = _tg_mod.show_analysis_limit_modal
show_india_gate_message   = _tg_mod.show_india_gate_message
show_report_upsell        = _tg_mod.show_report_upsell
sidebar_upgrade_button    = _tg_mod.sidebar_upgrade_button

APP_VERSION = "v6"

# ══════════════════════════════════════════════════════════════
# COMPLIANCE DISCLAIMER  (moved to ui/disclaimer.py)
# ══════════════════════════════════════════════════════════════
from ui.disclaimer import show_disclaimer_if_needed, render_view_disclaimer_link

# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="YieldIQ",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════
# Initialize Session State Keys (prevent KeyErrors)
# ══════════════════════════════════════════════════════════════
session_defaults = {
    'sector_dashboard': {},
    'nav': 'Stock Analysis',
    'ticker': '',
    'theme': 'light',
    'disclaimer_shown': False,
    '_tier': 'free',
}

for key, default_value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# Initialise tier gating (reads ?token= from URL)
init_tier()
# Mandatory compliance disclaimer — shown once per session / year
show_disclaimer_if_needed()

# Show first-run onboarding wizard for new users
maybe_show_wizard()

# ══════════════════════════════════════════════════════════════
# CSS  (all styles live in ui/styles.py)
# ══════════════════════════════════════════════════════════════
inject_sidebar_nav_css()
inject_fonts()
inject_tooltip_css()
# ── Theme: inject dark/light CSS overrides (runs on every rerun) ──
inject_theme_css(st.session_state.get("theme", "forest"))
inject_main_css()
inject_typography_css()


# ══════════════════════════════════════════════════════════════
# HELPERS  (moved to utils/data_helpers.py)
# ══════════════════════════════════════════════════════════════
_dh_path = _ob_pl.Path(__file__).parent / "utils" / "data_helpers.py"
_dh_spec = _ob_ilu.spec_from_file_location("_yiq_data_helpers", _dh_path)
_dh_mod  = _ob_ilu.module_from_spec(_dh_spec)
_dh_spec.loader.exec_module(_dh_mod)
CURRENCIES      = _dh_mod.CURRENCIES
_FX_FALLBACK    = _dh_mod._FX_FALLBACK
get_fx_rate     = _dh_mod.get_fx_rate
_get_cache_ttl  = _dh_mod._get_cache_ttl
fetch_stock_data = _dh_mod.fetch_stock_data
_fetch_stock_data_cached = _dh_mod._fetch_stock_data_cached
fmt             = _dh_mod.fmt
fmts            = _dh_mod.fmts
sig_human       = _dh_mod.sig_human
mos_insight     = _dh_mod.mos_insight
plain_kpi_label = _dh_mod.plain_kpi_label
KL              = _dh_mod.KL
apply_koyfin    = _dh_mod.apply_koyfin
CL              = _dh_mod.CL
generate_ai_summary = _dh_mod.generate_ai_summary
fetch_market_overview = _dh_mod.fetch_market_overview
fetch_market_pulse = _dh_mod.fetch_market_pulse
show_upgrade_modal = _dh_mod.show_upgrade_modal
_render_relative_valuation_view = _dh_mod._render_relative_valuation_view

from ui.helpers import ccard, ccard_end  # moved to helpers
from ui.helpers import render_score_dial  # moved to helpers

# ══════════════════════════════════════════════════════════════
# DCF REPORT GENERATORS  (moved to ui/report_generators.py)
# ══════════════════════════════════════════════════════════════
from ui.report_generators import generate_dcf_report, generate_excel_dcf_model


# ══════════════════════════════════════════════════════════════
# SIDEBAR — Bloomberg Terminal style  (moved to ui/sidebar.py)
# ══════════════════════════════════════════════════════════════
from ui.sidebar import render_sidebar
_active_main_tab = st.session_state.get("main_tab", "stock")

_sb = render_sidebar(
    CURRENCIES=CURRENCIES,
    FORECAST_YEARS=FORECAST_YEARS,
    fetch_market_pulse=fetch_market_pulse,
    get_fx_rate=get_fx_rate,
    ob_tooltip=ob_tooltip,
    can=can,
    tier=tier,
    usage_bar_html=usage_bar_html,
    sidebar_upgrade_button=sidebar_upgrade_button,
    render_resume_button=render_resume_button,
)
sym          = _sb["sym"]
to_code      = _sb["to_code"]
cur_key      = _sb["cur_key"]
fx_rate      = _sb["fx_rate"]
fx_inr       = _sb["fx_inr"]
use_auto_wacc = _sb["use_auto_wacc"]
manual_wacc  = _sb["manual_wacc"]
terminal_g   = _sb["terminal_g"]
terminal_pct = int(terminal_g * 100)
forecast_yrs = _sb["forecast_yrs"]
run_mc       = _sb["run_mc"]
pro_mode     = _sb["pro_mode"]
results_file = _sb["results_file"]

# ── "View Disclaimer" sidebar link ────────────────────────────
render_view_disclaimer_link()

# ── PRO MODE CSS INJECTION ────────────────────────────────────
if pro_mode:
    st.html("""
    <style>
    /* PRO MODE — dark dense layout */
    .main .block-container { background: #0d1117 !important; }
    .stApp { background: #0d1117 !important; }
    [data-testid="stMetric"] {
      background: #161b22 !important;
      border: 1px solid #21262d !important;
      border-radius: 8px !important;
      padding: 12px !important;
    }
    [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 11px !important; }
    [data-testid="stMetricValue"] { color: #e6edf3 !important; font-family: 'IBM Plex Mono', monospace !important; }
    [data-testid="stMetricDelta"] { font-family: 'IBM Plex Mono', monospace !important; }
    [data-testid="stExpander"] summary { border-bottom: 1px solid #E2E8F0 !important; }
    [data-testid="stExpander"] summary p { color: #1E293B !important; font-weight: 600 !important; }
    [data-testid="stExpander"] > div { background: #F8FAFC !important; }
    .stTabs [data-baseweb="tab-list"] { background: #161b22 !important; border-bottom: 1px solid #21262d !important; }
    .stTabs [data-baseweb="tab"] { color: #8b949e !important; }
    .stTabs [aria-selected="true"] { color: #00b4d8 !important; border-bottom-color: #00b4d8 !important; }
    p, div, span, label { color: #e6edf3 !important; }
    </style>
    """)


# Market data loaded for sidebar (no display)
mkt = fetch_market_overview() or {}


# Arrow killer removed — was stripping expander labels

# ══════════════════════════════════════════════════════════════
# TRIGGERED-ALERT BANNER
# Check at most once every 5 minutes per browser session.
# Newly-fired alerts are accumulated in session_state so the banner
# persists across reruns until the user clears it in the Alerts tab.
# ══════════════════════════════════════════════════════════════
import time as _time
_al_email = st.session_state.get("auth_email", "")
_al_uid   = _alerts_mod._get_user_id(_al_email)
if _al_uid:
    _al_last = st.session_state.get("_al_last_check_ts", 0)
    if _time.time() - _al_last > 300:   # 5-minute TTL
        _al_newly = _alerts_mod.check_alerts(_al_uid)
        st.session_state["_al_last_check_ts"] = _time.time()
        st.session_state["_al_fired"] = (
            st.session_state.get("_al_fired", []) + _al_newly
        )

_al_fired = st.session_state.get("_al_fired", [])
if _al_fired:
    _al_lines = []
    for _f in _al_fired:
        _al_lines.append(
            f"**{_f['ticker']}** — {_f['label']} "
            f"${_f['target_price']:,.2f} "
            f"(now ${_f['current_price']:,.2f})"
        )
    st.warning(
        "🔔 **Price alert" + ("s" if len(_al_fired) > 1 else "") + " triggered:** "
        + "  ·  ".join(_al_lines)
        + "  —  [Clear in the Alerts tab]"
    )

# ══════════════════════════════════════════════════════════════
# MAIN CONTENT — session-state tab routing
# ══════════════════════════════════════════════════════════════
_ADMIN_MODE = os.environ.get("YIELDIQ_ADMIN", "0") == "1"
# _active_main_tab is already set above (before the sidebar block)


# ══════════════════════════════════════════════════════════════
# TAB — COMPARE STOCKS
# ══════════════════════════════════════════════════════════════
if _active_main_tab == "compare":
    compare_tab.render(st.container())


# ══════════════════════════════════════════════════════════════
# TAB — MARKETS (Sector Heatmap)
# ══════════════════════════════════════════════════════════════
if _active_main_tab == "markets":
    render_sector_heatmap()



# ══════════════════════════════════════════════════════════════
# TAB 1 — SINGLE STOCK ANALYSIS  (moved to tabs/stock_analysis.py)
# ══════════════════════════════════════════════════════════════
from tabs.stock_analysis import render as _render_stock_analysis
if _active_main_tab == "stock":
    _render_stock_analysis()

from ui.helpers import render_fin_table  # moved to helpers



# ══════════════════════════════════════════════════════════════
# TAB 2 — FINANCIAL STATEMENTS  (moved to tabs/financials.py)
# ══════════════════════════════════════════════════════════════
from tabs.financials import render as _render_financials
if _active_main_tab == "financials":
    _render_financials()

# ══════════════════════════════════════════════════════════════
# TAB 3 — SCREENER RESULTS  (moved to tabs/screener_tab.py)
# ══════════════════════════════════════════════════════════════
from tabs.screener_tab import render as _render_screener
if _active_main_tab == "screener":
    _render_screener()

# ══════════════════════════════════════════════════════════════
# TAB — PORTFOLIO
# ══════════════════════════════════════════════════════════════
if _active_main_tab == "portfolio":
    _port_analysed = None
    if st.session_state.get("fin_ticker"):
        _port_analysed = {
            "entry_price":  st.session_state.get("fin_iv_d", 0) and
                            st.session_state.get("fin_enriched", {}).get("price", 0) *
                            st.session_state.get("fin_fx", 1),
            "iv":           st.session_state.get("fin_iv_d", 0),
            "mos_pct":      st.session_state.get("fin_mos_pct", 0),
            "signal":       st.session_state.get("fin_signal", ""),
            "wacc":         st.session_state.get("fin_enriched", {}).get("wacc_used",
                            st.session_state.get("fin_enriched", {}).get("wacc", 0)),
            "to_code":      st.session_state.get("fin_to_code", "USD"),
            "company_name": st.session_state.get("fin_raw", {}).get("company_name", ""),
            "sector":       st.session_state.get("fin_enriched", {}).get("sector_name", ""),
        }
        # Get actual entry price (price * fx)
        _raw_price = st.session_state.get("fin_enriched", {}).get("price", 0)
        _fx_val    = st.session_state.get("fin_fx", 1)
        if _raw_price and _fx_val:
            _port_analysed["entry_price"] = _raw_price * _fx_val

    render_portfolio_tab(
        sym              = sym,
        analysed_ticker  = st.session_state.get("fin_ticker", ""),
        analysed_data    = _port_analysed,
    )


if _active_main_tab == "backtest":
    render_backtest_tab()


# ══════════════════════════════════════════════════════════════
# TAB — EARNINGS CALENDAR
# ══════════════════════════════════════════════════════════════
if _active_main_tab == "earnings":
    render_earnings_tab(ticker=st.session_state.get("fin_ticker", ""))


if _active_main_tab == "sectors":
    render_sector_dashboard()



from tabs.watchlist_tab import render as _render_watchlist
if _active_main_tab == "watchlist":
    _render_watchlist()


if _active_main_tab == "about":

    a1, a2 = st.columns([3, 2])

    with a1:
        st.html("""
        <div style="background:linear-gradient(135deg,#F8FAFC,#F4F6F9);border:1px solid #E2E8F0;
                    border-radius:12px;padding:22px;margin-bottom:14px;">
          <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:14px;">⚙️ How it works</div>
        """)
        features = [
            ("Automatic return rate calculation",  "We use market data to figure out what return rate to expect from a stock (no guesswork needed)", "#3b82f6"),
            ("3 outcome scenarios",                "We model a pessimistic, a likely, and an optimistic case for every stock", "#f59e0b"),
            ("Realistic growth modelling",         "Growth rates gradually slow down over time — just like real businesses", "#8b5cf6"),
            ("Bank stocks handled separately",     "Cash-flow models don't work well for banks — we flag these automatically", "#10b981"),
            ("Quality filter",                     "Low-margin businesses are filtered out to avoid false 'good buy' signals", "#ef4444"),
            ("Currency auto-detection",            "Indian IT companies that report in USD (INFY, WIPRO, etc.) are automatically adjusted", "#06b6d4"),
            ("Model Price Levels",                 "Model-estimated DCF discount threshold, fair value estimate, and risk range — for research purposes only", "#10b981"),
            ("Download report",                    "Download a full analysis report as a text file for any stock you've analysed", "#3b82f6"),
        ]
        for title, desc, color in features:
            st.html(f"""
            <div style="display:flex;gap:12px;margin-bottom:10px;padding:12px 14px;
                        background:#F4F6F9;border:1px solid #E2E8F0;border-radius:8px;
                        border-left:3px solid {color};">
              <div>
                <div style="font-weight:600;color:#1E293B;font-size:12px;margin-bottom:2px;">{title}</div>
                <div style="color:#475569;font-size:12px;line-height:1.6;">{desc}</div>
              </div>
            </div>
            """)
        st.html("</div>")

    with a2:
        st.html("""
        <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:16px;margin-bottom:12px;">
          <div style="font-size:12px;font-weight:700;color:#0F172A;margin-bottom:12px;">What our model signals mean</div>
        """)
        for human_label, internal, cond, color, bg in [
            ("📊 Trading below model estimate",  "Model: Undervalued 🟢",    "Model price > market price by 20%+",  "#0D7A4E","#F0FDF4"),
            ("📉 Slight discount to model value","Model: Slight Discount 🟡","Model price > market price by 5–20%", "#B45309","#FFFBEB"),
            ("⚖️ Near model fair value",          "Model: Fairly Valued 🔵",  "Market price ≈ model fair value",      "#1D4ED8","#EFF6FF"),
            ("📈 Trading above model estimate",  "Model: Overvalued 🔴",     "Market price > model price",           "#B91C1C","#FEF2F2"),
            ("⏳ Not applicable",                "N/A",               "Bank/NBFC or insufficient data",       "#64748b","#F8FAFC"),
        ]:
            st.html(f"""
            <div style="padding:10px 12px;background:{bg};border:1px solid {color}30;
                        border-radius:7px;margin-bottom:6px;">
              <div style="font-weight:700;color:{color};font-size:13px;">{human_label}</div>
              <div style="font-size:11px;color:{color};opacity:0.8;margin-top:2px;">{cond}</div>
            </div>
            """)
        st.html("</div>")

    st.html("""
    <div style="margin-top:8px;padding:18px 20px;background:#FFFBEB;border:1px solid #FDE68A;
                border-radius:10px;">
      <div style="font-weight:700;color:#f59e0b;font-size:13px;margin-bottom:8px;">⚠️ Important Disclosure</div>
      <div style="color:#B45309;font-size:12px;line-height:1.8;">
        <strong>For informational and educational purposes only. Not investment advice.</strong>
        This tool provides quantitative DCF analysis for research purposes. It does not constitute
        a recommendation to buy, sell, or hold any security. Past performance is not indicative of
        future results. All valuations are estimates based on publicly available data and model
        assumptions that may prove incorrect. Users should conduct their own due diligence and
        consult a registered investment advisor (RIA) or licensed financial professional before
        making any investment decisions. This platform is not registered as an investment advisor
        under the Investment Advisers Act of 1940 or any state securities law.
        Data sourced from Yahoo Finance — accuracy not guaranteed.
      </div>
      <div style="color:#92400E;font-size:11px;margin-top:10px;padding-top:8px;
                  border-top:1px solid #FDE68A;font-weight:600;">
        YieldIQ displays model outputs for informational purposes only.
        This is not investment advice. YieldIQ is not a registered investment adviser.
        Past model performance does not guarantee future results.
      </div>
      <div style="color:#92400E;font-size:12px;line-height:1.8;margin-top:10px;
                  padding-top:10px;border-top:1px solid #FDE68A;">
        <strong>Signal definitions:</strong> YieldIQ does not provide personalised investment
        model outputs. The &#39;Undervalued / Overvalued&#39; signals are purely mathematical
        outputs comparing the current market price to a model-estimated intrinsic value derived
        from a Discounted Cash Flow (DCF) analysis. They do <em>not</em> account for your
        personal financial situation, risk tolerance, tax position, investment objectives, or
        time horizon. The model relies on publicly available financial data that may be incomplete,
        delayed, or inaccurate. Intrinsic value estimates are highly sensitive to input assumptions
        (growth rates, discount rates) and can change materially with different inputs. No content
        on this platform should be construed as an offer or solicitation to buy or sell any
        financial instrument. Always consult a qualified financial adviser before making any
        investment decision.
      </div>
    </div>
    """)


# ══════════════════════════════════════════════════════════════
# TAB — ALERTS
# ══════════════════════════════════════════════════════════════
from tabs.alerts_tab import render as _render_alerts
if _active_main_tab == "alerts":
    _render_alerts()

# ══════════════════════════════════════════════════════════════
# TAB — ADMIN ANALYTICS  (YIELDIQ_ADMIN=1 only)
# ══════════════════════════════════════════════════════════════
if _ADMIN_MODE and _active_main_tab == "admin":
    render_admin_dashboard()
