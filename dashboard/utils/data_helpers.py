"""dashboard/utils/data_helpers.py
Utility functions, formatting, FX, data fetching, and display helpers.
Moved from app.py to break circular imports.
"""
from __future__ import annotations
import logging
import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go

log = logging.getLogger(__name__)
from data.collector import StockDataCollector
from models.forecaster import compute_wacc
from screener.momentum import calculate_momentum


CURRENCIES = {
    "INR": {"symbol": "₹", "code": "INR"},
    "USD": {"symbol": "$", "code": "USD"},
    "GBP": {"symbol": "£", "code": "GBP"},
    "EUR": {"symbol": "€", "code": "EUR"},
}

# ── Hardcoded fallback rates (updated Mar 2025) ───────────────
# Used ONLY when ALL live APIs fail. Update these quarterly.
_FX_FALLBACK = {
    ("USD", "INR"): 83.5,  ("INR", "USD"): 1/83.5,
    ("USD", "EUR"): 0.92,  ("EUR", "USD"): 1/0.92,
    ("USD", "GBP"): 0.79,  ("GBP", "USD"): 1/0.79,
    ("USD", "JPY"): 149.0, ("JPY", "USD"): 1/149.0,
    ("INR", "EUR"): 0.011, ("EUR", "INR"): 90.0,
    ("INR", "GBP"): 0.0095,("GBP", "INR"): 105.0,
}

@st.cache_data(ttl=1800, show_spinner=False)
def get_fx_rate(from_ccy: str, to_ccy: str) -> float:
    """
    Fetch live FX rate with 3-tier fallback:
      1. exchangerate-api.com  (primary, free tier)
      2. frankfurter.app       (secondary, ECB data)
      3. Hardcoded table       (quarterly-updated emergency fallback)
    Cache: 30 minutes (ttl=1800). Never returns stale session value.
    """
    if not from_ccy or not to_ccy:
        return 1.0
    fc, tc = from_ccy.upper().strip(), to_ccy.upper().strip()
    if fc == tc:
        return 1.0
    try:
        r = requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{fc}",
            timeout=6,
        )
        if r.status_code == 200:
            rate = float(r.json().get("rates", {}).get(tc, 0))
            if rate > 0:
                return rate
    except Exception as _e1:
        print(f"[YieldIQ] FX tier-1 fetch failed ({fc}→{tc}): {_e1}")
    try:
        r = requests.get(
            f"https://api.frankfurter.app/latest?from={fc}&to={tc}",
            timeout=6,
        )
        if r.status_code == 200:
            rate = float(r.json().get("rates", {}).get(tc, 0))
            if rate > 0:
                return rate
    except Exception as _e2:
        print(f"[YieldIQ] FX tier-2 fetch failed ({fc}→{tc}): {_e2}")
    # Tier 3: hardcoded fallback
    fallback = _FX_FALLBACK.get((fc, tc))
    if fallback:
        return fallback
    # Last resort: try reverse
    rev = _FX_FALLBACK.get((tc, fc))
    if rev and rev != 0:
        return 1.0 / rev
    return 1.0

def _get_cache_ttl() -> int:
    """Return cache TTL based on user tier."""
    t = st.session_state.get("_tier", "free")
    return {"pro": 60, "starter": 180, "premium": 180, "free": 600}.get(t, 600)

_DATA_VERSION = "v5_tsla_growth_floor"  # bump this to bust cache after engine changes

def fetch_stock_data(ticker):
    """Wrapper that applies tiered TTL caching."""
    return _fetch_stock_data_cached(ticker, _get_cache_ttl(), _DATA_VERSION)

