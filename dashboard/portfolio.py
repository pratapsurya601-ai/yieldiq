# dashboard/portfolio.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ Portfolio — SQLite-backed watchlist with P&L tracking
#
# Tracks for each saved stock:
#   • Ticker + company name
#   • Entry price at time of save (for P&L calculation)
#   • YieldIQ signal at time of save (BUY/SELL/WATCH/HOLD)
#   • Intrinsic value at time of save
#   • MoS% at time of save
#   • WACC used
#   • User notes
#   • Date saved
#   • Currency (sym + to_code)
#
# Live data (fetched on tab open):
#   • Current price via yfinance fast_info
#   • P&L since save date ($ and %)
#   • Current MoS vs saved IV
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import json
import sqlite3
import os
import pathlib
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

# ── DB location: same folder as this file ─────────────────────
_DB_PATH = pathlib.Path(os.environ.get("YIELDIQ_DATA_DIR", str(pathlib.Path(__file__).parent))) / "portfolio.db"
_lock    = threading.Lock()


# ════════════════════════════════════════════════════════════════
# DB SETUP
# ════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker        TEXT    NOT NULL,
                company_name  TEXT    DEFAULT '',
                entry_price   REAL    NOT NULL,
                iv            REAL    DEFAULT 0,
                mos_pct       REAL    DEFAULT 0,
                signal        TEXT    DEFAULT '',
                wacc          REAL    DEFAULT 0,
                sym           TEXT    DEFAULT '$',
                to_code       TEXT    DEFAULT 'USD',
                notes         TEXT    DEFAULT '',
                saved_at      TEXT    NOT NULL,
                sector        TEXT    DEFAULT '',
                UNIQUE(ticker)
            )
        """)
        # Migration: add notes column if upgrading from older schema
        try:
            conn.execute("ALTER TABLE portfolio ADD COLUMN notes TEXT DEFAULT ''")
        except Exception:
            pass
        conn.commit()
        conn.close()


# ════════════════════════════════════════════════════════════════
# CRUD OPERATIONS
# ════════════════════════════════════════════════════════════════

def save_to_portfolio(
    ticker:       str,
    entry_price:  float,
    iv:           float,
    mos_pct:      float,
    signal:       str,
    wacc:         float,
    sym:          str   = "$",
    to_code:      str   = "USD",
    company_name: str   = "",
    sector:       str   = "",
    notes:        str   = "",
) -> bool:
    """
    Save or update a stock in the portfolio.
    Uses INSERT OR REPLACE so re-saving updates the entry.
    Returns True on success.
    """
    try:
        with _lock:
            conn = _get_conn()
            # Convert raw signal → clean Undervalued/Overvalued label
            clean_signal = _sig_to_label(signal, mos_pct)
            conn.execute("""
                INSERT INTO portfolio
                    (ticker, company_name, entry_price, iv, mos_pct,
                     signal, wacc, sym, to_code, notes, saved_at, sector)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_name = excluded.company_name,
                    entry_price  = excluded.entry_price,
                    iv           = excluded.iv,
                    mos_pct      = excluded.mos_pct,
                    signal       = excluded.signal,
                    wacc         = excluded.wacc,
                    sym          = excluded.sym,
                    to_code      = excluded.to_code,
                    notes        = excluded.notes,
                    saved_at     = excluded.saved_at,
                    sector       = excluded.sector
            """, (
                ticker.upper(), company_name, entry_price, iv, mos_pct,
                clean_signal, wacc, sym, to_code, notes,
                datetime.now().strftime("%Y-%m-%d %H:%M"), sector,
            ))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        st.error(f"Portfolio save error: {e}")
        return False


def remove_from_portfolio(ticker: str) -> bool:
    """Remove a stock from the portfolio."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker.upper(),))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        st.error(f"Portfolio remove error: {e}")
        return False


def get_portfolio() -> list[dict]:
    """Return all portfolio entries as list of dicts."""
    try:
        with _lock:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM portfolio ORDER BY saved_at DESC"
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def is_in_portfolio(ticker: str) -> bool:
    """Check if a ticker is already saved."""
    try:
        with _lock:
            conn = _get_conn()
            row  = conn.execute(
                "SELECT 1 FROM portfolio WHERE ticker = ?", (ticker.upper(),)
            ).fetchone()
            conn.close()
        return row is not None
    except Exception:
        return False


def update_notes(ticker: str, notes: str) -> bool:
    """Update notes for a ticker."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute(
                "UPDATE portfolio SET notes = ? WHERE ticker = ?",
                (notes, ticker.upper())
            )
            conn.commit()
            conn.close()
        return True
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# WATCHLIST CRUD
# ════════════════════════════════════════════════════════════════

def init_watchlist_db() -> None:
    """Create watchlist table if it doesn't exist. Safe to call on every startup."""
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker              TEXT    NOT NULL,
                company_name        TEXT    DEFAULT '',
                added_price         REAL    DEFAULT 0,
                target_price        REAL    DEFAULT 0,
                alert_mos_threshold REAL    DEFAULT 20,
                notes               TEXT    DEFAULT '',
                added_at            TEXT    NOT NULL,
                UNIQUE(ticker)
            )
        """)
        conn.commit()
        conn.close()


def add_to_watchlist(
    ticker:               str,
    company_name:         str   = "",
    added_price:          float = 0.0,
    target_price:         float = 0.0,
    alert_mos_threshold:  float = 20.0,
    notes:                str   = "",
) -> bool:
    """Add or update a ticker in the watchlist. Returns True on success."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO watchlist
                    (ticker, company_name, added_price, target_price,
                     alert_mos_threshold, notes, added_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_name        = excluded.company_name,
                    added_price         = excluded.added_price,
                    target_price        = excluded.target_price,
                    alert_mos_threshold = excluded.alert_mos_threshold,
                    notes               = excluded.notes,
                    added_at            = excluded.added_at
            """, (
                ticker.upper(), company_name, added_price, target_price,
                alert_mos_threshold, notes,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        st.error(f"Watchlist save error: {e}")
        return False


def remove_from_watchlist(ticker: str) -> bool:
    """Remove a ticker from the watchlist. Returns True on success."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        st.error(f"Watchlist remove error: {e}")
        return False


def get_watchlist() -> list[dict]:
    """Return all watchlist entries as a list of dicts."""
    try:
        with _lock:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM watchlist ORDER BY added_at DESC"
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def is_in_watchlist(ticker: str) -> bool:
    """Return True if the ticker is already in the watchlist."""
    try:
        with _lock:
            conn = _get_conn()
            row  = conn.execute(
                "SELECT 1 FROM watchlist WHERE ticker = ?", (ticker.upper(),)
            ).fetchone()
            conn.close()
        return row is not None
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# INSTITUTIONAL OWNERSHIP HISTORY
# ════════════════════════════════════════════════════════════════

def init_institutional_db() -> None:
    """
    Create the institutional_ownership_history table.
    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS institutional_ownership_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT    NOT NULL,
                quarter      TEXT    NOT NULL,
                total_pct    REAL    DEFAULT 0,
                qoq_change   REAL    DEFAULT 0,
                trend        TEXT    DEFAULT '',
                accumulation INTEGER DEFAULT 0,
                avg_top5_chg REAL    DEFAULT 0,
                num_holders  INTEGER DEFAULT 0,
                top_holders  TEXT    DEFAULT '[]',
                recorded_at  TEXT    NOT NULL,
                UNIQUE(ticker, quarter)
            )
        """)
        conn.commit()
        conn.close()


