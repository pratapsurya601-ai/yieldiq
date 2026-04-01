# dashboard/tabs/screener_tab.py
# ═══════════════════════════════════════════════════════════════════════════
# YieldIQ — Enhanced Stock Screener Tab
# Koyfin-inspired layout: left filter panel + right results grid
# ═══════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

from utils.config import RESULTS_PATH

# ── Constants ────────────────────────────────────────────────────────────────

# Map spec-style signal labels → actual CSV signal strings
_SIGNAL_MAP: dict[str, list[str]] = {
    "STRONG BUY": ["Undervalued 🟢"],      # MoS > 30 in post-filter
    "BUY":        ["Undervalued 🟢"],
    "WATCH":      ["Near Fair Value 🟡"],
    "HOLD":       ["Fairly Valued 🔵"],
    "SELL":       ["Overvalued 🔴"],
}
_ALL_CSV_SIGNALS = ["Undervalued 🟢", "Near Fair Value 🟡", "Fairly Valued 🔵", "Overvalued 🔴"]

_SIG_BADGE: dict[str, tuple[str, str]] = {
    "Undervalued 🟢":    ("#065F46", "#DCFCE7"),
    "Near Fair Value 🟡":("#92400E", "#FEF3C7"),
    "Fairly Valued 🔵":  ("#1E40AF", "#DBEAFE"),
    "Overvalued 🔴":     ("#991B1B", "#FEE2E2"),
}

_GRADE_BADGE: dict[str, tuple[str, str]] = {
    "STRONG": ("#065F46", "#DCFCE7"),
    "GOOD":   ("#1E40AF", "#DBEAFE"),
    "AVERAGE":("#92400E", "#FEF3C7"),
    "WEAK":   ("#991B1B", "#FEE2E2"),
}

_MKTCAP_BANDS = {
    "Mega (>$200B)":       (200e9, float("inf")),
    "Large ($10B–$200B)":  (10e9,  200e9),
    "Mid ($2B–$10B)":      (2e9,   10e9),
    "Small (<$2B)":        (0,     2e9),
}

_PRESET_CONFIGS: dict[str, dict] = {
    "🏆 Buffett Picks": dict(
        mos_min=20, signal_filter=["STRONG BUY", "BUY"],
        roe_min=15, op_margin_min=15, debt_eq_max=1.5,
        sort_col="margin_of_safety",
    ),
    "🚀 Growth at Value": dict(
        mos_min=10, signal_filter=["STRONG BUY", "BUY", "WATCH"],
        rev_growth_min=10, fcf_growth_min=5,
        sort_col="revenue_growth",
    ),
    "💰 Deep Value": dict(
        mos_min=30, signal_filter=["STRONG BUY", "BUY"],
        sort_col="margin_of_safety",
    ),
    "💎 Dividend Quality": dict(
        mos_min=0, signal_filter=["STRONG BUY", "BUY", "WATCH", "HOLD"],
        roe_min=10, op_margin_min=10,
        sort_col="fundamental_score",
    ),
    "⚡ High FCF": dict(
        mos_min=5, signal_filter=["STRONG BUY", "BUY", "WATCH"],
        fcf_margin_min=10, fcf_growth_min=5,
        sort_col="fcf_growth",
    ),
}

# ── Supplemental yfinance fetch ───────────────────────────────────────────────

def _fetch_one_supplemental(ticker: str) -> dict:
    """Fetch PE, PB, PS, ROE, D/E, FCF margin, mktcap for one ticker."""
    out = {
        "ticker":     ticker,
        "pe":         None,
        "pb":         None,
        "ps":         None,
        "roe":        None,
        "de_ratio":   None,
        "fcf_margin": None,
        "mktcap":     None,
    }
    try:
        info = yf.Ticker(ticker).info
        rev  = float(info.get("totalRevenue") or 0)
        fcf  = float(info.get("freeCashflow") or 0)
        de   = info.get("debtToEquity")        # Yahoo returns as %, e.g. 150 = 150%

        out["pe"]         = _safe_float(info.get("forwardPE") or info.get("trailingPE"))
        out["pb"]         = _safe_float(info.get("priceToBook"))
        out["ps"]         = _safe_float(info.get("priceToSalesTrailing12Months"))
        out["roe"]        = _safe_float(info.get("returnOnEquity"), scale=100)
        out["de_ratio"]   = _safe_float(de, scale=0.01) if de is not None else None  # → decimal
        out["mktcap"]     = _safe_float(info.get("marketCap"))
        out["fcf_margin"] = (fcf / rev * 100) if rev > 0 else None
    except Exception:
        pass
    return out