@st.cache_data(ttl=600, show_spinner=False)
def _fetch_stock_data_cached(ticker, _ttl_key, _version):
    """Actual cached fetch — _version parameter busts cache after code changes."""
    try:
        collector  = StockDataCollector(ticker)
        raw        = collector.get_all()
    except Exception as _fetch_err:
        print(f"FETCH_ERROR {ticker}: {type(_fetch_err).__name__}: {_fetch_err}")
        raw = None
        collector = None

    if raw is None:
        print(f"FETCH_FAIL {ticker}: raw is None — trying FMP direct fallback")
        # ── FMP DIRECT FALLBACK — build raw dict entirely from FMP ──
        try:
            import os as _os
            from data.collector import (
                _fmp_income_statement, _fmp_cashflow, _fmp_balance_sheet,
                _fmp_profile, _fh_quote, _fh_basic_financials,
            )
            # Read keys fresh — don't use imported module-level values (may be stale)
            _has_fmp = bool(_os.environ.get("FMP_API_KEY", ""))
            _has_fh  = bool(_os.environ.get("FINNHUB_API_KEY", ""))
            if not _has_fmp:
                try:
                    _has_fmp = bool(st.secrets.get("FMP_API_KEY", ""))
                    if _has_fmp:
                        _os.environ["FMP_API_KEY"] = st.secrets["FMP_API_KEY"]
                except Exception:
                    pass
            if not _has_fh:
                try:
                    _has_fh = bool(st.secrets.get("FINNHUB_API_KEY", ""))
                    if _has_fh:
                        _os.environ["FINNHUB_API_KEY"] = st.secrets["FINNHUB_API_KEY"]
                except Exception:
                    pass
            # Also update collector module globals
            import data.collector as _coll_mod
            if _has_fmp and not _coll_mod.FMP_KEY:
                _coll_mod.FMP_KEY = _os.environ.get("FMP_API_KEY", "")
            if _has_fh and not _coll_mod.FINNHUB_KEY:
                _coll_mod.FINNHUB_KEY = _os.environ.get("FINNHUB_API_KEY", "")

            print(f"FMP_FALLBACK_CHECK {ticker}: FMP={'YES' if _has_fmp else 'NO'}, FH={'YES' if _has_fh else 'NO'}")

            _fmp_t = ticker.split(".")[0]
            _fmp_inc = _fmp_income_statement(_fmp_t) if _has_fmp else pd.DataFrame()
            _fmp_cf  = _fmp_cashflow(_fmp_t) if _has_fmp else pd.DataFrame()
            _fmp_bs  = _fmp_balance_sheet(_fmp_t) if _has_fmp else {}
            _fmp_pr  = _fmp_profile(_fmp_t) if _has_fmp else {}
            _fh_q    = _fh_quote(ticker) if _has_fh else {}
            _fh_f    = _fh_basic_financials(ticker) if _has_fh else {}

            _price = (_fh_q or {}).get("price", 0) or (_fmp_pr or {}).get("price", 0)
            _shares = (_fmp_pr or {}).get("shares", 0)

            if _price > 0 and not _fmp_inc.empty:
                print(f"FMP_DIRECT_OK {ticker}: price={_price}, {len(_fmp_inc)} yrs financials, shares={_shares:,.0f}")
                # Build a minimal raw dict that compute_metrics can process
                raw = {
                    "ticker": ticker,
                    "price": _price,
                    "shares": _shares,
                    "total_debt": (_fmp_bs or {}).get("total_debt", 0),
                    "total_cash": (_fmp_bs or {}).get("total_cash", 0),
                    "income_df": _fmp_inc,
                    "cf_df": _fmp_cf,
                    "native_ccy": "USD",
                    "fin_multiplier": 1.0,
                    "forward_eps": (_fh_f or {}).get("eps_ttm", 0),
                    "trailing_eps": (_fh_f or {}).get("eps_ttm", 0),
                    "forward_pe": (_fh_f or {}).get("pe_ttm", 0),
                    "peg_ratio": 0,
                    "roe": (_fh_f or {}).get("roe_ttm", 0),
                    "roce_proxy": 0,
                    "de_ratio": (_fh_f or {}).get("debt_to_equity", 0),
                    "interest_cov": 0,
                    "gross_margin": (_fh_f or {}).get("gross_margin_ttm", 0),
                    "sector_name": (_fmp_pr or {}).get("sector", ""),
                    "company_name": (_fmp_pr or {}).get("company_name", ticker),
                    "norm_capex_pct": None,
                    "ebitda": 0,
                    "enterprise_value": 0,
                    "ev_to_ebitda": (_fh_f or {}).get("ev_ebitda_ttm", 0),
                    "ev_to_revenue": 0,
                    "yahoo_fcf_ttm": 0,
                    "dividend_yield": (_fh_f or {}).get("div_yield_ttm", 0),
                    "dividend_rate": 0,
                    "payout_ratio": 0,
                    "five_yr_avg_div_yield": 0,
                    "price_change_pct": (_fh_q or {}).get("change_pct", 0),
                    "day_high": (_fh_q or {}).get("day_high", 0),
                    "day_low": (_fh_q or {}).get("day_low", 0),
                    "finnhub_price_target": {},
                    "finnhub_rec_trend": [],
                    "finnhub_earnings": [],
                    "earnings_track_record": {},
                    "finnhub_next_earnings": {},
                    "news": [],
                    "finnhub_financials": _fh_f or {},
                    "fh_beta": (_fh_f or {}).get("beta", 0),
                    "fh_div_yield": (_fh_f or {}).get("div_yield_ttm", 0),
                    "fh_52w_high": (_fh_f or {}).get("52w_high", 0),
                    "fh_52w_low": (_fh_f or {}).get("52w_low", 0),
                    "exchange": "",
                    "pe_ratio": (_fh_f or {}).get("pe_ttm", 0),
                }
                # Return the FMP-built raw dict — full DCF will run
                return raw, pd.DataFrame(), {}, {
                    'momentum_score': 0, 'grade': 'N/A',
                    'signal': 'N/A ⬜', 'components': {}, 'indicators': {}
                }
            else:
                print(f"FMP_DIRECT_FAIL {ticker}: price={_price}, income_rows={len(_fmp_inc) if not _fmp_inc.empty else 0}")
        except Exception as _fmp_err:
            print(f"FMP_DIRECT_ERROR {ticker}: {type(_fmp_err).__name__}: {_fmp_err}")

        return None, pd.DataFrame(), {}, {'momentum_score': 0, 'grade': 'N/A', 'signal': 'N/A ⬜', 'components': {}, 'indicators': {}}

    price_hist = pd.DataFrame()
    wacc_data  = {}

    if collector and collector._ticker_obj:
        price_hist = collector.get_price_history(period="1y")
        is_indian  = ticker.endswith(".NS") or ticker.endswith(".BO")
        wacc_data  = compute_wacc(collector._ticker_obj, is_indian)

    momentum_result = {
        'momentum_score': 0,
        'grade': 'N/A',
        'signal': 'N/A ⬜',
        'components': {},
        'indicators': {}
    }

    if not price_hist.empty and len(price_hist) >= 50:
        try:
            momentum_result = calculate_momentum(price_hist)
        except Exception as e:
            st.warning(f"⚠️ Could not calculate momentum: {e}")

    if raw:
        print(f"LIVE_CHECK div_yield={raw.get('dividend_yield')} fh_div={raw.get('fh_div_yield')} pe={raw.get('forward_pe')} fcf_g={raw.get('fcf_growth')}")

    return raw, price_hist, wacc_data, momentum_result

