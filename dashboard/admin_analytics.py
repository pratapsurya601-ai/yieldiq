# dashboard/admin_analytics.py
# ════════════════════════════════════════════════════════════════
# YieldIQ — Admin Analytics System
#
# Tracks every meaningful product event in analytics.db, then
# renders a protected Streamlit dashboard when YIELDIQ_ADMIN=1.
#
# ── Tracked events ──────────────────────────────────────────────
#   analysis_events  : every stock analysis run (ticker, signal, tier…)
#   event_log        : report_download | pdf_download | screener_run |
#                      watchlist_add | alert_triggered | login | signup
#
# ── Public tracking API (call from app.py) ──────────────────────
#   init_analytics_db()
#   track_analysis(user_email, tier, ticker, signal, mos_pct, wacc,
#                  market='', duration_ms=None)
#   track_event(user_email, tier, event_type, meta=None)
#
# ── Admin dashboard ─────────────────────────────────────────────
#   render_admin_dashboard()   — only works when YIELDIQ_ADMIN=1
#
# ── Export ──────────────────────────────────────────────────────
#   export_analytics_zip(days=30) -> bytes  (ZIP with CSVs)
# ════════════════════════════════════════════════════════════════

from __future__ import annotations

import io
import json
import os
import pathlib
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Any

import streamlit as st

# ── optional heavy imports (guarded so tracking never crashes app) ──
try:
    import pandas as pd
    _PD = True
except ImportError:
    _PD = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PX = True
except ImportError:
    _PX = False

# ════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════

_DB_PATH   = pathlib.Path(os.environ.get("YIELDIQ_DATA_DIR", str(pathlib.Path(__file__).parent))) / "analytics.db"
_AUTH_PATH = pathlib.Path(os.environ.get("YIELDIQ_DATA_DIR", str(pathlib.Path(__file__).parent))) / "auth.db"
_lock      = threading.Lock()

_ADMIN_ENV = "YIELDIQ_ADMIN"

_TIER_PRICES  = {"free": 0, "starter": 19, "premium": 19, "pro": 49}
_TIER_COLORS  = {"free": "#64748B", "starter": "#5046e4", "premium": "#5046e4", "pro": "#059669"}
_SIGNAL_ORDER = ["STRONG BUY", "BUY", "WATCH", "HOLD", "SELL", "STRONG SELL"]
_SIGNAL_COLS  = {
    "STRONG BUY":  "#059669", "BUY": "#16a34a",
    "WATCH":       "#d97706", "HOLD": "#2563eb",
    "SELL":        "#dc2626", "STRONG SELL": "#7f1d1d",
}

_EVENT_LABELS = {
    "report_download":  "Excel Report",
    "pdf_download":     "PDF Report",
    "screener_run":     "Screener Run",
    "watchlist_add":    "Watchlist Add",
    "alert_triggered":  "Alert Triggered",
    "login":            "Login",
    "signup":           "Signup",
}

