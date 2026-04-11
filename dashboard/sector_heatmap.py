# dashboard/sector_heatmap.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Markets / Sector Heatmap
#
# Features
#   • 11 GICS sectors, each proxied by its SPDR Select Sector ETF
#   • 30 / 60 / 90-day performance fetched from yfinance (cached 1 h)
#   • Relative Strength vs SPY for each window
#   • Interactive Plotly heatmap: sectors × periods, red-green diverging
#   • Sector Momentum Score (composite of 3 windows, recent-weighted)
#   • Acceleration / Deceleration flag (30d trend vs 90d trend)
#   • Top-3 / Bottom-3 ranked cards with Rotating / Defensive label
#   • Refresh button + last-updated timestamp
#   • All tiers: no gating
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from tab_helpers import ccard, ccard_end, apply_koyfin, KL

try:
    from utils.config import LAUNCH_REGION as _LAUNCH_REGION
except Exception:
    _LAUNCH_REGION = "US"


def _get_active_theme():
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_x", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    import streamlit as st
    return _tm.get_theme(st.session_state.get("theme", "slate"))


# ══════════════════════════════════════════════════════════════
# SECTOR DEFINITIONS — 11 GICS sectors + SPDR ETF proxies
# ══════════════════════════════════════════════════════════════

SECTORS: dict[str, dict] = {
    "XLK":  {"name": "Technology",             "short": "Tech",       "style": "Rotating",  "icon": "💻"},
    "XLF":  {"name": "Financials",              "short": "Financials", "style": "Rotating",  "icon": "🏦"},
    "XLV":  {"name": "Healthcare",              "short": "Health",     "style": "Defensive", "icon": "🏥"},
    "XLI":  {"name": "Industrials",             "short": "Industrial", "style": "Rotating",  "icon": "🏭"},
    "XLY":  {"name": "Consumer Discretionary",  "short": "Cons. Disc","style": "Rotating",  "icon": "🛒"},
    "XLP":  {"name": "Consumer Staples",        "short": "Staples",    "style": "Defensive", "icon": "🛍️"},
    "XLE":  {"name": "Energy",                  "short": "Energy",     "style": "Rotating",  "icon": "⚡"},
    "XLB":  {"name": "Materials",               "short": "Materials",  "style": "Rotating",  "icon": "⛏️"},
    "XLRE": {"name": "Real Estate",             "short": "Real Est.",  "style": "Defensive", "icon": "🏢"},
    "XLC":  {"name": "Communication Svcs",      "short": "Comm.",      "style": "Defensive", "icon": "📡"},
    "XLU":  {"name": "Utilities",               "short": "Utilities",  "style": "Defensive", "icon": "💡"},
}

_BENCHMARK = "SPY"
_WINDOWS   = [30, 60, 90]   # calendar days
_CACHE_TTL = 3600            # 1 hour


# ══════════════════════════════════════════════════════════════
# DATA FETCHING  (cached 1 h)
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _fetch_prices(tickers_tuple: tuple[str, ...]) -> dict[str, pd.Series]:
    """
    Download ~6 months of adjusted closes for all tickers.
    Returns dict  {ticker: pd.Series of close prices}.
    Raises on total failure; individual misses return empty Series.
    """
    tickers = list(tickers_tuple)
    raw     = yf.download(
        tickers,
        period     = "6mo",
        auto_adjust= True,
        progress   = False,
        threads    = True,
    )

    prices: dict[str, pd.Series] = {}
    close = raw.get("Close", raw) if isinstance(raw.columns, pd.MultiIndex) else raw

    for t in tickers:
        try:
            s = close[t].dropna() if t in close.columns else pd.Series(dtype=float)
        except Exception:
            s = pd.Series(dtype=float)
        prices[t] = s

    return prices


def _pct_change(series: pd.Series, days: int) -> float:
    """
    Compute calendar-day return: compare the latest close
    to the closest available close ≥ `days` calendar days ago.
    Returns NaN if insufficient history.
    """
    if series.empty or len(series) < 2:
        return float("nan")

    cutoff = series.index[-1] - timedelta(days=days)
    hist   = series[series.index <= cutoff]
    if hist.empty:
        return float("nan")

    base  = float(hist.iloc[-1])
    now_  = float(series.iloc[-1])
    return (now_ - base) / base * 100 if base else float("nan")


