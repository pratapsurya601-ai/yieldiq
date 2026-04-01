"""dashboard/tabs/misc_tabs.py
Screener, Portfolio, Backtest, Sector Dashboard, Watchlist, and Guide tabs.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

from portfolio import render_portfolio_tab
from backtest import render_backtest_tab
from sector_dashboard import render_sector_dashboard
from features import render_comparison_watchlist
from utils.config import RESULTS_PATH
from ui.helpers import fmt, fmts, KL, apply_koyfin, CL, ccard, ccard_end


def render_screener_tab(tab, can_run_screener, record_screener, upgrade_prompt, blur_and_lock, tier_badge_html, usage_bar_html, results_file=None, sym="$") -> None:
    """Render the Stock Screener tab."""
    with tab:
        # ── TIER CHECK: screener access ────────────────────────────
        _screener_ok, _screener_reason = can_run_screener()
        if not _screener_ok:
            st.html("<br>")
            upgrade_prompt("screener")
            st.html("""
            <div style="margin-top:16px;padding:16px 20px;background:#f8fafc;
                        border:1px solid #e2e8f0;border-radius:10px;font-size:13px;color:#4a5568;">
              <strong>What the screener does:</strong> Runs our DCF model on all 698 S&amp;P 1500 stocks
              and ranks them by how undervalued they are — so you can find opportunities without
              analysing stocks one by one. Updated weekly.
            </div>
            """)
        else:
            df_screen = None
            if results_file is not None:
                df_screen = pd.read_csv(results_file)
            else:
                try:
                    df_screen = pd.read_csv(RESULTS_PATH)
                except FileNotFoundError:
                    pass
            record_screener()

        if _screener_ok and (df_screen is None or df_screen.empty):
            st.html("""
            <div style="margin-top:40px;padding:48px;background:linear-gradient(135deg,#F8FAFC,#F4F6F9);
                        border:1px solid #E2E8F0;border-radius:16px;text-align:center;">
              <div style="font-size:40px;margin-bottom:14px;">📋</div>
              <div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:12px;">No Screener Data Yet</div>
              <div style="background:#F4F6F9;border:1px solid #E2E8F0;border-radius:8px;
                          padding:12px 24px;display:inline-block;margin-bottom:10px;">
                <code style="color:#3b82f6;font-size:13px;">python main.py --screen --tickers data/tickers/usa_tickers.csv</code>
              </div>
              <div style="font-size:13px;color:#94a3b8;margin-top:10px;">Run the screener script first to generate results</div>
            </div>
            """)
        elif _screener_ok:
            clean  = df_screen[~df_screen["signal"].astype(str).str.contains("CHECK|N/A", na=False)]
            total  = len(df_screen)
            buys   = len(clean[clean["signal"].astype(str).str.contains("BUY",   na=False)])
            watches= len(clean[clean["signal"].astype(str).str.contains("WATCH", na=False)])
            sells  = len(clean[clean["signal"].astype(str).str.contains("SELL",  na=False)])
            na_ct  = len(df_screen[df_screen["signal"].astype(str).str.contains("N/A|CHECK", na=False)])
            best   = clean.loc[clean["margin_of_safety"].idxmax(),"ticker"] if not clean.empty else "-"

            s1,s2,s3,s4,s5,s6 = st.columns(6)
            s1.metric("Total",   total)
            s2.metric("BUY",     buys)
            s3.metric("WATCH",   watches)
            s4.metric("SELL",    sells)
            s5.metric("N/A",     na_ct)
            s6.metric("Top Pick",best)

            st.html("<div style='height:6px'></div>")

            fc1,fc2,fc3,fc4 = st.columns([1,1,1,1])
            with fc1:
                min_mos = st.slider("Min MoS (%)", -100, 100, 0)
            with fc2:
                sig_filter = st.multiselect("Signal",
                    ["Undervalued 🟢","Near Fair Value 🟡","Fairly Valued 🔵","Overvalued 🔴"],
                    default=["Undervalued 🟢","Near Fair Value 🟡"])  # internal signal codes
            with fc3:
                fund_filter = st.multiselect("Fundamentals",
                    ["STRONG","GOOD","AVERAGE","WEAK"], default=["STRONG","GOOD"])
            with fc4:
                sort_col = st.selectbox("Sort By",
                    ["margin_of_safety","fundamental_score","rr_ratio","target_upside_pct","price"])

            filtered = df_screen[df_screen["margin_of_safety"] >= min_mos].copy()
            filtered = filtered[~filtered["signal"].astype(str).str.contains("CHECK|N/A", na=False)]
            if sig_filter:
                filtered = filtered[filtered["signal"].isin(sig_filter)]
            if fund_filter and "fundamental_grade" in filtered.columns:
                filtered = filtered[filtered["fundamental_grade"].isin(fund_filter)]
            filtered = filtered.sort_values(sort_col, ascending=False).reset_index(drop=True)

            # Display columns — prioritise investment plan columns
            display_cols = ["ticker","price","intrinsic_value","margin_of_safety","signal",
                            "fundamental_grade","buy_price","target_price","stop_loss",
                            "rr_ratio","holding_period","revenue_growth","fcf_growth","op_margin"]
            avail_cols = [c for c in display_cols if c in filtered.columns]
            fmt_dict = {
                "price":            f"{sym}{{:.2f}}",
                "intrinsic_value":  f"{sym}{{:.2f}}",
                "buy_price":        f"{sym}{{:.2f}}",
                "target_price":     f"{sym}{{:.2f}}",
                "stop_loss":        f"{sym}{{:.2f}}",
                "margin_of_safety": "{:.1f}%",
                "revenue_growth":   "{:.1f}%",
                "fcf_growth":       "{:.1f}%",
                "op_margin":        "{:.1f}%",
                "rr_ratio":         "{:.1f}x",
            }
            fmt_dict = {k: v for k, v in fmt_dict.items() if k in avail_cols}

            st.dataframe(
                filtered[avail_cols].style
                    .format(fmt_dict)
                    .background_gradient(subset=["margin_of_safety"], cmap="RdYlGn"),
                width='stretch', height=420,
            )

            # Top 15 chart
            ccard("Top 15 most undervalued stocks right now", "#10b981")
            top15 = filtered.head(15)
            bar_colors = [
                "#10b981" if v>20 else "#f59e0b" if v>5 else "#3b82f6" if v>0 else "#ef4444"
                for v in top15["margin_of_safety"]
            ]
            fig_top = go.Figure(go.Bar(
                x=top15["ticker"], y=top15["margin_of_safety"],
                marker=dict(color=bar_colors, opacity=0.85, line=dict(width=0)),
                text=[f"{v:.1f}%" for v in top15["margin_of_safety"]],
                textposition="outside",
                textfont=dict(size=11, color="#64748b", family="IBM Plex Mono"),
                hovertemplate="<b>%{x}</b><br>MoS: %{y:.1f}%<extra></extra>",
            ))
            fig_top.update_layout(**CL(yaxis_title="Margin of Safety (%)"), showlegend=False, height=300)
            st.plotly_chart(fig_top, width='stretch', config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"filename":"screener_top15","scale":2}})
            ccard_end()

            # Excel download with all fields
            dl_a, dl_b = st.columns(2)
            with dl_a:
                st.download_button(
                    "⬇️ Download Filtered CSV",
                    data=filtered.to_csv(index=False).encode("utf-8"),
                    file_name=f"screener_filtered_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv", width='stretch',
                )
            with dl_b:
                # BUY only export
                buys_only = filtered[filtered["signal"].astype(str).str.contains("BUY", na=False)]
                st.download_button(
                    "🎯 Download BUY Signals Only",
                    data=buys_only.to_csv(index=False).encode("utf-8"),
                    file_name=f"BUY_signals_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv", width='stretch',
                )


        # ══════════════════════════════════════════════════════════════
        # TAB 3 — MODEL GUIDE
        # ══════════════════════════════════════════════════════════════


def render_portfolio_tab_wrapper(tab, sym: str = "$") -> None:
    """Render the Portfolio tab."""
    with tab:
        _port_analysed = None
        if st.session_state.get("fin_ticker"):
            _port_analysed = {
                "entry_price":  st.session_state.get("fin_iv_d", 0) and
                                st.session_state.get("fin_enriched", {}).get("price", 0) *
                                st.session_state.get("fin_fx", 1),
                "iv":           st.session_state.get("fin_iv_d", 0),
                "mos_pct":      st.session_state.get("fin_mos_pct", 0),
                "signal":       st.session_state.get("fin_signal", ""),
                "wacc":         st.session_state.get("fin_enriched", {}).get("wacc_used",
                                st.session_state.get("fin_enriched", {}).get("wacc", 0)),
                "to_code":      st.session_state.get("fin_to_code", "USD"),
                "company_name": st.session_state.get("fin_raw", {}).get("company_name", ""),
                "sector":       st.session_state.get("fin_enriched", {}).get("sector_name", ""),
            }
            # Get actual entry price (price * fx)
            _raw_price = st.session_state.get("fin_enriched", {}).get("price", 0)
            _fx_val    = st.session_state.get("fin_fx", 1)
            if _raw_price and _fx_val:
                _port_analysed["entry_price"] = _raw_price * _fx_val

        # Read sym from session state if not passed explicitly
        _sym = st.session_state.get("fin_sym", sym)

        render_portfolio_tab(
            sym              = _sym,
            analysed_ticker  = st.session_state.get("fin_ticker", ""),
            analysed_data    = _port_analysed,
        )



def render_backtest_tab_wrapper(tab) -> None:
    """Render the Backtest tab."""
    with tab:
        render_backtest_tab()



def render_sector_tab(tab) -> None:
    """Render the Sector tab."""
    with tab:
        render_sector_dashboard()



def render_watchlist_tab(tab, sym: str = "$") -> None:
    """Render the Watchlist tab."""
    with tab:
        st.html("""
        <div style="padding:4px 0 14px;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:700;
                      letter-spacing:0.12em;text-transform:uppercase;color:#94A3B8;margin-bottom:4px;">
            Live Multi-Stock Comparison
          </div>
          <div style="font-size:16px;font-weight:700;color:#0F172A;">
            Watchlist — Compare your universe in real time
          </div>
        </div>
        """)
        _analysed_data = None
        if "fin_ticker" in st.session_state:
            _analysed_data = {
                "mos_pct": st.session_state.get("fin_mos_pct", 0),
                "signal":  st.session_state.get("fin_signal", ""),
                "iv_d":    st.session_state.get("fin_iv_d", 0),
            }
        render_comparison_watchlist(
            sym=sym,
            analysed_ticker=st.session_state.get("fin_ticker", ""),
            analysed_data=_analysed_data,
        )

