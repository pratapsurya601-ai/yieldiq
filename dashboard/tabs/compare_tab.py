# dashboard/tabs/compare_tab.py
# ═══════════════════════════════════════════════════════════════
# Compare Stocks — Koyfin-style multi-ticker comparison
#
# UI:  4 individual ticker inputs  →  st.tabs() with
#       Valuation | Growth | Quality | Price Performance
# Backend:  ThreadPoolExecutor DCF + moat + quality (unchanged)
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

from data.collector import StockDataCollector
from data.processor import compute_metrics
from models.forecaster import FCFForecaster, compute_wacc, compute_confidence_score
from screener.dcf_engine import DCFEngine, margin_of_safety, assign_signal
from screener.piotroski import compute_piotroski_fscore as _piotroski_raw
from screener.earnings_quality import compute_earnings_quality as _eq_raw
from screener.moat_engine import compute_moat_score, apply_moat_adjustments
from tab_helpers import ccard, ccard_end
from ui.helpers import themed_metric


def _get_active_theme():
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent.parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_x", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    import streamlit as st
    return _tm.get_theme(st.session_state.get("theme", "slate"))



# ── Palette & rank maps ────────────────────────────────────────
_PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]

_SIG_RANK = {
    "Undervalued 🟢":    4,
    "Near Fair Value 🟡":3,
    "Fairly Valued 🔵":  2,
    "Overvalued 🔴":     1,
    "⚠️ Data Limited":   0,
    "N/A ⬜":            0,
}
_SIG_COLORS = {
    "Undervalued 🟢":    "#059669",
    "Near Fair Value 🟡":"#D97706",
    "Fairly Valued 🔵":  "#2563EB",
    "Overvalued 🔴":     "#DC2626",
    "⚠️ Data Limited":   "#D97706",
    "N/A ⬜":            "#64748B",
}
_EQ_RANK   = {"STRONG": 4, "GOOD": 3, "AVERAGE": 2, "WEAK": 1, "N/A": 0}
_EQ_COLORS = {
    "STRONG":  "#059669",
    "GOOD":    "#2563EB",
    "AVERAGE": "#D97706",
    "WEAK":    "#DC2626",
    "N/A":     "#64748B",
}


# ══════════════════════════════════════════════════════════════
# CACHED DATA FETCHERS  (safe to call from main thread)
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_revenue_history(ticker: str) -> pd.Series:
    """
    Return a pd.Series of annual Total Revenue values indexed by year (int),
    sorted ascending.  Returns an empty Series on failure.
    """
    try:
        t = yf.Ticker(ticker)
        # income_stmt rows × columns=fiscal-year dates
        fin = t.income_stmt
        if fin is None or fin.empty:
            fin = t.financials          # older yfinance versions
        if fin is None or fin.empty:
            return pd.Series(dtype=float)
        # Find the revenue row (label varies by yfinance version)
        for row_label in ("Total Revenue", "Revenue", "TotalRevenue"):
            if row_label in fin.index:
                rev = fin.loc[row_label].dropna()
                rev.index = pd.to_datetime(rev.index, errors="coerce")
                rev = rev[rev.index.notna()]
                rev.index = rev.index.year
                return rev.sort_index()
        return pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_price_history(
    tickers_tuple: tuple[str, ...],
    period: str = "1y",
) -> pd.DataFrame:
    """
    Download daily close prices for tickers + SPY.
    Returns a DataFrame with ticker columns, NaN-filled on failure.
    """
    try:
        symbols = list(tickers_tuple) + ["SPY"]
        df = yf.download(
            symbols,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )["Close"]
        # yfinance returns a Series (not DataFrame) when only one ticker
        if isinstance(df, pd.Series):
            df = df.to_frame(name=symbols[0])
        return df.dropna(how="all")
    except Exception:
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════
# ANALYSIS PIPELINE  (pure computation — no st.* calls)
# ══════════════════════════════════════════════════════════════

