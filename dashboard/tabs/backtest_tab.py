# dashboard/tabs/backtest_tab.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ Backtesting Engine — Upgraded v2
#
# Measures whether saved portfolio signals proved correct at
# 3-month, 6-month, and 12-month horizons.
#
# Logic:
#   Undervalued signal → correct if price ROSE at horizon
#   Overvalued  signal → correct if price FELL at horizon
#   Neutral            → tracked for return only, no hit/miss
#
# Storage: price_snapshots table in portfolio.db (same SQLite)
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import threading
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from portfolio import (
    _get_conn, _lock, get_portfolio,
    init_db as _init_portfolio_db,
)

def _get_active_theme():
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent.parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_x", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    import streamlit as st
    return _tm.get_theme(st.session_state.get("theme", "slate"))


HORIZONS = {90: "3 Months", 180: "6 Months", 365: "12 Months"}


# ════════════════════════════════════════════════════════════════
# DB SETUP
# ════════════════════════════════════════════════════════════════

def init_backtest_db() -> None:
    """Create price_snapshots table if it doesn't exist."""
    _init_portfolio_db()
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT    NOT NULL,
                saved_at    TEXT    NOT NULL,
                entry_price REAL    NOT NULL,
                iv          REAL    NOT NULL,
                signal      TEXT    NOT NULL,
                horizon     INTEGER NOT NULL,
                snap_date   TEXT,
                snap_price  REAL,
                hit         INTEGER,
                return_pct  REAL,
                vs_iv_pct   REAL,
                UNIQUE(ticker, saved_at, horizon)
            )
        """)
        conn.commit()
        conn.close()


# ════════════════════════════════════════════════════════════════
# PRICE FETCHER
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _get_historical_price(ticker: str, target_date: str) -> float:
    """Fetch close price on or near a specific date (±5 days for weekends)."""
    try:
        import yfinance as yf
        dt    = datetime.strptime(target_date, "%Y-%m-%d")
        start = (dt - timedelta(days=5)).strftime("%Y-%m-%d")
        end   = (dt + timedelta(days=5)).strftime("%Y-%m-%d")
        hist  = yf.Ticker(ticker).history(start=start, end=end)
        if hist.empty:
            return 0.0
        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index
        closest = hist.iloc[(hist.index - dt).abs().argsort()[:1]]
        return float(closest["Close"].iloc[0])
    except Exception:
        return 0.0


# ════════════════════════════════════════════════════════════════
# SNAPSHOT ENGINE
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def get_pending_snapshots() -> list[dict]:
    """Return entries where horizon has passed but snapshot not yet taken. Cached 10 min."""
    init_backtest_db()
    holdings = get_portfolio()
    today    = datetime.today()
    pending  = []

    with _lock:
        conn = _get_conn()
        for h in holdings:
            try:
                save_dt = datetime.strptime(h["saved_at"][:10], "%Y-%m-%d")
            except Exception:
                continue
            for days in HORIZONS:
                if save_dt + timedelta(days=days) > today:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM price_snapshots "
                    "WHERE ticker=? AND saved_at=? AND horizon=?",
                    (h["ticker"], h["saved_at"][:10], days)
                ).fetchone()
                if not exists:
                    pending.append({
                        "ticker":   h["ticker"],
                        "horizon":  days,
                        "due_date": (save_dt + timedelta(days=days)).strftime("%Y-%m-%d"),
                    })
        conn.close()
    return pending


def update_snapshots() -> int:
    """
    Collect price snapshots for all due horizons.
    Returns number of new snapshots taken.
    """
    init_backtest_db()
    holdings = get_portfolio()
    if not holdings:
        return 0

    today = datetime.today()
    taken = 0

    with _lock:
        conn = _get_conn()
        for h in holdings:
            ticker      = h["ticker"]
            entry_price = h["entry_price"]
            iv          = h["iv"]
            signal      = h["signal"]
            saved_at    = h["saved_at"][:10]

            try:
                save_dt = datetime.strptime(saved_at, "%Y-%m-%d")
            except Exception:
                continue

            for days in HORIZONS:
                target_dt  = save_dt + timedelta(days=days)
                target_str = target_dt.strftime("%Y-%m-%d")

                if target_dt > today:
                    continue

                exists = conn.execute(
                    "SELECT 1 FROM price_snapshots "
                    "WHERE ticker=? AND saved_at=? AND horizon=?",
                    (ticker, saved_at, days)
                ).fetchone()
                if exists:
                    continue

                snap_price = _get_historical_price(ticker, target_str)
                if snap_price <= 0 or entry_price <= 0:
                    continue

                return_pct = (snap_price - entry_price) / entry_price * 100
                vs_iv_pct  = (snap_price - iv) / iv * 100 if iv > 0 else None

                # Hit logic
                if "Under" in signal:
                    hit = 1 if snap_price > entry_price else 0
                elif "Over" in signal:
                    hit = 1 if snap_price < entry_price else 0
                else:
                    hit = None  # Neutral — track return but no hit/miss

                conn.execute(
                    """INSERT OR IGNORE INTO price_snapshots
                       (ticker, saved_at, entry_price, iv, signal, horizon,
                        snap_date, snap_price, hit, return_pct, vs_iv_pct)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (ticker, saved_at, entry_price, iv, signal, days,
                     target_str, snap_price, hit, return_pct, vs_iv_pct)
                )
                taken += 1

        conn.commit()
        conn.close()

    return taken


