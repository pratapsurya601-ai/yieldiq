# dashboard/tabs/reverse_dcf_tab.py
# ═══════════════════════════════════════════════════════════════
# Reverse DCF tab — market-implied growth analysis.
# Extracted from app.py  with st.expander("What growth rate...")  block.
# Entry point: render(enriched, price_n, wacc, terminal_g, forecast_yrs, fx, sym)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from screener.reverse_dcf import run_reverse_dcf
from tab_helpers import apply_koyfin, fmts


def render(
    enriched:     dict,
    price_n:      float,
    wacc:         float,
    terminal_g:   float,
    forecast_yrs: int,
    fx:           float,
    sym:          str,
) -> None:
    """Render Reverse DCF content inside an st.expander (caller owns the expander)."""
    try:
        rdcf = run_reverse_dcf(
            enriched=enriched,
            current_price=price_n,
            wacc=wacc,
            terminal_g=terminal_g,
            years=forecast_yrs,
        )
        impl_g   = rdcf.get("implied_growth", 0)
        hist_g   = rdcf.get("historical_growth") or 0
        long_run = rdcf.get("long_run_gdp", 0.025)
        level    = rdcf.get("verdict_level", "")
        colour   = rdcf.get("verdict_colour", "amber")
        ytj      = rdcf.get("years_to_justify")
        summary  = rdcf.get("summary", "")

        COLOUR_MAP = {
            "green": ("#0D7A4E", "#ECFDF5", "#BBF7D0"),
            "amber": ("#B45309", "#FFFBEB", "#FDE68A"),
            "red":   ("#B91C1C", "#FEF2F2", "#FECACA"),
        }
        txt_c, bg_c, bd_c = COLOUR_MAP.get(colour, COLOUR_MAP["amber"])

        # Verdict banner
        st.html(f"""
        <div style="padding:14px 20px;background:{bg_c};
                    border:1.5px solid {bd_c};border-radius:10px;
                    margin-bottom:16px;">
          <div style="font-size:13px;font-weight:700;color:{txt_c};
                      text-transform:uppercase;letter-spacing:.05em;
                      margin-bottom:6px;">
            {level.upper()} — {impl_g*100:.1f}% implied annual FCF growth
          </div>
          <div style="font-size:13px;color:#0F172A;line-height:1.7;">
            {summary}
          </div>
        </div>
        """)

        # Metrics row
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric(
            "Market-implied growth",
            f"{impl_g*100:.1f}% / yr",
            delta=f"{(impl_g - hist_g)*100:+.1f}% above history",
            delta_color="inverse",
            help="The annual FCF growth rate the market is betting on for 10 years"
        )
        rc2.metric(
            "Historical FCF growth",
            f"{hist_g*100:.1f}% / yr",
            help="What this company has actually delivered"
        )
        rc3.metric(
            "FCF yield",
            f"{rdcf.get('fcf_yield', 0)*100:.1f}%",
            help="Free cash flow per share ÷ current price. "
                 "Higher = more cash for every dollar you invest. "
                 "S&P 500 average is ~3.5%."
        )
        rc4.metric(
            "Payback at implied growth",
            f"{rdcf.get('payback_at_implied')} yrs" if rdcf.get('payback_at_implied') else "10+ yrs",
            help="If the company delivers the market-implied growth rate, "
                 "how many years until the DCF value equals today's price. "
                 "Shorter is better."
        )

        # Growth comparison bar chart
        st.html("<div style='margin-top:16px;margin-bottom:8px;"
                    "font-size:12px;font-weight:600;color:#475569;"
                    "text-transform:uppercase;letter-spacing:.07em;'>"
                    "Growth rate comparison</div>")

        rdcf_scenarios = rdcf.get("scenarios", {})
        bar_data = {
            "Scenario": [],
            "Annual FCF Growth (%)": [],
            "IV per share": [],
            "MoS vs price": [],
        }
        scenario_order = [
            ("GDP rate",     "#94A3B8"),
            ("Historical",   "#3B82F6"),
            ("Half implied", "#F59E0B"),
            ("Implied",      "#EF4444"),
        ]
        colours_bar = []
        for label, clr in scenario_order:
            if label in rdcf_scenarios:
                s = rdcf_scenarios[label]
                bar_data["Scenario"].append(label)
                bar_data["Annual FCF Growth (%)"].append(round(s["growth_rate"]*100, 1))
                bar_data["IV per share"].append(round(s["implied_iv"]*fx, 2))
                bar_data["MoS vs price"].append(f"{s['mos']*100:+.1f}%")
                colours_bar.append(clr)

        # plotly.graph_objects already imported as go above
        fig_rdcf = go.Figure()
        fig_rdcf.add_trace(go.Bar(
            x=bar_data["Scenario"],
            y=bar_data["Annual FCF Growth (%)"],
            marker_color=colours_bar,
            text=[f"{v:.1f}%" for v in bar_data["Annual FCF Growth (%)"]],
            textposition="outside",
        ))
        fig_rdcf.add_hline(
            y=impl_g * 100,
            line=dict(color="#EF4444", dash="dot", width=2),
            annotation_text=f"Market implies {impl_g*100:.1f}%",
            annotation_font_color="#EF4444",
        )
        apply_koyfin(fig_rdcf, height=240, extra_kw=dict(
            margin=dict(t=44, b=20, l=20, r=20),
            yaxis=dict(title="Annual FCF Growth (%)", gridcolor="rgba(0,0,0,0.04)",
                       tickfont=dict(color="#64748B")),
            showlegend=False,
        ))
        st.plotly_chart(fig_rdcf, width="stretch",
                        config={"displayModeBar": False})

        # IV table
        st.html("<div style='margin-top:4px;font-size:12px;font-weight:600;"
                    "color:#475569;text-transform:uppercase;letter-spacing:.07em;'>"
                    "Fair value at each growth scenario</div>")
        df_rdcf = pd.DataFrame({
            "Growth scenario": bar_data["Scenario"],
            "Growth rate":     [f"{v:.1f}%" for v in bar_data["Annual FCF Growth (%)"]],
            f"Fair value ({sym})": bar_data["IV per share"],
            "vs today's price":   bar_data["MoS vs price"],
        })
        st.dataframe(df_rdcf, width='stretch', hide_index=True)

    except Exception as _rdcf_err:
        st.warning(f"Reverse DCF could not run: {_rdcf_err}")