# ══════════════════════════════════════════════════════════════
# PERFORMANCE + MOMENTUM COMPUTATION
# ══════════════════════════════════════════════════════════════

def _compute_performance(prices: dict[str, pd.Series]) -> pd.DataFrame:
    """
    Build a DataFrame with one row per sector ETF.

    Columns
    -------
    etf, name, short, style, icon,
    r30, r60, r90,              # raw % returns
    rs30, rs60, rs90,           # relative strength vs SPY (sector% - spy%)
    momentum_score,             # composite score (recent-weighted)
    acceleration,               # "Accelerating" | "Decelerating" | "Stable"
    """
    spy = prices.get(_BENCHMARK, pd.Series(dtype=float))

    rows = []
    for etf, meta in SECTORS.items():
        s = prices.get(etf, pd.Series(dtype=float))

        r30 = _pct_change(s, 30)
        r60 = _pct_change(s, 60)
        r90 = _pct_change(s, 90)

        spy30 = _pct_change(spy, 30)
        spy60 = _pct_change(spy, 60)
        spy90 = _pct_change(spy, 90)

        rs30 = (r30 - spy30) if not (np.isnan(r30) or np.isnan(spy30)) else float("nan")
        rs60 = (r60 - spy60) if not (np.isnan(r60) or np.isnan(spy60)) else float("nan")
        rs90 = (r90 - spy90) if not (np.isnan(r90) or np.isnan(spy90)) else float("nan")

        # Momentum score: weight recent periods more heavily
        # If any window is NaN, degrade gracefully
        valid = [(w, v) for w, v in ((0.50, r30), (0.30, r60), (0.20, r90)) if not np.isnan(v)]
        if valid:
            total_w = sum(w for w, _ in valid)
            momentum_score = sum(w * v for w, v in valid) / total_w
        else:
            momentum_score = float("nan")

        # Acceleration flag — compare 30d trend to 90d trend
        if not (np.isnan(r30) or np.isnan(r90)):
            # Annualise so windows are comparable
            ann30 = r30 / 30 * 365
            ann90 = r90 / 90 * 365
            diff  = ann30 - ann90
            if diff > 2.0:
                acceleration = "Accelerating"
            elif diff < -2.0:
                acceleration = "Decelerating"
            else:
                acceleration = "Stable"
        else:
            acceleration = "N/A"

        rows.append({
            "etf":            etf,
            "name":           meta["name"],
            "short":          meta["short"],
            "style":          meta["style"],
            "icon":           meta["icon"],
            "r30":            r30,
            "r60":            r60,
            "r90":            r90,
            "rs30":           rs30,
            "rs60":           rs60,
            "rs90":           rs90,
            "momentum_score": momentum_score,
            "acceleration":   acceleration,
        })

    df = pd.DataFrame(rows)
    # Sort descending by momentum score for the ranking table
    df = df.sort_values("momentum_score", ascending=False, na_position="last")
    df = df.reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


# ══════════════════════════════════════════════════════════════
# HEATMAP FIGURE
# ══════════════════════════════════════════════════════════════