def fmt(v, sym, d=2):
    a = abs(v)
    if a >= 1e12: return f"{sym}{v/1e12:,.2f}T"
    if a >= 1e9:  return f"{sym}{v/1e9:,.2f}B"
    if a >= 1e6:  return f"{sym}{v/1e6:,.2f}M"
    return f"{sym}{v:,.{d}f}"

def fmts(v, sym): 
    return f"{sym}{v:,.2f}"

# ── HUMAN LANGUAGE TRANSLATION HELPERS ─────────────────────────
_SIG_HUMAN = {
    "Undervalued 🟢":    ("📊 Undervalued by model estimate",  "#0D7A4E", "#F0FDF4", "#BBF7D0"),
    "Near Fair Value 🟡":("📉 Slightly below model fair value", "#B45309", "#FFFBEB", "#FDE68A"),
    "Fairly Valued 🔵":  ("⚖️ Near model fair value",           "#1D4ED8", "#EFF6FF", "#BFDBFE"),
    "Overvalued 🔴":     ("📈 Overvalued by model estimate",    "#B91C1C", "#FEF2F2", "#FECACA"),
    "⚠️ Data Limited":   ("🔍 Model data needs review",         "#B45309", "#FFFBEB", "#FDE68A"),
    "N/A ⬜":            ("⏳ Analysing…",                     "#4A5E7A", "#FFFFFF", "#F8FAFC"),
}

