# dashboard/morning_brief.py
# ════════════════════════════════════════════════════════════════
# YieldIQ — Morning Brief  (Landing Page)
#
# Shown instead of the static hero when no analysis is in progress.
# Sections:
#   1. Header — date + title + gradient divider
#   2. Market Snapshot — S&P 500, Dow, NASDAQ, 10Y Yield, Gold (live)
#   3. Market Mood Indicator — VIX-derived Fear / Greed gauge
#   4. Top Opportunities — last analyses ranked by MoS%
#   5. Watchlist Quick-View — live prices + signal delta
#   6. Recent Analysis History — compact session table
#   7. Quick Analyze CTA
#
# Public API (called from app.py):
#   push_analysis_to_history(ticker, name, price, iv, mos_pct, signal)
#   render_morning_brief(watchlist_rows, sym, has_prior_results)
#       → sets session-state flags:
#           _prefill_ticker + _auto_analyse    — Quick Analyze submit
#           _show_morning_brief = False        — "Back to Analysis" click
# ════════════════════════════════════════════════════════════════

from __future__ import annotations
from datetime import datetime
import sys, os

import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import yfinance as yf
    _YF_OK = True
except ImportError:
    _YF_OK = False

# ── History key ──────────────────────────────────────────────
_HIST_KEY = "_analysis_history"   # list[dict] in session_state (max 20)


# ════════════════════════════════════════════════════════════════
# DATA FETCHING (cached)
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _market_snapshot() -> dict[str, dict]:
    """
    Fetch live data for 5 display indices + VIX for mood.  TTL=5 min.
    Returns {name: {price, change_pct, symbol}}
    """
    if not _YF_OK:
        return {}
    indices = {
        "S&P 500":   "^GSPC",
        "Dow Jones": "^DJI",
        "NASDAQ":    "^IXIC",
        "10Y Yield": "^TNX",
        "Gold":      "GC=F",
        "VIX":       "^VIX",   # fetched for mood gauge, not in display row
    }
    result: dict[str, dict] = {}
    for name, sym in indices.items():
        try:
            fi    = yf.Ticker(sym).fast_info
            price = float(fi.last_price or 0)
            prev  = float(fi.previous_close or price)
            chg   = ((price - prev) / prev * 100) if prev else 0.0
            result[name] = {"price": price, "change_pct": chg, "symbol": sym}
        except Exception:
            result[name] = {"price": 0.0, "change_pct": 0.0, "symbol": sym}
    return result


@st.cache_data(ttl=180, show_spinner=False)
def _live_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """Batch-fetch current prices for watchlist tickers.  TTL=3 min."""
    if not _YF_OK or not tickers:
        return {}
    out: dict[str, float] = {}
    for sym in tickers:
        try:
            out[sym] = float(yf.Ticker(sym).fast_info.last_price or 0)
        except Exception:
            out[sym] = 0.0
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _ticker_bar_prices(tickers_tuple: tuple[str, ...]) -> dict[str, dict]:
    """
    Fetch price + % change for each ticker in the scrolling bar. TTL=5 min.
    Returns {ticker: {price, change_pct}} — zeros on failure.
    """
    if not _YF_OK:
        return {}
    result: dict[str, dict] = {}
    for t in tickers_tuple:
        try:
            fi    = yf.Ticker(t).fast_info
            price = float(fi.last_price or 0)
            prev  = float(fi.previous_close or price)
            chg   = ((price - prev) / prev * 100) if prev else 0.0
            result[t] = {"price": price, "change_pct": chg}
        except Exception:
            result[t] = {"price": 0.0, "change_pct": 0.0}
    return result


# ════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════

def push_analysis_to_history(
    ticker:  str,
    name:    str,
    price:   float,
    iv:      float,
    mos_pct: float,
    signal:  str,
) -> None:
    """
    Call after every successful analysis to build the Top Opportunities list.
    Keeps the last 20 unique tickers (most-recent per ticker wins).
    """
    hist: list[dict] = st.session_state.get(_HIST_KEY, [])
    # Remove stale entry for same ticker so it gets an updated position
    hist = [h for h in hist if h.get("ticker") != ticker]
    hist.insert(0, {
        "ticker":  ticker,
        "name":    name,
        "price":   price,
        "iv":      iv,
        "mos_pct": mos_pct,
        "signal":  signal,
        "ts":      datetime.utcnow().strftime("%H:%M UTC"),
    })
    st.session_state[_HIST_KEY] = hist[:20]


# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

def _tv() -> dict:
    """
    Return current theme color vars set by render_morning_brief().
    Sub-renderers call this inside st.html() f-strings to get card
    background/text colors that match the active dark/light theme.
    CSS custom properties cannot reach sandboxed st.html() iframes,
    so explicit hex values must be injected via Python.
    """
    return st.session_state.get("_mb_theme_vars", {
        "card_bg":     "#FFFFFF",
        "card_bg2":    "#F8FAFC",
        "card_border": "#E2E8F0",
        "text_main":   "#0F172A",
        "text_sec":    "#64748B",
        "text_muted":  "#94A3B8",
    })


def _sig_badge(sig: str) -> tuple[str, str, str]:
    """Returns (text_color, bg_color, border_color) for a signal string."""
    return {
        "STRONG BUY":  ("#166534", "#DCFCE7", "#BBF7D0"),
        "BUY":         ("#166534", "#DCFCE7", "#BBF7D0"),
        "WATCH":       ("#854D0E", "#FEF9C3", "#FDE68A"),
        "HOLD":        ("#92400E", "#FEF3C7", "#FCD34D"),
        "SELL":        ("#991B1B", "#FEE2E2", "#FECACA"),
        "STRONG SELL": ("#7F1D1D", "#FEE2E2", "#FECACA"),
    }.get(sig.upper(), ("#475569", "#F1F5F9", "#E2E8F0"))


def _vix_sentiment(vix: float) -> tuple[str, str, float, str]:
    """Returns (label, hex_color, gauge_pct 0–100, description)."""
    # gauge_pct: 0 = full Greed (left), 100 = Extreme Fear (right)
    pct = min(100.0, max(0.0, vix / 40 * 100))
    if vix >= 35:
        return ("Extreme Fear", "#B91C1C", pct,
                f"VIX {vix:.1f} — extreme volatility, markets pricing in panic")
    if vix >= 25:
        return ("Fear",         "#DC2626", pct,
                f"VIX {vix:.1f} — elevated risk-off sentiment")
    if vix >= 18:
        return ("Cautious",     "#D97706", pct,
                f"VIX {vix:.1f} — uncertainty in the market, tread carefully")
    if vix >= 12:
        return ("Neutral",      "#64748B", pct,
                f"VIX {vix:.1f} — moderate volatility, balanced risk appetite")
    return ("Greed",            "#059669", pct,
            f"VIX {vix:.1f} — low volatility, risk-on, investors complacent")


def _fmt_price(p: float, name: str = "") -> str:
    """Format a price value for display."""
    if name == "10Y Yield":
        return f"{p:.2f}%"
    if name == "Gold":
        return f"${p:,.0f}"
    if p >= 10_000:
        return f"{p:,.0f}"
    if p >= 100:
        return f"{p:,.1f}"
    return f"{p:.2f}"