def _run_single(ticker: str) -> dict:
    """Full DCF + moat + quality analysis for one ticker."""
    ticker = ticker.upper().strip()

    collector = StockDataCollector(ticker)
    raw = collector.get_all()
    if raw is None:
        raise ValueError(f"No data returned for {ticker}")

    # ── WACC ────────────────────────────────────────────────
    wacc_data: dict = {}
    if collector._ticker_obj:
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")
        wacc_data = compute_wacc(collector._ticker_obj, is_indian)

    enriched = compute_metrics(raw)

    # ── Industry WACC + sector ──────────────────────────────
    wacc      = wacc_data.get("wacc", 0.10)
    terminal_g = 0.03
    try:
        from models.industry_wacc import get_industry_wacc, detect_sector
        _yf_sector  = raw.get("sector_name", "")
        _sector_key = detect_sector(ticker, _yf_sector)
        _ind_info   = get_industry_wacc(
            ticker=ticker, yf_sector=_yf_sector, capm_wacc=wacc
        )
        enriched["sector"]      = _sector_key
        enriched["sector_name"] = _ind_info.get("sector_name", _sector_key)
        wacc       = _ind_info["wacc"]
        terminal_g = _ind_info["terminal_growth"]
    except Exception:
        enriched.setdefault("sector", "general")

    # ── DCF ─────────────────────────────────────────────────
    forecaster      = FCFForecaster()
    forecast_result = forecaster.predict(enriched, years=10)
    projected       = forecast_result["projections"]
    terminal_norm   = forecast_result["terminal_fcf_norm"]
    base_growth     = forecast_result["base_growth"]

    dcf_engine = DCFEngine(discount_rate=wacc, terminal_growth=terminal_g)
    dcf_res    = dcf_engine.intrinsic_value_per_share(
        projected_fcfs     = projected,
        terminal_fcf_norm  = terminal_norm,
        total_debt         = enriched["total_debt"],
        total_cash         = enriched["total_cash"],
        shares_outstanding = enriched["shares"],
        current_price      = enriched["price"],
        ticker             = ticker,
    )

    iv_n = dcf_res.get("intrinsic_value_per_share", 0)

    # ── PE blending ─────────────────────────────────────────
    try:
        from screener.valuation_crosscheck import (
            compute_pe_based_iv, blend_dcf_pe, get_eps,
        )
        _sector = enriched.get("sector", "general")
        _eps    = get_eps(enriched)
        _pe_iv  = compute_pe_based_iv(
            _eps, _sector, scenario="base",
            growth=enriched.get("revenue_growth", None),
        )
        if enriched.get("dcf_reliable", True) and iv_n > 0 and _pe_iv > 0:
            iv_n = blend_dcf_pe(iv_n, _pe_iv, _sector)
        elif _pe_iv > 0 and not enriched.get("dcf_reliable", True):
            _impl_pe = enriched["price"] / max(_eps, 0.01)
            if 5 <= _impl_pe <= 60:
                iv_n = _pe_iv
    except Exception:
        pass

    # ── Moat ────────────────────────────────────────────────
    moat_grade = "None"
    moat_score = 0
    try:
        moat_result  = compute_moat_score(enriched, wacc)
        moat_adj     = apply_moat_adjustments(
            moat_result, wacc, base_growth, terminal_g, iv_n,
            sector=enriched.get("sector", "general"),
        )
        moat_grade   = moat_result.get("grade",      "None")
        moat_score   = moat_result.get("score",      0)
        iv_delta_pct = moat_adj.get("iv_delta_pct",  0) / 100
        iv_n_moat    = iv_n * (1 + iv_delta_pct)
        enriched["moat_grade"] = moat_grade
        enriched["moat_score"] = moat_score
    except Exception:
        iv_n_moat = iv_n
        enriched.setdefault("moat_grade", "N/A")
        enriched.setdefault("moat_score", 0)

    # ── Confidence haircut ───────────────────────────────────
    try:
        _conf    = compute_confidence_score(enriched)
        _haircut = 1.0
        for _w in _conf.get("warnings", []):
            if "DECLINING" in _w:
                _haircut *= 0.55
            elif "spike" in _w.lower():
                _haircut *= 0.60
            elif "decelerat" in _w.lower():
                _haircut *= 0.80
        iv_n_moat *= _haircut
    except Exception:
        pass

    price  = enriched["price"]
    mos    = margin_of_safety(iv_n_moat, price)
    signal = assign_signal(
        mos,
        dcf_res.get("suspicious", False),
        forecast_result.get("reliable", True),
    )

    # ── Piotroski ────────────────────────────────────────────
    piotroski_score = 0
    try:
        pf = _piotroski_raw(enriched)
        piotroski_score = int(pf.get("score", 0))
    except Exception:
        pass

    # ── Earnings quality ────────────────────────────────────
    eq_grade = "N/A"
    eq_score = 0.0
    try:
        eq       = _eq_raw(enriched)
        eq_grade = eq.get("grade", "N/A")
        eq_score = float(eq.get("score", 0))
    except Exception:
        pass

    # ── Valuation multiples ─────────────────────────────────
    forward_pe   = float(enriched.get("forward_pe",   0) or 0)
    trailing_eps = float(enriched.get("trailing_eps", 0) or 0)
    if 3 < forward_pe < 200:
        pe = forward_pe
    elif trailing_eps > 0 and price > 0:
        pe = price / trailing_eps
    else:
        pe = 0.0

    ev_ebitda = float(enriched.get("ev_to_ebitda", 0) or 0)
    pb        = float(enriched.get("pb_ratio",     0) or 0)

    # P/FCF  =  price / (free_cash_flow / shares)
    _fcf    = float(enriched.get("free_cash_flow", 0) or 0)
    _shares = float(enriched.get("shares", 1)        or 1)
    _fcf_ps = _fcf / _shares if _shares > 0 else 0.0
    p_fcf   = (price / _fcf_ps) if 0 < _fcf_ps and price > 0 else 0.0
    # Clamp absurd values
    if p_fcf > 500 or p_fcf < 0:
        p_fcf = 0.0

    # ── Quality metrics ─────────────────────────────────────
    roe           = float(enriched.get("roe",           0) or 0) * 100
    fcf_margin    = float(enriched.get("fcf_margin",    0) or 0) * 100
    current_ratio = float(enriched.get("current_ratio", 0) or 0)
    debt_equity   = float(enriched.get("debt_equity",   0) or 0)

    return {
        "ticker":          ticker,
        "company_name":    raw.get("company_name", ticker),
        "sector":          enriched.get("sector_name", enriched.get("sector", "—")),
        "price":           price,
        "intrinsic_value": iv_n_moat,
        "mos_pct":         mos * 100,
        "signal":          signal,
        "wacc":            wacc * 100,
        # Growth
        "fcf_growth":      (enriched.get("fcf_growth")     or 0) * 100,
        "revenue_growth":  (enriched.get("revenue_growth") or 0) * 100,
        # Valuation
        "pe":              pe,
        "pb":              pb,
        "ev_ebitda":       ev_ebitda,
        "p_fcf":           p_fcf,
        # Quality
        "op_margin":       (enriched.get("op_margin") or 0) * 100,
        "fcf_margin":      fcf_margin,
        "roe":             roe,
        "current_ratio":   current_ratio,
        "debt_equity":     debt_equity,
        # Scores
        "moat_score":      float(moat_score),
        "moat_grade":      moat_grade,
        "piotroski_score": float(piotroski_score),
        "eq_grade":        eq_grade,
        "eq_score":        eq_score,
        "dcf_reliable":    enriched.get("dcf_reliable", True),
    }


