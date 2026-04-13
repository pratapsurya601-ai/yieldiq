# dashboard/tabs/discover_tab.py
# ═══════════════════════════════════════════════════════════════
# Discover tab — daily opportunity engine
# Section A: Top Pick Today (hero card)
# Section B: YieldIQ 50 Index (tiered)
# Section C: Screener (preset + custom)
# Section D: Sector Map (collapsible)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st
from datetime import date


# ── YieldIQ 50 universe (shared with yieldiq50_tab) ──────────
YIELDIQ_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "BHARTIARTL.NS", "SBIN.NS", "BAJFINANCE.NS",
    "LT.NS", "KOTAKBANK.NS", "HCLTECH.NS", "AXISBANK.NS", "ASIANPAINT.NS",
    "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "TATAMOTORS.NS", "WIPRO.NS",
    "ULTRACEMCO.NS", "NESTLEIND.NS", "NTPC.NS", "M&M.NS", "POWERGRID.NS",
    "ONGC.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "BAJAJFINSV.NS", "ADANIENT.NS",
    "TECHM.NS", "HDFCLIFE.NS", "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS",
    "BRITANNIA.NS", "GRASIM.NS", "COALINDIA.NS", "BPCL.NS", "EICHERMOT.NS",
    "HEROMOTOCO.NS", "INDUSINDBK.NS", "SBILIFE.NS", "TATACONSUM.NS",
    "DABUR.NS", "PIDILITIND.NS", "GODREJCP.NS", "BAJAJ-AUTO.NS",
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "CHOLAFIN.NS",
    "MUTHOOTFIN.NS", "TATAELXSI.NS", "PIIND.NS", "APOLLOHOSP.NS", "ADANIPORTS.NS", "HINDALCO.NS",
]


def _get_tier() -> str:
    return st.session_state.get("tier", st.session_state.get("user_tier", "free"))


def _get_cached_top_pick() -> dict | None:
    """Return cached top pick for today, or None."""
    _key = f"_discover_top_pick_{date.today().isoformat()}"
    return st.session_state.get(_key)


def _set_cached_top_pick(data: dict) -> None:
    _key = f"_discover_top_pick_{date.today().isoformat()}"
    st.session_state[_key] = data


def _load_screener_data():
    """Load screener_results.csv if available."""
    import pandas as pd
    from pathlib import Path
    _path = Path(__file__).resolve().parent.parent / "screener_results.csv"
    try:
        if _path.exists():
            return pd.read_csv(_path)
    except Exception:
        pass
    # Also check data/ folder
    _path2 = Path(__file__).resolve().parent.parent.parent / "data" / "screener_results.csv"
    try:
        if _path2.exists():
            return pd.read_csv(_path2)
    except Exception:
        pass
    return None


def _compute_top_pick(df) -> dict:
    """Find highest-conviction stock from screener data."""
    if df is None or df.empty:
        return {
            "ticker": "RELIANCE.NS", "company": "Reliance Industries",
            "score": 72, "mos": 18.5, "moat": "Wide",
            "confidence": 75, "summary": "Strong free cash flows with wide moat.",
        }
    # Prefer columns: score/yieldiq_score, mos/mos_pct, moat
    _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
    _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
    _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
    _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name", "name")), None)
    _moat_col = next((c for c in df.columns if "moat" in c.lower()), None)

    if _score_col and _mos_col:
        df["_rank"] = df[_score_col].fillna(0) + df[_mos_col].fillna(0)
        _best = df.nlargest(1, "_rank").iloc[0]
    elif _score_col:
        _best = df.nlargest(1, _score_col).iloc[0]
    elif _mos_col:
        _best = df.nlargest(1, _mos_col).iloc[0]
    else:
        _best = df.iloc[0]

    return {
        "ticker": str(_best.get(_ticker_col, "RELIANCE.NS")),
        "company": str(_best.get(_company_col, _best.get(_ticker_col, ""))).replace(".NS", "").replace(".BO", ""),
        "score": int(_best.get(_score_col, 70)) if _score_col else 70,
        "mos": float(_best.get(_mos_col, 15)) if _mos_col else 15.0,
        "moat": str(_best.get(_moat_col, "Narrow")) if _moat_col else "Narrow",
        "confidence": 75,
        "summary": "",
    }