def _render_ticker_bar() -> None:
    """
    Scrolling live news ticker bar — like a financial TV channel chyron.
    Self-contained HTML/CSS/JS; uses st.html() (sandboxed, no Streamlit elements).
    Pauses on hover. Prices cached 5 minutes via _ticker_bar_prices().
    """
    tickers_tuple = tuple(sym for sym, _, _ in _TICKER_BAR_STOCKS)
    prices        = _ticker_bar_prices(tickers_tuple)

    # ── Build one copy of the ticker items ──────────────────────
    items_html = ""
    for sym, _name, logo in _TICKER_BAR_STOCKS:
        data  = prices.get(sym, {"price": 0.0, "change_pct": 0.0})
        price = data["price"]
        chg   = data["change_pct"]

        # Price string
        if price > 0:
            price_str = f"${price:,.2f}" if price < 1_000 else f"${price:,.0f}"
        else:
            price_str = "--"

        # Change string + CSS class
        if price > 0:
            chg_class = "up" if chg >= 0 else "dn"
            chg_arrow = "▲" if chg >= 0 else "▼"
            chg_str   = f"{chg_arrow} {abs(chg):.2f}%"
        else:
            chg_class = "up"
            chg_str   = ""

        items_html += f"""
        <div class="yiq-tick-item">
            <div class="yiq-tick-logo">{logo}</div>
            <span class="yiq-tick-symbol">{sym}</span>
            <span class="yiq-tick-price">{price_str}</span>
            <span class="yiq-tick-change {chg_class}">{chg_str}</span>
        </div>"""

    # Duplicate items_html for seamless infinite loop
    st.html(f"""
<style>
.yiq-ticker-wrap {{
    overflow: hidden;
    background: #0F172A;
    padding: 10px 0;
    border-radius: 8px;
    margin-bottom: 16px;
    position: relative;
}}
/* Fade edges */
.yiq-ticker-wrap::before,
.yiq-ticker-wrap::after {{
    content: "";
    position: absolute;
    top: 0; bottom: 0;
    width: 40px;
    z-index: 2;
    pointer-events: none;
}}
.yiq-ticker-wrap::before {{
    left: 0;
    background: linear-gradient(to right, #0F172A, transparent);
}}
.yiq-ticker-wrap::after {{
    right: 0;
    background: linear-gradient(to left, #0F172A, transparent);
}}
.yiq-ticker-track {{
    display: flex;
    gap: 0;
    animation: tickerScroll 40s linear infinite;
    width: max-content;
}}
.yiq-ticker-track:hover {{
    animation-play-state: paused;
}}
@keyframes tickerScroll {{
    0%   {{ transform: translateX(0); }}
    100% {{ transform: translateX(-50%); }}
}}
.yiq-tick-item {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 0 24px;
    border-right: 1px solid rgba(255,255,255,0.08);
    white-space: nowrap;
    cursor: pointer;
    transition: background 0.15s;
}}
.yiq-tick-item:hover {{
    background: rgba(255,255,255,0.05);
}}
.yiq-tick-logo {{
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: rgba(255,255,255,0.1);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    flex-shrink: 0;
}}
.yiq-tick-symbol {{
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 12px;
    color: #FFFFFF;
}}
.yiq-tick-price {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: rgba(255,255,255,0.65);
}}
.yiq-tick-change.up {{
    color: #34D399;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
}}
.yiq-tick-change.dn {{
    color: #F87171;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
}}
</style>
<div class="yiq-ticker-wrap">
    <div class="yiq-ticker-track">
        {items_html}
        {items_html}
    </div>
</div>
""")


# ── Ticker-bar stock universe ────────────────────────────────
_TICKER_BAR_STOCKS: list[tuple[str, str, str]] = [
    ("AAPL",  "Apple",             "🍎"),
    ("MSFT",  "Microsoft",         "🪟"),
    ("GOOGL", "Alphabet",          "🔍"),
    ("NVDA",  "NVIDIA",            "⚡"),
    ("TSLA",  "Tesla",             "🚗"),
    ("AMZN",  "Amazon",            "📦"),
    ("META",  "Meta",              "👤"),
    ("JPM",   "JPMorgan",          "🏦"),
    ("V",     "Visa",              "💳"),
    ("WMT",   "Walmart",           "🛒"),
    ("JNJ",   "Johnson & Johnson", "💊"),
    ("BRK-B", "Berkshire",         "💼"),
]


# ════════════════════════════════════════════════════════════════
# SECTION RENDERERS
# ════════════════════════════════════════════════════════════════

def _render_header() -> None:
    """Premium newsletter-style header with date, title, subtitle and divider."""
    _now  = datetime.now()
    # Platform-safe date string: "Friday, March 28, 2026"
    _date = _now.strftime(f"%A, %B {_now.day}, %Y")

    _t = _tv()
    col_hdr, col_refresh = st.columns([5, 1])
    with col_hdr:
        st.html(f"""
<div style="padding:10px 0 6px;">
  <div style="font-size:13px;font-weight:400;color:{_t['text_muted']};
              letter-spacing:0.06em;margin-bottom:8px;">{_date}</div>
  <div style="font-size:36px;font-weight:800;color:{_t['text_main']};
              line-height:1.05;letter-spacing:-0.02em;margin-bottom:7px;">
    Morning Brief
  </div>
  <div style="font-size:14px;color:{_t['text_sec']};">
    Your daily market intelligence summary
  </div>
</div>
""")
    with col_refresh:
        st.html('<div style="height:40px;"></div>')
        if st.button("↺ Refresh", key="mb_refresh", help="Reload live market data"):
            st.cache_data.clear()
            st.rerun()

    # Gradient divider
    st.html("""
<div style="height:2px;
            background:linear-gradient(90deg,#1D4ED8 0%,#06B6D4 35%,#8B5CF6 65%,transparent 100%);
            border-radius:2px;margin:14px 0 22px;"></div>
""")