# ══════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════

def _norm(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return float(np.clip((v - lo) / (hi - lo) * 100, 0, 100))


def _conviction_score(r: dict) -> float:
    return (
        0.25 * _norm(r["mos_pct"],         -50, 100) +
        0.20 * _norm(r["piotroski_score"],    0,   9) +
        0.20 * _norm(r["moat_score"],         0, 100) +
        0.15 * _norm(r["eq_score"],           0, 100) +
        0.15 * _norm(r["fcf_growth"],       -10,  40) +
        0.05 * _norm(r["op_margin"],        -20,  40)
    )


_RADAR_DIMS = [
    "Value",
    "Quality",
    "Growth",
    "Moat",
    "Earnings\nQuality",
    "Profitability",
]


def _radar_scores(r: dict) -> list[float]:
    return [
        _norm(r["mos_pct"],        -50, 100),
        _norm(r["piotroski_score"],  0,   9),
        _norm(r["fcf_growth"],     -10,  40),
        _norm(r["moat_score"],       0, 100),
        _norm(r["eq_score"],         0, 100),
        _norm(r["op_margin"],      -20,  40),
    ]


# ══════════════════════════════════════════════════════════════
# HIGHLIGHT HELPERS
# ══════════════════════════════════════════════════════════════

def _highlight(values: list[float], higher_is_better) -> tuple[int, int]:
    if higher_is_better is None or len(values) < 2:
        return -1, -1
    valid = [(i, v) for i, v in enumerate(values) if v is not None and v != 0]
    if len(valid) < 2:
        return -1, -1
    if higher_is_better:
        best  = max(valid, key=lambda x: x[1])[0]
        worst = min(valid, key=lambda x: x[1])[0]
    else:
        best  = min(valid, key=lambda x: x[1])[0]
        worst = max(valid, key=lambda x: x[1])[0]
    return best, worst


def _cell_style(i: int, best: int, worst: int) -> str:
    if i == best:
        return "background:#ECFDF5;color:#059669;font-weight:700;"
    if i == worst:
        return "background:#FEF2F2;color:#DC2626;font-weight:700;"
    return "color:#0F172A;"


def _fmt(key: str, v) -> str:
    if v is None or v == 0:
        return "—"
    if key in ("price", "intrinsic_value"):
        return f"${v:,.2f}"
    if key == "mos_pct":
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"
    if key in ("fcf_growth", "revenue_growth", "op_margin",
               "fcf_margin", "roe", "wacc"):
        sign = "+" if v > 0 and key != "wacc" else ""
        return f"{sign}{v:.1f}%"
    if key in ("pe", "pb", "ev_ebitda", "p_fcf"):
        return f"{v:.1f}x"
    if key == "current_ratio":
        return f"{v:.2f}"
    if key == "debt_equity":
        return f"{v:.2f}x"
    if key == "moat_score":
        return f"{v:.0f}/100"
    if key == "piotroski_score":
        return f"{v:.0f}/9"
    return str(v)


# ══════════════════════════════════════════════════════════════
# HTML COMPARISON TABLE
# ══════════════════════════════════════════════════════════════

_ROWS = [
    # (field_key,        label,                  higher_is_better)
    ("price",            "Current Price",         None),
    ("intrinsic_value",  "Intrinsic Value",        None),
    ("mos_pct",          "Margin of Safety",       True),
    ("signal",           "Signal",                 True),
    ("wacc",             "WACC",                   False),
    ("pe",               "P/E Ratio",              False),
    ("pb",               "P/B Ratio",              False),
    ("ev_ebitda",        "EV / EBITDA",            False),
    ("p_fcf",            "P / FCF",                False),
    ("revenue_growth",   "Revenue Growth",         True),
    ("fcf_growth",       "FCF Growth",             True),
    ("op_margin",        "Operating Margin",       True),
    ("fcf_margin",       "FCF Margin",             True),
    ("roe",              "ROE",                    True),
    ("current_ratio",    "Current Ratio",          True),
    ("debt_equity",      "Debt / Equity",          False),
    ("moat_score",       "Moat Score",             True),
    ("piotroski_score",  "Piotroski Score",        True),
    ("eq_grade",         "Earnings Quality",       True),
]


def _build_table(results: list[dict]) -> str:
    n        = len(results)
    col_w    = f"{100 / (n + 1):.1f}%"
    metric_w = f"{100 / (n + 1):.1f}%"

    html = (
        '<div style="overflow-x:auto;margin-bottom:4px;">'
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:\'Inter\',sans-serif;font-size:13px;">'
        '<thead><tr style="background:#1A2540;">'
        f'<th style="text-align:left;padding:10px 14px;font-size:10px;font-weight:700;'
        f'letter-spacing:.1em;text-transform:uppercase;color:#94A3B8;width:{metric_w};">'
        'Metric</th>'
    )
    for r in results:
        company_short = (r["company_name"] or r["ticker"])[:22]
        html += (
            f'<th style="text-align:center;padding:10px 14px;font-size:13px;'
            f'font-weight:700;color:#FFFFFF;font-family:\'IBM Plex Mono\',monospace;'
            f'width:{col_w};">'
            f'{r["ticker"]}<br>'
            f'<span style="font-size:10px;font-weight:400;color:#94A3B8;">'
            f'{company_short}</span></th>'
        )
    html += '</tr></thead><tbody>'

    for row_idx, (key, label, higher_better) in enumerate(_ROWS):
        if key == "signal":
            sort_vals = [_SIG_RANK.get(r.get(key, ""), 0) for r in results]
        elif key == "eq_grade":
            sort_vals = [_EQ_RANK.get(r.get(key, "N/A"), 0) for r in results]
        else:
            sort_vals = [float(r.get(key, 0) or 0) for r in results]

        best_idx, worst_idx = _highlight(sort_vals, higher_better)
        row_bg = "#F8FAFC" if row_idx % 2 == 1 else "#FFFFFF"

        html += (
            f'<tr style="background:{row_bg};border-bottom:1px solid #F1F5F9;">'
            f'<td style="padding:10px 14px;font-size:12px;font-weight:600;'
            f'color:#475569;white-space:nowrap;">{label}</td>'
        )

        for i, r in enumerate(results):
            v      = r.get(key)
            cstyle = _cell_style(i, best_idx, worst_idx)

            if key == "signal":
                color   = _SIG_COLORS.get(v, "#64748B")
                display = f'<span style="color:{color};font-weight:700;">{v or "—"}</span>'
            elif key == "eq_grade":
                color   = _EQ_COLORS.get(v, "#64748B")
                display = f'<span style="color:{color};font-weight:700;">{v or "—"}</span>'
            else:
                display = _fmt(key, v)

            html += (
                f'<td style="text-align:center;padding:10px 14px;'
                f'font-family:\'IBM Plex Mono\',monospace;{cstyle}">'
                f'{display}</td>'
            )
        html += '</tr>'

    html += '</tbody></table></div>'
    return html


# ══════════════════════════════════════════════════════════════
# CHART BUILDERS
# ══════════════════════════════════════════════════════════════

_LAYOUT_BASE = dict(
    paper_bgcolor = "rgba(0,0,0,0)",
    plot_bgcolor  = "rgba(0,0,0,0)",
    font          = dict(family="Inter, sans-serif", size=12, color="#475569"),
    margin        = dict(l=10, r=10, t=44, b=10),
    legend        = dict(
        orientation = "h",
        y           = -0.18,
        font        = dict(size=11),
    ),
    xaxis = dict(
        gridcolor = "rgba(0,0,0,0.04)",
        linecolor = "#E2E8F0",
        tickfont  = dict(family="IBM Plex Mono, monospace", size=11),
    ),
    yaxis = dict(
        gridcolor = "rgba(0,0,0,0.04)",
        linecolor = "#E2E8F0",
        tickfont  = dict(family="IBM Plex Mono, monospace", size=11),
    ),
)


def _build_valuation_chart(results: list[dict]) -> go.Figure:
    """Grouped bar chart — P/E, P/B, EV/EBITDA, P/FCF for each ticker."""
    metrics = ["P/E", "P/B", "EV/EBITDA", "P/FCF"]
    keys    = ["pe",  "pb",  "ev_ebitda", "p_fcf"]

    fig = go.Figure()
    for i, r in enumerate(results):
        color = _PALETTE[i % len(_PALETTE)]
        vals  = [float(r.get(k, 0) or 0) for k in keys]
        # Replace zeros with None so bar doesn't render
        vals_clean = [v if v > 0 else None for v in vals]
        fig.add_trace(go.Bar(
            name          = r["ticker"],
            x             = metrics,
            y             = vals_clean,
            marker_color  = color,
            text          = [f"{v:.1f}x" if v else "N/A" for v in vals_clean],
            textposition  = "outside",
            textfont      = dict(family="IBM Plex Mono, monospace", size=10),
        ))

    fig.update_layout(
        **_LAYOUT_BASE,
        barmode = "group",
        height  = 380,
        title   = dict(
            text = "Valuation Multiples",
            font = dict(size=14, family="Inter, sans-serif", color="#0F172A"),
            x    = 0.02,
        ),
        yaxis_title = "Multiple (×)",
    )
    return fig


def _build_growth_chart(results: list[dict]) -> go.Figure:
    """
    Bar chart comparing Revenue Growth % and FCF Growth % side by side.
    Also attempts to show 4-year revenue history bars per ticker.
    """
    tickers = [r["ticker"] for r in results]

    # ── Historical revenue from yfinance ────────────────────
    rev_series: dict[str, pd.Series] = {}
    for t in tickers:
        s = _fetch_revenue_history(t)
        if not s.empty:
            rev_series[t] = s.tail(5)

    fig = go.Figure()

    if rev_series:
        # Line chart: revenue over time per ticker
        for i, ticker in enumerate(tickers):
            s = rev_series.get(ticker)
            if s is None or s.empty:
                continue
            color = _PALETTE[i % len(_PALETTE)]
            fig.add_trace(go.Scatter(
                x          = s.index.tolist(),
                y          = (s / 1e9).tolist(),
                mode       = "lines+markers",
                name       = ticker,
                line       = dict(color=color, width=2.5),
                marker     = dict(size=7, color=color),
                hovertemplate = (
                    f"<b>{ticker}</b><br>"
                    "Year: %{x}<br>"
                    "Revenue: $%{y:.2f}B<extra></extra>"
                ),
            ))
        fig.update_layout(
            **_LAYOUT_BASE,
            height = 380,
            title  = dict(
                text = "Annual Revenue History",
                font = dict(size=14, family="Inter, sans-serif", color="#0F172A"),
                x    = 0.02,
            ),
            yaxis_title = "Revenue (USD Billions)",
            xaxis_title = "Fiscal Year",
        )
    else:
        # Fallback: grouped bar for TTM growth rates
        metrics = ["Revenue Growth %", "FCF Growth %"]
        for i, r in enumerate(results):
            color = _PALETTE[i % len(_PALETTE)]
            vals  = [r.get("revenue_growth", 0) or 0,
                     r.get("fcf_growth",     0) or 0]
            fig.add_trace(go.Bar(
                name         = r["ticker"],
                x            = metrics,
                y            = vals,
                marker_color = color,
                text         = [f"{v:+.1f}%" for v in vals],
                textposition = "outside",
                textfont     = dict(family="IBM Plex Mono, monospace", size=10),
            ))
        fig.update_layout(
            **_LAYOUT_BASE,
            barmode     = "group",
            height      = 380,
            title       = dict(
                text = "Growth Rates (TTM)",
                font = dict(size=14, family="Inter, sans-serif", color="#0F172A"),
                x    = 0.02,
            ),
            yaxis_title = "Growth (%)",
        )
        fig.add_hline(y=0, line_dash="dot", line_color="#94A3B8", line_width=1)

    return fig


def _build_quality_radar(results: list[dict]) -> go.Figure:
    """Spider chart — 5 quality dimensions, all tickers overlaid."""
    # Axes: ROE, Op Margin, FCF Margin, Current Ratio (normalized), D/E (inverted)
    dims = ["ROE", "Op Margin", "FCF Margin", "Liquidity", "Low Leverage"]
    dims_closed = dims + [dims[0]]

    def _quality_scores(r: dict) -> list[float]:
        return [
            _norm(r.get("roe",           0), -20,  60),   # ROE
            _norm(r.get("op_margin",     0), -10,  50),   # Op Margin
            _norm(r.get("fcf_margin",    0), -10,  40),   # FCF Margin
            _norm(r.get("current_ratio", 0),   0,   4),   # Liquidity
            _norm(-(r.get("debt_equity", 0)),  -8,   0),  # Low Leverage (inverted D/E)
        ]

    fig = go.Figure()
    for i, r in enumerate(results):
        scores = _quality_scores(r)
        scores_closed = scores + [scores[0]]
        color  = _PALETTE[i % len(_PALETTE)]
        h      = color.lstrip("#")
        rgb    = tuple(int(h[j:j+2], 16) for j in (0, 2, 4))
        fig.add_trace(go.Scatterpolar(
            r         = scores_closed,
            theta     = dims_closed,
            fill      = "toself",
            fillcolor = f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.15)",
            line      = dict(color=color, width=2),
            name      = r["ticker"],
            hovertemplate = (
                f"<b>{r['ticker']}</b><br>"
                "%{theta}: %{r:.0f}/100<extra></extra>"
            ),
        ))

    fig.update_layout(
        polar = dict(
            bgcolor      = "#F8FAFC",
            radialaxis   = dict(
                visible   = True,
                range     = [0, 100],
                tickfont  = dict(color="#94A3B8", size=9),
                gridcolor = "rgba(0,0,0,0.04)",
                linecolor = "#E2E8F0",
                tickvals  = [25, 50, 75, 100],
            ),
            angularaxis = dict(
                tickfont  = dict(color="#0F172A", size=11, family="Inter, sans-serif"),
                gridcolor = "rgba(0,0,0,0.04)",
                linecolor = "#E2E8F0",
            ),
        ),
        paper_bgcolor = "rgba(0,0,0,0)",
        plot_bgcolor  = "rgba(0,0,0,0)",
        font   = dict(family="Inter, sans-serif"),
        legend = dict(
            orientation = "h", y=-0.12,
            font=dict(size=11),
        ),
        margin = dict(l=60, r=60, t=30, b=30),
        height = 420,
    )
    return fig


