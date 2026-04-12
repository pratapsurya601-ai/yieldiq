# dashboard/tabs/discover_tab.py
# Discover tab — YieldIQ 50 Index + Sector Map + Screener
from __future__ import annotations
import streamlit as st


def render_discover():
    """Render the Discover tab — YieldIQ 50, sectors, and opportunities."""
    _sub = st.radio(
        "Explore",
        ["🏆 YieldIQ 50", "🗺️ Sector Map", "🔍 Screener"],
        horizontal=True,
        label_visibility="collapsed",
        key="_discover_sub",
    )

    if _sub == "🏆 YieldIQ 50":
        from tabs.yieldiq50_tab import render as _render_yiq50
        _render_yiq50()
    elif _sub == "🗺️ Sector Map":
        from sector_heatmap import render_sector_heatmap
        render_sector_heatmap()
    elif _sub == "🔍 Screener":
        from tabs.screener_tab import render as _render_screener
        _render_screener()
