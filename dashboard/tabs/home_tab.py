# dashboard/tabs/home_tab.py
# ═══════════════════════════════════════════════════════════════
# Home tab — Morning brief for returning users, empty state for new
# Sections: Market Pulse, Your Movers, Top Pick, Notifications, Quick Actions
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_home():
    """Render the Home tab."""
    _has_analyses = bool(st.session_state.get("fin_ticker"))
    _has_watchlist = False
    try:
        from portfolio import get_watchlist
        _wl = get_watchlist()
        _has_watchlist = bool(_wl) and len(_wl) > 0
    except Exception:
        pass

    _has_portfolio = False
    try:
        from portfolio import get_portfolio
        _pf = get_portfolio()
        _has_portfolio = bool(_pf) and len(_pf) > 0
    except Exception:
        pass

    if _has_analyses or _has_watchlist or _has_portfolio:
        _render_morning_brief(_has_portfolio, _has_watchlist)
    else:
        _render_empty_home()


# ═══════════════════════════════════════════════════════════════
# MORNING BRIEF (returning users)
# ═══════════════════════════════════════════════════════════════

def _render_morning_brief(has_portfolio: bool, has_watchlist: bool):
    """Full morning brief for returning users."""

    # ── Section A: Market Pulse Strip ─────────────────────────
    _render_market_pulse()

    # ── Section B: Your Movers ────────────────────────────────
    if has_portfolio or has_watchlist:
        _render_your_movers()

    # ── Section C: Top Pick (compact) ─────────────────────────
    _render_top_pick_compact()

    # ── Section D: Unread Notifications ───────────────────────
    _render_notification_preview()

    # ── Section E: Quick Actions ──────────────────────────────
    _render_quick_actions()


# ── SECTION A: Market Pulse ───────────────────────────────────

def _render_market_pulse():
    """Show market indices + fear & greed indicator."""
    # Determine market based on country config
    _is_india = _check_is_india()

    if _is_india:
        _indices = [
            {"name": "NIFTY 50", "ticker": "^NSEI"},
            {"name": "SENSEX", "ticker": "^BSESN"},
        ]
    else:
        _indices = [
            {"name": "S&P 500", "ticker": "^GSPC"},
            {"name": "NASDAQ", "ticker": "^IXIC"},
        ]

    # Fetch prices (cached 5 min)
    _data = _fetch_market_data([i["ticker"] for i in _indices])

    _cards_html = ""
    for idx_info in _indices:
        _d = _data.get(idx_info["ticker"], {})
        _price = _d.get("price", 0)
        _change = _d.get("change_pct", 0)
        _color = "#059669" if _change >= 0 else "#DC2626"
        _arrow = "↑" if _change >= 0 else "↓"
        _price_str = f"{_price:,.0f}" if _price > 100 else f"{_price:,.2f}"

        _cards_html += f"""
        <div style="flex:1;text-align:center;padding:8px 0;">
          <div style="font-size:10px;color:#94A3B8;font-weight:700;text-transform:uppercase;
                      letter-spacing:0.08em;">{idx_info['name']}</div>
          <div style="font-size:16px;font-weight:800;color:#0F172A;
                      font-family:IBM Plex Mono,monospace;">{_price_str}</div>
          <div style="font-size:11px;font-weight:700;color:{_color};">
            {_arrow} {abs(_change):.1f}%</div>
        </div>"""

    # Fear & Greed estimate (simplified — based on VIX or India VIX)
    _fg = _estimate_fear_greed(_is_india)
    _fg_value = _fg["value"]
    _fg_label = _fg["label"]
    _fg_color = _fg["color"]

    _cards_html += f"""
    <div style="flex:1;text-align:center;padding:8px 0;">
      <div style="font-size:10px;color:#94A3B8;font-weight:700;text-transform:uppercase;
                  letter-spacing:0.08em;">Sentiment</div>
      <div style="font-size:16px;font-weight:800;color:{_fg_color};
                  font-family:IBM Plex Mono,monospace;">{_fg_value}</div>
      <div style="font-size:11px;font-weight:600;color:{_fg_color};">{_fg_label}</div>
    </div>"""

    st.html(f"""
    <div style="display:flex;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                padding:8px 4px;margin-bottom:16px;gap:4px;">
      {_cards_html}
    </div>
    """)


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_market_data(tickers: list[str]) -> dict:
    """Fetch current prices for market indices. Cached 5 minutes."""
    result = {}
    try:
        import yfinance as yf
        for t in tickers:
            try:
                _tk = yf.Ticker(t)
                _fi = _tk.fast_info
                _price = getattr(_fi, "last_price", 0) or 0
                _prev = getattr(_fi, "previous_close", _price) or _price
                _change = ((_price - _prev) / _prev * 100) if _prev > 0 else 0
                result[t] = {"price": _price, "change_pct": _change}
            except Exception:
                result[t] = {"price": 0, "change_pct": 0}
    except Exception:
        for t in tickers:
            result[t] = {"price": 0, "change_pct": 0}
    return result