def _render_market_snapshot(market: dict) -> float:
    """
    5 compact index cards side by side.
    Displays S&P 500, Dow Jones, NASDAQ, 10Y Yield, Gold.
    Returns the current VIX value for the mood gauge.
    """
    vix_val = market.get("VIX", {}).get("price", 0.0)

    _DISPLAY = [
        ("S&P 500",   "Large-cap US equities"),
        ("Dow Jones", "30 blue-chip companies"),
        ("NASDAQ",    "Tech-heavy US index"),
        ("10Y Yield", "US Treasury benchmark"),
        ("Gold",      "Safe-haven commodity"),
    ]

    _t    = _tv()
    cols  = st.columns(5, gap="small")
    for col, (name, _subtitle) in zip(cols, _DISPLAY):
        d     = market.get(name, {})
        price = d.get("price", 0.0)
        chg   = d.get("change_pct", 0.0)

        price_str = _fmt_price(price, name)

        if name == "10Y Yield":
            # Rising yield = negative for growth stocks
            arrow   = "▲" if chg >= 0 else "▼"
            chg_clr = "#EF4444" if chg >= 0 else "#10B981"
            chg_str = f"{arrow} {abs(chg):.2f}pp"
        else:
            arrow   = "▲" if chg >= 0 else "▼"
            chg_clr = "#10B981" if chg >= 0 else "#EF4444"
            chg_str = f"{arrow} {abs(chg):.2f}%"

        # Top accent colour matches change direction
        accent = "#10B981" if (chg >= 0 and name != "10Y Yield") else "#EF4444"

        col.html(f"""
<div style="background:{_t['card_bg']};
            border:1px solid {_t['card_border']};
            border-top:3px solid {accent};
            border-radius:10px;padding:14px 12px;text-align:center;
            box-shadow:0 1px 4px rgba(15,23,42,0.05);">
  <div style="font-size:10px;font-weight:600;color:{_t['text_muted']};
              text-transform:uppercase;letter-spacing:0.1em;
              margin-bottom:9px;">{name}</div>
  <div style="font-size:18px;font-weight:700;color:{_t['text_main']};
              font-family:'IBM Plex Mono',monospace;
              line-height:1.15;margin-bottom:6px;">{price_str}</div>
  <div style="font-size:11px;font-weight:600;color:{chg_clr};">{chg_str}</div>
</div>
""")

    return vix_val


