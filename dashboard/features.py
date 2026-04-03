# dashboard/features.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — 4 Bloomberg-Grade Feature Upgrades
# ═══════════════════════════════════════════════════════════════
#
# FEATURE 1: Real-time price refresh (auto-refreshes every 60s)
# FEATURE 2: Analyst consensus estimates (targets, ratings, EPS)
# FEATURE 3: Earnings calendar with surprise history
# FEATURE 4: Multi-stock comparison watchlist
#
# All powered by yfinance — zero extra API keys needed.
#
# USAGE IN app.py:
#   from features import (
#       render_live_price_header,
#       render_analyst_consensus,
#       render_earnings_calendar,
#       render_comparison_watchlist,
#   )
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import time
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import yfinance as yf


# ────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────

def _safe(v, default=0.0):
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def _fmt_price(v, sym="$"):
    return f"{sym}{_safe(v):,.2f}"

def _fmt_pct(v):
    v = _safe(v)
    return f"{v:+.1f}%" if v != 0 else "0.0%"

def _clr(v, threshold=0):
    v = _safe(v)
    return "#059669" if v > threshold else "#DC2626" if v < threshold else "#64748B"

def _sig_clr(sig: str) -> str:
    s = (sig or "").upper()
    if "BUY"   in s: return "#059669"
    if "SELL"  in s: return "#DC2626"
    if "WATCH" in s: return "#D97706"
    if "HOLD"  in s: return "#2563EB"
    return "#64748B"

def _badge(text, color):
    return (
        f'<span style="display:inline-block;padding:2px 8px;'
        f'background:{color}18;border:1px solid {color}44;'
        f'border-radius:4px;font-size:10px;font-weight:700;'
        f'color:{color};font-family:"JetBrains Mono",monospace;'
        f'letter-spacing:0.06em;">{text}</span>'
    )

def _row(label, value, color=None):
    vc = f'color:{color};' if color else ''
    return (
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;padding:5px 0;'
        f'border-bottom:1px solid #F1F5F9;">'
        f'<span style="font-size:11px;color:#94A3B8;">{label}</span>'
        f'<span style="font-size:11px;font-weight:600;{vc}'
        f'font-family:"JetBrains Mono",monospace;">{value}</span>'
        f'</div>'
    )

def _section(title, accent="#1D4ED8"):
    return (
        f'<div style="font-size:9px;font-weight:700;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{accent};'
        f'margin:14px 0 8px;display:flex;align-items:center;gap:6px;">'
        f'<span style="display:inline-block;width:3px;height:12px;'
        f'background:{accent};border-radius:2px;"></span>{title}</div>'
    )