def _build_heatmap(df: pd.DataFrame, show_rs: bool = False) -> go.Figure:
    """
    Interactive Plotly heatmap.

    Y-axis : sectors (sorted best → worst by momentum score)
    X-axis : time periods  30d / 60d / 90d
    Color  : performance % (or RS vs SPY when show_rs=True)
    """
    col_map   = ("rs30", "rs60", "rs90") if show_rs else ("r30", "r60", "r90")
    x_labels  = ["30-Day", "60-Day", "90-Day"]
    y_labels  = [f"{row['icon']} {row['short']}" for _, row in df.iterrows()]

    z_raw = [[row[c] for c in col_map] for _, row in df.iterrows()]
    z     = np.array(z_raw, dtype=float)

    # Symmetric color range around 0
    abs_max = float(np.nanmax(np.abs(z))) if not np.all(np.isnan(z)) else 10.0
    abs_max = max(abs_max, 3.0)   # floor so tiny moves still show color

    # Custom text for each cell
    text = []
    for row_vals in z_raw:
        row_text = []
        for v in row_vals:
            if np.isnan(v):
                row_text.append("N/A")
            else:
                sign = "+" if v >= 0 else ""
                row_text.append(f"{sign}{v:.2f}%")
        text.append(row_text)

    # Hover template
    hover = []
    for i, (_, row) in enumerate(df.iterrows()):
        row_hover = []
        for j, period in enumerate(("30d", "60d", "90d")):
            v   = z_raw[i][j]
            v_s = f"{'+' if v >= 0 else ''}{v:.2f}%" if not np.isnan(v) else "N/A"
            row_hover.append(
                f"<b>{row['name']}</b><br>"
                f"Period: {x_labels[j]}<br>"
                f"{'RS vs SPY' if show_rs else 'Return'}: {v_s}<br>"
                f"Momentum Score: {row['momentum_score']:+.2f}%<br>"
                f"Trend: {row['acceleration']}"
                "<extra></extra>"
            )
        hover.append(row_hover)

    fig = go.Figure(go.Heatmap(
        z             = z,
        x             = x_labels,
        y             = y_labels,
        text          = text,
        texttemplate  = "%{text}",
        textfont      = dict(size=12, color="white",
                             family="IBM Plex Mono, monospace"),
        hovertemplate = "%{customdata}<extra></extra>",
        customdata    = hover,
        colorscale    = [
            [0.00, "#7f1d1d"],   # deep red
            [0.20, "#DC2626"],   # red
            [0.38, "#f87171"],   # light red
            [0.48, "#1e2736"],   # near-zero dark
            [0.50, "#21262d"],   # zero — dark neutral
            [0.52, "#1e3a2a"],   # near-zero dark
            [0.62, "#34d399"],   # light green
            [0.80, "#059669"],   # green
            [1.00, "#064e3b"],   # deep green
        ],
        zmin      = -abs_max,
        zmax      =  abs_max,
        zmid      = 0,
        showscale = True,
        colorbar  = dict(
            title      = dict(
                text = "RS vs SPY (%)" if show_rs else "Return (%)",
                side = "right",
                font = dict(color="#64748B", size=11),
            ),
            tickfont   = dict(color="#8b949e", size=10),
            outlinecolor="#CBD5E1",
            outlinewidth=1,
            len        = 0.85,
            thickness  = 14,
        ),
    ))

    fig.update_layout(**KL(
        height=420,
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor  = _get_active_theme()["chart_bg"],
        paper_bgcolor = _get_active_theme()["chart_paper"],
        xaxis=dict(
            side      = "top",
            tickfont  = dict(color="#475569", size=12, family="Inter, sans-serif"),
            linecolor = "#CBD5E1",
            gridcolor = "rgba(0,0,0,0.04)",
        ),
        yaxis=dict(
            tickfont  = dict(color="#475569", size=12, family="Inter, sans-serif"),
            linecolor = "#CBD5E1",
            gridcolor = "rgba(0,0,0,0.04)",
            autorange = "reversed",
        ),
    ))

    # Accent bar
    fig.add_shape(
        type="line", xref="paper", yref="paper",
        x0=0, x1=1, y0=1, y1=1,
        line=dict(color="#00b4d8", width=2),
        layer="above",
    )

    return fig


# ══════════════════════════════════════════════════════════════
# MOMENTUM RANKING TABLE
# ══════════════════════════════════════════════════════════════

