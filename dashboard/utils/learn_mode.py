# dashboard/utils/learn_mode.py
# ═══════════════════════════════════════════════════════════════
# Learn Mode — plain-English explanations below every metric.
# Usage: learn_tip("wacc") or learn_tip("custom", "Your text here")
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


TIPS = {
    "wacc": "This is the minimum return the company needs to satisfy both lenders and shareholders. Lower = cheaper to fund growth.",
    "mos": "Margin of Safety — how far below our estimated fair value the stock currently trades. Higher = more cushion if our model is wrong.",
    "fcf": "Free Cash Flow — real cash left after running the business and maintaining assets. This is what funds dividends, buybacks, and growth.",
    "terminal_value": "The estimated value of all cash flows beyond our 10-year forecast. If this is over 70% of total value, treat the result cautiously.",
    "piotroski": "A 0–9 score measuring financial health across profitability, leverage, and efficiency. 7+ is strong. Below 3 is a warning.",
    "moat": "Competitive advantage — how protected the business is from competitors eating its profits. Wide moat = durable advantage.",
    "beta": "How much this stock moves relative to the market. Beta 1.5 = moves 50% more than the market in both directions.",
    "ev_ebitda": "Enterprise Value divided by earnings before interest, tax, depreciation. A valuation multiple — lower than peers = potentially cheaper.",
    "dcf": "Discounted Cash Flow — we forecast the company's future cash, then calculate what that cash is worth in today's money.",
    "monte_carlo": "We run 1,000 different scenarios with varied assumptions to show a range of possible fair values, not just one number.",
    "score": "YieldIQ Score combines valuation (40%), business quality (30%), growth (20%), and market sentiment (10%) into one number.",
    "confidence": "How reliable our data and model inputs are for this stock. Low confidence = treat the output as directional only.",
    "reverse_dcf": "Instead of calculating fair value, we ask: what growth rate does the current stock price assume? Higher than realistic = overpriced.",
    "patience_meter": "Based on current price vs fair value and growth rate, we estimate how long until the stock might reach fair value.",
    "earnings_quality": "Are the profits real? We check if earnings are backed by actual cash, or inflated by accounting choices.",
    "pe_ratio": "Price-to-Earnings — how many years of current earnings you're paying for. Lower than peers = potentially cheaper.",
    "roe": "Return on Equity — how much profit the company generates from shareholders' money. Higher = more efficient management.",
    "debt_equity": "How much debt the company has relative to shareholders' equity. Above 2x = high leverage, more risk.",
    "dividend_yield": "Annual dividend as a percentage of stock price. Compare to risk-free rate (FD rate) to see if it's worth it.",
    "risk_reward": "Ratio of potential upside (to bull case) vs downside (to bear case). Above 2:1 = favourable bet.",
    "red_flag": "Automated checks for suspicious patterns: revenue growing but cash declining, insider selling, accounting red flags.",
    "sector_pe": "How this stock's P/E compares to the average for its sector. Premium = market expects more growth.",
    "volatility": "How much the stock price swings day to day. High volatility = bigger potential gains AND losses.",
    "cash_conversion": "FCF divided by net income. Above 1.0 = the company converts more than 100% of profits to cash. Very healthy.",
    "growth_runway": "How fast the company is growing revenue and cash flow. Hypergrowth (>20%) commands premium valuations.",
}


def learn_tip(key: str, custom_text: str = None):
    """
    Render a Learn Mode tooltip if Learn Mode is enabled.
    Uses TIPS dict by key, or custom_text if provided.
    Renders nothing if Learn Mode is off.
    """
    if not st.session_state.get("learn_mode", False):
        return
    text = custom_text or TIPS.get(key)
    if not text:
        return
    st.html(
        f'<div style="font-size:11px;color:#64748B;'
        f'background:rgba(29,78,216,0.04);border-left:2px solid rgba(29,78,216,0.3);'
        f'padding:4px 10px;border-radius:0 4px 4px 0;'
        f'margin-top:2px;margin-bottom:6px;line-height:1.5;">'
        f'💡 {text}</div>'
    )