def sig_human(sig):
    """Return (human_label, fg, bg, border) for a signal string."""
    return _SIG_HUMAN.get(sig, ("⏳ Analysing…", "#4A5E7A", "#FFFFFF", "#F8FAFC"))

def mos_insight(mos_pct: float, sig: str, company: str, suspicious: bool) -> str:
    """One-line model-output summary. No advice language."""
    if suspicious:
        return f"⚠️ {company}'s financials show unusual patterns — model estimates may be unreliable."
    if mos_pct >= 20:
        return f"📊 Our model estimates {company} is trading ~{mos_pct:.0f}% below its calculated fair value."
    elif mos_pct >= 5:
        return f"📊 Our model estimates {company} is trading ~{mos_pct:.0f}% below its calculated fair value."
    elif mos_pct >= -5:
        return f"⚖️ {company} is trading close to our model's estimated fair value."
    elif mos_pct >= -15:
        return f"📊 Our model estimates {company} is trading ~{abs(mos_pct):.0f}% above its calculated fair value."
    else:
        return f"📊 Our model estimates {company} is trading ~{abs(mos_pct):.0f}% above its calculated fair value."

def plain_kpi_label(label: str) -> str:
    """Translate finance jargon into plain English for KPI cards."""
    _MAP = {
        "Margin of Safety":   "Discount to fair value",
        "WACC":               "Required return rate",
        "Op Margin":          "Profit per ₹100 revenue",
        "FCF Growth":         "Cash flow growth",
        "Revenue Growth":     "Revenue growth",
        "Confidence":         "Model reliability",
        "Intrinsic Value":    "Estimated fair value",
        "IV (DCF+PE Blend)":  "Estimated fair value",
        "Intrinsic Value (DCF)": "Estimated fair value",
        "Current Price":      "Current price",
    }
    return _MAP.get(label, label)

def _get_active_theme() -> dict:
    """Read the active theme dict from session_state."""
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent.parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    _name = st.session_state.get("theme", "forest")
    return _tm.get_theme(_name)

def KL(**kw):
    """Theme-aware chart layout — apply to every fig.update_layout()."""
    t = _get_active_theme()
    base = dict(
        paper_bgcolor=t["chart_paper"],
        plot_bgcolor=t["chart_bg"],
        font=dict(family="Inter, DM Sans, system-ui, sans-serif", color=t["chart_font"], size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=t["bg3"],
            font=dict(color=t["text"], family="IBM Plex Mono, monospace", size=12),
            bordercolor=t["border2"],
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor=t["border"],
            borderwidth=1,
            font=dict(color=t["text2"], size=11),
        ),
        xaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False,
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base

def apply_koyfin(fig, accent=None, height=280, title_txt="", extra_kw=None):
    """One-call upgrade: themed layout + accent top border + axis polish."""
    t = _get_active_theme()
    if accent is None:
        accent = t["accent"]
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(text=title_txt, font=dict(color=t["text"], size=13, family="Inter, sans-serif"), x=0, pad=dict(l=4))
    if extra_kw:
        kw.update(extra_kw)
    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["text3"], size=10))
    fig.update_yaxes(gridcolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["text3"], size=10))
    # Accent top-border
    fig.add_shape(type="line", xref="paper", yref="paper",
                  x0=0, x1=1, y0=1, y1=1,
                  line=dict(color=accent, width=2),
                  layer="above")
    return fig