def _render_mood_indicator(vix_val: float) -> None:
    """Horizontal Fear ← → Greed gauge derived from VIX."""
    label, clr, gauge_pct, desc = _vix_sentiment(vix_val)
    # Clamp marker to 3–97% to avoid edge clipping
    marker_pct = max(3.0, min(97.0, gauge_pct))

    _t = _tv()
    st.html(f"""
<div style="background:{_t['card_bg']};border:1px solid {_t['card_border']};
            border-radius:12px;padding:18px 24px;margin:14px 0;
            box-shadow:0 1px 4px rgba(15,23,42,0.05);">
  <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap;">

    <!-- Sentiment label -->
    <div style="flex-shrink:0;min-width:120px;">
      <div style="font-size:10px;font-weight:600;color:{_t['text_muted']};
                  text-transform:uppercase;letter-spacing:0.1em;margin-bottom:5px;">
        Market Mood
      </div>
      <div style="font-size:20px;font-weight:800;color:{clr};">{label}</div>
    </div>

    <!-- Gauge bar -->
    <div style="flex:1;min-width:200px;">
      <div style="display:flex;justify-content:space-between;
                  font-size:10px;font-weight:600;margin-bottom:7px;">
        <span style="color:#059669;">◀ Greed</span>
        <span style="color:#64748B;">Neutral</span>
        <span style="color:#DC2626;">Fear ▶</span>
      </div>
      <div style="height:9px;
                  background:linear-gradient(90deg,
                    #059669 0%,#84CC16 20%,#EAB308 45%,#EF4444 75%,#991B1B 100%);
                  border-radius:5px;position:relative;">
        <div style="position:absolute;top:50%;left:{marker_pct:.1f}%;
                    width:18px;height:18px;background:#FFFFFF;border-radius:50%;
                    transform:translate(-50%,-50%);
                    border:3px solid {clr};
                    box-shadow:0 0 0 3px {clr}28,0 2px 6px rgba(0,0,0,0.12);">
        </div>
      </div>
      <div style="font-size:11px;color:#64748B;margin-top:9px;">{desc}</div>
    </div>

    <!-- VIX number -->
    <div style="flex-shrink:0;text-align:center;min-width:72px;">
      <div style="font-size:10px;font-weight:600;color:#94A3B8;
                  text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">VIX</div>
      <div style="font-size:26px;font-weight:800;color:{clr};
                  font-family:'IBM Plex Mono',monospace;line-height:1;">{vix_val:.1f}</div>
    </div>

  </div>
</div>
""")


def _render_top_opportunities(hist: list[dict], sym: str) -> None:
    """Top 5 analyses ranked by MoS% with Analyze → buttons."""
    st.html("""
<div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:3px;">
  Today's Top Picks
</div>
<div style="font-size:12px;color:#64748B;margin-bottom:14px;">
  Your recent analyses, ranked by margin of safety
</div>
""")

    if not hist:
        st.html("""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
            padding:28px;text-align:center;">
  <div style="font-size:32px;margin-bottom:10px;">🔍</div>
  <div style="font-size:14px;font-weight:600;color:#0F172A;margin-bottom:4px;">
    No analyses yet
  </div>
  <div style="font-size:12px;color:#64748B;">
    Use the Quick Analyse box below to get started
  </div>
</div>
""")
        return

    ranked = sorted(hist[:10], key=lambda x: x.get("mos_pct", 0), reverse=True)[:5]

    for row in ranked:
        ticker  = row.get("ticker", "")
        name    = row.get("name", "")
        sig     = row.get("signal", "WATCH")
        mos     = row.get("mos_pct", 0)
        price   = row.get("price", 0)
        iv      = row.get("iv", 0)
        ts      = row.get("ts", "")

        sig_tc, sig_bg, sig_bd = _sig_badge(sig)
        mos_clr  = "#059669" if mos >= 15 else "#EF4444" if mos < 0 else "#D97706"
        mos_bg   = "#ECFDF5" if mos >= 15 else "#FEF2F2" if mos < 0 else "#FFFBEB"
        mos_sign = "+" if mos >= 0 else ""

        _c_card, _c_btn = st.columns([6, 1], gap="small")
        with _c_card:
            st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
            padding:12px 16px;box-shadow:0 1px 2px rgba(15,23,42,0.04);">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">

    <!-- Ticker + company -->
    <div style="flex:1;min-width:0;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
        <span style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                     font-weight:700;color:#0F172A;">{ticker}</span>
        <span style="font-size:11px;color:#64748B;white-space:nowrap;
                     overflow:hidden;text-overflow:ellipsis;max-width:160px;">{name}</span>
      </div>
      <div style="font-size:10px;color:#94A3B8;">
        Price {sym}{price:,.2f}&nbsp;&nbsp;·&nbsp;&nbsp;IV {sym}{iv:,.2f}&nbsp;&nbsp;·&nbsp;&nbsp;{ts}
      </div>
    </div>

    <!-- Signal badge -->
    <span style="flex-shrink:0;font-size:11px;font-weight:700;
                 color:{sig_tc};background:{sig_bg};border:1px solid {sig_bd};
                 border-radius:20px;padding:4px 12px;
                 font-family:'IBM Plex Mono',monospace;">{sig}</span>

    <!-- MoS chip -->
    <div style="flex-shrink:0;min-width:58px;text-align:center;
                padding:6px 12px;background:{mos_bg};border-radius:8px;">
      <div style="font-size:14px;font-weight:800;color:{mos_clr};
                  font-family:'IBM Plex Mono',monospace;">
        {mos_sign}{mos:.1f}%
      </div>
      <div style="font-size:9px;color:{mos_clr};text-transform:uppercase;
                  letter-spacing:0.07em;margin-top:1px;">MoS</div>
    </div>

  </div>
