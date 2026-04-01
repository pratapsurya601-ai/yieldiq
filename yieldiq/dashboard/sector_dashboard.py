# dashboard/sector_dashboard.py  v4
# ═══════════════════════════════════════════════════════════════
# YieldIQ Sector Dashboard — Bloomberg-grade Market Terminal
#
# v4 upgrades:
#   1. Plotly Treemap sector heatmap (replaces CSS grid)
#   2. 4-segment market breadth bar (BUY/WATCH/HOLD/SELL)
#   3. Top-5 opportunity card strip with Analyze buttons
#   4. Sector detail expander: click treemap or use dropdown
#   5. Cache freshness indicator
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import json
import sqlite3
import threading
import pathlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_HERE        = pathlib.Path(__file__).parent
_TICKERS_CSV = _HERE.parent / "data" / "usa_tickers.csv"
_DB_PATH     = _HERE / "sector_cache.db"
_lock        = threading.Lock()

COVERAGE = {
    "Technology":             28,
    "Healthcare":             26,
    "Financials":             26,
    "Industrials":            30,
    "Consumer Discretionary": 19,
    "Consumer Staples":       15,
    "Energy":                 12,
    "Materials":              11,
    "Real Estate":            10,
    "Communication Services":  9,
    "Utilities":               9,
}

SECTOR_SHORT = {
    "Technology":             "Technology",
    "Healthcare":             "Healthcare",
    "Financials":             "Financials",
    "Industrials":            "Industrials",
    "Consumer Discretionary": "Consumer Disc.",
    "Consumer Staples":       "Cons. Staples",
    "Energy":                 "Energy",
    "Materials":              "Materials",
    "Real Estate":            "Real Estate",
    "Communication Services": "Communication",
    "Utilities":              "Utilities",
}

def _confidence(n):
    if n >= 20: return "High",   "#059669"
    if n >= 10: return "Medium", "#D97706"
    return           "Low",    "#DC2626"

SECTOR_REPS = {
    "Technology":             ["MSFT", "AAPL", "NVDA", "GOOGL", "META"],
    "Healthcare":             ["LLY",  "UNH",  "ABBV", "JNJ",   "MRK"],
    "Financials":             ["V",    "MA",   "JPM",  "GS",    "SPGI"],
    "Industrials":            ["CAT",  "HON",  "UPS",  "RTX",   "GE"],
    "Consumer Discretionary": ["AMZN", "HD",   "MCD",  "NKE",   "BKNG"],
    "Consumer Staples":       ["PG",   "KO",   "PEP",  "WMT",   "COST"],
    "Energy":                 ["XOM",  "CVX",  "COP",  "SLB",   "PSX"],
    "Materials":              ["LIN",  "APD",  "ECL",  "NEM",   "FCX"],
    "Real Estate":            ["AMT",  "PLD",  "CCI",  "EQIX",  "SPG"],
    "Communication Services": ["GOOGL","META", "NFLX", "DIS",   "T"],
    "Utilities":              ["NEE",  "DUK",  "SO",   "AEP",   "EXC"],
}

SECTOR_ICONS = {
    "Technology":             "💻",
    "Healthcare":             "🏥",
    "Financials":             "🏦",
    "Industrials":            "🏭",
    "Consumer Discretionary": "🛍️",
    "Consumer Staples":       "🛒",
    "Energy":                 "⚡",
    "Materials":              "⚗️",
    "Real Estate":            "🏢",
    "Communication Services": "📡",
    "Utilities":              "💡",
}

SECTOR_ORDER = [
    "Technology", "Healthcare", "Financials", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Energy",
    "Communication Services", "Materials", "Real Estate", "Utilities",
]


# ══════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════

