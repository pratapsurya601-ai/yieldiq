# dashboard/tabs/earnings_tab.py
# ═══════════════════════════════════════════════════════════════════════════
# YieldIQ — Earnings Calendar Tab
# Koyfin-inspired layout:  week-grid  |  table  |  surprise chart  |  macro
# ═══════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# ── Watchlist of mega-cap tickers shown in the weekly calendar ───────────────

_MEGA_CAPS: list[tuple[str, str]] = [
    ("AAPL",  "Apple"),
    ("MSFT",  "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("AMZN",  "Amazon"),
    ("META",  "Meta"),
    ("NVDA",  "NVIDIA"),
    ("TSLA",  "Tesla"),
    ("JPM",   "JPMorgan Chase"),
    ("GS",    "Goldman Sachs"),
    ("MS",    "Morgan Stanley"),
    ("V",     "Visa"),
    ("WMT",   "Walmart"),
    ("HD",    "Home Depot"),
    ("BAC",   "Bank of America"),
    ("NFLX",  "Netflix"),
    ("ORCL",  "Oracle"),
    ("CRM",   "Salesforce"),
]

# ── Hardcoded macro calendar events (update quarterly) ──────────────────────

_MACRO_EVENTS: list[tuple[str, str, str, str, str]] = [
    # (emoji, label, date_str, bg_color, text_color)
    ("📅", "FOMC Meeting",     "Apr 30 – May 1",  "#FEF3C7", "#92400E"),
    ("💼", "Jobs Report",      "May 2",            "#DBEAFE", "#1E40AF"),
    ("📈", "GDP Advance",      "Apr 30",           "#DCFCE7", "#166534"),
    ("📊", "PCE Inflation",    "Apr 25",           "#FCE7F3", "#9D174D"),
    ("📊", "CPI Release",      "May 13",           "#FEF3C7", "#92400E"),
    ("📋", "PPI Release",      "May 14",           "#DBEAFE", "#1E40AF"),
    ("🏦", "Fed Chair Speech", "May 15",           "#DCFCE7", "#166534"),
    ("📅", "FOMC Minutes",     "May 21",           "#FCE7F3", "#9D174D"),
    ("📊", "Core PCE",         "May 30",           "#FEF3C7", "#92400E"),
    ("💼", "Jobs Report",      "Jun 6",            "#DBEAFE", "#1E40AF"),
    ("📅", "FOMC Meeting",     "Jun 11 – 12",      "#DCFCE7", "#166534"),
]

# ── Cached data fetchers ──────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_week_earnings(
    tickers_tuple: tuple[str, ...],
    window_start: str,
    window_end: str,
) -> list[dict]:
    """
    For each ticker, call yf.Ticker.calendar and keep entries whose
    earnings date falls in [window_start, window_end].
    Returns a list of dicts, one per matching ticker.
    """
    ws = datetime.date.fromisoformat(window_start)
    we = datetime.date.fromisoformat(window_end)
    rows: list[dict] = []

    name_map = dict(_MEGA_CAPS)

    for ticker in tickers_tuple:
        try:
            t   = yf.Ticker(ticker)
            cal = t.calendar          # dict  {Earnings Date: [...], EPS Estimate: ..., ...}
            if not isinstance(cal, dict):
                continue

            raw_dates = cal.get("Earnings Date") or cal.get("earningsDate")
            if raw_dates is None:
                continue

            # Normalize to a list
            if not hasattr(raw_dates, "__iter__") or isinstance(raw_dates, str):
                raw_dates = [raw_dates]

            earn_date: Optional[datetime.date] = None
            for rd in raw_dates:
                try:
                    d = pd.to_datetime(rd).date()
                    if ws <= d <= we:
                        earn_date = d
                        break
                except Exception:
                    continue

            if earn_date is None:
                continue

            eps_est = cal.get("EPS Estimate") or cal.get("epsEstimate")
            rev_est = cal.get("Revenue Estimate") or cal.get("revenueEstimate")

            # Last reported EPS + surprise from earnings_history
            last_eps: Optional[float] = None
            surprise: Optional[float] = None
            try:
                eh = t.earnings_history
                if eh is not None and not eh.empty:
                    eh = eh.reset_index()
                    # column names vary across yfinance versions
                    act_col  = next((c for c in eh.columns if "actual" in c.lower()), None)
                    surp_col = next((c for c in eh.columns if "surprise" in c.lower() and "%" in c.lower()), None)
                    if surp_col is None:
                        surp_col = next((c for c in eh.columns if "surprise" in c.lower()), None)
                    if act_col and len(eh):
                        last_eps  = float(eh[act_col].iloc[-1])
                    if surp_col and len(eh):
                        surprise  = float(eh[surp_col].iloc[-1])
            except Exception:
                pass

            rows.append({
                "date":        earn_date,
                "ticker":      ticker,
                "company":     name_map.get(ticker, ticker),
                "eps_est":     float(eps_est) if eps_est is not None else None,
                "rev_est":     float(rev_est) if rev_est is not None else None,
                "last_eps":    last_eps,
                "surprise":    surprise,
            })
        except Exception:
            continue

    rows.sort(key=lambda r: r["date"])
    return rows


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_surprise_history(ticker: str) -> pd.DataFrame:
    """
    Fetch last 8 quarters of EPS actuals + estimates + surprise %.
    Returns a clean DataFrame with columns:
        period, eps_actual, eps_estimate, surprise_pct
    """
    empty = pd.DataFrame(columns=["period", "eps_actual", "eps_estimate", "surprise_pct"])
    try:
        t = yf.Ticker(ticker)

        # Try earnings_history first (yfinance >= 0.2)
        eh = None
        try:
            eh = t.earnings_history
            if eh is not None and not eh.empty:
                eh = eh.reset_index()
        except Exception:
            pass

        # Fallback to earnings_dates
        if eh is None or (hasattr(eh, "empty") and eh.empty):
            try:
                ed = t.earnings_dates
                if ed is not None and not ed.empty:
                    eh = ed.reset_index()
            except Exception:
                pass

        if eh is None or eh.empty:
            return empty

        # Normalise column names
        col = lambda *candidates: next(
            (c for c in candidates if c in eh.columns), None
        )
        date_col  = col("Earnings Date", "earningsDate", "date", "index")
        act_col   = col("EPS Actual", "epsActual", "Reported EPS", "actual")
        est_col   = col("EPS Estimate", "epsEstimate", "estimate")
        surp_col  = col("Surprise(%)", "surprisePercent", "epsSurprisePct", "surprise_pct", "Surprise(%)")

        if act_col is None:
            return empty

        df = pd.DataFrame()
        if date_col:
            df["period"] = pd.to_datetime(eh[date_col], errors="coerce")
        else:
            df["period"] = pd.to_datetime("today")

        df["eps_actual"]   = pd.to_numeric(eh[act_col],  errors="coerce") if act_col  else float("nan")
        df["eps_estimate"] = pd.to_numeric(eh[est_col],  errors="coerce") if est_col  else float("nan")
        df["surprise_pct"] = pd.to_numeric(eh[surp_col], errors="coerce") if surp_col else float("nan")

        # Compute surprise_pct where missing
        mask = df["surprise_pct"].isna() & df["eps_estimate"].notna() & df["eps_actual"].notna()
        with_est = df.loc[mask, "eps_estimate"] != 0
        df.loc[mask & with_est, "surprise_pct"] = (
            (df.loc[mask & with_est, "eps_actual"] - df.loc[mask & with_est, "eps_estimate"])
            / df.loc[mask & with_est, "eps_estimate"].abs() * 100
        )

        df = df.dropna(subset=["eps_actual"]).sort_values("period").tail(8).reset_index(drop=True)
        df["period"] = df["period"].dt.strftime("%b '%y")
        return df

    except Exception:
        return empty


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_week_grid(rows: list[dict], week_days: list[datetime.date]) -> None:
    """Koyfin-style 5-column day grid rendered with st.html()."""
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    # Group rows by date
    by_day: dict[datetime.date, list[dict]] = {d: [] for d in week_days}
    for row in rows:
        if row["date"] in by_day:
            by_day[row["date"]].append(row)

    today = datetime.date.today()

    # Build column HTML blocks
    cols_html = ""
    for i, day in enumerate(week_days):
        is_today   = (day == today)
        is_past    = (day < today)
        day_header_bg    = "#1A2540" if is_today else "#F8FAFC"
        day_header_color = "#FFFFFF" if is_today else ("#94A3B8" if is_past else "#0F172A")
        day_border       = "#1D4ED8" if is_today else "#E2E8F0"
        day_opacity      = "0.55" if is_past else "1"

        cards_html = ""
        for r in by_day[day]:
            eps_str = f"${r['eps_est']:.2f}" if r["eps_est"] is not None else "—"
            rev_str = ""
            if r["rev_est"] is not None:
                rev_b = r["rev_est"] / 1e9
                rev_str = f" · ${rev_b:.1f}B" if rev_b >= 1 else f" · ${r['rev_est']/1e6:.0f}M"
            surp_badge = ""
            if r["surprise"] is not None:
                sc  = "#16a34a" if r["surprise"] >= 0 else "#dc2626"
                sbg = "#DCFCE7" if r["surprise"] >= 0 else "#FEE2E2"
                surp_badge = (
                    f'<span style="font-size:9px;font-weight:700;color:{sc};'
                    f'background:{sbg};border-radius:4px;padding:1px 5px;margin-left:4px;">'
                    f'{"+" if r["surprise"]>=0 else ""}{r["surprise"]:.1f}%</span>'
                )
            cards_html += f"""
<div style="background:#FFFFFF;border:1px solid #E8EEF7;border-radius:8px;
            padding:8px 10px;margin-bottom:6px;
            box-shadow:0 1px 2px rgba(15,23,42,0.04);">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                 font-weight:700;color:#1D4ED8;">{r["ticker"]}</span>
    {surp_badge}
  </div>
  <div style="font-size:10px;color:#475569;
              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
              margin-bottom:4px;">{r["company"]}</div>
  <div style="font-size:10px;color:#94A3B8;
              font-family:'IBM Plex Mono',monospace;">
    EPS Est: <span style="color:#0F172A;font-weight:600;">{eps_str}</span>{rev_str}
  </div>
</div>"""

        if not cards_html:
            cards_html = (
                '<div style="font-size:10px;color:#CBD5E1;'
                'text-align:center;padding:16px 0;">—</div>'
            )

        cols_html += f"""
<div style="flex:1;min-width:0;opacity:{day_opacity};">
  <div style="background:{day_header_bg};color:{day_header_color};
              border:1px solid {day_border};border-radius:8px 8px 0 0;
              padding:7px 10px;font-size:11px;font-weight:700;
              font-family:'Inter',sans-serif;text-align:center;
              letter-spacing:0.04em;margin-bottom:6px;">
    {DAY_NAMES[i]}<br>
    <span style="font-size:10px;font-weight:400;opacity:0.75;">
      {day.strftime("%b %d")}
    </span>
  </div>
  {cards_html}
</div>"""

    st.html(f"""
<div style="display:flex;gap:10px;align-items:flex-start;margin:4px 0 16px;">
  {cols_html}
</div>
""")