def save_institutional_ownership(ticker: str, data: dict) -> bool:
    """
    Upsert one quarterly snapshot into institutional_ownership_history.
    Returns True on success.
    """
    if not data or not data.get("quarter"):
        return False
    try:
        init_institutional_db()
        top_holders_json = json.dumps(data.get("holders", []))
        with _lock:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO institutional_ownership_history
                    (ticker, quarter, total_pct, qoq_change, trend,
                     accumulation, avg_top5_chg, num_holders,
                     top_holders, recorded_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ticker, quarter) DO UPDATE SET
                    total_pct    = excluded.total_pct,
                    qoq_change   = excluded.qoq_change,
                    trend        = excluded.trend,
                    accumulation = excluded.accumulation,
                    avg_top5_chg = excluded.avg_top5_chg,
                    num_holders  = excluded.num_holders,
                    top_holders  = excluded.top_holders,
                    recorded_at  = excluded.recorded_at
            """, (
                ticker.upper(),
                data.get("quarter", ""),
                float(data.get("total_pct", 0)),
                float(data.get("qoq_change_pct", 0)),
                data.get("trend", ""),
                int(bool(data.get("accumulation", False))),
                float(data.get("avg_top5_chg", 0)),
                int(data.get("num_holders", 0)),
                top_holders_json,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"save_institutional_ownership error: {e}")
        return False


def get_institutional_history(ticker: str, quarters: int = 8) -> list[dict]:
    """Return up to `quarters` quarterly snapshots for `ticker`, newest first."""
    try:
        init_institutional_db()
        with _lock:
            conn = _get_conn()
            rows = conn.execute(
                """
                SELECT * FROM institutional_ownership_history
                WHERE ticker = ?
                ORDER BY quarter DESC
                LIMIT ?
                """,
                (ticker.upper(), quarters),
            ).fetchall()
            conn.close()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["top_holders"] = json.loads(d.get("top_holders", "[]") or "[]")
            except Exception:
                d["top_holders"] = []
            result.append(d)
        return result
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════
# GOOGLE SHEETS SYNC  — per-user URL/ID storage
# ════════════════════════════════════════════════════════════════

def init_sheets_db() -> None:
    """Create user_sheets_settings table. Safe to call on every startup."""
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sheets_settings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email    TEXT    NOT NULL,
                sheets_url    TEXT    DEFAULT '',
                sheets_id     TEXT    DEFAULT '',
                last_synced   TEXT    DEFAULT '',
                created_at    TEXT    NOT NULL,
                UNIQUE(user_email)
            )
        """)
        conn.commit()
        conn.close()


def save_sheets_url(user_email: str, sheets_url: str, sheets_id: str) -> bool:
    """Upsert the Google Sheets URL/ID for a user."""
    if not user_email:
        return False
    try:
        init_sheets_db()
        now = datetime.now().isoformat()
        with _lock:
            conn = _get_conn()
            conn.execute(
                """
                INSERT INTO user_sheets_settings
                    (user_email, sheets_url, sheets_id, last_synced, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    sheets_url  = excluded.sheets_url,
                    sheets_id   = excluded.sheets_id,
                    last_synced = excluded.last_synced
                """,
                (user_email.lower(), sheets_url, sheets_id, now, now),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"save_sheets_url error: {e}")
        return False


def get_sheets_info(user_email: str) -> dict:
    """Return stored Google Sheets info for a user."""
    if not user_email:
        return {"sheets_url": "", "sheets_id": "", "last_synced": ""}
    try:
        init_sheets_db()
        with _lock:
            conn = _get_conn()
            row = conn.execute(
                "SELECT sheets_url, sheets_id, last_synced "
                "FROM user_sheets_settings WHERE user_email = ?",
                (user_email.lower(),),
            ).fetchone()
            conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return {"sheets_url": "", "sheets_id": "", "last_synced": ""}


