"""dashboard/tabs/guide_tab.py — Guide / About tab."""
from __future__ import annotations
import streamlit as st
from ui.helpers import ccard, ccard_end


def render_guide_tab(tab) -> None:
    """Render the Guide & About tab."""
    with tab:
        a1, a2 = st.columns([3, 2])

        with a1:
            st.html("""
            <div style="background:linear-gradient(135deg,#F8FAFC,#F4F6F9);border:1px solid #E2E8F0;
                        border-radius:12px;padding:22px;margin-bottom:14px;">
              <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:14px;">⚙️ How it works</div>
            """)
            features = [
                ("Automatic return rate calculation",  "We use market data to figure out what return rate to expect from a stock (no guesswork needed)", "#3b82f6"),
                ("3 outcome scenarios",                "We model a pessimistic, a likely, and an optimistic case for every stock", "#f59e0b"),
                ("Realistic growth modelling",         "Growth rates gradually slow down over time — just like real businesses", "#8b5cf6"),
                ("Bank stocks handled separately",     "Cash-flow models don't work well for banks — we flag these automatically", "#10b981"),
                ("Quality filter",                     "Low-margin businesses are filtered out to avoid false 'good buy' signals", "#ef4444"),
                ("Currency auto-detection",            "Indian IT companies that report in USD (INFY, WIPRO, etc.) are automatically adjusted", "#06b6d4"),
                ("Model Price Levels",                 "Model-estimated entry price, 12-month fair value, and risk range — for research purposes only", "#10b981"),
                ("Download report",                    "Download a full analysis report as a text file for any stock you've analysed", "#3b82f6"),
            ]
            for title, desc, color in features:
                st.html(f"""
                <div style="display:flex;gap:12px;margin-bottom:10px;padding:12px 14px;
                            background:#F4F6F9;border:1px solid #E2E8F0;border-radius:8px;
                            border-left:3px solid {color};">
                  <div>
                    <div style="font-weight:600;color:#1E293B;font-size:12px;margin-bottom:2px;">{title}</div>
                    <div style="color:#475569;font-size:12px;line-height:1.6;">{desc}</div>
                  </div>
                </div>
                """)
            st.html("</div>")

        with a2:
            st.html("""
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:16px;margin-bottom:12px;">
              <div style="font-size:12px;font-weight:700;color:#0F172A;margin-bottom:12px;">What our model signals mean</div>
            """)
            for human_label, internal, cond, color, bg in [
                ("📊 Trading below DCF fair value", "Undervalued 🟢",    "Model IV > market price by 20%+",  "#0D7A4E","#F0FDF4"),
                ("📉 Slight discount to model IV",  "Near Fair Value 🟡","Model IV > market price by 5–20%", "#B45309","#FFFBEB"),
                ("⚖️ Near DCF fair value",           "Fairly Valued 🔵",  "Market price ≈ model IV",          "#1D4ED8","#EFF6FF"),
                ("📈 Trading above DCF fair value", "Overvalued 🔴",     "Market price > model IV",          "#B91C1C","#FEF2F2"),
                ("⏳ Not applicable",               "N/A",               "Bank/loss-making company",         "#64748b","#F8FAFC"),
            ]:
                st.html(f"""
                <div style="padding:10px 12px;background:{bg};border:1px solid {color}30;
                            border-radius:7px;margin-bottom:6px;">
                  <div style="font-weight:700;color:{color};font-size:13px;">{human_label}</div>
                  <div style="font-size:11px;color:{color};opacity:0.8;margin-top:2px;">{cond}</div>
                </div>
                """)
            st.html("</div>")

        st.html("""
        <div style="margin-top:8px;padding:14px 20px;background:#FFFBEB;border:1px solid #FDE68A;
                    border-radius:10px;">
          <div style="font-weight:700;color:#f59e0b;font-size:12px;margin-bottom:3px;">⚠️ Important Disclosure</div>
          <div style="color:#B45309;font-size:12px;line-height:1.7;">
            <strong>For informational and educational purposes only. Not investment advice.</strong>
            This tool provides quantitative DCF analysis for research purposes. It does not constitute
            a recommendation to buy, sell, or hold any security. Past performance is not indicative of
            future results. All valuations are estimates based on publicly available data and model
            assumptions that may prove incorrect. Users should conduct their own due diligence and
            consult a registered investment advisor (RIA) or licensed financial professional before
            making any investment decisions. This platform is not registered as an investment advisor
            under the Investment Advisers Act of 1940 or any state securities law.
            Data sourced from Yahoo Finance — accuracy not guaranteed.
          </div>
        </div>
        """)