def _render_table_styled(rows: list[dict]) -> None:
    """Styled st.dataframe() table of upcoming earnings."""
    if not rows:
        st.info("No earnings scheduled in this period for the tracked tickers.", icon="📭")
        return

    def _fmt_eps(v: Optional[float]) -> str:
        return f"${v:.2f}" if v is not None else "—"

    def _fmt_rev(v: Optional[float]) -> str:
        if v is None:
            return "—"
        if v >= 1e9:
            return f"${v/1e9:.2f}B"
        if v >= 1e6:
            return f"${v/1e6:.0f}M"
        return f"${v:,.0f}"

    def _fmt_surp(v: Optional[float]) -> str:
        if v is None:
            return "—"
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

    df = pd.DataFrame([{
        "Date":        r["date"].strftime("%a, %b %d"),
        "Company":     r["company"],
        "Ticker":      r["ticker"],
        "EPS Est.":    _fmt_eps(r["eps_est"]),
        "Rev Est.":    _fmt_rev(r["rev_est"]),
        "Last EPS":    _fmt_eps(r["last_eps"]),
        "Surprise %":  _fmt_surp(r["surprise"]),
    } for r in rows])

    st.markdown("""
<style>
div[data-testid="stDataFrame"] table {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 13px !important;
    border-collapse: collapse !important;
    width: 100% !important;
}
div[data-testid="stDataFrame"] thead th {
    background: #1A2540 !important;
    color: white !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    padding: 10px 12px !important;
    border: none !important;
}
div[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
    background: #F8FAFC !important;
}
div[data-testid="stDataFrame"] tbody tr:hover td {
    background: #EFF6FF !important;
}
div[data-testid="stDataFrame"] tbody td {
    padding: 9px 12px !important;
    border-bottom: 1px solid #F1F5F9 !important;
    color: #0F172A !important;
}
</style>
""", unsafe_allow_html=True)

    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_surprise_chart(ticker: str) -> None:
    """8-quarter EPS beat/miss bar chart for a given ticker."""
    if not ticker:
        st.info("Run a Stock Analysis first to see the earnings history for a specific stock.", icon="🔍")
        return

    with st.spinner(f"Loading earnings history for {ticker}…"):
        df = _fetch_surprise_history(ticker)

    if df.empty:
        st.info(f"No earnings history available for {ticker}.", icon="📭")
        return

    has_surp = df["surprise_pct"].notna().any()
    has_act  = df["eps_actual"].notna().any()
    has_est  = df["eps_estimate"].notna().any()

    fig = go.Figure()

    # EPS estimate bars (light blue background)
    if has_est:
        fig.add_trace(go.Bar(
            x=df["period"],
            y=df["eps_estimate"],
            name="Estimate",
            marker=dict(color="#BFDBFE", opacity=0.85, line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Estimate: $%{y:.2f}<extra></extra>",
        ))

    # EPS actual bars (green = beat, red = miss)
    if has_act:
        colors = []
        for _, row in df.iterrows():
            act = row["eps_actual"]
            est = row["eps_estimate"] if pd.notna(row["eps_estimate"]) else act
            colors.append("#059669" if float(act) >= float(est) else "#DC2626")

        fig.add_trace(go.Bar(
            x=df["period"],
            y=df["eps_actual"],
            name="Actual EPS",
            marker=dict(color=colors, opacity=0.9, line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Actual: $%{y:.2f}<extra></extra>",
        ))

    # Surprise % as scatter on secondary y-axis
    if has_surp:
        surp_colors = ["#059669" if v >= 0 else "#DC2626"
                       for v in df["surprise_pct"].fillna(0)]
        fig.add_trace(go.Scatter(
            x=df["period"],
            y=df["surprise_pct"],
            name="Surprise %",
            mode="lines+markers",
            yaxis="y2",
            line=dict(color="#6366F1", width=1.5, dash="dot"),
            marker=dict(color=surp_colors, size=7, line=dict(color="#FFFFFF", width=1.5)),
            hovertemplate="<b>%{x}</b><br>Surprise: %{y:+.1f}%<extra></extra>",
        ))

    fig.update_layout(
        barmode="overlay",
        title=dict(
            text=f"{ticker.upper()} — 8 Quarter Earnings History",
            font=dict(family="Inter, sans-serif", size=14, color="#0F172A"),
            x=0,
            pad=dict(l=0, t=0),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family="IBM Plex Mono, monospace", color="#64748B", size=10),
        margin=dict(t=40, b=40, l=10, r=10),
        height=280,
        xaxis=dict(
            showgrid=False,
            tickfont=dict(family="IBM Plex Mono, monospace", size=10),
            linecolor="#E2E8F0",
        ),
        yaxis=dict(
            title="EPS ($)",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.04)",
            tickfont=dict(family="IBM Plex Mono, monospace", size=10),
            tickprefix="$",
            zeroline=True,
            zerolinecolor="#E2E8F0",
            zerolinewidth=1,
        ),
        yaxis2=dict(
            title="Surprise %",
            overlaying="y",
            side="right",
            showgrid=False,
            tickfont=dict(family="IBM Plex Mono, monospace", size=10),
            ticksuffix="%",
            zeroline=False,
        ) if has_surp else {},
        legend=dict(
            orientation="h",
            y=1.08,
            x=0,
            font=dict(size=10, family="Inter, sans-serif"),
            bgcolor="rgba(0,0,0,0)",
        ),
    )

    # Zero line annotation
    fig.add_hline(y=0, line_width=1, line_dash="solid", line_color="#CBD5E1")

    # Beat/miss annotation per bar
    if has_act and has_est:
        for _, row in df.iterrows():
            if pd.notna(row["eps_actual"]) and pd.notna(row["eps_estimate"]):
                beat = float(row["eps_actual"]) >= float(row["eps_estimate"])
                fig.add_annotation(
                    x=row["period"],
                    y=float(row["eps_actual"]),
                    text="✓" if beat else "✗",
                    showarrow=False,
                    yshift=10,
                    font=dict(size=10, color="#059669" if beat else "#DC2626"),
                )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Beat-rate KPI strip
    if has_act and has_est and len(df) >= 2:
        beats   = int(sum(
            float(r["eps_actual"]) >= float(r["eps_estimate"])
            for _, r in df.iterrows()
            if pd.notna(r["eps_actual"]) and pd.notna(r["eps_estimate"])
        ))
        total   = len(df)
        br      = beats / total * 100
        br_clr  = "#059669" if br >= 70 else "#D97706" if br >= 50 else "#DC2626"
        avg_surp = df["surprise_pct"].mean() if has_surp else None
        as_clr   = "#059669" if avg_surp and avg_surp >= 0 else "#DC2626"

        st.html(f"""
<div style="display:flex;gap:10px;margin-top:4px;">
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
              padding:10px 16px;flex:1;text-align:center;">
    <div style="font-size:9px;font-weight:700;color:#94A3B8;
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px;">Beat Rate</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;
                font-weight:700;color:{br_clr};">{br:.0f}%</div>
    <div style="font-size:9px;color:#94A3B8;">{beats} of {total} quarters</div>
  </div>
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
              padding:10px 16px;flex:1;text-align:center;">
    <div style="font-size:9px;font-weight:700;color:#94A3B8;
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px;">Avg Surprise</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;
                font-weight:700;color:{as_clr};">
      {"+" if avg_surp and avg_surp >= 0 else ""}{f"{avg_surp:.1f}%" if avg_surp is not None else "—"}
    </div>
    <div style="font-size:9px;color:#94A3B8;">vs consensus</div>
  </div>
  <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
              padding:10px 16px;flex:1;text-align:center;">
    <div style="font-size:9px;font-weight:700;color:#94A3B8;
                text-transform:uppercase;letter-spacing:0.12em;margin-bottom:4px;">Last EPS</div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;
                font-weight:700;color:#0F172A;">
      {"$" + f"{float(df['eps_actual'].iloc[-1]):.2f}" if pd.notna(df["eps_actual"].iloc[-1]) else "—"}
    </div>
    <div style="font-size:9px;color:#94A3B8;">most recent quarter</div>
  </div>
</div>
""")


def _render_macro_events() -> None:
    """Render macro economic calendar as colored chip tags."""
    chips_html = ""
    for emoji, label, date_str, bg, fg in _MACRO_EVENTS:
        chips_html += (
            f'<span style="display:inline-flex;align-items:center;gap:5px;'
            f'background:{bg};color:{fg};padding:5px 12px;'
            f'border-radius:20px;font-size:12px;font-family:Inter,sans-serif;'
            f'font-weight:500;white-space:nowrap;">'
            f'{emoji} <strong>{label}</strong>'
            f'<span style="opacity:0.7;margin-left:2px;">— {date_str}</span>'
            f'</span>'
        )

    st.html(f"""
<div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px;">
  {chips_html}
</div>
""")


def _section_header(title: str, subtitle: str = "") -> None:
    sub_html = (
        f'<span style="font-size:12px;font-weight:400;color:#94A3B8;margin-left:10px;">'
        f'{subtitle}</span>'
    ) if subtitle else ""
    st.markdown(
        f'<div style="font-size:13px;font-weight:700;color:#0F172A;'
        f'letter-spacing:0.01em;margin:22px 0 10px;display:flex;align-items:baseline;">'
        f'{title}{sub_html}</div>',
        unsafe_allow_html=True,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def render_earnings_tab(ticker: str = "") -> None:
    """
    Render the full Earnings Calendar page.
    ticker: currently analysed stock ticker (for the surprise history section).
    """
    # Page header
    st.markdown(
        '<h2 style="font-size:22px;font-weight:700;color:#0F172A;'
        'font-family:Inter,sans-serif;margin-bottom:4px;">Earnings Calendar</h2>'
        '<p style="font-size:13px;color:#64748B;margin-bottom:20px;">'
        'Upcoming earnings for US mega-caps · EPS surprise history · Macro events</p>',
        unsafe_allow_html=True,
    )

    today     = datetime.date.today()
    # Find Mon of the current week
    week_mon  = today - datetime.timedelta(days=today.weekday())
    week_fri  = week_mon + datetime.timedelta(days=4)
    # Month window
    month_end = (today.replace(day=1) + datetime.timedelta(days=31)).replace(day=1) - datetime.timedelta(days=1)

    tickers_tuple = tuple(t for t, _ in _MEGA_CAPS)

    # ── SECTION 1 — Upcoming Earnings ────────────────────────────────────────
    _section_header(
        "Upcoming Earnings",
        f"Week of {week_mon.strftime('%b %d')} – {week_fri.strftime('%b %d, %Y')}",
    )

    view_tab_week, view_tab_month = st.tabs(["📅  This Week", "🗓️  This Month"])

    # ── Weekly tab ───────────────────────────────────────────────────────────
    with view_tab_week:
        with st.spinner("Fetching earnings schedules…"):
            week_rows = _fetch_week_earnings(
                tickers_tuple,
                week_mon.isoformat(),
                week_fri.isoformat(),
            )

        if week_rows:
            week_days = [week_mon + datetime.timedelta(days=i) for i in range(5)]
            _render_week_grid(week_rows, week_days)
            _section_header("Earnings Detail", f"{len(week_rows)} companies this week")
            _render_table_styled(week_rows)
        else:
            st.html("""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
            padding:40px;text-align:center;margin:12px 0;">
  <div style="font-size:32px;margin-bottom:12px;">📭</div>
  <div style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:6px;">
    No major earnings this week
  </div>
  <div style="font-size:13px;color:#64748B;">
    None of the tracked mega-caps report earnings in the next 7 days.
    Check the "This Month" tab for upcoming reports.
  </div>
</div>
""")

    # ── Monthly tab ──────────────────────────────────────────────────────────
    with view_tab_month:
        with st.spinner("Fetching monthly earnings…"):
            month_rows = _fetch_week_earnings(
                tickers_tuple,
                today.isoformat(),
                month_end.isoformat(),
            )

        if month_rows:
            # Group by week for sub-headers
            shown_weeks: set[datetime.date] = set()
            week_groups: dict[datetime.date, list[dict]] = {}
            for r in month_rows:
                wmon = r["date"] - datetime.timedelta(days=r["date"].weekday())
                if wmon not in week_groups:
                    week_groups[wmon] = []
                week_groups[wmon].append(r)

            for wmon in sorted(week_groups):
                wfri = wmon + datetime.timedelta(days=4)
                wdays = [wmon + datetime.timedelta(days=i) for i in range(5)]
                label = (
                    "This week" if wmon == week_mon
                    else f"Week of {wmon.strftime('%b %d')}"
                )
                st.markdown(
                    f'<div style="font-size:11px;font-weight:700;color:#64748B;'
                    f'text-transform:uppercase;letter-spacing:0.1em;margin:16px 0 6px;">'
                    f'{label} · {wmon.strftime("%b %d")} – {wfri.strftime("%b %d")}</div>',
                    unsafe_allow_html=True,
                )
                _render_week_grid(week_groups[wmon], wdays)

            _section_header("Full Month Detail", f"{len(month_rows)} companies")
            _render_table_styled(month_rows)
        else:
            st.info("No major earnings remaining this month for tracked tickers.", icon="📭")

    # ── SECTION 2 — Earnings Surprise History ────────────────────────────────
    st.markdown("<hr style='border:none;border-top:1px solid #E2E8F0;margin:24px 0 0;'>",
                unsafe_allow_html=True)

    ticker_display = ticker.upper() if ticker else ""
    _section_header(
        "Earnings Surprise History",
        ticker_display or "Select a stock in Stock Analysis",
    )

    if ticker:
        _render_surprise_chart(ticker)
    else:
        # Allow ad-hoc ticker input directly on this tab
        _adhoc_col, _ = st.columns([2, 3])
        with _adhoc_col:
            _adhoc = st.text_input(
                "Enter ticker",
                placeholder="AAPL",
                key="earnings_tab_adhoc_ticker",
                label_visibility="collapsed",
            )
        if _adhoc:
            _render_surprise_chart(_adhoc.strip().upper())
        else:
            st.caption("Enter a ticker above or run a Stock Analysis to auto-populate.")

    # ── SECTION 3 — Macro Events ─────────────────────────────────────────────
    st.markdown("<hr style='border:none;border-top:1px solid #E2E8F0;margin:24px 0 0;'>",
                unsafe_allow_html=True)
    _section_header("Key Macro Events", "Fed · CPI · Jobs · GDP")
    _render_macro_events()
    st.caption(
        "Dates are approximate and subject to change. "
        "Source: Federal Reserve, BLS, BEA."
    )