# ════════════════════════════════════════════════════════════════
# DB SETUP
# ════════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_analytics_db() -> None:
    """Create analytics tables. Safe to call on every startup."""
    with _lock:
        c = _conn()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS analysis_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email  TEXT    NOT NULL DEFAULT '',
            tier        TEXT    NOT NULL DEFAULT 'free',
            ticker      TEXT    NOT NULL,
            signal      TEXT    DEFAULT '',
            mos_pct     REAL    DEFAULT 0,
            wacc        REAL    DEFAULT 0,
            market      TEXT    DEFAULT '',
            ts          TEXT    NOT NULL,
            duration_ms INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS event_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email  TEXT    NOT NULL DEFAULT '',
            tier        TEXT    NOT NULL DEFAULT 'free',
            event_type  TEXT    NOT NULL,
            meta        TEXT    DEFAULT '{}',
            ts          TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ae_ts      ON analysis_events(ts);
        CREATE INDEX IF NOT EXISTS idx_ae_ticker  ON analysis_events(ticker);
        CREATE INDEX IF NOT EXISTS idx_ae_email   ON analysis_events(user_email);
        CREATE INDEX IF NOT EXISTS idx_el_ts      ON event_log(ts);
        CREATE INDEX IF NOT EXISTS idx_el_type    ON event_log(event_type);
        CREATE INDEX IF NOT EXISTS idx_el_email   ON event_log(user_email);
        """)
        c.commit()
        c.close()


# ════════════════════════════════════════════════════════════════
# EVENT TRACKING (fire-and-forget — exceptions must not surface)
# ════════════════════════════════════════════════════════════════

def track_analysis(
    user_email:  str,
    tier:        str,
    ticker:      str,
    signal:      str   = "",
    mos_pct:     float = 0.0,
    wacc:        float = 0.0,
    market:      str   = "",
    duration_ms: int   = 0,
) -> None:
    """Record a completed stock analysis. Never raises."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        # Infer market from ticker if not provided
        if not market:
            market = "india" if ticker.endswith(".NS") or ticker.endswith(".BO") else "us"
        with _lock:
            c = _conn()
            c.execute(
                "INSERT INTO analysis_events "
                "(user_email, tier, ticker, signal, mos_pct, wacc, market, ts, duration_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (user_email or "", tier or "free", ticker.upper(),
                 signal or "", float(mos_pct or 0), float(wacc or 0),
                 market, ts, int(duration_ms or 0)),
            )
            c.commit()
            c.close()
    except Exception:
        pass  # tracking must never crash the main app


def track_event(
    user_email: str,
    tier:       str,
    event_type: str,
    meta:       dict | None = None,
) -> None:
    """Record any product event. Never raises."""
    try:
        ts       = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(meta or {})
        with _lock:
            c = _conn()
            c.execute(
                "INSERT INTO event_log (user_email, tier, event_type, meta, ts) "
                "VALUES (?,?,?,?,?)",
                (user_email or "", tier or "free", event_type, meta_str, ts),
            )
            c.commit()
            c.close()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# DATA QUERY HELPERS  (all return pd.DataFrame or plain dict)
# ════════════════════════════════════════════════════════════════