def CL(**kw):
    """Theme-aware clean/light chart layout."""
    t = _get_active_theme()
    base = dict(
        paper_bgcolor=t["chart_paper"], plot_bgcolor=t["chart_bg"],
        font=dict(family="Inter,sans-serif", color=t["text2"], size=11),
        margin=dict(t=20, b=40, l=10, r=10),
        xaxis=dict(gridcolor=t["chart_grid"], linecolor=t["border"], zeroline=False, tickcolor=t["border2"], tickfont=dict(color=t["text3"])),
        yaxis=dict(gridcolor=t["chart_grid"], linecolor=t["border"], zeroline=False, tickcolor=t["border2"], tickfont=dict(color=t["text3"])),
        hoverlabel=dict(bgcolor=t["bg3"], bordercolor=t["accent"],
                        font=dict(color=t["text"], family="IBM Plex Mono", size=12)),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base

@st.cache_data(ttl=3600, show_spinner=False)
def generate_ai_summary(
    ticker: str, company_name: str, price: float, iv: float,
    mos_pct: float, signal: str, piotroski_score: int, wacc: float,
    rev_growth: float, fcf_growth: float, op_margin: float,
    moat_grade: str, sym: str,
) -> str:
    """Generate a plain-English stock summary using Gemini 2.0 Flash (free tier)."""
    import os as _os
    _prompt = (
        f"You are a senior equity analyst. Write a concise 3-paragraph stock analysis "
        f"in plain English for a retail investor. Be balanced, factual, and specific. "
        f"Do NOT say 'buy' or 'sell'. Use 'appears undervalued/overvalued by the model'.\n\n"
        f"Stock: {company_name} ({ticker})\n"
        f"Current Price: {sym}{price:,.2f}\n"
        f"Model Intrinsic Value: {sym}{iv:,.2f}\n"
        f"Margin of Safety: {mos_pct:.1f}%\n"
        f"Model Signal: {signal}\n"
        f"Piotroski F-Score: {piotroski_score}/9\n"
        f"Revenue Growth: {rev_growth:.1%}\n"
        f"FCF Growth: {fcf_growth:.1%}\n"
        f"Operating Margin: {op_margin:.1%}\n"
        f"WACC (Required Return): {wacc:.1%}\n"
        f"Economic Moat: {moat_grade}\n\n"
        f"Write exactly 3 paragraphs:\n"
        f"Para 1 (2-3 sentences): What does this company do and what does the valuation tell us?\n"
        f"Para 2 (2-3 sentences): What are the key financial strengths or concerns?\n"
        f"Para 3 (1-2 sentences): What is the main risk or watchpoint for this thesis?\n\n"
        f"Keep total response under 200 words. No headers. No bullets. Plain paragraphs only.\n"
        f"End with a one-line disclaimer: This is model output, not investment advice."
    )
    # ── Try Gemini first, fall back to Groq ──────────────────
    _gemini_key = _os.environ.get("GEMINI_API_KEY", "").strip()
    _groq_key   = _os.environ.get("GROQ_API_KEY",   "").strip()

    if _gemini_key:
        try:
            from google import genai as _genai
            _client = _genai.Client(api_key=_gemini_key)
            _response = _client.models.generate_content(
                model="gemini-2.0-flash", contents=_prompt,
            )
            return _response.text.strip()
        except Exception as _e:
            _err = str(_e).lower()
            if not any(k in _err for k in ("quota", "429", "resource_exhausted", "limit")):
                return f"AI summary unavailable: {_e}"
            # quota/region error → fall through to Groq

    if _groq_key:
        try:
            from groq import Groq as _Groq
            _client = _Groq(api_key=_groq_key)
            _resp = _client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": _prompt}],
                max_tokens=400,
                temperature=0.3,
            )
            return _resp.choices[0].message.content.strip()
        except Exception as _e:
            return f"AI summary unavailable: {_e}"

    return "AI summary unavailable: add GEMINI_API_KEY or GROQ_API_KEY to .env"


def _yf_fast_info_with_retry(sym: str, max_attempts: int = 1):
    """Fetch yfinance fast_info — single attempt, no blocking retries.
    Market overview/pulse are cosmetic; they must not block page load."""
    import yfinance as yf
    try:
        fi = yf.Ticker(sym).fast_info
        return fi
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_overview():
    symbols = {
        "S&P 500":   "^GSPC",
        "NASDAQ":    "^IXIC",
        "Dow Jones": "^DJI",
        "Gold":      "GC=F",
        "10Y UST":   "^TNX",
    }
    results = {}
    for name, sym in symbols.items():
        try:
            fi = _yf_fast_info_with_retry(sym)
            price = float(getattr(fi, "last_price", 0) or 0) if fi else 0
            prev  = float(getattr(fi, "previous_close", 0) or 0) if fi else 0
            chg   = ((price - prev) / prev * 100) if prev > 0 else 0
            results[name] = {"price": price, "change_pct": chg, "symbol": sym}
        except Exception as _e:
            log.warning(f"[market_overview] price fetch failed for {sym}: {_e}")
            results[name] = {"price": 0, "change_pct": 0, "symbol": sym}
    return results


