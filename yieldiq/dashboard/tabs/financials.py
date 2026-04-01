"""dashboard/tabs/financials.py"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from ui.helpers import fmt, fmts, KL, apply_koyfin, CL, ccard, ccard_end, CURRENCIES


def render_financials_tab(tab) -> None:
    """Render the Financials tab."""
    with tab:
        st.html("""
        <div style="margin-top:8px;margin-bottom:16px;padding:16px 20px;
                    background:linear-gradient(135deg,#F8FAFC,#F4F6F9);
                    border:1px solid #E2E8F0;border-radius:12px;">
          <div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:4px;">📑 Financial Statements</div>
          <div style="font-size:13px;color:#475569;line-height:1.7;">
            Analyse a stock in the <b style="color:#3b82f6;">Single Stock Analysis</b> tab first, then return here to view
            the full historical P&amp;L, Cash Flow, and Balance Sheet data pulled from Yahoo Finance.
          </div>
        </div>
        """)

        # Check if analysis has been run (look for session state data)
        if "fin_enriched" not in st.session_state:
            st.html("""
            <div style="margin-top:32px;padding:48px;background:linear-gradient(135deg,#F8FAFC,#F4F6F9);
                        border:1px solid #E2E8F0;border-radius:16px;text-align:center;">
              <div style="font-size:40px;margin-bottom:14px;">📑</div>
              <div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:8px;">No data loaded yet</div>
              <div style="font-size:13px;color:#475569;max-width:460px;margin:0 auto;line-height:1.8;">
                Go to <b style="color:#3b82f6;">Single Stock Analysis</b>, enter a ticker and click Analyse.<br>
                Financial Statements will appear here automatically.
              </div>
            </div>
            """)
        else:
            fin_enriched  = st.session_state["fin_enriched"]
            fin_ticker    = st.session_state.get("fin_ticker", "")
            fin_fx        = st.session_state.get("fin_fx", 1.0)
            fin_to_code   = st.session_state.get("fin_to_code", "INR")
            fin_sym       = st.session_state.get("fin_sym", "₹")

            def _fmt_fin_val(v, is_pct=False, is_ratio=False):
                """Format a financial value for display."""
                if pd.isna(v) or v is None:
                    return "—"
                if is_pct:
                    return f"{v*100:.1f}%"
                if is_ratio:
                    return f"{v:.2f}x"
                converted = v * fin_fx / 1e9
                color = "#10b981" if converted > 0 else ("#ef4444" if converted < 0 else "#64748b")
                return converted, color

            def render_fin_table(df, title, rows_config, accent="#3b82f6"):
                """Render a financial statement as a styled HTML table."""
                if df is None or df.empty:
                    st.html(f"""
                    <div style="padding:20px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
                                text-align:center;color:#475569;font-size:13px;">
                      No data available for {title}
                    </div>
                    """)
                    return

                years = []
                if "year" in df.columns:
                    years = [str(int(y)) for y in df["year"].tolist()]
                elif df.index.name == "year" or df.index.dtype in [int, float]:
                    years = [str(int(y)) for y in df.index.tolist()]
                else:
                    years = [f"Period {i+1}" for i in range(len(df))]

                yr_headers = "".join([
                    f'<th style="background:#EFF6FF;color:#475569;font-size:13px;font-weight:700;'
                    f'padding:10px 16px;text-align:right;border:1px solid #F8FAFC;">{yr}</th>'
                    for yr in years
                ])

                rows_html = ""
                for label, col, is_pct, is_ratio, bold, is_section in rows_config:
                    if is_section:
                        span = len(years) + 1
                        rows_html += f"""
                        <tr>
                          <td colspan="{span}" style="background:{accent}22;color:{accent};
                              font-size:12px;font-weight:700;padding:8px 16px;
                              text-transform:uppercase;letter-spacing:0.04em;
                              border:1px solid #F8FAFC;">{label}</td>
                        </tr>"""
                        continue

                    row_bg = "#F8FAFC" if bold else "#F4F6F9"
                    lbl_cell = f'<td style="background:{row_bg};color:{"#e2e8f0" if bold else "#94a3b8"};font-size:{"14px" if bold else "13px"};font-weight:{"700" if bold else "400"};padding:9px 16px;border:1px solid #F8FAFC;min-width:220px;">{label}</td>'

                    val_cells = ""
                    if col and col in df.columns:
                        _vals = df[col].tolist()
                        for _vi, val in enumerate(_vals):
                            if pd.isna(val) or val is None:
                                display = "—"
                                color   = "#334155"
                            elif is_pct:
                                display = f"{val*100:.1f}%"
                                color   = "#10b981" if val > 0 else ("#ef4444" if val < 0 else "#64748b")
                            elif is_ratio:
                                display = f"{val:.2f}x"
                                color   = "#10b981" if val > 1 else "#f59e0b"
                            else:
                                converted = val * fin_fx / 1e9
                                display   = f"{fin_sym}{converted:,.2f}B"
                                # 3-tier YoY growth coloring for absolute value rows
                                if _vi > 0:
                                    _prev = _vals[_vi - 1]
                                    if _prev and not pd.isna(_prev) and _prev != 0:
                                        _yoy = (val - _prev) / abs(_prev)
                                        if _yoy > 0.10:
                                            color = "#10b981"   # green  — >10% growth
                                        elif _yoy >= 0:
                                            color = "#f59e0b"   # amber  — 0–10% growth
                                        else:
                                            color = "#ef4444"   # red    — negative growth
                                    else:
                                        color = "#10b981" if converted > 0 else ("#ef4444" if converted < 0 else "#64748b")
                                else:
                                    # First year — no prior period, use sign-based color
                                    color = "#10b981" if converted > 0 else ("#ef4444" if converted < 0 else "#64748b")
                            val_cells += f'<td style="background:{row_bg};color:{color};font-size:{"14px" if bold else "13px"};font-weight:{"700" if bold else "400"};padding:9px 16px;text-align:right;border:1px solid #F8FAFC;font-family:"Courier New",monospace;">{display}</td>'
                    else:
                        for _ in years:
                            val_cells += f'<td style="background:{row_bg};color:#64748B;padding:9px 16px;text-align:right;border:1px solid #F8FAFC;">—</td>'

                    rows_html += f"<tr>{lbl_cell}{val_cells}</tr>"

                ccard(title, accent)
                st.html(f"""
                <div style="overflow-x:auto;border-radius:8px;border:1px solid #E2E8F0;">
                  <table style="width:100%;border-collapse:collapse;">
                    <thead>
                      <tr>
                        <th style="background:#EFF6FF;color:{accent};font-size:13px;font-weight:700;
                                   padding:10px 16px;text-align:left;border:1px solid #F8FAFC;min-width:220px;">Line Item</th>
                        {yr_headers}
                      </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                  </table>
                </div>
                """)
                ccard_end()

            st.html(f"""
            <div style="padding:12px 18px;background:#F8FAFC;border:1px solid #E2E8F0;
                        border-radius:10px;margin-bottom:16px;display:flex;
                        align-items:center;justify-content:space-between;">
              <div>
                <span style="font-size:20px;font-weight:800;color:#0F172A;
                             font-family:'IBM Plex Mono',monospace;">{fin_ticker}</span>
                <span style="font-size:13px;color:#475569;margin-left:12px;">
                  Values in {fin_to_code} Billions · Source: Yahoo Finance
                </span>
              </div>
              <div style="font-size:13px;color:#475569;">
                All figures converted at live FX rate
              </div>
            </div>
            """)

            income_df = fin_enriched.get("income_df", pd.DataFrame())
            cf_df     = fin_enriched.get("cf_df",     pd.DataFrame())
            bs_df     = fin_enriched.get("bs_df",     pd.DataFrame())

            # ── P&L ───────────────────────────────────────────────
            inc_config = [
                ("REVENUE",                   None,              False, False, True,  True),
                (f"Revenue ({fin_to_code}B)",         "revenue",         False, False, True,  False),
                (f"Gross Profit ({fin_to_code}B)",     "gross_profit",    False, False, False, False),
                ("PROFITABILITY",              None,              False, False, True,  True),
                (f"Operating Income ({fin_to_code}B)", "operating_income",False, False, True,  False),
                (f"Net Income ({fin_to_code}B)",        "net_income",      False, False, True,  False),
                ("MARGINS",                    None,              False, False, True,  True),
                ("Gross Margin",               "gross_margin",    True,  False, False, False),
                ("Operating Margin",           "op_margin",       True,  False, True,  False),
                ("Net Margin",                 "net_margin",      True,  False, False, False),
            ]
            render_fin_table(income_df, f"Income Statement (P&L) — {fin_ticker}", inc_config, "#3b82f6")

            # ── Cash Flow ─────────────────────────────────────────
            cf_config = [
                ("OPERATING ACTIVITIES",       None,   False, False, True,  True),
                (f"Operating Cash Flow ({fin_to_code}B)", "cfo",  False, False, True,  False),
                (f"Capital Expenditure ({fin_to_code}B)", "capex",False, False, False, False),
                ("FREE CASH FLOW",             None,   False, False, True,  True),
                (f"Free Cash Flow ({fin_to_code}B)",      "fcf",  False, False, True,  False),
                ("GROWTH",                     None,   False, False, True,  True),
                ("FCF YoY Growth",             "fcf_growth", True, False, False, False),
            ]
            render_fin_table(cf_df, f"Cash Flow Statement — {fin_ticker}", cf_config, "#10b981")

            # ── Balance Sheet ─────────────────────────────────────
            bs_config_fallback = None
            if bs_df is not None and not bs_df.empty:
                bs_config = [
                    ("ASSETS",                         None,              False, False, True,  True),
                    (f"Total Assets ({fin_to_code}B)",         "total_assets",    False, False, True,  False),
                    (f"Cash & Equivalents ({fin_to_code}B)",   "cash",            False, False, False, False),
                    (f"Current Assets ({fin_to_code}B)",       "current_assets",  False, False, False, False),
                    ("LIABILITIES",                    None,              False, False, True,  True),
                    (f"Total Debt ({fin_to_code}B)",            "total_debt",      False, False, True,  False),
                    (f"Current Liabilities ({fin_to_code}B)",  "current_liab",    False, False, False, False),
                    ("EQUITY & SOLVENCY",              None,              False, False, True,  True),
                    (f"Shareholders' Equity ({fin_to_code}B)", "equity",          False, False, True,  False),
                    ("Debt / Equity",                  "de_ratio",        False, True,  False, False),
                    ("Current Ratio",                  "current_ratio",   False, True,  False, False),
                ]
                render_fin_table(bs_df, f"Balance Sheet — {fin_ticker}", bs_config, "#06b6d4")
            else:
                # Snapshot from enriched data
                ccard(f"Balance Sheet Snapshot — {fin_ticker}", "#06b6d4")
                snap_rows = [
                    ("Cash & Equivalents",    fin_enriched.get("total_cash", 0)),
                    ("Total Debt",            fin_enriched.get("total_debt", 0)),
                ]
                snap_html = ""
                for label, raw_val in snap_rows:
                    v = raw_val * fin_fx / 1e9
                    color = "#10b981" if v >= 0 else "#ef4444"
                    snap_html += f"""
                    <tr>
                      <td style="background:#F4F6F9;color:#475569;font-size:13px;padding:10px 16px;border:1px solid #F8FAFC;">{label}</td>
                      <td style="background:#F4F6F9;color:{color};font-size:13px;font-weight:700;padding:10px 16px;text-align:right;border:1px solid #F8FAFC;font-family:'Courier New',monospace;">{fin_sym}{v:,.2f}B</td>
                    </tr>"""
                st.html(f"""
                <div style="overflow-x:auto;border-radius:8px;border:1px solid #E2E8F0;">
                  <table style="width:100%;border-collapse:collapse;">
                    <thead><tr>
                      <th style="background:#EFF6FF;color:#06b6d4;font-size:13px;font-weight:700;padding:10px 16px;text-align:left;border:1px solid #F8FAFC;">Line Item</th>
                      <th style="background:#EFF6FF;color:#475569;font-size:13px;font-weight:700;padding:10px 16px;text-align:right;border:1px solid #F8FAFC;">Latest Available</th>
                    </tr></thead>
                    <tbody>{snap_html}</tbody>
                  </table>
                </div>
                """)
                st.caption("Full multi-year balance sheet not available for this ticker via Yahoo Finance.")
                ccard_end()

            # ── Key Ratios Summary ─────────────────────────────────
            ccard("Key financial ratios at a glance", "#8b5cf6")
            r1,r2,r3,r4,r5,r6 = st.columns(6)
            r1.metric("Revenue growth",   f"{fin_enriched.get('revenue_growth', 0)*100:.1f}%")
            r2.metric("Cash flow growth",  f"{fin_enriched.get('fcf_growth', 0)*100:.1f}%")
            r3.metric("Profit margin",     f"{fin_enriched.get('op_margin', 0)*100:.1f}%")
            r4.metric("Free cash generated", fmt(fin_enriched.get("latest_fcf", 0) * fin_fx, fin_sym))
            r5.metric("Cash on hand",      fmt(fin_enriched.get("total_cash", 0) * fin_fx, fin_sym))
            r6.metric("Total debt",        fmt(fin_enriched.get("total_debt", 0) * fin_fx, fin_sym))
            ccard_end()


        # ══════════════════════════════════════════════════════════════
        # TAB 3 — SCREENER RESULTS
        # ══════════════════════════════════════════════════════════════