def _safe_float(v, scale: float = 1.0) -> Optional[float]:
    try:
        f = float(v)
        return f * scale if scale != 1.0 else f
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_supplemental_batch(tickers_tuple: tuple[str, ...]) -> pd.DataFrame:
    """
    Batch-fetch PE/PB/PS/ROE/D/E/FCF margin/mktcap for a set of tickers.
    Runs with 12 concurrent threads; cached for 24 h.
    """
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_one_supplemental, t): t for t in tickers_tuple}
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception:
                rows.append({"ticker": futures[fut]})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "ticker","pe","pb","ps","roe","de_ratio","fcf_margin","mktcap"
    ])


# ── Filter helpers ────────────────────────────────────────────────────────────

def _needs_supplemental(
    pe_range, pb_range, ps_range,
    roe_min, fcf_margin_min, debt_eq_max, mktcap_choice,
) -> bool:
    """Return True if any enriched filter differs from its default value."""
    return (
        pe_range        != (0.0, 100.0)  or
        pb_range        != (0.0, 20.0)   or
        ps_range        != (0.0, 30.0)   or
        roe_min         != -20           or
        fcf_margin_min  != -10           or
        debt_eq_max     != 5.0           or
        mktcap_choice   != "All"
    )


def _apply_csv_filters(
    df: pd.DataFrame,
    mos_min: float,
    signal_filter: list[str],
    sectors: list[str],
    rev_growth_min: float,
    fcf_growth_min: float,
    op_margin_min: float,
    sort_col: str,
    market: str,
) -> pd.DataFrame:
    """Apply filters that use only columns already present in the CSV."""
    out = df.copy()

    # Drop data-limited rows
    if "signal" in out.columns:
        out = out[~out["signal"].astype(str).str.contains(
            r"Data Limited|N/A|CHECK", na=False, regex=True
        )]

    # Signal filter — map spec labels to CSV signal strings
    if signal_filter:
        wanted_csv_sigs: set[str] = set()
        for label in signal_filter:
            for s in _SIGNAL_MAP.get(label, []):
                wanted_csv_sigs.add(s)
        if wanted_csv_sigs:
            out = out[out["signal"].isin(wanted_csv_sigs)]

    # MoS
    if "margin_of_safety" in out.columns:
        out = out[out["margin_of_safety"].fillna(-9999) >= mos_min]

    # STRONG BUY sub-filter: MoS ≥ 30 within Undervalued
    if signal_filter == ["STRONG BUY"] and "margin_of_safety" in out.columns:
        out = out[out["margin_of_safety"].fillna(0) >= 30]

    # Sectors
    if sectors and "sector" in out.columns:
        out = out[out["sector"].isin(sectors)]

    # Revenue growth
    if "revenue_growth" in out.columns:
        out = out[out["revenue_growth"].fillna(-9999) >= rev_growth_min]

    # FCF growth
    if "fcf_growth" in out.columns:
        out = out[out["fcf_growth"].fillna(-9999) >= fcf_growth_min]

    # Operating margin
    if "op_margin" in out.columns:
        out = out[out["op_margin"].fillna(-9999) >= op_margin_min]

    # Market (US / India)
    if market == "US Only":
        out = out[~out["ticker"].astype(str).str.endswith((".NS", ".BO"))]
    elif market == "India Only":
        out = out[out["ticker"].astype(str).str.endswith((".NS", ".BO"))]

    # Sort
    if sort_col in out.columns:
        out = out.sort_values(sort_col, ascending=False)

    return out.reset_index(drop=True)


