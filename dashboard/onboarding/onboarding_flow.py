# dashboard/onboarding/onboarding_flow.py
# ═══════════════════════════════════════════════════════════════
# 60-second onboarding — 5 screens to first "aha moment"
# Only shows when st.session_state.onboarding_complete == False
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def _progress_dots(current: int, total: int = 5) -> None:
    """Render progress dots at the top."""
    dots = ""
    for i in range(1, total + 1):
        if i < current:
            dots += '<span style="display:inline-block;width:8px;height:8px;background:#1D4ED8;border-radius:50%;margin:0 4px;"></span>'
        elif i == current:
            dots += '<span style="display:inline-block;width:24px;height:8px;background:linear-gradient(90deg,#1D4ED8,#06B6D4);border-radius:4px;margin:0 4px;"></span>'
        else:
            dots += '<span style="display:inline-block;width:8px;height:8px;background:#E2E8F0;border-radius:50%;margin:0 4px;"></span>'
    st.html(f'<div style="text-align:center;padding:16px 0;">{dots}</div>')


def _screen1_welcome() -> None:
    """Screen 1 — Welcome."""
    st.html("""
    <div style="text-align:center;padding:60px 20px 40px;max-width:500px;margin:0 auto;">
      <div style="font-size:40px;margin-bottom:16px;">📊</div>
      <div style="font-size:28px;font-weight:900;color:#0F172A;line-height:1.2;margin-bottom:12px;">
        Find out if a stock is worth your money — in seconds</div>
      <div style="font-size:15px;color:#64748B;line-height:1.6;">
        No spreadsheets. No jargon. Just clarity.</div>
    </div>
    """)

    _c1, _c2, _c3 = st.columns([1, 2, 1])
    with _c2:
        if st.button("Get started →", key="_ob_start", type="primary",
                     use_container_width=True):
            st.session_state.onboarding_step = 2
            st.rerun()

    st.html('<div style="text-align:center;margin-top:12px;">')
    if st.button("Skip onboarding", key="_ob_skip_1"):
        st.session_state.onboarding_complete = True
        st.rerun()
    st.html('</div>')


def _screen2_personalise() -> None:
    """Screen 2 — Personalisation."""
    st.html("""
    <div style="text-align:center;padding:30px 20px 20px;max-width:500px;margin:0 auto;">
      <div style="font-size:22px;font-weight:800;color:#0F172A;margin-bottom:8px;">
        What kind of investor are you?</div>
      <div style="font-size:13px;color:#94A3B8;">This personalises your experience</div>
    </div>
    """)

    options = [
        ("🌱", "Just getting started",
         "I want to understand if stocks are cheap or expensive", "beginner"),
        ("📈", "I know the basics",
         "I've analysed stocks before and want better tools", "intermediate"),
        ("🔬", "I analyse stocks regularly",
         "I want institutional-grade research tools", "advanced"),
    ]

    for _icon, _title, _desc, _type in options:
        if st.button(
            f"{_icon}  {_title}",
            key=f"_ob_type_{_type}",
            use_container_width=True,
            help=_desc,
        ):
            st.session_state.investor_type = _type
            # Set defaults based on type
            if _type == "beginner":
                st.session_state.learn_mode = True
                st.session_state.mode = "simple"
            elif _type == "intermediate":
                st.session_state.learn_mode = True
                st.session_state.mode = "simple"
            else:  # advanced
                st.session_state.learn_mode = False
                st.session_state.mode = "simple"
            st.session_state.onboarding_step = 3
            st.rerun()

        st.html(f'<div style="font-size:11px;color:#94A3B8;margin-top:-8px;margin-bottom:12px;padding-left:16px;">{_desc}</div>')


def _screen3_pick_stock() -> None:
    """Screen 3 — Pick a stock."""
    st.html("""
    <div style="text-align:center;padding:30px 20px 20px;max-width:500px;margin:0 auto;">
      <div style="font-size:22px;font-weight:800;color:#0F172A;margin-bottom:8px;">
        Pick a stock you already know</div>
      <div style="font-size:13px;color:#64748B;">
        We'll show you what our model says about it</div>
    </div>
    """)

    # Search input
    _ticker = st.text_input(
        "Enter a stock ticker",
        placeholder="e.g. RELIANCE.NS, TCS.NS, AAPL",
        key="_ob_ticker",
    ).strip().upper()

    # Quick picks
    try:
        from config.countries import get_active_country
        _country = get_active_country()
        _picks = _country.get("popular_display", ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "TSLA"])[:8]
        _tickers = _country.get("popular_stocks", ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "TSLA"])[:8]
    except Exception:
        _picks = ["RELIANCE", "TCS", "INFY", "HDFC BANK", "ICICI BANK", "ITC"]
        _tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "ITC.NS"]

    st.html('<div style="text-align:center;font-size:10px;color:#94A3B8;margin:8px 0;">Or pick one:</div>')

    _cols = st.columns(min(len(_picks), 4))
    for _i, (_display, _full) in enumerate(zip(_picks[:4], _tickers[:4])):
        with _cols[_i]:
            if st.button(_display, key=f"_ob_pick_{_i}", use_container_width=True):
                st.session_state._ob_selected_ticker = _full
                st.session_state.onboarding_step = 4
                st.rerun()

    if len(_picks) > 4:
        _cols2 = st.columns(min(len(_picks) - 4, 4))
        for _i, (_display, _full) in enumerate(zip(_picks[4:8], _tickers[4:8])):
            with _cols2[_i]:
                if st.button(_display, key=f"_ob_pick2_{_i}", use_container_width=True):
                    st.session_state._ob_selected_ticker = _full
                    st.session_state.onboarding_step = 4
                    st.rerun()

    # Manual ticker entry
    if _ticker:
        if st.button(f"Analyse {_ticker} →", key="_ob_go", type="primary",
                     use_container_width=True):
            st.session_state._ob_selected_ticker = _ticker
            st.session_state.onboarding_step = 4
            st.rerun()