</div>
""")
        with _c_btn:
            st.html('<div style="height:8px;"></div>')
            if st.button(
                "Analyze →",
                key=f"mb_analyze_{ticker}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["_prefill_ticker"]     = ticker
                st.session_state["_auto_analyse"]       = True
                st.session_state["_show_morning_brief"] = False
                st.rerun()

        st.html('<div style="height:5px;"></div>')


def _render_watchlist_panel(watchlist_rows: list[dict], sym: str = "$") -> None:
    """Live prices + signal for watchlist holdings."""
    st.html("""
<div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:3px;">
  Watchlist
</div>
<div style="font-size:12px;color:#64748B;margin-bottom:12px;">
  Live prices for your saved positions
</div>
""")

    if not watchlist_rows:
        st.html("""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
            padding:28px;text-align:center;">
  <div style="font-size:28px;margin-bottom:8px;">📋</div>
  <div style="font-size:13px;font-weight:600;color:#0F172A;margin-bottom:4px;">
    Watchlist is empty
  </div>
  <div style="font-size:11px;color:#64748B;">
    Add stocks from the Watchlist tab after analysing
  </div>
</div>
""")
        return

    tickers = tuple(r.get("ticker", "") for r in watchlist_rows[:8] if r.get("ticker"))
    live_px = _live_prices(tickers)

    for row in watchlist_rows[:6]:
        sym_t    = row.get("ticker", "")
        saved_iv = row.get("iv", 0) or 0
        saved_px = row.get("entry_price", 0) or 0
        sig      = row.get("signal", "") or ""
        cur_px   = live_px.get(sym_t, 0)

        sig_tc, sig_bg, sig_bd = _sig_badge(sig)

        live_mos  = ((saved_iv - cur_px) / saved_iv * 100) if saved_iv and cur_px else 0
        mos_clr   = "#059669" if live_mos >= 15 else "#EF4444" if live_mos < 0 else "#D97706"
        pl_pct    = ((cur_px - saved_px) / saved_px * 100) if saved_px and cur_px else 0
        pl_clr    = "#059669" if pl_pct >= 0 else "#EF4444"
        pl_sign   = "+" if pl_pct >= 0 else ""
        mos_sign  = "+" if live_mos >= 0 else ""

        st.html(f"""
<div style="display:flex;align-items:center;background:#FFFFFF;
            border:1px solid #E2E8F0;border-radius:9px;
            padding:10px 14px;margin-bottom:6px;
            box-shadow:0 1px 2px rgba(15,23,42,0.04);">
  <div style="flex:1;min-width:0;">
    <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                font-weight:700;color:#0F172A;">{sym_t}</div>
    <div style="font-size:10px;color:#94A3B8;margin-top:2px;">
      Entry {sym}{saved_px:,.2f}
      &nbsp;·&nbsp;
      <span style="color:{mos_clr};">{mos_sign}{live_mos:.1f}% MoS</span>
    </div>
  </div>
  <div style="text-align:right;flex-shrink:0;margin-right:10px;">
    <div style="font-size:13px;font-weight:700;color:#0F172A;">
      {f"{cur_px:,.2f}" if cur_px else "—"}
    </div>
    <div style="font-size:11px;color:{pl_clr};">{pl_sign}{pl_pct:.1f}% P&L</div>
  </div>
  <span style="font-size:10px;font-weight:700;color:{sig_tc};
               background:{sig_bg};border:1px solid {sig_bd};
               border-radius:20px;padding:3px 9px;white-space:nowrap;">
    {sig or "—"}
  </span>
</div>
""")


def _render_recent_analyses(hist: list[dict], sym: str) -> None:
    """Compact striped table of all recent analyses this session."""
    st.html("""