def _build_radar(results: list[dict]) -> go.Figure:
    """Full 6-dimension investment radar (Value+Quality+Growth+Moat+EQ+Profitability)."""
    dims   = _RADAR_DIMS + [_RADAR_DIMS[0]]
    fig    = go.Figure()
    for i, r in enumerate(results):
        scores = _radar_scores(r)
        color  = _PALETTE[i % len(_PALETTE)]
        h      = color.lstrip("#")
        rgb    = tuple(int(h[j:j+2], 16) for j in (0, 2, 4))
        fig.add_trace(go.Scatterpolar(
            r         = scores + [scores[0]],
            theta     = dims,
            fill      = "toself",
            fillcolor = f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.15)",
            line      = dict(color=color, width=2),
            name      = r["ticker"],
            hovertemplate = (
                f"<b>{r['ticker']}</b><br>"
                "%{theta}: %{r:.0f}/100<extra></extra>"
            ),
        ))
    fig.update_layout(
        polar = dict(
            bgcolor     = "#161b22",
            radialaxis  = dict(
                visible   = True,
                range     = [0, 100],
                tickfont  = dict(color="#8b949e", size=9),
                gridcolor = "rgba(0,0,0,0.04)",
                linecolor = "#30363d",
                tickvals  = [25, 50, 75, 100],
            ),
            angularaxis = dict(
                tickfont  = dict(color="#e6edf3", size=11, family="Inter, sans-serif"),
                gridcolor = "rgba(0,0,0,0.04)",
                linecolor = "#30363d",
            ),
        ),
        paper_bgcolor = _get_active_theme()["chart_paper"],
        plot_bgcolor  = _get_active_theme()["chart_bg"],
        font          = dict(family="Inter, sans-serif", color="#e6edf3"),
        legend        = dict(
            bgcolor="rgba(0,0,0,0)", bordercolor="#30363d",
            borderwidth=1, font=dict(color="#8b949e", size=11),
        ),
        margin = dict(l=60, r=60, t=30, b=30),
        height = 420,
    )
    return fig