# ════════════════════════════════════════════════════════════════
# FEATURE 1 — REAL-TIME PRICE REFRESH
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=45, show_spinner=False)
def _fetch_live_price(ticker: str) -> dict:
    """Fetch current price + day change. Cached 45s, auto-invalidates."""
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price  = _safe(getattr(fi, "last_price", 0) or getattr(fi, "regular_market_price", 0))
        prev   = _safe(getattr(fi, "previous_close", 0))
        change = price - prev
        pct    = (change / prev * 100) if prev > 0 else 0
        volume = _safe(getattr(fi, "last_volume", 0))
        high   = _safe(getattr(fi, "day_high", 0))
        low    = _safe(getattr(fi, "day_low", 0))
        return {
            "price": price, "prev_close": prev,
            "change": change, "change_pct": pct,
            "volume": volume, "day_high": high, "day_low": low,
            "fetched_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return {}


def render_live_price_header(
    ticker: str,
    sym: str = "$",
    fx: float = 1.0,
    refresh_every: int = 60,
) -> None:
    """
    Renders a live price header that auto-refreshes every `refresh_every` seconds.
    Place this at the TOP of your analysis results, before your KPI cards.

    Args:
        ticker:        The ticker string, e.g. "TCS.NS"
        sym:           Currency symbol, e.g. "$" or "₹"
        fx:            FX conversion factor (native → display currency)
        refresh_every: Auto-refresh interval in seconds (default 60)
    """
    # ── Auto-refresh logic ───────────────────────────────────
    if "live_price_last_refresh" not in st.session_state:
        st.session_state["live_price_last_refresh"] = 0
    if "live_price_ticker" not in st.session_state:
        st.session_state["live_price_ticker"] = ""

    now = time.time()
    ticker_changed = st.session_state["live_price_ticker"] != ticker
    time_elapsed   = now - st.session_state["live_price_last_refresh"] > refresh_every

    if ticker_changed or time_elapsed:
        st.session_state["live_price_last_refresh"] = now
        st.session_state["live_price_ticker"] = ticker
        _fetch_live_price.clear()   # force cache refresh

    live = _fetch_live_price(ticker)
    if not live:
        return

    price    = live["price"] * fx
    change   = live["change"] * fx
    pct      = live["change_pct"]
    high     = live["day_high"] * fx
    low      = live["day_low"] * fx
    volume   = live["volume"]
    fetched  = live["fetched_at"]

    is_pos   = pct >= 0
    chg_clr  = "#059669" if is_pos else "#DC2626"
    chg_bg   = "#ECFDF5" if is_pos else "#FEF2F2"
    arrow    = "▲" if is_pos else "▼"

    # Time to next refresh
    elapsed  = int(now - st.session_state["live_price_last_refresh"])
    next_in  = max(0, refresh_every - elapsed)

    col_price, col_refresh = st.columns([6, 1])

    with col_price:
        st.html(f"""
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;
                    padding:12px 16px;background:#F8FAFC;
                    border:1px solid #E2E8F0;border-radius:8px;margin-bottom:8px;">

          <!-- Ticker + Price -->
          <div style="display:flex;align-items:baseline;gap:10px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                         font-weight:700;color:#94A3B8;letter-spacing:0.08em;">{ticker}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:28px;
                         font-weight:400;color:#0F172A;letter-spacing:-0.5px;">{sym}{price:,.2f}</span>
          </div>

          <!-- Change badge -->
          <div style="display:flex;align-items:center;gap:6px;padding:5px 10px;
                      background:{chg_bg};border-radius:6px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                         font-weight:700;color:{chg_clr};">{arrow} {sym}{abs(change):,.2f}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;
                         font-weight:600;color:{chg_clr};">({pct:+.2f}%)</span>
          </div>

          <!-- Day range -->
          <div style="display:flex;gap:12px;">
            <div>
              <div style="font-size:8px;color:#94A3B8;letter-spacing:0.1em;text-transform:uppercase;">Day Low</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#DC2626;font-weight:500;">{sym}{low:,.2f}</div>
            </div>
            <div>
              <div style="font-size:8px;color:#94A3B8;letter-spacing:0.1em;text-transform:uppercase;">Day High</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#059669;font-weight:500;">{sym}{high:,.2f}</div>
            </div>
            <div>
              <div style="font-size:8px;color:#94A3B8;letter-spacing:0.1em;text-transform:uppercase;">Volume</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#475569;font-weight:500;">{volume/1e6:.1f}M</div>
            </div>
          </div>

          <!-- Live indicator -->
          <div style="margin-left:auto;display:flex;align-items:center;gap:8px;">
            <div style="display:flex;align-items:center;gap:5px;
                        padding:4px 8px;background:rgba(5,150,105,0.08);
                        border:1px solid rgba(5,150,105,0.2);border-radius:4px;">
              <div style="width:5px;height:5px;border-radius:50%;background:#059669;
                          animation:pulse 2s ease-in-out infinite;"></div>
              <span style="font-size:9px;font-weight:700;color:#059669;letter-spacing:0.1em;">LIVE</span>
            </div>
            <div style="font-size:9px;color:#94A3B8;">Updated {fetched} · Next in {next_in}s</div>
          </div>

        </div>
        <style>@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.4}}}}</style>
        """)

    with col_refresh:
        if st.button("↻ Refresh", key=f"refresh_btn_{ticker}", width='stretch'):
            st.session_state["live_price_last_refresh"] = 0
            _fetch_live_price.clear()
            st.rerun()

    # Auto-rerun when refresh interval expires
    if next_in <= 2:
        time.sleep(1)
        st.rerun()


# ════════════════════════════════════════════════════════════════
# FEATURE 2 — ANALYST CONSENSUS ESTIMATES
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_analyst_data(ticker: str) -> dict:
    """Fetch analyst price targets, EPS estimates, and rating changes."""
    result = {
        "targets":    {},
        "eps_est":    {},
        "rev_est":    {},
        "ratings":    pd.DataFrame(),
        "rec_trend":  {},
    }
    try:
        t = yf.Ticker(ticker)

        # Price targets
        apt = t.analyst_price_targets
        if apt and isinstance(apt, dict):
            result["targets"] = {
                "mean":   _safe(apt.get("mean")),
                "median": _safe(apt.get("median")),
                "high":   _safe(apt.get("high")),
                "low":    _safe(apt.get("low")),
                "count":  int(apt.get("numberOfAnalysts", 0)),
            }

        # EPS estimates (current year / next year)
        try:
            ae = t.earnings_estimate
            if ae is not None and not ae.empty:
                result["eps_est"] = ae.to_dict()
        except Exception:
            pass

        # Revenue estimates
        try:
            re = t.revenue_estimate
            if re is not None and not re.empty:
                result["rev_est"] = re.to_dict()
        except Exception:
            pass

        # Recent upgrades/downgrades
        try:
            ud = t.upgrades_downgrades
            if ud is not None and not ud.empty:
                ud = ud.reset_index()
                if "GradeDate" in ud.columns:
                    ud["GradeDate"] = pd.to_datetime(ud["GradeDate"]).dt.strftime("%d %b %Y")
                result["ratings"] = ud.head(10)
        except Exception:
            pass

        # Recommendation trend (Buy/Hold/Sell counts)
        try:
            rt = t.recommendations_summary
            if rt is not None and not rt.empty:
                result["rec_trend"] = rt.to_dict("records")
        except Exception:
            pass

    except Exception:
        pass
    return result


def render_analyst_consensus(
    ticker: str,
    current_price: float,
    sym: str = "$",
    fx: float = 1.0,
    raw_data: dict = None,
) -> None:
    """
    Renders a Bloomberg-style analyst consensus panel with:
    - Price target distribution (mean/median/high/low vs current)
    - EPS estimates current + next year
    - Recent rating changes (upgrades/downgrades)
    - Buy/Hold/Sell recommendation count

    Place this inside your ccard() section after KPI cards.
    """
    # Use pre-fetched Finnhub data from collector if available
    if raw_data and raw_data.get("finnhub_price_target"):
        tgt = raw_data["finnhub_price_target"]
        ratings_df = pd.DataFrame()   # upgrades/downgrades not in collector
        rec_trend  = raw_data.get("finnhub_rec_trend", [])
    else:
        data = _fetch_analyst_data(ticker)
        tgt  = data["targets"]
        ratings_df = data["ratings"]
        rec_trend  = data["rec_trend"]

    if not tgt and ratings_df.empty:
        st.info("No analyst data available for this ticker via yfinance.")
        return

    # ── Price Target Visual ──────────────────────────────────
    if tgt and tgt.get("mean"):
        mean   = tgt["mean"]   * fx
        median = tgt["median"] * fx
        high   = tgt["high"]   * fx
        low    = tgt["low"]    * fx
        count  = tgt["count"]
        upside = (mean - current_price) / current_price * 100 if current_price > 0 else 0
        upside_clr = _clr(upside)

        # Progress bar: where is current price in low→high range?
        rng = high - low
        pos_pct = max(0, min(100, (current_price - low) / rng * 100)) if rng > 0 else 50

        st.html(f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
                    padding:16px 20px;margin-bottom:8px;">
          {_section(f"ANALYST PRICE TARGETS — {count} ANALYSTS", "#2563EB")}

          <!-- Target range bar -->
          <div style="margin-bottom:14px;">
            <div style="display:flex;justify-content:space-between;font-size:9px;
                        color:#94A3B8;margin-bottom:4px;font-family:'JetBrains Mono',monospace;">
              <span>LOW {sym}{low:,.2f}</span>
              <span style="color:#2563EB;">MEAN {sym}{mean:,.2f}</span>
              <span>HIGH {sym}{high:,.2f}</span>
            </div>
            <div style="position:relative;height:8px;background:#F1F5F9;border-radius:4px;">
              <!-- Range fill -->
              <div style="position:absolute;height:100%;background:linear-gradient(90deg,#BFDBFE,#3B82F6);
                          border-radius:4px;left:0;right:0;opacity:0.3;"></div>
              <!-- Median marker -->
              <div style="position:absolute;top:-3px;width:3px;height:14px;background:#2563EB;
                          border-radius:2px;left:{max(0,min(95,(median-low)/rng*100) if rng>0 else 50):.0f}%;"></div>
              <!-- Current price marker -->
              <div style="position:absolute;top:-4px;width:4px;height:16px;background:#0F172A;
                          border-radius:2px;left:{pos_pct:.0f}%;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:4px;">
              <span style="font-size:9px;color:#94A3B8;">Low</span>
              <div style="display:flex;align-items:center;gap:4px;">
                <span style="font-size:10px;color:#0F172A;font-weight:600;">Current: {sym}{current_price:,.2f}</span>
                <span style="font-size:10px;font-weight:700;color:{upside_clr};">
                  ({upside:+.1f}% to mean target)
                </span>
              </div>
              <span style="font-size:9px;color:#94A3B8;">High</span>
            </div>
          </div>

          <!-- Stats row -->
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
            {"".join([
              f'<div style="background:#F8FAFC;padding:8px 10px;border-radius:6px;border:1px solid #E2E8F0;">'
              f'<div style="font-size:8px;color:#94A3B8;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:3px;">{lbl}</div>'
              f'<div style="font-size:14px;font-weight:500;color:{clr};font-family:"JetBrains Mono",monospace;">{val}</div>'
              f'</div>'
              for lbl, val, clr in [
                ("Mean Target",   f"{sym}{mean:,.2f}",   _clr(mean - current_price)),
                ("Median Target", f"{sym}{median:,.2f}", _clr(median - current_price)),
                ("Upside",        f"{upside:+.1f}%",     upside_clr),
                ("# Analysts",    str(count),            "#2563EB"),
              ]
            ])}
          </div>
        </div>
        """)

    # ── Recommendation Trend ─────────────────────────────────
    if rec_trend:
        try:
            latest = rec_trend[0] if rec_trend else {}
            strong_buy  = int(latest.get("strongBuy",  latest.get("strongbuy",  0)))
            buy         = int(latest.get("buy",         0))
            hold        = int(latest.get("hold",        0))
            sell        = int(latest.get("sell",        0))
            strong_sell = int(latest.get("strongSell", latest.get("strongsell", 0)))
            total = strong_buy + buy + hold + sell + strong_sell or 1

            def bar(v, clr):
                w = v / total * 100
                return (
                    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                    f'<div style="width:60px;font-size:9px;color:#64748B;text-align:right;">'
                    f'{"Strong Buy" if clr=="#059669" and v==strong_buy else "Buy" if clr=="#059669" else "Hold" if clr=="#D97706" else "Sell" if v==sell else "Strong Sell"}</div>'
                    f'<div style="flex:1;height:6px;background:#F1F5F9;border-radius:3px;overflow:hidden;">'
                    f'<div style="height:100%;width:{w:.0f}%;background:{clr};border-radius:3px;"></div></div>'
                    f'<div style="font-size:9px;font-weight:700;color:{clr};width:20px;">{v}</div>'
                    f'</div>'
                )

            st.html(f"""
            <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
                        padding:14px 20px;margin-bottom:8px;">
              {_section("ANALYST CONSENSUS — Source: third-party analyst data", "#059669")}
              {bar(strong_buy,  "#059669")}
              {bar(buy,         "#34D399")}
              {bar(hold,        "#D97706")}
              {bar(sell,        "#F87171")}
              {bar(strong_sell, "#DC2626")}
              <div style="font-size:9px;color:#94A3B8;margin-top:8px;font-style:italic;">
                Source: Analyst consensus data (Finnhub/Yahoo Finance). Not YieldIQ&#39;s own recommendation.
              </div>
            </div>
            """)
        except Exception:
            pass

    # ── Recent Ratings Changes ────────────────────────────────
    if not ratings_df.empty:
        rows_html = ""
        for _, r in ratings_df.head(8).iterrows():
            action   = str(r.get("Action", r.get("action", ""))).strip()
            firm     = str(r.get("Firm", r.get("firm", "—"))).strip()
            to_grade = str(r.get("ToGrade", r.get("toGrade", ""))).strip()
            fr_grade = str(r.get("FromGrade", r.get("fromGrade", ""))).strip()
            date_s   = str(r.get("GradeDate", "")).strip()

            action_up = action.upper()
            if "UPGRADE" in action_up or "INIT" in action_up or "REITERATED" in action_up:
                a_clr = "#059669"; a_bg = "#ECFDF5"
            elif "DOWNGRADE" in action_up:
                a_clr = "#DC2626"; a_bg = "#FEF2F2"
            else:
                a_clr = "#D97706"; a_bg = "#FFFBEB"

            change_str = f"{fr_grade} → {to_grade}" if fr_grade and to_grade and fr_grade != to_grade else to_grade

            rows_html += f"""
            <tr>
              <td style="padding:6px 10px;font-size:10px;color:#64748B;">{date_s}</td>
              <td style="padding:6px 10px;font-size:10px;font-weight:600;color:#0F172A;">{firm}</td>
              <td style="padding:6px 10px;">
                <span style="padding:2px 7px;background:{a_bg};border-radius:4px;
                             font-size:9px;font-weight:700;color:{a_clr};">{action}</span>
              </td>
              <td style="padding:6px 10px;font-size:10px;color:#475569;font-family:'JetBrains Mono',monospace;">{change_str}</td>
            </tr>"""

        st.html(f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
                    padding:14px 20px;margin-bottom:8px;">
          {_section("RECENT RATING CHANGES", "#7C3AED")}
          <div style="overflow:hidden;border-radius:6px;border:1px solid #F1F5F9;">
            <table style="width:100%;border-collapse:collapse;">
              <thead>
                <tr style="background:#F8FAFC;">
                  <th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;
                             text-transform:uppercase;color:#94A3B8;text-align:left;">Date</th>
                  <th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;
                             text-transform:uppercase;color:#94A3B8;text-align:left;">Firm</th>
                  <th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;
                             text-transform:uppercase;color:#94A3B8;text-align:left;">Action</th>
                  <th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;
                             text-transform:uppercase;color:#94A3B8;text-align:left;">Rating</th>
                </tr>
              </thead>
              <tbody>{rows_html}</tbody>
            </table>
          </div>
        </div>
        """)


# ════════════════════════════════════════════════════════════════
# FEATURE 3 — EARNINGS CALENDAR + SURPRISE HISTORY
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_earnings_data(ticker: str) -> dict:
    """Fetch next earnings date and historical EPS surprise history."""
    result = {"next_date": None, "history": pd.DataFrame(), "calendar": {}}
    try:
        t = yf.Ticker(ticker)

        # Next earnings date
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                result["calendar"] = cal
                ed = cal.get("Earnings Date", cal.get("earningsDate"))
                if ed is not None:
                    if hasattr(ed, "__len__") and len(ed) > 0:
                        result["next_date"] = pd.to_datetime(ed[0])
                    else:
                        result["next_date"] = pd.to_datetime(ed)
        except Exception:
            pass

        # Historical EPS surprises
        try:
            hist = t.earnings_history
            if hist is not None and not hist.empty:
                hist = hist.reset_index()
                result["history"] = hist
        except Exception:
            pass

        if result["history"].empty:
            try:
                dates = t.earnings_dates
                if dates is not None and not dates.empty:
                    dates = dates.reset_index()
                    result["history"] = dates
            except Exception:
                pass

    except Exception:
        pass
    return result


def render_earnings_calendar(ticker: str, sym: str = "$", raw_data: dict = None) -> None:
    """
    Renders:
    - Next earnings date countdown
    - EPS estimate vs actual history with beat/miss visualization
    - Surprise % trend chart
    """
    # Use pre-fetched Finnhub data from collector if available
    if raw_data and raw_data.get("finnhub_earnings"):
        # Convert Finnhub earnings format to our expected format
        fh_earn = raw_data["finnhub_earnings"]
        hist_rows = []
        for q in fh_earn:
            hist_rows.append({
                "Date":        q.get("period", ""),
                "Reported EPS":float(q.get("actual",   0)),
                "EPS Estimate":float(q.get("estimate",  0)),
                "Surprise(%)": float(q.get("surprise_pct", 0)),
            })
        hist = pd.DataFrame(hist_rows) if hist_rows else pd.DataFrame()

        fh_next = raw_data.get("finnhub_next_earnings", {})
        nxt = pd.to_datetime(fh_next.get("date", ""), errors="coerce") if fh_next.get("date") else None
        cal = {
            "EPS Estimate":     fh_next.get("eps_estimate", 0),
            "Revenue Estimate": fh_next.get("revenue_estimate", 0),
        }
    else:
        data  = _fetch_earnings_data(ticker)
        nxt   = data["next_date"]
        hist  = data["history"]
        cal   = data["calendar"]

    # ── Next Earnings Countdown ──────────────────────────────
    cal_html = ""
    if nxt is not None:
        try:
            days_to = (nxt.date() - datetime.today().date()).days
            if days_to >= 0:
                countdown_clr = "#DC2626" if days_to <= 7 else "#D97706" if days_to <= 30 else "#2563EB"
                countdown_msg = (
                    "THIS WEEK" if days_to <= 7
                    else "THIS MONTH" if days_to <= 30
                    else f"IN {days_to} DAYS"
                )
                eps_est_str = ""
                if cal:
                    eps_est = cal.get("EPS Estimate", cal.get("epsEstimate"))
                    rev_est = cal.get("Revenue Estimate", cal.get("revenueEstimate"))
                    if eps_est:
                        eps_est_str = f" &nbsp;·&nbsp; EPS Est: {sym}{_safe(eps_est):.2f}"
                    if rev_est:
                        rev_f = _safe(rev_est)
                        eps_est_str += f" &nbsp;·&nbsp; Rev Est: {sym}{rev_f/1e9:.2f}B" if rev_f > 1e9 else ""

                cal_html = f"""
                <div style="display:flex;align-items:center;justify-content:space-between;
                            padding:12px 16px;
                            background:linear-gradient(90deg,{countdown_clr}0A,transparent);
                            border:1px solid {countdown_clr}30;border-radius:8px;margin-bottom:8px;">
                  <div style="display:flex;align-items:center;gap:12px;">
                    <div style="font-size:28px;font-weight:300;color:{countdown_clr};
                                font-family:'JetBrains Mono',monospace;line-height:1;">{days_to}</div>
                    <div>
                      <div style="font-size:8px;font-weight:700;letter-spacing:0.14em;
                                  text-transform:uppercase;color:{countdown_clr};">Days to Earnings</div>
                      <div style="font-size:12px;font-weight:600;color:#0F172A;margin-top:2px;">
                        {nxt.strftime("%d %B %Y")}
                        <span style="font-size:10px;color:#94A3B8;margin-left:6px;">{countdown_msg}</span>
                      </div>
                      <div style="font-size:10px;color:#64748B;margin-top:2px;">{eps_est_str}</div>
                    </div>
                  </div>
                  <div style="padding:6px 12px;background:{countdown_clr}18;
                              border:1px solid {countdown_clr}40;border-radius:6px;">
                    <div style="font-size:9px;font-weight:700;color:{countdown_clr};
                                letter-spacing:0.1em;">UPCOMING EARNINGS</div>
                  </div>
                </div>"""
        except Exception:
            pass

    if cal_html:
        st.html(cal_html)

    if hist.empty:
        if not cal_html:
            st.info("No earnings data available for this ticker.")
        return

    # ── Normalise columns ────────────────────────────────────
    col_map = {
        "Reported EPS":  ["reportedEPS", "Reported EPS", "epsActual", "EPS Actual"],
        "EPS Estimate":  ["epsEstimate", "EPS Estimate", "epsestimate"],
        "Surprise(%)":   ["surprisePercent", "Surprise(%)", "epsSurprisePct"],
        "Date":          ["Earnings Date", "Date", "date", "earningsDate"],
    }
    rename = {}
    for target, candidates in col_map.items():
        for c in candidates:
            if c in hist.columns:
                rename[c] = target
                break
    hist = hist.rename(columns=rename)

    # Keep only last 8 quarters
    if "Date" in hist.columns:
        hist["Date"] = pd.to_datetime(hist["Date"], errors="coerce")
        hist = hist.dropna(subset=["Date"]).sort_values("Date").tail(8)
        hist["Date_str"] = hist["Date"].dt.strftime("%b %Y")
    else:
        hist = hist.tail(8)
        hist = hist.reset_index(drop=True)
        hist["Date_str"] = [f"Q{i+1}" for i in range(len(hist))]

    has_actual  = "Reported EPS" in hist.columns
    has_est     = "EPS Estimate" in hist.columns
    has_surp    = "Surprise(%)" in hist.columns

    if not has_actual:
        return

    # ── Beat/Miss Summary ────────────────────────────────────
    if has_actual and has_est:
        hist["beat"] = hist["Reported EPS"].astype(float) > hist["EPS Estimate"].astype(float)
        beats = hist["beat"].sum()
        total = len(hist)
        beat_rate = beats / total * 100

        beat_clr = "#059669" if beat_rate >= 70 else "#D97706" if beat_rate >= 50 else "#DC2626"

        st.html(f"""
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px;">
          <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
                      padding:10px 14px;text-align:center;">
            <div style="font-size:8px;color:#94A3B8;letter-spacing:0.12em;
                        text-transform:uppercase;margin-bottom:4px;">Beat Rate</div>
            <div style="font-size:22px;font-weight:500;color:{beat_clr};
                        font-family:'JetBrains Mono',monospace;">{beat_rate:.0f}%</div>
            <div style="font-size:9px;color:#94A3B8;">{beats}/{total} quarters</div>
          </div>
          <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
                      padding:10px 14px;text-align:center;">
            <div style="font-size:8px;color:#94A3B8;letter-spacing:0.12em;
                        text-transform:uppercase;margin-bottom:4px;">Avg Surprise</div>
            <div style="font-size:22px;font-weight:500;
                        font-family:'JetBrains Mono',monospace;color:{"#059669" if has_surp and hist["Surprise(%)"].mean()>0 else "#DC2626"};">
              {_fmt_pct(hist["Surprise(%)"].mean()) if has_surp else "—"}
            </div>
            <div style="font-size:9px;color:#94A3B8;">vs consensus estimate</div>
          </div>
          <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
                      padding:10px 14px;text-align:center;">
            <div style="font-size:8px;color:#94A3B8;letter-spacing:0.12em;
                        text-transform:uppercase;margin-bottom:4px;">Last EPS</div>
            <div style="font-size:22px;font-weight:500;color:#0F172A;
                        font-family:'JetBrains Mono',monospace;">
              {f"{sym}{_safe(hist['Reported EPS'].iloc[-1]):.2f}" if not hist.empty else "—"}
            </div>
            <div style="font-size:9px;color:#94A3B8;">most recent quarter</div>
          </div>
        </div>
        """)

    # ── EPS Chart ────────────────────────────────────────────
    fig = go.Figure()

    if has_est:
        fig.add_trace(go.Bar(
            x=hist["Date_str"],
            y=hist["EPS Estimate"].astype(float),
            name="EPS Estimate",
            marker=dict(color="#BFDBFE", opacity=0.8),
            hovertemplate="<b>%{x}</b><br>Estimate: %{y:.2f}<extra></extra>",
        ))

    if has_actual:
        colors = []
        for i, row in hist.iterrows():
            act = _safe(row.get("Reported EPS", 0))
            est = _safe(row.get("EPS Estimate", act)) if has_est else act
            colors.append("#059669" if act >= est else "#DC2626")

        fig.add_trace(go.Bar(
            x=hist["Date_str"],
            y=hist["Reported EPS"].astype(float),
            name="Reported EPS",
            marker=dict(color=colors, opacity=0.9),
            hovertemplate="<b>%{x}</b><br>Reported: %{y:.2f}<extra></extra>",
        ))

    fig.update_layout(
        barmode="overlay",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family="JetBrains Mono, monospace", color="#475569", size=10),
        margin=dict(t=10, b=30, l=10, r=10),
        height=200,
        legend=dict(
            orientation="h", y=1.1, x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=10),
        ),
        xaxis=dict(gridcolor="#F1F5F9", linecolor="#E2E8F0", tickfont=dict(size=9)),
        yaxis=dict(
            gridcolor="#F1F5F9", linecolor="#E2E8F0",
            title="EPS", title_font=dict(size=9), tickfont=dict(size=9),
        ),
        hoverlabel=dict(bgcolor="#0F172A", font=dict(color="#F1F5F9", family="JetBrains Mono")),
    )

    st.plotly_chart(fig, width='stretch',
                    config={"displayModeBar": False})

    # ── Surprise % history table ─────────────────────────────
    if has_surp:
        rows_html = ""
        sort_col = "Date" if "Date" in hist.columns else "Date_str"
        for _, r in hist.sort_values(sort_col, ascending=False).iterrows():
            surp = _safe(r.get("Surprise(%)"))
            act  = _safe(r.get("Reported EPS"))
            est  = _safe(r.get("EPS Estimate")) if has_est else 0
            beat = act >= est if has_est else None
            beat_icon  = "▲ BEAT" if beat else "▼ MISS"
            beat_clr2  = "#059669" if beat else "#DC2626"
            beat_bg    = "#ECFDF5" if beat else "#FEF2F2"

            rows_html += f"""
            <tr style="border-bottom:1px solid #F8FAFC;">
              <td style="padding:5px 10px;font-size:10px;color:#475569;">{r.get("Date_str","")}</td>
              <td style="padding:5px 10px;font-size:10px;font-weight:500;color:#0F172A;
                         font-family:'JetBrains Mono',monospace;text-align:right;">{sym}{act:.2f}</td>
              <td style="padding:5px 10px;font-size:10px;color:#64748B;
                         font-family:'JetBrains Mono',monospace;text-align:right;">{sym}{est:.2f}</td>
              <td style="padding:5px 10px;font-size:10px;font-weight:700;
                         font-family:'JetBrains Mono',monospace;text-align:right;color:{beat_clr2};">{surp:+.1f}%</td>
              <td style="padding:5px 10px;text-align:center;">
                <span style="padding:2px 7px;background:{beat_bg};border-radius:3px;
                             font-size:8px;font-weight:700;color:{beat_clr2};">{beat_icon}</span>
              </td>
            </tr>"""

        st.html(f"""
        <div style="border-radius:8px;border:1px solid #E2E8F0;overflow:hidden;margin-top:4px;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#F8FAFC;">
                {''.join(f'<th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#94A3B8;text-align:{"right" if i>0 else "left"};">{h}</th>'
                         for i,h in enumerate(["Quarter","Reported EPS","Estimate","Surprise","Result"]))}
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """)