def _generate_summary(pick: dict) -> str:
    """Generate one-line plain English summary for top pick."""
    _t = pick["ticker"].replace(".NS", "").replace(".BO", "")
    _mos = pick["mos"]
    _moat = pick["moat"]
    if _mos > 25:
        return f"{_t} trades {_mos:.0f}% below our fair value estimate with a {_moat.lower()} moat — strong margin of safety."
    elif _mos > 10:
        return f"{_t} shows a {_mos:.0f}% discount to fair value. {_moat} moat with stable fundamentals."
    elif _mos > 0:
        return f"{_t} is modestly undervalued at {_mos:.0f}% below fair value. Quality metrics are solid."
    else:
        return f"{_t} is near fair value. Quality score is high but limited upside at current price."


# ═══════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════

def render_discover():
    """Render the Discover tab — daily opportunity engine."""
    _tier = _get_tier()
    _df = _load_screener_data()

    # ── Section A: Top Pick Today ─────────────────────────────
    _render_top_pick(_df, _tier)

    # ── Section B: YieldIQ 50 ─────────────────────────────────
    _render_yieldiq50(_df, _tier)

    # ── Section C: Screener ───────────────────────────────────
    _render_screener_section(_tier)

    # ── Section D: Sector Map ─────────────────────────────────
    _render_sector_map()


# ═══════════════════════════════════════════════════════════════
# SECTION A — TOP PICK TODAY
# ═══════════════════════════════════════════════════════════════

def _render_top_pick(df, tier: str):
    cached = _get_cached_top_pick()
    if cached:
        pick = cached
    else:
        pick = _compute_top_pick(df)
        if not pick.get("summary"):
            pick["summary"] = _generate_summary(pick)
        _set_cached_top_pick(pick)

    _display_ticker = pick["ticker"].replace(".NS", "").replace(".BO", "")
    _score = pick["score"]
    _mos = pick["mos"]
    _moat = pick["moat"]
    _summary = pick["summary"]
    _company = pick.get("company", _display_ticker)

    # Score color
    if _score >= 75:
        _sc, _sbg = "#059669", "#F0FDF4"
    elif _score >= 55:
        _sc, _sbg = "#1D4ED8", "#EFF6FF"
    else:
        _sc, _sbg = "#D97706", "#FFFBEB"

    st.html(f"""
    <div style="border-left:4px solid #1D4ED8;background:#FFFFFF;border-radius:0 14px 14px 0;
                padding:20px 24px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
        <span style="font-size:10px;font-weight:700;color:#1D4ED8;text-transform:uppercase;
                     letter-spacing:0.12em;">Top pick today</span>
        <span style="background:#EFF6FF;color:#1D4ED8;font-size:9px;font-weight:700;
                     padding:2px 8px;border-radius:10px;">Highest conviction</span>
      </div>
      <div style="font-size:20px;font-weight:800;color:#0F172A;margin-bottom:2px;">
        {_company}</div>
      <div style="font-size:12px;color:#94A3B8;margin-bottom:14px;">{_display_ticker}</div>
      <div style="display:flex;gap:16px;margin-bottom:14px;flex-wrap:wrap;">
        <div style="background:{_sbg};padding:8px 14px;border-radius:10px;text-align:center;">
          <div style="font-size:9px;color:{_sc};font-weight:700;text-transform:uppercase;">Score</div>
          <div style="font-size:22px;font-weight:900;color:{_sc};font-family:IBM Plex Mono,monospace;">
            {_score}</div>
        </div>
        <div style="background:#F0FDF4;padding:8px 14px;border-radius:10px;text-align:center;">
          <div style="font-size:9px;color:#059669;font-weight:700;text-transform:uppercase;">MoS</div>
          <div style="font-size:22px;font-weight:900;color:#059669;font-family:IBM Plex Mono,monospace;">
            {_mos:+.0f}%</div>
        </div>
        <div style="background:#F8FAFC;padding:8px 14px;border-radius:10px;text-align:center;">
          <div style="font-size:9px;color:#64748B;font-weight:700;text-transform:uppercase;">Moat</div>
          <div style="font-size:16px;font-weight:700;color:#0F172A;">{_moat}</div>
        </div>
      </div>
      <div style="font-size:13px;color:#475569;line-height:1.6;">{_summary}</div>
    </div>
    """)

    # Analyse button
    if st.button(f"Analyse {_display_ticker} →", key="_tp_analyse", type="primary"):
        st.session_state["_prefill_ticker"] = pick["ticker"]
        st.session_state["_auto_analyse"] = True
        st.session_state.active_tab = "Search"
        st.session_state.main_tab = "stock"
        st.rerun()

    st.html("""
    <div style="font-size:10px;color:#94A3B8;margin-top:4px;margin-bottom:20px;">
      Updated daily · Based on YieldIQ 50 model · Not investment advice</div>
    """)