def _apply_enriched_filters(
    df: pd.DataFrame,
    supp: pd.DataFrame,
    pe_range: tuple[float, float],
    pb_range: tuple[float, float],
    ps_range: tuple[float, float],
    roe_min: float,
    fcf_margin_min: float,
    debt_eq_max: float,
    mktcap_choice: str,
) -> pd.DataFrame:
    """Merge supplemental data and apply enriched filters."""
    if supp.empty:
        return df

    merged = df.merge(supp, on="ticker", how="left")

    def _rng(col, lo, hi):
        mask = merged[col].isna()
        return ~mask & merged[col].between(lo, hi) | mask

    # PE
    merged = merged[
        merged["pe"].isna() | merged["pe"].between(pe_range[0], pe_range[1])
    ]
    # PB
    merged = merged[
        merged["pb"].isna() | merged["pb"].between(pb_range[0], pb_range[1])
    ]
    # PS
    merged = merged[
        merged["ps"].isna() | merged["ps"].between(ps_range[0], ps_range[1])
    ]
    # ROE ≥ min
    merged = merged[
        merged["roe"].isna() | (merged["roe"] >= roe_min)
    ]
    # FCF margin ≥ min
    merged = merged[
        merged["fcf_margin"].isna() | (merged["fcf_margin"] >= fcf_margin_min)
    ]
    # D/E ≤ max (stored as decimal; spec slider in decimal)
    merged = merged[
        merged["de_ratio"].isna() | (merged["de_ratio"] <= debt_eq_max)
    ]
    # Market cap band
    if mktcap_choice != "All":
        lo, hi = _MKTCAP_BANDS[mktcap_choice]
        merged = merged[
            merged["mktcap"].isna() | merged["mktcap"].between(lo, hi)
        ]

    return merged.reset_index(drop=True)


# ── UI renderers ──────────────────────────────────────────────────────────────

