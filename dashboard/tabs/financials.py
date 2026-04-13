"""dashboard/tabs/financials.py
Tab 2 — Financial Statements.
Moved from app.py.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
from ui.helpers import render_fin_table, ccard, ccard_end
from tier_gate import can_download_report, record_report
import importlib.util as _ilu, pathlib as _pl
_dh_path = _pl.Path(__file__).resolve().parent.parent / "utils" / "data_helpers.py"
_dh_spec = _ilu.spec_from_file_location("_yiq_dh", _dh_path)
_dh_mod  = _ilu.module_from_spec(_dh_spec); _dh_spec.loader.exec_module(_dh_mod)
fmt = _dh_mod.fmt; CURRENCIES = _dh_mod.CURRENCIES


def render() -> None:
    """Render the Financial Statements tab."""
    _cur = st.session_state.get("sb_currency", "INR")
    sym     = CURRENCIES[_cur]["symbol"]
    to_code = CURRENCIES[_cur]["code"]

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
        fin_enriched  = st.session_state.get("fin_enriched", {})
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

        # ── KEY METRICS CHART PANEL (Revenue / Op Margin / FCF) ───────
        if not income_df.empty and not cf_df.empty:
            try:
                _chart_years = [str(int(y)) for y in income_df["year"].tolist()] if "year" in income_df.columns else []
                _rev_vals  = [(v * fin_fx / 1e9) if v is not None and not pd.isna(v) else None
                              for v in income_df.get("revenue", pd.Series()).tolist()] if "revenue" in income_df.columns else []
                _opm_vals  = [(v * 100) if v is not None and not pd.isna(v) else None
                              for v in income_df.get("op_margin", pd.Series()).tolist()] if "op_margin" in income_df.columns else []
                _fcf_vals  = [(v * fin_fx / 1e9) if v is not None and not pd.isna(v) else None
                              for v in cf_df.get("fcf", pd.Series()).tolist()] if "fcf" in cf_df.columns else []

                _ch1, _ch2, _ch3 = st.columns(3)

                # Panel 1 — Revenue (bar)
                if _rev_vals and _chart_years:
                    with _ch1:
                        _fig_rev = go.Figure(go.Bar(
                            x=_chart_years, y=_rev_vals,
                            marker_color="#3b82f6",
                            marker_line_width=0,
                            hovertemplate="%{x}: " + fin_sym + "%{y:,.2f}B<extra></extra>",
                        ))
                        _fig_rev.update_layout(**CL(
                            height=190,
                            title=dict(text="Revenue", font=dict(size=12, color="#0F172A"), x=0.02),
                            margin=dict(t=36, b=32, l=40, r=8),
                            yaxis=dict(tickprefix=fin_sym, ticksuffix="B", gridcolor="#F1F5F9",
                                       linecolor="#E2E8F0", zeroline=False, tickfont=dict(color="#64748B", size=9)),
                            xaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", zeroline=False,
                                       tickfont=dict(color="#64748B", size=9)),
                        ))
                        st.plotly_chart(_fig_rev, width="stretch",
                                        config={"displayModeBar": False})

                # Panel 2 — Operating Margin (line)
                if _opm_vals and _chart_years:
                    with _ch2:
                        _fig_opm = go.Figure(go.Scatter(
                            x=_chart_years, y=_opm_vals,
                            mode="lines+markers",
                            line=dict(color="#0d9488", width=2),
                            marker=dict(color="#0d9488", size=5),
                            fill="tozeroy",
                            fillcolor="rgba(13,148,136,0.08)",
                            hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
                        ))
                        _fig_opm.update_layout(**CL(
                            height=190,
                            title=dict(text="Operating Margin", font=dict(size=12, color="#0F172A"), x=0.02),
                            margin=dict(t=36, b=32, l=40, r=8),
                            yaxis=dict(ticksuffix="%", gridcolor="#F1F5F9",
                                       linecolor="#E2E8F0", zeroline=False, tickfont=dict(color="#64748B", size=9)),
                            xaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", zeroline=False,
                                       tickfont=dict(color="#64748B", size=9)),
                        ))
                        st.plotly_chart(_fig_opm, width="stretch",
                                        config={"displayModeBar": False})

                # Panel 3 — FCF (bar, green/red)
                if _fcf_vals and _chart_years:
                    with _ch3:
                        _fcf_colors = ["#059669" if (v or 0) >= 0 else "#dc2626" for v in _fcf_vals]
                        _fig_fcf2 = go.Figure(go.Bar(
                            x=_chart_years, y=_fcf_vals,
                            marker_color=_fcf_colors,
                            marker_line_width=0,
                            hovertemplate="%{x}: " + fin_sym + "%{y:,.2f}B<extra></extra>",
                        ))
                        _fig_fcf2.update_layout(**CL(
                            height=190,
                            title=dict(text="Free Cash Flow", font=dict(size=12, color="#0F172A"), x=0.02),
                            margin=dict(t=36, b=32, l=40, r=8),
                            yaxis=dict(tickprefix=fin_sym, ticksuffix="B", gridcolor="#F1F5F9",
                                       linecolor="#E2E8F0", zeroline=True, zeroline_color="#CBD5E1",
                                       tickfont=dict(color="#64748B", size=9)),
                            xaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", zeroline=False,
                                       tickfont=dict(color="#64748B", size=9)),
                        ))
                        st.plotly_chart(_fig_fcf2, width="stretch",
                                        config={"displayModeBar": False})
            except Exception:
                pass  # Charts are non-critical; silently skip on data issues

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

        # ── EXCEL EXPORT ──────────────────────────────────────────
        st.html("<div style='height:8px'></div>")
        _can_dl_fin, _dl_fin_reason = can_download_report()
        if _can_dl_fin:
            try:
                import sys as _sys2
                from pathlib import Path as _Path2
                _proj2 = str(_Path2(__file__).parent.parent)
                if _proj2 not in _sys2.path:
                    _sys2.path.insert(0, _proj2)
                from generate_dcf_excel import generate_institutional_dcf
                from generate_hf_excel import build_hedge_fund_sheets
                from generate_portfolio_excel import build_portfolio_sheets
                import io as _io2
                from openpyxl import load_workbook as _lwb2
                _dcf_res_fin   = st.session_state.get("dcf_res", {})
                _fcst_fin      = st.session_state.get("forecast_result", {})
                _scen_fin      = st.session_state.get("scenarios", {})
                _wacc_data_fin = st.session_state.get("wacc_data", {})
                _wacc_fin      = st.session_state.get("wacc", 0.10)
                _tg_fin        = st.session_state.get("terminal_g", 0.03)
                _fy_fin        = st.session_state.get("forecast_yrs", 5)
                if _dcf_res_fin:
                    _hf2 = generate_institutional_dcf(
                        ticker=fin_ticker, enriched=fin_enriched, dcf_res=_dcf_res_fin,
                        forecast_result=_fcst_fin, scenarios=_scen_fin,
                        wacc_data=_wacc_data_fin, wacc=_wacc_fin, terminal_g=_tg_fin,
                        forecast_yrs=_fy_fin, sym=fin_sym, to_code=fin_to_code, fx=fin_fx,
                    )
                    _wb2 = _lwb2(filename=_io2.BytesIO(_hf2))
                    _wb2 = build_hedge_fund_sheets(
                        wb=_wb2, ticker=fin_ticker, enriched=fin_enriched, dcf_res=_dcf_res_fin,
                        forecast_result=_fcst_fin, scenarios=_scen_fin, wacc_data=_wacc_data_fin,
                        wacc=_wacc_fin, terminal_g=_tg_fin, forecast_yrs=_fy_fin,
                        sym=fin_sym, fx=fin_fx,
                    )
                    _wb2 = build_portfolio_sheets(
                        wb=_wb2, ticker=fin_ticker, enriched=fin_enriched, dcf_res=_dcf_res_fin,
                        forecast_result=_fcst_fin, scenarios=_scen_fin, wacc_data=_wacc_data_fin,
                        wacc=_wacc_fin, terminal_g=_tg_fin, forecast_yrs=_fy_fin,
                        sym=fin_sym, fx=fin_fx,
                        portfolio_size=st.session_state.get("portfolio_capital", 10_000_000),
                    )
                    _buf2 = _io2.BytesIO()
                    _wb2.save(_buf2)
                    st.download_button(
                        "📥 Download Full Financial Model (Excel)",
                        data=_buf2.getvalue(),
                        file_name=f"{fin_ticker}_FinancialModel_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width='content',
                    )
                else:
                    st.info("Run a full analysis in the Single Stock tab first to enable Excel export.", icon="ℹ️")
            except Exception as _ex_fin:
                st.info("Run a full analysis in the Single Stock tab first to enable Excel export.", icon="ℹ️")
        else:
            st.info(f"📥 Excel export requires a Pro account. {_dl_fin_reason}", icon="🔒")

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