def _screen4_aha_moment() -> None:
    """Screen 4 — Show simplified verdict."""
    _ticker = st.session_state.get("_ob_selected_ticker", "RELIANCE.NS")

    st.html(f"""
    <div style="text-align:center;padding:20px 0 12px;">
      <div style="font-size:18px;font-weight:800;color:#0F172A;">
        Here's what our model found:</div>
    </div>
    """)

    # Try to get real data
    _has_data = False
    try:
        from utils.data_helpers import fetch_stock_data
        _result = fetch_stock_data(_ticker, "USD", 1.0, 1.0)
        if _result and _result[0]:
            _raw = _result[0]
            _price = _raw.get("price", 0)
            _name = _raw.get("company_name", _ticker)
            _has_data = True
    except Exception:
        pass

    if _has_data and _price > 0:
        # Show real verdict card
        st.html(f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;
                    padding:24px;max-width:400px;margin:0 auto;text-align:center;
                    box-shadow:0 4px 20px rgba(0,0,0,0.06);">
          <div style="font-size:18px;font-weight:800;color:#0F172A;margin-bottom:4px;">
            {_name}</div>
          <div style="font-size:12px;color:#94A3B8;margin-bottom:16px;">{_ticker}</div>
          <div style="font-size:32px;font-weight:900;color:#0F172A;
                      font-family:'IBM Plex Mono',monospace;">₹{_price:,.2f}</div>
          <div style="font-size:13px;color:#64748B;margin-top:12px;line-height:1.6;">
            Full analysis with fair value, quality scores, and risk assessment
            will be ready when you enter the app.</div>
        </div>
        """)
    else:
        # Fallback static card
        st.html(f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;
                    padding:24px;max-width:400px;margin:0 auto;text-align:center;
                    box-shadow:0 4px 20px rgba(0,0,0,0.06);">
          <div style="font-size:18px;font-weight:800;color:#0F172A;margin-bottom:4px;">
            {_ticker.replace('.NS','').replace('.BO','')}</div>
          <div style="font-size:12px;color:#94A3B8;margin-bottom:16px;">{_ticker}</div>
          <div style="font-size:13px;color:#1D4ED8;font-weight:600;margin-top:12px;">
            ⏳ Loading live data...</div>
          <div style="font-size:12px;color:#94A3B8;margin-top:8px;">
            Full analysis will be ready in seconds</div>
        </div>
        """)

    st.html('<div style="height:20px;"></div>')
    _c1, _c2, _c3 = st.columns([1, 2, 1])
    with _c2:
        if st.button("See full analysis →", key="_ob_full", type="primary",
                     use_container_width=True):
            st.session_state.onboarding_step = 5
            st.rerun()


def _screen5_reframe() -> None:
    """Screen 5 — Reframe + CTA."""
    _ticker = st.session_state.get("_ob_selected_ticker", "RELIANCE.NS")
    _display = _ticker.replace(".NS", "").replace(".BO", "")

    st.html(f"""
    <div style="text-align:center;padding:40px 20px;max-width:500px;margin:0 auto;">
      <div style="font-size:48px;margin-bottom:16px;">✅</div>
      <div style="font-size:24px;font-weight:900;color:#0F172A;margin-bottom:12px;">
        You just ran a professional stock analysis</div>
      <div style="font-size:14px;color:#64748B;line-height:1.6;max-width:400px;margin:0 auto;">
        Analysts spend hours building models like this.
        YieldIQ does it in seconds.</div>
    </div>
    """)

    _c1, _c2 = st.columns(2)
    with _c1:
        if st.button("Analyse more stocks →", key="_ob_more", type="primary",
                     use_container_width=True):
            st.session_state.onboarding_complete = True
            st.session_state["_prefill_ticker"] = _ticker
            st.session_state["_auto_analyse"] = True
            st.session_state.active_tab = "Search"
            st.session_state.main_tab = "stock"
            st.rerun()

    with _c2:
        if st.button(f"Save {_display} to watchlist", key="_ob_save",
                     use_container_width=True):
            try:
                from portfolio import add_to_watchlist
                add_to_watchlist(_ticker)
            except Exception:
                pass
            st.session_state.onboarding_complete = True
            st.session_state.active_tab = "Home"
            st.session_state.main_tab = "stock"
            st.rerun()


def render_onboarding() -> None:
    """Main onboarding entry point. Call this in app.py."""
    step = st.session_state.get("onboarding_step", 1)

    # Ensure step is valid
    if step < 1 or step > 5:
        step = 1
        st.session_state.onboarding_step = 1

    _progress_dots(step)

    if step == 1:
        _screen1_welcome()
    elif step == 2:
        _screen2_personalise()
    elif step == 3:
        _screen3_pick_stock()
    elif step == 4:
        _screen4_aha_moment()
    elif step == 5:
        _screen5_reframe()