def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_sector_db():
    with _lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sector_dcf_cache (
                sector      TEXT PRIMARY KEY,
                avg_mos     REAL,
                pct_under   REAL,
                pct_over    REAL,
                avg_wacc    REAL,
                top_pick    TEXT,
                stocks_json TEXT,
                updated_at  TEXT
            )
        """)
        conn.commit()
        conn.close()


def get_cached_dcf():
    init_sector_db()
    try:
        with _lock:
            conn = _get_conn()
            rows = conn.execute("SELECT * FROM sector_dcf_cache").fetchall()
            conn.close()
        return {
            r["sector"]: {
                "avg_mos":    r["avg_mos"],
                "pct_under":  r["pct_under"],
                "pct_over":   r["pct_over"],
                "avg_wacc":   r["avg_wacc"],
                "top_pick":   r["top_pick"] or "",
                "stocks":     json.loads(r["stocks_json"] or "[]"),
                "updated_at": r["updated_at"] or "",
            }
            for r in rows
        }
    except Exception:
        return {}


def _cache_age_hours(dcf_cache):
    if not dcf_cache:
        return None
    timestamps = [v["updated_at"] for v in dcf_cache.values() if v.get("updated_at")]
    if not timestamps:
        return None
    latest_str = max(timestamps)
    try:
        latest_dt = datetime.strptime(latest_str, "%Y-%m-%d %H:%M")
        return (datetime.now() - latest_dt).total_seconds() / 3600
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# SNAPSHOT
# ══════════════════════════════════════════════════════════════

def _fetch_one_sector_stock(tk: str) -> dict:
    """Fetch one ticker's snapshot data. Used in parallel by fetch_sector_snapshot."""
    try:
        import yfinance as yf
        t    = yf.Ticker(tk)
        fi   = t.fast_info
        price   = float(getattr(fi, "last_price", 0) or 0)
        prev    = float(getattr(fi, "previous_close", 0) or 0)
        mkt_cap = float(getattr(fi, "market_cap", 0) or 0)
        chg_pct = (price - prev) / prev * 100 if prev > 0 and price > 0 else 0.0
        try:
            info    = t.info or {}
            reg_chg = float(info.get("regularMarketChangePercent", 0) or 0)
            if reg_chg != 0:
                chg_pct = reg_chg
            fwd_pe    = float(info.get("forwardPE", 0) or 0)
            trail_pe  = float(info.get("trailingPE", 0) or 0)
            ev_ebitda = float(info.get("enterpriseToEbitda", 0) or 0)
            rev_g     = float(info.get("revenueGrowth", 0) or 0) * 100
            w52_hi    = float(info.get("fiftyTwoWeekHigh", 0) or 0)
            w52_lo    = float(info.get("fiftyTwoWeekLow", 0) or 0)
            rec       = info.get("recommendationKey") or ""
            div_y     = float(info.get("dividendYield", 0) or 0) * 100
            name      = info.get("shortName", tk)[:20]
            if mkt_cap == 0:
                mkt_cap = float(info.get("marketCap", 0) or 0)
        except Exception:
            fwd_pe = trail_pe = ev_ebitda = rev_g = w52_hi = w52_lo = div_y = 0.0
            rec = ""; name = tk
        w52_pos = (price - w52_lo) / (w52_hi - w52_lo) * 100 if w52_hi > w52_lo else 50
        return {
            "ticker": tk, "name": name,
            "price": price, "chg_pct": chg_pct, "fwd_pe": fwd_pe,
            "trail_pe": trail_pe, "ev_ebitda": ev_ebitda, "rev_g": rev_g,
            "mkt_cap": mkt_cap, "w52_pos": w52_pos, "rec": rec, "div_y": div_y,
        }
    except Exception:
        return {
            "ticker": tk, "name": tk, "price": 0, "chg_pct": 0,
            "fwd_pe": 0, "trail_pe": 0, "ev_ebitda": 0, "rev_g": 0,
            "mkt_cap": 0, "w52_pos": 50, "rec": "", "div_y": 0,
        }


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_sector_snapshot():
    """
    Fetch snapshot data for all sector representative tickers.
    PERFORMANCE FIX: All tickers fetched IN PARALLEL via ThreadPoolExecutor.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_tickers = []
    for sector in SECTOR_ORDER:
        all_tickers.extend(SECTOR_REPS.get(sector, []))
    all_tickers = list(dict.fromkeys(all_tickers))

    ticker_data = {}
    with ThreadPoolExecutor(max_workers=min(12, len(all_tickers))) as pool:
        futures = {pool.submit(_fetch_one_sector_stock, tk): tk for tk in all_tickers}
        for fut in as_completed(futures, timeout=30):
            tk = futures[fut]
            try:
                ticker_data[tk] = fut.result()
            except Exception:
                ticker_data[tk] = {
                    "ticker": tk, "name": tk, "price": 0, "chg_pct": 0,
                    "fwd_pe": 0, "trail_pe": 0, "ev_ebitda": 0, "rev_g": 0,
                    "mkt_cap": 0, "w52_pos": 50, "rec": "", "div_y": 0,
                }

    results = {}
    for sector in SECTOR_ORDER:
        tickers = SECTOR_REPS.get(sector, [])
        stocks  = [ticker_data.get(tk, {"ticker": tk, "name": tk, "price": 0,
                   "chg_pct": 0, "fwd_pe": 0, "trail_pe": 0, "ev_ebitda": 0,
                   "rev_g": 0, "mkt_cap": 0, "w52_pos": 50, "rec": "", "div_y": 0})
                   for tk in tickers]
        prices    = [s["price"]   for s in stocks if s["price"] > 0]
        chgs      = [s["chg_pct"] for s in stocks if s["price"] > 0]
        _pe_vals  = [s["fwd_pe"]  for s in stocks if s["fwd_pe"]  > 0]
        _rg_vals  = [s["rev_g"]   for s in stocks if s.get("rev_g",  0) != 0]
        _w52_vals = [s["w52_pos"] for s in stocks if s.get("w52_pos", 50) != 50]
        _avg_chg  = sum(chgs) / len(chgs) if chgs else 0
        results[sector] = {
            "stocks":     stocks,
            "avg_chg":    _avg_chg,
            "avg_pe":     sum(_pe_vals)  / len(_pe_vals)  if _pe_vals  else 0,
            "avg_fwd_pe": sum(_pe_vals)  / len(_pe_vals)  if _pe_vals  else 0,
            "avg_rev_g":  sum(_rg_vals)  / len(_rg_vals)  if _rg_vals  else 0,
            "avg_w52":    sum(_w52_vals) / len(_w52_vals)  if _w52_vals else 50,
            "sentiment":  ("Bullish" if _avg_chg > 0.5
                           else "Bearish" if _avg_chg < -0.5
                           else "Neutral"),
        }
    return results


# ══════════════════════════════════════════════════════════════
# DCF ENGINE
# ══════════════════════════════════════════════════════════════

def _dcf_one_sector(sector):
    import sys
    sys.path.insert(0, str(_HERE.parent))
    from data.collector    import StockDataCollector
    from data.processor    import compute_metrics
    from models.forecaster import FCFForecaster
    from screener.dcf_engine import DCFEngine, margin_of_safety, assign_signal
    try:
        from models.industry_wacc import get_industry_wacc
    except Exception:
        get_industry_wacc = None

    results = []
    for tk in SECTOR_REPS.get(sector, [])[:3]:
        try:
            raw = StockDataCollector(tk).get_all()
            if not raw: continue
            enriched = compute_metrics(raw)
            if not enriched.get("dcf_reliable", True): continue
            wacc = 0.10
            if get_industry_wacc:
                try: wacc = get_industry_wacc(enriched.get("sector", "general")).get("wacc", 0.10)
                except Exception: pass
            fr  = FCFForecaster().predict(enriched, years=10)
            res = DCFEngine(discount_rate=wacc, terminal_growth=0.03).intrinsic_value_per_share(
                projected_fcfs=fr["projections"], terminal_fcf_norm=fr["terminal_fcf_norm"],
                total_debt=enriched["total_debt"], total_cash=enriched["total_cash"],
                shares_outstanding=enriched["shares"], current_price=enriched["price"], ticker=tk,
            )
            iv = res.get("intrinsic_value_per_share", 0)
            price = enriched["price"]
            if iv > 0 and price > 0:
                mos = margin_of_safety(iv, price) * 100
                results.append({
                    "ticker": tk, "name": enriched.get("company_name", tk),
                    "sector": sector, "price": price, "iv": iv,
                    "mos": mos, "signal": assign_signal(mos / 100), "wacc": wacc,
                })
        except Exception:
            continue

    if not results:
        return {}
    avg_mos   = float(np.mean([r["mos"]  for r in results]))
    pct_under = sum(1 for r in results if r["mos"] > 0) / len(results) * 100
    return {
        "avg_mos":    avg_mos,
        "pct_under":  pct_under,
        "pct_over":   100 - pct_under,
        "avg_wacc":   float(np.mean([r["wacc"] for r in results])),
        "top_pick":   max(results, key=lambda r: r["mos"])["ticker"],
        "stocks":     results,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _save_sector_result(sector, data):
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sector_dcf_cache "
            "(sector,avg_mos,pct_under,pct_over,avg_wacc,top_pick,stocks_json,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sector, data["avg_mos"], data["pct_under"], data["pct_over"], data["avg_wacc"],
             data["top_pick"], json.dumps(data["stocks"]), data["updated_at"]),
        )
        conn.commit()
        conn.close()


def run_full_dcf(progress_cb=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    init_sector_db()
    dcf_sectors  = [s for s in SECTOR_ORDER if s not in {"Energy","Utilities","Real Estate","Communication Services","Materials"}]
    skip_sectors = [s for s in SECTOR_ORDER if s not in dcf_sectors]
    if progress_cb: progress_cb(0.05, f"Running DCF on {len(dcf_sectors)} sectors in parallel…")
    done = completed = 0
    futures = {}
    with ThreadPoolExecutor(max_workers=min(len(dcf_sectors), 6)) as pool:
        for sector in dcf_sectors:
            futures[pool.submit(_dcf_one_sector, sector)] = sector
        for future in as_completed(futures):
            sector = futures[future]; completed += 1
            if progress_cb: progress_cb(completed/len(dcf_sectors), f"Completed {sector} ({completed}/{len(dcf_sectors)})…")
            try:
                data = future.result()
                if data: _save_sector_result(sector, data); done += 1
            except Exception: pass
    if progress_cb: progress_cb(1.0, f"Done — {done} sectors computed, {len(skip_sectors)} skipped")
    return done


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _clr_mos(v):
    return "#059669" if v > 15 else "#D97706" if v > 0 else "#DC2626"

def _bg_mos(v):
    return ("#ECFDF5","#059669") if v>15 else ("#FFFBEB","#D97706") if v>0 else ("#FEF2F2","#DC2626")

def _clr_chg(v):
    return "#059669" if v > 0 else "#DC2626" if v < 0 else "#64748B"

def _clr_sent(s):
    return {"Bullish":"#059669","Bearish":"#DC2626"}.get(s,"#D97706")

def _mos_hex(mos: float) -> str:
    """Map MoS value to treemap cell colour per spec."""
    if mos > 30:  return "#059669"   # bright green
    if mos > 15:  return "#6EE7B7"   # light green
    if mos > 0:   return "#FCD34D"   # yellow
    if mos > -15: return "#FCA5A5"   # light red
    return               "#DC2626"   # bright red

def _badge(text, color):
    return (f'<span style="padding:2px 8px;background:{color}18;border:1px solid {color}44;'
            f'border-radius:4px;font-family:"IBM Plex Mono",monospace;font-size:11px;'
            f'font-weight:700;color:{color};">{text}</span>')

def _sig_badge_css(sig: str) -> tuple[str, str, str]:
    """Returns (text_color, bg_color, border_color)."""
    s = (sig or "").upper()
    if "STRONG BUY" in s or s == "BUY": return "#166534", "#DCFCE7", "#BBF7D0"
    if "WATCH"      in s:               return "#854D0E", "#FEF9C3", "#FDE68A"
    if "HOLD"       in s:               return "#92400E", "#FEF3C7", "#FCD34D"
    if "SELL"       in s:               return "#991B1B", "#FEE2E2", "#FECACA"
    return                              "#475569", "#F1F5F9", "#E2E8F0"

def _classify_signal(sig: str) -> str:
    """Bucket signal into BUY / WATCH / HOLD / SELL."""
    s = (sig or "").upper()
    if "BUY"  in s: return "BUY"
    if "WATCH" in s: return "WATCH"
    if "HOLD"  in s: return "HOLD"
    if "SELL"  in s: return "SELL"
    return "WATCH"

def _section_title(text):
    return (
        f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:11px;font-weight:700;'
        f'letter-spacing:0.14em;text-transform:uppercase;color:#64748B;margin:18px 0 12px;'
        f'display:flex;align-items:center;gap:8px;">'
        f'<span style="display:inline-block;width:3px;height:14px;background:#1D4ED8;'
        f'border-radius:2px;flex-shrink:0;"></span>{text}</div>'
    )


# ══════════════════════════════════════════════════════════════
# SECTION 1 — PLOTLY TREEMAP HEATMAP
# ══════════════════════════════════════════════════════════════

def _render_treemap(dcf_cache: dict, snap: dict) -> str | None:
    """
    Plotly Treemap sector heatmap.
    Returns the sector name selected by clicking a cell, or None.
    """
    if not dcf_cache:
        st.html("""