def _estimate_fear_greed(is_india: bool) -> dict:
    """Estimate market sentiment from VIX."""
    try:
        import yfinance as yf
        _vix_ticker = "^INDIAVIX" if is_india else "^VIX"
        _vix = yf.Ticker(_vix_ticker).fast_info
        _val = getattr(_vix, "last_price", 20) or 20

        if is_india:
            # India VIX: <12 = greed, 12-18 = neutral, 18-25 = fear, >25 = extreme fear
            if _val < 12:
                return {"value": int(_val), "label": "Greed", "color": "#059669"}
            elif _val < 18:
                return {"value": int(_val), "label": "Neutral", "color": "#D97706"}
            elif _val < 25:
                return {"value": int(_val), "label": "Fear", "color": "#DC2626"}
            else:
                return {"value": int(_val), "label": "Extreme Fear", "color": "#991B1B"}
        else:
            if _val < 15:
                return {"value": int(_val), "label": "Extreme Greed", "color": "#065F46"}
            elif _val < 20:
                return {"value": int(_val), "label": "Greed", "color": "#059669"}
            elif _val < 25:
                return {"value": int(_val), "label": "Neutral", "color": "#D97706"}
            elif _val < 30:
                return {"value": int(_val), "label": "Fear", "color": "#DC2626"}
            else:
                return {"value": int(_val), "label": "Extreme Fear", "color": "#991B1B"}
    except Exception:
        return {"value": 50, "label": "Neutral", "color": "#D97706"}


def _check_is_india() -> bool:
    """Check if current market is India."""
    try:
        from config.countries import get_active_country
        _country = get_active_country()
        return _country.get("code", "IN") == "IN"
    except Exception:
        pass
    # Fallback: check LAUNCH_REGION
    try:
        import importlib.util as _ilu, pathlib as _pl
        _cfg_path = _pl.Path(__file__).resolve().parent.parent.parent / "utils" / "config.py"
        _cfg_spec = _ilu.spec_from_file_location("_yiq_cfg", _cfg_path)
        _cfg_mod = _ilu.module_from_spec(_cfg_spec)
        _cfg_spec.loader.exec_module(_cfg_mod)
        return getattr(_cfg_mod, "LAUNCH_REGION", "GLOBAL") in ("IN", "GLOBAL")
    except Exception:
        return True  # Default to India


# ── SECTION B: Your Movers ────────────────────────────────────

def _render_your_movers():
    """Show portfolio/watchlist stocks that moved > 2% today."""
    _movers = _get_movers()
    if not _movers:
        st.html("""
        <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.14em;margin-bottom:8px;">Your stocks today</div>
        <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                    padding:12px 16px;margin-bottom:16px;font-size:12px;color:#64748B;">
          Your stocks are stable today — no significant moves.</div>
        """)
        return

    st.html("""
    <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.14em;margin-bottom:8px;">Your stocks today</div>
    """)

    _cols = st.columns(min(len(_movers), 4))
    for i, m in enumerate(_movers[:4]):
        with _cols[i]:
            _color = "#059669" if m["change"] >= 0 else "#DC2626"
            _bg = "#F0FDF4" if m["change"] >= 0 else "#FEF2F2"
            _arrow = "↑" if m["change"] >= 0 else "↓"
            _display = m["ticker"].replace(".NS", "").replace(".BO", "")
            st.html(f"""
            <div style="background:{_bg};border-radius:10px;padding:12px;text-align:center;
                        margin-bottom:12px;">
              <div style="font-size:12px;font-weight:700;color:#0F172A;">{_display}</div>
              <div style="font-size:18px;font-weight:800;color:{_color};
                          font-family:IBM Plex Mono,monospace;">
                {_arrow}{abs(m['change']):.1f}%</div>
            </div>
            """)