def _render_filter_panel(df_raw: pd.DataFrame) -> dict:
    """
    Render all filter widgets and return the collected filter state as a dict.
    Must be called inside the left column.
    """
    # ── Preset buttons ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:10px;font-weight:700;color:#94A3B8;'
        'text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;">'
        'Quick Presets</div>',
        unsafe_allow_html=True,
    )
    preset_cols = st.columns(2)
    _preset_keys = list(_PRESET_CONFIGS.keys())
    for _i, (_pk, _pcol) in enumerate(zip(_preset_keys, preset_cols * 3)):
        if _pcol.button(_pk, key=f"preset_{_i}", use_container_width=True):
            for k, v in _PRESET_CONFIGS[_pk].items():
                st.session_state[f"scr_{k}"] = v
            st.rerun()

    st.markdown("<div style='margin:10px 0 4px;'>", unsafe_allow_html=True)

    # ── Valuation Filters ────────────────────────────────────────────────────
    with st.expander("📊 Valuation Filters", expanded=True):
        pe_range = st.slider(
            "P/E Ratio", 0.0, 100.0,
            st.session_state.get("scr_pe_range", (0.0, 100.0)),
            key="scr_pe_range",
            help="Forward or trailing P/E. Stocks with no P/E (e.g. negative earnings) pass by default.",
        )
        pb_range = st.slider(
            "P/B Ratio", 0.0, 20.0,
            st.session_state.get("scr_pb_range", (0.0, 20.0)),
            key="scr_pb_range",
        )
        ps_range = st.slider(
            "P/S Ratio", 0.0, 30.0,
            st.session_state.get("scr_ps_range", (0.0, 30.0)),
            key="scr_ps_range",
        )
        mos_min = st.slider(
            "Min Margin of Safety %", -50, 60,
            st.session_state.get("scr_mos_min", 15),
            key="scr_mos_min",
            help="Discount of current price to our model's intrinsic value estimate.",
        )

    # ── Quality Filters ──────────────────────────────────────────────────────
    with st.expander("💰 Quality Filters"):
        roe_min = st.slider(
            "Min ROE %", -20, 60,
            st.session_state.get("scr_roe_min", -20),
            key="scr_roe_min",
        )
        op_margin_min = st.slider(
            "Min Operating Margin %", -10, 50,
            st.session_state.get("scr_op_margin_min", -10),
            key="scr_op_margin_min",
        )
        fcf_margin_min = st.slider(
            "Min FCF Margin %", -10, 40,
            st.session_state.get("scr_fcf_margin_min", -10),
            key="scr_fcf_margin_min",
        )
        debt_eq_max = st.slider(
            "Max Debt/Equity", 0.0, 5.0,
            st.session_state.get("scr_debt_eq_max", 5.0),
            step=0.1,
            key="scr_debt_eq_max",
        )

    # ── Growth Filters ───────────────────────────────────────────────────────
    with st.expander("📈 Growth Filters"):
        rev_growth_min = st.slider(
            "Min Revenue Growth %", -20, 50,
            st.session_state.get("scr_rev_growth_min", -20),
            key="scr_rev_growth_min",
        )
        fcf_growth_min = st.slider(
            "Min FCF Growth %", -20, 60,
            st.session_state.get("scr_fcf_growth_min", -20),
            key="scr_fcf_growth_min",
        )

    # ── Universe ─────────────────────────────────────────────────────────────
    with st.expander("🌐 Universe"):
        # Market (only relevant for multi-region installs)
        market = st.selectbox(
            "Market",
            ["All Markets", "US Only", "India Only"],
            index=0,
            key="scr_market",
        )
        # Sectors — build list from actual data if available
        available_sectors = sorted(df_raw["sector"].dropna().unique().tolist()) if (
            df_raw is not None and "sector" in df_raw.columns
        ) else [
            "Technology", "Healthcare", "Financials", "Consumer Discretionary",
            "Consumer Staples", "Energy", "Industrials", "Materials",
            "Real Estate", "Utilities", "Communication Services",
        ]
        sectors = st.multiselect(
            "Sectors",
            available_sectors,
            default=st.session_state.get("scr_sectors", []),
            key="scr_sectors",
        )
        signal_filter = st.multiselect(
            "Signal",
            ["STRONG BUY", "BUY", "WATCH", "HOLD", "SELL"],
            default=st.session_state.get("scr_signal_filter", ["STRONG BUY", "BUY"]),
            key="scr_signal_filter",
        )
        mktcap_choice = st.selectbox(
            "Market Cap",
            ["All", "Mega (>$200B)", "Large ($10B–$200B)", "Mid ($2B–$10B)", "Small (<$2B)"],
            key="scr_mktcap",
        )

    # ── Sort ──────────────────────────────────────────────────────────────────
    with st.expander("⚙️ Sort & Limit"):
        sort_col = st.selectbox(
            "Sort by",
            [
                ("margin_of_safety", "Margin of Safety"),
                ("fundamental_score", "Quality Score"),
                ("rr_ratio",          "Risk/Reward Ratio"),
                ("revenue_growth",    "Revenue Growth"),
                ("fcf_growth",        "FCF Growth"),
                ("op_margin",         "Operating Margin"),
                ("price",             "Price"),
            ],
            format_func=lambda x: x[1],
            index=0,
            key="scr_sort",
        )[0]
        max_results = st.number_input(
            "Max rows to show", min_value=10, max_value=500, value=100, step=10,
            key="scr_max_rows",
        )

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Reset button ─────────────────────────────────────────────────────────
    if st.button("↺ Reset All Filters", use_container_width=True, key="scr_reset"):
        for k in [
            "scr_pe_range", "scr_pb_range", "scr_ps_range",
            "scr_mos_min", "scr_roe_min", "scr_op_margin_min",
            "scr_fcf_margin_min", "scr_debt_eq_max",
            "scr_rev_growth_min", "scr_fcf_growth_min",
            "scr_sectors", "scr_signal_filter", "scr_mktcap",
            "scr_market", "scr_sort", "scr_max_rows",
        ]:
            st.session_state.pop(k, None)
        st.rerun()

    run_screen = st.button(
        "🔍 Run Screener",
        type="primary",
        use_container_width=True,
        key="scr_run",
    )

    return dict(
        pe_range       = pe_range,
        pb_range       = pb_range,
        ps_range       = ps_range,
        mos_min        = mos_min,
        roe_min        = roe_min,
        op_margin_min  = op_margin_min,
        fcf_margin_min = fcf_margin_min,
        debt_eq_max    = debt_eq_max,
        rev_growth_min = rev_growth_min,
        fcf_growth_min = fcf_growth_min,
        sectors        = sectors,
        signal_filter  = signal_filter,
        mktcap_choice  = mktcap_choice,
        market         = market,
        sort_col       = sort_col,
        max_results    = int(max_results),
        run_screen     = run_screen,
    )