<div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:3px;">
  Your Recent Analyses
</div>
<div style="font-size:12px;color:#64748B;margin-bottom:14px;">
  Full history of stocks you've analysed this session
</div>
""")

    if not hist:
        st.html("""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
            padding:20px;text-align:center;">
  <div style="font-size:12px;color:#64748B;">No analyses yet this session</div>
</div>
""")
        return

    _rows_html = ""
    for i, row in enumerate(hist[:15]):
        sig     = row.get("signal", "")
        sig_tc, sig_bg, sig_bd = _sig_badge(sig)
        mos     = row.get("mos_pct", 0)
        mos_clr = "#059669" if mos >= 10 else "#EF4444" if mos < 0 else "#D97706"
        mos_sgn = "+" if mos >= 0 else ""
        row_bg  = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"

        _rows_html += f"""
<tr style="background:{row_bg};border-bottom:1px solid #F1F5F9;">
  <td style="padding:10px 14px;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                 font-weight:700;color:#0F172A;">{row.get("ticker","")}</span>
  </td>
  <td style="padding:10px 14px;font-size:12px;color:#475569;
             max-width:150px;overflow:hidden;text-overflow:ellipsis;
             white-space:nowrap;">{row.get("name","")}</td>
  <td style="padding:10px 14px;">
    <span style="font-size:10px;font-weight:700;color:{sig_tc};
                 background:{sig_bg};border:1px solid {sig_bd};
                 border-radius:20px;padding:3px 10px;
                 font-family:'IBM Plex Mono',monospace;">{sig}</span>
  </td>
  <td style="padding:10px 14px;text-align:right;">
    <span style="font-size:13px;font-weight:700;color:{mos_clr};
                 font-family:'IBM Plex Mono',monospace;">
      {mos_sgn}{mos:.1f}%
    </span>
  </td>
  <td style="padding:10px 14px;text-align:right;
             font-size:12px;color:#374151;
             font-family:'IBM Plex Mono',monospace;">
    {sym}{row.get("iv",0):,.2f}
  </td>
  <td style="padding:10px 14px;text-align:right;
             font-size:11px;color:#94A3B8;">{row.get("ts","")}</td>
</tr>"""

    st.html(f"""
<div style="border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;
            box-shadow:0 1px 4px rgba(15,23,42,0.05);">
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0;">
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:left;text-transform:uppercase;letter-spacing:0.1em;">Ticker</th>
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:left;text-transform:uppercase;letter-spacing:0.1em;">Company</th>
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:left;text-transform:uppercase;letter-spacing:0.1em;">Signal</th>
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:right;text-transform:uppercase;letter-spacing:0.1em;">MoS %</th>
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:right;text-transform:uppercase;letter-spacing:0.1em;">IV</th>
        <th style="padding:9px 14px;font-size:10px;font-weight:700;color:#94A3B8;
                   text-align:right;text-transform:uppercase;letter-spacing:0.1em;">Time</th>
      </tr>
    </thead>
    <tbody>{_rows_html}</tbody>
  </table>
</div>
""")


def _render_quick_analyze() -> None:
    """Centered Quick Analyze CTA with example ticker chips."""
    st.html("""
<div style="text-align:center;padding:8px 0 6px;">
  <div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:5px;">
    🔍 Quick Analyse a Stock
  </div>
  <div style="font-size:13px;color:#64748B;">
    Enter any US or Indian ticker — full DCF analysis in ~10 seconds
  </div>
