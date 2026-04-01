"""dashboard/tabs/stock_analysis.py
Tab 1 — Single Stock Analysis.

Call render_stock_analysis_tab() from app.py.
All sidebar values (wacc, fx, sym, etc.) are passed via st.session_state
so this module doesn't need to re-read them.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json as _json
import io
import requests
from datetime import datetime
import yfinance as yf

from features import (
    render_live_price_header,
    render_analyst_consensus,
    render_earnings_calendar,
    render_comparison_watchlist,
)
from portfolio import render_portfolio_tab, is_in_portfolio
from data.collector import StockDataCollector
from data.processor import compute_metrics
from models.forecaster import FCFForecaster, compute_wacc, compute_confidence_score
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal,
    sensitivity_analysis, monte_carlo_valuation
)
from screener.scenarios import run_scenarios
from screener.valuation_model import generate_valuation_summary as generate_investment_plan
from screener.reverse_dcf import run_reverse_dcf
from screener.ev_ebitda import run_ev_ebitda_analysis
from screener.piotroski import compute_piotroski_fscore
from screener.fcf_yield import compute_fcf_yield_analysis
from screener.historical_iv import compute_historical_iv
from screener.earnings_quality import compute_earnings_quality
from screener.sector_relative import compute_sector_relative
from screener.ddm import compute_ddm
from utils.config import FORECAST_YEARS, RESULTS_PATH

from ui.helpers import (
    fmt, fmts, sig_human, mos_insight, KL, apply_koyfin, apply_yieldiq_theme, CL, ccard, ccard_end,
    CURRENCIES, get_fx_rate, fetch_stock_data,
    add_tooltip, FINANCIAL_TOOLTIPS,
)
from ui.report_generators import generate_dcf_report, generate_excel_dcf_model
from ai_chat import get_gemini_response


# ══════════════════════════════════════════════════════════════════════════════
# AI EXPLAIN HELPER  — reusable "🤖 Explain" button + response card
# ══════════════════════════════════════════════════════════════════════════════

def render_ai_explain(context: str, button_key: str) -> None:
    """
    Renders a right-aligned "🤖 Explain" button.
    When clicked, calls Gemini (or Groq fallback) and displays the
    response in a self-contained st.html() card.

    Parameters
    ----------
    context    : Pre-built plain-English description of the metric/section.
    button_key : Unique Streamlit widget key (must be unique on the page).
    """
    _ai_col1, _ai_col2 = st.columns([5, 1])
    with _ai_col2:
        _explain_clicked = st.button(
            "🤖 Explain",
            key              = button_key,
            use_container_width = True,
            help             = "Ask YieldIQ AI to explain this in plain English",
        )

    if _explain_clicked:
        with st.spinner("YieldIQ AI is thinking…"):
            _question = (
                "Explain this to me in 3-4 sentences using plain English "
                "for a retail investor who is not a finance expert. "
                "Use a simple real-world analogy if it helps. "
                "End with one clear, actionable takeaway — what should I do or watch for?"
            )
            _response = get_gemini_response(
                user_question = _question,
                stock_context = context,
                chat_history  = [],
            )

        # Sanitise for HTML embedding
        _safe_resp = (
            _response
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

        st.html(f"""
<div style="background:linear-gradient(135deg,#EFF6FF 0%,#F0FDF4 100%);
            border:1px solid #BFDBFE;border-radius:12px;
            padding:16px 20px;margin:8px 0 4px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <span style="font-size:16px;">🤖</span>
    <span style="font-weight:700;font-size:13px;color:#1E40AF;
                 font-family:Inter,sans-serif;">YieldIQ AI</span>
    <span style="font-size:11px;color:#64748B;margin-left:auto;
                 font-family:Inter,sans-serif;">Powered by Gemini</span>
  </div>
  <div style="font-size:13px;color:#1E293B;font-family:Inter,sans-serif;
              line-height:1.75;">{_safe_resp}</div>
</div>""")


# ══════════════════════════════════════════════════════════════════════════════
# NEWS + SEC FILINGS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _format_news_time(pub_time: int) -> str:
    """Convert a Unix timestamp to a human-readable relative string."""
    if not pub_time:
        return ""
    try:
        dt    = datetime.fromtimestamp(pub_time)
        delta = datetime.now() - dt
        mins  = delta.seconds // 60
        hours = delta.seconds // 3600
        if delta.days == 0 and mins < 60:
            return f"{mins}m ago"
        if delta.days == 0:
            return f"{hours}h ago"
        if delta.days == 1:
            return "Yesterday"
        if delta.days < 7:
            return f"{delta.days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return ""


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_yf_news(ticker: str) -> list[dict]:
    """Fetch up to 10 news items from yfinance, cached 15 min."""
    try:
        return yf.Ticker(ticker).news or []
    except Exception:
        return []


@st.cache_data(ttl=7200, show_spinner=False)
def _fetch_sec_filings(ticker: str) -> list[dict]:
    """
    Fetch recent 10-K / 10-Q / 8-K filings from SEC EDGAR full-text search.
    Returns a list of dicts: {form, date, description, url}
    """
    try:
        url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q=%22{ticker}%22"
            "&forms=10-K%2C10-Q%2C8-K"
            "&dateRange=custom&startdt=2024-01-01"
            "&_source=period_of_report,entity_name,file_date,form_type,file_num,biz_location"
            "&hits.hits.total.value=1"
            "&hits.hits._source=1"
        )
        headers = {
            "User-Agent": "YieldIQ research@yieldiq.io",
            "Accept":     "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        rows = []
        for hit in hits[:12]:
            src         = hit.get("_source", {})
            form_type   = src.get("form_type", "")
            file_date   = src.get("file_date", "")
            entity      = src.get("entity_name", ticker.upper())
            # Build a direct EDGAR filing URL from the accession number in _id
            filing_id   = hit.get("_id", "")            # e.g. "0001193125-24-123456"
            cik_raw     = src.get("ciks", [""])[0] if src.get("ciks") else ""
            if cik_raw and filing_id:
                accession = filing_id.replace("-", "")
                cik_pad   = str(cik_raw).zfill(10)
                file_url  = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_raw}/{accession}/{filing_id}-index.htm"
                )
            else:
                # Fallback: EDGAR company search page
                file_url = (
                    f"https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&company={ticker}"
                    f"&type={form_type}&dateb=&owner=include&count=10"
                )
            _FORM_LABELS = {
                "10-K":  "Annual report — audited full-year financials",
                "10-Q":  "Quarterly report — unaudited financials",
                "8-K":   "Current report — material event disclosure",
                "DEF 14A": "Proxy statement — executive pay & shareholder votes",
                "S-1":   "IPO registration statement",
            }
            rows.append({
                "form":        form_type,
                "date":        file_date,
                "description": _FORM_LABELS.get(form_type, form_type),
                "entity":      entity,
                "url":         file_url,
            })
        return rows
    except Exception:
        return []


def _render_news_panel(ticker: str, company_name: str) -> None:
    """
    Render a Koyfin-style news sidebar panel using st.html() cards,
    followed by a collapsible SEC Filings expander.
    """
    st.markdown("### 📰 Latest News")

    with st.spinner(""):
        news_items = _fetch_yf_news(ticker)[:8]

    if not news_items:
        st.html("""
<div style="text-align:center;padding:32px;color:#94A3B8;
            font-family:Inter,sans-serif;font-size:13px;">
  No recent news found for this ticker.
</div>""")
    else:
        cards_html = ""
        for item in news_items:
            title      = item.get("title", "")
            source     = item.get("publisher", "")
            url        = item.get("link", "#")
            pub_time   = item.get("providerPublishTime", 0)
            time_str   = _format_news_time(pub_time)
            # Thumbnail (yfinance sometimes includes one)
            thumb_html = ""
            thumb_url  = (item.get("thumbnail") or {})
            if isinstance(thumb_url, dict):
                thumb_url = (thumb_url.get("resolutions") or [{}])[0].get("url", "")
            if thumb_url:
                thumb_html = (
                    f'<img src="{thumb_url}" style="width:56px;height:42px;'
                    f'object-fit:cover;border-radius:6px;flex-shrink:0;" />'
                )

            cards_html += f"""
  <a href="{url}" target="_blank" rel="noopener noreferrer"
     style="display:flex;gap:10px;align-items:flex-start;text-decoration:none;
            padding:11px 0;border-bottom:1px solid #F1F5F9;">
    {thumb_html}
    <div style="flex:1;min-width:0;">
      <div style="font-size:13px;font-weight:600;color:#0F172A;
                  font-family:Inter,sans-serif;line-height:1.4;
                  margin-bottom:5px;
                  display:-webkit-box;-webkit-line-clamp:2;
                  -webkit-box-orient:vertical;overflow:hidden;">{title}</div>
      <div style="display:flex;align-items:center;gap:10px;">
        <span style="font-size:11px;font-weight:500;color:#1D4ED8;
                     font-family:Inter,sans-serif;">{source}</span>
        <span style="font-size:11px;color:#94A3B8;font-family:Inter,sans-serif;">
          {time_str}</span>
      </div>
    </div>
  </a>"""

        st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
            padding:4px 20px 8px;">
  <div style="font-size:12px;font-weight:700;color:#94A3B8;text-transform:uppercase;
              letter-spacing:0.12em;padding:14px 0 4px;">{company_name} — Recent News</div>
  {cards_html}
</div>""")

    # ── SEC Filings expander ────────────────────────────────────────────────
    with st.expander("📄 Recent SEC Filings  (10-K · 10-Q · 8-K)"):
        with st.spinner("Fetching from SEC EDGAR…"):
            filings = _fetch_sec_filings(ticker)

        if not filings:
            edgar_url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&company={ticker}&type=10-K"
                f"&dateb=&owner=include&count=10"
            )
            st.markdown(
                f"No filings found via EDGAR search. "
                f"[Open EDGAR directly ↗]({edgar_url})",
                unsafe_allow_html=False,
            )
        else:
            _FORM_COLORS = {
                "10-K":  ("#1E40AF", "#DBEAFE"),
                "10-Q":  ("#065F46", "#DCFCE7"),
                "8-K":   ("#92400E", "#FEF3C7"),
            }
            rows_html = ""
            for f in filings:
                fc, fbg = _FORM_COLORS.get(f["form"], ("#475569", "#F1F5F9"))
                rows_html += f"""
  <tr>
    <td style="padding:8px 12px;white-space:nowrap;">
      <span style="background:{fbg};color:{fc};font-size:10px;font-weight:700;
                   padding:2px 8px;border-radius:4px;font-family:Inter,sans-serif;">
        {f["form"]}
      </span>
    </td>
    <td style="padding:8px 12px;font-family:'IBM Plex Mono',monospace;
               font-size:12px;color:#475569;white-space:nowrap;">{f["date"]}</td>
    <td style="padding:8px 12px;font-size:12px;color:#0F172A;
               font-family:Inter,sans-serif;">{f["description"]}</td>
    <td style="padding:8px 12px;text-align:right;">
      <a href="{f["url"]}" target="_blank" rel="noopener noreferrer"
         style="font-size:11px;font-weight:600;color:#1D4ED8;
                font-family:Inter,sans-serif;text-decoration:none;">
        View ↗
      </a>
    </td>
  </tr>"""

            st.html(f"""
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif;">
  <thead>
    <tr style="background:#1A2540;">
      <th style="padding:9px 12px;text-align:left;font-size:10px;font-weight:700;
                 color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;
                 white-space:nowrap;">Form</th>
      <th style="padding:9px 12px;text-align:left;font-size:10px;font-weight:700;
                 color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;">Filed</th>
      <th style="padding:9px 12px;text-align:left;font-size:10px;font-weight:700;
                 color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;">Description</th>
      <th style="padding:9px 12px;text-align:right;font-size:10px;font-weight:700;
                 color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;">Link</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</div>
<div style="font-size:10px;color:#94A3B8;padding:8px 0 2px;font-family:Inter,sans-serif;">
  Source: SEC EDGAR · Data refreshed every 2 hours
</div>""")