def _query_df(sql: str, params: tuple = (), db: str = "analytics") -> "pd.DataFrame":
    """Run a SELECT and return a DataFrame. Returns empty DF on error."""
    if not _PD:
        return None  # type: ignore
    try:
        path = str(_DB_PATH) if db == "analytics" else str(_AUTH_PATH)
        c = sqlite3.connect(path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        rows = c.execute(sql, params).fetchall()
        c.close()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


def _summary_metrics(days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    # Analyses
    total_analyses = _query_df(
        "SELECT COUNT(*) AS n FROM analysis_events WHERE ts >= ?", (since,)
    )
    analyses_today = _query_df(
        "SELECT COUNT(*) AS n FROM analysis_events WHERE date(ts)=date('now')", ()
    )

    # DAU / MAU
    dau = _query_df(
        "SELECT COUNT(DISTINCT user_email) AS n FROM analysis_events WHERE date(ts)=date('now')", ()
    )
    mau = _query_df(
        "SELECT COUNT(DISTINCT user_email) AS n FROM analysis_events WHERE ts >= ?", (since,)
    )

    # Total users from auth.db
    users_df = _query_df("SELECT COUNT(*) AS n FROM users WHERE is_active=1", db="auth")
    users_by_tier = _query_df(
        "SELECT tier, COUNT(*) AS cnt FROM users WHERE is_active=1 GROUP BY tier", db="auth"
    )

    # MRR estimate
    mrr = 0
    if _PD and users_by_tier is not None and not users_by_tier.empty:
        for _, row in users_by_tier.iterrows():
            mrr += _TIER_PRICES.get(row["tier"], 0) * int(row["cnt"])

    def _n(df):
        if df is None or df.empty:
            return 0
        return int(df.iloc[0]["n"])

    return {
        "total_users":      _n(users_df),
        "dau":              _n(dau),
        "mau":              _n(mau),
        "analyses_today":   _n(analyses_today),
        "analyses_30d":     _n(total_analyses),
        "mrr_estimate":     mrr,
    }


def _dau_series(days: int = 30) -> "pd.DataFrame":
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _query_df(
        """
        SELECT date(ts) AS day,
               COUNT(DISTINCT user_email) AS dau,
               COUNT(*) AS analyses
        FROM analysis_events
        WHERE ts >= ?
        GROUP BY date(ts)
        ORDER BY day
        """,
        (since,),
    )


def _top_tickers(n: int = 20, days: int = 30) -> "pd.DataFrame":
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _query_df(
        """
        SELECT ticker,
               COUNT(*)        AS runs,
               ROUND(AVG(mos_pct), 1) AS avg_mos,
               COUNT(DISTINCT user_email) AS unique_users
        FROM analysis_events
        WHERE ts >= ?
        GROUP BY ticker
        ORDER BY runs DESC
        LIMIT ?
        """,
        (since, n),
    )


def _tier_distribution() -> "pd.DataFrame":
    return _query_df(
        "SELECT tier, COUNT(*) AS count FROM users WHERE is_active=1 GROUP BY tier",
        db="auth",
    )


def _feature_usage_by_tier(days: int = 30) -> "pd.DataFrame":
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    df = _query_df(
        """
        SELECT event_type, tier, COUNT(*) AS cnt
        FROM event_log
        WHERE ts >= ? AND event_type IN
              ('report_download','pdf_download','screener_run','watchlist_add','alert_triggered')
        GROUP BY event_type, tier
        """,
        (since,),
    )
    if df is None or df.empty:
        return pd.DataFrame()
    # Pivot: rows = event_type, cols = tier
    try:
        pivot = df.pivot_table(
            index="event_type", columns="tier", values="cnt", aggfunc="sum", fill_value=0
        ).reset_index()
        pivot["event_label"] = pivot["event_type"].map(
            lambda x: _EVENT_LABELS.get(x, x)
        )
        return pivot
    except Exception:
        return df


def _signal_distribution(days: int = 30) -> "pd.DataFrame":
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _query_df(
        """
        SELECT signal, COUNT(*) AS count
        FROM analysis_events
        WHERE ts >= ? AND signal != ''
        GROUP BY signal
        ORDER BY count DESC
        """,
        (since,),
    )


def _conversion_funnel() -> list[dict]:
    """
    Returns funnel stages as a list of {stage, count, pct_of_prev}.
    Stages: Signup → First Analysis → Watchlist Add → Any Report → Upgrade
    """
    signups = _query_df(
        "SELECT COUNT(*) AS n FROM users WHERE is_active=1", db="auth"
    )
    analysed = _query_df(
        "SELECT COUNT(DISTINCT user_email) AS n FROM analysis_events WHERE user_email != ''"
    )
    watchlisted = _query_df(
        "SELECT COUNT(DISTINCT user_email) AS n FROM event_log "
        "WHERE event_type='watchlist_add' AND user_email != ''"
    )
    downloaded = _query_df(
        "SELECT COUNT(DISTINCT user_email) AS n FROM event_log "
        "WHERE event_type IN ('report_download','pdf_download') AND user_email != ''"
    )
    upgraded = _query_df(
        "SELECT COUNT(*) AS n FROM users WHERE tier != 'free' AND is_active=1", db="auth"
    )

    def _n(df):
        if df is None or df.empty:
            return 0
        return int(df.iloc[0]["n"])

    stages = [
        ("Signup",          _n(signups)),
        ("First Analysis",  _n(analysed)),
        ("Watchlist Add",   _n(watchlisted)),
        ("Report Download", _n(downloaded)),
        ("Upgraded",        _n(upgraded)),
    ]
    funnel = []
    for i, (label, count) in enumerate(stages):
        prev = stages[i - 1][1] if i > 0 else count
        pct  = round(count / prev * 100, 1) if prev else 0.0
        funnel.append({"stage": label, "count": count, "pct_of_prev": pct})
    return funnel


def _recent_events(limit: int = 100) -> "pd.DataFrame":
    return _query_df(
        """
        SELECT ts, 'analysis' AS category, user_email, tier,
               ticker || ' → ' || signal AS detail
        FROM analysis_events
        UNION ALL
        SELECT ts, 'event' AS category, user_email, tier,
               event_type AS detail
        FROM event_log
        ORDER BY ts DESC
        LIMIT ?
        """,
        (limit,),
    )


def _market_breakdown(days: int = 30) -> "pd.DataFrame":
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _query_df(
        """
        SELECT market, COUNT(*) AS count,
               ROUND(AVG(mos_pct), 1) AS avg_mos
        FROM analysis_events
        WHERE ts >= ? AND market != ''
        GROUP BY market
        """,
        (since,),
    )


# ════════════════════════════════════════════════════════════════
# CSV / ZIP EXPORT
# ════════════════════════════════════════════════════════════════

def export_analytics_zip(days: int = 30) -> bytes:
    """
    Build a ZIP containing multiple CSVs for offline analysis.
    Returns raw bytes suitable for st.download_button().
    """
    if not _PD:
        return b""

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def _safe(df):
        return df if df is not None else pd.DataFrame()

    sheets: dict[str, "pd.DataFrame"] = {
        f"analysis_events_{days}d.csv": _safe(_query_df(
            "SELECT * FROM analysis_events WHERE ts >= ? ORDER BY ts DESC", (since,)
        )),
        f"event_log_{days}d.csv": _safe(_query_df(
            "SELECT * FROM event_log WHERE ts >= ? ORDER BY ts DESC", (since,)
        )),
        f"dau_series_{days}d.csv":          _safe(_dau_series(days)),
        f"top_tickers_{days}d.csv":         _safe(_top_tickers(20, days)),
        "tier_distribution.csv":            _safe(_tier_distribution()),
        f"signal_distribution_{days}d.csv": _safe(_signal_distribution(days)),
        "conversion_funnel.csv":            pd.DataFrame(_conversion_funnel()),
        f"feature_usage_{days}d.csv":       _safe(_feature_usage_by_tier(days)),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, df in sheets.items():
            if df is not None and not df.empty:
                zf.writestr(filename, df.to_csv(index=False))
            else:
                zf.writestr(filename, "")  # empty placeholder
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
# CHART BUILDERS
# ════════════════════════════════════════════════════════════════

def _chart_dau(df: "pd.DataFrame") -> "go.Figure":
    fig = go.Figure()
    if df is None or df.empty:
        fig.add_annotation(text="No data yet", showarrow=False,
                           font=dict(color="#475569", size=14))
        return _style_fig(fig)

    fig.add_trace(go.Bar(
        x=df["day"], y=df["analyses"],
        name="Analyses", marker_color="#1D4ED8", opacity=0.5,
        yaxis="y2",
    ))
    fig.add_trace(go.Scatter(
        x=df["day"], y=df["dau"],
        name="DAU (unique users)", mode="lines+markers",
        line=dict(color="#22D3EE", width=2),
        marker=dict(size=5),
    ))
    fig.update_layout(
        yaxis=dict(title="Unique Users (DAU)", gridcolor="rgba(0,0,0,0.04)"),
        yaxis2=dict(title="Total Analyses", overlaying="y", side="right",
                    gridcolor="rgba(255,255,255,0.0)"),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        barmode="overlay",
    )
    return _style_fig(fig)


def _chart_top_tickers(df: "pd.DataFrame") -> "go.Figure":
    fig = go.Figure()
    if df is None or df.empty:
        fig.add_annotation(text="No data yet", showarrow=False,
                           font=dict(color="#475569", size=14))
        return _style_fig(fig)

    df = df.sort_values("runs", ascending=True)
    colors = [
        "#4ADE80" if m > 15 else "#F87171" if m < 0 else "#FBBF24"
        for m in df["avg_mos"].fillna(0)
    ]
    fig.add_trace(go.Bar(
        x=df["runs"], y=df["ticker"],
        orientation="h",
        marker_color=colors,
        text=df["runs"].apply(lambda v: f"{v} runs"),
        textposition="auto",
        customdata=df[["avg_mos", "unique_users"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Runs: %{x}<br>"
            "Avg MoS: %{customdata[0]:.1f}%<br>"
            "Unique users: %{customdata[1]}<extra></extra>"
        ),
    ))
    fig.update_layout(
        xaxis=dict(title="Analysis runs", gridcolor="rgba(0,0,0,0.04)"),
        yaxis=dict(tickfont=dict(family="IBM Plex Mono", size=11)),
    )
    return _style_fig(fig)


def _chart_tier_pie(df: "pd.DataFrame") -> "go.Figure":
    fig = go.Figure()
    if df is None or df.empty:
        fig.add_annotation(text="No user data", showarrow=False,
                           font=dict(color="#475569", size=14))
        return _style_fig(fig)

    labels = df["tier"].tolist()
    values = df["count"].tolist()
    colors = [_TIER_COLORS.get(t, "#64748B") for t in labels]

    fig.add_trace(go.Pie(
        labels=[t.capitalize() for t in labels],
        values=values,
        marker=dict(colors=colors, line=dict(color="#0F172A", width=2)),
        hole=0.5,
        textinfo="label+percent",
        textfont=dict(size=12),
        hovertemplate="<b>%{label}</b><br>Users: %{value}<br>%{percent}<extra></extra>",
    ))
    return _style_fig(fig)


def _chart_feature_usage(df: "pd.DataFrame") -> "go.Figure":
    fig = go.Figure()
    if df is None or df.empty:
        fig.add_annotation(text="No data yet", showarrow=False,
                           font=dict(color="#475569", size=14))
        return _style_fig(fig)

    tiers = ["free", "starter", "pro"]
    tier_colors_list = [_TIER_COLORS["free"], _TIER_COLORS["starter"], _TIER_COLORS["pro"]]

    labels = df.get("event_label", df.get("event_type", pd.Series())).tolist()
    for tier_name, clr in zip(tiers, tier_colors_list):
        if tier_name in df.columns:
            fig.add_trace(go.Bar(
                name=tier_name.capitalize(),
                x=labels,
                y=df[tier_name].tolist(),
                marker_color=clr,
            ))

    fig.update_layout(
        barmode="group",
        xaxis=dict(title="Feature"),
        yaxis=dict(title="Events", gridcolor="rgba(0,0,0,0.04)"),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0)"),
    )
    return _style_fig(fig)


def _chart_funnel(funnel: list[dict]) -> "go.Figure":
    fig = go.Figure()
    if not funnel:
        return _style_fig(fig)

    stages = [f["stage"] for f in funnel]
    counts = [f["count"] for f in funnel]
    pcts   = [f["pct_of_prev"] for f in funnel]

    fig.add_trace(go.Funnel(
        y=stages,
        x=counts,
        textinfo="value+percent previous",
        marker=dict(
            color=["#1D4ED8", "#2563EB", "#3B82F6", "#22D3EE", "#059669"],
            line=dict(color="#0F172A", width=1),
        ),
        connector=dict(line=dict(color="rgba(255,255,255,0.1)", width=1)),
    ))
    fig.update_layout(
        yaxis=dict(tickfont=dict(size=13)),
        margin=dict(l=140, r=20, t=20, b=20),
    )
    return _style_fig(fig)


def _chart_signal_dist(df: "pd.DataFrame") -> "go.Figure":
    fig = go.Figure()
    if df is None or df.empty:
        return _style_fig(fig)

    # Reorder by natural signal order
    df["_ord"] = df["signal"].apply(
        lambda s: _SIGNAL_ORDER.index(s) if s in _SIGNAL_ORDER else 99
    )
    df = df.sort_values("_ord")

    colors = [_SIGNAL_COLS.get(s, "#64748B") for s in df["signal"]]
    fig.add_trace(go.Bar(
        x=df["signal"],
        y=df["count"],
        marker_color=colors,
        text=df["count"],
        textposition="auto",
    ))
    fig.update_layout(
        xaxis=dict(title="Signal"),
        yaxis=dict(title="Count", gridcolor="rgba(0,0,0,0.04)"),
    )
    return _style_fig(fig)


def _style_fig(fig: "go.Figure") -> "go.Figure":
    """Apply consistent themed styling to all admin charts."""
    import importlib.util as _ilu, pathlib as _pl
    _cl = _pl.Path(__file__).resolve().parent / "utils" / "chart_layouts.py"
    _sp = _ilu.spec_from_file_location("_cl", _cl)
    _md = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_md)
    _md.style_fig(fig, height=320, compact=True)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=30))
    return fig