</div>
""")

    qa_c1, qa_c2, qa_c3 = st.columns([1, 3, 1])
    with qa_c2:
        with st.form("mb_quick_analyse_form", clear_on_submit=False):
            qa_col1, qa_col2 = st.columns([3, 1])
            with qa_col1:
                qa_ticker = st.text_input(
                    "Quick ticker",
                    placeholder="e.g. AAPL · TCS.NS · NVDA",
                    label_visibility="collapsed",
                    key="mb_qa_ticker",
                ).upper().strip()
            with qa_col2:
                submitted = st.form_submit_button(
                    "Analyse →", width='stretch', type="primary"
                )
            if submitted and qa_ticker:
                st.session_state["_prefill_ticker"]     = qa_ticker
                st.session_state["_auto_analyse"]       = True
                st.session_state["_show_morning_brief"] = False
                st.rerun()
            elif submitted:
                st.error("Please enter a ticker symbol.")

        # Live scrolling ticker bar replaces static chips
        _render_ticker_bar()


# ════════════════════════════════════════════════════════════════
# MAIN RENDERER
# ════════════════════════════════════════════════════════════════

def render_morning_brief(
    watchlist_rows: list[dict],
    sym: str = "$",
    has_prior_results: bool = False,
    theme: str = "light",
) -> None:
    """
    Render the full Morning Brief dashboard.

    Parameters
    ----------
    watchlist_rows    : list of dicts from get_watchlist()
    sym               : currency symbol (e.g. "$", "₹")
    has_prior_results : True when the user has previous analysis results cached —
                        shows a "← Back to Analysis" button
    theme             : "light" or "dark" — controls card background colors
                        in st.html() blocks (CSS vars don't reach sandboxed HTML)
    """
    # ── Theme-aware card colors for st.html() blocks ─────────
    # CSS custom properties cannot reach sandboxed st.html() iframes,
    # so we compute explicit colors here and pass them as f-string vars.
    _card_bg    = "#1E293B" if theme == "dark" else "#FFFFFF"
    _card_bg2   = "#273449" if theme == "dark" else "#F8FAFC"
    _card_border= "#334155" if theme == "dark" else "#E2E8F0"
    _text_main  = "#F1F5F9" if theme == "dark" else "#0F172A"
    _text_sec   = "#94A3B8" if theme == "dark" else "#64748B"
    _text_muted = "#64748B" if theme == "dark" else "#94A3B8"
    # Store on session_state so sub-renderers can access without refactoring
    st.session_state["_mb_theme_vars"] = {
        "card_bg":     _card_bg,
        "card_bg2":    _card_bg2,
        "card_border": _card_border,
        "text_main":   _text_main,
        "text_sec":    _text_sec,
        "text_muted":  _text_muted,
    }

    # ── Optional "Back to Analysis" button ───────────────────
    if has_prior_results:
        _back_col, _ = st.columns([1, 4])
        with _back_col:
            if st.button("← Back to Analysis", key="mb_back_to_analysis",
                         help="Resume your last stock analysis"):
                st.session_state["_show_morning_brief"] = False
                st.rerun()

    # ── Fetch market data ─────────────────────────────────────
    with st.spinner("Loading market data…"):
        market = _market_snapshot()

    # ── 1. Header ─────────────────────────────────────────────
    _render_header()

    # ── 1b. Live scrolling ticker bar ─────────────────────────
    _render_ticker_bar()

    # ── 2. Market Snapshot row ────────────────────────────────
    vix_val = _render_market_snapshot(market)

    # ── 3. Market Mood Indicator ──────────────────────────────
    _render_mood_indicator(vix_val)

    st.html('<div style="height:8px;"></div>')

    # ── 4. Top Opportunities + Watchlist ─────────────────────
    hist = st.session_state.get(_HIST_KEY, [])
    col_opp, col_wl = st.columns([6, 4], gap="medium")

    with col_opp:
        _render_top_opportunities(hist, sym)

    with col_wl:
        _render_watchlist_panel(watchlist_rows, sym)

    st.html('<div style="height:20px;"></div>')

    # ── 5. Recent Analyses table ──────────────────────────────
    _render_recent_analyses(hist, sym)

    # Thin divider before CTA
    st.html("""
<div style="height:1.5px;
            background:linear-gradient(90deg,transparent,#E2E8F0,transparent);
            margin:22px 0 18px;"></div>
""")

    # ── 6. Quick Analyse CTA ──────────────────────────────────
    _render_quick_analyze()

    # ── Footer ────────────────────────────────────────────────
    st.html("""
<div style="text-align:center;margin-top:18px;
            font-size:11px;color:#94A3B8;letter-spacing:0.04em;">
  Market data via Yahoo Finance &nbsp;·&nbsp; Refreshes every 5 minutes &nbsp;·&nbsp;
  <span style="color:#EF4444;font-weight:500;">⚠ Not investment advice</span>
</div>
""")
