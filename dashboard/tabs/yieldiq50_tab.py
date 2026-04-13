# dashboard/tabs/yieldiq50_tab.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ 50 Index — Top 50 most undervalued high-quality stocks.
# Auto-generated from pre-defined stock universe.
# The performance vs NIFTY 50 is YieldIQ's #1 marketing asset.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


# NIFTY 50 constituents + popular midcaps (pre-defined universe)
YIELDIQ_UNIVERSE = [
    # NIFTY 50
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "BHARTIARTL.NS", "SBIN.NS", "BAJFINANCE.NS",
    "LT.NS", "KOTAKBANK.NS", "HCLTECH.NS", "AXISBANK.NS", "ASIANPAINT.NS",
    "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "TATAMOTORS.NS", "WIPRO.NS",
    "ULTRACEMCO.NS", "NESTLEIND.NS", "NTPC.NS", "M&M.NS", "POWERGRID.NS",
    "ONGC.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "BAJAJFINSV.NS", "ADANIENT.NS",
    "TECHM.NS", "HDFCLIFE.NS", "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS",
    "BRITANNIA.NS", "GRASIM.NS", "COALINDIA.NS", "BPCL.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "INDUSINDBK.NS", "SBILIFE.NS", "TATACONSUM.NS",
    "DABUR.NS", "PIDILITIND.NS", "GODREJCP.NS", "BAJAJ-AUTO.NS",
    # Popular midcaps
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "CHOLAFIN.NS",
    "MUTHOOTFIN.NS", "TATAELXSI.NS", "PIIND.NS", "APOLLOHOSP.NS", "ADANIPORTS.NS", "HINDALCO.NS",
]


def render() -> None:
    """Render the YieldIQ 50 Index page."""

    st.html("""
    <div style="text-align:center;padding:20px 0 16px;">
      <div style="font-size:11px;font-weight:700;color:#1D4ED8;
                  letter-spacing:0.15em;text-transform:uppercase;margin-bottom:8px;">
        YIELDIQ RESEARCH</div>
      <div style="font-size:28px;font-weight:900;color:#0F172A;margin-bottom:8px;">
        YieldIQ 50 Index</div>
      <div style="font-size:14px;color:#64748B;max-width:500px;margin:0 auto;line-height:1.6;">
        The 50 most undervalued high-quality stocks according to our DCF model,
        ranked by margin of safety. Updated with every analysis.
      </div>
    </div>
    """)

    # Try to load cached screener results
    import pandas as pd
    from pathlib import Path

    _results_path = Path(__file__).resolve().parent.parent / "screener_results.csv"
    _has_data = False

    try:
        if _results_path.exists():
            df = pd.read_csv(_results_path)
            _has_data = True
    except Exception:
        pass

    if not _has_data:
        # Show the concept with placeholder data
        st.html("""
        <div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:12px;
                    padding:20px;text-align:center;margin-bottom:16px;">
          <div style="font-size:14px;font-weight:600;color:#1E40AF;margin-bottom:8px;">
            Index building in progress</div>
          <div style="font-size:13px;color:#64748B;line-height:1.6;">
            As users analyse stocks, the YieldIQ 50 automatically populates with
            the best opportunities. Analyse stocks to contribute to the index!
          </div>
        </div>
        """)

        # Show universe stats
        st.html(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px;">
          <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                      padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#0F172A;">{len(YIELDIQ_UNIVERSE)}</div>
            <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;">
              Stocks in Universe</div>
          </div>
          <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                      padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#0F172A;">50</div>
            <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;">
              Index Constituents</div>
          </div>
          <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                      padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#0F172A;">Monthly</div>
            <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.08em;">
              Rebalance Frequency</div>
          </div>
        </div>
        """)

        # Show the stock universe as clickable chips
        st.html('<div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;'
                'letter-spacing:0.14em;margin-bottom:8px;">Stock Universe</div>')

        _chips = ""
        for _t in YIELDIQ_UNIVERSE[:50]:
            _display = _t.replace(".NS", "").replace(".BO", "")
            _chips += (
                f'<span style="display:inline-block;padding:5px 12px;margin:3px;'
                f'background:#F1F5F9;border:1px solid #E2E8F0;border-radius:6px;'
                f'font-size:11px;font-weight:600;color:#475569;cursor:pointer;">'
                f'{_display}</span>'
            )
        st.html(f'<div style="margin-bottom:16px;">{_chips}</div>')

        # Methodology
        st.html("""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                    padding:20px;margin-bottom:16px;">
          <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:12px;">
            📋 Index Methodology</div>
          <div style="font-size:12px;color:#475569;line-height:1.8;">
            <strong>Universe:</strong> NIFTY 50 + select midcaps and global blue chips<br>
            <strong>Ranking:</strong> YieldIQ Composite Score (Valuation 40% + Quality 30% + Growth 20% + Sentiment 10%)<br>
            <strong>Filters:</strong> Piotroski F-Score ≥ 5, Market Cap > ₹5,000 Cr, Positive FCF<br>
            <strong>Rebalance:</strong> Monthly on the 1st trading day<br>
            <strong>Benchmark:</strong> NIFTY 50 Total Return Index
          </div>
        </div>
        """)

        # How to use
        st.html("""
        <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;
                    padding:16px 20px;">
          <div style="font-size:12px;font-weight:700;color:#166534;margin-bottom:6px;">
            💡 How to use the YieldIQ 50</div>
          <div style="font-size:12px;color:#14532D;line-height:1.7;">
            1. Stocks ranked highest have the best combination of value + quality<br>
            2. Use as a starting point for research — not as a buy list<br>
            3. Compare monthly performance vs NIFTY 50 to validate the model<br>
            4. Green = undervalued by model, Red = overvalued by model
          </div>
        </div>
        """)

    else:
        # Show actual data
        st.dataframe(
            df.head(50),
            use_container_width=True,
            hide_index=True,
        )

    # Disclaimer
    st.html("""
    <div style="margin-top:16px;padding:10px 16px;background:#FFFBEB;border:1px solid #FDE68A;
                border-radius:8px;font-size:10px;color:#92400E;text-align:center;">
      The YieldIQ 50 is a model-generated research index for educational purposes only.
      It is NOT investment advice. Past model performance does not predict future results.
      YieldIQ is not registered with SEBI as an investment adviser.
    </div>
    """)