def _build_price_chart(results: list[dict], period: str) -> go.Figure:
    """
    Normalized price chart (base 100) for all tickers + SPY benchmark.
    """
    tickers_tuple = tuple(r["ticker"] for r in results)
    df = _fetch_price_history(tickers_tuple, period=period)

    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text="Price data unavailable",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=14, color="#94A3B8"),
        )
        fig.update_layout(**_LAYOUT_BASE, height=380)
        return fig

    # Normalize to 100 at start
    df_norm = df.div(df.iloc[0]) * 100

    # Plot each ticker
    for i, r in enumerate(results):
        t = r["ticker"]
        if t not in df_norm.columns:
            continue
        color = _PALETTE[i % len(_PALETTE)]
        s     = df_norm[t].dropna()
        fig.add_trace(go.Scatter(
            x    = s.index,
            y    = s.values,
            name = t,
            mode = "lines",
            line = dict(color=color, width=2.5),
            hovertemplate = (
                f"<b>{t}</b><br>"
                "%{x|%b %d, %Y}<br>"
                "Return: %{customdata:+.1f}%<extra></extra>"
            ),
            customdata = s.values - 100,
        ))

    # S&P 500 as dashed grey benchmark
    if "SPY" in df_norm.columns:
        spy = df_norm["SPY"].dropna()
        fig.add_trace(go.Scatter(
            x    = spy.index,
            y    = spy.values,
            name = "S&P 500",
            mode = "lines",
            line = dict(color="#94A3B8", width=1.5, dash="dash"),
            hovertemplate = (
                "<b>S&P 500</b><br>"
                "%{x|%b %d, %Y}<br>"
                "Return: %{customdata:+.1f}%<extra></extra>"
            ),
            customdata = spy.values - 100,
        ))

    # Zero-baseline
    fig.add_hline(y=100, line_dash="dot", line_color="#CBD5E1", line_width=1)

    _period_labels = {
        "1mo": "1 Month", "3mo": "3 Months",
        "6mo": "6 Months", "1y":  "1 Year",
    }
    fig.update_layout(
        **_LAYOUT_BASE,
        height = 400,
        title  = dict(
            text = f"Normalized Price Performance — {_period_labels.get(period, period)}",
            font = dict(size=14, family="Inter, sans-serif", color="#0F172A"),
            x    = 0.02,
        ),
        yaxis_title = "Indexed Return (base 100)",
        hovermode   = "x unified",
    )
    return fig