<div style="padding:12px 16px;background:#FFF8ED;border:1px solid #FDE68A;
            border-radius:8px;font-size:12px;color:#92400E;
            font-family:'IBM Plex Mono',monospace;">
  ⚠️  Run Sector DCF to see Margin of Safety colours.
  Showing day-change colours below.
</div>""")

    labels, parents, values, colors, custom = [], [], [], [], []

    for sector in SECTOR_ORDER:
        n_cov    = COVERAGE.get(sector, 0)
        short    = SECTOR_SHORT.get(sector, sector)
        icon     = SECTOR_ICONS.get(sector, "")
        dcf      = dcf_cache.get(sector)
        snap_sec = snap.get(sector, {})

        if dcf:
            mos      = dcf["avg_mos"]
            n_stocks = len(dcf.get("stocks", []))
            top_pick = dcf.get("top_pick", "—")
            cell_clr = _mos_hex(mos)
            mos_txt  = f"{mos:+.1f}%"
            hover_extra = f"Top pick: <b>{top_pick}</b><br>{n_stocks} stocks analysed"
        else:
            chg      = snap_sec.get("avg_chg", 0)
            mos      = chg
            cell_clr = "#6EE7B7" if chg > 0 else "#FCA5A5" if chg < 0 else "#E2E8F0"
            mos_txt  = f"{chg:+.2f}% (day)"
            hover_extra = "DCF not yet run for this sector"

        labels.append(f"{icon} {short}<br><b>{mos_txt}</b>")
        parents.append("")
        values.append(max(n_cov, 1))
        colors.append(cell_clr)
        custom.append({
            "sector":   sector,
            "mos_txt":  mos_txt,
            "n_cov":    n_cov,
            "hover":    hover_extra,
        })

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        values=values,
        customdata=[[c["sector"], c["mos_txt"], c["n_cov"], c["hover"]] for c in custom],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Avg MoS: %{customdata[1]}<br>"
            "Coverage: %{customdata[2]} stocks<br>"
            "%{customdata[3]}"
            "<extra></extra>"
        ),
        marker=dict(
            colors=colors,
            line=dict(width=2, color="#FFFFFF"),
            pad=dict(t=8, l=4, r=4, b=4),
        ),
        textfont=dict(
            family="IBM Plex Mono, monospace",
            size=13,
            color="#0F172A",
        ),
        tiling=dict(squarifyratio=1),
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=48, l=0, r=0, b=4),
        height=380,
        title=dict(
            text="<b>Sector Valuation Heatmap</b>  —  Color = Average Margin of Safety",
            font=dict(size=13, color="#0F172A", family="Inter, sans-serif"),
            x=0, pad=dict(l=2),
        ),
    )

    # Colour legend
    st.html("""
