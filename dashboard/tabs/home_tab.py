# dashboard/tabs/home_tab.py
# Home tab — morning brief OR empty state for new users
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

    if _has_analyses or _has_watchlist:
        # Show morning brief for returning users
        try:
            from morning_brief import render_morning_brief
            from portfolio import get_watchlist
            render_morning_brief(
                watchlist_rows=get_watchlist(),
                sym=st.session_state.get("fin_sym", "₹"),
                has_prior_results=_has_analyses,
                theme=st.session_state.get("theme", "slate"),
            )
        except Exception:
            st.info("Welcome back! Search for a stock to get started.")
    else:
        # Empty state for new users
        _render_empty_home()


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
        if st.button("🔍 Analyse a stock →", key="_home_analyse", type="primary",
                     use_container_width=True):
            st.session_state.active_tab = "Search"
            st.session_state.main_tab = "stock"
            st.rerun()