# ════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD RENDERER
# ════════════════════════════════════════════════════════════════

def _is_admin() -> bool:
    return os.environ.get(_ADMIN_ENV, "0") == "1"


def _metric_card(label: str, value: str, sub: str = "", color: str = "#60A5FA") -> str:
    sub_html = f'<div style="font-size:11px;color:#475569;margin-top:3px;">{sub}</div>' if sub else ""
    return (
        f'<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);'
        f'border-radius:12px;padding:16px 18px;">'
        f'<div style="font-size:10px;color:#64748B;letter-spacing:0.08em;text-transform:uppercase;'
        f'margin-bottom:6px;">{label}</div>'
        f'<div style="font-size:26px;font-weight:800;color:{color};font-family:"IBM Plex Mono",monospace;">'
        f'{value}</div>'
        f'{sub_html}'
        f'</div>'
    )


def render_admin_dashboard() -> None:
    """
    Renders the full admin analytics dashboard.
    Exits immediately if YIELDIQ_ADMIN env var is not set to "1".
    """
    if not _is_admin():
        st.error("🔒 Admin access denied. Set `YIELDIQ_ADMIN=1` in the server environment.")
        return

    if not _PD or not _PX:
        st.error("pandas and plotly are required for the admin dashboard.")
        return

    # ── Header ──────────────────────────────────────────────────
    st.html("""
    <div style="display:flex;align-items:center;gap:14px;padding:6px 0 20px;">
      <div style="font-size:30px;">⚙️</div>
      <div>
        <div style="font-size:22px;font-weight:800;
                    background:linear-gradient(90deg,#F59E0B,#EF4444);
                    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                    background-clip:text;line-height:1.1;">Admin Analytics</div>
        <div style="font-size:11px;color:#475569;letter-spacing:0.06em;">
          YieldIQ Internal · RESTRICTED ACCESS
        </div>
      </div>
    </div>
    """)

    # ── Date-range selector ──────────────────────────────────────
    _col_dr, _col_ref, _ = st.columns([1, 1, 4])
    with _col_dr:
        days = st.selectbox(
            "Period", [7, 14, 30, 60, 90], index=2,
            format_func=lambda d: f"Last {d} days",
            label_visibility="collapsed", key="admin_days",
        )
    with _col_ref:
        if st.button("🔄 Refresh", key="admin_refresh"):
            st.rerun()

    st.html('<div style="height:4px"></div>')

    # ════════════════════════════════════════════════════════════
    # SECTION 1 — SUMMARY METRICS
    # ════════════════════════════════════════════════════════════
    st.html('<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:10px;">📊 Summary</div>')

    m = _summary_metrics(days)
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    with mc1:
        st.html(_metric_card("Total Users",      f"{m['total_users']:,}", color="#60A5FA"))
    with mc2:
        st.html(_metric_card("DAU",              f"{m['dau']:,}",         "Unique today",    "#22D3EE"))
    with mc3:
        st.html(_metric_card("MAU",              f"{m['mau']:,}",         f"Last {days}d",   "#22D3EE"))
    with mc4:
        st.html(_metric_card("Analyses Today",   f"{m['analyses_today']:,}",                 color="#A78BFA"))
    with mc5:
        st.html(_metric_card(f"Analyses ({days}d)", f"{m['analyses_30d']:,}",                color="#A78BFA"))
    with mc6:
        st.html(_metric_card("Est. MRR",         f"${m['mrr_estimate']:,}",                  color="#4ADE80"))

    st.html('<div style="height:12px"></div>')

    # ════════════════════════════════════════════════════════════
    # SECTION 2 — DAU TIME SERIES
    # ════════════════════════════════════════════════════════════
    st.html('<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">📈 Daily Active Users & Analysis Volume</div>')
    dau_df = _dau_series(days)
    st.plotly_chart(_chart_dau(dau_df), width='stretch', key="admin_dau")

    # ════════════════════════════════════════════════════════════
    # SECTION 3 — TOP TICKERS + SIGNAL DISTRIBUTION
    # ════════════════════════════════════════════════════════════
    col_tk, col_sig = st.columns([6, 4], gap="medium")

    with col_tk:
        st.html(f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">🔥 Top 20 Analysed Tickers (last {days}d)</div>')
        top_df = _top_tickers(20, days)
        st.plotly_chart(_chart_top_tickers(top_df), width='stretch', key="admin_tickers")

    with col_sig:
        st.html(f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">📡 Signal Distribution (last {days}d)</div>')
        sig_df = _signal_distribution(days)
        st.plotly_chart(_chart_signal_dist(sig_df), width='stretch', key="admin_signals")

    # ════════════════════════════════════════════════════════════
    # SECTION 4 — TIER DISTRIBUTION + FEATURE USAGE
    # ════════════════════════════════════════════════════════════
    col_tier, col_feat = st.columns([4, 6], gap="medium")

    with col_tier:
        st.html('<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">👥 Tier Distribution</div>')
        tier_df = _tier_distribution()
        st.plotly_chart(_chart_tier_pie(tier_df), width='stretch', key="admin_tier_pie")

        # Tier breakdown table
        if tier_df is not None and not tier_df.empty:
            total_u = tier_df["count"].sum()
            for _, row in tier_df.sort_values("count", ascending=False).iterrows():
                t   = row["tier"]
                cnt = int(row["count"])
                pct = round(cnt / total_u * 100, 1) if total_u else 0
                clr = _TIER_COLORS.get(t, "#64748B")
                mrr_est = _TIER_PRICES.get(t, 0) * cnt
                st.html(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);'
                    f'border-radius:8px;padding:8px 12px;margin-bottom:5px;">'
                    f'<div>'
                    f'<span style="color:{clr};font-weight:700;font-size:12px;">{t.capitalize()}</span>'
                    f'<span style="color:#475569;font-size:11px;margin-left:8px;">{pct}%</span>'
                    f'</div>'
                    f'<div style="text-align:right;">'
                    f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;">{cnt:,} users</div>'
                    f'<div style="font-size:10px;color:#475569;">${mrr_est:,}/mo MRR</div>'
                    f'</div></div>'
                )

    with col_feat:
        st.html(f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">⚡ Feature Usage by Tier (last {days}d)</div>')
        feat_df = _feature_usage_by_tier(days)
        st.plotly_chart(_chart_feature_usage(feat_df), width='stretch', key="admin_feat")

    # ════════════════════════════════════════════════════════════
    # SECTION 5 — CONVERSION FUNNEL
    # ════════════════════════════════════════════════════════════
    st.html('<div style="height:4px"></div>')
    st.html('<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:6px;">🔄 Conversion Funnel</div>')

    col_funnel, col_funnel_stats = st.columns([5, 3], gap="medium")
    funnel_data = _conversion_funnel()

    with col_funnel:
        st.plotly_chart(_chart_funnel(funnel_data), width='stretch', key="admin_funnel")

    with col_funnel_stats:
        st.html('<div style="margin-top:30px;"></div>')
        for i, stage in enumerate(funnel_data):
            bar_w = max(4, int(stage["count"] / max(funnel_data[0]["count"], 1) * 100)) if funnel_data else 0
            drop  = "" if i == 0 else f"↘ {100 - stage['pct_of_prev']:.0f}% drop"
            stage_label = "Base stage" if i == 0 else f"{stage['pct_of_prev']:.1f}% of previous · {drop}"
            st.html(
                f'<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);'
                f'border-radius:9px;padding:10px 14px;margin-bottom:6px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<div style="font-size:11px;font-weight:700;color:#E2E8F0;">{stage["stage"]}</div>'
                f'<div style="font-size:12px;font-family:\'IBM Plex Mono\',monospace;color:#60A5FA;">'
                f'{stage["count"]:,}</div>'
                f'</div>'
                f'<div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;margin:5px 0;">'
                f'<div style="height:100%;width:{bar_w}%;background:#1D4ED8;border-radius:2px;"></div>'
                f'</div>'
                f'<div style="font-size:10px;color:#475569;">'
                f'{stage_label}'
                f'</div></div>'
            )

    # ════════════════════════════════════════════════════════════
    # SECTION 6 — MARKET BREAKDOWN
    # ════════════════════════════════════════════════════════════
    mkt_df = _market_breakdown(days)
    if mkt_df is not None and not mkt_df.empty:
        st.html('<div style="height:4px"></div>')
        st.html(f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:8px;">🌍 Market Breakdown (last {days}d)</div>')
        _mk_cols = st.columns(min(len(mkt_df), 4))
        for col, (_, row) in zip(_mk_cols, mkt_df.iterrows()):
            with col:
                st.html(_metric_card(
                    row["market"].upper() or "Unknown",
                    f"{int(row['count']):,}",
                    f"Avg MoS {row['avg_mos']:.1f}%",
                    "#22D3EE" if row["market"] == "us" else "#FBBF24",
                ))

    # ════════════════════════════════════════════════════════════
    # SECTION 7 — RECENT EVENTS TABLE
    # ════════════════════════════════════════════════════════════
    st.html('<div style="height:12px"></div>')
    with st.expander("📋 Recent Events (last 100)", expanded=False):
        evt_df = _recent_events(100)
        if evt_df is not None and not evt_df.empty:
            # Format timestamp to local
            if "ts" in evt_df.columns:
                evt_df["ts"] = pd.to_datetime(evt_df["ts"], utc=True).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(
                evt_df,
                width='stretch',
                column_config={
                    "ts":         st.column_config.TextColumn("Timestamp", width="medium"),
                    "category":   st.column_config.TextColumn("Type",      width="small"),
                    "user_email": st.column_config.TextColumn("User",      width="medium"),
                    "tier":       st.column_config.TextColumn("Tier",      width="small"),
                    "detail":     st.column_config.TextColumn("Detail",    width="large"),
                },
                hide_index=True,
                height=350,
            )
        else:
            st.info("No events recorded yet.")

    # ════════════════════════════════════════════════════════════
    # SECTION 8 — RAW DATA TABLE (Top Tickers)
    # ════════════════════════════════════════════════════════════
    with st.expander(f"📊 Top Tickers — Full Table (last {days}d)", expanded=False):
        top_full = _top_tickers(50, days)
        if top_full is not None and not top_full.empty:
            st.dataframe(
                top_full,
                width='stretch',
                column_config={
                    "ticker":       st.column_config.TextColumn("Ticker"),
                    "runs":         st.column_config.NumberColumn("Runs", format="%d"),
                    "avg_mos":      st.column_config.NumberColumn("Avg MoS%", format="%.1f%%"),
                    "unique_users": st.column_config.NumberColumn("Unique Users", format="%d"),
                },
                hide_index=True,
            )

    # ════════════════════════════════════════════════════════════
    # SECTION 9 — EXPORT
    # ════════════════════════════════════════════════════════════
    st.html('<div style="height:12px"></div>')
    st.html(f'<div style="font-size:13px;font-weight:700;color:#F1F5F9;margin-bottom:8px;">⬇️ Export Analytics Data</div>')

    _exp_col1, _exp_col2, _ = st.columns([1, 1, 2])
    with _exp_col1:
        _zip_bytes = export_analytics_zip(days)
        st.download_button(
            label=f"📦 Download ZIP ({days}d analytics)",
            data=_zip_bytes,
            file_name=f"yieldiq_analytics_{days}d_{datetime.now().strftime('%Y%m%d')}.zip",
            mime="application/zip",
            width='stretch',
        )
    with _exp_col2:
        # Quick single-CSV: analysis events only
        ae_df = _query_df(
            "SELECT * FROM analysis_events WHERE ts >= ? ORDER BY ts DESC",
            ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),),
        )
        if ae_df is not None and not ae_df.empty:
            st.download_button(
                label=f"📄 Analysis Events CSV ({days}d)",
                data=ae_df.to_csv(index=False).encode(),
                file_name=f"analysis_events_{days}d_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width='stretch',
            )

    # ── Footer ──────────────────────────────────────────────────
    st.html(f"""
    <div style="margin-top:24px;padding:10px 14px;
                background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.18);
                border-radius:8px;font-size:10px;color:#F87171;">
      ⚠️ <strong>Restricted:</strong> This dashboard is visible because
      <code style="background:rgba(239,68,68,0.12);padding:1px 4px;border-radius:3px;">
      YIELDIQ_ADMIN=1</code> is set in the server environment.
      Do not share this URL or screenshots externally.
      Last render: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
    </div>
    """)