@st.cache_data(ttl=300, show_spinner=False)
def get_backtest_results() -> list[dict]:
    """Return all completed snapshots from DB. Cached 5 minutes."""
    init_backtest_db()
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT ticker, saved_at, entry_price, iv, signal,
                      horizon, snap_date, snap_price, hit, return_pct, vs_iv_pct
               FROM price_snapshots
               WHERE snap_price IS NOT NULL
               ORDER BY saved_at DESC, horizon ASC"""
        ).fetchall()
        conn.close()

    return [
        {
            "ticker":       r[0],
            "saved_at":     r[1],
            "entry_price":  r[2],
            "iv":           r[3],
            "signal":       r[4],
            "horizon":      r[5],
            "snap_date":    r[6],
            "snap_price":   r[7],
            "hit":          r[8],
            "return_pct":   r[9] or 0.0,
            "vs_iv_pct":    r[10],
            "sym":          "$",
        }
        for r in rows
    ]


# ════════════════════════════════════════════════════════════════
# RENDER — upgraded marketing-grade tab
# ════════════════════════════════════════════════════════════════

def render_backtest_tab() -> None:
    """Full backtesting tab — upgraded to Koyfin-grade marketing asset."""
    init_backtest_db()
    # Auto-update snapshots in background (only runs if new horizons are due)
    # Bust cache after update so fresh results show immediately
    _pending = get_pending_snapshots()
    if _pending:
        _new = update_snapshots()
        if _new > 0:
            get_backtest_results.clear()
            get_pending_snapshots.clear()
    results = get_backtest_results()

    # ── UPGRADE 1: Hero accuracy banner ─────────────────────
    if len(results) >= 3:
        _all_hit    = [r for r in results if r["hit"] is not None]
        _total      = len(_all_hit)
        _hits       = sum(1 for r in _all_hit if r["hit"] == 1)
        _accuracy   = _hits / _total * 100 if _total else 0

        _under_rets = [r["return_pct"] for r in results
                       if "Under" in r.get("signal", "") and r["return_pct"] is not None]
        _over_rets  = [r["return_pct"] for r in results
                       if "Over" in r.get("signal", "") and r["return_pct"] is not None]
        _avg_under  = sum(_under_rets) / len(_under_rets) if _under_rets else 0.0
        _avg_over   = sum(_over_rets)  / len(_over_rets)  if _over_rets  else 0.0
        _n_signals  = len(results)

        _acc_clr   = "#00b4d8"
        _under_clr = "#10b981" if _avg_under > 0 else "#ef4444"
        # For Overvalued signals, a negative return_pct means model was RIGHT
        _over_clr  = "#10b981" if _avg_over < 0 else "#ef4444"
        _over_sign = "+" if _avg_over >= 0 else ""

        st.html(f"""