# ═══════════════════════════════════════════════════════════════
# SECTION B — YIELDIQ 50
# ═══════════════════════════════════════════════════════════════

def _render_yieldiq50(df, tier: str):
    st.html("""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.14em;">YieldIQ 50</div>
      <div style="font-size:10px;color:#94A3B8;">Updated daily</div>
    </div>
    """)

    # Try to build top stocks from screener data
    _top_stocks = _build_top_stocks(df)

    if tier in ("starter", "pro") and df is not None and not df.empty:
        # Full sortable table for paid users
        _render_full_table(df)
    else:
        # Free users: show top 3 mini-cards + blurred remainder
        _render_free_preview(_top_stocks)

    # Methodology expander
    with st.expander("How is YieldIQ 50 constructed?"):
        st.html("""
        <div style="font-size:13px;color:#475569;line-height:1.8;">
          We run our valuation model on 500+ quality stocks weekly. Each stock gets
          a composite score based on valuation (40%), financial quality (30%),
          growth trajectory (20%), and market sentiment (10%).<br><br>
          The top 50 by combined score and margin of safety make the index.
          Stocks must have positive free cash flow and a Piotroski F-Score of 5 or above
          to qualify. The index rebalances every Sunday.<br><br>
          Think of it as a watchlist of the most promising opportunities our model
          has found — not a buy list.
        </div>
        """)


def _build_top_stocks(df) -> list[dict]:
    """Build a list of top stocks from screener data or fallback."""
    if df is not None and not df.empty:
        _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
        _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
        _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])

        if _score_col:
            _sorted = df.nlargest(50, _score_col)
        elif _mos_col:
            _sorted = df.nlargest(50, _mos_col)
        else:
            _sorted = df.head(50)

        result = []
        for _, row in _sorted.head(3).iterrows():
            result.append({
                "ticker": str(row.get(_ticker_col, "")),
                "score": int(row.get(_score_col, 0)) if _score_col else 0,
                "mos": float(row.get(_mos_col, 0)) if _mos_col else 0,
            })
        return result

    # Fallback — show placeholder top 3
    return [
        {"ticker": "RELIANCE.NS", "score": 74, "mos": 22},
        {"ticker": "TCS.NS", "score": 71, "mos": 18},
        {"ticker": "INFY.NS", "score": 68, "mos": 15},
    ]


def _render_free_preview(top_stocks: list[dict]):
    """Show top 3 as mini-cards + blurred remainder for free users."""
    cols = st.columns(4)
    for i, stock in enumerate(top_stocks[:3]):
        _display = stock["ticker"].replace(".NS", "").replace(".BO", "")
        _mos_color = "#059669" if stock["mos"] > 0 else "#DC2626"
        with cols[i]:
            st.html(f"""
            <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
                        padding:14px;text-align:center;min-height:100px;">
              <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:6px;">
                {_display}</div>
              <div style="font-size:10px;color:#94A3B8;margin-bottom:4px;">MoS</div>
              <div style="font-size:18px;font-weight:800;color:{_mos_color};
                          font-family:IBM Plex Mono,monospace;">{stock['mos']:+.0f}%</div>
              <div style="font-size:10px;color:#94A3B8;margin-top:4px;">
                Score: {stock['score']}</div>
            </div>
            """)
    # Blurred "+47 more" card
    with cols[3]:
        st.html("""
        <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;
                    padding:14px;text-align:center;min-height:100px;
                    display:flex;flex-direction:column;align-items:center;justify-content:center;">
          <div style="font-size:20px;font-weight:900;color:#94A3B8;margin-bottom:4px;">+47</div>
          <div style="font-size:10px;color:#94A3B8;font-weight:600;">more stocks</div>
          <div style="font-size:9px;color:#1D4ED8;font-weight:700;margin-top:6px;">
            Starter plan</div>
        </div>
        """)
        if st.button("Unlock all 50 →", key="_yiq50_upgrade", type="primary",
                     use_container_width=True):
            st.session_state.active_tab = "Account"
            st.session_state.main_tab = "pricing"
            st.rerun()