<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px;align-items:center;">
  <span style="font-size:10px;font-weight:700;color:#64748B;text-transform:uppercase;
               letter-spacing:0.1em;">Colour key:</span>
  <span style="font-size:11px;color:#059669;background:#ECFDF5;border:1px solid #A7F3D0;
               border-radius:4px;padding:2px 8px;font-family:'IBM Plex Mono',monospace;">
    ▮ &gt;30% MoS</span>
  <span style="font-size:11px;color:#065F46;background:#6EE7B7;border:1px solid #A7F3D0;
               border-radius:4px;padding:2px 8px;font-family:'IBM Plex Mono',monospace;">
    ▮ 15–30%</span>
  <span style="font-size:11px;color:#78350F;background:#FCD34D;border:1px solid #FDE68A;
               border-radius:4px;padding:2px 8px;font-family:'IBM Plex Mono',monospace;">
    ▮ 0–15%</span>
  <span style="font-size:11px;color:#991B1B;background:#FCA5A5;border:1px solid #FECACA;
               border-radius:4px;padding:2px 8px;font-family:'IBM Plex Mono',monospace;">
    ▮ -15 to 0%</span>
  <span style="font-size:11px;color:#FFFFFF;background:#DC2626;border:1px solid #B91C1C;
               border-radius:4px;padding:2px 8px;font-family:'IBM Plex Mono',monospace;">
    ▮ &lt;-15%</span>
  <span style="font-size:11px;color:#64748B;margin-left:6px;">
    · Size = number of stocks in coverage</span>
</div>
""")

    event = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        config={"displayModeBar": False},
    )

    # Extract clicked sector from Plotly selection event
    clicked_sector = None
    try:
        pts = (event.selection or {}).get("points", []) if event else []
        if pts:
            # label is "icon shortname\n<b>mos</b>" — pull sector from customdata[0]
            raw_label = pts[0].get("label", "")
            # customdata comes as a list in the event
            cd = pts[0].get("customdata", [])
            if cd:
                clicked_sector = cd[0]  # sector full name
    except Exception:
        clicked_sector = None

    return clicked_sector


# ══════════════════════════════════════════════════════════════
# SECTION 2 — MARKET BREADTH BAR (4-segment: BUY/WATCH/HOLD/SELL)
# ══════════════════════════════════════════════════════════════

def _render_breadth_bar(dcf_cache: dict) -> None:
    if not dcf_cache:
        return

    all_stocks = []
    for d in dcf_cache.values():
        all_stocks.extend(d.get("stocks", []))
    if not all_stocks:
        return

    total = len(all_stocks)
    buckets = {"BUY": 0, "WATCH": 0, "HOLD": 0, "SELL": 0}
    n_under = 0
    for s in all_stocks:
        b = _classify_signal(s.get("signal", ""))
        buckets[b] += 1
        if s.get("mos", 0) > 0:
            n_under += 1

    pcts   = {k: v / total * 100 for k, v in buckets.items()}
    colors = {"BUY": "#059669", "WATCH": "#EAB308", "HOLD": "#94A3B8", "SELL": "#DC2626"}
    labels = {"BUY": "▲ BUY", "WATCH": "◆ WATCH", "HOLD": "● HOLD", "SELL": "▼ SELL"}

    # Build bar segments
    segments_html = ""
    for key in ["BUY", "WATCH", "HOLD", "SELL"]:
        pct = pcts[key]
        clr = colors[key]
        lbl = f"{labels[key]}  {pct:.0f}%" if pct >= 10 else ""
        segments_html += (
            f'<div style="width:{pct:.1f}%;background:{clr};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-family:\'IBM Plex Mono\',monospace;font-size:11px;font-weight:700;'
            f'color:#FFFFFF;white-space:nowrap;min-width:{max(pct*0.5,0):.0f}px;">'
            f'{lbl}</div>'
        )

    # Legend row
    legend_html = ""
    for key in ["BUY", "WATCH", "HOLD", "SELL"]:
        clr = colors[key]
        n   = buckets[key]
        p   = pcts[key]
        legend_html += (
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<div style="width:11px;height:11px;background:{clr};border-radius:2px;flex-shrink:0;"></div>'
            f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:12px;color:#0F172A;">'
            f'<strong>{n}</strong>'
            f'<span style="color:#64748B;"> {key} ({p:.0f}%)</span></span></div>'
        )

    st.html(f"""