<div style="background:linear-gradient(135deg,#0a1628 0%,#0f2537 60%,#0a1e30 100%);
            border:1px solid rgba(0,180,216,0.2);border-radius:14px;
            padding:28px 32px;margin-bottom:20px;position:relative;overflow:hidden;">
  <!-- Subtle grid overlay -->
  <div style="position:absolute;inset:0;
              background-image:linear-gradient(rgba(0,180,216,0.04) 1px,transparent 1px),
                               linear-gradient(90deg,rgba(0,180,216,0.04) 1px,transparent 1px);
              background-size:32px 32px;pointer-events:none;"></div>
  <div style="position:relative;z-index:2;">
    <!-- Eyebrow -->
    <div style="font-size:10px;font-weight:700;letter-spacing:0.2em;
                text-transform:uppercase;color:#00b4d8;margin-bottom:10px;">
      Live Model Track Record
    </div>
    <!-- Headline -->
    <div style="font-size:22px;font-weight:700;color:#e6edf3;
                margin-bottom:24px;letter-spacing:-0.01em;">
      YieldIQ Signal Accuracy
    </div>
    <!-- 4 metrics -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
                gap:0;border:1px solid rgba(255,255,255,0.08);
                border-radius:10px;overflow:hidden;">
      <div style="padding:18px 20px;border-right:1px solid rgba(255,255,255,0.08);
                  text-align:center;">
        <div style="font-size:36px;font-weight:700;color:{_acc_clr};
                    font-family:'IBM Plex Mono',monospace;line-height:1;">
          {_accuracy:.0f}%</div>
        <div style="font-size:11px;color:#8b949e;margin-top:6px;
                    text-transform:uppercase;letter-spacing:0.1em;">Overall Accuracy</div>
        <div style="font-size:10px;color:#484f58;margin-top:3px;">{_hits}/{_total} signals correct</div>
      </div>
      <div style="padding:18px 20px;border-right:1px solid rgba(255,255,255,0.08);
                  text-align:center;">
        <div style="font-size:36px;font-weight:700;color:{_under_clr};
                    font-family:'IBM Plex Mono',monospace;line-height:1;">
          {_avg_under:+.1f}%</div>
        <div style="font-size:11px;color:#8b949e;margin-top:6px;
                    text-transform:uppercase;letter-spacing:0.1em;">Avg Undervalued Return</div>
        <div style="font-size:10px;color:#484f58;margin-top:3px;">{len(_under_rets)} signals</div>
      </div>
      <div style="padding:18px 20px;border-right:1px solid rgba(255,255,255,0.08);
                  text-align:center;">
        <div style="font-size:36px;font-weight:700;color:{_over_clr};
                    font-family:'IBM Plex Mono',monospace;line-height:1;">
          {_over_sign}{_avg_over:.1f}%</div>
        <div style="font-size:11px;color:#8b949e;margin-top:6px;
                    text-transform:uppercase;letter-spacing:0.1em;">Avg Overvalued Return</div>
        <div style="font-size:10px;color:#484f58;margin-top:3px;">↓ negative = model correct</div>
      </div>
      <div style="padding:18px 20px;text-align:center;">
        <div style="font-size:36px;font-weight:700;color:#e6edf3;
                    font-family:'IBM Plex Mono',monospace;line-height:1;">
          {_n_signals}</div>
        <div style="font-size:11px;color:#8b949e;margin-top:6px;
                    text-transform:uppercase;letter-spacing:0.1em;">Signals Tracked</div>
        <div style="font-size:10px;color:#484f58;margin-top:3px;">across all horizons</div>
      </div>
    </div>
    <!-- Footnote -->
    <div style="font-size:10px;color:#484f58;font-style:italic;margin-top:14px;text-align:center;">
      Based on {_n_signals} historical signals.
      Past performance does not guarantee future results.
    </div>
  </div>