def _momentum_row_html(row: pd.Series, rank: int) -> str:
    """Render one row of the momentum ranking table."""
    score = row["momentum_score"]
    score_s = f"{score:+.2f}%" if not np.isnan(score) else "N/A"
    score_color = "#059669" if (not np.isnan(score) and score >= 0) else "#DC2626"

    acc = row["acceleration"]
    acc_icon  = "🚀" if acc == "Accelerating" else ("📉" if acc == "Decelerating" else "➡️")
    acc_color = "#059669" if acc == "Accelerating" else ("#DC2626" if acc == "Decelerating" else "#64748B")

    style_color = "#2563EB" if row["style"] == "Rotating" else "#7c3aed"
    style_bg    = "#EFF6FF" if row["style"] == "Rotating" else "#F5F3FF"

    r30s = f"{row['r30']:+.1f}%" if not np.isnan(row["r30"]) else "—"
    r60s = f"{row['r60']:+.1f}%" if not np.isnan(row["r60"]) else "—"
    r90s = f"{row['r90']:+.1f}%" if not np.isnan(row["r90"]) else "—"

    rs30s = f"{row['rs30']:+.1f}%" if not np.isnan(row.get("rs30", float("nan"))) else "—"

    rank_color = ("#059669" if rank <= 3 else
                  "#DC2626" if rank >= len(SECTORS) - 2 else
                  "#64748B")

    return f"""
    <tr style="border-bottom:1px solid #F1F5F9;{'background:#F0FDF4;' if rank <= 3 else
                                                'background:#FEF2F2;' if rank >= len(SECTORS)-2 else ''}">
      <td style="padding:9px 12px;font-family:'IBM Plex Mono',monospace;
                 font-size:13px;font-weight:700;color:{rank_color};
                 text-align:center;width:36px;">{rank}</td>
      <td style="padding:9px 12px;font-size:13px;color:#0F172A;font-weight:600;
                 white-space:nowrap;">
        {row['icon']} {row['name']}
      </td>
      <td style="padding:9px 8px;text-align:center;">
        <span style="display:inline-block;padding:2px 10px;border-radius:20px;
                     background:{style_bg};color:{style_color};
                     font-size:11px;font-weight:700;border:1px solid {style_color}33;">
          {row['style']}
        </span>
      </td>
      <td style="padding:9px 12px;text-align:right;font-family:'IBM Plex Mono',monospace;
                 font-size:12px;color:{'#059669' if '+' in r30s else '#DC2626' if '—' not in r30s else '#64748B'};">
        {r30s}
      </td>
      <td style="padding:9px 12px;text-align:right;font-family:'IBM Plex Mono',monospace;
                 font-size:12px;color:{'#059669' if '+' in r60s else '#DC2626' if '—' not in r60s else '#64748B'};">
        {r60s}
      </td>
      <td style="padding:9px 12px;text-align:right;font-family:'IBM Plex Mono',monospace;
                 font-size:12px;color:{'#059669' if '+' in r90s else '#DC2626' if '—' not in r90s else '#64748B'};">
        {r90s}
      </td>
      <td style="padding:9px 12px;text-align:right;font-family:'IBM Plex Mono',monospace;
                 font-size:12px;color:{'#059669' if '+' in rs30s else '#DC2626' if '—' not in rs30s else '#64748B'};">
        {rs30s}
      </td>
      <td style="padding:9px 12px;text-align:center;font-weight:700;
                 font-family:'IBM Plex Mono',monospace;font-size:13px;
                 color:{score_color};">
        {score_s}
      </td>
      <td style="padding:9px 12px;text-align:center;font-size:13px;">
        <span title="{acc}" style="color:{acc_color};">{acc_icon} {acc}</span>
      </td>
    </tr>
    """


def _build_ranking_table(df: pd.DataFrame) -> str:
    header = """
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;
                  font-family:'Inter',sans-serif;font-size:13px;">
      <thead>
        <tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0;">
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:center;">#</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:left;">Sector</th>
          <th style="padding:9px 8px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:center;">Style</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:right;">30D</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:right;">60D</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:right;">90D</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:right;">RS&nbsp;vs&nbsp;SPY</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:center;">Momentum</th>
          <th style="padding:9px 12px;font-size:10px;font-weight:700;
                     letter-spacing:.1em;text-transform:uppercase;color:#64748B;
                     text-align:center;">Trend</th>
        </tr>
      </thead>
      <tbody>
    """
    rows = "".join(
        _momentum_row_html(row, int(row["rank"]))
        for _, row in df.iterrows()
    )
    return header + rows + "</tbody></table></div>"


# ══════════════════════════════════════════════════════════════
# TOP / BOTTOM SECTOR CARDS
# ══════════════════════════════════════════════════════════════

