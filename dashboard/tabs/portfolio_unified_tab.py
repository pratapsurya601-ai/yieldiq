# dashboard/tabs/portfolio_unified_tab.py
# ═══════════════════════════════════════════════════════════════
# Unified Portfolio tab — Holdings + Watchlist + Alerts as sub-tabs
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_portfolio():
    """Render unified portfolio with Holdings, Watchlist, and Alerts sub-tabs."""

    # Count items for badges
    _holdings_count = 0
    _watchlist_count = 0
    _alerts_count = 0

    try:
        from portfolio import get_watchlist
        _wl = get_watchlist()
        _watchlist_count = len(_wl) if _wl else 0
    except Exception:
        pass

    # Sub-tab navigation
    _sub_options = [
        f"💼 Holdings ({_holdings_count})",
        f"📋 Watchlist ({_watchlist_count})",
        f"🔔 Alerts ({_alerts_count})",
    ]

    _sub = st.radio(
        "Portfolio",
        _sub_options,
        horizontal=True,
        label_visibility="collapsed",
        key="_portfolio_sub",
    )

    if "Holdings" in _sub:
        # Render existing portfolio
        try:
            from portfolio import render_portfolio_tab
            sym = st.session_state.get("fin_sym", "$")
            _port_analysed = None
            if st.session_state.get("fin_ticker"):
                _port_analysed = {
                    "entry_price": st.session_state.get("fin_enriched", {}).get("price", 0) * st.session_state.get("fin_fx", 1),
                    "iv": st.session_state.get("fin_iv_d", 0),
                    "mos_pct": st.session_state.get("fin_mos_pct", 0),
                    "signal": st.session_state.get("fin_signal", ""),
                    "wacc": st.session_state.get("fin_enriched", {}).get("wacc_used", 0),
                    "to_code": st.session_state.get("fin_to_code", "USD"),
                    "company_name": st.session_state.get("fin_raw", {}).get("company_name", ""),
                    "sector": st.session_state.get("fin_enriched", {}).get("sector_name", ""),
                }
            render_portfolio_tab(
                sym=sym,
                analysed_ticker=st.session_state.get("fin_ticker", ""),
                analysed_data=_port_analysed,
            )
        except Exception as e:
            st.info("Your portfolio is empty. Analyse a stock and save it to get started!")

    elif "Watchlist" in _sub:
        try:
            from tabs.watchlist_tab import render as _render_watchlist
            _render_watchlist()
        except Exception:
            st.info("Your watchlist is empty. Add stocks from the analysis page.")

    elif "Alerts" in _sub:
        try:
            from tabs.alerts_tab import render as _render_alerts
            _render_alerts()
        except Exception:
            st.info("No price alerts set. Add alerts from the analysis page.")
