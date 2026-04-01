"""dashboard/ui/helpers.py
Pure helper functions and constants used across all tabs.
No Streamlit state — safe to import anywhere.
"""
from __future__ import annotations
import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go

from data.collector import StockDataCollector
from models.forecaster import compute_wacc

CURRENCIES = {
    "INR": {"symbol": "₹", "code": "INR"},
    "USD": {"symbol": "$", "code": "USD"},
    "GBP": {"symbol": "£", "code": "GBP"},
    "EUR": {"symbol": "€", "code": "EUR"},
}

@st.cache_data(ttl=3600)
def get_fx_rate(from_ccy, to_ccy):
    if from_ccy == to_ccy: return 1.0
    try:
        r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{from_ccy}", timeout=5)
        return float(r.json()["rates"].get(to_ccy, 1.0))
    except Exception:
        try:
            r = requests.get(f"https://api.frankfurter.app/latest?from={from_ccy}&to={to_ccy}", timeout=5)
            return float(r.json()["rates"].get(to_ccy, 1.0))
        except Exception:
            return 1.0

@st.cache_data(ttl=60)
def fetch_stock_data(ticker):
    collector  = StockDataCollector(ticker)
    raw        = collector.get_all()
    price_hist = pd.DataFrame()
    wacc_data  = {}
    if collector._ticker_obj:
        price_hist = collector.get_price_history(period="1y")
        is_indian  = ticker.endswith(".NS") or ticker.endswith(".BO")
        wacc_data  = compute_wacc(collector._ticker_obj, is_indian)
    return raw, price_hist, wacc_data

def fmt(v, sym, d=2):
    a = abs(v)
    if a >= 1e12: return f"{sym}{v/1e12:,.2f}T"
    if a >= 1e9:  return f"{sym}{v/1e9:,.2f}B"
    if a >= 1e6:  return f"{sym}{v/1e6:,.2f}M"
    return f"{sym}{v:,.{d}f}"

def fmts(v, sym): return f"{sym}{v:,.2f}"

# ── HUMAN LANGUAGE TRANSLATION HELPERS ─────────────────────────
_SIG_HUMAN = {
    "Undervalued 🟢":    ("📊 Trading below model estimate",  "#0D7A4E", "#F0FDF4", "#BBF7D0"),
    "Near Fair Value 🟡":("📉 Slight discount to model value", "#B45309", "#FFFBEB", "#FDE68A"),
    "Fairly Valued 🔵":  ("⚖️ Near model fair value",          "#1D4ED8", "#EFF6FF", "#BFDBFE"),
    "Overvalued 🔴":     ("📈 Trading above model estimate",   "#B91C1C", "#FEF2F2", "#FECACA"),
    "⚠️ Data Limited":   ("🔍 Model data needs review",        "#B45309", "#FFFBEB", "#FDE68A"),
    "N/A ⬜":            ("⏳ Analysing…",                    "#4A5E7A", "#FFFFFF", "#F8FAFC"),
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

def KL(**kw):
    """Koyfin-style dark chart layout — apply to every fig.update_layout()."""
    base = dict(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        font=dict(family="Inter, DM Sans, system-ui, sans-serif", color="#e6edf3", size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#21262d",
            font=dict(color="#e6edf3", family="IBM Plex Mono, monospace", size=12),
            bordercolor="#30363d",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#8b949e", size=11),
        ),
        xaxis=dict(
            gridcolor="#21262d",
            linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10),
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#21262d",
            linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10),
            zeroline=False,
        ),
    )
    base.update(kw)
    return base

def apply_koyfin(fig, accent="#00b4d8", height=280, title_txt="", extra_kw=None):
    """One-call upgrade: dark layout + teal accent top border + axis polish."""
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(text=title_txt, font=dict(color="#e6edf3", size=13, family="Inter, sans-serif"), x=0, pad=dict(l=4))
    if extra_kw:
        kw.update(extra_kw)
    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor="#21262d", linecolor="#30363d", tickfont=dict(color="#8b949e", size=10))
    fig.update_yaxes(gridcolor="#21262d", linecolor="#30363d", tickfont=dict(color="#8b949e", size=10))
    # Teal top-border accent via annotation line
    fig.add_shape(type="line", xref="paper", yref="paper",
                  x0=0, x1=1, y0=1, y1=1,
                  line=dict(color=accent, width=2),
                  layer="above")
    return fig

