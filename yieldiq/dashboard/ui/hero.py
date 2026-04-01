"""dashboard/ui/hero.py
Landing page hero section shown when no stock has been analysed yet.
Call render_hero() from the stock analysis tab before the analyse button logic.
"""
from __future__ import annotations
import streamlit as st


def render_hero() -> None:
    """Render the animated hero landing block."""
    st.html("""
<style>
/* ── Hero gradient animation ────────────────────────────────── */
@keyframes yiq-hero-shift {
  0%   { background-position: 0%   50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0%   50%; }
}
@keyframes yiq-fade-up {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0);    }
}
.yiq-hero {
  margin-top: 24px;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(135deg, #0d1f35 0%, #0f2537 40%, #0a3350 70%, #0d2d48 100%);
  background-size: 300% 300%;
  animation: yiq-hero-shift 10s ease infinite;
  padding: 52px 48px 40px;
  text-align: center;
  position: relative;
}
/* Subtle grid overlay */
.yiq-hero::before {
  content: "";
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(0,180,216,0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,180,216,0.06) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}
/* Glow orb */
.yiq-hero::after {
  content: "";
  position: absolute;
  top: -60px; left: 50%; transform: translateX(-50%);
  width: 400px; height: 280px;
  background: radial-gradient(ellipse, rgba(0,180,216,0.18) 0%, transparent 70%);
  pointer-events: none;
}
.yiq-hero-inner {
  position: relative; z-index: 2;
  animation: yiq-fade-up 0.6s ease both;
}
.yiq-hero-eyebrow {
  display: inline-block;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: #00b4d8;
  background: rgba(0,180,216,0.12);
  border: 1px solid rgba(0,180,216,0.3);
  border-radius: 20px;
  padding: 4px 14px;
  margin-bottom: 20px;
}
.yiq-hero-headline {
  font-family: 'Barlow Condensed', 'Inter', sans-serif;
  font-size: 42px; font-weight: 700; line-height: 1.15;
  color: #FFFFFF;
  letter-spacing: -0.01em;
  margin-bottom: 16px;
  max-width: 680px; margin-left: auto; margin-right: auto;
}
.yiq-hero-headline span {
  background: linear-gradient(90deg, #00b4d8, #38e8ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.yiq-hero-sub {
  font-size: 15px; font-weight: 400; line-height: 1.7;
  color: rgba(255,255,255,0.65);
  max-width: 520px; margin: 0 auto 36px;
}
/* Value prop cards */
.yiq-cards {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  max-width: 760px;
  margin: 0 auto 32px;
}
.yiq-card {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 18px 16px;
  text-align: left;
  transition: background 0.2s, border-color 0.2s;
}
.yiq-card:hover {
  background: rgba(0,180,216,0.1);
  border-color: rgba(0,180,216,0.35);
}
.yiq-card-icon {
  font-size: 22px; margin-bottom: 8px; display: block;
}
.yiq-card-title {
  font-size: 13px; font-weight: 600; color: #FFFFFF;
  margin-bottom: 4px; letter-spacing: 0.01em;
}
.yiq-card-desc {
  font-size: 11px; color: rgba(255,255,255,0.5);
  line-height: 1.55;
}
/* Trust bar */
.yiq-trust {
  font-size: 11px; color: rgba(255,255,255,0.35);
  letter-spacing: 0.06em;
  margin-bottom: 24px;
}
.yiq-trust strong {
  color: rgba(255,255,255,0.55);
  font-weight: 500;
}
/* Ticker examples */
.yiq-tickers {
  display: flex; align-items: center; justify-content: center;
  flex-wrap: wrap; gap: 6px;
  margin-top: 4px;
}
.yiq-ticker-chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; font-weight: 500;
  color: rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px;
  padding: 3px 9px;
}
.yiq-ticker-sep {
  color: rgba(255,255,255,0.2);
  font-size: 11px;
}
.yiq-ticker-label {
  font-size: 11px; color: rgba(255,255,255,0.3);
  margin-right: 4px;
}
</style>

<div class="yiq-hero">
  <div class="yiq-hero-inner">

    <div class="yiq-hero-eyebrow">Institutional-Grade Stock Analysis</div>

    <div class="yiq-hero-headline">
      Know What a Stock Is<br><span>Really Worth</span> — Before You Invest
    </div>

    <div class="yiq-hero-sub">
      DCF-powered intrinsic value, margin of safety, scenario analysis,
      and quality scoring — in plain English.
    </div>

    <div class="yiq-cards">
      <div class="yiq-card">
        <span class="yiq-card-icon">📊</span>
        <div class="yiq-card-title">Intrinsic Value</div>
        <div class="yiq-card-desc">DCF-based fair value with margin of safety and 3 scenario analysis</div>
      </div>
      <div class="yiq-card">
        <span class="yiq-card-icon">🏢</span>
        <div class="yiq-card-title">Company Quality</div>
        <div class="yiq-card-desc">Revenue trends, profit margins, debt levels and earnings consistency</div>
      </div>
      <div class="yiq-card">
        <span class="yiq-card-icon">⚡</span>
        <div class="yiq-card-title">Live Data</div>
        <div class="yiq-card-desc">Real-time price vs estimated value — updated every minute</div>
      </div>
    </div>

    <div class="yiq-trust">
      <strong>Trusted analytical framework</strong> · DCF · Economic Moat · Monte Carlo · Piotroski Score
    </div>

    <div class="yiq-tickers">
      <span class="yiq-ticker-label">Try:</span>
      <span class="yiq-ticker-chip">TCS.NS</span>
      <span class="yiq-ticker-chip">RELIANCE.NS</span>
      <span class="yiq-ticker-chip">INFY.NS</span>
      <span class="yiq-ticker-sep">·</span>
      <span class="yiq-ticker-chip">AAPL</span>
      <span class="yiq-ticker-chip">MSFT</span>
      <span class="yiq-ticker-chip">NVDA</span>
      <span class="yiq-ticker-chip">GOOGL</span>
    </div>

  </div>
</div>
    """)