def _get_movers() -> list[dict]:
    """Get portfolio/watchlist stocks that moved > 2% today."""
    _tickers = set()
    try:
        from portfolio import get_portfolio, get_watchlist
        for h in get_portfolio():
            _tickers.add(h.get("ticker", ""))
        for w in get_watchlist():
            _tickers.add(w.get("ticker", ""))
    except Exception:
        return []

    _tickers.discard("")
    if not _tickers:
        return []

    movers = []
    try:
        import yfinance as yf
        for t in list(_tickers)[:20]:
            try:
                _tk = yf.Ticker(t)
                _fi = _tk.fast_info
                _price = getattr(_fi, "last_price", 0) or 0
                _prev = getattr(_fi, "previous_close", _price) or _price
                _change = ((_price - _prev) / _prev * 100) if _prev > 0 else 0
                if abs(_change) >= 2:
                    movers.append({"ticker": t, "change": _change})
            except Exception:
                pass
    except Exception:
        return []

    movers.sort(key=lambda x: abs(x["change"]), reverse=True)
    return movers[:4]


# ── SECTION C: Top Pick (compact) ─────────────────────────────

def _render_top_pick_compact():
    """Compact version of Discover tab's top pick."""
    from datetime import date

    _key = f"_discover_top_pick_{date.today().isoformat()}"
    _pick = st.session_state.get(_key)

    if not _pick:
        # Try to compute from screener data
        try:
            from tabs.discover_tab import _compute_top_pick, _generate_summary, _load_screener_data
            _df = _load_screener_data()
            _pick = _compute_top_pick(_df)
            if not _pick.get("summary"):
                _pick["summary"] = _generate_summary(_pick)
            st.session_state[_key] = _pick
        except Exception:
            _pick = {
                "ticker": "RELIANCE.NS", "company": "Reliance Industries",
                "score": 72, "mos": 18, "moat": "Wide",
                "summary": "Strong free cash flows with wide moat.",
            }

    _display = _pick["ticker"].replace(".NS", "").replace(".BO", "")

    st.html(f"""
    <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.14em;margin-bottom:8px;">Top pick today</div>
    <div style="border-left:3px solid #1D4ED8;background:#FFFFFF;border-radius:0 10px 10px 0;
                padding:14px 16px;margin-bottom:4px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
      <div style="display:flex;align-items:center;gap:12px;">
        <div>
          <div style="font-size:14px;font-weight:700;color:#0F172A;">{_pick.get('company', _display)}</div>
          <div style="font-size:11px;color:#94A3B8;">{_display}</div>
        </div>
        <div style="margin-left:auto;text-align:right;">
          <div style="font-size:18px;font-weight:900;color:#1D4ED8;
                      font-family:IBM Plex Mono,monospace;">{_pick.get('score', 70)}</div>
          <div style="font-size:9px;color:#94A3B8;">Score</div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:14px;font-weight:700;color:#059669;
                      font-family:IBM Plex Mono,monospace;">{_pick.get('mos', 15):+.0f}%</div>
          <div style="font-size:9px;color:#94A3B8;">MoS</div>
        </div>
      </div>
      <div style="font-size:12px;color:#64748B;margin-top:8px;line-height:1.5;">
        {_pick.get('summary', '')}</div>
    </div>
    """)

    _bc1, _bc2 = st.columns(2)
    with _bc1:
        if st.button(f"Analyse {_display} →", key="_home_tp_analyse"):
            st.session_state["_prefill_ticker"] = _pick["ticker"]
            st.session_state["_auto_analyse"] = True
            st.session_state.active_tab = "Search"
            st.session_state.main_tab = "stock"
            st.rerun()
    with _bc2:
        if st.button("See full Discover →", key="_home_discover"):
            st.session_state.active_tab = "Discover"
            st.session_state.main_tab = "yieldiq50"
            st.rerun()