def apply_yieldiq_theme(fig, height=280, title_txt="", extra_kw=None):
    """YieldIQ light-mode chart theme: transparent bg, dashed grids, dark hover labels."""
    kw = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#1F2937", size=11),
        margin=dict(l=40, r=20, t=50, b=40),
        height=height,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#1A2540",
            font=dict(color="#FFFFFF", family="IBM Plex Mono, monospace", size=12),
            bordercolor="#1A2540",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(color="#6B7280", size=11),
        ),
        xaxis=dict(
            gridcolor="#E5E7EB",
            griddash="dash",
            gridwidth=0.5,
            linecolor="#E2E8F0",
            tickfont=dict(color="#6B7280", size=10),
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#E5E7EB",
            griddash="dash",
            gridwidth=0.5,
            linecolor="#E2E8F0",
            tickfont=dict(color="#6B7280", size=10),
            zeroline=False,
        ),
    )
    if title_txt:
        kw["title"] = dict(
            text=f"<b>{title_txt}</b>",
            font=dict(size=14, color="#111827", family="Inter, sans-serif"),
            x=0,
            pad=dict(l=4),
        )
    if extra_kw:
        kw.update(extra_kw)
    fig.update_layout(**kw)
    # Force light-mode grids on every axis (wins over any dark values in extra_kw)
    fig.update_xaxes(
        gridcolor="#E5E7EB", griddash="dash", gridwidth=0.5,
        linecolor="#E2E8F0", tickfont=dict(color="#6B7280", size=10),
    )
    fig.update_yaxes(
        gridcolor="#E5E7EB", griddash="dash", gridwidth=0.5,
        linecolor="#E2E8F0", tickfont=dict(color="#6B7280", size=10),
    )
    return fig


def CL(**kw):
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF",
        font=dict(family="Inter,sans-serif", color="#475569", size=11),
        margin=dict(t=20, b=40, l=10, r=10),
        xaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", zeroline=False, tickcolor="#CBD5E1", tickfont=dict(color="#64748B")),
        yaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", zeroline=False, tickcolor="#CBD5E1", tickfont=dict(color="#64748B")),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#1D4ED8",
                        font=dict(color="#0F172A", family="IBM Plex Mono", size=12)),
    )
    base.update(kw)
    return base

def ccard(title, accent="#1D4ED8"):
    st.html(
        f'''<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
            padding:20px 24px 6px;margin-bottom:16px;position:relative;overflow:hidden;
            box-shadow:0 1px 4px rgba(15,23,42,0.06),0 1px 2px rgba(15,23,42,0.04);">
        <div style="position:absolute;top:0;left:0;right:0;height:3px;
            background:linear-gradient(90deg,{accent} 0%,rgba(6,182,212,0.6) 60%,transparent 100%);"></div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;
            letter-spacing:0.12em;text-transform:uppercase;color:#94A3B8;
            margin-bottom:14px;display:flex;align-items:center;gap:8px;">
          <span style="display:inline-block;width:5px;height:5px;border-radius:50%;
              background:{accent};flex-shrink:0;opacity:0.8;"></span>{title}</div>''',
    )

def ccard_end(): st.html("</div>")


# ── FINANCIAL TERM TOOLTIPS ──────────────────────────────────────────────────

FINANCIAL_TOOLTIPS: dict[str, str] = {
    "WACC":             "Weighted Average Cost of Capital — the discount rate used in DCF",
    "Margin of Safety": "How much below intrinsic value the stock is trading",
    "FCF":              "Free Cash Flow — cash the company generates after expenses",
    "Terminal Value":   "Value of all cash flows beyond the forecast period",
    "Piotroski Score":  "9-point quality score based on financial health signals",
    "Economic Moat":    "Sustainable competitive advantage that protects market share",
}


