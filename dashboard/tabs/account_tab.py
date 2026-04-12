# dashboard/tabs/account_tab.py
# Account tab — settings, pricing, about
from __future__ import annotations
import streamlit as st


def render_account():
    """Render the Account tab — user settings, pricing, about."""
    _sub = st.radio(
        "Account",
        ["⚙️ Settings", "💳 Pricing", "📊 Financials", "⚖️ Compare", "📅 Earnings"],
        horizontal=True,
        label_visibility="collapsed",
        key="_account_sub",
    )

    if _sub == "⚙️ Settings":
        # About/Settings page
        st.session_state["main_tab"] = "about"
        # Import and render inline to avoid circular imports
        st.html("""
        <div style="padding:20px 0;">
          <div style="font-size:20px;font-weight:800;color:#0F172A;margin-bottom:12px;">Settings</div>
          <div style="font-size:13px;color:#64748B;">
            Use the sidebar controls to adjust currency, WACC, forecast years, and theme.
          </div>
        </div>
        """)

        # Sign out button
        if st.button("🚪 Sign Out", use_container_width=True):
            for _k in list(st.session_state.keys()):
                del st.session_state[_k]
            st.rerun()

    elif _sub == "💳 Pricing":
        try:
            from tier_gate import render_pricing_page
            render_pricing_page()
        except Exception as e:
            st.error(f"Could not load pricing: {e}")

    elif _sub == "📊 Financials":
        try:
            from tabs.financials import render as _render_fin
            _render_fin()
        except Exception:
            st.info("Run a stock analysis first to see financial statements.")

    elif _sub == "⚖️ Compare":
        try:
            from tabs.compare_tab import render as _render_compare
            _render_compare(st.container())
        except Exception:
            st.info("Compare stocks feature.")

    elif _sub == "📅 Earnings":
        try:
            from tabs.earnings_tab import render_earnings_tab
            render_earnings_tab(ticker=st.session_state.get("fin_ticker", ""))
        except Exception:
            st.info("Run a stock analysis first to see earnings data.")