# ── SECTION D: Notification Preview ──────────────────────────

def _render_notification_preview():
    """Show first 2 unread notifications if any."""
    try:
        from utils.notifications import NotificationStore
        store = NotificationStore()
        _unread = store.get_unread()
        if not _unread:
            return

        st.html("""
        <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.14em;margin:16px 0 8px;">Notifications</div>
        """)

        for n in _unread[:2]:
            st.html(f"""
            <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:10px;
                        padding:10px 14px;margin-bottom:6px;">
              <div style="font-size:12px;font-weight:600;color:#0F172A;margin-bottom:2px;">
                {n.title}</div>
              <div style="font-size:11px;color:#64748B;line-height:1.5;
                          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
                          overflow:hidden;">{n.body}</div>
            </div>
            """)

        if len(_unread) > 2:
            st.html(f"""
            <div style="font-size:11px;color:#1D4ED8;font-weight:600;margin-bottom:12px;
                        cursor:pointer;">View all {len(_unread)} notifications →</div>
            """)
    except Exception:
        pass


# ── SECTION E: Quick Actions ─────────────────────────────────

def _render_quick_actions():
    """Two large action buttons."""
    st.html('<div style="height:8px;"></div>')
    _c1, _c2 = st.columns(2)
    with _c1:
        if st.button("Analyse a stock", key="_home_analyse", type="primary",
                     use_container_width=True):
            st.session_state.active_tab = "Search"
            st.session_state.main_tab = "stock"
            st.rerun()
    with _c2:
        if st.button("View YieldIQ 50", key="_home_yiq50",
                     use_container_width=True):
            st.session_state.active_tab = "Discover"
            st.session_state.main_tab = "yieldiq50"
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# EMPTY STATE (new users)
# ═══════════════════════════════════════════════════════════════

def _render_empty_home():
    """Empty state — drives first action."""
    st.html("""
    <div style="text-align:center;padding:40px 20px 20px;max-width:500px;margin:0 auto;">
      <div style="font-size:36px;margin-bottom:12px;">📊</div>
      <div style="font-size:22px;font-weight:800;color:#0F172A;margin-bottom:8px;">
        Your market briefing will live here</div>
      <div style="font-size:14px;color:#64748B;line-height:1.6;">
        Start by analysing one stock you already own or follow.</div>
    </div>
    """)

    # Quick pick buttons
    try:
        from config.countries import get_active_country
        _country = get_active_country()
        _picks = _country.get("popular_display", ["RELIANCE", "TCS", "INFY", "HDFC BANK"])[:8]
        _tickers = _country.get("popular_stocks", ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"])[:8]
    except Exception:
        _picks = ["RELIANCE", "TCS", "INFY", "HDFC BANK"]
        _tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]

    _cols = st.columns(min(len(_picks), 4))
    for _i, (_display, _full) in enumerate(zip(_picks[:4], _tickers[:4])):
        with _cols[_i]:
            if st.button(_display, key=f"_home_pick_{_i}", use_container_width=True):
                st.session_state["_prefill_ticker"] = _full
                st.session_state["_auto_analyse"] = True
                st.session_state.active_tab = "Search"
                st.session_state.main_tab = "stock"
                st.rerun()

    if len(_picks) > 4:
        _cols2 = st.columns(min(len(_picks) - 4, 4))
        for _i, (_display, _full) in enumerate(zip(_picks[4:8], _tickers[4:8])):
            with _cols2[_i]:
                if st.button(_display, key=f"_home_pick2_{_i}", use_container_width=True):
                    st.session_state["_prefill_ticker"] = _full
                    st.session_state["_auto_analyse"] = True
                    st.session_state.active_tab = "Search"
                    st.session_state.main_tab = "stock"
                    st.rerun()

    # Primary CTA
    st.html('<div style="height:16px;"></div>')
    _c1, _c2, _c3 = st.columns([1, 2, 1])
    with _c2:
        if st.button("Analyse a stock →", key="_home_analyse_empty", type="primary",
                     use_container_width=True):
            st.session_state.active_tab = "Search"
            st.session_state.main_tab = "stock"
            st.rerun()