@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_pulse():
    """Fetch S&P 500, 10Y Treasury, VIX for the sidebar Market Pulse widget."""
    _pulse_syms = [("S&P 500", "^GSPC"), ("10Y Yield", "^TNX"), ("VIX", "^VIX")]
    result = {}
    for name, sym in _pulse_syms:
        try:
            fi    = _yf_fast_info_with_retry(sym)
            price = float(getattr(fi, "last_price", 0) or 0) if fi else 0
            prev  = float(getattr(fi, "previous_close", 0) or 0) if fi else 0
            chg   = ((price - prev) / prev * 100) if prev > 0 else 0
            result[name] = {"price": price, "chg": chg}
        except Exception as _e:
            log.warning(f"[market_pulse] {sym}: {_e}")
            result[name] = {"price": 0, "chg": 0}
    return result


def show_upgrade_modal(feature_name: str = "this feature"):
    _features = [
        ("♾️", "Unlimited stock analyses"),
        ("🎲", "Monte Carlo — 1,000 simulations"),
        ("📥", "Excel DCF model download"),
        ("🤖", "AI plain-English stock summary"),
        ("🌍", "US + India + Europe markets"),
    ]
    _rows_html = ""
    for _fi, _ft in _features:
        _rows_html += (
            '<div style="display:flex;align-items:center;gap:10px;padding:8px 0;'
            'border-bottom:0.5px solid #F1F5F9;">'
            f'<div style="font-size:15px;width:24px;text-align:center;">{_fi}</div>'
            f'<div style="font-size:12px;color:#334155;flex:1;">{_ft}</div>'
            '<div style="color:#059669;font-size:13px;">✓</div>'
            '</div>'
        )
    st.html(f"""
    <div style="position:relative;background:rgba(0,0,0,0.04);border-radius:14px;
                padding:20px;margin:8px 0;">
      <div style="background:linear-gradient(135deg,#0f2537,#1d4ed8);
                  border-radius:12px 12px 0 0;padding:20px 20px 16px;position:relative;">
        <div style="display:inline-block;background:rgba(245,158,11,0.2);
                    border:1px solid rgba(245,158,11,0.4);color:#f59e0b;
                    font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;
                    margin-bottom:8px;">🔒 PRO FEATURE</div>
        <div style="font-size:18px;font-weight:700;color:white;">Unlock YieldIQ Pro</div>
        <div style="font-size:12px;color:rgba(255,255,255,0.55);margin-top:3px;">
          {feature_name} requires a Starter or Pro plan</div>
      </div>
      <div style="background:white;border-radius:0 0 12px 12px;border:1px solid #E2E8F0;
                  border-top:none;padding:16px 20px;">
        {_rows_html}
      </div>
    </div>
    """)
    col1, col2 = st.columns(2)
    with col1:
        st.link_button("Upgrade to Pro — $49/mo →", "https://yieldiq.app/pricing", width='stretch', type="primary")  # Pro price is $49/mo
    with col2:
        st.link_button("See all plans", "https://yieldiq.app/pricing", width='stretch')



# ══════════════════════════════════════════════════════════════
# RELATIVE VALUATION VIEW  (non-DCF stocks: banks, REITs, etc.)
# ══════════════════════════════════════════════════════════════