def render_stock_analysis_tab(
    tab,
    # sidebar values — passed in by app.py after sidebar renders
    manual_wacc: float,
    terminal_pct: int,
    forecast_yrs: int,
    use_auto_wacc: bool,
    run_mc: bool,
    cur_key: str,
    sym: str,
    to_code: str,
    fx_rate: float,
    # tier-gate functions
    can, limit, can_analyse, record_analysis,
    can_download_report, record_report,
    check_ticker_allowed, upgrade_prompt,
    blur_and_lock, tier_badge_html, usage_bar_html,
) -> None:
    """Render the full Stock Analysis tab content."""
    terminal_g = terminal_pct / 100

    # Pre-compute whether results already exist — used by empty-state guard below
    _has_results = bool(
        st.session_state.get("fin_ticker") and
        st.session_state.get("fin_enriched") is not None
    )

    # Popular-chip auto-run: chip buttons set these keys then rerun
    _auto_run    = st.session_state.pop("auto_run", False)
    _auto_ticker = st.session_state.pop("ticker_input", "") if _auto_run else ""

    sc1, sc2, sc3 = st.columns([2, 1, 3])
    with sc1:
        _default_val = _auto_ticker.upper() if _auto_ticker else "TCS.NS"
        ticker_input = st.text_input(
            "Ticker", value=_default_val,
            placeholder="TCS.NS · RELIANCE.NS · AAPL",
            label_visibility="collapsed"
        ).upper().strip()
    with sc2:
        analyse_btn = st.button("🔍 Analyse this stock", width='stretch')
    with sc3:
        st.html("""
        <div style="padding:10px 16px;background:#FFFFFF;border:1px solid #E2E8F0;
                    border-radius:2px;font-size:12px;color:#64748B;letter-spacing:0.05em;">
          NSE: <span style="color:#475569;">TCS.NS · INFY.NS · RELIANCE.NS · HDFCBANK.NS</span>
          &nbsp;·&nbsp; US: <span style="color:#475569;">AAPL · MSFT · GOOGL · NVDA</span>
        </div>
        """)

    # Auto-trigger analysis when a popular chip was clicked
    if _auto_run and _auto_ticker:
        ticker_input = _auto_ticker.upper().strip()
        analyse_btn  = True

    if not analyse_btn and not _has_results:
        st.html("""
<style>
/* ── Hero gradient animation ────────────────────────────────── */
@keyframes yiq-hero-shift {
  0%   { background-position: 0%   50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0%   50%; }
}
@keyframes yiq-fade-up {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0);    }
}
.yiq-hero {
  margin-top: 24px;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(135deg, #0d1f35 0%, #0f2537 40%, #0a3350 70%, #0d2d48 100%);
  background-size: 300% 300%;
  animation: yiq-hero-shift 10s ease infinite;
  padding: 52px 48px 40px;
  text-align: center;
  position: relative;
}
/* Subtle grid overlay */
.yiq-hero::before {
  content: "";
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(0,180,216,0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,180,216,0.06) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}
/* Glow orb */
.yiq-hero::after {
  content: "";
  position: absolute;
  top: -60px; left: 50%; transform: translateX(-50%);
  width: 400px; height: 280px;
  background: radial-gradient(ellipse, rgba(0,180,216,0.18) 0%, transparent 70%);
  pointer-events: none;
}
.yiq-hero-inner {
  position: relative; z-index: 2;
  animation: yiq-fade-up 0.6s ease both;
}
.yiq-hero-eyebrow {
  display: inline-block;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: #00b4d8;
  background: rgba(0,180,216,0.12);
  border: 1px solid rgba(0,180,216,0.3);
  border-radius: 20px;
  padding: 4px 14px;
  margin-bottom: 20px;
}
.yiq-hero-headline {
  font-family: 'Barlow Condensed', 'Inter', sans-serif;
  font-size: 42px; font-weight: 700; line-height: 1.15;
  color: #FFFFFF;
  letter-spacing: -0.01em;
  margin-bottom: 16px;
  max-width: 680px; margin-left: auto; margin-right: auto;
}
.yiq-hero-headline span {
  background: linear-gradient(90deg, #00b4d8, #38e8ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.yiq-hero-sub {
  font-size: 15px; font-weight: 400; line-height: 1.7;
  color: rgba(255,255,255,0.65);
  max-width: 520px; margin: 0 auto 36px;
}
/* Value prop cards */
.yiq-cards {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  max-width: 760px;
  margin: 0 auto 32px;
}
.yiq-card {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 18px 16px;
  text-align: left;
  transition: background 0.2s, border-color 0.2s;
}
.yiq-card:hover {
  background: rgba(0,180,216,0.1);
  border-color: rgba(0,180,216,0.35);
}
.yiq-card-icon {
  font-size: 22px; margin-bottom: 8px; display: block;
}
.yiq-card-title {
  font-size: 13px; font-weight: 600; color: #FFFFFF;
  margin-bottom: 4px; letter-spacing: 0.01em;
}
.yiq-card-desc {
  font-size: 11px; color: rgba(255,255,255,0.5);
  line-height: 1.55;
}
/* Trust bar */
.yiq-trust {
  font-size: 11px; color: rgba(255,255,255,0.35);
  letter-spacing: 0.06em;
  margin-bottom: 24px;
}
.yiq-trust strong {
  color: rgba(255,255,255,0.55);
  font-weight: 500;
}
/* Ticker examples */
.yiq-tickers {
  display: flex; align-items: center; justify-content: center;
  flex-wrap: wrap; gap: 6px;
  margin-top: 4px;
}
.yiq-ticker-chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; font-weight: 500;
  color: rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 3px 9px;
}
.yiq-ticker-sep {
  color: rgba(255,255,255,0.2);
  font-size: 11px;
}
.yiq-ticker-label {
  font-size: 11px; color: rgba(255,255,255,0.3);
  margin-right: 4px;
}
</style>

<div class="yiq-hero">
  <div class="yiq-hero-inner">

    <div class="yiq-hero-eyebrow">Institutional-Grade Stock Analysis</div>

    <div class="yiq-hero-headline">
      Know What a Stock Is<br><span>Really Worth</span> — Before You Invest
    </div>

    <div class="yiq-hero-sub">
      DCF-powered intrinsic value, margin of safety, scenario analysis,
      and quality scoring — in plain English.
    </div>

    <div class="yiq-cards">
      <div class="yiq-card">
        <span class="yiq-card-icon">📊</span>
        <div class="yiq-card-title">Intrinsic Value</div>
        <div class="yiq-card-desc">DCF-based fair value with margin of safety and 3 scenario analysis</div>
      </div>
      <div class="yiq-card">
        <span class="yiq-card-icon">🏢</span>
        <div class="yiq-card-title">Company Quality</div>
        <div class="yiq-card-desc">Revenue trends, profit margins, debt levels and earnings consistency</div>
      </div>
      <div class="yiq-card">
        <span class="yiq-card-icon">⚡</span>
        <div class="yiq-card-title">Live Data</div>
        <div class="yiq-card-desc">Real-time price vs estimated value — updated every minute</div>
      </div>
    </div>

    <div class="yiq-trust">
      <strong>Trusted analytical framework</strong> · DCF · Economic Moat · Monte Carlo · Piotroski Score
    </div>

    <div class="yiq-tickers">
      <span class="yiq-ticker-label">Try:</span>
      <span class="yiq-ticker-chip">TCS.NS</span>
      <span class="yiq-ticker-chip">RELIANCE.NS</span>
      <span class="yiq-ticker-chip">INFY.NS</span>
      <span class="yiq-ticker-sep">·</span>
      <span class="yiq-ticker-chip">AAPL</span>
      <span class="yiq-ticker-chip">MSFT</span>
      <span class="yiq-ticker-chip">NVDA</span>
      <span class="yiq-ticker-chip">GOOGL</span>
    </div>

  </div>
</div>
        """)

        # ── HOW IT WORKS — 3 steps ─────────────────────────────────
        st.html("""
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;
            gap:16px;margin:24px 0 20px;">
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
              padding:20px;text-align:center;
              box-shadow:0 1px 4px rgba(15,23,42,0.05);">
    <div style="font-size:28px;margin-bottom:8px;">1️⃣</div>
    <div style="font-weight:700;font-size:14px;color:#0F172A;margin-bottom:6px;">
      Enter Any US Ticker</div>
    <div style="font-size:12px;color:#64748B;line-height:1.5;">
      Type AAPL, MSFT, NVDA or any US stock symbol above</div>
  </div>
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
              padding:20px;text-align:center;
              box-shadow:0 1px 4px rgba(15,23,42,0.05);">
    <div style="font-size:28px;margin-bottom:8px;">2️⃣</div>
    <div style="font-weight:700;font-size:14px;color:#0F172A;margin-bottom:6px;">
      AI Runs the Analysis</div>
    <div style="font-size:12px;color:#64748B;line-height:1.5;">
      Our ML model forecasts FCF growth and runs a 10-year DCF</div>
  </div>
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
              padding:20px;text-align:center;
              box-shadow:0 1px 4px rgba(15,23,42,0.05);">
    <div style="font-size:28px;margin-bottom:8px;">3️⃣</div>
    <div style="font-weight:700;font-size:14px;color:#0F172A;margin-bottom:6px;">
      Get Your Signal</div>
    <div style="font-size:12px;color:#64748B;line-height:1.5;">
      BUY, WATCH, HOLD or SELL with full reasoning</div>
  </div>
</div>
""")

        # ── POPULAR STOCK CHIPS ────────────────────────────────────
        # Scoped to section[data-testid="stMain"] so sidebar buttons are NOT affected
        st.markdown("""<style>
section[data-testid="stMain"] .stButton > button {
    background: #EFF6FF !important;
    border: 1px solid #BFDBFE !important;
    color: #1D4ED8 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    border-radius: 20px !important;
    padding: 4px 12px !important;
    transition: all 0.15s ease !important;
}
section[data-testid="stMain"] .stButton > button:hover {
    background: #1D4ED8 !important;
    color: white !important;
    border-color: #1D4ED8 !important;
}
</style>""", unsafe_allow_html=True)

        st.markdown(
            '<p style="font-size:13px;font-weight:600;color:#374151;margin:4px 0 10px;">'
            'Try a popular stock:</p>',
            unsafe_allow_html=True,
        )

        _popular  = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "AMZN", "META", "JPM"]
        _pop_cols = st.columns(len(_popular))
        for _pi, _pt in enumerate(_popular):
            if _pop_cols[_pi].button(_pt, key=f"pop_{_pt}", use_container_width=True):
                st.session_state["ticker_input"] = _pt
                st.session_state["auto_run"]     = True
                st.rerun()

    # Re-render from session state if we already have results
    # This prevents page reset on any rerun (form submit, button click etc.)
    _has_results = (
        st.session_state.get("fin_ticker") and
        st.session_state.get("fin_enriched") is not None
    )
    _should_analyse = analyse_btn and ticker_input
    _should_redisplay = (
        _has_results and
        not analyse_btn and
        st.session_state.get("fin_ticker") == ticker_input
    )

    # Re-display from session state (after form submit / button click rerun)
    if _should_redisplay:
        ticker_input = st.session_state["fin_ticker"]
        _should_analyse = True

    if _should_analyse and ticker_input:
        # ── Skip fetch/compute if redisplaying from session state ──
        _from_cache = (
            _should_redisplay and
            st.session_state.get("fin_ticker") == ticker_input and
            st.session_state.get("fin_enriched") is not None and
            st.session_state.get("_dcf_res") is not None
        )

        if _from_cache:
            # Restore all computed variables from session state
            import pandas as _pd
            enriched        = st.session_state["fin_enriched"]
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
                lim = limit("analyses_per_day")
                st.error(f"🔒 You've used all {lim} free analyses today. Resets at midnight.")
                upgrade_prompt("analyses")
                st.stop()

            # ── TIER CHECK: market access ───────────────────────
            allowed, reason = check_ticker_allowed(ticker_input)
            if not allowed:
                upgrade_prompt(reason)
                st.stop()

            with st.spinner(f"Fetching data for {ticker_input}…"):
                raw, price_hist, wacc_data = fetch_stock_data(ticker_input)

        if not _from_cache:
            if raw is None:
                st.error(f"Could not fetch data for **{ticker_input}**.")
                st.stop()

            # Record this analysis
            record_analysis()

        if not _from_cache:
          with st.spinner("Running DCF, scenarios, and investment plan…"):
            enriched   = compute_metrics(raw)
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
                enriched.setdefault("sector", "general")

            dcf_engine      = DCFEngine(discount_rate=wacc, terminal_growth=terminal_g)
            forecast_result = forecaster.predict(enriched, years=forecast_yrs)
            projected       = forecast_result["projections"]
            terminal_norm   = forecast_result["terminal_fcf_norm"]
            base_growth     = forecast_result["base_growth"]
            fcf_base        = forecast_result["fcf_base"]
            growth_schedule = forecast_result["growth_schedule"]

            dcf_res = dcf_engine.intrinsic_value_per_share(
                projected_fcfs=projected, terminal_fcf_norm=terminal_norm,
                total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                shares_outstanding=enriched["shares"],
                current_price=enriched["price"], ticker=ticker_input,
            )

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
            moat_grade   = "None"
            moat_score   = 0
            moat_types   = []
            moat_summary = ""
            moat_adj     = {"iv_delta_pct": 0}   # safe default — overwritten if moat succeeds
            try:
                from screener.moat_engine import compute_moat_score, apply_moat_adjustments
                moat_result  = compute_moat_score(enriched, wacc)
                moat_adj     = apply_moat_adjustments(
                    moat_result, wacc, base_growth, terminal_g, iv_n,
                    sector=enriched.get("sector", "general")
                )
                moat_grade   = moat_result.get("grade",      "None")
                moat_score   = moat_result.get("score",      0)
                moat_types   = moat_result.get("moat_types", [])
                moat_summary = moat_result.get("summary",    "")

                # Apply moat IV premium/discount to get moat-adjusted IV
                iv_delta_pct = moat_adj.get("iv_delta_pct", 0) / 100
                iv_n_moat    = iv_n * (1 + iv_delta_pct)

                enriched["moat_grade"]   = moat_grade
                enriched["moat_score"]   = moat_score
                enriched["moat_types"]   = moat_types
                enriched["moat_summary"] = moat_summary
                st.session_state["fin_moat"]     = moat_result
                st.session_state["fin_moat_adj"] = moat_adj
            except Exception as _me:
                iv_n_moat    = iv_n
                enriched["moat_grade"]   = "N/A"
                enriched["moat_score"]   = 0
                enriched["moat_types"]   = []
                enriched["moat_summary"] = ""

            # ── Confidence-based IV haircut ────────────────────
            # When confidence flags major warnings, reduce IV to reflect
            # the uncertainty. This is the IB approach: widen the range
            # and reduce point estimate when data quality is poor.
            confidence     = compute_confidence_score(enriched)
            _conf_warnings = confidence.get("warnings", [])
            _iv_haircut = 1.0
            for _w in _conf_warnings:
                if "DECLINING" in _w:
                    _iv_haircut *= 0.55   # revenue declining: cut IV 45%
                elif "spike" in _w.lower():
                    _iv_haircut *= 0.60   # FCF spike (one-time): cut IV 40%
                elif "decelerat" in _w.lower():
                    _iv_haircut *= 0.80   # sharp deceleration: cut IV 20%
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
            sig      = assign_signal(mos, dcf_res.get("suspicious", False), forecast_result.get("reliable", True))
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
        st.session_state["fin_enriched"]  = enriched
        st.session_state["fin_ticker"]    = ticker_input
        st.session_state["fin_fx"]        = fx
        st.session_state["fin_to_code"]   = to_code
        st.session_state["fin_sym"]       = sym
        st.session_state["fin_raw"]       = raw
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

        # Use human language signal helper for colors
        _h_label_m, sig_fg, sig_bg, sig_bd = sig_human(sig)
        mos_pct   = mos * 100
        mos_color = "#0D7A4E" if mos_pct > 20 else "#B8972A" if mos_pct > 0 else "#A62020"
        st.session_state["fin_mos_pct"] = mos_pct
        st.session_state["fin_signal"]  = sig
        st.session_state["fin_iv_d"]    = iv_d
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
        # INNER SUB-TABS
        # ══════════════════════════════════════════════════
        _sub_ov, _sub_vl, _sub_ql, _sub_sg = st.tabs([
            "  ⚡ Summary  ",
            "  📈  Is it Fairly Priced?  ",
            "  🏆  Is the Business Healthy?  ",
            "  📡  What Are Others Saying?  ",
        ])

        with _sub_ov:

            # ══════════════════════════════════════════════════════════
            # SHARED PREP — values used across all 4 layers
            # ══════════════════════════════════════════════════════════
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
                "Fairly priced" if mos_pct > -10 else
                "Overvalued"
            )
            _val_color = (
                "#0D7A4E" if _val_label == "Undervalued" else
                "#1D4ED8" if _val_label == "Fairly priced" else "#B91C1C"
            )

            # ── moat plain description ────────────────────────────────
            _moat_plain = {
                "Wide":   "Strong competitive advantage",
                "Narrow": "Some competitive advantage",
                "None":   "No clear competitive advantage",
            }.get(_moat_grade, "Competitive advantage unknown")

            # ══════════════════════════════════════════════════════════
            # HERO — Premium Stock Terminal
            # ══════════════════════════════════════════════════════════

            # ── Day change ─────────────────────────────────────────
            _day_chg_pct   = float((raw.get("day_change_pct", 0) or 0)) if raw else 0.0
            _day_chg_price = price_d * _day_chg_pct / 100
            _chg_color     = "#10B981" if _day_chg_pct >= 0 else "#EF4444"
            _chg_sym       = "▲" if _day_chg_pct >= 0 else "▼"
            _chg_sign      = "+" if _day_chg_pct >= 0 else ""

            # ── 52-week range ───────────────────────────────────────
            _52w_high = float((raw.get("fh_52w_high") or 0)) * fx if raw else 0.0
            _52w_low  = float((raw.get("fh_52w_low")  or 0)) * fx if raw else 0.0
            if (not _52w_high or not _52w_low) and not price_hist.empty:
                _ph52     = price_hist.copy()
                _52w_high = float(_ph52["High"].tail(252).max()) * fx
                _52w_low  = float(_ph52["Low"].tail(252).min())  * fx
            _52w_span = max(_52w_high - _52w_low, 0.01)
            _52w_pos  = float(max(3.0, min(97.0, (price_d - _52w_low) / _52w_span * 100)))

            # ── Sector pill ─────────────────────────────────────────
            _sector_tag  = (enriched.get("sector", "") or "").strip()
            _sector_cmap = {
                "Technology": "#1D4ED8",           "Healthcare": "#059669",
                "Financials": "#7C3AED",            "Finance": "#7C3AED",
                "Consumer Cyclical": "#D97706",     "Consumer Discretionary": "#D97706",
                "Energy": "#DC2626",                "Utilities": "#0891B2",
                "Industrials": "#64748B",           "Real Estate": "#DB2777",
                "Materials": "#65A30D",             "Communication Services": "#6D28D9",
                "Consumer Defensive": "#0369A1",    "Consumer Staples": "#0369A1",
            }
            _sc = _sector_cmap.get(_sector_tag, "#475569")
            _sector_pill_html = (
                f'<span style="font-size:11px;font-weight:600;color:{_sc};'
                f'background:{_sc}18;border:1px solid {_sc}33;'
                f'border-radius:20px;padding:3px 10px;">{_sector_tag}</span>'
            ) if _sector_tag else ""

            # ── YieldIQ Score (inline — matches app.py formula) ────
            _ys_pio  = enriched.get("piotroski_score") or int(fs.get("score", 50) / 100 * 9)
            _ys_fpt  = (raw.get("finnhub_price_target") or {}) if raw else {}
            _ys_mean = float(_ys_fpt.get("mean", 0)) * fx if _ys_fpt.get("mean") else 0.0
            _ys_anl  = ((_ys_mean - price_d) / price_d * 100) if price_d and _ys_mean else 0.0
            _ys_v = (40 if mos_pct >= 40 else 32 if mos_pct >= 25 else 22 if mos_pct >= 10
                     else 14 if mos_pct >= 0 else 7 if mos_pct >= -15 else 0)
            _ys_q = (int(min(int(_ys_pio or 0) / 9 * 20, 20))
                     + {"Wide": 10, "Narrow": 7}.get(str(_moat_grade), 0))
            _ys_g = (20 if _rev_growth >= 20 else 15 if _rev_growth >= 10
                     else 10 if _rev_growth >= 5 else 5 if _rev_growth >= 0 else 0)
            _ys_s = (10 if _ys_anl >= 20 else 7 if _ys_anl >= 10 else 4 if _ys_anl >= 0 else 1)
            _ys_score = max(0, min(100, int(_ys_v + _ys_q + _ys_g + _ys_s)))
            _ys_color = "#16a34a" if _ys_score >= 65 else "#ca8a04" if _ys_score >= 40 else "#dc2626"
            _ys_grade_lbl = (
                "Strong opportunity" if _ys_score >= 75 else
                "Good opportunity"   if _ys_score >= 65 else
                "Neutral / watch"    if _ys_score >= 40 else
                "Proceed with caution"
            )

            _upside_str = (f"+{mos_pct:.1f}%" if mos_pct >= 0 else f"{mos_pct:.1f}%")

            # ── Two-column hero layout ──────────────────────────────
            _hero_left, _hero_right = st.columns([3, 2], gap="large")

            with _hero_left:
                st.html(f"""
<div style="background:var(--bg-card,#FFFFFF);
            border:1px solid var(--rule,#E2E8F0);
            border-top:3px solid {sig_fg};
            border-radius:var(--r-lg,14px);
            padding:22px 24px 20px;
            box-shadow:var(--shadow-sm,0 1px 3px rgba(15,23,42,0.06));
            height:100%;">

  <!-- Company name -->
  <div style="font-size:28px;font-weight:700;color:var(--text,#0F172A);
              line-height:1.1;margin-bottom:10px;
              font-family:var(--font-ui,'Inter',sans-serif);">{_display_name}</div>

  <!-- Ticker + sector badges -->
  <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:18px;">
    <span style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                 font-size:12px;font-weight:600;color:#475569;
                 background:#F1F5F9;border:1px solid #E2E8F0;
                 border-radius:var(--r-sm,6px);padding:3px 10px;">{ticker_input}</span>
    {_sector_pill_html}
  </div>

  <!-- Current price -->
  <div style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
              font-size:32px;font-weight:700;color:var(--text,#0F172A);
              letter-spacing:-0.02em;line-height:1;">{fmts(price_d, sym)}</div>

  <!-- Day change -->
  <div style="font-size:14px;font-weight:600;color:{_chg_color};
              font-family:var(--font-mono,'IBM Plex Mono',monospace);
              margin-top:6px;margin-bottom:22px;">
    {_chg_sym}&nbsp;{sym}{abs(_day_chg_price):.2f}&nbsp;({_chg_sign}{_day_chg_pct:.2f}%)&nbsp;today
  </div>

  <!-- 52-Week Range bar -->
  <div>
    <div style="font-size:10px;font-weight:600;color:#94A3B8;
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:10px;">
      52-Week Range
    </div>
    <!-- Track wrapper: padding gives clearance for the circle marker -->
    <div style="position:relative;padding:8px 0 4px;">
      <div style="height:5px;background:#E2E8F0;border-radius:3px;overflow:hidden;">
        <div style="height:100%;width:{_52w_pos:.1f}%;
                    background:linear-gradient(90deg,#60A5FA,#1D4ED8);
                    border-radius:3px;"></div>
      </div>
      <div style="position:absolute;top:50%;left:{_52w_pos:.1f}%;
                  transform:translate(-50%,-50%);
                  width:14px;height:14px;background:#1D4ED8;
                  border:2.5px solid #FFFFFF;border-radius:50%;
                  box-shadow:0 0 0 3px rgba(29,78,216,0.18),
                             0 1px 4px rgba(0,0,0,0.14);"></div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:6px;">
      <span style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                   font-size:11px;color:#94A3B8;">
        {fmts(_52w_low, sym) if _52w_low else '—'}
      </span>
      <span style="font-size:10px;color:#94A3B8;">{_52w_pos:.0f}% of 52W range</span>
      <span style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                   font-size:11px;color:#94A3B8;">
        {fmts(_52w_high, sym) if _52w_high else '—'}
      </span>
    </div>
  </div>

</div>
""")

            with _hero_right:
                # ── YieldIQ Score circular gauge ─────────────────
                _gauge_fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=_ys_score,
                    gauge={
                        "axis": {
                            "range":     [0, 100],
                            "tickvals":  [0, 40, 65, 100],
                            "ticktext":  ["0", "40", "65", "100"],
                            "tickfont":  {"size": 9, "color": "#94A3B8"},
                            "tickwidth": 1,
                            "tickcolor": "#E2E8F0",
                        },
                        "bar":         {"color": _ys_color, "thickness": 0.3},
                        "bgcolor":     "#F8FAFC",
                        "borderwidth": 0,
                        "steps": [
                            {"range": [0,  40],  "color": "#FEE2E2"},
                            {"range": [40, 65],  "color": "#FEF9C3"},
                            {"range": [65, 100], "color": "#DCFCE7"},
                        ],
                        "threshold": {
                            "line":      {"color": _ys_color, "width": 4},
                            "thickness": 0.82,
                            "value":     _ys_score,
                        },
                    },
                    number={
                        "font": {
                            "size":   44,
                            "family": "IBM Plex Mono, monospace",
                            "color":  _ys_color,
                        },
                        "valueformat": ".0f",
                    },
                    title={
                        "text": "YieldIQ Score",
                        "font": {"size": 13, "color": "#64748B",
                                 "family": "Inter, sans-serif"},
                    },
                ))
                _gauge_fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin={"l": 24, "r": 24, "t": 30, "b": 10},
                    height=220,
                    font={"family": "Inter, sans-serif"},
                )
                st.plotly_chart(
                    _gauge_fig,
                    use_container_width=True,
                    config={"displayModeBar": False},
                )
                st.html(
                    f'<div style="text-align:center;font-size:12px;font-weight:600;'
                    f'color:{_ys_color};margin-top:-8px;letter-spacing:0.02em;">'
                    f'{_ys_grade_lbl}</div>'
                )

            # model warnings
            if suspicious:
                st.warning("⚠️ Our model flagged unusual patterns in this company's financials. Treat this analysis with extra caution.")
            for _w in _conf_warnings:
                st.warning(f"⚠️ {_w}")

            # ══════════════════════════════════════════════════════════
            # FINANCIAL SNAPSHOT
            # ══════════════════════════════════════════════════════════
            _snap_pe       = float(enriched.get("forward_pe",    0) or 0)
            _snap_evebitda = float(enriched.get("ev_to_ebitda",  0) or 0)
            _snap_fcf_yld  = float(enriched.get("fcf_yield",     0) or 0)
            _snap_pfcf     = (1.0 / _snap_fcf_yld) if _snap_fcf_yld > 0.005 else 0.0
            _snap_pb       = float(enriched.get("pb",            0) or 0)
            _snap_div      = float(enriched.get("dividend_yield", 0) or 0) * 100
            _snap_roe      = float(enriched.get("roe",           0) or 0) * 100
            _snap_fcfmgn   = float(enriched.get("fcf_margin",    0) or 0) * 100
            _snap_de       = float(enriched.get("de_ratio",      0) or 0)
            _snap_cr       = float(enriched.get("current_ratio", 0) or 0)

            st.markdown(
                '<div style="font-size:11px;font-weight:700;color:#94A3B8;'
                'text-transform:uppercase;letter-spacing:0.12em;margin:20px 0 8px;">'
                'Financial Snapshot</div>',
                unsafe_allow_html=True,
            )
            st.markdown("""
<style>
[data-testid="stMetric"] {
    background: var(--bg-card, #FFFFFF);
    border: 1px solid var(--rule, #E2E8F0);
    border-radius: 10px;
    padding: 14px 16px 12px !important;
}
[data-testid="stMetricLabel"] p {
    font-size: 10px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted, #94A3B8) !important;
}
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 20px !important;
    font-weight: 700 !important;
}
[data-testid="stMetricDelta"] svg { display: none !important; }
[data-testid="stMetricDelta"] { font-size: 10px !important; }
</style>
""", unsafe_allow_html=True)

            # Row 1 — Valuation
            _sv1, _sv2, _sv3, _sv4, _sv5 = st.columns(5)
            _sv1.metric("P/E (Fwd)",   f"{_snap_pe:.1f}×"       if _snap_pe       > 0 else "—")
            _sv2.metric("EV/EBITDA",   f"{_snap_evebitda:.1f}×"  if _snap_evebitda > 0 else "—")
            _sv3.metric("P/FCF",       f"{_snap_pfcf:.1f}×"     if _snap_pfcf     > 0 else "—")
            _sv4.metric("P/Book",      f"{_snap_pb:.2f}×"       if _snap_pb       > 0 else "—")
            _sv5.metric("Div Yield",   f"{_snap_div:.2f}%"      if _snap_div      > 0 else "—")

            # Row 2 — Quality
            _sq1, _sq2, _sq3, _sq4 = st.columns(4)
            _sq1.metric("Revenue Growth", f"{_rev_growth:+.1f}%")
            _sq2.metric("Op Margin",      f"{_op_margin:.1f}%")
            _sq3.metric("FCF Margin",     f"{_snap_fcfmgn:.1f}%" if _snap_fcfmgn != 0 else "—")
            _sq4.metric("ROE",            f"{_snap_roe:.1f}%"    if _snap_roe    != 0 else "—")

            # Row 3 — Balance Sheet Health
            _bs_de_sc  = (3 if _snap_de <= 0.3 else 2 if _snap_de <= 0.8 else
                          1 if _snap_de <= 1.5 else 0) if _snap_de > 0 else 1
            _bs_cr_sc  = (3 if _snap_cr >= 2.0 else 2 if _snap_cr >= 1.5 else
                          1 if _snap_cr >= 1.0 else 0) if _snap_cr > 0 else 1
            _bs_mg_sc  = (3 if _op_margin >= 20 else 2 if _op_margin >= 10 else
                          1 if _op_margin >= 0  else 0)
            _bs_pct    = int((_bs_de_sc + _bs_cr_sc + _bs_mg_sc) / 9 * 100)
            _bs_color  = "#16a34a" if _bs_pct >= 67 else "#ca8a04" if _bs_pct >= 34 else "#dc2626"
            _bs_label  = "Strong" if _bs_pct >= 67 else "Adequate" if _bs_pct >= 34 else "Weak"
            _de_color  = ("#16a34a" if _bs_de_sc == 3 else "#ca8a04" if _bs_de_sc == 2
                          else "#dc2626") if _snap_de > 0 else "#94A3B8"
            _cr_color  = ("#16a34a" if _bs_cr_sc == 3 else "#ca8a04" if _bs_cr_sc == 2
                          else "#dc2626") if _snap_cr > 0 else "#94A3B8"
            _mg_color  = ("#16a34a" if _bs_mg_sc == 3 else "#ca8a04" if _bs_mg_sc == 2
                          else "#dc2626") if _op_margin != 0 else "#94A3B8"
            _de_note   = ("Low leverage" if _bs_de_sc == 3 else "Moderate"
                          if _bs_de_sc == 2 else "Elevated" if _bs_de_sc == 1 else "High")
            _cr_note   = ("Excellent liquidity" if _bs_cr_sc == 3 else "Good liquidity"
                          if _bs_cr_sc == 2 else "Adequate" if _bs_cr_sc == 1 else "Below 1×")
            _mg_note   = ("High quality" if _bs_mg_sc == 3 else "Solid margins"
                          if _bs_mg_sc == 2 else "Thin margins" if _bs_mg_sc == 1 else "Operating loss")

            st.html(f"""
<div style="background:var(--bg-card,#FFFFFF);
            border:1px solid var(--rule,#E2E8F0);
            border-radius:10px;padding:16px 20px;margin-top:4px;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
    <span style="font-size:10px;font-weight:700;color:#94A3B8;
                 text-transform:uppercase;letter-spacing:0.12em;">Balance Sheet Health</span>
    <span style="font-size:12px;font-weight:700;color:{_bs_color};">{_bs_label}</span>
  </div>
  <div style="height:7px;background:#E2E8F0;border-radius:4px;overflow:hidden;margin-bottom:14px;">
    <div style="height:100%;width:{_bs_pct}%;background:{_bs_color};border-radius:4px;"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
    <div>
      <div style="font-size:9px;font-weight:600;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.1em;margin-bottom:4px;">D/E Ratio</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:700;
                  color:{_de_color};">{f"{_snap_de:.2f}×" if _snap_de > 0 else "—"}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{_de_note}</div>
    </div>
    <div>
      <div style="font-size:9px;font-weight:600;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.1em;margin-bottom:4px;">Current Ratio</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:700;
                  color:{_cr_color};">{f"{_snap_cr:.2f}×" if _snap_cr > 0 else "—"}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{_cr_note}</div>
    </div>
    <div>
      <div style="font-size:9px;font-weight:600;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.1em;margin-bottom:4px;">Op Margin</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:700;
                  color:{_mg_color};">{_op_margin:.1f}%</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{_mg_note}</div>
    </div>
  </div>
</div>
""")

            # ══════════════════════════════════════════════════════════
            # METRIC CARDS — Intrinsic Value / Price / MoS / Signal
            # ══════════════════════════════════════════════════════════
            _mos_clr = "#059669" if mos_pct > 20 else "#D97706" if mos_pct > 0 else "#DC2626"
            _mos_bg  = "#ECFDF5" if mos_pct > 20 else "#FFFBEB" if mos_pct > 0 else "#FEF2F2"
            _mos_bd  = "#BBF7D0" if mos_pct > 20 else "#FDE68A" if mos_pct > 0 else "#FECACA"

            st.html(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);
            gap:12px;margin-top:14px;">

  <!-- 1 · Intrinsic Value -->
  <div style="background:var(--bg-card,#FFFFFF);
              border:1px solid var(--rule,#E2E8F0);
              border-radius:var(--r,12px);
              padding:16px 18px;
              box-shadow:var(--shadow-sm,0 1px 3px rgba(15,23,42,0.06));">
    <div style="font-size:10px;font-weight:600;color:var(--text-muted,#94A3B8);
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:8px;">
      Intrinsic Value
    </div>
    <div style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                font-size:22px;font-weight:700;color:var(--blue,#1D4ED8);
                letter-spacing:-0.02em;">{fmts(iv_d, sym)}</div>
    <div style="font-size:11px;color:var(--text-muted,#94A3B8);margin-top:5px;">
      DCF fair-value estimate
    </div>
  </div>

  <!-- 2 · Current Price -->
  <div style="background:var(--bg-card,#FFFFFF);
              border:1px solid var(--rule,#E2E8F0);
              border-radius:var(--r,12px);
              padding:16px 18px;
              box-shadow:var(--shadow-sm,0 1px 3px rgba(15,23,42,0.06));">
    <div style="font-size:10px;font-weight:600;color:var(--text-muted,#94A3B8);
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:8px;">
      Current Price
    </div>
    <div style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                font-size:22px;font-weight:700;color:var(--text,#0F172A);
                letter-spacing:-0.02em;">{fmts(price_d, sym)}</div>
    <div style="font-size:11px;color:{_chg_color};margin-top:5px;">
      {_chg_sign}{_day_chg_pct:.2f}% today
    </div>
  </div>

  <!-- 3 · Margin of Safety -->
  <div style="background:{_mos_bg};
              border:1px solid {_mos_bd};
              border-radius:var(--r,12px);
              padding:16px 18px;
              box-shadow:var(--shadow-sm,0 1px 3px rgba(15,23,42,0.06));">
    <div style="font-size:10px;font-weight:600;color:{_mos_clr};
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:8px;">
      Margin of Safety
    </div>
    <div style="font-family:var(--font-mono,'IBM Plex Mono',monospace);
                font-size:22px;font-weight:700;color:{_mos_clr};
                letter-spacing:-0.02em;">{_upside_str}</div>
    <div style="font-size:11px;color:{_mos_clr};margin-top:5px;opacity:0.85;">
      {'Discount to fair value' if mos_pct >= 0 else 'Premium to fair value'}
    </div>
  </div>

  <!-- 4 · Signal -->
  <div style="background:var(--bg-card,#FFFFFF);
              border:1px solid {sig_bd};
              border-top:3px solid {sig_fg};
              border-radius:var(--r,12px);
              padding:16px 18px;
              box-shadow:var(--shadow-sm,0 1px 3px rgba(15,23,42,0.06));">
    <div style="font-size:10px;font-weight:600;color:var(--text-muted,#94A3B8);
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:10px;">
      Signal
    </div>
    <div style="display:inline-block;background:{sig_bg};
                border:1.5px solid {sig_bd};border-radius:8px;
                padding:5px 14px;margin-bottom:6px;">
      <span style="font-size:16px;font-weight:800;color:{sig_fg};
                   letter-spacing:0.03em;">{_h_label}</span>
    </div>
    <div style="font-size:11px;color:var(--text-muted,#94A3B8);">Model recommendation</div>
  </div>

</div>
""")

            # ── 🤖 AI Explain — DCF result ─────────────────────────
            _dcf_ai_ctx = (
                f"DCF valuation for {ticker_input}: "
                f"Estimated intrinsic value = {fmts(iv_d, sym)}, "
                f"current market price = {fmts(price_d, sym)}, "
                f"margin of safety = {mos_pct:.1f}% "
                f"({'undervalued' if mos_pct > 0 else 'overvalued'}), "
                f"model signal = {sig}, "
                f"required return rate (WACC) = {wacc*100:.1f}%, "
                f"assumed long-run growth rate = {terminal_g*100:.1f}%, "
                f"revenue growth = {_rev_growth:.1f}%, "
                f"operating margin = {_op_margin:.1f}%."
            )
            render_ai_explain(_dcf_ai_ctx, "explain_dcf")

            # ══════════════════════════════════════════════════════════
            # LAYER 3 — Why? (plain-language expandable)
            # ══════════════════════════════════════════════════════════
            with st.expander("Why these signals? — plain English explanation"):
                _why_val = (
                    f"Our model estimates this stock's fair value at **{fmts(iv_d, sym)}**. "
                    f"At the current price of **{fmts(price_d, sym)}**, it appears **{_val_label.lower()}** "
                    f"by around **{abs(mos_pct):.0f}%**."
                    if abs(mos_pct) > 2 else
                    f"The stock is trading very close to our estimated fair value of **{fmts(iv_d, sym)}**."
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

                # ── 🤖 AI Explain — Moat ──────────────────────────
                _moat_types_str = (
                    ", ".join(_moat_types[:3]) if _moat_types else "none identified"
                )
                _moat_ai_ctx = (
                    f"{ticker_input} economic moat assessment: "
                    f"grade = {_moat_grade} moat, "
                    f"moat score = {_moat_score}/100. "
                    f"Competitive advantages identified: {_moat_types_str}. "
                    f"{_moat_plain}. "
                    + (f"Model summary: {_moat_summary[:150]}." if _moat_summary else "")
                )
                render_ai_explain(_moat_ai_ctx, "explain_moat")

            # ══════════════════════════════════════════════════════════
            # LAYER 3b — Model Insight Card (target / downside / horizon)
            # ══════════════════════════════════════════════════════════
            if pt.get("buy_price") and forecast_result.get("reliable", True):
                _ins_tgt_d   = (pt.get("target_price") or 0) * fx
                _ins_sl_d    = (pt.get("stop_loss")    or 0) * fx
                _ins_price_d = price_d
                _ins_upside  = ((_ins_tgt_d - _ins_price_d) / _ins_price_d * 100) if _ins_price_d > 0 else 0
                _ins_down    = pt.get("sl_pct", 12)
                _ins_rr      = pt.get("rr_ratio", 0)
                _ins_hp      = (hp.get("label","Long-term") or "Long-term").replace("'","&#39;").replace('"','&quot;')
                _ins_summary = (inv_plan.get("summary","") or "")[:220].replace("'","&#39;").replace('"','&quot;').replace('<','&lt;').replace('>','&gt;')

                if _ins_mos_pct := mos_pct:
                    pass
                _ins_badge_color, _ins_badge_bg, _ins_badge_bd, _ins_gauge_color = (
                    ("#0D7A4E","#F0FDF4","#BBF7D0","#0D7A4E") if mos_pct >= 20 else
                    ("#B45309","#FFFBEB","#FDE68A","#B45309") if mos_pct >= 5  else
                    ("#1D4ED8","#EFF6FF","#BFDBFE","#1D4ED8") if mos_pct >= -5 else
                    ("#B91C1C","#FEF2F2","#FECACA","#B91C1C")
                )
                _ins_badge_txt = (
                    f"{mos_pct:.0f}% below estimated fair value"   if mos_pct >= 5  else
                    "Near estimated fair value"                      if mos_pct >= -5 else
                    f"{abs(mos_pct):.0f}% above estimated fair value"
                )
                _ins_gauge_w  = min(max(abs(mos_pct), 2), 100)
                _ins_ret_str  = ("+" if _ins_upside >= 0 else "") + f"{_ins_upside:.1f}%"
                _ins_ret_color = "#0D7A4E" if _ins_upside >= 0 else "#B91C1C"
                _ins_risk_label = "Lower risk" if _ins_down <= 8 else "Moderate risk" if _ins_down <= 15 else "Higher risk"
                _ins_risk_color = "#0D7A4E"    if _ins_down <= 8 else "#B45309"       if _ins_down <= 15 else "#B91C1C"
                _ins_rr_txt = (
                    "The model estimate is " + _ins_ret_str +
                    " above current price against a downside scenario of -" + f"{_ins_down:.0f}%" +
                    (f" (model upside/downside ratio: {_ins_rr:.1f}×)." if _ins_rr else ".")
                )

                _tpl = (
                    '<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
                    'overflow:hidden;margin-bottom:6px;">'

                    '<div style="padding:16px 24px 12px;border-bottom:1px solid #F1F5F9;'
                    'background:linear-gradient(135deg,#FAFBFD,#F4F7FC);">'
                    '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin-bottom:8px;">📊 Model Output</div>'
                    '<div style="display:inline-block;padding:5px 14px;background:BADGE_BG;'
                    'border:1px solid BADGE_BD;border-radius:20px;margin-bottom:10px;">'
                    '<span style="font-size:13px;font-weight:700;color:BADGE_COLOR;">BADGE_TXT</span>'
                    '</div>'
                    '<div style="height:7px;background:#F1F5F9;border-radius:4px;overflow:hidden;">'
                    '<div style="height:100%;width:GAUGE_W%;background:GAUGE_COLOR;border-radius:4px;"></div>'
                    '</div>'
                    '</div>'

                    '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;">'

                    '<div style="padding:16px 20px;border-right:1px solid #F1F5F9;">'
                    '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.11em;margin-bottom:5px;">DCF Model Estimate</div>'
                    '<div style="font-size:21px;font-weight:700;color:RET_COLOR;">TGT_D</div>'
                    '<div style="font-size:12px;color:RET_COLOR;margin-top:3px;font-weight:600;">'
                    'RET_STR gap vs current price and model estimate</div>'
                    '</div>'

                    '<div style="padding:16px 20px;border-right:1px solid #F1F5F9;">'
                    '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.11em;margin-bottom:5px;">Downside scenario</div>'
                    '<div style="font-size:21px;font-weight:700;color:RISK_COLOR;">SL_D</div>'
                    '<div style="font-size:12px;color:RISK_COLOR;margin-top:3px;font-weight:500;">'
                    'RISK_LABEL · -DOWN% range</div>'
                    '</div>'

                    '<div style="padding:16px 20px;">'
                    '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.11em;margin-bottom:5px;">DCF projection horizon</div>'
                    '<div style="font-size:16px;font-weight:600;color:#334155;margin-top:4px;">HP_LABEL</div>'
                    '<div style="font-size:12px;color:#94A3B8;margin-top:3px;">Model forecast period</div>'
                    '</div>'

                    '</div>'

                    '<div style="padding:10px 24px 8px;background:#FAFBFD;border-top:1px solid #F1F5F9;">'
                    '<div style="font-size:12px;color:#64748B;line-height:1.6;">RR_TXT</div>'
                    '</div>'

                    '<div style="padding:8px 24px 12px;background:#FAFBFD;">'
                    '<div style="font-size:11px;color:#94A3B8;line-height:1.5;font-style:italic;'
                    'border-top:1px dashed #E2E8F0;padding-top:8px;">'
                    '⚠️ Model-based estimate for informational purposes only. Not a price target, return projection, or investment advice. YieldIQ is not a registered investment adviser.'
                    '</div>'
                    '</div>'
                    '</div>'
                )
                _tpl = (
                    _tpl
                    .replace("BADGE_BG",    _ins_badge_bg)
                    .replace("BADGE_BD",    _ins_badge_bd)
                    .replace("BADGE_COLOR", _ins_badge_color)
                    .replace("BADGE_TXT",   _ins_badge_txt)
                    .replace("GAUGE_W",     str(int(_ins_gauge_w)))
                    .replace("GAUGE_COLOR", _ins_gauge_color)
                    .replace("RET_COLOR",   _ins_ret_color)
                    .replace("TGT_D",       fmts(_ins_tgt_d, sym))
                    .replace("RET_STR",     _ins_ret_str)
                    .replace("RISK_COLOR",  _ins_risk_color)
                    .replace("SL_D",        fmts(_ins_sl_d, sym))
                    .replace("RISK_LABEL",  _ins_risk_label)
                    .replace("DOWN",        f"{_ins_down:.0f}")
                    .replace("HP_LABEL",    _ins_hp)
                    .replace("RR_TXT",      _ins_rr_txt)
                )
                st.html(_tpl)

                if _ins_summary:
                    with st.expander("Model reasoning — what drives this estimate?"):
                        st.markdown("> " + _ins_summary.replace("&#39;","'").replace("&quot;",'"').replace("&lt;","<").replace("&gt;",">"))
                        st.caption("Model output based on public data. Not a recommendation.")

            # ══════════════════════════════════════════════════════════
            # LAYER 4 — Advanced Analysis (all hidden)
            # ══════════════════════════════════════════════════════════
            with st.expander("Advanced data — live price, analyst views & earnings"):
                render_live_price_header(ticker=ticker_input, sym=sym, fx=fx, refresh_every=60)
                ccard("What do professional analysts say?", "#7C3AED")
                render_analyst_consensus(ticker=ticker_input, current_price=price_d, sym=sym, fx=fx, raw_data=raw)
                ccard_end()
                ccard("Upcoming earnings & past surprises", "#0891B2")
                render_earnings_calendar(ticker=ticker_input, sym=sym, raw_data=raw)
                ccard_end()

            with st.expander("Advanced data — detailed metrics"):
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

            if use_auto_wacc and wacc_data.get("auto_computed"):
                with st.expander(f"How we calculated the required return rate ({wacc:.1%}) — technical details"):
                    w1,w2,w3,w4,w5 = st.columns(5)
                    w1.metric("Required return (WACC)",    f"{wacc_data['wacc']:.1%}",
                              help=FINANCIAL_TOOLTIPS["WACC"])
                    w2.metric("Expected equity return",    f"{wacc_data['re']:.1%}")
                    w3.metric("Volatility vs market (Beta)", f"{wacc_data['beta']:.2f}")
                    w4.metric("Risk-free rate",             f"{wacc_data['rf']:.1%}")
                    w5.metric("Cost of debt",               f"{wacc_data['rd']:.1%}")

        with _sub_vl:

            # ══════════════════════════════════════════════════════════
            # SECTION 1 — Valuation Summary (top card)
            # ══════════════════════════════════════════════════════════
            _vl_val_label  = (
                "Undervalued"   if mos_pct > 10 else
                "Fairly priced" if mos_pct > -10 else
                "Overvalued"
            )
            _vl_val_color  = (
                "#0D7A4E" if _vl_val_label == "Undervalued"   else
                "#1D4ED8" if _vl_val_label == "Fairly priced" else "#B91C1C"
            )
            _vl_val_bg     = (
                "#F0FDF4" if _vl_val_label == "Undervalued"   else
                "#EFF6FF" if _vl_val_label == "Fairly priced" else "#FEF2F2"
            )
            _vl_val_bd     = (
                "#BBF7D0" if _vl_val_label == "Undervalued"   else
                "#BFDBFE" if _vl_val_label == "Fairly priced" else "#FECACA"
            )
            _vl_gauge_w = min(max(abs(mos_pct), 2), 100)
            _vl_upside  = (("+" if mos_pct >= 0 else "") + f"{mos_pct:.1f}%")

            _summary_tpl = (
                '<div style="background:#FFFFFF;border-radius:12px;border:1px solid #E2E8F0;'
                'overflow:hidden;margin-bottom:8px;">'
                '<div style="height:4px;background:linear-gradient(90deg,VAL_COLOR,#06B6D4,transparent);"></div>'
                '<div style="padding:20px 24px;">'

                # label + upside
                '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">'
                '<div>'
                '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.14em;margin-bottom:6px;">Valuation</div>'
                '<div style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;'
                'background:VAL_BG;border:1px solid VAL_BD;border-radius:20px;">'
                '<span style="font-size:14px;font-weight:700;color:VAL_COLOR;">VAL_LABEL</span>'
                '</div>'
                '</div>'
                '<div style="text-align:right;">'
                '<div style="font-size:11px;color:#94A3B8;margin-bottom:3px;">vs estimated fair value</div>'
                '<div style="font-size:28px;font-weight:700;color:VAL_COLOR;">UPSIDE</div>'
                '</div>'
                '</div>'

                # 3 metrics row
                '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;'
                'background:#F1F5F9;border-radius:8px;overflow:hidden;margin-bottom:16px;">'

                '<div style="background:#FFFFFF;padding:14px 16px;">'
                '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Current price</div>'
                '<div style="font-size:20px;font-weight:700;color:#0F172A;">PRICE</div>'
                '</div>'

                '<div style="background:#FFFFFF;padding:14px 16px;">'
                '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Estimated fair value</div>'
                '<div style="font-size:20px;font-weight:700;color:#1D4ED8;">IV</div>'
                '</div>'

                '<div style="background:#FFFFFF;padding:14px 16px;">'
                '<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">Model confidence</div>'
                '<div style="font-size:20px;font-weight:700;color:#334155;">CONF</div>'
                '</div>'

                '</div>'

                # progress bar
                '<div style="display:flex;justify-content:space-between;margin-bottom:5px;">'
                '<span style="font-size:12px;color:#64748B;">Discount to fair value</span>'
                '<span style="font-size:12px;font-weight:700;color:VAL_COLOR;">MOS_PCT%</span>'
                '</div>'
                '<div style="height:7px;background:#F1F5F9;border-radius:4px;overflow:hidden;">'
                '<div style="height:100%;width:GAUGE_W%;background:VAL_COLOR;border-radius:4px;"></div>'
                '</div>'

                '</div>'  # end padding
                '</div>'  # end card
            )
            _summary_tpl = (
                _summary_tpl
                .replace("VAL_COLOR",  _vl_val_color)
                .replace("VAL_BG",     _vl_val_bg)
                .replace("VAL_BD",     _vl_val_bd)
                .replace("VAL_LABEL",  _vl_val_label)
                .replace("UPSIDE",     _vl_upside)
                .replace("PRICE",      fmts(price_d, sym))
                .replace("IV",         fmts(iv_d, sym))
                .replace("CONF",       f"{confidence.get('grade','N/A')} · {confidence.get('score',0)}/100")
                .replace("MOS_PCT",    f"{mos_pct:.1f}")
                .replace("GAUGE_W",    str(int(_vl_gauge_w)))
            )
            st.html(_summary_tpl)

            # ══════════════════════════════════════════════════════════
            # SECTION 2 — Scenario Cards (Bear / Base / Bull)
            # ══════════════════════════════════════════════════════════
            st.html(
                '<div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;'
                'letter-spacing:0.14em;margin:18px 0 10px;padding-left:2px;">Valuation Scenarios</div>'
            )

            _sc_cols = st.columns(3, gap="medium")
            _sc_cfg = [
                ("Bear Case", "🐻", "Cautious outlook",    scenarios.get("Bear 🐻", {}),
                 "#991B1B", "#DC2626", "#FEF2F2", "#FECACA"),
                ("Base Case", "📊", "Most likely outcome", scenarios.get("Base 📊", {}),
                 "#1E3A8A", "#1D4ED8", "#EFF6FF", "#BFDBFE"),
                ("Bull Case", "🐂", "Optimistic outlook",  scenarios.get("Bull 🐂", {}),
                 "#065F46", "#059669", "#F0FDF4", "#BBF7D0"),
            ]

            for _col, (_sc_title, _sc_icon, _sc_desc, _sc_data, _sc_dark, _sc_c, _sc_bg, _sc_bd) in zip(_sc_cols, _sc_cfg):
                _sc_iv   = (_sc_data.get("iv",      0) or 0) * fx
                _sc_mos  = _sc_data.get("mos_pct",  0) or 0
                _sc_g    = (_sc_data.get("growth",   0) or 0) * 100
                _sc_w    = (_sc_data.get("wacc",     0) or 0) * 100
                _sc_tg   = (_sc_data.get("term_g",   0) or 0) * 100
                _sc_diff = _sc_iv - price_d
                _sc_diff_pct = (_sc_diff / price_d * 100) if price_d else 0

                # Signal badge
                if _sc_mos > 25:
                    _sc_sig, _sc_sig_bg, _sc_sig_c = "STRONG BUY", "#DCFCE7", "#166534"
                elif _sc_mos > 10:
                    _sc_sig, _sc_sig_bg, _sc_sig_c = "BUY",        "#DCFCE7", "#166534"
                elif _sc_mos > -5:
                    _sc_sig, _sc_sig_bg, _sc_sig_c = "WATCH",      "#FEF9C3", "#854D0E"
                elif _sc_mos > -20:
                    _sc_sig, _sc_sig_bg, _sc_sig_c = "HOLD",       "#FEF3C7", "#92400E"
                else:
                    _sc_sig, _sc_sig_bg, _sc_sig_c = "SELL",       "#FEE2E2", "#991B1B"

                _diff_color = "#059669" if _sc_diff_pct >= 0 else "#DC2626"
                _diff_arrow = "▲" if _sc_diff_pct >= 0 else "▼"
                _diff_sign  = "+" if _sc_diff_pct >= 0 else ""

                _col.html(f"""
<div style="border-radius:14px;overflow:hidden;
            border:1px solid {_sc_bd};
            box-shadow:0 2px 8px rgba(0,0,0,0.06);
            height:100%;">

  <!-- Colored banner -->
  <div style="background:linear-gradient(135deg,{_sc_dark} 0%,{_sc_c} 100%);
              padding:18px 20px 14px;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
      <span style="font-size:24px;line-height:1;">{_sc_icon}</span>
      <div>
        <div style="font-size:15px;font-weight:700;color:#FFFFFF;letter-spacing:0.01em;">
          {_sc_title}
        </div>
        <div style="font-size:11px;color:rgba(255,255,255,0.75);margin-top:2px;">
          {_sc_desc}
        </div>
      </div>
    </div>
  </div>

  <!-- Card body -->
  <div style="background:#FFFFFF;padding:18px 20px 16px;">

    <!-- Intrinsic Value -->
    <div style="font-size:11px;font-weight:600;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.1em;margin-bottom:4px;">Intrinsic Value</div>
    <div style="font-size:26px;font-weight:700;color:#0F172A;
                font-family:'IBM Plex Mono',monospace;margin-bottom:4px;">
      {fmts(_sc_iv, sym) if _sc_iv else "—"}
    </div>

    <!-- vs Current Price -->
    <div style="font-size:12px;color:#64748B;margin-bottom:14px;">
      vs current price
      <span style="font-weight:700;color:{_diff_color};margin-left:4px;">
        {_diff_arrow} {_diff_sign}{_sc_diff_pct:.1f}%
      </span>
    </div>

    <!-- Assumption chips -->
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;">
      <span style="font-size:10px;font-weight:600;color:{_sc_c};
                   background:{_sc_bg};border:1px solid {_sc_bd};
                   border-radius:20px;padding:3px 9px;white-space:nowrap;">
        Growth {_sc_g:.1f}%
      </span>
      <span style="font-size:10px;font-weight:600;color:{_sc_c};
                   background:{_sc_bg};border:1px solid {_sc_bd};
                   border-radius:20px;padding:3px 9px;white-space:nowrap;">
        WACC {_sc_w:.1f}%
      </span>
      <span style="font-size:10px;font-weight:600;color:{_sc_c};
                   background:{_sc_bg};border:1px solid {_sc_bd};
                   border-radius:20px;padding:3px 9px;white-space:nowrap;">
        Terminal {_sc_tg:.1f}%
      </span>
    </div>

    <!-- Signal badge -->
    <div style="display:inline-block;padding:5px 14px;
                background:{_sc_sig_bg};border-radius:8px;">
      <span style="font-size:12px;font-weight:800;color:{_sc_sig_c};
                   letter-spacing:0.08em;font-family:'IBM Plex Mono',monospace;">
        {_sc_sig}
      </span>
    </div>

  </div>
</div>
""")

            st.html('<div style="margin-bottom:6px;"></div>')

            # ══════════════════════════════════════════════════════════
            # SECTION 3 — Key Insights (bullet points, plain English)
            # ══════════════════════════════════════════════════════════
            st.html('<div style="font-size:11px;color:#94A3B8;text-transform:uppercase;'
                    'letter-spacing:0.14em;margin:16px 0 8px;padding-left:2px;">Key insights</div>')

            # Build 3–5 plain-language insight bullets dynamically
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
                    _insights.append(("✅", "Bull and bear scenarios are relatively close together, suggesting moderate uncertainty in the estimate."))

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
                with st.expander("Price chart with fair value line", expanded=True):
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

                # Serialize all data for JS
                import json as _json
                _candles_js  = _json.dumps(_candles)
                _volumes_js  = _json.dumps(_volumes)
                _ma20_js     = _json.dumps(_ma20)
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
  color:            '#3b82f6',
  lineWidth:        1.5,
  lineStyle:        LightweightCharts.LineStyle.Dashed,
  priceLineVisible: false,
  lastValueVisible: true,
  title:            'MA20',
}});
maSeries.setData(ma20Data);

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

            with st.expander("Cash flow history & projections"):
                pass  # content follows
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

                if hist_fcfs:
                    fig_fcf.add_trace(go.Bar(
                        x=hist_yrs, y=hist_fcfs,
                        marker=dict(
                            color=["#1D4ED8" if v >= 0 else "#DC2626" for v in hist_fcfs],
                            opacity=0.85, line=dict(width=0)
                        ),
                        name="Historical FCF",
                        hovertemplate=f"<b>%{{x}}</b><br>FCF: {sym}%{{y:.2f}}B<extra>Historical</extra>",
                    ))

                proj_vals = [v / 1e9 for v in proj_d]
                fig_fcf.add_trace(go.Bar(
                    x=proj_labels, y=proj_vals,
                    marker=dict(
                        color=["#1D4ED8" if v >= 0 else "#DC2626" for v in proj_vals],
                        pattern=dict(shape="/", fgcolor="rgba(255,255,255,0.4)", size=6),
                        opacity=0.6, line=dict(width=0)
                    ),
                    name="Projected FCF",
                    hovertemplate=f"<b>%{{x}}</b><br>FCF: {sym}%{{y:.2f}}B<extra>Projected</extra>",
                ))

                # Growth rate overlay on secondary y-axis
                growth_pct = [g * 100 for g in growth_schedule]
                fig_fcf.add_trace(go.Scatter(
                    x=proj_labels, y=growth_pct,
                    yaxis="y2",
                    line=dict(color="#f59e0b", width=2, dash="dot"),
                    mode="lines+markers",
                    marker=dict(size=6, color="#F59E0B", symbol="circle"),
                    name="Growth %",
                    hovertemplate="<b>%{x}</b><br>Growth: %{y:.1f}%<extra>Growth Rate</extra>",
                ))

                # Vertical separator between historical and projected
                if hist_yrs and proj_labels:
                    fig_fcf.add_shape(
                        type="line",
                        xref="paper", yref="paper",
                        x0=len(hist_yrs) / (len(hist_yrs) + len(proj_labels)),
                        x1=len(hist_yrs) / (len(hist_yrs) + len(proj_labels)),
                        y0=0, y1=1,
                        line=dict(color="#CBD5E1", width=1.5, dash="dash"),
                    )
                    fig_fcf.add_annotation(
                        xref="paper", yref="paper",
                        x=len(hist_yrs) / (len(hist_yrs) + len(proj_labels)) + 0.01,
                        y=1.0,
                        text="Forecast →",
                        showarrow=False,
                        font=dict(color="#94A3B8", size=10),
                        xanchor="left",
                    )

                apply_yieldiq_theme(fig_fcf, height=280, extra_kw=dict(
                    barmode="group",
                    showlegend=True,
                    yaxis=dict(
                        title=dict(text=f"{to_code}B", font=dict(size=11, color="#374151")),
                        zeroline=True, zerolinecolor="#D1D5DB",
                    ),
                    yaxis2=dict(
                        title=dict(text="Growth %", font=dict(size=11, color="#f59e0b")),
                        overlaying="y", side="right",
                        gridcolor="rgba(0,0,0,0)", ticksuffix="%",
                        tickfont=dict(color="#f59e0b", size=10), zeroline=False,
                    ),
                    xaxis=dict(type="category", zeroline=False, tickangle=-30),
                    legend=dict(
                        orientation="h", x=0.0, y=-0.22,
                        bgcolor="rgba(0,0,0,0)", borderwidth=0,
                        font=dict(color="#6B7280", size=11),
                    ),
                ))
                st.plotly_chart(fig_fcf, width='stretch', config={
                    "displayModeBar": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                    "toImageButtonOptions": {"filename": f"FCF_{ticker_input}", "scale": 2},
                })

                # ── THREE SCENARIOS
            with st.expander("Fair value vs current price (chart)"):
                pass  # content follows
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
                    # Color zones: bear=red, base=amber, bull=green
                    for _zone_x0, _zone_x1, _zone_color, _zone_name in [
                        (_min_v,   _bear_val, "rgba(239,68,68,0.18)",  "Bear zone"),
                        (_bear_val, _base_val, "rgba(245,158,11,0.18)", "Base zone"),
                        (_base_val, _bull_val, "rgba(16,185,129,0.18)", "Bull zone"),
                    ]:
                        fig_iv.add_shape(type="rect", xref="x", yref="paper",
                            x0=_zone_x0, x1=_zone_x1, y0=0, y1=1,
                            fillcolor=_zone_color, line=dict(width=0), layer="below")

                    # Scenario markers
                    for _sv, _slabel, _scolor in [
                        (_bear_val, f"Bear<br>{fmts(_bear_val,sym)}", "#ef4444"),
                        (_base_val, f"Base<br>{fmts(_base_val,sym)}", "#f59e0b"),
                        (_bull_val, f"Bull<br>{fmts(_bull_val,sym)}", "#10b981"),
                    ]:
                        fig_iv.add_vline(x=_sv, line=dict(color=_scolor, width=1.5, dash="dot"))
                        fig_iv.add_annotation(x=_sv, y=0.92, xref="x", yref="paper",
                            text=_slabel, showarrow=False,
                            font=dict(color=_scolor, size=10, family="IBM Plex Mono"),
                            align="center")

                    # Current price marker (bold)
                    fig_iv.add_vline(x=price_d,
                        line=dict(color="#00b4d8", width=3, dash="solid"),
                        annotation_text=f"Now<br>{fmts(price_d,sym)}",
                        annotation_font=dict(color="#00b4d8", size=11, family="IBM Plex Mono"),
                        annotation_position="top right")

                    # Invisible scatter for hover
                    fig_iv.add_trace(go.Scatter(
                        x=[_bear_val, _base_val, _bull_val, price_d],
                        y=[0.5, 0.5, 0.5, 0.5],
                        mode="markers", marker=dict(color="rgba(0,0,0,0)", size=8),
                        text=[f"Bear: {fmts(_bear_val,sym)}", f"Base: {fmts(_base_val,sym)}",
                              f"Bull: {fmts(_bull_val,sym)}", f"Price: {fmts(price_d,sym)}"],
                        hovertemplate="%{text}<extra></extra>",
                    ))
                    apply_yieldiq_theme(fig_iv, height=160, extra_kw=dict(
                        showlegend=False,
                        xaxis=dict(title=f"{to_code}/share", range=[_min_v, _max_v]),
                        yaxis=dict(visible=False),
                        margin=dict(t=40, b=40, l=20, r=20),
                    ))
                    st.plotly_chart(fig_iv, width='stretch', config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"iv_vs_price","scale":2}})
                    ccard_end()

                with c2:
                    ccard("Where does the fair value come from?", "#f59e0b")
                    _wf_y      = [v/1e9 for v in pv_fcfs_d] + [pv_tv_d/1e9]
                    _wf_colors = ["#1D4ED8"] * forecast_yrs + ["#2563EB"]
                    fig_wf = go.Figure(go.Bar(
                        x=years_labels + ["Terminal"],
                        y=_wf_y,
                        marker=dict(color=_wf_colors, opacity=0.9, line=dict(width=0)),
                        text=[f"{v:.1f}B" for v in _wf_y],
                        textposition="inside",
                        textfont=dict(size=9, color="#FFFFFF", family="IBM Plex Mono, monospace"),
                        hovertemplate=f"%{{x}}<br><b>PV: {sym}%{{y:.2f}}B</b><extra></extra>",
                        width=0.65,
                    ))
                    apply_yieldiq_theme(fig_wf, height=240, extra_kw=dict(
                        showlegend=False,
                        yaxis=dict(title=f"{to_code}B (PV)"),
                        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
                        margin=dict(t=44, b=16, l=48, r=16),
                    ))
                    st.plotly_chart(fig_wf, width='stretch', config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"dcf_waterfall","scale":2}})
                    ccard_end()

                # ── Sensitivity Heatmap
            with st.expander("Sensitivity analysis — how assumptions affect the estimate"):
                pass  # content follows
                # ── TIER CHECK: sensitivity ───────────────────────────
                if not _show_sensitive:
                    upgrade_prompt("sensitivity", compact=True)
                else:
                    sa_df = sensitivity_analysis(
                    projected_fcfs=projected, terminal_fcf_norm=terminal_norm,
                    total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                    shares_outstanding=enriched["shares"], current_price=price_n,
                )
                    sa_display = (sa_df * fx).round(2)

                    # ── Title + subtitle ──────────────────────────────
                    st.html(f"""
<div style="margin-bottom:16px;">
  <div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:4px;">
    Intrinsic Value Sensitivity Analysis
  </div>
  <div style="font-size:13px;color:#64748B;">
    How IV changes with WACC and Terminal Growth Rate &nbsp;·&nbsp;
    Current price: <strong>{fmts(price_d, sym)}</strong>
  </div>
</div>""")

                    # Find base-case cell indices for highlight border
                    _sa_cols = sa_display.columns.tolist()
                    _sa_rows = sa_display.index.tolist()

                    def _parse_sa_val(v):
                        """Parse sensitivity header in ANY format → float.
                        Handles: 'g=1', 'wacc=9.5', '1%', '1.0', '9', '3.0%'
                        """
                        import re as _re
                        s = str(v).strip()
                        if '=' in s:
                            s = s.split('=')[-1].strip()
                        s = s.replace('%', '').replace(' ', '')
                        m = _re.search(r'-?\d+\.?\d*', s)
                        if m:
                            try:
                                return float(m.group())
                            except ValueError:
                                return 0.0
                        return 0.0

                    _base_col_idx = min(range(len(_sa_cols)), key=lambda i: abs(_parse_sa_val(_sa_cols[i]) - terminal_g * 100)) if _sa_cols else 0
                    _base_row_idx = min(range(len(_sa_rows)), key=lambda i: abs(_parse_sa_val(_sa_rows[i]) - wacc * 100)) if _sa_rows else 0

                    # Red → white (at current price) → green colorscale
                    _sa_zmid = price_d if price_d > 0 else None
                    fig_sa = go.Figure(go.Heatmap(
                        z=sa_display.values.astype(float),
                        x=[str(c) for c in _sa_cols],
                        y=[str(r) for r in _sa_rows],
                        colorscale=[
                            [0.0,  "#7F1D1D"],
                            [0.3,  "#EF4444"],
                            [0.5,  "#FFFFFF"],
                            [0.7,  "#22C55E"],
                            [1.0,  "#14532D"],
                        ],
                        zmid=_sa_zmid,
                        text=[[f"{sym}{v:,.2f}" if not np.isnan(v) else "N/A"
                               for v in row] for row in sa_display.values],
                        texttemplate="%{text}",
                        textfont=dict(size=10, color="#0F172A", family="IBM Plex Mono"),
                        hovertemplate="WACC: %{y}<br>Terminal g: %{x}<br>IV: %{text}<extra></extra>",
                        showscale=True,
                        colorbar=dict(
                            tickfont=dict(color="#6B7280", size=10),
                            title=dict(text=f"IV ({to_code})", font=dict(color="#6B7280", size=11)),
                            thickness=12, bgcolor="rgba(0,0,0,0)",
                            bordercolor="#E2E8F0", borderwidth=1,
                        ),
                    ))
                    # Bold border on base-case cell
                    fig_sa.add_shape(type="rect",
                        xref="x", yref="y",
                        x0=_base_col_idx - 0.5, x1=_base_col_idx + 0.5,
                        y0=_base_row_idx - 0.5, y1=_base_row_idx + 0.5,
                        line=dict(color="#1D4ED8", width=3),
                    )
                    # Current-price reference annotation
                    fig_sa.add_annotation(
                        text=f"◆ Current assumptions  ·  Price = {fmts(price_d, sym)}",
                        xref="paper", yref="paper", x=0.0, y=1.07,
                        font=dict(color="#1D4ED8", size=11, family="IBM Plex Mono"),
                        showarrow=False, xanchor="left",
                    )
                    apply_yieldiq_theme(fig_sa, height=320, extra_kw=dict(
                        margin=dict(t=50, b=44, l=64, r=100),
                        xaxis=dict(title="Terminal Growth Rate →", title_font=dict(size=12, color="#374151")),
                        yaxis=dict(title="← WACC", title_font=dict(size=12, color="#374151")),
                    ))
                    st.plotly_chart(fig_sa, width='stretch', config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"sensitivity","scale":2}})
                    st.html(
                        '<div style="font-size:11px;color:#94A3B8;text-align:center;margin-top:-8px;">'
                        f'Blue border = current assumptions &nbsp;·&nbsp; White = priced at today\'s price &nbsp;·&nbsp; Green = undervalued &nbsp;·&nbsp; Red = overvalued &nbsp;·&nbsp; Values in {to_code}'
                        '</div>'
                    )
                    ccard_end()

                # ── Monte Carlo
                if _show_mc:
                    with st.expander("Probability range of outcomes (1,000 simulations)"):
                        if run_mc and mc_result and "iv_values" in mc_result:
                            mc_arr   = mc_result["iv_values"] * fx
                            _mc_p10  = mc_result["p10"]  * fx
                            _mc_p50  = mc_result["median_iv"] * fx
                            _mc_p90  = mc_result["p90"]  * fx
                            _mc_std  = mc_result["std_iv"] * fx
                            _mc_prob = mc_result["prob_undervalued"]

                            # ── Chart ─────────────────────────────────
                            fig_mc = go.Figure()
                            fig_mc.add_trace(go.Histogram(
                                x=mc_arr, nbinsx=60,
                                marker=dict(color="#1D4ED8", opacity=0.75,
                                            line=dict(width=0.5, color="#1E3A8A")),
                                name="IV Distribution",
                            ))
                            # Current price vertical line
                            fig_mc.add_vline(
                                x=price_d,
                                line=dict(color="#EF4444", width=2.5, dash="dash"),
                                annotation_text=f"Current price  {fmts(price_d, sym)}",
                                annotation_font=dict(color="#EF4444", size=11, family="IBM Plex Mono"),
                                annotation_position="top right",
                            )
                            # Median IV line
                            fig_mc.add_vline(
                                x=_mc_p50,
                                line=dict(color="#059669", width=2, dash="dot"),
                                annotation_text=f"Median IV  {fmts(_mc_p50, sym)}",
                                annotation_font=dict(color="#059669", size=11, family="IBM Plex Mono"),
                                annotation_position="top left",
                            )
                            apply_yieldiq_theme(fig_mc, height=260, extra_kw=dict(
                                showlegend=False,
                                xaxis=dict(title=f"Simulated Intrinsic Value ({to_code})"),
                                yaxis=dict(title="Frequency"),
                                margin=dict(t=40, b=44, l=50, r=20),
                            ))
                            st.plotly_chart(fig_mc, width='stretch', config={
                                "displayModeBar": True,
                                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                "toImageButtonOptions": {"filename": "monte_carlo", "scale": 2},
                            })

                            # ── P10 / P50 / P90 stat boxes ────────────
                            _mc_box_cfg = [
                                ("P10 — Pessimistic",  _mc_p10, "#FEE2E2", "#991B1B", "#DC2626",
                                 "Only 10% of simulations came in below this value"),
                                ("P50 — Median",       _mc_p50, "#EFF6FF", "#1E3A8A", "#1D4ED8",
                                 "Half of all 1,000 simulations landed below this value"),
                                ("P90 — Optimistic",   _mc_p90, "#DCFCE7", "#065F46", "#059669",
                                 "90% of simulations came in below this value"),
                            ]
                            _mc_cols = st.columns(3, gap="medium")
                            for _mc_col, (_mc_lbl, _mc_val, _mc_bg, _mc_dark, _mc_clr, _mc_tip) in zip(_mc_cols, _mc_box_cfg):
                                _mc_col.html(f"""
<div style="background:{_mc_bg};border:1px solid {_mc_clr}33;border-left:4px solid {_mc_clr};
            border-radius:10px;padding:14px 16px;">
  <div style="font-size:10px;font-weight:700;color:{_mc_clr};text-transform:uppercase;
              letter-spacing:0.1em;margin-bottom:6px;">{_mc_lbl}</div>
  <div style="font-size:22px;font-weight:700;color:{_mc_dark};
              font-family:'IBM Plex Mono',monospace;margin-bottom:4px;">
    {fmts(_mc_val, sym)}
  </div>
  <div style="font-size:11px;color:#64748B;line-height:1.5;">{_mc_tip}</div>
</div>""")

                            # ── Extra stats row ───────────────────────
                            st.html('<div style="margin-top:12px;"></div>')
                            mc4, mc5 = st.columns(2)
                            mc4.metric("Std Dev (spread)", fmts(_mc_std, sym),
                                       help="Standard deviation of simulated IVs — wider spread = higher uncertainty")
                            mc5.metric("P(Undervalued)", f"{_mc_prob:.0%}",
                                       help="Share of simulations where IV > current price")

                # ── Reverse DCF
            with st.expander("What growth rate does the current price assume?"):
                pass  # content follows
                # ── Reverse DCF ────────────────────────────────────────
                try:
                    rdcf = run_reverse_dcf(
                        enriched=enriched,
                        current_price=price_n,
                        wacc=wacc,
                        terminal_g=terminal_g,
                        years=forecast_yrs,
                    )
                    impl_g   = rdcf.get("implied_growth", 0)
                    hist_g   = rdcf.get("historical_growth") or 0
                    long_run = rdcf.get("long_run_gdp", 0.025)
                    level    = rdcf.get("verdict_level", "")
                    colour   = rdcf.get("verdict_colour", "amber")
                    ytj      = rdcf.get("years_to_justify")
                    summary  = rdcf.get("summary", "")

                    COLOUR_MAP = {
                        "green": ("#0D7A4E", "#ECFDF5", "#BBF7D0"),
                        "amber": ("#B45309", "#FFFBEB", "#FDE68A"),
                        "red":   ("#B91C1C", "#FEF2F2", "#FECACA"),
                    }
                    txt_c, bg_c, bd_c = COLOUR_MAP.get(colour, COLOUR_MAP["amber"])

                    # Verdict banner
                    st.html(f"""
                    <div style="padding:14px 20px;background:{bg_c};
                                border:1.5px solid {bd_c};border-radius:10px;
                                margin-bottom:16px;">
                      <div style="font-size:13px;font-weight:700;color:{txt_c};
                                  text-transform:uppercase;letter-spacing:.05em;
                                  margin-bottom:6px;">
                        {level.upper()} — {impl_g*100:.1f}% implied annual FCF growth
                      </div>
                      <div style="font-size:13px;color:#0F172A;line-height:1.7;">
                        {summary}
                      </div>
                    </div>
                    """)

                    # Metrics row
                    rc1, rc2, rc3, rc4 = st.columns(4)
                    rc1.metric(
                        "Market-implied growth",
                        f"{impl_g*100:.1f}% / yr",
                        delta=f"{(impl_g - hist_g)*100:+.1f}% above history",
                        delta_color="inverse",
                        help="The annual FCF growth rate the market is betting on for 10 years"
                    )
                    rc2.metric(
                        "Historical FCF growth",
                        f"{hist_g*100:.1f}% / yr",
                        help="What this company has actually delivered"
                    )
                    rc3.metric(
                        "FCF yield",
                        f"{rdcf.get('fcf_yield', 0)*100:.1f}%",
                        help="Free cash flow per share ÷ current price. "
                             "Higher = more cash for every dollar you invest. "
                             "S&P 500 average is ~3.5%."
                    )
                    rc4.metric(
                        "Payback at implied growth",
                        f"{rdcf.get('payback_at_implied')} yrs" if rdcf.get('payback_at_implied') else "10+ yrs",
                        help="If the company delivers the market-implied growth rate, "
                             "how many years until the DCF value equals today's price. "
                             "Shorter is better."
                    )

                    # Growth comparison bar chart
                    st.html("<div style='margin-top:16px;margin-bottom:8px;"
                                "font-size:12px;font-weight:600;color:#475569;"
                                "text-transform:uppercase;letter-spacing:.07em;'>"
                                "Growth rate comparison</div>")

                    rdcf_scenarios = rdcf.get("scenarios", {})
                    bar_data = {
                        "Scenario": [],
                        "Annual FCF Growth (%)": [],
                        "IV per share": [],
                        "MoS vs price": [],
                    }
                    scenario_order = [
                        ("GDP rate",     "#94A3B8"),
                        ("Historical",   "#3B82F6"),
                        ("Half implied", "#F59E0B"),
                        ("Implied",      "#EF4444"),
                    ]
                    colours_bar = []
                    for label, clr in scenario_order:
                        if label in rdcf_scenarios:
                            s = rdcf_scenarios[label]
                            bar_data["Scenario"].append(label)
                            bar_data["Annual FCF Growth (%)"].append(round(s["growth_rate"]*100, 1))
                            bar_data["IV per share"].append(round(s["implied_iv"]*fx, 2))
                            bar_data["MoS vs price"].append(f"{s['mos']*100:+.1f}%")
                            colours_bar.append(clr)

                    # plotly.graph_objects already imported as go above
                    fig_rdcf = go.Figure()
                    fig_rdcf.add_trace(go.Bar(
                        x=bar_data["Scenario"],
                        y=bar_data["Annual FCF Growth (%)"],
                        marker_color=colours_bar,
                        text=[f"{v:.1f}%" for v in bar_data["Annual FCF Growth (%)"]],
                        textposition="outside",
                    ))
                    fig_rdcf.add_hline(
                        y=impl_g * 100,
                        line=dict(color="#EF4444", dash="dot", width=2),
                        annotation_text=f"Market implies {impl_g*100:.1f}%",
                        annotation_font_color="#EF4444",
                    )
                    apply_yieldiq_theme(fig_rdcf, height=240, extra_kw=dict(
                        margin=dict(t=44, b=20, l=20, r=20),
                        yaxis=dict(title="Annual FCF Growth (%)"),
                        showlegend=False,
                    ))
                    st.plotly_chart(fig_rdcf, width='stretch',
                                    config={"displayModeBar": False})

                    # IV table
                    st.html("<div style='margin-top:4px;font-size:12px;font-weight:600;"
                                "color:#475569;text-transform:uppercase;letter-spacing:.07em;'>"
                                "Fair value at each growth scenario</div>")
                    df_rdcf = pd.DataFrame({
                        "Growth scenario": bar_data["Scenario"],
                        "Growth rate":     [f"{v:.1f}%" for v in bar_data["Annual FCF Growth (%)"]],
                        f"Fair value ({sym})": bar_data["IV per share"],
                        "vs today's price":   bar_data["MoS vs price"],
                    })
                    st.dataframe(df_rdcf, width='stretch', hide_index=True)

                    # ── 🤖 AI Explain — Reverse DCF ───────────────────
                    _rdcf_verdict_map = {
                        "green": "appears reasonably priced or undervalued",
                        "amber": "is priced for moderate expectations",
                        "red":   "requires very high growth to justify its price",
                    }
                    _rdcf_verdict_str = _rdcf_verdict_map.get(colour, level)
                    _rdcf_ai_ctx = (
                        f"Reverse DCF analysis for {ticker_input}: "
                        f"The current stock price of {fmts(price_d, sym)} implies the market "
                        f"expects {impl_g*100:.1f}% annual FCF growth over the next {forecast_yrs} years. "
                        f"The company's historical FCF growth was {hist_g*100:.1f}%. "
                        f"Long-run GDP growth assumption is {long_run*100:.1f}%. "
                        f"Assessment: the stock {_rdcf_verdict_str}. "
                        + (f"It would take approximately {ytj:.0f} years for earnings to justify today's price." if ytj else "")
                        + (f" Model summary: {summary[:120]}." if summary else "")
                    )
                    render_ai_explain(_rdcf_ai_ctx, "explain_rdcf")

                except Exception as _rdcf_err:
                    st.warning(f"Reverse DCF could not run: {_rdcf_err}")

                # ── EV/EBITDA Multiples
            with st.expander("How does valuation compare to similar companies?"):
                pass  # content follows
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
                        apply_yieldiq_theme(fig_ev, height=200, extra_kw=dict(
                            margin=dict(t=44, b=20, l=30, r=30),
                            xaxis=dict(title="EV/EBITDA Multiple", range=[0, max_x], ticksuffix="×"),
                            yaxis=dict(visible=False, range=[0, 1]),
                            showlegend=False,
                        ))
                        st.plotly_chart(fig_ev, width='stretch',
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
                            with st.expander(f"Peer multiples ({len(_valid_peers)} companies)"):
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

                # ── Historical Fair Value Chart
            with st.expander("Historical fair value track record"):
                pass  # content follows
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
                        apply_yieldiq_theme(fig_hv, height=260, extra_kw=dict(
                            margin=dict(t=44, b=40, l=60, r=80),
                            xaxis=dict(title="Year"),
                            yaxis=dict(title=f"Price per share ({sym})", tickprefix=sym),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                        xanchor="left", x=0, font=dict(size=11, color="#6B7280")),
                            hovermode="x unified",
                        ))
                        st.plotly_chart(fig_hv, width='stretch',
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

                # ── Dividend Discount Model
            with st.expander("Dividend-based valuation (for income investors)"):
                pass  # content follows
                # Collect dividend yield from all possible sources
                _div_y1 = enriched.get("dividend_yield", 0) or 0
                _div_y2 = raw.get("dividend_yield", 0) or 0
                _div_r1 = enriched.get("dividend_rate", 0) or 0
                _div_r2 = raw.get("dividend_rate", 0) or 0
                _div_yield_raw = _div_y1 or _div_y2 or 0
                _div_rate_raw  = _div_r1 or _div_r2 or 0
                # Normalize: Yahoo sometimes returns yield as integer % (e.g. 276 = 2.76%)
                if _div_yield_raw > 1:
                    _div_yield_raw = _div_yield_raw / 100
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
                            sc_map = {"green":("#065F46","#ECFDF5","#A7F3D0","✅"),
                                      "amber":("#92400E","#FFFBEB","#FDE68A","⚠️"),
                                      "red":  ("#991B1B","#FEF2F2","#FECACA","🚨")}
                            sc_tc,sc_bg,sc_bd,sc_icon = sc_map.get(sc, sc_map["amber"])
                            st.html(
                                f'''<div style="padding:12px 18px;background:{sc_bg};border:1.5px solid {sc_bd};border-radius:10px;margin-bottom:16px;">
                                <div style="font-size:13px;font-weight:700;color:{sc_tc};margin-bottom:4px;">{sc_icon} {ddm["sustainability_msg"]}</div>
                                <div style="font-size:13px;color:#0F172A;line-height:1.7;">{ddm["summary"]}</div></div>''',
                            )
                            dm1,dm2,dm3,dm4,dm5 = st.columns(5)
                            dm1.metric("Dividend yield",  f"{ddm['div_yield']*100:.1f}%")
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
            with st.expander("Is the return worth the risk vs a safe bond?"):
                pass  # content follows
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

                    apply_yieldiq_theme(fig_fy, height=260, extra_kw=dict(
                        margin=dict(t=30, b=20, l=40, r=80),
                        yaxis=dict(title="Yield (%)", ticksuffix="%"),
                        showlegend=False,
                    ))
                    st.plotly_chart(fig_fy, width='stretch',
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
                        sy2.metric("Dividend yield", f"{fy['div_yield']*100:.1f}%")
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
                          ✅ <strong>Key insight:</strong> This stock earns more in free cash flow than
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
                ccard_end()

                # ── Piotroski
        with _sub_ql:
            ccard(add_tooltip("Business Health Check (9-point score)", FINANCIAL_TOOLTIPS["Piotroski Score"]), "#7c3aed")
            try:
                pf = compute_piotroski_fscore(enriched)
                pf_score  = pf["score"]
                pf_grade  = pf["grade"]
                pf_emoji  = pf["grade_emoji"]
                pf_txt_c  = pf["grade_colour"]
                pf_bg_c   = pf["grade_bg"]
                pf_bd_c   = pf["grade_border"]
                pf_cats   = pf["category_scores"]
                pf_sigs   = pf["signals"]

                # Score banner
                _pf_plain = f"{pf_score}/9 signals positive" if pf_score else "No signals available"
                st.html(f"""
                <div style="display:flex;align-items:center;gap:20px;
                            padding:16px 20px;background:{pf_bg_c};
                            border:1.5px solid {pf_bd_c};border-radius:12px;
                            margin-bottom:16px;">
                  <div style="font-size:40px;line-height:1">{pf_emoji}</div>
                  <div style="flex:1">
                    <div style="font-size:32px;font-weight:800;
                                font-family:'IBM Plex Mono',monospace;
                                color:{pf_txt_c};letter-spacing:-0.03em;">
                      {pf_score}/9
                    </div>
                    <div style="font-size:14px;font-weight:600;color:{pf_txt_c};">
                      {pf_grade}
                    </div>
                    <div style="font-size:12px;color:#64748B;margin-top:2px;">
                      {_pf_plain} — higher is healthier
                    </div>
                  </div>
                  <div style="flex:2;font-size:13px;color:#0F172A;line-height:1.7;">
                    {pf["summary"]}
                  </div>
                </div>
                """)

                # Category progress bars
                pb1, pb2, pb3 = st.columns(3)
                cat_cfg = [
                    (pb1, "Profitability", pf_cats["Profitability"], 4, "#059669"),
                    (pb2, "Leverage & Liquidity", pf_cats["Leverage"],  3, "#2563EB"),
                    (pb3, "Operating Efficiency", pf_cats["Efficiency"],2, "#D97706"),
                ]
                for col, label, score_c, max_c, clr in cat_cfg:
                    pct = score_c / max_c * 100
                    col.html(f"""
                    <div style="padding:12px 14px;background:#F8FAFC;
                                border:1px solid #E2E8F0;border-radius:10px;">
                      <div style="font-size:12px;font-weight:700;color:#475569;
                                  text-transform:uppercase;letter-spacing:.07em;
                                  margin-bottom:6px;">{label}</div>
                      <div style="font-size:24px;font-weight:800;color:{clr};
                                  font-family:'IBM Plex Mono',monospace;
                                  margin-bottom:6px;">{score_c}/{max_c}</div>
                      <div style="height:6px;background:#E2E8F0;border-radius:3px;">
                        <div style="height:100%;width:{pct:.0f}%;
                                    background:{clr};border-radius:3px;"></div>
                      </div>
                    </div>
                    """)

                # Signal checklist
                st.html("<div style='margin-top:16px;margin-bottom:8px;"
                            "font-size:12px;font-weight:700;color:#475569;"
                            "text-transform:uppercase;letter-spacing:.07em;'>"
                            "9-Point Signal Breakdown</div>")

                # Group signals by category
                categories = ["Profitability", "Leverage", "Efficiency"]
                cat_labels  = {
                    "Profitability": "Profitability  (4 signals)",
                    "Leverage":      "Leverage & Liquidity  (3 signals)",
                    "Efficiency":    "Operating Efficiency  (2 signals)",
                }

                for cat in categories:
                    cat_sigs = [s for s in pf_sigs if s["category"] == cat]
                    cat_score = sum(s["score"] for s in cat_sigs)
                    cat_max   = len(cat_sigs)

                    with st.expander(f"{cat_labels[cat]} — {cat_score}/{cat_max}", expanded=True):
                        for sig in cat_sigs:
                            icon = "✅" if sig["pass"] else "❌"
                            bg   = "#F0FDF4" if sig["pass"] else "#FEF2F2"
                            bd   = "#BBF7D0" if sig["pass"] else "#FECACA"
                            tc   = "#065F46" if sig["pass"] else "#991B1B"
                            st.html(f"""
                            <div style="display:flex;align-items:flex-start;gap:12px;
                                        padding:10px 14px;background:{bg};
                                        border:1px solid {bd};border-radius:8px;
                                        margin-bottom:6px;">
                              <div style="font-size:16px;flex-shrink:0;margin-top:1px">{icon}</div>
                              <div style="flex:1">
                                <div style="font-size:13px;font-weight:600;color:{tc};">
                                  {sig['key'].upper()}  {sig['label']}
                                </div>
                                <div style="font-size:12px;color:#64748B;margin-top:2px;">
                                  {sig['detail']}
                                </div>
                              </div>
                              <div style="font-size:20px;font-weight:800;
                                          color:{tc};font-family:'IBM Plex Mono',monospace;">
                                {sig['score']}
                              </div>
                            </div>
                            """)

                # Academic note
                st.caption(f"📚 {pf['academic_note']}")

                # ── 🤖 AI Explain — Piotroski ─────────────────────
                _pf_passed = [s["label"] for s in pf_sigs if s.get("pass")]
                _pf_failed = [s["label"] for s in pf_sigs if not s.get("pass")]
                _pf_ai_ctx = (
                    f"{ticker_input} Piotroski F-Score: {pf_score}/9 — {pf_grade}. "
                    f"Profitability sub-score: {pf_cats['Profitability']}/4, "
                    f"Leverage & Liquidity: {pf_cats['Leverage']}/3, "
                    f"Operating Efficiency: {pf_cats['Efficiency']}/2. "
                    + (f"Signals passed: {', '.join(_pf_passed[:4])}. " if _pf_passed else "")
                    + (f"Signals failed: {', '.join(_pf_failed[:4])}." if _pf_failed else "")
                )
                render_ai_explain(_pf_ai_ctx, "explain_piotroski")

            except Exception as _pf_err:
                st.warning(f"Piotroski F-Score could not run: {_pf_err}")
            ccard_end()

            # ── Earnings Quality Score ─────────────────────────────
            ccard("Are the company's profits backed by real cash?", "#0f766e")
            try:
                eq = compute_earnings_quality(enriched)
                eq_score = eq["score"]
                eq_grade = eq["grade"]
                eq_emoji = eq["grade_emoji"]
                eq_txt_c = eq["grade_colour"]
                eq_bg_c  = eq["grade_bg"]
                eq_bd_c  = eq["grade_border"]
                eq_cats  = eq["category_scores"]
                eq_facts = eq["factors"]

                # Score banner
                st.html(f"""
                <div style="display:flex;align-items:center;gap:20px;
                            padding:16px 20px;background:{eq_bg_c};
                            border:1.5px solid {eq_bd_c};border-radius:12px;
                            margin-bottom:16px;">
                  <div style="text-align:center;min-width:80px;">
                    <div style="font-size:40px;line-height:1">{eq_emoji}</div>
                    <div style="font-size:32px;font-weight:800;
                                font-family:'IBM Plex Mono',monospace;
                                color:{eq_txt_c};letter-spacing:-0.03em;">
                      {eq_score:.0f}
                    </div>
                    <div style="font-size:12px;color:{eq_txt_c};
                                font-weight:700;letter-spacing:.1em;">/ 100</div>
                  </div>
                  <div style="width:1px;height:70px;background:{eq_bd_c}"></div>
                  <div style="flex:1">
                    <div style="font-size:16px;font-weight:700;
                                color:{eq_txt_c};margin-bottom:6px;">
                      {eq_grade}
                    </div>
                    <div style="font-size:13px;color:#0F172A;line-height:1.7;">
                      {eq["summary"]}
                    </div>
                  </div>
                </div>
                """)

                # Category scores
                cat_order = ["Cash Conversion","Earnings Stability","Balance Sheet","Growth Quality"]
                cat_icons = {"Cash Conversion":"💵","Earnings Stability":"📊",
                             "Balance Sheet":"🏦","Growth Quality":"📈"}
                cat_cols  = st.columns(len(cat_order))

                for col, cat in zip(cat_cols, cat_order):
                    val = eq_cats.get(cat, 50)
                    clr = ("#059669" if val >= 70 else
                           "#D97706" if val >= 50 else "#DC2626")
                    col.html(f"""
                    <div style="padding:12px 14px;background:#F8FAFC;
                                border:1px solid #E2E8F0;border-radius:10px;
                                text-align:center;">
                      <div style="font-size:20px">{cat_icons.get(cat,'📌')}</div>
                      <div style="font-size:12px;font-weight:700;color:#475569;
                                  text-transform:uppercase;letter-spacing:.05em;
                                  margin:4px 0;">{cat}</div>
                      <div style="font-size:24px;font-weight:800;color:{clr};
                                  font-family:'IBM Plex Mono',monospace;">
                        {val:.0f}
                      </div>
                      <div style="height:4px;background:#E2E8F0;border-radius:2px;margin-top:6px;">
                        <div style="height:100%;width:{val}%;
                                    background:{clr};border-radius:2px;"></div>
                      </div>
                    </div>
                    """)

                # Factor breakdown
                st.html("<div style='margin-top:16px;margin-bottom:8px;"
                            "font-size:12px;font-weight:700;color:#475569;"
                            "text-transform:uppercase;letter-spacing:.07em;'>"
                            "8-Factor Breakdown</div>")

                for cat in cat_order:
                    cat_facts = [f for f in eq_facts if f["category"] == cat]
                    cat_val   = eq_cats.get(cat, 50)
                    cat_score_label = (
                        "Excellent" if cat_val >= 85 else
                        "Good"      if cat_val >= 70 else
                        "Moderate"  if cat_val >= 50 else
                        "Weak"
                    )
                    with st.expander(
                        f"{cat}  —  {cat_val:.0f}/100 ({cat_score_label})",
                        expanded=(cat_val < 50)  # auto-expand weak categories
                    ):
                        for f in cat_facts:
                            score_pct = f["score"] / 100
                            bar_fill  = int(f["score"] / 10)
                            bar_empty = 10 - bar_fill
                            clr_f = ("#059669" if f["score"] >= 70 else
                                     "#D97706" if f["score"] >= 50 else "#DC2626")
                            st.html(f"""
                            <div style="padding:10px 14px;background:#F8FAFC;
                                        border:1px solid #E2E8F0;border-radius:8px;
                                        margin-bottom:6px;">
                              <div style="display:flex;align-items:center;
                                          gap:10px;margin-bottom:4px;">
                                <div style="font-size:12px;font-weight:700;
                                            color:#475569;text-transform:uppercase;
                                            width:24px;">{f['key'].upper()}</div>
                                <div style="flex:1;font-size:13px;font-weight:600;
                                            color:#0F172A;">{f['label']}</div>
                                <div style="font-size:13px;font-weight:800;
                                            color:{clr_f};
                                            font-family:'IBM Plex Mono',monospace;
                                            min-width:36px;text-align:right;">
                                  {f['score']:.0f}
                                </div>
                              </div>
                              <div style="height:4px;background:#E2E8F0;
                                          border-radius:2px;margin-bottom:6px;">
                                <div style="height:100%;width:{f['score']}%;
                                            background:{clr_f};border-radius:2px;"></div>
                              </div>
                              <div style="font-size:12px;color:#64748B;">
                                {f['detail']}
                              </div>
                            </div>
                            """)

                # Red flags callout
                if eq["red_flags"]:
                    flags_str = " · ".join(eq["red_flags"])
                    st.html(f"""
                    <div style="padding:10px 14px;background:#FEF2F2;
                                border:1px solid #FECACA;border-radius:8px;
                                font-size:12px;color:#991B1B;margin-top:8px;">
                      ⚠️ <strong>Red flags (score &lt;35):</strong> {flags_str}
                    </div>
                    """)

                if eq["green_flags"]:
                    flags_str = " · ".join(eq["green_flags"])
                    st.html(f"""
                    <div style="padding:10px 14px;background:#ECFDF5;
                                border:1px solid #A7F3D0;border-radius:8px;
                                font-size:12px;color:#065F46;margin-top:6px;">
                      ✅ <strong>Strengths (score ≥85):</strong> {flags_str}
                    </div>
                    """)

                st.caption(f"📚 {eq['academic_note']}")

            except Exception as _eq_err:
                st.warning(f"Earnings quality could not run: {_eq_err}")
            ccard_end()

            # ── Sector Relative Valuation ──────────────────────────

        with _sub_sg:
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
                        "Sector Undervalued signals",
                        f"{screen['buy_pct']:.0f}%",
                        help=f"% of sector with Undervalued signal. Overvalued: {screen['sell_pct']:.0f}%"
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
                        {'UV ' + str(round(screen['buy_pct'])) + '%' if screen['buy_pct'] > 8 else ''}
                      </div>
                      <div style="width:{screen.get('watch_pct',0)}%;background:#2563EB;
                                  min-width:0;"></div>
                      <div style="flex:1;background:#E2E8F0;min-width:0;"></div>
                      <div style="width:{screen['sell_pct']}%;background:#DC2626;
                                  display:flex;align-items:center;justify-content:center;
                                  font-size:12px;color:#fff;font-weight:700;min-width:0;">
                        {'OV ' + str(round(screen['sell_pct'])) + '%' if screen['sell_pct'] > 8 else ''}
                      </div>
                    </div>
                    <div style="display:flex;gap:16px;margin-top:4px;font-size:12px;color:#64748B;">
                      <span>🟢 Undervalued {screen['buy_pct']:.0f}%</span>
                      <span>🔴 Overvalued {screen['sell_pct']:.0f}%</span>
                      <span>⚪ Other {100-screen['buy_pct']-screen['sell_pct']:.0f}%</span>
                    </div>
                    """)

                    # Top picks in sector
                    top = screen.get("top_picks")
                    if top is not None and not top.empty:
                        with st.expander(f"Top picks in {sr['sector_name']} by margin of safety"):
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

        # ── News & SEC Filings ──────────────────────────────────
        st.markdown("---")
        _render_news_panel(
            ticker       = ticker_input,
            company_name = company_name,
        )

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
                # Free tier — offer purchase
                st.html(f"""
                <div style="text-align:center;padding:8px;">
                  <a href="https://buy.stripe.com/your_link_here" target="_blank"
                     style="background:#5046e4;color:#fff;font-size:13px;font-weight:600;
                            padding:9px 20px;border-radius:8px;text-decoration:none;
                            display:inline-block;width:100%;text-align:center;">
                    📄 Buy Report — $4.99
                  </a>
                </div>
                """)
            elif not _can_dl:
                st.warning(f"📄 {_dl_reason}")
                st.caption(f"Extra reports: ${limit('report_cost'):.2f} each")
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

        # ── Full DCF Audit ─────────────────────────────────────
        with st.expander("Full technical model details (for advanced users)"):
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
                "Discount to fair value":       f"{mos_pct:.1f}%",
                "Our recommendation":           sig,
                "FX rate used":                 f"1 {native_ccy} = {fx:.4f} {to_code}",
            }
            detail_clean = {k: str(v) if not isinstance(v, str) else v
                           for k, v in detail.items()}
            st.dataframe(pd.DataFrame.from_dict(detail_clean, orient="index", columns=["Value"]),
                         width='stretch')


# ══════════════════════════════════════════════════════════════
# TAB 2 — FINANCIAL STATEMENTS
# ══════════════════════════════════════════════════════════════