# ════════════════════════════════════════════════════════════════
# FEATURE 4 — MULTI-STOCK COMPARISON WATCHLIST
# ════════════════════════════════════════════════════════════════

_DEFAULT_WATCHLIST = [
    "TCS.NS", "INFY.NS", "RELIANCE.NS", "HDFCBANK.NS",
    "AAPL", "MSFT", "GOOGL", "NVDA",
]

@st.cache_data(ttl=120, show_spinner=False)
def _fetch_comparison_row(ticker: str) -> dict:
    """Fetch one row of comparison data for a ticker. Cached 2 minutes."""
    try:
        t  = yf.Ticker(ticker)
        fi = t.fast_info
        info = t.info

        price  = _safe(getattr(fi, "last_price", 0))
        prev   = _safe(getattr(fi, "previous_close", 0))
        pct    = (price - prev) / prev * 100 if prev > 0 else 0
        mktcap = _safe(getattr(fi, "market_cap", 0) or info.get("marketCap", 0))

        return {
            "ticker":    ticker,
            "price":     price,
            "change":    pct,
            "mktcap":    mktcap,
            "pe":        _safe(info.get("forwardPE") or info.get("trailingPE")),
            "pb":        _safe(info.get("priceToBook")),
            "roe":       _safe(info.get("returnOnEquity")),
            "rev_growth":_safe(info.get("revenueGrowth")),
            "op_margin": _safe(info.get("operatingMargins")),
            "div_yield": _safe(info.get("dividendYield")),
            "sector":    info.get("sector", "—"),
            "name":      info.get("shortName", ticker),
            "ok":        True,
        }
    except Exception:
        return {"ticker": ticker, "ok": False}