def _render_relative_valuation_view(
    ticker:    str,
    rv:        dict,
    raw:       dict,
    sym:       str = "$",
    fx:        float = 1.0,
) -> None:
    """Render the full dashboard view for a non-DCF stock using relative valuation."""
    price      = rv.get("price", 0) * fx
    name       = rv.get("name") or raw.get("company_name", ticker)
    signal     = rv.get("signal", "N/A ⬜")
    avg_pct    = rv.get("signal_avg_pct", 0)
    sector_lbl = rv.get("gics_sector") or rv.get("sector_key", "Financial / Real Estate")
    metrics    = rv.get("metrics", [])
    mkt_cap    = rv.get("market_cap", 0)
    div_yield  = rv.get("dividend_yield", 0)
    beta       = rv.get("beta", 0)
    hi52       = rv.get("52w_high", 0) * fx
    lo52       = rv.get("52w_low", 0) * fx

    # Signal colour
    if "Discount" in signal:
        sig_fg, sig_bg, sig_bd = "#0D7A4E", "#ECFDF5", "#6EE7B7"
    elif "Premium" in signal:
        sig_fg, sig_bg, sig_bd = "#A62020", "#FEF2F2", "#FECACA"
    else:
        sig_fg, sig_bg, sig_bd = "#B8972A", "#FFFBEB", "#FDE68A"

    # ── Banner: non-DCF notice ─────────────────────────────────
    st.info(
        f"**{name}** ({ticker}) is in the **{sector_lbl}** sector. "
        "DCF valuation is not applicable for this company type. "
        "Showing relative valuation vs sector medians instead.",
        icon="ℹ️",
    )

    # ── Header row ────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown(f"## {name}")
        st.caption(f"{ticker} · {sector_lbl}")
    with c2:
        st.markdown(
            f"<div style='text-align:center;padding:8px 0'>"
            f"<div style='font-size:0.8rem;color:#6B7280'>Price</div>"
            f"<div style='font-size:1.6rem;font-weight:700'>{sym}{price:,.2f}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div style='text-align:center;padding:4px 8px;"
            f"background:{sig_bg};border:1px solid {sig_bd};"
            f"border-radius:8px;color:{sig_fg};font-weight:700'>"
            f"{signal}<br>"
            f"<span style='font-size:0.75rem;font-weight:400'>"
            f"Avg {avg_pct:+.1f}% vs sector</span></div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Metrics table ─────────────────────────────────────────
    st.markdown("#### Valuation Multiples vs Sector Median")
    if metrics:
        import pandas as _pd2
        rows = []
        for m in metrics:
            cv = m.get("company_val")
            sm = m.get("sector_median")
            pd_ = m.get("pct_diff")
            label = m.get("label", "")
            arrow = "▲" if (pd_ or 0) > 0 else "▼"
            color = "#A62020" if (pd_ or 0) > 15 else "#0D7A4E" if (pd_ or 0) < -15 else "#B8972A"
            rows.append({
                "Metric":         m.get("metric_label", m.get("metric", "")),
                "Company":        f"{cv:.1f}x" if cv is not None else "—",
                "Sector Median":  f"{sm:.1f}x" if sm is not None else "—",
                "vs Sector":      f"{arrow} {abs(pd_ or 0):.1f}%" if pd_ is not None else "—",
                "_color":         color,
            })
        tdf = _pd2.DataFrame(rows)
        st.dataframe(
            tdf.drop(columns=["_color"]),
            hide_index=True,
            width='stretch',
        )
    else:
        st.warning("Could not retrieve valuation multiples. Data may be unavailable.")

    # ── Key stats ─────────────────────────────────────────────
    st.divider()
    st.markdown("#### Key Statistics")
    ks1, ks2, ks3, ks4 = st.columns(4)
    def _kstat(col, label, val):
        col.metric(label, val)
    _kstat(ks1, "Market Cap", f"{sym}{mkt_cap/1e9:.1f}B" if mkt_cap else "—")
    _kstat(ks2, "Dividend Yield", f"{div_yield*100:.2f}%" if div_yield else "—")
    _kstat(ks3, "Beta", f"{beta:.2f}" if beta else "—")
    _kstat(ks4, "52W Range", f"{sym}{lo52:,.0f} – {sym}{hi52:,.0f}" if hi52 else "—")

    # ── Why no DCF? ───────────────────────────────────────────
    with st.expander("ℹ️ Why no DCF valuation for this stock?"):
        st.markdown(
            f"""
**{sector_lbl}** companies (banks, REITs, insurance firms) are excluded from
DCF analysis for the following structural reasons:

- **Banks & Insurers** — Capital is a raw material, not just funding.
  Free cash flow is not meaningful because debt issuance is core to operations.
  Regulatory capital requirements (Basel III / Solvency II) make FCF projections
  unreliable. Appropriate models: **P/B**, **P/E**, **ROE vs Cost of Equity**.

- **REITs** — Earnings are distorted by non-cash depreciation on real assets
  that typically *appreciate* in value. The relevant metric is **FFO
  (Funds from Operations)**, not FCF. Appropriate models: **P/FFO**, **Cap Rate**,
  **Dividend Discount Model (DDM)**.

YieldIQ instead benchmarks these companies against **sector median multiples**
to identify relative cheapness or richness.
"""
        )