def _sector_card(row: pd.Series, is_top: bool) -> str:
    score = row["momentum_score"]
    score_s = f"{score:+.2f}%" if not np.isnan(score) else "N/A"

    bg_border = "#059669" if is_top else "#DC2626"
    bg_card   = "#F0FDF4" if is_top else "#FEF2F2"
    bg_badge  = "#DCFCE7" if is_top else "#FEE2E2"
    label     = "LEADER" if is_top else "LAGGARD"

    style_color = "#2563EB" if row["style"] == "Rotating" else "#7c3aed"

    r30_s = f"{row['r30']:+.1f}%" if not np.isnan(row["r30"]) else "—"
    r30_color = "#059669" if (not np.isnan(row["r30"]) and row["r30"] >= 0) else "#DC2626"

    acc = row["acceleration"]
    acc_icon = "🚀" if acc == "Accelerating" else ("📉" if acc == "Decelerating" else "➡️")

    return f"""
    <div style="background:{bg_card};border:1.5px solid {bg_border};
                border-radius:12px;padding:16px 18px;position:relative;
                overflow:hidden;height:100%;">
      <div style="position:absolute;top:0;left:0;right:0;height:3px;
                  background:{bg_border};"></div>

      <!-- Label badge -->
      <div style="display:flex;align-items:center;justify-content:space-between;
                  margin-bottom:10px;">
        <span style="font-size:10px;font-weight:700;letter-spacing:.12em;
                     text-transform:uppercase;color:{bg_border};
                     background:{bg_badge};padding:2px 10px;
                     border-radius:20px;">{label}</span>
        <span style="font-size:11px;color:{style_color};font-weight:600;">
          {row['style']}
        </span>
      </div>

      <!-- Sector name -->
      <div style="font-size:18px;font-weight:800;color:#0F172A;
                  font-family:'IBM Plex Mono',monospace;margin-bottom:2px;">
        {row['icon']} {row['etf']}
      </div>
      <div style="font-size:12px;color:#64748B;margin-bottom:12px;">
        {row['name']}
      </div>

      <!-- Metrics row -->
      <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;">
        <div>
          <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                      letter-spacing:.08em;">30D Return</div>
          <div style="font-size:16px;font-weight:700;color:{r30_color};
                      font-family:'IBM Plex Mono',monospace;">{r30_s}</div>
        </div>
        <div style="width:1px;height:32px;background:#E2E8F0;"></div>
        <div>
          <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                      letter-spacing:.08em;">Momentum</div>
          <div style="font-size:16px;font-weight:700;color:{bg_border};
                      font-family:'IBM Plex Mono',monospace;">{score_s}</div>
        </div>
        <div style="width:1px;height:32px;background:#E2E8F0;"></div>
        <div>
          <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                      letter-spacing:.08em;">Trend</div>
          <div style="font-size:13px;font-weight:600;color:#0F172A;">
            {acc_icon} {acc}
          </div>
        </div>
      </div>
    </div>
    """


# ══════════════════════════════════════════════════════════════
# SPY BENCHMARK ROW
# ══════════════════════════════════════════════════════════════

def _spy_banner_html(prices: dict[str, pd.Series]) -> str:
    spy = prices.get(_BENCHMARK, pd.Series(dtype=float))
    r7  = _pct_change(spy, 7)
    r30 = _pct_change(spy, 30)
    r90 = _pct_change(spy, 90)
    ytd_start = datetime(datetime.now().year, 1, 1)
    if not spy.empty:
        spy_ytd_hist = spy[spy.index >= pd.Timestamp(ytd_start)]
        r_ytd = ((float(spy.iloc[-1]) / float(spy_ytd_hist.iloc[0])) - 1) * 100 \
                if len(spy_ytd_hist) >= 2 else float("nan")
        last_price = float(spy.iloc[-1])
        last_date  = spy.index[-1].strftime("%b %d, %Y")
    else:
        r_ytd = float("nan")
        last_price = 0.0
        last_date  = "—"

    def _c(v: float) -> str:
        return "#059669" if (not np.isnan(v) and v >= 0) else "#DC2626"

    def _f(v: float) -> str:
        return f"{v:+.2f}%" if not np.isnan(v) else "—"

    chips = [
        ("7-Day",  r7),
        ("30-Day", r30),
        ("90-Day", r90),
        ("YTD",    r_ytd),
    ]
    chips_html = "".join(f"""
      <div style="text-align:center;padding:0 14px;
                  border-right:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:10px;color:rgba(255,255,255,0.5);
                    text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px;">{lbl}</div>
        <div style="font-size:14px;font-weight:700;color:{_c(v)};
                    font-family:'IBM Plex Mono',monospace;">{_f(v)}</div>
      </div>""" for lbl, v in chips)

    return f"""
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);
                border:1px solid #334155;border-radius:12px;
                padding:14px 20px;margin-bottom:20px;
                display:flex;align-items:center;gap:0;overflow-x:auto;">
      <!-- SPY label -->
      <div style="padding-right:20px;border-right:1px solid rgba(255,255,255,0.1);
                  flex-shrink:0;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;
                    font-weight:800;color:#FFFFFF;">SPY</div>
        <div style="font-size:11px;color:rgba(255,255,255,0.4);">
          S&amp;P 500 ETF
        </div>
        <div style="font-size:13px;font-weight:700;color:#e6edf3;
                    font-family:'IBM Plex Mono',monospace;margin-top:2px;">
          ${last_price:,.2f}
          <span style="font-size:10px;color:rgba(255,255,255,0.35);font-weight:400;">
            {last_date}
          </span>
        </div>
      </div>
      {chips_html}
    </div>
    """