def _sig_badge_html(sig: str) -> str:
    fg, bg = _SIG_BADGE.get(str(sig), ("#475569", "#F1F5F9"))
    label  = str(sig).split()[0] if sig else "—"
    return (
        f'<span style="background:{bg};color:{fg};font-size:10px;font-weight:700;'
        f'padding:2px 9px;border-radius:12px;white-space:nowrap;">{label}</span>'
    )


def _grade_badge_html(grade: str) -> str:
    fg, bg = _GRADE_BADGE.get(str(grade).upper(), ("#475569", "#F1F5F9"))
    return (
        f'<span style="background:{bg};color:{fg};font-size:10px;font-weight:700;'
        f'padding:2px 8px;border-radius:6px;">{grade}</span>'
    )


def _mos_bar_html(mos: float) -> str:
    clr  = "#059669" if mos > 20 else "#D97706" if mos > 0 else "#DC2626"
    pct  = min(max(int(abs(mos)), 2), 100)
    sign = "+" if mos >= 0 else ""
    return (
        f'<div style="display:flex;align-items:center;gap:5px;">'
        f'<div style="width:44px;height:5px;background:#E2E8F0;border-radius:3px;flex-shrink:0;">'
        f'<div style="height:100%;width:{pct}%;background:{clr};border-radius:3px;"></div></div>'
        f'<span style="font-size:11px;color:{clr};font-family:IBM Plex Mono,monospace;">'
        f'{sign}{mos:.1f}%</span></div>'
    )


def _render_results_table(df: pd.DataFrame, sym: str, has_supplemental: bool) -> None:
    """Render results using st.dataframe() with column_config + styled header."""
    # ── Dataframe styling header ──────────────────────────────────────────────
    st.markdown("""
<style>
div[data-testid="stDataFrame"] th {
    background-color: #1A2540 !important;
    color: white !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    padding: 10px 12px !important;
}
div[data-testid="stDataFrame"] td {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
    padding: 8px 12px !important;
}
div[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
    background: #F8FAFC !important;
}
div[data-testid="stDataFrame"] tbody tr:hover td {
    background: #EFF6FF !important;
}
</style>
""", unsafe_allow_html=True)

    # ── Build display DataFrame ───────────────────────────────────────────────
    display_cols = {
        "ticker":            "ticker",
        "company_name":      "company",        # may not exist
        "signal":            "signal",
        "margin_of_safety":  "mos_pct",
        "intrinsic_value":   "iv",
        "price":             "price",
        "fundamental_grade": "grade",
        "fundamental_score": "quality",
        "revenue_growth":    "rev_gr",
        "op_margin":         "op_mgn",
        "sector":            "sector",
    }
    if has_supplemental:
        display_cols.update({
            "pe": "pe",
            "pb": "pb",
            "roe": "roe",
        })

    # Rename only columns that exist
    rename = {k: v for k, v in display_cols.items() if k in df.columns}
    disp = df[list(rename.keys())].rename(columns=rename).copy()

    # ── column_config ─────────────────────────────────────────────────────────
    cfg: dict = {
        "ticker":  st.column_config.TextColumn("Ticker",   width="small"),
        "signal":  st.column_config.TextColumn("Signal",   width="small"),
        "mos_pct": st.column_config.NumberColumn(
            "MoS %", format="%.1f%%", width="small",
            help="Discount of current price to model intrinsic value.",
        ),
        "iv": st.column_config.NumberColumn(
            "Intrinsic Value", format=f"{sym}%.2f", width="small",
        ),
        "price": st.column_config.NumberColumn(
            "Price", format=f"{sym}%.2f", width="small",
        ),
        "grade":   st.column_config.TextColumn("Grade",    width="small"),
        "quality": st.column_config.NumberColumn(
            "Quality", format="%d", width="small",
            help="Fundamental quality score (0–100)",
        ),
        "rev_gr":  st.column_config.NumberColumn(
            "Rev Gr %", format="%.1f%%", width="small",
        ),
        "op_mgn":  st.column_config.NumberColumn(
            "Op Margin", format="%.1f%%", width="small",
        ),
        "sector":  st.column_config.TextColumn("Sector",   width="medium"),
    }
    if "company" in disp.columns:
        cfg["company"] = st.column_config.TextColumn("Company", width="medium")
    if has_supplemental:
        cfg["pe"]  = st.column_config.NumberColumn("P/E",  format="%.1fx", width="small")
        cfg["pb"]  = st.column_config.NumberColumn("P/B",  format="%.2fx", width="small")
        cfg["roe"] = st.column_config.NumberColumn("ROE %", format="%.1f%%", width="small")

    # Clean up: percentage columns already stored as % (not decimal)
    for col in ("mos_pct", "rev_gr", "op_mgn"):
        if col in disp.columns:
            disp[col] = pd.to_numeric(disp[col], errors="coerce")

    st.dataframe(
        disp,
        column_config=cfg,
        hide_index=True,
        use_container_width=True,
        height=500,
    )