<div style="margin:4px 0 18px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
    <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;
                letter-spacing:0.12em;text-transform:uppercase;color:#64748B;">
      Market Breadth — {total} Stocks Analysed
    </div>
    <div style="font-size:12px;color:#0F172A;">
      <strong style="color:#059669;">{n_under}</strong>
      <span style="color:#64748B;"> of {total} stocks are undervalued</span>
    </div>
  </div>
  <div style="display:flex;height:36px;border-radius:8px;overflow:hidden;
              border:1px solid #E2E8F0;box-shadow:0 1px 3px rgba(15,23,42,0.05);">
    {segments_html}
  </div>
  <div style="display:flex;gap:20px;margin-top:10px;flex-wrap:wrap;">
    {legend_html}
  </div>
</div>
""")


# ══════════════════════════════════════════════════════════════
# SECTION 3 — TOP OPPORTUNITIES STRIP
# ══════════════════════════════════════════════════════════════

def _render_top_opportunities(dcf_cache: dict) -> None:
    if not dcf_cache:
        return

    all_stocks = []
    for sector, d in dcf_cache.items():
        for s in d.get("stocks", []):
            sc = dict(s)
            if "sector" not in sc:
                sc["sector"] = sector
            all_stocks.append(sc)
    if not all_stocks:
        return

    top5 = sorted(all_stocks, key=lambda s: s.get("mos", -999), reverse=True)[:5]

    st.html(_section_title("TODAY'S TOP 5 OPPORTUNITIES"))

    cols = st.columns(len(top5), gap="small")
    for col, stock in zip(cols, top5):
        mos     = stock.get("mos", 0)
        ticker  = stock.get("ticker", "")
        name    = stock.get("name", ticker)[:18]
        sector  = stock.get("sector", "")
        price   = stock.get("price", 0)
        iv      = stock.get("iv", 0)
        sig     = stock.get("signal", "WATCH")
        icon    = SECTOR_ICONS.get(sector, "")

        sig_tc, sig_bg, sig_bd = _sig_badge_css(sig)
        mos_clr = "#059669" if mos >= 15 else "#D97706" if mos >= 0 else "#DC2626"
        mos_bg  = "#ECFDF5" if mos >= 15 else "#FFFBEB" if mos >= 0 else "#FEF2F2"
        mos_bd  = "#A7F3D0" if mos >= 15 else "#FDE68A" if mos >= 0 else "#FECACA"

        with col:
            st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-top:3px solid {mos_clr};
            border-radius:12px;padding:14px 14px 10px;
            box-shadow:0 2px 6px rgba(15,23,42,0.06);">

  <!-- Sector tag -->
  <div style="font-size:10px;font-weight:600;color:#64748B;margin-bottom:8px;">
    {icon} {sector[:16]}
  </div>

  <!-- Ticker -->
  <div style="font-family:'IBM Plex Mono',monospace;font-size:17px;font-weight:800;
              color:#1D4ED8;margin-bottom:2px;">{ticker}</div>

  <!-- Company -->
  <div style="font-size:11px;color:#64748B;margin-bottom:10px;
              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>

  <!-- Signal badge -->
  <div style="display:inline-block;margin-bottom:10px;">
    <span style="font-size:10px;font-weight:700;color:{sig_tc};
                 background:{sig_bg};border:1px solid {sig_bd};
                 border-radius:20px;padding:3px 10px;
                 font-family:'IBM Plex Mono',monospace;">{sig}</span>
  </div>

  <!-- MoS large number -->
  <div style="background:{mos_bg};border:1px solid {mos_bd};
              border-radius:8px;padding:8px 10px;text-align:center;margin-bottom:6px;">
    <div style="font-family:'IBM Plex Mono',monospace;font-size:24px;font-weight:800;
                color:{mos_clr};line-height:1;">{mos:+.1f}%</div>
    <div style="font-size:9px;color:{mos_clr};text-transform:uppercase;
                letter-spacing:0.08em;margin-top:2px;">Margin of Safety</div>
  </div>

  <!-- Price / IV -->
  <div style="font-size:10px;color:#94A3B8;text-align:center;
              font-family:'IBM Plex Mono',monospace;">
    IV ${iv:,.0f} · Price ${price:,.0f}
  </div>
</div>
""")
            st.html('<div style="height:6px;"></div>')
            if st.button(
                f"Analyze {ticker} →",
                key=f"opp_{ticker}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["_prefill_ticker"] = ticker
                st.rerun()


# ══════════════════════════════════════════════════════════════
# SECTION 4 — SECTOR DETAIL EXPANDER
# ══════════════════════════════════════════════════════════════

def _render_sector_detail(dcf_cache: dict, snap: dict, active_sector: str | None) -> None:
    """
    Dropdown selector + expander table for the selected sector.
    Shows: Ticker | Company | Price | IV | MoS% | Signal | P/E | EV/EBITDA
    """
    if not dcf_cache:
        return

    available = [s for s in SECTOR_ORDER if s in dcf_cache and dcf_cache[s].get("stocks")]
    if not available:
        return

    st.html(_section_title("SECTOR DETAIL — SELECT A SECTOR TO DRILL DOWN"))

    # Dropdown — pre-select clicked sector from treemap if available
    options   = ["— Select a sector —"] + available
    default_i = 0
    if active_sector and active_sector in available:
        default_i = available.index(active_sector) + 1

    chosen = st.selectbox(
        "Sector",
        options,
        index=default_i,
        label_visibility="collapsed",
        key="sd_sector_select",
    )

    if chosen == "— Select a sector —":
        st.html("""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;
            padding:20px;text-align:center;color:#64748B;font-size:12px;">
  Select a sector above (or click a cell in the heatmap) to see stock-level detail
</div>""")
        return

    dcf_sec  = dcf_cache.get(chosen, {})
    stocks   = dcf_sec.get("stocks", [])
    snap_sec = snap.get(chosen, {})
    n_cov    = COVERAGE.get(chosen, 0)
    conf, _  = _confidence(n_cov)
    icon     = SECTOR_ICONS.get(chosen, "")
    avg_mos  = dcf_sec.get("avg_mos", 0)

    # Build a ticker → snapshot dict for P/E and EV/EBITDA lookup
    snap_stocks = {s["ticker"]: s for s in snap_sec.get("stocks", [])}

    with st.expander(
        f"{icon} {chosen}  —  {avg_mos:+.1f}% avg MoS  ·  {conf} confidence  ·  {n_cov} stocks",
        expanded=True,
    ):
        if not stocks:
            st.info("No DCF data available for this sector.")
            return

        mono = "'IBM Plex Mono',monospace"

        # Sort by MoS descending
        sorted_stocks = sorted(stocks, key=lambda x: x.get("mos", 0), reverse=True)

        # Build header
        headers = [
            ("Ticker",      "left"),
            ("Company",     "left"),
            ("Price",       "right"),
            ("IV",          "right"),
            ("MoS %",       "right"),
            ("Signal",      "center"),
            ("Fwd P/E",     "right"),
            ("EV/EBITDA",   "right"),
        ]
        hdr_html = "".join(
            f'<th style="padding:9px 14px;font-family:{mono};font-size:10px;font-weight:700;'
            f'letter-spacing:0.1em;text-transform:uppercase;color:#94A3B8;'
            f'text-align:{align};white-space:nowrap;">{h}</th>'
            for h, align in headers
        )

        rows_html = ""
        for i, s in enumerate(sorted_stocks):
            ticker  = s.get("ticker", "")
            name    = s.get("name", ticker)
            price   = s.get("price", 0)
            iv      = s.get("iv", 0)
            mos     = s.get("mos", 0)
            sig     = s.get("signal", "—")
            wacc    = s.get("wacc", 0)

            # Enrich with snapshot data
            snap_tk   = snap_stocks.get(ticker, {})
            fwd_pe    = snap_tk.get("fwd_pe", 0)
            ev_ebitda = snap_tk.get("ev_ebitda", 0)

            sig_tc, sig_bg, sig_bd = _sig_badge_css(sig)
            mos_clr = "#059669" if mos >= 15 else "#D97706" if mos >= 0 else "#DC2626"
            row_bg  = "#FFFFFF" if i % 2 == 0 else "#F8FAFC"

            fwd_pe_str    = f"{fwd_pe:.1f}×"    if fwd_pe    > 0 else "—"
            ev_ebitda_str = f"{ev_ebitda:.1f}×"  if ev_ebitda > 0 else "—"

            rows_html += f"""
<tr style="background:{row_bg};border-bottom:1px solid #F1F5F9;">
  <td style="padding:10px 14px;">
    <span style="font-family:{mono};font-size:13px;font-weight:700;color:#1D4ED8;">{ticker}</span>
  </td>
  <td style="padding:10px 14px;font-size:12px;color:#475569;max-width:160px;
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</td>
  <td style="padding:10px 14px;text-align:right;font-family:{mono};font-size:12px;color:#374151;">
    ${price:,.2f}</td>
  <td style="padding:10px 14px;text-align:right;font-family:{mono};font-size:12px;color:#374151;">
    ${iv:,.2f}</td>
  <td style="padding:10px 14px;text-align:right;">
    <span style="font-family:{mono};font-size:13px;font-weight:700;color:{mos_clr};">
      {mos:+.1f}%
    </span>
  </td>
  <td style="padding:10px 14px;text-align:center;">
    <span style="font-size:10px;font-weight:700;color:{sig_tc};
                 background:{sig_bg};border:1px solid {sig_bd};
                 border-radius:20px;padding:3px 10px;
                 font-family:{mono};white-space:nowrap;">{sig}</span>
  </td>
  <td style="padding:10px 14px;text-align:right;font-family:{mono};font-size:12px;color:#64748B;">
    {fwd_pe_str}</td>
  <td style="padding:10px 14px;text-align:right;font-family:{mono};font-size:12px;color:#64748B;">
    {ev_ebitda_str}</td>
</tr>"""

        st.html(f"""
<div style="border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;
            box-shadow:0 1px 4px rgba(15,23,42,0.05);">
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0;">{hdr_html}</tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<div style="margin-top:8px;font-size:11px;color:#94A3B8;font-family:{mono};">
  Sorted by MoS % descending &nbsp;·&nbsp; P/E and EV/EBITDA from live market data &nbsp;·&nbsp;
  IV from YieldIQ DCF model
</div>
""")

        # Analyse button for top pick
        top_pick = dcf_sec.get("top_pick", "")
        if top_pick:
            st.html('<div style="height:4px;"></div>')
            _btn_c, _ = st.columns([1, 3])
            with _btn_c:
                if st.button(f"Analyze top pick: {top_pick} →", type="primary",
                              key=f"detail_analyze_{chosen}"):
                    st.session_state["_prefill_ticker"] = top_pick
                    st.rerun()


# ══════════════════════════════════════════════════════════════
# SECTOR COMPARISON TABLE (unchanged logic, updated style)
# ══════════════════════════════════════════════════════════════

def _render_sector_table(dcf_cache: dict, snap: dict, active_filter: str | None) -> None:
    st.html(_section_title("ALL SECTORS — RANKED BY OPPORTUNITY"))

    combined = []
    for sector in SECTOR_ORDER:
        if sector not in snap: continue
        if active_filter and sector != active_filter: continue
        s = snap[sector]; n_cov = COVERAGE.get(sector, 0)
        conf, conf_clr = _confidence(n_cov)
        combined.append({
            "sector":   sector,
            "icon":     SECTOR_ICONS.get(sector, ""),
            "n_cov":    n_cov,
            "conf":     conf, "conf_clr": conf_clr,
            "chg":      s.get("avg_chg", 0),
            "fwd_pe":   s.get("avg_fwd_pe", s.get("avg_pe", 0)),
            "rev_g":    s.get("avg_rev_g", 0),
            "w52":      s.get("avg_w52", 0),
            "sentiment":s.get("sentiment", "Neutral"),
            "dcf":      dcf_cache.get(sector),
        })

    has_dcf = any(r["dcf"] for r in combined)
    combined.sort(
        key=lambda r: r["dcf"]["avg_mos"] if (has_dcf and r["dcf"]) else r["chg"],
        reverse=True,
    )

    mono = "'IBM Plex Mono',monospace"
    hdrs = [
        ("#",           "center"), ("Sector",     "left"),  ("Coverage",  "center"),
        ("Confidence",  "center"), ("Day Chg",    "right"),  ("Fwd P/E",  "right"),
        ("Rev Growth",  "right"),  ("52W Pos",    "right"),  ("Sentiment","center"),
        ("YIQ MoS",     "right"),  ("% Under",   "right"),  ("Top Pick", "center"),
    ]
    hdr_html = "".join(
        f'<th style="padding:8px 12px;font-family:{mono};font-size:10px;font-weight:700;'
        f'letter-spacing:0.10em;text-transform:uppercase;color:#94A3B8;text-align:{a};">{h}</th>'
        for h, a in hdrs
    )

    rows_html = ""
    for rank, r in enumerate(combined, 1):
        chg_clr  = _clr_chg(r["chg"])
        sent_clr = _clr_sent(r["sentiment"])
        w52      = r["w52"]
        w52_clr  = "#059669" if w52 > 70 else "#D97706" if w52 > 40 else "#DC2626"
        dcf      = r["dcf"]

        if dcf:
            mv       = dcf["avg_mos"]; mc = _clr_mos(mv)
            mos_html = (f'<span style="font-family:{mono};font-size:13px;font-weight:700;'
                        f'color:{mc};">{mv:+.1f}%</span>')
            pct_c    = "#059669" if dcf["pct_under"] >= 50 else "#DC2626"
            pct_html = f'<span style="font-family:{mono};font-size:12px;color:{pct_c};">{dcf["pct_under"]:.0f}%</span>'
            top_html = f'<span style="font-family:{mono};font-size:12px;font-weight:700;color:#1D4ED8;">{dcf["top_pick"]}</span>'
        else:
            mos_html = pct_html = top_html = '<span style="color:#94A3B8;font-size:12px;">—</span>'

        rk_html = (
            '<span style="font-size:14px;">🥇</span>' if rank == 1 else
            '<span style="font-size:14px;">🥈</span>' if rank == 2 else
            '<span style="font-size:14px;">🥉</span>' if rank == 3 else
            f'<span style="font-family:{mono};font-size:12px;color:#94A3B8;">{rank}</span>'
        )
        fwd_pe_str = f'{r["fwd_pe"]:.1f}×' if r["fwd_pe"] > 0 else "—"

        rows_html += (
            f'<tr style="border-bottom:1px solid #F1F5F9;">'
            f'<td style="padding:10px 12px;text-align:center;">{rk_html}</td>'
            f'<td style="padding:10px 12px;">'
            f'<span style="margin-right:6px;font-size:15px;">{r["icon"]}</span>'
            f'<span style="font-family:{mono};font-size:13px;font-weight:700;color:#0F172A;">{r["sector"]}</span></td>'
            f'<td style="padding:10px 12px;text-align:center;">'
            f'<span style="font-family:{mono};font-size:12px;color:#475569;">{r["n_cov"]} stocks</span></td>'
            f'<td style="padding:10px 12px;text-align:center;">{_badge(r["conf"],r["conf_clr"])}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:{mono};font-size:13px;'
            f'font-weight:600;color:{chg_clr};">{r["chg"]:+.2f}%</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:{mono};font-size:12px;color:#475569;">{fwd_pe_str}</td>'
            f'<td style="padding:10px 12px;text-align:right;font-family:{mono};font-size:12px;'
            f'color:{"#059669" if r["rev_g"]>0 else "#DC2626"};">{r["rev_g"]:+.1f}%</td>'
            f'<td style="padding:10px 12px;text-align:right;">'
            f'<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;">'
            f'<div style="width:56px;height:5px;background:#F1F5F9;border-radius:3px;overflow:hidden;">'
            f'<div style="height:100%;width:{min(w52,100):.0f}%;background:{w52_clr};border-radius:3px;"></div></div>'
            f'<span style="font-family:{mono};font-size:11px;color:#64748B;">{w52:.0f}%</span></div></td>'
            f'<td style="padding:10px 12px;text-align:center;">{_badge(r["sentiment"],sent_clr)}</td>'
            f'<td style="padding:10px 12px;text-align:right;">{mos_html}</td>'
            f'<td style="padding:10px 12px;text-align:right;">{pct_html}</td>'
            f'<td style="padding:10px 12px;text-align:center;">{top_html}</td></tr>'
        )

    st.html(f"""
<div style="border-radius:10px;border:1px solid #E2E8F0;overflow:hidden;
            box-shadow:0 1px 3px rgba(15,23,42,0.06);">
  <table style="width:100%;border-collapse:collapse;">
    <thead><tr style="background:#F8FAFC;">{hdr_html}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<div style="margin-top:8px;font-family:'IBM Plex Mono',monospace;font-size:11px;
            color:#94A3B8;line-height:1.8;">
  High ≥20 stocks · Medium ≥10 · Low &lt;10 · YIQ MoS = avg Margin of Safety · Ranked by MoS when available
</div>""")


# ══════════════════════════════════════════════════════════════
# MAIN RENDERER
# ══════════════════════════════════════════════════════════════

def render_sector_dashboard():
    """Full sector dashboard. Call inside `with tab_sector:`"""
    init_sector_db()
    dcf_cache = get_cached_dcf()

    # ── Cache freshness pill ──────────────────────────────────
    age_h = _cache_age_hours(dcf_cache)
    if age_h is None:
        freshness_html = """
<div style="padding:6px 12px;background:#FFF8ED;border:1px solid #FDE68A;
            border-radius:6px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#D97706;">
  ⏳ No DCF data yet — run Sector DCF to populate</div>"""
    elif age_h < 24:
        freshness_html = f"""
<div style="padding:6px 12px;background:#F0FDF4;border:1px solid #A7F3D0;
            border-radius:6px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#059669;">
  ✓ Data from {age_h:.1f}h ago</div>"""
    else:
        freshness_html = f"""
<div style="padding:6px 12px;background:#FFF8ED;border:1px solid #FCD34D;
            border-radius:6px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:#92400E;">
  ⚠️ Data from {age_h:.0f}h ago &nbsp;·&nbsp; <strong>Refresh recommended</strong></div>"""

    st.html(f"""
<div style="padding:4px 0 14px;display:flex;align-items:flex-start;
            justify-content:space-between;flex-wrap:wrap;gap:10px;">
  <div>
    <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:700;
                letter-spacing:0.14em;text-transform:uppercase;color:#94A3B8;margin-bottom:4px;">
      Market Intelligence · 195 US Stocks · 11 Sectors
    </div>
    <div style="font-size:20px;font-weight:700;color:#0F172A;">
      Sector Dashboard — Where Should You Look Right Now?
    </div>
    <div style="font-size:12px;color:#64748B;margin-top:4px;line-height:1.8;">
      All sectors with coverage depth and confidence level.<br>
      YieldIQ DCF by sector available on demand (~3 min).
    </div>
  </div>
  <div style="padding-top:6px;">{freshness_html}</div>
</div>""")

    c1, c2, _sp = st.columns([2, 2, 4])
    with c1:
        if st.button("↻  Refresh Snapshot", key="sd_refresh", use_container_width=True):
            fetch_sector_snapshot.clear()
            st.cache_data.clear()
            st.rerun()
    with c2:
        run_btn = st.button(
            "▶  Run Sector DCF", key="sd_dcf",
            use_container_width=True, type="primary",
        )

    if run_btn:
        bar = st.progress(0, text="Initialising…")
        with st.spinner("Running YieldIQ DCF across all sectors (~3 min)…"):
            n = run_full_dcf(lambda p, m: bar.progress(p, text=m))
        bar.empty()
        if n > 0:
            st.success(f"✓ DCF complete for {n}/11 sectors!")
        else:
            st.warning("DCF returned no results.")
        dcf_cache = get_cached_dcf()
        st.rerun()

    st.markdown("---")

    with st.spinner("Loading live market snapshot…"):
        snap = fetch_sector_snapshot()
    if not snap:
        st.error("Could not load sector data. Check internet connection.")
        return

    # ── 2. Market Breadth Bar ─────────────────────────────────
    _render_breadth_bar(dcf_cache)

    # ── 3. Top Opportunities strip ────────────────────────────
    _render_top_opportunities(dcf_cache)

    st.markdown("---")

    # ── 1. Treemap heatmap ────────────────────────────────────
    clicked_sector = _render_treemap(dcf_cache, snap)

    # Persist clicked sector in session state
    if clicked_sector:
        st.session_state["_sector_filter"] = clicked_sector

    active_filter = st.session_state.get("_sector_filter")

    _fc1, _fc2, _fc3 = st.columns([2, 2, 4])
    with _fc1:
        if st.button("✕ Clear filter", key="sd_clear_filter"):
            st.session_state.pop("_sector_filter", None)
            active_filter = None

    if active_filter:
        st.html(f"""
<div style="padding:6px 12px;background:#EFF6FF;border:1px solid #BFDBFE;
            border-radius:6px;font-family:'IBM Plex Mono',monospace;font-size:11px;
            color:#1D4ED8;margin:6px 0;">
  🔍 Active filter: <strong>{active_filter}</strong>
</div>""")

    st.markdown("---")

    # ── Lead insight cards ────────────────────────────────────
    if dcf_cache:
        ranked = sorted(
            [(s, dcf_cache[s]) for s in dcf_cache if s in snap],
            key=lambda x: x[1]["avg_mos"], reverse=True,
        )
        if ranked:
            best_s, best_d = ranked[0]
            worst_s, worst_d = ranked[-1]
            bmos = best_d["avg_mos"]; wmos = worst_d["avg_mos"]
            bi = SECTOR_ICONS.get(best_s, ""); wi = SECTOR_ICONS.get(worst_s, "")
            if bmos > 15:
                bl = "MOST ATTRACTIVE — UNDERVALUED"; bbg = "#ECFDF5"; bbd = "#A7F3D0"; bc = "#059669"
                bs = f"{best_d['pct_under']:.0f}% of stocks undervalued"
            elif bmos > 0:
                bl = "LEAST OVERVALUED RIGHT NOW"; bbg = "#FFFBEB"; bbd = "#FDE68A"; bc = "#D97706"
                bs = "Market broadly stretched"
            else:
                bl = "LEAST OVERVALUED (ALL STRETCHED)"; bbg = "#FFFBEB"; bbd = "#FDE68A"; bc = "#D97706"
                bs = f"Least overvalued at {bmos:+.1f}% MoS"
            wl = "MOST OVERVALUED — AVOID" if wmos < -25 else "LEAST ATTRACTIVE RIGHT NOW"

            st.html(
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">'
                f'<div style="background:{bbg};border:1px solid {bbd};border-radius:10px;'
                f'border-left:4px solid {bc};padding:16px 20px;">'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;font-weight:700;'
                f'color:{bc};letter-spacing:0.12em;text-transform:uppercase;margin-bottom:6px;">🟢 {bl}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:4px;">{bi} {best_s}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:24px;color:{bc};">{bmos:+.1f}% avg MoS</div>'
                f'<div style="font-size:12px;color:#475569;margin-top:4px;">{bs} · Top: <strong>{best_d["top_pick"]}</strong></div>'
                f'</div>'
                f'<div style="background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;'
                f'border-left:4px solid #DC2626;padding:16px 20px;">'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:10px;font-weight:700;'
                f'color:#DC2626;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:6px;">🔴 {wl}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#0F172A;margin-bottom:4px;">{wi} {worst_s}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:24px;color:#DC2626;">{wmos:+.1f}% avg MoS</div>'
                f'<div style="font-size:12px;color:#475569;margin-top:4px;">'
                f'{worst_d["pct_over"]:.0f}% overvalued · WACC {worst_d["avg_wacc"]*100:.1f}%</div>'
                f'</div></div>'
                f'<div style="padding:8px 14px;background:#F8FAFC;border:1px solid #E2E8F0;'
                f'border-radius:8px;font-family:IBM Plex Mono,monospace;font-size:11px;'
                f'color:#64748B;margin-bottom:4px;">'
                f'&#9432; {len(ranked)}/11 sectors have DCF · Energy/Utilities/REITs/Comms/Materials excluded · '
                f'<strong>YieldIQ models current US market as broadly overvalued.</strong></div>'
            )

    # ── All-sectors comparison table ──────────────────────────
    _render_sector_table(dcf_cache, snap, active_filter)

    st.markdown("---")

    # ── 4. Sector Detail Expander ─────────────────────────────
    _render_sector_detail(dcf_cache, snap, active_filter)