# ══════════════════════════════════════════════════════════════
# MINI MOMENTUM BAR CHART
# ══════════════════════════════════════════════════════════════

def _build_momentum_bar(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart of momentum scores, colored by sign."""
    df_sorted = df.sort_values("momentum_score", ascending=True)

    colors = [
        "#059669" if (not np.isnan(v) and v >= 0) else "#DC2626"
        for v in df_sorted["momentum_score"]
    ]
    labels = [f"{r['icon']} {r['short']}" for _, r in df_sorted.iterrows()]
    values = [v if not np.isnan(v) else 0 for v in df_sorted["momentum_score"]]
    texts  = [f"{v:+.1f}%" if not np.isnan(v) else "N/A" for v in df_sorted["momentum_score"]]

    fig = go.Figure(go.Bar(
        x           = values,
        y           = labels,
        orientation = "h",
        marker_color= colors,
        text        = texts,
        textposition= "outside",
        textfont    = dict(color="#e6edf3", size=11,
                           family="IBM Plex Mono, monospace"),
        hovertemplate = (
            "<b>%{y}</b><br>"
            "Momentum Score: %{x:+.2f}%<extra></extra>"
        ),
    ))

    fig = apply_koyfin(
        fig,
        accent    = "#00b4d8",
        height    = 360,
        title_txt = "Sector Momentum Score  (50% × 30d + 30% × 60d + 20% × 90d)",
        extra_kw  = dict(
            xaxis=dict(
                zeroline     = True,
                zerolinecolor= "#CBD5E1",
                zerolinewidth= 1.5,
                ticksuffix   = "%",
            ),
            bargap=0.35,
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════
# MAIN RENDER
# ══════════════════════════════════════════════════════════════

def render_sector_heatmap() -> None:
    """Full Markets tab. Call from app.py inside `with tab_markets:`."""

    # ── Header ────────────────────────────────────────────────
    st.html("""
    <div style="display:flex;align-items:center;justify-content:space-between;
                margin-bottom:4px;flex-wrap:wrap;gap:8px;">
      <div>
        <div style="font-family:'Barlow Condensed','Inter',sans-serif;
                    font-size:24px;font-weight:700;color:#0F172A;
                    letter-spacing:-.01em;">
          US Sector Heatmap
        </div>
        <div style="font-size:13px;color:#64748B;margin-top:2px;">
          11 GICS sectors · SPDR Select Sector ETFs · S&amp;P 500 · Cached 1 hour
        </div>
      </div>
    </div>
    """)

    # ── Refresh control ───────────────────────────────────────
    ctrl_l, ctrl_r = st.columns([8, 2])
    with ctrl_r:
        if st.button("🔄 Refresh Data", key="_hm_refresh", width='stretch'):
            st.cache_data.clear()
            st.rerun()
    with ctrl_l:
        show_rs = st.toggle(
            "Show Relative Strength vs SPY",
            value=False,
            key="_hm_show_rs",
            help="Toggle heatmap color between absolute return and RS vs S&P 500",
        )

    # ── Fetch & compute ───────────────────────────────────────
    all_tickers = tuple(SECTORS.keys()) + (_BENCHMARK,)
    with st.spinner("Fetching sector data from yfinance…"):
        try:
            prices = _fetch_prices(all_tickers)
        except Exception as exc:
            st.error(f"Data fetch failed: {exc}")
            return

    df = _compute_performance(prices)

    if df["momentum_score"].isna().all():
        st.error("No performance data available. Check your internet connection.")
        return

    # Cache timestamp
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    st.html(f"""
    <div style="font-size:11px;color:#94A3B8;margin-bottom:16px;text-align:right;">
      Data as of market close · Last fetched {ts} · Refreshes hourly
    </div>
    """)

    # ── SPY benchmark banner ──────────────────────────────────
    st.html(_spy_banner_html(prices))

    # ── Top 3 / Bottom 3 cards ────────────────────────────────
    top3    = df.head(3)
    bottom3 = df.tail(3).iloc[::-1]

    st.html("""
    <div style="font-size:11px;font-weight:700;color:#64748B;
                text-transform:uppercase;letter-spacing:.12em;margin-bottom:10px;">
      Sector Leaders
    </div>
    """)
    t_cols = st.columns(3)
    for col, (_, row) in zip(t_cols, top3.iterrows()):
        with col:
            st.html(_sector_card(row, is_top=True))

    st.html('<div style="height:16px;"></div>')

    st.html("""
    <div style="font-size:11px;font-weight:700;color:#64748B;
                text-transform:uppercase;letter-spacing:.12em;margin-bottom:10px;">
      Sector Laggards
    </div>
    """)
    b_cols = st.columns(3)
    for col, (_, row) in zip(b_cols, bottom3.iterrows()):
        with col:
            st.html(_sector_card(row, is_top=False))

    st.html('<div style="height:24px;"></div>')

    # ── Heatmap ───────────────────────────────────────────────
    ccard(
        "Performance Heatmap  —  Relative Strength vs SPY" if show_rs
        else "Performance Heatmap  —  Absolute Returns",
        "#00b4d8",
    )
    st.html("""
    <div style="font-size:12px;color:#94A3B8;margin-bottom:12px;line-height:1.6;">
      Sectors sorted best → worst by Momentum Score (top to bottom).
      Red = underperformance · Green = outperformance · Color anchored at zero.
    </div>
    """)
    heatmap_fig = _build_heatmap(df, show_rs=show_rs)
    st.plotly_chart(heatmap_fig, width='stretch',
                    config={"displayModeBar": False})
    ccard_end()

    # ── Momentum bar chart ────────────────────────────────────
    ccard("Sector Momentum Score", "#7c3aed")
    st.html("""
    <div style="font-size:12px;color:#94A3B8;margin-bottom:12px;line-height:1.6;">
      Composite score = 50% × 30-day + 30% × 60-day + 20% × 90-day return.
      Sectors above zero are in positive momentum; below zero are in negative momentum.
    </div>
    """)
    bar_fig = _build_momentum_bar(df)
    st.plotly_chart(bar_fig, width='stretch',
                    config={"displayModeBar": False})
    ccard_end()

    # ── Momentum ranking table ────────────────────────────────
    ccard("Sector Momentum Ranking", "#1D4ED8")
    st.html("""
    <div style="font-size:12px;color:#94A3B8;margin-bottom:12px;line-height:1.6;">
      <b style="color:#059669;">Rows 1–3 (green)</b> = sector leaders &nbsp;·&nbsp;
      <b style="color:#DC2626;">Rows 9–11 (red)</b> = sector laggards &nbsp;·&nbsp;
      <b>RS vs SPY</b> = 30-day return relative to S&amp;P 500 &nbsp;·&nbsp;
      <b>Rotating</b> = cyclical sectors that outperform in bull markets &nbsp;·&nbsp;
      <b>Defensive</b> = sectors that hold value during downturns
    </div>
    """)
    st.html(_build_ranking_table(df))
    ccard_end()

    # ── Methodology note ─────────────────────────────────────
    st.html("""
    <div style="font-size:11px;color:#94A3B8;margin-top:8px;line-height:1.7;
                padding:10px 14px;background:#F8FAFC;border-radius:8px;
                border-left:3px solid #CBD5E1;">
      <b>Data:</b> SPDR Select Sector ETFs via Yahoo Finance.
      <b>Momentum Score</b> = weighted composite of 30/60/90-day calendar returns
      (50%/30%/20%). <b>Acceleration</b> flags sectors where the annualised 30-day
      trend exceeds the 90-day trend by &gt;2 pp.
      <b>Relative Strength</b> = sector return minus SPY return over the same period.
      All data is informational; not investment advice.
    </div>
    """)