</div>
""")

    # ── Header ───────────────────────────────────────────────
    st.html("""
    <div style="padding:4px 0 14px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;
                  letter-spacing:0.14em;text-transform:uppercase;color:#94A3B8;margin-bottom:4px;">
        Signal Accuracy Tracker
      </div>
      <div style="font-size:20px;font-weight:700;color:#0F172A;">
        Backtesting — Did YieldIQ's Calls Prove Right?
      </div>
      <div style="font-size:12px;color:#64748B;margin-top:4px;line-height:1.8;">
        Every saved signal is checked at 3m · 6m · 12m horizons.<br>
        <strong style="color:#059669;">Undervalued</strong> = correct if price rose &nbsp;·&nbsp;
        <strong style="color:#DC2626;">Overvalued</strong> = correct if price fell.
      </div>
    </div>
    """)

    # ── Controls ─────────────────────────────────────────────
    pending = get_pending_snapshots()

    if pending:
        st.info(
            f"⏳ **{len(pending)}** snapshot(s) ready — "
            "horizon dates have passed. Click **▶ Run Backtest** to fetch prices."
        )

    c1, c2, _ = st.columns([2, 2, 5])
    with c1:
        if st.button("▶  Run Backtest", key="bt_run",
                     width='stretch', type="primary"):
            with st.spinner("Fetching historical prices…"):
                n = update_snapshots()
            if n > 0:
                st.success(f"✓ {n} new snapshot(s) collected!")
                st.rerun()
            else:
                st.info("No new snapshots yet — wait for 3-month horizon.")
    with c2:
        if st.button("↻  Refresh", key="bt_refresh", width='stretch'):
            _get_historical_price.clear()
            st.rerun()

    st.html("<div style='height:6px'></div>")

    # ── Empty state ───────────────────────────────────────────
    if not results:
        holdings = get_portfolio()
        if not holdings:
            st.html("""
            <div style="text-align:center;padding:60px;
                        background:linear-gradient(135deg,#0d1117,#161b22);
                        border:1px dashed #21262d;border-radius:12px;">
              <div style="font-size:40px;margin-bottom:14px;">📊</div>
              <div style="font-size:18px;font-weight:700;color:#e6edf3;margin-bottom:10px;">
                No signals to backtest yet</div>
              <div style="font-size:13px;color:#8b949e;line-height:1.8;max-width:400px;margin:0 auto;">
                Save stocks in the <strong style="color:#00b4d8;">Portfolio</strong> tab first.<br>
                Backtesting begins automatically after 3 months.
              </div>
            </div>
            """)
            return

        # Show countdown table
        _rows = ""
        for h in holdings:
            try:
                save_dt   = datetime.strptime(h["saved_at"][:10], "%Y-%m-%d")
                first_dt  = save_dt + timedelta(days=90)
                days_left = (first_dt - datetime.today()).days
                label     = "Ready now ✓" if days_left <= 0 else f"In {days_left} days"
                l_clr     = "#10b981" if days_left <= 0 else "#f59e0b" if days_left < 30 else "#8b949e"
                s_clr     = "#10b981" if "Under" in h["signal"] else "#ef4444"
                _rows += (
                    f'<tr style="border-bottom:1px solid #21262d;">'
                    f'<td style="padding:9px 14px;font-family:IBM Plex Mono,monospace;'
                    f'font-size:13px;font-weight:700;color:#e6edf3;">{h["ticker"]}</td>'
                    f'<td style="padding:9px 14px;font-size:12px;color:#8b949e;">'
                    f'{h.get("company_name","")[:24]}</td>'
                    f'<td style="padding:9px 14px;font-size:12px;color:#8b949e;">{h["saved_at"][:10]}</td>'
                    f'<td style="padding:9px 14px;font-family:IBM Plex Mono,monospace;'
                    f'font-size:12px;font-weight:700;color:{s_clr};">{h["signal"]}</td>'
                    f'<td style="padding:9px 14px;font-family:IBM Plex Mono,monospace;'
                    f'font-size:12px;font-weight:700;color:{l_clr};">{label}</td>'
                    f'</tr>'
                )
            except Exception:
                continue

        _hdr = "".join(
            f'<th style="padding:9px 14px;font-size:10px;font-weight:700;'
            f'letter-spacing:0.12em;text-transform:uppercase;color:#8b949e;">{t}</th>'
            for t in ["Ticker", "Company", "Saved", "Signal", "First Check In"]
        )
        st.html(
            '<div style="border-radius:10px;border:1px solid #21262d;overflow:hidden;">'
            '<div style="background:#161b22;padding:10px 14px;border-bottom:1px solid #21262d;'
            'font-family:IBM Plex Mono,monospace;font-size:10px;font-weight:700;'
            'letter-spacing:0.12em;text-transform:uppercase;color:#8b949e;">'
            'SAVED SIGNALS — AWAITING 3-MONTH HORIZON</div>'
            '<table style="width:100%;border-collapse:collapse;background:#0d1117;">'
            '<thead><tr style="background:#161b22;">' + _hdr + '</tr></thead>'
            '<tbody>' + _rows + '</tbody>'
            '</table></div>'
        )
        return

    # ── Scorecard columns ────────────────────────────────────
    by_horizon = defaultdict(list)
    for r in results:
        if r["hit"] is not None:
            by_horizon[r["horizon"]].append(r)

    s_cols = st.columns(3)
    for col, (days, label) in zip(s_cols, HORIZONS.items()):
        batch = by_horizon.get(days, [])
        if batch:
            hits    = sum(1 for r in batch if r["hit"] == 1)
            total   = len(batch)
            acc     = hits / total * 100
            avg_ret = sum(r["return_pct"] for r in batch) / total
            a_clr   = "#10b981" if acc >= 60 else "#f59e0b" if acc >= 45 else "#ef4444"
            r_clr   = "#10b981" if avg_ret > 0 else "#ef4444"
            col.html(
                f'<div style="background:#161b22;border:1px solid #21262d;border-radius:10px;'
                f'border-top:3px solid {a_clr};padding:18px;text-align:center;">'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;font-weight:700;'
                f'color:#8b949e;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">'
                f'{label}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:34px;font-weight:700;'
                f'color:{a_clr};margin-bottom:4px;">{acc:.0f}%</div>'
                f'<div style="font-size:12px;color:#8b949e;">Accuracy · {hits}/{total} correct</div>'
                f'<div style="height:1px;background:#21262d;margin:12px 0;"></div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:18px;'
                f'font-weight:600;color:{r_clr};">{avg_ret:+.1f}%</div>'
                f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">Avg price return</div>'
                f'</div>'
            )
        else:
            col.html(
                f'<div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;'
                f'padding:18px;text-align:center;opacity:0.5;">'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;font-weight:700;'
                f'color:#8b949e;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px;">'
                f'{label}</div>'
                f'<div style="font-size:28px;margin-bottom:8px;">⏳</div>'
                f'<div style="font-size:12px;color:#8b949e;">No results yet</div>'
                f'</div>'
            )

    st.html("<div style='height:16px'></div>")

    # ── UPGRADE 2: Equity curve chart ───────────────────────
    _completed = [r for r in results if r["return_pct"] is not None]
    if len(_completed) >= 2:
        try:
            _sorted = sorted(_completed, key=lambda x: x["saved_at"])
            _dates  = [r["saved_at"] for r in _sorted]
            _rets   = [r["return_pct"] / 100 for r in _sorted]

            # Cumulative compounding from $10,000
            _portfolio = [10_000.0]
            for _r in _rets:
                _portfolio.append(_portfolio[-1] * (1 + _r / len(_rets)))

            # SPY 7% annualised flat line
            _days_span = max((datetime.strptime(_dates[-1], "%Y-%m-%d") -
                              datetime.strptime(_dates[0],  "%Y-%m-%d")).days, 1)
            _spy_end   = 10_000 * ((1.07) ** (_days_span / 365))
            _spy_line  = [
                10_000 + (_spy_end - 10_000) * i / max(len(_dates), 1)
                for i in range(len(_dates) + 1)
            ]
            _x_pts = _dates + [_dates[-1]]

            _fig_eq = go.Figure()
            _fig_eq.add_trace(go.Scatter(
                x=_x_pts, y=_portfolio,
                mode="lines", name="YieldIQ Signals",
                line=dict(color="#00b4d8", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(0,180,216,0.06)",
                hovertemplate="<b>%{x}</b><br>Portfolio: $%{y:,.0f}<extra>YieldIQ</extra>",
            ))
            _fig_eq.add_trace(go.Scatter(
                x=_x_pts, y=_spy_line,
                mode="lines", name="Buy & Hold SPY (7% p.a.)",
                line=dict(color="#8b949e", width=1.5, dash="dot"),
                hovertemplate="<b>%{x}</b><br>SPY ref: $%{y:,.0f}<extra>SPY</extra>",
            ))
            _fig_eq.add_hline(y=10_000, line=dict(color="#30363d", width=1, dash="dash"))

            _fig_eq.update_layout(
                paper_bgcolor=_get_active_theme()["chart_paper"], plot_bgcolor=_get_active_theme()["chart_bg"],
                font=dict(family="Inter, sans-serif", color="#e6edf3", size=11),
                height=260,
                margin=dict(t=44, b=40, l=60, r=20),
                hovermode="x unified",
                hoverlabel=dict(bgcolor="#FFFFFF", font_color="#475569", bordercolor="#30363d"),
                legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#30363d", borderwidth=1,
                            font=dict(color="#8b949e", size=11), x=0, y=1),
                xaxis=dict(gridcolor="rgba(0,0,0,0.04)", linecolor="#CBD5E1",
                           tickfont=dict(color="#64748B", size=10)),
                yaxis=dict(gridcolor="rgba(0,0,0,0.04)", linecolor="#CBD5E1",
                           tickfont=dict(color="#64748B", size=10),
                           tickprefix="$", tickformat=",.0f"),
                title=dict(text="Hypothetical Portfolio — $10,000 Starting Capital",
                           font=dict(color="#8b949e", size=11), x=0),
            )
            # Teal top accent line
            _fig_eq.add_shape(type="line", xref="paper", yref="paper",
                              x0=0, x1=1, y0=1, y1=1,
                              line=dict(color="#00b4d8", width=2))
            st.plotly_chart(_fig_eq, width='stretch',
                            config={"displayModeBar": True,
                                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                    "toImageButtonOptions": {"filename": "yieldiq_equity_curve",
                                                             "scale": 2}})
        except Exception:
            pass  # equity curve is best-effort, don't block rest of tab

    st.html("<div style='height:8px'></div>")

    # ── UPGRADE 3: Styled results table ─────────────────────
    _SIG_COLORS = {
        "Undervalued 🟢":    ("#0D7A4E", "#022c1d"),
        "Slight Discount 🟡":("#B45309", "#2d1f05"),
        "Fairly Valued 🔵":  ("#1D4ED8", "#07112e"),
        "Overvalued 🔴":     ("#B91C1C", "#2d0606"),
    }

    def _sig_pill(s: str) -> str:
        # Match on partial key
        fg, bg = "#8b949e", "#161b22"
        for k, (f, b) in _SIG_COLORS.items():
            if any(w in str(s) for w in k.split()):
                fg, bg = f, b
                break
        lbl = str(s).split()[0] if s else "—"
        return (f'<span style="background:{bg};color:{fg};border:1px solid {fg}55;'
                f'font-size:10px;font-weight:700;padding:2px 9px;border-radius:12px;'
                f'white-space:nowrap;">{lbl}</span>')

    def _ret_cell(v: float) -> str:
        clr  = "#10b981" if v > 0 else "#ef4444"
        arr  = "▲" if v > 0 else "▼"
        return (f'<span style="font-family:IBM Plex Mono,monospace;font-size:12px;'
                f'font-weight:600;color:{clr};">{arr} {v:+.1f}%</span>')

    def _hit_cell(h) -> str:
        if h == 1:  return '<span style="font-size:15px;">✅</span>'
        if h == 0:  return '<span style="font-size:15px;">❌</span>'
        return '<span style="font-size:15px;opacity:.5;">⏳</span>'

    _hdr3 = "".join(
        f'<th style="padding:9px 12px;background:#0d1117;color:#8b949e;'
        f'font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;'
        f'border-bottom:2px solid #21262d;white-space:nowrap;'
        f'position:sticky;top:0;z-index:1;">{t}</th>'
        for t in ["Ticker", "Saved", "Signal", "Horizon", "Entry", "At Horizon", "Return", "Result"]
    )

    _tbody3 = ""
    for _ri, r in enumerate(sorted(results, key=lambda x: (x["saved_at"], x["horizon"]), reverse=True)):
        _bg   = "#0d1117" if _ri % 2 == 0 else "#0f1318"
        _sym  = r.get("sym", "$")
        _snap = r.get("snap_price", 0) or 0
        _tbody3 += (
            f'<tr style="border-bottom:1px solid #161b22;background:{_bg};">'
            f'<td style="padding:9px 12px;font-family:IBM Plex Mono,monospace;'
            f'font-size:13px;font-weight:700;color:#00b4d8;">{r["ticker"]}</td>'
            f'<td style="padding:9px 12px;font-size:11px;color:#8b949e;">{r["saved_at"]}</td>'
            f'<td style="padding:9px 12px;">{_sig_pill(r["signal"])}</td>'
            f'<td style="padding:9px 12px;font-size:11px;color:#8b949e;">'
            f'{HORIZONS.get(r["horizon"], str(r["horizon"])+"d")}</td>'
            f'<td style="padding:9px 12px;font-family:IBM Plex Mono,monospace;'
            f'font-size:11px;color:#e6edf3;">{_sym}{r["entry_price"]:,.2f}</td>'
            f'<td style="padding:9px 12px;font-family:IBM Plex Mono,monospace;'
            f'font-size:11px;color:#e6edf3;">'
            f'{_sym}{_snap:,.2f}</td>'
            f'<td style="padding:9px 12px;">{_ret_cell(r["return_pct"])}</td>'
            f'<td style="padding:9px 12px;text-align:center;">{_hit_cell(r["hit"])}</td>'
            f'</tr>'
        )

    st.html(
        '<div style="overflow:auto;max-height:420px;border:1px solid #21262d;'
        'border-radius:10px;margin-bottom:16px;">'
        '<table style="width:100%;border-collapse:collapse;min-width:700px;">'
        '<thead><tr>' + _hdr3 + '</tr></thead>'
        '<tbody>' + _tbody3 + '</tbody>'
        '</table></div>'
    )

    # ── CSV export ────────────────────────────────────────────
    df_bt = pd.DataFrame([{
        "Ticker":           r["ticker"],
        "Saved At":         r["saved_at"],
        "Signal":           r["signal"],
        "Horizon":          HORIZONS.get(r["horizon"], f"{r['horizon']}d"),
        "Entry Price":      r["entry_price"],
        "Price at Horizon": r.get("snap_price", 0),
        "Return %":         round(r["return_pct"], 2),
        "Saved IV":         r["iv"],
        "Result":           "Correct" if r["hit"]==1 else "Wrong" if r["hit"]==0 else "Neutral",
    } for r in results])

    st.download_button(
        "⬇  Export Backtest CSV",
        data=df_bt.to_csv(index=False).encode("utf-8"),
        file_name=f"yieldiq_backtest_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key="bt_export",
        width='content',
    )

    # ── UPGRADE 4: Disclaimer card ───────────────────────────
    st.html("""
<div style="margin-top:24px;padding:18px 20px;
            background:rgba(251,191,36,0.07);
            border:1px solid rgba(251,191,36,0.25);
            border-left:4px solid #f59e0b;
            border-radius:10px;">
  <div style="font-size:12px;font-weight:700;color:#f59e0b;
              margin-bottom:6px;letter-spacing:0.04em;">
    ⚠️ Backtest Disclosure
  </div>
  <div style="font-size:12px;color:#94a3b8;line-height:1.8;">
    Backtest results reflect <strong style="color:#cbd5e1;">hypothetical past performance</strong>
    using the same model parameters applied retrospectively. They do
    <strong style="color:#cbd5e1;">not</strong> account for trading costs, slippage, taxes,
    or the practical impossibility of knowing future outcomes at the time of the signal.
    Backtesting has inherent look-ahead bias. A signal that looks correct in hindsight
    may not be replicable in live trading.
    <strong style="color:#f59e0b;">Past performance does not guarantee future results.</strong>
  </div>
</div>
""")


# ── render() entry point ──────────────────────────────────────
render = render_backtest_tab