def _fetch_watchlist_parallel(tickers: list[str]) -> list[dict]:
    """Fetch all tickers in parallel using threads."""
    results = [None] * len(tickers)
    def fetch_one(i, tk):
        results[i] = _fetch_comparison_row(tk)
    threads = [threading.Thread(target=fetch_one, args=(i, tk))
               for i, tk in enumerate(tickers)]
    for th in threads: th.start()
    for th in threads: th.join(timeout=10)
    return [r for r in results if r and r.get("ok")]


def render_comparison_watchlist(
    sym: str = "$",
    analysed_ticker: str = "",
    analysed_data: dict = None,
) -> None:
    """
    Renders a live multi-stock comparison table with:
    - Persistent watchlist (stored in session_state)
    - Add/remove tickers
    - Live prices, P/E, margins, growth, dividend yield
    - One-click "analyse this stock" link
    - Highlighted row for currently analysed stock

    Args:
        sym:              Currency symbol
        analysed_ticker:  Currently analysed ticker (highlighted in table)
        analysed_data:    Dict with your DCF results to add YieldIQ IV column
    """
    # ── Watchlist state ──────────────────────────────────────
    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = list(_DEFAULT_WATCHLIST)

    wl = st.session_state["watchlist"]

    # ── Controls ─────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3 = st.columns([3, 2, 1])
    with ctrl1:
        new_ticker = st.text_input(
            "Add ticker to watchlist",
            placeholder="e.g. WIPRO.NS or AMZN",
            label_visibility="collapsed",
            key="watchlist_add_input",
        ).upper().strip()
    with ctrl2:
        if st.button("+ Add to Watchlist", key="watchlist_add_btn", width='stretch'):
            if new_ticker and new_ticker not in wl:
                wl.insert(0, new_ticker)
                st.session_state["watchlist"] = wl
                _fetch_comparison_row.clear()
                st.rerun()
    with ctrl3:
        if st.button("↻ Refresh All", key="watchlist_refresh_btn", width='stretch'):
            _fetch_comparison_row.clear()
            st.rerun()

    # ── Fetch data for all watchlist tickers ─────────────────
    with st.spinner("Fetching watchlist data…"):
        rows = _fetch_watchlist_parallel(wl)

    if not rows:
        st.warning("Could not fetch data for any watchlist ticker.")
        return

    # ── Build table ──────────────────────────────────────────
    def _mc(v):
        if v >= 1e12: return f"{v/1e12:.1f}T"
        if v >= 1e9:  return f"{v/1e9:.1f}B"
        if v >= 1e6:  return f"{v/1e6:.1f}M"
        return str(int(v))

    rows_html = ""
    for r in rows:
        tk       = r["ticker"]
        is_curr  = tk == analysed_ticker
        row_bg   = "background:#EFF6FF;" if is_curr else ""
        chg      = r.get("change", 0)
        chg_clr  = _clr(chg)
        chg_icon = "▲" if chg >= 0 else "▼"

        # YieldIQ MoS column — only for currently analysed ticker
        mos_cell = ""
        if is_curr and analysed_data:
            mos_v = analysed_data.get("mos_pct", 0)
            sig_v = analysed_data.get("signal", "")
            m_clr = _clr(mos_v)
            mos_cell = (
                f'<td style="padding:7px 10px;text-align:right;font-family:"JetBrains Mono",monospace;">'
                f'<span style="color:{m_clr};font-weight:700;">{mos_v:.1f}%</span>'
                f'<br><span style="font-size:8px;color:{_sig_clr(sig_v)};font-weight:700;">'
                f'{sig_v.split()[0] if sig_v else ""}</span></td>'
            )
        else:
            mos_cell = '<td style="padding:7px 10px;text-align:center;color:#CBD5E1;">—</td>'

        # Remove button
        remove_key = f"rm_{tk}"

        rows_html += f"""
        <tr style="border-bottom:1px solid #F1F5F9;{row_bg}transition:background 0.1s;"
            onmouseover="this.style.background='#F8FAFC'"
            onmouseout="this.style.background='{'#EFF6FF' if is_curr else 'transparent'}'">
          <td style="padding:7px 10px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
                        font-weight:700;color:{'#1D4ED8' if is_curr else '#0F172A'};">{tk}</div>
            <div style="font-size:9px;color:#94A3B8;white-space:nowrap;overflow:hidden;
                        text-overflow:ellipsis;max-width:140px;">{r.get("name","")}</div>
          </td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:12px;font-weight:500;">${r.get("price",0):,.2f}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:11px;font-weight:700;color:{chg_clr};">
            {chg_icon}{abs(chg):.2f}%</td>
          <td style="padding:7px 10px;text-align:right;font-size:10px;color:#475569;">
            {_mc(r.get("mktcap",0))}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:10px;color:#475569;">
            {f"{r['pe']:.1f}x" if r.get("pe") else "—"}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:10px;color:{_clr(r.get("roe",0))};">
            {f"{r['roe']*100:.1f}%" if r.get("roe") else "—"}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:10px;color:{_clr(r.get("rev_growth",0))};">
            {f"{r['rev_growth']*100:.1f}%" if r.get("rev_growth") else "—"}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:10px;color:{_clr(r.get("op_margin",0),0.08)};">
            {f"{r['op_margin']*100:.1f}%" if r.get("op_margin") else "—"}</td>
          <td style="padding:7px 10px;text-align:right;font-family:'JetBrains Mono',monospace;
                     font-size:10px;color:#2563EB;">
            {f"{r['div_yield']*100:.1f}%" if r.get("div_yield") else "—"}</td>
          {mos_cell}
        </tr>"""

    header_cells = [
        ("TICKER", "left"), ("PRICE", "right"), ("CHANGE", "right"),
        ("MKT CAP", "right"), ("FWD P/E", "right"), ("ROE", "right"),
        ("REV GROWTH", "right"), ("OP MARGIN", "right"), ("DIV YIELD", "right"),
        ("YIQ MoS", "right"),
    ]

    header_html = "".join(
        f'<th style="padding:7px 10px;font-size:8px;font-weight:700;letter-spacing:0.12em;'
        f'text-transform:uppercase;color:#94A3B8;text-align:{align};">{h}</th>'
        for h, align in header_cells
    )

    st.html(f"""
    <div style="border-radius:10px;border:1px solid #E2E8F0;overflow:hidden;
                box-shadow:0 1px 3px rgba(15,23,42,0.06);">
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#F8FAFC;">{header_html}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:9px;color:#94A3B8;font-family:'JetBrains Mono',monospace;">
      YIQ MoS = YieldIQ Margin of Safety (only shown for currently analysed stock) ·
      Prices refresh every 2 minutes · Source: Yahoo Finance
    </div>
    """)

    # ── Remove ticker buttons (native Streamlit below table) ─
    st.markdown("**Remove from watchlist:**")
    rm_cols = st.columns(min(len(rows), 8))
    for i, r in enumerate(rows[:8]):
        with rm_cols[i]:
            if st.button(f"✕ {r['ticker']}", key=f"rm_{r['ticker']}_{i}",
                         width='stretch'):
                wl.remove(r["ticker"])
                st.session_state["watchlist"] = wl
                st.rerun()