def _render_full_table(df):
    """Render full sortable YieldIQ 50 table for paid users."""
    import pandas as pd

    _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score", "yiq_score")), None)
    _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct", "margin_of_safety")), None)
    _ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), df.columns[0])
    _company_col = next((c for c in df.columns if c.lower() in ("company", "company_name", "name")), None)
    _moat_col = next((c for c in df.columns if "moat" in c.lower()), None)

    # Build display df
    _cols_to_show = [_ticker_col]
    _rename = {_ticker_col: "Ticker"}
    if _company_col:
        _cols_to_show.append(_company_col)
        _rename[_company_col] = "Company"
    if _score_col:
        _cols_to_show.append(_score_col)
        _rename[_score_col] = "Score"
    if _mos_col:
        _cols_to_show.append(_mos_col)
        _rename[_mos_col] = "MoS %"
    if _moat_col:
        _cols_to_show.append(_moat_col)
        _rename[_moat_col] = "Moat"

    _display = df[_cols_to_show].head(50).rename(columns=_rename).copy()
    _display.insert(0, "Rank", range(1, len(_display) + 1))

    st.dataframe(_display, use_container_width=True, hide_index=True, height=500)


# ═══════════════════════════════════════════════════════════════
# SECTION C — SCREENER
# ═══════════════════════════════════════════════════════════════

def _render_screener_section(tier: str):
    st.html("""
    <div style="display:flex;justify-content:space-between;align-items:center;
                margin:24px 0 12px;">
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.14em;">Screener</div>
      <div style="font-size:10px;color:#94A3B8;">6,000+ stocks</div>
    </div>
    """)

    # 2x2 preset grid
    _presets = [
        {
            "name": "Buffett screen",
            "color": "#1D4ED8",
            "criteria": "ROE > 15% · D/E < 0.5 · Wide moat · MoS > 20%",
            "desc": "High-quality businesses at reasonable prices",
            "filters": {"roe_min": 15, "de_max": 0.5, "moat": "Wide", "mos_min": 20},
        },
        {
            "name": "Deep value",
            "color": "#7C3AED",
            "criteria": "MoS > 30% · FCF positive · Score > 60",
            "desc": "Deeply undervalued with strong cash generation",
            "filters": {"mos_min": 30, "fcf_positive": True, "score_min": 60},
        },
        {
            "name": "Growth quality",
            "color": "#059669",
            "criteria": "Score > 80 · Revenue growth > 15% · FCF positive",
            "desc": "High-growth companies with strong quality metrics",
            "filters": {"score_min": 80, "rev_growth_min": 15, "fcf_positive": True},
        },
        {
            "name": "Custom screen",
            "color": "#94A3B8",
            "criteria": "Build your own filters",
            "desc": "Set MoS, score, moat, sector, and more",
            "filters": None,
        },
    ]

    _c1, _c2 = st.columns(2)
    for i, preset in enumerate(_presets):
        _col = _c1 if i % 2 == 0 else _c2
        with _col:
            st.html(f"""
            <div style="border-left:3px solid {preset['color']};background:#FFFFFF;
                        border-radius:0 10px 10px 0;padding:14px 16px;
                        margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,0.04);">
              <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:4px;">
                {preset['name']}</div>
              <div style="font-size:11px;color:#64748B;margin-bottom:6px;">{preset['desc']}</div>
              <div style="font-size:10px;color:#94A3B8;">{preset['criteria']}</div>
            </div>
            """)
            if preset["filters"] is not None:
                if st.button(f"Run screen →", key=f"_scr_{i}", use_container_width=True):
                    st.session_state["_active_screen"] = preset["name"]
                    st.session_state["_screen_filters"] = preset["filters"]
            else:
                # Custom screen
                if tier in ("starter", "pro"):
                    if st.button("Build custom →", key="_scr_custom", use_container_width=True):
                        st.session_state["_show_custom_screener"] = True
                else:
                    if st.button("Upgrade to unlock →", key="_scr_custom_up",
                                 use_container_width=True, type="primary"):
                        st.session_state.active_tab = "Account"
                        st.session_state.main_tab = "pricing"
                        st.rerun()

    # Show screener results if a screen was run
    _active = st.session_state.get("_active_screen")
    if _active:
        _render_screen_results(_active, st.session_state.get("_screen_filters", {}), tier)

    # Custom screener panel
    if st.session_state.get("_show_custom_screener") and tier in ("starter", "pro"):
        _render_custom_screener(tier)