def inject_tooltip_css() -> None:
    """Inject CSS for ⓘ hover tooltips and skeleton shimmer. Call once at page load."""
    st.markdown("""
<style>
/* ── TOOLTIPS ── */
.yiq-tt-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: default;
}
.yiq-tt-icon {
  font-size: 10px;
  color: #94A3B8;
  line-height: 1;
  flex-shrink: 0;
  font-style: normal;
  transition: color 0.15s;
}
.yiq-tt-wrap:hover .yiq-tt-icon { color: #60A5FA; }
.yiq-tt-box {
  visibility: hidden;
  opacity: 0;
  position: absolute;
  bottom: calc(100% + 7px);
  left: 50%;
  transform: translateX(-50%);
  background: #1E293B;
  color: #E2E8F0;
  font-size: 11px;
  font-family: 'Inter', sans-serif;
  font-weight: 400;
  line-height: 1.55;
  padding: 7px 11px;
  border-radius: 7px;
  white-space: normal;
  width: max-content;
  max-width: 240px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.28);
  border: 1px solid rgba(255,255,255,0.08);
  z-index: 9999;
  transition: opacity 0.15s;
  pointer-events: none;
  text-align: left;
}
.yiq-tt-box::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1E293B;
}
.yiq-tt-wrap:hover .yiq-tt-box {
  visibility: visible;
  opacity: 1;
}

/* ── SKELETON SHIMMER ── */
@keyframes yiq-shimmer {
  0%   { background-position: -600px 0; }
  100% { background-position:  600px 0; }
}
.yiq-skeleton {
  background: linear-gradient(
    90deg,
    #E8EDF4 0%, #F1F5F9 30%, #E8EDF4 60%
  );
  background-size: 1200px 100%;
  animation: yiq-shimmer 1.5s linear infinite;
  border-radius: 10px;
  width: 100%;
}

/* ── PROGRESS CARD ── */
@keyframes yiq-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
.yiq-step-active .yiq-spin-icon {
  display: inline-block;
  animation: yiq-spin 1s linear infinite;
}

/* ── EMPTY STATE ── */
@keyframes yiq-fade-up-es {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
.yiq-empty-state {
  text-align: center;
  padding: 48px 24px 40px;
  max-width: 640px;
  margin: 16px auto 0;
  animation: yiq-fade-up-es 0.45s ease both;
}

/* ── SUCCESS FLASH ── */
@keyframes yiq-flash-green {
  0%   { box-shadow: none; }
  25%  { box-shadow: 0 0 40px rgba(5,150,105,0.22); }
  100% { box-shadow: none; }
}
@keyframes yiq-flash-red {
  0%   { box-shadow: none; }
  25%  { box-shadow: 0 0 40px rgba(220,38,38,0.18); }
  100% { box-shadow: none; }
}
.yiq-flash-green { animation: yiq-flash-green 1.8s ease-out; }
.yiq-flash-red   { animation: yiq-flash-red   1.8s ease-out; }
</style>
""", unsafe_allow_html=True)


def add_tooltip(label: str, tip: str) -> str:
    """Return HTML: label + ⓘ icon that shows a dark tooltip on hover.
    Use inside st.html() blocks or f-strings passed to st.markdown(unsafe_allow_html=True).
    """
    safe = tip.replace('"', '&quot;').replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<span class="yiq-tt-wrap">'
        f'{label}'
        f'<span class="yiq-tt-icon"> ⓘ</span>'
        f'<span class="yiq-tt-box">{safe}</span>'
        f'</span>'
    )


def render_skeleton_card(height: int = 200, label: str = "") -> None:
    """Shimmer placeholder shown while a chart or data section is loading."""
    _lbl = (
        f'<div style="font-size:11px;color:#94A3B8;font-family:\'IBM Plex Mono\',monospace;'
        f'letter-spacing:0.07em;text-transform:uppercase;margin-bottom:6px;">{label}</div>'
    ) if label else ""
    st.html(f'{_lbl}<div class="yiq-skeleton" style="height:{height}px;"></div>')


def render_empty_state(sym: str = "$") -> None:
    """Centered landing card shown when no analysis has been run yet.

    The ticker chip buttons below (rendered by the caller via st.button) handle
    the actual Streamlit rerun; this function renders only the visual HTML shell.
    """
    st.html("""
<div class="yiq-empty-state">
  <div style="font-size:58px;line-height:1;margin-bottom:18px;">📈</div>
  <div style="font-size:27px;font-weight:800;color:#0F172A;
              letter-spacing:-0.03em;margin-bottom:10px;">
    Analyze Any Stock
  </div>
  <div style="font-size:14px;color:#64748B;line-height:1.75;
              max-width:460px;margin:0 auto 26px;">
    Enter a ticker symbol above to get institutional-grade
    DCF valuation, AI growth forecasting, and investment signals.
  </div>
  <div style="display:flex;justify-content:center;flex-wrap:wrap;gap:8px;margin-bottom:28px;">
    <span style="font-size:12px;font-weight:600;color:#1D4ED8;
                 background:#EFF6FF;border:1px solid #BFDBFE;
                 border-radius:100px;padding:5px 16px;">📐 DCF Valuation</span>
    <span style="font-size:12px;font-weight:600;color:#059669;
                 background:#ECFDF5;border:1px solid #BBF7D0;
                 border-radius:100px;padding:5px 16px;">🤖 AI Forecasting</span>
    <span style="font-size:12px;font-weight:600;color:#7C3AED;
                 background:#F5F3FF;border:1px solid #DDD6FE;
                 border-radius:100px;padding:5px 16px;">🎲 Scenario Analysis</span>
  </div>
  <div style="font-size:12px;color:#94A3B8;margin-bottom:10px;
              font-family:'IBM Plex Mono',monospace;letter-spacing:0.04em;">
    Popular — click to analyze:
  </div>
</div>
""")