# ══════════════════════════════════════════════════════════════
# BEST PICK BOX
# ══════════════════════════════════════════════════════════════

def _render_best_pick(results: list[dict]) -> None:
    scored    = sorted(results, key=_conviction_score, reverse=True)
    best      = scored[0]
    score     = _conviction_score(best)
    sig_color = _SIG_COLORS.get(best["signal"], "#64748B")

    reasons = []
    if best["mos_pct"] >= 20:
        reasons.append(f"trading {best['mos_pct']:.0f}% below estimated fair value")
    if best["piotroski_score"] >= 6:
        reasons.append(f"strong business health (Piotroski {best['piotroski_score']:.0f}/9)")
    if best["moat_grade"] in ("Wide", "Narrow"):
        reasons.append(f"{best['moat_grade'].lower()} economic moat")
    if best["eq_grade"] in ("STRONG", "GOOD"):
        reasons.append(f"{best['eq_grade'].lower()} earnings quality")
    if not reasons:
        reasons.append("best composite score across all dimensions")
    why = ", ".join(reasons[:3])

    runners = [
        f"{r['ticker']} ({_conviction_score(r):.0f})"
        for r in scored[1:]
    ]
    runners_html = (
        f'<div style="font-size:11px;color:#64748B;margin-top:6px;">'
        f'Runners-up: {", ".join(runners)}</div>'
        if runners else ""
    )

    ccard("Highest Conviction Pick", "#059669")
    st.html(f"""
<div style="background:linear-gradient(135deg,#0c1a14,#0f2520);
            border:1.5px solid #059669;border-radius:14px;
            padding:24px 28px;margin-bottom:4px;position:relative;overflow:hidden;">
  <div style="position:absolute;top:0;left:0;right:0;height:3px;
              background:linear-gradient(90deg,#059669,#00b4d8);"></div>
  <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap;">

    <div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:36px;
                  font-weight:800;color:#FFFFFF;letter-spacing:-.01em;line-height:1.1;">
        {best['ticker']}
      </div>
      <div style="font-size:12px;color:#94A3B8;margin-top:4px;">{best['company_name']}</div>
    </div>

    <div style="width:1px;height:56px;background:rgba(255,255,255,0.12);flex-shrink:0;"></div>

    <div>
      <span style="display:inline-block;padding:5px 16px;border-radius:20px;
                   background:rgba(5,150,105,0.15);border:1px solid {sig_color};
                   font-size:13px;font-weight:700;color:{sig_color};">
        {best['signal']}
      </span>
      <div style="font-size:12px;color:#64748B;margin-top:8px;">
        Conviction Score:
        <span style="color:#e6edf3;font-weight:700;font-family:'IBM Plex Mono',monospace;">
          {score:.0f} / 100
        </span>
      </div>
      <div style="font-size:12px;color:#64748B;margin-top:2px;">
        IV: <span style="color:#e6edf3;font-family:'IBM Plex Mono',monospace;">
          ${best['intrinsic_value']:,.2f}
        </span>
        &nbsp;·&nbsp; MoS:
        <span style="color:{'#059669' if best['mos_pct'] >= 0 else '#DC2626'};
                     font-family:'IBM Plex Mono',monospace;font-weight:700;">
          {best['mos_pct']:+.1f}%
        </span>
      </div>
    </div>

    <div style="width:1px;height:56px;background:rgba(255,255,255,0.12);flex-shrink:0;"></div>

    <div style="flex:1;min-width:220px;">
      <div style="font-size:13px;color:#CBD5E1;line-height:1.65;">
        <strong style="color:#e6edf3;">{best['ticker']}</strong>
        ranks highest due to: {why}.
      </div>
      {runners_html}
    </div>

  </div>
</div>
""")
    ccard_end()


# ══════════════════════════════════════════════════════════════
# DATAFRAME SUMMARY  (for export / accessibility)
# ══════════════════════════════════════════════════════════════