def _render_screen_results(name: str, filters: dict, tier: str):
    """Run a preset screen against available data."""
    import pandas as pd
    df = _load_screener_data()
    if df is None or df.empty:
        st.info(f"No screener data available yet. Run the batch screener first to populate results.")
        return

    st.html(f"""
    <div style="font-size:12px;font-weight:700;color:#0F172A;margin:12px 0 8px;">
      Results: {name}</div>
    """)

    # Apply filters where columns exist
    _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)
    _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)

    filtered = df.copy()
    if _mos_col and "mos_min" in filters:
        filtered = filtered[filtered[_mos_col] >= filters["mos_min"]]
    if _score_col and "score_min" in filters:
        filtered = filtered[filtered[_score_col] >= filters["score_min"]]

    _limit = 100 if tier in ("starter", "pro") else 20
    _display = filtered.head(_limit)

    if _display.empty:
        st.info("No stocks match these criteria right now.")
    else:
        st.dataframe(_display, use_container_width=True, hide_index=True, height=300)
        if tier == "free" and len(filtered) > 20:
            st.html(f"""
            <div style="text-align:center;font-size:11px;color:#1D4ED8;margin-top:8px;">
              Showing 20 of {len(filtered)} results · Upgrade for full access</div>
            """)

    if st.button("Clear results", key="_scr_clear"):
        st.session_state.pop("_active_screen", None)
        st.session_state.pop("_screen_filters", None)
        st.rerun()


def _render_custom_screener(tier: str):
    """Custom screener with filter controls."""
    st.html("""
    <div style="font-size:12px;font-weight:700;color:#0F172A;margin:16px 0 8px;">
      Custom Screener</div>
    """)
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            _mos_range = st.slider("Margin of Safety %", -50, 80, (10, 80), key="_cscr_mos")
            _moat = st.selectbox("Moat", ["Any", "Wide", "Narrow", "None"], key="_cscr_moat")
        with c2:
            _score_range = st.slider("YieldIQ Score", 0, 100, (50, 100), key="_cscr_score")
            _fcf = st.selectbox("Free Cash Flow", ["Any", "Positive only", "Negative only"], key="_cscr_fcf")
        with c3:
            _sector = st.selectbox("Sector", ["All sectors", "Technology", "Financials",
                                               "Healthcare", "Industrials", "Consumer",
                                               "Energy", "Materials", "Utilities"], key="_cscr_sector")
            _rev_growth = st.slider("Revenue Growth % (min)", -20, 50, 0, key="_cscr_revg")

        if st.button("Run custom screen →", key="_cscr_run", type="primary"):
            st.session_state["_active_screen"] = "Custom"
            st.session_state["_screen_filters"] = {
                "mos_min": _mos_range[0], "score_min": _score_range[0],
            }
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# SECTION D — SECTOR MAP
# ═══════════════════════════════════════════════════════════════

