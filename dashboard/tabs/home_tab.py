# dashboard/tabs/home_tab.py
# Home tab — delegates to morning_brief for now
from __future__ import annotations
import streamlit as st


def render_home():
    """Render the Home tab — morning brief + market snapshot."""
    try:
        from morning_brief import render_morning_brief
        from portfolio import get_watchlist
        render_morning_brief(
            watchlist_rows=get_watchlist(),
            sym=st.session_state.get("fin_sym", "$"),
            has_prior_results=bool(st.session_state.get("fin_ticker")),
            theme=st.session_state.get("theme", "slate"),
        )
    except Exception as e:
        st.info("Welcome to YieldIQ! Search for a stock to get started.")