def _build_summary_df(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "ticker":       r["ticker"],
            "company":      (r.get("company_name") or r["ticker"])[:28],
            "signal":       r.get("signal", "—"),
            "mos_pct":      r.get("mos_pct",        0) or 0,
            "price":        r.get("price",           0) or 0,
            "iv":           r.get("intrinsic_value", 0) or 0,
            "pe":           r.get("pe",              0) or 0,
            "pb":           r.get("pb",              0) or 0,
            "ev_ebitda":    r.get("ev_ebitda",       0) or 0,
            "roe":          r.get("roe",             0) or 0,
            "op_margin":    r.get("op_margin",       0) or 0,
            "rev_growth":   r.get("revenue_growth",  0) or 0,
            "piotroski":    r.get("piotroski_score", 0) or 0,
            "moat":         r.get("moat_grade",      "—"),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
# RENDER — main entry point
# ══════════════════════════════════════════════════════════════

def render(tab) -> None:
    """Render the Compare Stocks tab — Koyfin-style multi-metric layout."""
    with tab:

        # ── Header ────────────────────────────────────────────────────
        ccard("Compare Stocks", "#7c3aed")
        st.html("""
<div style="font-size:13px;color:#64748B;margin-bottom:12px;line-height:1.6;">
  Enter 2–4 ticker symbols to run a full DCF, moat &amp; quality analysis on each
  in parallel — then compare Valuation, Growth, Quality, and Price Performance.
  Green cell = best in group &nbsp;·&nbsp; Red = worst.
</div>""")
        ccard_end()

        # ── Dataframe header style ─────────────────────────────────────
        st.markdown("""<style>
div[data-testid="stDataFrame"] th {
    background-color: #1A2540 !important;
    color: white !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}
div[data-testid="stDataFrame"] td {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
}
</style>""", unsafe_allow_html=True)

        # ── Ticker input row ──────────────────────────────────────────
        _cols = st.columns([1, 1, 1, 1, 1])
        ticker1 = _cols[0].text_input("Stock 1", "AAPL",  key="_cmp_t1")
        ticker2 = _cols[1].text_input("Stock 2", "MSFT",  key="_cmp_t2")
        ticker3 = _cols[2].text_input("Stock 3", "GOOGL", key="_cmp_t3")
        ticker4 = _cols[3].text_input("Stock 4", "",      key="_cmp_t4",
                                      placeholder="Optional")
        compare_btn = _cols[4].button(
            "Compare →",
            type             = "primary",
            use_container_width = True,
            key              = "_cmp_run_btn",
        )
        # Vertical alignment helper — push button to bottom of the cell
        _cols[4].markdown(
            "<style>"
            "div[data-testid='column']:nth-child(5) .stButton{margin-top:24px;}</style>",
            unsafe_allow_html=True,
        )

        # ── Parse tickers ─────────────────────────────────────────────
        tickers = [
            t.strip().upper()
            for t in [ticker1, ticker2, ticker3, ticker4]
            if t.strip()
        ]
        tickers = list(dict.fromkeys(tickers))   # deduplicate

        if compare_btn and tickers:
            if len(tickers) < 2:
                st.warning("Enter at least 2 tickers to compare.")
                return

            results: dict[str, dict] = {}
            errors:  dict[str, str]  = {}

            prog = st.progress(
                0,
                text=f"Running analysis for {len(tickers)} stocks in parallel…",
            )
            with ThreadPoolExecutor(max_workers=len(tickers)) as pool:
                futures = {pool.submit(_run_single, t): t for t in tickers}
                done    = 0
                for fut in as_completed(futures):
                    t    = futures[fut]
                    done += 1
                    try:
                        results[t] = fut.result()
                    except Exception as exc:
                        errors[t]  = str(exc)
                    prog.progress(
                        done / len(tickers),
                        text=f"Completed {done} of {len(tickers)}…",
                    )
            prog.empty()

            for t, err in errors.items():
                st.warning(f"Could not analyse **{t}**: {err}")

            if len(results) < 2:
                st.error("Need at least 2 successful analyses to compare.")
                return

            st.session_state["_cmp_results"] = results
            st.session_state["_cmp_order"]   = [t for t in tickers if t in results]

        # ── Pull from session state ───────────────────────────────────
        _map     = st.session_state.get("_cmp_results", {})
        _ordered = st.session_state.get("_cmp_order",   [])
        if not _map or not _ordered:
            _render_empty_state()
            return

        result_list = [_map[t] for t in _ordered if t in _map]
        if len(result_list) < 2:
            return

        # ── Best Pick ─────────────────────────────────────────────────
        _render_best_pick(result_list)

        # ── Metric Tabs ───────────────────────────────────────────────
        _tab_val, _tab_gr, _tab_qu, _tab_px = st.tabs([
            "💰 Valuation",
            "📈 Growth",
            "💪 Quality",
            "💵 Price Performance",
        ])

        # ── TAB 1 · Valuation ─────────────────────────────────────────
        with _tab_val:
            st.plotly_chart(
                _build_valuation_chart(result_list),
                use_container_width = True,
                config = {"displayModeBar": False},
            )
            st.html("""
<div style="font-size:11px;color:#94A3B8;line-height:1.7;margin-top:-6px;">
  <strong>P/E</strong> — price ÷ earnings &nbsp;·&nbsp;
  <strong>P/B</strong> — price ÷ book value &nbsp;·&nbsp;
  <strong>EV/EBITDA</strong> — enterprise value ÷ EBITDA &nbsp;·&nbsp;
  <strong>P/FCF</strong> — price ÷ free cash flow per share.
  Lower multiples = cheaper (for the same quality).
</div>""")

        # ── TAB 2 · Growth ────────────────────────────────────────────
        with _tab_gr:
            st.plotly_chart(
                _build_growth_chart(result_list),
                use_container_width = True,
                config = {"displayModeBar": False},
            )
            # Side-by-side current growth metrics
            st.html("""
<div style="font-size:11px;font-weight:700;color:#94A3B8;
            text-transform:uppercase;letter-spacing:0.1em;
            margin:12px 0 8px;">Current Growth Rates (TTM)</div>""")
            _gr_cols = st.columns(len(result_list))
            for _ci, _r in enumerate(result_list):
                _color = _PALETTE[_ci % len(_PALETTE)]
                with _gr_cols[_ci]:
                    _fcf_g = _r.get('fcf_growth', 0)
                    themed_metric(
                        label=_r["ticker"],
                        value=f"{_r.get('revenue_growth', 0):+.1f}% Rev",
                        delta=f"{_fcf_g:+.1f}% FCF",
                        delta_positive=(_fcf_g >= 0),
                        theme_name=st.session_state.get("theme", "slate"),
                    )

        # ── TAB 3 · Quality ───────────────────────────────────────────
        with _tab_qu:
            _qcol1, _qcol2 = st.columns(2, gap="large")
            with _qcol1:
                st.plotly_chart(
                    _build_quality_radar(result_list),
                    use_container_width = True,
                    config = {"displayModeBar": False},
                )
                st.html("""
<div style="font-size:11px;color:#94A3B8;text-align:center;line-height:1.7;">
  Each axis normalized 0–100.
  <strong>Liquidity</strong> = Current Ratio &nbsp;·&nbsp;
  <strong>Low Leverage</strong> = inverted D/E (higher = less debt)
</div>""")
            with _qcol2:
                st.plotly_chart(
                    _build_radar(result_list),
                    use_container_width = True,
                    config = {"displayModeBar": False},
                )
                st.html("""
<div style="font-size:11px;color:#8b949e;text-align:center;line-height:1.7;">
  Investment radar: Value · Quality · Growth · Moat · EQ · Profitability
</div>""")

        # ── TAB 4 · Price Performance ─────────────────────────────────
        with _tab_px:
            _period = st.radio(
                "Period",
                options    = ["1mo", "3mo", "6mo", "1y"],
                index      = 3,
                horizontal = True,
                key        = "_cmp_period",
                label_visibility = "collapsed",
            )
            st.plotly_chart(
                _build_price_chart(result_list, _period),
                use_container_width = True,
                config = {"displayModeBar": False},
            )
            st.html("""
<div style="font-size:11px;color:#94A3B8;line-height:1.7;margin-top:-6px;">
  All prices rebased to 100 at the start of the period.
  S&P 500 (SPY) shown as a dashed grey benchmark.
</div>""")

        # ── Full Comparison Summary ───────────────────────────────────
        st.markdown("---")
        ccard("Full Comparison Summary", "#1D4ED8")
        st.html("""
<div style="font-size:11px;color:#94A3B8;margin-bottom:10px;">
  <span style="display:inline-block;width:10px;height:10px;
        background:#ECFDF5;border:1px solid #059669;
        border-radius:2px;vertical-align:middle;margin-right:4px;"></span>Best value
  &nbsp;
  <span style="display:inline-block;width:10px;height:10px;
        background:#FEF2F2;border:1px solid #DC2626;
        border-radius:2px;vertical-align:middle;margin-right:4px;"></span>Worst value
</div>""")
        st.html(_build_table(result_list))
        ccard_end()

        # ── Exportable dataframe ──────────────────────────────────────
        with st.expander("📊 Export-friendly table"):
            df_summary = _build_summary_df(result_list)
            st.dataframe(
                df_summary,
                column_config = {
                    "ticker":    st.column_config.TextColumn("Ticker",      width="small"),
                    "company":   st.column_config.TextColumn("Company",     width="medium"),
                    "signal":    st.column_config.TextColumn("Signal",      width="small"),
                    "mos_pct":   st.column_config.NumberColumn(
                                     "MoS %",    format="%.1f%%",  width="small"),
                    "price":     st.column_config.NumberColumn(
                                     "Price",    format="$%.2f",   width="small"),
                    "iv":        st.column_config.NumberColumn(
                                     "Fair Value", format="$%.2f", width="small"),
                    "pe":        st.column_config.NumberColumn(
                                     "P/E",      format="%.1fx",   width="small"),
                    "pb":        st.column_config.NumberColumn(
                                     "P/B",      format="%.1fx",   width="small"),
                    "ev_ebitda": st.column_config.NumberColumn(
                                     "EV/EBITDA",format="%.1fx",   width="small"),
                    "roe":       st.column_config.NumberColumn(
                                     "ROE %",    format="%.1f%%",  width="small"),
                    "op_margin": st.column_config.NumberColumn(
                                     "Op Margin",format="%.1f%%",  width="small"),
                    "rev_growth":st.column_config.NumberColumn(
                                     "Rev Growth",format="%.1f%%", width="small"),
                    "piotroski": st.column_config.NumberColumn(
                                     "Piotroski",format="%.0f/9",  width="small"),
                    "moat":      st.column_config.TextColumn("Moat",        width="small"),
                },
                hide_index          = True,
                use_container_width = True,
            )


# ══════════════════════════════════════════════════════════════
# EMPTY STATE
# ══════════════════════════════════════════════════════════════

def _render_empty_state() -> None:
    st.html("""
<div style="text-align:center;padding:64px 32px;max-width:480px;margin:0 auto;">
  <div style="font-size:40px;margin-bottom:16px;">⚖️</div>
  <div style="font-size:20px;font-weight:700;color:#0F172A;
              font-family:Inter,sans-serif;margin-bottom:10px;">
    Compare any stocks side by side
  </div>
  <div style="font-size:14px;color:#64748B;font-family:Inter,sans-serif;
              line-height:1.7;">
    Enter 2–4 ticker symbols above and click <strong>Compare →</strong>
    to see Valuation, Growth, Quality, and Price Performance charts
    along with a full metrics breakdown.
  </div>
</div>""")