def _render_summary_kpis(df_raw: pd.DataFrame, df_filtered: pd.DataFrame, total: int) -> None:
    """Render the 5 summary metric chips above the results table."""
    n_found   = len(df_filtered)
    n_buy     = int((df_filtered["signal"] == "Undervalued 🟢").sum()) if "signal" in df_filtered.columns else 0
    n_watch   = int((df_filtered["signal"] == "Near Fair Value 🟡").sum()) if "signal" in df_filtered.columns else 0
    avg_mos   = float(df_filtered["margin_of_safety"].mean()) if "margin_of_safety" in df_filtered.columns else 0
    top_ticker = (
        df_filtered.loc[df_filtered["margin_of_safety"].idxmax(), "ticker"]
        if n_found > 0 and "margin_of_safety" in df_filtered.columns else "—"
    )
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Stocks Found",     n_found,   delta=f"of {total} screened", delta_color="off")
    k2.metric("Buy Signal",       n_buy)
    k3.metric("Watch",            n_watch)
    k4.metric("Avg Discount",     f"{avg_mos:.1f}%")
    k5.metric("Top Pick",         top_ticker)


def _render_empty_state(msg: str) -> None:
    st.html(f"""
<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
            padding:48px 32px;text-align:center;margin:16px 0;">
  <div style="font-size:36px;margin-bottom:14px;">🔍</div>
  <div style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:8px;">
    {msg}
  </div>
  <div style="font-size:13px;color:#64748B;max-width:400px;margin:0 auto;line-height:1.6;">
    Adjust the filters on the left and click
    <strong>Run Screener</strong> to find matching stocks.
  </div>
</div>""")


# ── Active filters pill display ───────────────────────────────────────────────

