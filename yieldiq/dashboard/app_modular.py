# dashboard/app.py  — routing hub
# ═══════════════════════════════════════════════════════════════
# YieldIQ  ·  Institutional DCF Platform
# Modular version: CSS/JS → ui/styles.py  |  Helpers → ui/helpers.py
#                  Tabs → tabs/*.py
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

# ── Tier gate (local import) ────────────────────────────────────
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
can_run_screener     = _tg_mod.can_run_screener
record_screener      = _tg_mod.record_screener
check_ticker_allowed = _tg_mod.check_ticker_allowed
upgrade_prompt       = _tg_mod.upgrade_prompt
blur_and_lock        = _tg_mod.blur_and_lock
tier_badge_html      = _tg_mod.tier_badge_html
usage_bar_html       = _tg_mod.usage_bar_html

# ── DB init (must run before tabs) ─────────────────────────────
from portfolio import init_db
from backtest import init_backtest_db
from sector_dashboard import init_sector_db
init_sector_db()
init_backtest_db()
init_db()

# ── Page config ─────────────────────────────────────────────────
st.set_page_config(
    page_title="YieldIQ",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_tier()

# ── Styles + JS ─────────────────────────────────────────────────
from ui.styles import inject_all
inject_all()

# ── Helpers (needed by sidebar) ─────────────────────────────────
from ui.helpers import (
    CURRENCIES, get_fx_rate,
    fmt, fmts, KL, apply_koyfin, CL, ccard, ccard_end,
    sig_human, mos_insight,
)
from utils.config import FORECAST_YEARS

# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.html("""
    <div style="padding:4px 0 20px;">
      <div style="display:flex;align-items:center;gap:12px;">
        <div style="width:40px;height:40px;background:linear-gradient(135deg,#1D4ED8,#06B6D4);
                    border-radius:10px;display:flex;align-items:center;justify-content:center;
                    font-size:20px;box-shadow:0 4px 12px rgba(29,78,216,0.4);">📊</div>
        <div>
          <div style="font-size:13px;font-weight:800;
                      background:linear-gradient(90deg,#60A5FA,#22D3EE);
                      -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                      background-clip:text;letter-spacing:-0.02em;">YieldIQ</div>
          <div style="font-size:12px;color:#22D3EE;letter-spacing:0.08em;font-weight:600;text-transform:uppercase;">Stock Insights</div>
        </div>
      </div>
      <div style="height:1px;background:linear-gradient(90deg,#3B82F6,#06B6D4,transparent);margin-top:16px;"></div>
    </div>
    """)

    st.html('<div style="font-size:12px;font-weight:700;color:#38BDF8;letter-spacing:0.08em;text-transform:uppercase;margin:16px 0 8px;">💱 Currency</div>')
    cur_key = st.selectbox("Currency", list(CURRENCIES.keys()), index=1, label_visibility="collapsed", key="sb_currency")
    sym     = CURRENCIES[cur_key]["symbol"]
    to_code = CURRENCIES[cur_key]["code"]

    st.html('<div style="font-size:12px;font-weight:700;color:#38BDF8;letter-spacing:0.08em;text-transform:uppercase;margin:16px 0 8px;">⚙️ Model Settings</div>')

    use_auto_wacc = st.toggle("Auto-calculate required return rate", value=True, key="sb_auto_wacc")
    manual_wacc   = st.slider("Manual required return (%)", 8, 20, 10, 1, format="%d%%", disabled=use_auto_wacc, key="sb_manual_wacc")
    terminal_pct  = st.slider("Long-run growth assumption (%)", 1, 4, 3, 1, format="%d%%", key="sb_terminal_pct")
    terminal_g    = terminal_pct / 100
    forecast_yrs  = st.slider("Years to forecast ahead", 5, 15, FORECAST_YEARS, key="sb_forecast_yrs")
    _mc_allowed = can("monte_carlo")
    run_mc = st.toggle(
        "Run 1,000 valuation simulations",
        value=False,
        disabled=not _mc_allowed,
        help="Upgrade to Pro to unlock" if not _mc_allowed else "Simulates 1,000 possible outcomes to show the range of fair values",
        key="sb_run_mc"
    )
    if not _mc_allowed:
        st.html(
            '<div style="font-size:12px;color:#8492a6;margin-top:-8px;">'
            '🔒 <a href="https://yourdomain.com/pricing.html" target="_blank" '
            'style="color:#5046e4">Pro feature</a></div>',
        )

    # Portfolio capital kept as silent default for HF Excel Kelly sheet
    if "portfolio_capital" not in st.session_state:
        st.session_state["portfolio_capital"] = 10_000_000
    results_file = None  # Screener tab loads from default path automatically

    st.html('<div style="font-size:12px;font-weight:700;color:#38BDF8;letter-spacing:0.08em;text-transform:uppercase;margin:16px 0 8px;">🔄 Data</div>')
    if st.button("Clear Cache & Refresh", width='stretch', key="sb_clear_cache"):
        st.cache_data.clear()
        st.rerun()

    fx_rate = get_fx_rate("USD", to_code)
    fx_inr  = get_fx_rate("INR", to_code)
    st.html(f"""
    <div style="margin-top:16px;padding:12px 14px;background:rgba(255,255,255,0.06);
                border:1px solid rgba(255,255,255,0.1);border-radius:10px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
        <div style="width:7px;height:7px;background:#34D399;border-radius:50%;
                    animation:shimmer 2s ease-in-out infinite;"></div>
        <span style="font-size:12px;color:#34D399;font-weight:700;letter-spacing:0.04em;">LIVE FX</span>
      </div>
      <div style="font-size:12px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;line-height:2;">
        1 USD = <span style="color:#F1F5F9;font-weight:600;">{sym}{fx_rate:,.2f}</span><br>
        1 INR = <span style="color:#F1F5F9;font-weight:600;">{sym}{fx_inr:,.4f}</span>
      </div>
    </div>
    <div style="margin-top:8px;padding:10px 14px;background:rgba(251,191,36,0.08);
                border:1px solid rgba(251,191,36,0.2);border-radius:10px;">
      <div style="font-size:12px;color:#FCD34D;line-height:1.8;">
        ⚠ For informational purposes only<br>
        Not investment advice · Not an RIA<br>
        <span style="color:#64748B;">Data: Yahoo Finance · yfinance</span>
      </div>
    </div>
    """)

    # ── Tier badge + usage bars ────────────────────────────
    _badge_html = tier_badge_html()
    _usage_html = usage_bar_html()
    st.html(
        f'<div style="margin-top:14px;padding:12px 14px;'
        f'background:rgba(255,255,255,0.05);'
        f'border:1px solid rgba(255,255,255,0.1);'
        f'border-radius:10px;">'
        f'<div style="margin-bottom:10px;">' + _badge_html + '</div>'
        + _usage_html +
        '</div>'
    )
    if is_free():
        st.html(
            f'''<a href="https://yourdomain.com/pricing.html" target="_blank"
               style="display:block;text-align:center;margin-top:10px;
                      background:#5046e4;color:#fff;padding:9px 12px;
                      border-radius:8px;font-size:12px;font-weight:600;
                      text-decoration:none;">
              Upgrade to Starter — $19/mo →
            </a>''',
        )


# ══════════════════════════════════════════════════════════════
# TOP NAV
# ══════════════════════════════════════════════════════════════
st.html(f"""
<div style="padding:16px 0 8px;">
  <div style="display:flex;align-items:center;justify-content:space-between;
              padding:14px 24px;
              background:linear-gradient(135deg,#1E2A3A 0%,#1D4ED8 60%,#0891B2 100%);
              border-radius:14px;margin-bottom:16px;
              box-shadow:0 4px 24px rgba(29,78,216,0.25);">
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="width:36px;height:36px;background:rgba(255,255,255,0.15);
                  border-radius:9px;display:flex;align-items:center;justify-content:center;
                  font-size:20px;backdrop-filter:blur(4px);">📊</div>
      <div>
        <div style="font-size:20px;font-weight:800;color:#FFFFFF;letter-spacing:-0.02em;">YieldIQ</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.6);letter-spacing:0.08em;text-transform:uppercase;">Institutional DCF Platform</div>
      </div>
      <div style="margin-left:8px;padding:4px 10px;background:rgba(255,255,255,0.15);
                  border-radius:20px;font-size:12px;color:#FFFFFF;font-weight:700;letter-spacing:0.5px;">v5</div>
    </div>
    <div style="display:flex;align-items:center;gap:20px;">
      <div style="text-align:center;">
        <div style="font-size:12px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.04em;">WACC</div>
        <div style="font-size:13px;font-weight:700;color:#FFFFFF;font-family:'IBM Plex Mono',monospace;">{"Auto" if use_auto_wacc else f"{manual_wacc}%"}</div>
      </div>
      <div style="width:1px;height:28px;background:rgba(255,255,255,0.2);"></div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.04em;">Term. g</div>
        <div style="font-size:13px;font-weight:700;color:#FFFFFF;font-family:'IBM Plex Mono',monospace;">{terminal_pct}%</div>
      </div>
      <div style="width:1px;height:28px;background:rgba(255,255,255,0.2);"></div>
      <div style="text-align:center;">
        <div style="font-size:12px;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.04em;">FX Rate</div>
        <div style="font-size:13px;font-weight:700;color:#34D399;font-family:'IBM Plex Mono',monospace;">1 USD={sym}{fx_rate:,.2f}</div>
      </div>
      <div style="display:flex;align-items:center;gap:6px;padding:6px 12px;
                  background:rgba(52,211,153,0.2);border-radius:20px;
                  border:1px solid rgba(52,211,153,0.3);">
        <div style="width:7px;height:7px;background:#34D399;border-radius:50%;
                    animation:shimmer 2s ease-in-out infinite;"></div>
        <span style="font-size:12px;color:#34D399;font-weight:700;">LIVE</span>
      </div>
    </div>
  </div>
</div>
""")


# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════
tab_stock, tab_fin, tab_screener, tab_portfolio, tab_backtest, tab_sector, tab_watchlist, tab_about = st.tabs([
    "  🔍  Stock Analysis  ",
    "  📑  Financials  ",
    "  📋  Screener  ",
    "  💼  Portfolio  ",
    "  📈  Backtesting  ",
    "  🌐  Sectors  ",
    "  📊  Watchlist  ",
    "  ℹ️  Guide  ",
])


# ══════════════════════════════════════════════════════════════
# TAB 1 — SINGLE STOCK ANALYSIS
# ── Tab routing ─────────────────────────────────────────────────
from tabs.stock_analysis import render_stock_analysis_tab
from tabs.financials      import render_financials_tab
from tabs.misc_tabs       import (
    render_screener_tab, render_portfolio_tab_wrapper,
    render_backtest_tab_wrapper, render_sector_tab,
    render_watchlist_tab,
)
from tabs.guide_tab import render_guide_tab

render_stock_analysis_tab(
    tab_stock,
    manual_wacc=manual_wacc, terminal_pct=terminal_pct,
    forecast_yrs=forecast_yrs, use_auto_wacc=use_auto_wacc,
    run_mc=run_mc, cur_key=cur_key, sym=sym, to_code=to_code,
    fx_rate=fx_rate,
    can=can, limit=limit, can_analyse=can_analyse,
    record_analysis=record_analysis,
    can_download_report=can_download_report, record_report=record_report,
    check_ticker_allowed=check_ticker_allowed, upgrade_prompt=upgrade_prompt,
    blur_and_lock=blur_and_lock,
    tier_badge_html=tier_badge_html, usage_bar_html=usage_bar_html,
)

render_financials_tab(tab_fin)
render_screener_tab(
    tab_screener,
    can_run_screener=can_run_screener, record_screener=record_screener,
    upgrade_prompt=upgrade_prompt, blur_and_lock=blur_and_lock,
    tier_badge_html=tier_badge_html, usage_bar_html=usage_bar_html,
    results_file=results_file, sym=sym,
)
render_portfolio_tab_wrapper(tab_portfolio, sym=sym)
render_backtest_tab_wrapper(tab_backtest)
render_sector_tab(tab_sector)
render_watchlist_tab(tab_watchlist, sym=sym)
render_guide_tab(tab_about)