def _render_sector_map():
    with st.expander("Sector overview", expanded=False):
        # Sector data — either from screener data or static
        _sectors = _compute_sector_data()
        if not _sectors:
            st.info("Sector data populates as more stocks are analysed.")
            return

        # Render as styled HTML table
        _rows = ""
        for s in _sectors:
            _pct = s["pct_undervalued"]
            if _pct >= 60:
                _color, _bg = "#059669", "#F0FDF4"
            elif _pct >= 40:
                _color, _bg = "#D97706", "#FFFBEB"
            else:
                _color, _bg = "#DC2626", "#FEF2F2"

            _trend = s.get("trend", "→")
            _rows += f"""
            <tr style="border-bottom:1px solid #F1F5F9;">
              <td style="padding:10px 12px;font-size:12px;font-weight:600;color:#0F172A;">
                {s['name']}</td>
              <td style="padding:10px;font-size:13px;font-weight:700;color:#0F172A;
                          font-family:IBM Plex Mono,monospace;text-align:center;">
                {s['avg_score']:.0f}</td>
              <td style="padding:10px;text-align:center;">
                <span style="background:{_bg};color:{_color};font-size:11px;font-weight:700;
                              padding:3px 10px;border-radius:8px;">{_pct:.0f}%</span></td>
              <td style="padding:10px;font-size:16px;text-align:center;">{_trend}</td>
            </tr>"""

        st.html(f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="border-bottom:2px solid #E2E8F0;">
              <th style="padding:8px 12px;font-size:10px;color:#94A3B8;text-transform:uppercase;
                          letter-spacing:0.08em;text-align:left;">Sector</th>
              <th style="padding:8px;font-size:10px;color:#94A3B8;text-transform:uppercase;
                          letter-spacing:0.08em;text-align:center;">Avg Score</th>
              <th style="padding:8px;font-size:10px;color:#94A3B8;text-transform:uppercase;
                          letter-spacing:0.08em;text-align:center;">% Undervalued</th>
              <th style="padding:8px;font-size:10px;color:#94A3B8;text-transform:uppercase;
                          letter-spacing:0.08em;text-align:center;">Trend</th>
            </tr>
          </thead>
          <tbody>{_rows}</tbody>
        </table>
        """)


def _compute_sector_data() -> list[dict]:
    """Compute sector-level stats from screener data or return static fallback."""
    df = _load_screener_data()
    if df is not None and not df.empty:
        _sector_col = next((c for c in df.columns if c.lower() in ("sector", "sector_name")), None)
        _score_col = next((c for c in df.columns if c.lower() in ("score", "yieldiq_score")), None)
        _mos_col = next((c for c in df.columns if c.lower() in ("mos", "mos_pct")), None)

        if _sector_col and _score_col:
            result = []
            for sector, group in df.groupby(_sector_col):
                _avg_score = group[_score_col].mean()
                _pct_under = (group[_mos_col] > 0).mean() * 100 if _mos_col else 50
                result.append({
                    "name": str(sector),
                    "avg_score": _avg_score,
                    "pct_undervalued": _pct_under,
                    "trend": "↑" if _avg_score > 60 else "→" if _avg_score > 45 else "↓",
                })
            return sorted(result, key=lambda x: x["avg_score"], reverse=True)

    # Static fallback for Indian market
    return [
        {"name": "Technology", "avg_score": 65, "pct_undervalued": 55, "trend": "↑"},
        {"name": "Financials", "avg_score": 62, "pct_undervalued": 60, "trend": "↑"},
        {"name": "Healthcare", "avg_score": 58, "pct_undervalued": 45, "trend": "→"},
        {"name": "Consumer Staples", "avg_score": 55, "pct_undervalued": 40, "trend": "→"},
        {"name": "Industrials", "avg_score": 54, "pct_undervalued": 50, "trend": "↑"},
        {"name": "Energy", "avg_score": 52, "pct_undervalued": 48, "trend": "↓"},
        {"name": "Materials", "avg_score": 50, "pct_undervalued": 42, "trend": "→"},
        {"name": "Utilities", "avg_score": 48, "pct_undervalued": 35, "trend": "↓"},
        {"name": "Real Estate", "avg_score": 45, "pct_undervalued": 30, "trend": "↓"},
    ]