def _render_active_filters(filters: dict) -> None:
    """Show a compact row of active-filter chips above the results."""
    chips: list[str] = []
    if filters["mos_min"] > -50:
        chips.append(f"MoS ≥ {filters['mos_min']}%")
    if filters["signal_filter"]:
        chips.append("Signal: " + ", ".join(filters["signal_filter"]))
    if filters["sectors"]:
        chips.append("Sectors: " + ", ".join(filters["sectors"][:2]) +
                     (f" +{len(filters['sectors'])-2}" if len(filters["sectors"]) > 2 else ""))
    if filters["rev_growth_min"] > -20:
        chips.append(f"RevGr ≥ {filters['rev_growth_min']}%")
    if filters["op_margin_min"] > -10:
        chips.append(f"OpMgn ≥ {filters['op_margin_min']}%")
    if filters["roe_min"] > -20:
        chips.append(f"ROE ≥ {filters['roe_min']}%")
    if filters["pe_range"] != (0.0, 100.0):
        chips.append(f"P/E {filters['pe_range'][0]:.0f}–{filters['pe_range'][1]:.0f}×")
    if filters["mktcap_choice"] != "All":
        chips.append(filters["mktcap_choice"])

    if not chips:
        return

    chips_html = "".join(
        f'<span style="background:#EFF6FF;color:#1D4ED8;border:1px solid #BFDBFE;'
        f'font-size:11px;font-weight:600;padding:3px 10px;border-radius:16px;'
        f'font-family:Inter,sans-serif;white-space:nowrap;">{c}</span>'
        for c in chips
    )
    st.html(f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px;">{chips_html}</div>')


# ── Last batch run banner ─────────────────────────────────────────────────────

def _render_batch_banner() -> None:
    try:
        import json as _json
        p = Path("data/last_batch_run.json")
        if not p.exists():
            return
        d    = _json.loads(p.read_text())
        ts   = d.get("timestamp", "")[:16].replace("T", " ")
        comp = d.get("completed", "—")
        dur  = d.get("duration_min", "—")
        top  = d.get("top_pick", "—")
        st.html(f"""
<div style="display:flex;align-items:center;gap:20px;padding:9px 16px;
            background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;
            margin-bottom:12px;font-size:12px;color:#0369A1;flex-wrap:wrap;">
  <span>🕒 Updated: <strong>{ts}</strong></span>
  <span>📊 Screened: <strong>{comp:,}</strong> stocks</span>
  <span>⏱ Runtime: <strong>{dur} min</strong></span>
  <span>🏆 Top pick today: <strong>{top}</strong></span>
</div>""")
    except Exception:
        pass


# ── Main entry point ──────────────────────────────────────────────────────────

def render_screener_tab(
    df_raw: Optional[pd.DataFrame],
    sym: str = "$",
) -> None:
    """
    Render the full enhanced screener tab.

    Parameters
    ----------
    df_raw : pre-loaded screener results DataFrame (from RESULTS_PATH CSV).
             Pass None to show the empty-state prompt.
    sym    : currency symbol for price formatting.
    """
    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(
        '<h2 style="font-size:22px;font-weight:700;color:#0F172A;'
        'font-family:Inter,sans-serif;margin-bottom:2px;">Stock Screener</h2>'
        '<p style="font-size:13px;color:#64748B;margin-bottom:16px;">'
        'Filter 2,800+ stocks by valuation, quality, growth, and sector</p>',
        unsafe_allow_html=True,
    )

    # ── No data state ─────────────────────────────────────────────────────────
    if df_raw is None or df_raw.empty:
        st.html("""
<div style="background:linear-gradient(135deg,#0d1117,#161b22);
            border:1px solid #21262d;border-radius:16px;
            padding:48px;text-align:center;margin:20px 0;">
  <div style="font-size:44px;margin-bottom:16px;">📊</div>
  <div style="font-size:20px;font-weight:700;color:#e6edf3;margin-bottom:10px;">
    No screener results yet</div>
  <div style="font-size:13px;color:#8b949e;max-width:440px;margin:0 auto 24px;line-height:1.7;">
    Run the nightly batch to generate results for 2,800+ stocks.
  </div>
  <code style="background:#0d1117;border:1px solid #21262d;border-radius:6px;
               padding:8px 18px;color:#00b4d8;font-size:12px;
               font-family:IBM Plex Mono,monospace;">
    python batch/nightly_precompute.py
  </code>
</div>""")
        return

    _render_batch_banner()

    total_stocks = len(df_raw)

    # ── Two-column layout ─────────────────────────────────────────────────────
    _col_filters, _col_results = st.columns([1, 3], gap="large")

    # ── LEFT — Filter panel ───────────────────────────────────────────────────
    with _col_filters:
        st.markdown(
            '<div style="font-size:11px;font-weight:700;color:#94A3B8;'
            'text-transform:uppercase;letter-spacing:0.12em;margin-bottom:10px;">'
            'Filter Criteria</div>',
            unsafe_allow_html=True,
        )
        filters = _render_filter_panel(df_raw)

    # ── RIGHT — Results panel ─────────────────────────────────────────────────
    with _col_results:

        # Initial state — show prompt
        if not filters["run_screen"] and "scr_last_result_len" not in st.session_state:
            _render_active_filters(filters)
            st.html("""
<div style="background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:12px;
            padding:48px;text-align:center;margin:8px 0;">
  <div style="font-size:32px;margin-bottom:12px;">🔍</div>
  <div style="font-size:15px;font-weight:600;color:#0F172A;margin-bottom:6px;">
    Set your filters and click Run Screener</div>
  <div style="font-size:13px;color:#64748B;">
    Results will appear here · Enriched filters (P/E, P/B, ROE, D/E) fetch
    live data from Yahoo Finance for the filtered set.
  </div>
</div>""")
            return

        # ── Apply CSV-native filters ──────────────────────────────────────────
        df_base = _apply_csv_filters(
            df_raw,
            mos_min        = filters["mos_min"],
            signal_filter  = filters["signal_filter"],
            sectors        = filters["sectors"],
            rev_growth_min = filters["rev_growth_min"],
            fcf_growth_min = filters["fcf_growth_min"],
            op_margin_min  = filters["op_margin_min"],
            sort_col       = filters["sort_col"],
            market         = filters["market"],
        )

        # ── Enriched filters — fetch supplemental if needed ───────────────────
        need_supp = _needs_supplemental(
            filters["pe_range"],   filters["pb_range"],  filters["ps_range"],
            filters["roe_min"],    filters["fcf_margin_min"],
            filters["debt_eq_max"], filters["mktcap_choice"],
        )

        df_final       = df_base
        has_supp       = False
        supp_df        = pd.DataFrame()

        if need_supp and not df_base.empty:
            n_to_fetch = len(df_base)
            with st.spinner(
                f"Fetching enriched data (P/E, P/B, ROE, D/E) for "
                f"{n_to_fetch} stocks from Yahoo Finance…"
            ):
                tickers_tuple = tuple(df_base["ticker"].tolist())
                supp_df       = _fetch_supplemental_batch(tickers_tuple)
                has_supp      = not supp_df.empty

            if has_supp:
                df_final = _apply_enriched_filters(
                    df_base, supp_df,
                    pe_range       = filters["pe_range"],
                    pb_range       = filters["pb_range"],
                    ps_range       = filters["ps_range"],
                    roe_min        = filters["roe_min"],
                    fcf_margin_min = filters["fcf_margin_min"],
                    debt_eq_max    = filters["debt_eq_max"],
                    mktcap_choice  = filters["mktcap_choice"],
                )

        st.session_state["scr_last_result_len"] = len(df_final)

        # ── KPI strip ────────────────────────────────────────────────────────
        _render_summary_kpis(df_raw, df_final, total_stocks)
        st.caption(
            "⚠️ Model outputs only — not investment advice. "
            "YieldIQ is not a registered investment adviser."
        )

        # ── Active filter chips ───────────────────────────────────────────────
        _render_active_filters(filters)

        # ── Results table ─────────────────────────────────────────────────────
        if df_final.empty:
            _render_empty_state("No stocks match these filters")
        else:
            # Merge supplemental columns into df_final for display
            if has_supp and not supp_df.empty:
                extra_cols = ["ticker"] + [
                    c for c in ["pe", "pb", "ps", "roe", "de_ratio", "fcf_margin", "mktcap"]
                    if c in supp_df.columns
                ]
                supp_for_display = supp_df[extra_cols]
                df_display = df_final.merge(supp_for_display, on="ticker", how="left")
            else:
                df_display = df_final.copy()

            _render_results_table(
                df_display.head(filters["max_results"]),
                sym,
                has_supplemental=has_supp,
            )

            # ── Quick-analyze chip ─────────────────────────────────────────
            if "ticker" in df_final.columns and len(df_final) > 0:
                st.markdown(
                    '<div style="font-size:11px;color:#64748B;margin:10px 0 6px;">'
                    'Click any ticker to run a full analysis:</div>',
                    unsafe_allow_html=True,
                )
                _chip_cols = st.columns(min(len(df_final.head(8)), 8))
                for _ci, (_cj, _row) in enumerate(
                    zip(_chip_cols, df_final.head(8).itertuples())
                ):
                    with _cj:
                        if st.button(
                            _row.ticker,
                            key=f"scr_analyze_{_ci}_{_row.ticker}",
                            use_container_width=True,
                        ):
                            st.session_state["_prefill_ticker"] = _row.ticker
                            st.session_state["main_tab"]        = "stock"
                            st.rerun()

            # ── Download ───────────────────────────────────────────────────
            _csv_bytes = df_final.to_csv(index=False).encode()
            st.download_button(
                f"⬇️ Download results ({len(df_final)} stocks) as CSV",
                data       = _csv_bytes,
                file_name  = f"yieldiq_screen_{datetime.date.today()}.csv",
                mime       = "text/csv",
                key        = "scr_download",
            )