# ════════════════════════════════════════════════════════════════
# LIVE PRICE FETCHER
# ════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def _fetch_live_price(ticker: str) -> float:
    """Fetch current price. Cached 2 minutes."""
    try:
        import yfinance as yf
        fi = yf.Ticker(ticker).fast_info
        p  = getattr(fi, "last_price", 0) or getattr(fi, "regular_market_price", 0)
        return float(p) if p else 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_perf_data(tickers_tuple: tuple, start_str: str) -> dict:
    """Fetch daily close prices for chart. Returns {ticker: {date_str: price}}."""
    import yfinance as yf
    all_t = list(tickers_tuple) + ["SPY"]
    try:
        raw = yf.download(all_t, start=start_str, progress=False, auto_adjust=True)
        if raw.empty:
            return {}
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            closes = raw.rename(columns={"Close": all_t[0]})
        result = {}
        for col in closes.columns:
            series = closes[col].dropna()
            result[str(col)] = {str(d.date()): float(v) for d, v in series.items()}
        return result
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _lookup_company(ticker: str) -> str:
    """Fetch company name from yfinance. Cached 1 hour."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("longName", info.get("shortName", "")) or ""
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════════
# UI HELPERS
# ════════════════════════════════════════════════════════════════

def _sig_to_label(sig: str, mos_pct: float = 0) -> str:
    """Convert raw YieldIQ signal to clean Undervalued/Overvalued label."""
    s = (sig or "").upper()
    if mos_pct > 0 or "BUY" in s or "WATCH" in s or "HOLD" in s:
        return "Undervalued"
    if mos_pct < 0 or "SELL" in s:
        return "Overvalued"
    return "Neutral"


def _sig_color(sig: str, mos_pct: float = 0) -> str:
    label = _sig_to_label(sig, mos_pct)
    if label == "Undervalued": return "#059669"
    if label == "Overvalued":  return "#DC2626"
    return "#D97706"


def _pnl_color(v: float) -> str:
    return "#059669" if v > 0 else "#DC2626" if v < 0 else "#64748B"


def _sig_badge_html(sig: str) -> str:
    """Return a styled HTML badge for the signal string."""
    s = (sig or "").upper()
    if "STRONG BUY" in s:
        fg, bg, bd = "#065F46", "#D1FAE5", "#6EE7B7"
    elif "BUY" in s and "SELL" not in s:
        fg, bg, bd = "#059669", "#ECFDF5", "#A7F3D0"
    elif "SELL" in s:
        fg, bg, bd = "#DC2626", "#FEF2F2", "#FECACA"
    elif "WATCH" in s:
        fg, bg, bd = "#D97706", "#FFFBEB", "#FDE68A"
    elif "HOLD" in s:
        fg, bg, bd = "#2563EB", "#EFF6FF", "#BFDBFE"
    elif "UNDERVALUED" in s:
        fg, bg, bd = "#059669", "#ECFDF5", "#A7F3D0"
    elif "OVERVALUED" in s:
        fg, bg, bd = "#DC2626", "#FEF2F2", "#FECACA"
    else:
        fg, bg, bd = "#6B7280", "#F3F4F6", "#E5E7EB"
    label = sig if sig else "—"
    return (
        f'<span style="padding:2px 10px;background:{bg};border:1px solid {bd};'
        f'border-radius:100px;font-size:11px;font-weight:700;color:{fg};'
        f'white-space:nowrap;letter-spacing:0.02em;">{label}</span>'
    )


def _mos_cell_colors(mos: float) -> tuple[str, str]:
    """Return (text_color, bg_color) for a MoS% table cell."""
    if mos > 30:  return "#065F46", "#D1FAE5"
    if mos > 10:  return "#92400E", "#FEF3C7"
    if mos >= 0:  return "#374151", "#F9FAFB"
    return "#991B1B", "#FEE2E2"


def _enrich_with_live_prices(holdings: list) -> None:
    """Mutate holdings in place — add live_price, pnl_pct, pnl_abs, current_mos."""
    for h in holdings:
        lp = _fetch_live_price(h["ticker"])
        h["live_price"] = lp
        ep = h["entry_price"]
        iv = h.get("iv", 0)
        if ep > 0 and lp > 0:
            h["pnl_pct"]     = (lp - ep) / ep * 100
            h["pnl_abs"]     = lp - ep
            h["current_mos"] = (iv - lp) / lp * 100 if iv > 0 else 0.0
        else:
            h["pnl_pct"]     = 0.0
            h["pnl_abs"]     = 0.0
            h["current_mos"] = 0.0


# ════════════════════════════════════════════════════════════════
# UI SECTION RENDERERS
# ════════════════════════════════════════════════════════════════

def _render_kpi_cards(holdings: list, sym: str) -> None:
    """Four KPI summary cards at the top of the portfolio tab."""
    total     = len(holdings)
    invested  = sum(h["entry_price"] for h in holdings if h["entry_price"] > 0)
    cur_val   = sum(h["live_price"]  for h in holdings if h["live_price"]  > 0)
    total_pnl = cur_val - invested
    pnl_pct   = (total_pnl / invested * 100) if invested > 0 else 0.0
    avg_mos   = (sum(h["current_mos"] for h in holdings) / total) if total else 0.0

    pnl_clr  = "#059669" if total_pnl >= 0 else "#DC2626"
    pnl_bg   = "#ECFDF5" if total_pnl >= 0 else "#FEF2F2"
    pnl_bd   = "#A7F3D0" if total_pnl >= 0 else "#FECACA"
    mos_clr  = "#059669" if avg_mos > 15 else "#D97706" if avg_mos > 0 else "#DC2626"
    pnl_sign = "+" if total_pnl >= 0 else ""

    c1, c2, c3, c4 = st.columns(4, gap="small")

    # ── Card 1: Portfolio Value ────────────────────────────────
    c1.html(f"""
    <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                padding:20px 20px 16px;box-shadow:0 1px 4px rgba(15,23,42,0.06);
                border-top:3px solid #1D4ED8;">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.10em;margin-bottom:8px;">Est. Portfolio Value</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:700;
                  color:#0F172A;line-height:1;">{sym}{cur_val:,.0f}</div>
      <div style="font-size:11px;color:#64748B;margin-top:6px;">
        Cost basis: {sym}{invested:,.0f}
      </div>
    </div>
    """)

    # ── Card 2: Unrealized P&L ────────────────────────────────
    c2.html(f"""
    <div style="background:{pnl_bg};border:1px solid {pnl_bd};border-radius:12px;
                padding:20px 20px 16px;box-shadow:0 1px 4px rgba(15,23,42,0.06);
                border-top:3px solid {pnl_clr};">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.10em;margin-bottom:8px;">Unrealized P&amp;L</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:700;
                  color:{pnl_clr};line-height:1;">{pnl_sign}{sym}{abs(total_pnl):,.0f}</div>
      <div style="font-size:11px;color:{pnl_clr};margin-top:6px;font-weight:600;">
        {pnl_sign}{pnl_pct:.1f}% total return
      </div>
    </div>
    """)

    # ── Card 3: Average MoS ───────────────────────────────────
    c3.html(f"""
    <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                padding:20px 20px 16px;box-shadow:0 1px 4px rgba(15,23,42,0.06);
                border-top:3px solid {mos_clr};">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.10em;margin-bottom:8px;">Avg Margin of Safety</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:700;
                  color:{mos_clr};line-height:1;">{avg_mos:+.1f}%</div>
      <div style="font-size:11px;color:#64748B;margin-top:6px;">
        vs intrinsic value at save
      </div>
    </div>
    """)

    # ── Card 4: Position Count ────────────────────────────────
    winners = sum(1 for h in holdings if h["pnl_pct"] > 0)
    losers  = sum(1 for h in holdings if h["pnl_pct"] < 0)
    c4.html(f"""
    <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                padding:20px 20px 16px;box-shadow:0 1px 4px rgba(15,23,42,0.06);
                border-top:3px solid #6366F1;">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.10em;margin-bottom:8px;">Stocks in Portfolio</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:26px;font-weight:700;
                  color:#0F172A;line-height:1;">{total}</div>
      <div style="font-size:11px;color:#64748B;margin-top:6px;">
        <span style="color:#059669;font-weight:600;">{winners}W</span>
        &nbsp;·&nbsp;
        <span style="color:#DC2626;font-weight:600;">{losers}L</span>
        &nbsp;·&nbsp;{total - winners - losers} flat
      </div>
    </div>
    """)

    st.html("<div style='height:8px'></div>")


def _render_performance_chart(holdings: list) -> None:
    """Portfolio vs S&P 500 performance line chart with date range selector."""
    import plotly.graph_objects as go

    st.html("""
    <div style="margin:20px 0 8px;">
      <div style="font-size:15px;font-weight:700;color:#0F172A;">Portfolio Performance</div>
      <div style="font-size:12px;color:#64748B;margin-top:2px;">
        Equal-weighted return vs S&amp;P 500 · Indexed to 0% at period start
      </div>
    </div>
    """)

    range_col, _ = st.columns([3, 7])
    with range_col:
        range_key = st.radio(
            "Range", ["1M", "3M", "6M", "1Y"],
            horizontal=True, index=1,
            key="_perf_range_radio",
            label_visibility="collapsed",
        )

    days_map = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365}
    start_dt  = datetime.now() - timedelta(days=days_map[range_key])
    start_str = start_dt.strftime("%Y-%m-%d")

    tickers = tuple(h["ticker"] for h in holdings)

    with st.spinner("Loading performance data…"):
        price_data = _fetch_perf_data(tickers, start_str)

    if not price_data:
        st.info("Performance data temporarily unavailable.")
        return

    spy_data = price_data.get("SPY", {})
    if not spy_data:
        return

    all_dates = sorted(spy_data.keys())

    # Portfolio: equal-weighted cumulative return at each date
    port_returns: dict[str, float] = {}
    for d in all_dates:
        day_returns = []
        for h in holdings:
            t = h["ticker"]
            if t not in price_data or h["entry_price"] <= 0:
                continue
            # Only include holding if it was saved before this date
            if d < h["saved_at"][:10]:
                continue
            price_on_d = price_data[t].get(d)
            if price_on_d:
                day_returns.append((price_on_d / h["entry_price"] - 1) * 100)
        if day_returns:
            port_returns[d] = sum(day_returns) / len(day_returns)

    # SPY: normalized to 0 at range start
    spy_prices = [(d, spy_data[d]) for d in all_dates if d in spy_data]
    if not spy_prices:
        return
    spy_base = spy_prices[0][1]
    spy_returns = {d: (p / spy_base - 1) * 100 for d, p in spy_prices}

    fig = go.Figure()

    p_dates = sorted(port_returns.keys())
    p_vals  = [port_returns[d] for d in p_dates]

    if p_dates:
        last_pval   = p_vals[-1]
        port_color  = "#059669" if last_pval >= 0 else "#DC2626"
        fill_rgba   = "rgba(5,150,105,0.08)" if last_pval >= 0 else "rgba(220,38,38,0.08)"
        fig.add_trace(go.Scatter(
            x=p_dates, y=p_vals,
            name="My Portfolio",
            line=dict(color=port_color, width=2.5),
            fill="tozeroy",
            fillcolor=fill_rgba,
            hovertemplate="%{y:+.2f}%<extra>Portfolio</extra>",
        ))

    s_dates = sorted(spy_returns.keys())
    s_vals  = [spy_returns[d] for d in s_dates]
    fig.add_trace(go.Scatter(
        x=s_dates, y=s_vals,
        name="S&P 500",
        line=dict(color="#94A3B8", width=1.5, dash="dash"),
        hovertemplate="%{y:+.2f}%<extra>S&P 500</extra>",
    ))

    fig.add_hline(y=0, line_color="#E2E8F0", line_width=1)

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=260,
        margin=dict(l=40, r=20, t=20, b=40),
        hovermode="x unified",
        legend=dict(
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(size=11, color="#6B7280"),
            orientation="h", y=1.08, x=1, xanchor="right",
        ),
        yaxis=dict(
            ticksuffix="%",
            tickfont=dict(family="IBM Plex Mono, monospace", color="#6B7280", size=10),
            gridcolor="rgba(0,0,0,0.04)", griddash="dash", gridwidth=0.5,
            zeroline=False,
        ),
        xaxis=dict(
            tickfont=dict(color="#6B7280", size=10),
            gridcolor="rgba(0,0,0,0.04)", griddash="dash", gridwidth=0.5,
            zeroline=False,
        ),
        hoverlabel=dict(
            bgcolor="#1A2540",
            font=dict(color="#FFFFFF", family="IBM Plex Mono, monospace", size=12),
            bordercolor="#1A2540",
        ),
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_portfolio_table(holdings: list, sym: str) -> None:
    """Styled HTML portfolio table with sort control + action controls below."""

    st.html("""
    <div style="margin:20px 0 8px;">
      <div style="font-size:15px;font-weight:700;color:#0F172A;">Holdings</div>
    </div>
    """)

    # ── Sort controls ────────────────────────────────────────
    sc1, sc2, sc3 = st.columns([2, 2, 6])
    with sc1:
        sort_by = st.selectbox(
            "Sort",
            ["P&L%", "Current MoS%", "Ticker", "Signal", "Entry Price", "Added Date"],
            key="_port_sort_col",
            label_visibility="collapsed",
        )
    with sc2:
        sort_dir = st.selectbox(
            "Order",
            ["↓ High → Low", "↑ Low → High"],
            key="_port_sort_dir",
            label_visibility="collapsed",
        )

    reverse = sort_dir.startswith("↓")
    sort_map = {
        "P&L%":         lambda h: h["pnl_pct"],
        "Current MoS%": lambda h: h["current_mos"],
        "Ticker":       lambda h: h["ticker"],
        "Signal":       lambda h: h.get("signal", ""),
        "Entry Price":  lambda h: h["entry_price"],
        "Added Date":   lambda h: h["saved_at"],
    }
    sorted_holdings = sorted(holdings, key=sort_map[sort_by], reverse=reverse)

    # ── Build rows ───────────────────────────────────────────
    rows_html = ""
    for i, h in enumerate(sorted_holdings):
        bg_row   = "#FFFFFF" if i % 2 == 0 else "#F9FAFB"
        sym_h    = h.get("sym", "$")
        lp       = h["live_price"]
        ep       = h["entry_price"]
        iv       = h.get("iv", 0)
        pnl_clr  = _pnl_color(h["pnl_pct"])
        arrow    = "▲" if h["pnl_pct"] >= 0 else "▼"
        mos_fg, mos_bg = _mos_cell_colors(h["current_mos"])
        saved_dt = h["saved_at"][:10]
        badge    = _sig_badge_html(h.get("signal", ""))

        rows_html += f"""
        <tr style="background:{bg_row};border-bottom:1px solid #F1F5F9;">
          <td style="padding:11px 14px;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                        font-weight:700;color:#1D4ED8;">{h['ticker']}</div>
            <div style="font-size:11px;color:#94A3B8;margin-top:1px;max-width:100px;
                        overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
              {h.get('company_name','')[:18]}
            </div>
          </td>
          <td style="padding:11px 14px;text-align:right;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                        color:#64748B;">{sym_h}{ep:,.2f}</div>
          </td>
          <td style="padding:11px 14px;text-align:right;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                        font-weight:600;color:#0F172A;">
              {f"{sym_h}{lp:,.2f}" if lp else "—"}
            </div>
          </td>
          <td style="padding:11px 14px;text-align:right;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                        font-weight:700;color:{pnl_clr};">
              {arrow} {sym_h}{abs(h['pnl_abs']):,.2f}
            </div>
          </td>
          <td style="padding:11px 14px;text-align:right;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                        font-weight:700;color:{pnl_clr};">
              {h['pnl_pct']:+.1f}%
            </div>
          </td>
          <td style="padding:11px 14px;text-align:right;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                        color:#475569;">{sym_h}{iv:,.2f}</div>
          </td>
          <td style="padding:8px 14px;text-align:center;">
            <div style="background:{mos_bg};color:{mos_fg};padding:3px 10px;
                        border-radius:6px;font-family:'IBM Plex Mono',monospace;
                        font-size:12px;font-weight:700;display:inline-block;">
              {h['current_mos']:+.1f}%
            </div>
          </td>
          <td style="padding:8px 14px;text-align:center;">{badge}</td>
          <td style="padding:11px 14px;text-align:center;">
            <div style="font-size:11px;color:#94A3B8;">{saved_dt}</div>
          </td>
          <td style="padding:8px 14px;text-align:center;">
            <div style="font-size:16px;color:#CBD5E1;letter-spacing:4px;">🗑&nbsp;📊&nbsp;📝</div>
          </td>
        </tr>"""

    header_cells = [
        ("TICKER",      "left"),
        ("ENTRY",       "right"),
        ("LIVE PRICE",  "right"),
        ("P&amp;L $",   "right"),
        ("P&amp;L %",   "right"),
        ("IV",          "right"),
        ("MOS%",        "center"),
        ("SIGNAL",      "center"),
        ("ADDED",       "center"),
        ("ACTIONS",     "center"),
    ]
    header_html = "".join(
        f'<th style="padding:10px 14px;font-family:Inter,sans-serif;font-size:11px;'
        f'font-weight:700;letter-spacing:0.10em;text-transform:uppercase;'
        f'color:#94A3B8;text-align:{align};white-space:nowrap;">{label}</th>'
        for label, align in header_cells
    )

    st.html(f"""
    <div style="border-radius:12px;border:1px solid #E2E8F0;overflow:hidden;
                box-shadow:0 1px 6px rgba(15,23,42,0.06);margin-bottom:8px;">
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;min-width:900px;">
          <thead>
            <tr style="background:#F8FAFC;border-bottom:1px solid #E2E8F0;">
              {header_html}
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>
    <div style="font-size:11px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;
                margin-bottom:20px;">
      P&L = live price vs entry price at save date · MoS% = (saved IV − live price) / live price ·
      Prices refresh every 2 min
    </div>
    """)

    # ── Action controls ──────────────────────────────────────
    st.html("""
    <div style="font-size:12px;font-weight:600;color:#475569;margin-bottom:8px;">
      Manage positions
    </div>
    """)

    ticker_options = [h["ticker"] for h in sorted_holdings]

    ac1, ac2, ac3, ac4, ac5 = st.columns([2, 1, 1, 1, 1])

    with ac1:
        selected = st.selectbox(
            "Select ticker",
            options=[""] + ticker_options,
            key="_port_action_select",
            label_visibility="collapsed",
            placeholder="Select a position…",
        )

    with ac2:
        if st.button("🗑 Remove", key="_port_remove_btn", use_container_width=True):
            if selected:
                remove_from_portfolio(selected)
                _fetch_live_price.clear()
                st.rerun()
            else:
                st.warning("Select a ticker first.")

    with ac3:
        if st.button("📊 Analyze", key="_port_analyze_btn", use_container_width=True):
            if selected:
                st.session_state["_prefill_ticker"] = selected
                st.session_state["_auto_analyse"]   = True
                st.rerun()
            else:
                st.warning("Select a ticker first.")

    with ac4:
        # Export CSV
        df_export = pd.DataFrame([{
            "Ticker":      h["ticker"],
            "Company":     h.get("company_name", ""),
            "Entry Price": h["entry_price"],
            "Live Price":  h["live_price"],
            "P&L %":       round(h["pnl_pct"], 2),
            "P&L Abs":     round(h["pnl_abs"], 2),
            "Signal":      h["signal"],
            "Saved IV":    h["iv"],
            "MoS at Save": h["mos_pct"],
            "Current MoS": round(h["current_mos"], 2),
            "WACC":        h["wacc"],
            "Notes":       h.get("notes", ""),
            "Saved At":    h["saved_at"],
        } for h in holdings])
        st.download_button(
            "⬇ Export CSV",
            data=df_export.to_csv(index=False).encode("utf-8"),
            file_name=f"yieldiq_portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
            key="_port_export_btn",
        )

    with ac5:
        if st.button("↻ Refresh", key="_port_refresh_btn", use_container_width=True):
            _fetch_live_price.clear()
            st.rerun()

    # ── Notes editor ─────────────────────────────────────────
    if selected:
        with st.expander(f"📝 Edit notes for {selected}", expanded=False):
            current_notes = next(
                (h.get("notes", "") for h in holdings if h["ticker"] == selected), ""
            )
            new_notes = st.text_area(
                "Notes",
                value=current_notes,
                height=100,
                key=f"_notes_{selected}",
                label_visibility="collapsed",
                placeholder="e.g. Strong moat, buying on dip, watching for breakout…",
            )
            if st.button("Save Notes", key=f"_save_notes_{selected}", type="primary"):
                update_notes(selected, new_notes)
                st.success("Notes saved.")
                st.rerun()


def _render_add_form(analysed_ticker: str, analysed_data: dict | None, sym: str) -> None:
    """Add-to-portfolio panel — auto-fills if a stock was just analysed."""
    # ── Pre-filled from analysis ──────────────────────────────
    if analysed_ticker and analysed_data:
        already_saved = is_in_portfolio(analysed_ticker)
        action_label  = "Update Position" if already_saved else "Save to Portfolio"
        mos       = analysed_data.get("mos_pct", 0)
        raw_sig   = analysed_data.get("signal", "")
        ep        = analysed_data.get("entry_price", 0)
        iv        = analysed_data.get("iv", 0)
        sig_clr   = _sig_color(raw_sig, mos)
        bg_clr    = "#ECFDF5" if mos >= 0 else "#FEF2F2"
        bd_clr    = "#A7F3D0" if mos >= 0 else "#FECACA"
        lbl_txt   = "✓ IN PORTFOLIO — UPDATE?" if already_saved else "💼 ADD TO PORTFOLIO"

        st.html(f"""
        <div style="margin:16px 0 0;">
          <div style="font-size:15px;font-weight:700;color:#0F172A;margin-bottom:10px;">
            Save Current Analysis
          </div>
        </div>
        """)

        st.html(f"""
        <div style="background:{bg_clr};border:1px solid {bd_clr};border-radius:12px;
                    padding:16px 20px;margin-bottom:10px;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;
                      color:{sig_clr};letter-spacing:0.10em;text-transform:uppercase;
                      margin-bottom:12px;">{lbl_txt}</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
            <div>
              <div style="font-size:10px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;
                          letter-spacing:0.10em;text-transform:uppercase;margin-bottom:3px;">
                Ticker</div>
              <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;
                          font-weight:700;color:#1D4ED8;">{analysed_ticker}</div>
            </div>
            <div>
              <div style="font-size:10px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;
                          letter-spacing:0.10em;text-transform:uppercase;margin-bottom:3px;">
                Current Price</div>
              <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;
                          font-weight:600;color:#0F172A;">{sym}{ep:,.2f}</div>
            </div>
            <div>
              <div style="font-size:10px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;
                          letter-spacing:0.10em;text-transform:uppercase;margin-bottom:3px;">
                Intrinsic Value</div>
              <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;
                          font-weight:600;color:{sig_clr};">{sym}{iv:,.2f}</div>
            </div>
            <div>
              <div style="font-size:10px;color:#94A3B8;font-family:'IBM Plex Mono',monospace;
                          letter-spacing:0.10em;text-transform:uppercase;margin-bottom:3px;">
                Margin of Safety</div>
              <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;
                          font-weight:700;color:{sig_clr};">{mos:+.1f}%</div>
            </div>
          </div>
        </div>
        """)

        n_col, b_col = st.columns([4, 1])
        with n_col:
            notes_val = st.text_input(
                "Investment thesis / notes",
                placeholder="e.g. Strong moat, buying on dip, watching for entry below $170…",
                label_visibility="collapsed",
                key=f"notes_input_{analysed_ticker}",
            )
        with b_col:
            if st.button(action_label, key=f"save_btn_{analysed_ticker}",
                         use_container_width=True, type="primary"):
                ok = save_to_portfolio(
                    ticker       = analysed_ticker,
                    entry_price  = ep,
                    iv           = iv,
                    mos_pct      = mos,
                    signal       = raw_sig,
                    wacc         = analysed_data.get("wacc", 0),
                    sym          = sym,
                    to_code      = analysed_data.get("to_code", "USD"),
                    company_name = analysed_data.get("company_name", ""),
                    sector       = analysed_data.get("sector", ""),
                    notes        = notes_val,
                )
                if ok:
                    verb = "updated" if already_saved else "saved"
                    st.success(f"✓ {analysed_ticker} {verb}!")
                    st.rerun()

    # ── Manual add expander ───────────────────────────────────
    with st.expander("➕ Add position manually", expanded=False):
        st.html("""
        <div style="font-size:13px;color:#64748B;margin-bottom:12px;">
          Add any stock to your portfolio with a custom entry price and notes.
        </div>
        """)
        t_col, p_col = st.columns([2, 1])
        with t_col:
            manual_ticker = st.text_input(
                "Ticker symbol",
                placeholder="AAPL, MSFT, NVDA…",
                key="_manual_add_ticker",
            )
            if manual_ticker and len(manual_ticker) >= 2:
                co = _lookup_company(manual_ticker.strip().upper())
                if co:
                    st.html(
                        f'<div style="font-size:12px;color:#1D4ED8;font-weight:600;'
                        f'margin-top:-6px;margin-bottom:4px;">✓ {co}</div>'
                    )
        with p_col:
            manual_price = st.number_input(
                "Entry price",
                min_value=0.0, step=0.01, format="%.2f",
                key="_manual_add_price",
            )

        manual_iv = st.number_input(
            "Intrinsic value (optional)",
            min_value=0.0, step=0.01, format="%.2f",
            key="_manual_add_iv",
        )
        manual_notes = st.text_area(
            "Notes",
            height=80,
            placeholder="Why are you adding this position?",
            key="_manual_add_notes",
            label_visibility="visible",
        )

        if st.button("Save to Portfolio", key="_manual_save_btn",
                     type="primary", use_container_width=True):
            t = (manual_ticker or "").strip().upper()
            if not t:
                st.error("Enter a valid ticker.")
            elif manual_price <= 0:
                st.error("Enter a valid entry price.")
            else:
                mos_m = (manual_iv - manual_price) / manual_price * 100 if manual_iv > 0 else 0.0
                co_m  = _lookup_company(t) or t
                ok = save_to_portfolio(
                    ticker       = t,
                    entry_price  = manual_price,
                    iv           = manual_iv,
                    mos_pct      = mos_m,
                    signal       = "Undervalued" if mos_m > 0 else "Overvalued" if mos_m < 0 else "Neutral",
                    wacc         = 0.0,
                    sym          = sym,
                    company_name = co_m,
                    notes        = manual_notes,
                )
                if ok:
                    st.success(f"✓ {t} added to portfolio!")
                    st.rerun()


def _render_watchlist_section(sym: str) -> None:
    """Watchlist cards in a 3-column grid below the portfolio table."""
    init_watchlist_db()
    items = get_watchlist()

    st.html("""
    <div style="margin:28px 0 10px;">
      <div style="font-size:15px;font-weight:700;color:#0F172A;">Watchlist</div>
      <div style="font-size:12px;color:#64748B;margin-top:2px;">
        Stocks you're monitoring — analyze any with one click
      </div>
    </div>
    """)

    if not items:
        st.html("""
        <div style="text-align:center;padding:36px 20px;background:#F8FAFC;
                    border:1.5px dashed #CBD5E1;border-radius:12px;margin-bottom:20px;">
          <div style="font-size:28px;margin-bottom:8px;">👁</div>
          <div style="font-size:14px;font-weight:600;color:#475569;">
            Your watchlist is empty
          </div>
          <div style="font-size:12px;color:#94A3B8;margin-top:4px;">
            Add stocks from the analysis tab to track them here.
          </div>
        </div>
        """)
        return

    # Render 3-column card grid
    for row_start in range(0, len(items), 3):
        row_items = items[row_start:row_start + 3]
        cols = st.columns(3, gap="small")
        for col, item in zip(cols, row_items):
            ticker   = item["ticker"]
            co_name  = item.get("company_name", "") or ticker
            added_at = item.get("added_at", "")[:10]
            ap       = item.get("added_price", 0)
            tp       = item.get("target_price", 0)

            live_p   = _fetch_live_price(ticker)
            chg      = ((live_p - ap) / ap * 100) if ap > 0 and live_p > 0 else None
            chg_clr  = "#059669" if (chg or 0) >= 0 else "#DC2626"
            chg_arr  = "▲" if (chg or 0) >= 0 else "▼"
            price_str = f"{sym}{live_p:,.2f}" if live_p > 0 else "—"

            tp_html = ""
            if tp > 0:
                tp_html = (
                    f'<div style="font-size:11px;color:#64748B;margin-top:3px;">'
                    f'Target: {sym}{tp:,.2f}</div>'
                )

            chg_html = ""
            if chg is not None and ap > 0:
                chg_html = (
                    f'<span style="font-size:11px;color:{chg_clr};font-weight:600;'
                    f'margin-left:6px;">{chg_arr} {abs(chg):.1f}%</span>'
                )

            with col:
                st.html(f"""
                <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                            padding:16px;box-shadow:0 1px 4px rgba(15,23,42,0.05);
                            border-left:3px solid #1D4ED8;margin-bottom:4px;">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                                  font-weight:700;color:#1D4ED8;">{ticker}</div>
                      <div style="font-size:11px;color:#94A3B8;margin-top:1px;
                                  max-width:130px;overflow:hidden;text-overflow:ellipsis;
                                  white-space:nowrap;">{co_name}</div>
                    </div>
                    <div style="text-align:right;">
                      <div style="font-family:'IBM Plex Mono',monospace;font-size:15px;
                                  font-weight:600;color:#0F172A;">{price_str}{chg_html}</div>
                      {tp_html}
                    </div>
                  </div>
                  <div style="font-size:10px;color:#CBD5E1;margin-top:10px;">
                    Added {added_at}
                  </div>
                </div>
                """)
                btn_col, rm_col = st.columns([3, 1])
                with btn_col:
                    if st.button(
                        f"Analyze {ticker} →",
                        key=f"_wl_analyze_{ticker}",
                        use_container_width=True,
                        type="primary",
                    ):
                        st.session_state["_prefill_ticker"] = ticker
                        st.session_state["_auto_analyse"]   = True
                        st.rerun()
                with rm_col:
                    if st.button("✕", key=f"_wl_remove_{ticker}",
                                 use_container_width=True):
                        remove_from_watchlist(ticker)
                        st.rerun()


def _render_empty_state() -> None:
    st.html("""
    <div style="text-align:center;padding:60px 40px;background:#F8FAFC;
                border:1.5px dashed #CBD5E1;border-radius:16px;margin:16px 0;">
      <div style="font-size:48px;margin-bottom:16px;">📂</div>
      <div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:10px;">
        No positions saved yet
      </div>
      <div style="font-size:13px;color:#64748B;line-height:1.8;max-width:380px;margin:0 auto;">
        Analyse a stock in the Stock Analysis tab, then save it here.<br>
        YieldIQ will track live price and P&L from your save date.
      </div>
    </div>
    """)


# ════════════════════════════════════════════════════════════════
# GOOGLE SHEETS SYNC (unchanged)
# ════════════════════════════════════════════════════════════════

def _render_sheets_sync(holdings: list) -> None:
    """
    Render the 'Sync to Google Sheets' UI block inside the Portfolio tab.
    Tier-gated to Starter and Pro only.
    """
    import importlib, sys as _sys, pathlib as _pl
    _tg = None
    for mod_name in list(_sys.modules.keys()):
        mod = _sys.modules[mod_name]
        if hasattr(mod, "can") and hasattr(mod, "tier") and hasattr(mod, "LIMITS"):
            _tg = mod
            break

    def _can_sheets() -> bool:
        if _tg is None:
            return False
        return bool(_tg.LIMITS.get(_tg.tier(), {}).get("sheets_sync", False))

    st.markdown("---")
    st.html(
        '<div style="font-size:13px;font-weight:700;color:#475569;'
        'text-transform:uppercase;letter-spacing:0.04em;margin-bottom:8px;">'
        '📊 Google Sheets Sync</div>'
    )

    if not _can_sheets():
        st.html("""
        <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;
                    background:#F8FAFC;border:1.5px solid #E2E8F0;border-radius:10px;">
          <span style="font-size:20px">📊</span>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:#0d1117">Sync to Google Sheets</div>
            <div style="font-size:12px;color:#8492a6">
              Export your portfolio to a live Google Sheet with auto-formatting —
              Starter &amp; Pro only.
            </div>
          </div>
          <a href="https://yourdomain.com/pricing.html" target="_blank"
             style="background:#5046e4;color:#fff;font-size:12px;font-weight:600;
                    padding:7px 14px;border-radius:7px;text-decoration:none;white-space:nowrap;">
            Upgrade →
          </a>
        </div>
        """)
        return

    try:
        _dash_dir = str(_pl.Path(__file__).parent)
        if _dash_dir not in _sys.path:
            _sys.path.insert(0, _dash_dir)
        from sheets_export import (
            export_portfolio_to_sheets,
            get_service_account_email,
            is_configured,
        )
        _sheets_ok = True
    except ImportError:
        _sheets_ok = False

    if not _sheets_ok:
        st.warning(
            "📦 `gspread` and `google-auth` are not installed. "
            "Run: `pip install gspread google-auth`"
        )
        return

    if not is_configured():
        st.info(
            "⚙️ **Google Sheets not configured.** "
            "Set the `GOOGLE_SHEETS_CREDENTIALS` environment variable with your "
            "service-account JSON to enable this feature.",
            icon="ℹ️",
        )
        return

    user_email  = st.session_state.get("auth_email", "")
    sheets_info = get_sheets_info(user_email)
    existing_id = sheets_info.get("sheets_id",   "")
    existing_url= sheets_info.get("sheets_url",  "")
    last_synced = sheets_info.get("last_synced", "")

    sa_email = get_service_account_email()

    sync_col, info_col = st.columns([2, 3])

    with sync_col:
        google_email = st.text_input(
            "Your Google email (to share the sheet with)",
            value=user_email if "@" in (user_email or "") else "",
            placeholder="you@gmail.com",
            key="sheets_google_email",
            help="The sheet will be shared with this Google account.",
        )
        sheet_title = st.text_input(
            "Spreadsheet title",
            value="YieldIQ Portfolio",
            key="sheets_title",
        )
        if st.button(
            "📊 Sync to Google Sheets",
            key="sheets_sync_btn",
            use_container_width=True,
            type="primary",
        ):
            if not google_email or "@" not in google_email:
                st.error("Enter a valid Google email to share the sheet.")
            else:
                with st.spinner("Exporting to Google Sheets…"):
                    try:
                        url, sheet_id = export_portfolio_to_sheets(
                            holdings          = holdings,
                            user_email        = google_email,
                            spreadsheet_title = sheet_title,
                            existing_sheet_id = existing_id or None,
                        )
                        save_sheets_url(user_email, url, sheet_id)
                        st.session_state["_sheets_url"]    = url
                        st.session_state["_sheets_synced"] = \
                            datetime.now().strftime("%d %b %Y %H:%M")
                        st.success("✓ Portfolio synced!")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Sheets sync failed: {_e}")

    with info_col:
        _url  = st.session_state.get("_sheets_url",    existing_url)
        _sync = st.session_state.get("_sheets_synced", last_synced[:16] if last_synced else "")

        if _url:
            st.html(f"""
            <div style="padding:14px 16px;background:#F0F9FF;border:1px solid #BAE6FD;
                        border-radius:10px;">
              <div style="font-size:11px;color:#0369A1;font-weight:700;
                          text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">
                Linked Sheet
              </div>
              <a href="{_url}" target="_blank"
                 style="font-size:13px;font-weight:600;color:#0369A1;
                        word-break:break-all;text-decoration:none;">
                📄 Open in Google Sheets →
              </a>
              {"<div style='font-size:11px;color:#64748B;margin-top:6px;'>"
               "Last synced: " + _sync + "</div>" if _sync else ""}
            </div>
            """)
        else:
            st.html("""
            <div style="padding:14px 16px;background:#F8FAFC;border:1px solid #E2E8F0;
                        border-radius:10px;">
              <div style="font-size:12px;color:#64748B;line-height:1.7;">
                Enter your Google email and click <b>Sync</b> to create a formatted sheet
                with all your holdings, P&amp;L, signals, and annualized returns.<br>
                The sheet is re-synced (overwritten) each time you click the button.
              </div>
            </div>
            """)

        if sa_email:
            st.caption(
                f"ℹ️ The sheet is created by service account `{sa_email}` "
                "and shared with your email automatically."
            )


# ════════════════════════════════════════════════════════════════
# MAIN TAB RENDERER
# ════════════════════════════════════════════════════════════════

def render_portfolio_tab(
    sym: str = "$",
    analysed_ticker: str = "",
    analysed_data: dict = None,
) -> None:
    """
    Render the full Portfolio tab.
    Call this inside `with tab_portfolio:`.

    Args:
        sym:              Currency symbol from sidebar
        analysed_ticker:  Currently analysed ticker (to show Save button)
        analysed_data:    Dict with current analysis results
    """
    init_db()

    # ── Page header ───────────────────────────────────────────
    st.html("""
    <div style="padding:4px 0 20px;">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;
                  letter-spacing:0.14em;text-transform:uppercase;color:#94A3B8;
                  margin-bottom:4px;">Research Portfolio</div>
      <div style="font-size:22px;font-weight:700;color:#0F172A;">
        My Positions &amp; Watchlist
      </div>
      <div style="font-size:12px;color:#64748B;margin-top:4px;">
        Save stocks after analysis to track live P&amp;L vs your YieldIQ call.
        Prices refresh every 2 minutes.
      </div>
    </div>
    """)

    # ── Fetch holdings + enrich with live prices ──────────────
    holdings = get_portfolio()
    if holdings:
        with st.spinner("Fetching live prices…"):
            _enrich_with_live_prices(holdings)

    # ── 1. KPI cards ──────────────────────────────────────────
    if holdings:
        _render_kpi_cards(holdings, sym)
    else:
        _render_empty_state()

    # ── 2. Add / save form ────────────────────────────────────
    _render_add_form(analysed_ticker, analysed_data or {}, sym)

    if not holdings:
        _render_watchlist_section(sym)
        return

    # ── 3. Performance chart ──────────────────────────────────
    _render_performance_chart(holdings)

    # ── 4. Holdings table ─────────────────────────────────────
    _render_portfolio_table(holdings, sym)

    # ── 5. Watchlist ──────────────────────────────────────────
    _render_watchlist_section(sym)

    # ── 6. Google Sheets sync ─────────────────────────────────
    _render_sheets_sync(holdings)
