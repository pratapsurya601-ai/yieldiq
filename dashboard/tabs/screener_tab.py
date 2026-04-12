"""dashboard/tabs/screener_tab.py
Tab 3 — Screener Results.
Moved from app.py.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from ui.helpers import ccard, ccard_end, apply_koyfin
import importlib.util as _ilu, pathlib as _pl
_dh_path = _pl.Path(__file__).resolve().parent.parent / "utils" / "data_helpers.py"
_dh_spec = _ilu.spec_from_file_location("_yiq_dh", _dh_path)
_dh_mod  = _ilu.module_from_spec(_dh_spec); _dh_spec.loader.exec_module(_dh_mod)
CURRENCIES = _dh_mod.CURRENCIES; show_upgrade_modal = _dh_mod.show_upgrade_modal

_cfg_path = _pl.Path(__file__).resolve().parent.parent.parent / "utils" / "config.py"
_cfg_spec = _ilu.spec_from_file_location("_yiq_cfg", _cfg_path)
_cfg_mod  = _ilu.module_from_spec(_cfg_spec); _cfg_spec.loader.exec_module(_cfg_mod)
RESULTS_PATH = _cfg_mod.RESULTS_PATH; LAUNCH_REGION = _cfg_mod.LAUNCH_REGION
from tier_gate import can_run_screener, record_screener, tier
try:
    from admin_analytics import track_event
except Exception:
    def track_event(*a, **kw): pass


def render() -> None:
    """Render the Screener tab."""
    _cur = st.session_state.get("sb_currency", "USD")
    sym  = CURRENCIES[_cur]["symbol"]

    _screener_ok, _screener_reason = can_run_screener()
    if not _screener_ok:
        st.html("<br>")
        show_upgrade_modal("Batch stock screener")
        st.html("""
        <div style="margin-top:16px;padding:16px 20px;background:#f8fafc;
                    border:1px solid #e2e8f0;border-radius:10px;font-size:13px;color:#4a5568;">
          <strong>What the screener does:</strong> Runs our DCF model on 6,000+ stocks
          and 2,270+ Indian stocks — ranked by margin of safety. Updated nightly.
        </div>""")
    else:
        df_screen = None
        results_file = st.session_state.get("results_file", None)
        if results_file is not None:
            df_screen = pd.read_csv(results_file)
        else:
            try:
                df_screen = pd.read_csv(RESULTS_PATH)
            except FileNotFoundError:
                st.info("No screener results found yet — run the screener above to generate them.")
        record_screener()
        track_event(st.session_state.get("auth_email",""), tier(), "screener_run")

    if _screener_ok and (df_screen is None or df_screen.empty):
        _, _ec, _ = st.columns([1, 3, 1])
        with _ec:
            st.html("""
            <div style="margin-top:60px;padding:56px 48px;
                        background:linear-gradient(135deg,#0d1117,#161b22);
                        border:1px solid #21262d;border-radius:16px;text-align:center;">
              <div style="font-size:48px;margin-bottom:16px;">&#128269;</div>
              <div style="font-size:22px;font-weight:700;color:#e6edf3;margin-bottom:12px;">
                Run your first screen</div>
              <div style="font-size:14px;color:#8b949e;max-width:480px;
                          margin:0 auto 28px;line-height:1.7;">
                Find undervalued stocks across US and Indian markets using
                institutional DCF methodology &#8212; 2,800+ stocks ranked by model estimate.
              </div>
              <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;
                          padding:10px 20px;display:inline-block;">
                <code style="color:#00b4d8;font-size:12px;font-family:'IBM Plex Mono',monospace;">
                  python batch/nightly_precompute.py
                </code>
              </div>
            </div>""")

    elif _screener_ok and df_screen is not None and not df_screen.empty:
        # ── Batch run metadata banner ─────────────────────────
        try:
            import json as _json
            _status_path = Path("data/last_batch_run.json")
            if _status_path.exists():
                _bst = _json.loads(_status_path.read_text())
                _bts = _bst.get("timestamp", "")[:16].replace("T", " ")
                _bcomp = _bst.get("completed", "—")
                _bdur  = _bst.get("duration_min", "—")
                _bpick = _bst.get("top_pick", "—")
                st.html(f"""
                <div style="display:flex;align-items:center;gap:24px;padding:10px 16px;
                            background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;
                            margin-bottom:12px;font-size:12px;color:#0369A1;">
                  <span>🕒 Last updated: <strong>{_bts}</strong></span>
                  <span>📊 Stocks analysed: <strong>{_bcomp:,}</strong></span>
                  <span>⏱ Runtime: <strong>{_bdur} min</strong></span>
                  <span>🏆 Top pick: <strong>{_bpick}</strong></span>
                </div>""")
        except Exception:
            pass
        _sc_clean = df_screen[~df_screen["signal"].astype(str).str.contains("Data Limited|N/A", na=False)]
        _sc_total = len(df_screen)
        _sc_buys  = len(_sc_clean[_sc_clean["signal"].astype(str).str.contains("Undervalued",    na=False)])
        _sc_watch = len(_sc_clean[_sc_clean["signal"].astype(str).str.contains("Near Fair Value", na=False)])
        _sc_sells = len(_sc_clean[_sc_clean["signal"].astype(str).str.contains("Overvalued",      na=False)])
        _sc_na    = len(df_screen[df_screen["signal"].astype(str).str.contains("N/A|Data Limited", na=False)])
        _sc_best  = (_sc_clean.loc[_sc_clean["margin_of_safety"].idxmax(), "ticker"]
                     if not _sc_clean.empty else "—")

        _k1, _k2, _k3, _k4, _k5, _k6 = st.columns(6)
        _k1.metric("Total",       _sc_total)
        _k2.metric("Undervalued", _sc_buys)
        _k3.metric("Discount",    _sc_watch)
        _k4.metric("Overvalued",  _sc_sells)
        _k5.metric("N/A",         _sc_na)
        _k6.metric("Top Pick",    _sc_best)

        st.caption(
            "⚠️ Screener results are model outputs only — not investment advice. "
            "Signals reflect DCF model estimates, not buy/sell recommendations. "
            "YieldIQ is not a registered investment adviser."
        )

        # ── Preset filter templates ───────────────────────────
        st.html("""<div style="font-size:11px;font-weight:600;color:#8b949e;
                    text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;">
                    Quick Presets</div>""")
        _pr1, _pr2, _pr3, _pr4 = st.columns(4)
        _PRESETS = {
            "🏆 Buffett Picks":    dict(sc_mos=20, sc_qual=60, sc_sig=["Undervalued 🟢"],            sc_sort="fundamental_score"),
            "🚀 Growth at Value":  dict(sc_mos=10, sc_qual=50, sc_sig=["Undervalued 🟢","Near Fair Value 🟡"], sc_sort="revenue_growth"),
            "💰 Deep Value":       dict(sc_mos=30, sc_qual=0,  sc_sig=["Undervalued 🟢"],            sc_sort="margin_of_safety"),
            "💎 Dividend Quality": dict(sc_mos=0,  sc_qual=55, sc_sig=["Undervalued 🟢","Near Fair Value 🟡","Fairly Valued 🔵"], sc_sort="fundamental_score"),
        }
        for _pcol, (_plabel, _pvals) in zip([_pr1, _pr2, _pr3, _pr4], _PRESETS.items()):
            with _pcol:
                if st.button(_plabel, key=f"preset_{_plabel}", width="stretch"):
                    for _pk, _pv in _pvals.items():
                        st.session_state[_pk] = _pv
                    st.rerun()

        # ── Filter bar
        st.html("""<div style="background:#161b22;border:1px solid #21262d;border-radius:10px;
                    padding:10px 14px;margin:10px 0 12px;">
          <span style="font-size:11px;font-weight:600;color:#8b949e;
                       text-transform:uppercase;letter-spacing:.1em;">Filters</span></div>""")

        _fb1, _fb2, _fb3, _fb4 = st.columns(4)
        with _fb1:
            if LAUNCH_REGION == "US":
                _mkt_sel = "US Only"   # locked — no market picker shown
                st.caption("🇺🇸 US markets")
            else:
                _mkt_sel = st.selectbox("Market", ["All Markets", "US Only", "India Only"], key="sc_mkt")
        with _fb2:
            _sig_filter = st.multiselect("Signal",
                ["Undervalued 🟢","Near Fair Value 🟡","Fairly Valued 🔵","Overvalued 🔴"],
                default=["Undervalued 🟢","Near Fair Value 🟡"], key="sc_sig")
        with _fb3:
            _sectors = ["All Sectors"]
            if "sector" in df_screen.columns:
                _sectors += sorted(df_screen["sector"].dropna().unique().tolist())
            _sec_sel = st.selectbox("Sector", _sectors, key="sc_sec")
        with _fb4:
            _sort_col = st.selectbox("Sort by",
                ["margin_of_safety","fundamental_score","rr_ratio","price"], key="sc_sort")

        _fb5, _fb6, _ = st.columns([2,2,2])
        with _fb5:
            _min_mos  = st.slider("Min MoS (%)", -50, 100, 0, key="sc_mos")
        with _fb6:
            _min_qual = st.slider("Min Quality", 0, 100, 0, key="sc_qual")

        # Apply filters
        _filtered = df_screen[~df_screen["signal"].astype(str).str.contains("CHECK|N/A", na=False)].copy()
        _filtered = _filtered[_filtered["margin_of_safety"] >= _min_mos]
        if _min_qual > 0 and "fundamental_score" in _filtered.columns:
            _filtered = _filtered[_filtered["fundamental_score"] >= _min_qual]
        if _sig_filter:
            _filtered = _filtered[_filtered["signal"].isin(_sig_filter)]
        if _mkt_sel == "US Only":
            _filtered = _filtered[~_filtered["ticker"].astype(str).str.endswith((".NS",".BO"))]
        elif _mkt_sel == "India Only":
            _filtered = _filtered[_filtered["ticker"].astype(str).str.endswith((".NS",".BO"))]
        if _sec_sel != "All Sectors" and "sector" in _filtered.columns:
            _filtered = _filtered[_filtered["sector"] == _sec_sel]
        if _sort_col in _filtered.columns:
            _filtered = _filtered.sort_values(_sort_col, ascending=False).reset_index(drop=True)

        _result_count = len(_filtered)
        _result_color = "#e6edf3" if _result_count > 0 else "#ef4444"
        st.html('<div style="font-size:12px;color:#8b949e;margin-bottom:6px;">Showing <strong style="color:'
                + _result_color + ';">' + str(_result_count) + '</strong> of ' + str(_sc_total) + ' stocks</div>')

        if _result_count == 0:
            st.html("""
            <div style="padding:28px;background:#161b22;border:1px solid #21262d;border-radius:10px;
                        text-align:center;margin:10px 0;">
              <div style="font-size:28px;margin-bottom:8px;">🔍</div>
              <div style="font-size:14px;font-weight:600;color:#e6edf3;margin-bottom:6px;">
                No stocks match these filters</div>
              <div style="font-size:12px;color:#8b949e;">Try loosening the Min MoS or Min Quality sliders,
                or select more signal types.</div>
            </div>
            """)

        # ── Styled HTML table
        _display_cols = ["ticker","price","intrinsic_value","margin_of_safety",
                         "signal","fundamental_grade","fundamental_score",
                         "revenue_growth","op_margin","rr_ratio"]
        _show_cols = [c for c in _display_cols if c in _filtered.columns]
        _col_labels = {"ticker":"Ticker","price":"Price","intrinsic_value":"Fair Value",
                       "margin_of_safety":"Discount","signal":"Signal","fundamental_grade":"Grade",
                       "fundamental_score":"Quality","revenue_growth":"Rev Gr","op_margin":"Margin",
                       "rr_ratio":"R/R"}
        _SIG_META = {"Undervalued 🟢":("#185FA5","#0a1e3d"),"Near Fair Value 🟡":("#B45309","#2d1f05"),
                     "Fairly Valued 🔵":("#475569","#1a1f27"),"Overvalued 🔴":("#B45309","#2d1f05")}

        def _badge(s):
            fg,bg = _SIG_META.get(str(s), ("#475569","#161b22"))
            lbl = str(s).split()[0] if s else "—"
            return ('<span style="background:' + bg + ';color:' + fg + ';border:1px solid ' + fg
                    + '66;font-size:10px;font-weight:700;padding:2px 8px;border-radius:12px;">'
                    + lbl + '</span>')

        def _bar(v):
            try: v = float(v)
            except (TypeError, ValueError): return "—"
            clr = "#10b981" if v>20 else "#f59e0b" if v>0 else "#ef4444"
            pct = min(max(int(abs(v)),2),100)
            sign = "+" if v>=0 else ""
            return ('<div style="display:flex;align-items:center;gap:5px;">'
                    '<div style="width:48px;height:5px;background:#21262d;border-radius:3px;flex-shrink:0;">'
                    '<div style="height:100%;width:' + str(pct) + '%;background:' + clr + ';border-radius:3px;"></div></div>'
                    '<span style="font-size:11px;color:' + clr + ';font-family:IBM Plex Mono,monospace;">'
                    + sign + '{:.1f}%'.format(v) + '</span></div>')

        def _ring(v):
            try: v = float(v)
            except (TypeError, ValueError): return "—"
            clr = "#10b981" if v>=70 else "#f59e0b" if v>=40 else "#ef4444"
            pct = int(v)
            return ('<div style="display:flex;align-items:center;gap:4px;">'
                    '<div style="width:20px;height:20px;border-radius:50%;flex-shrink:0;background:'
                    'conic-gradient(' + clr + ' ' + str(pct) + '%, #21262d ' + str(pct) + '%);">'
                    '</div><span style="font-size:11px;color:' + clr + ';font-family:IBM Plex Mono,monospace;">'
                    + str(pct) + '</span></div>')

        _th = "".join('<th style="padding:8px 12px;background:#0d1117;color:#8b949e;font-size:11px;'
                      'font-weight:600;text-transform:uppercase;letter-spacing:.08em;'
                      'border-bottom:2px solid #21262d;white-space:nowrap;'
                      'position:sticky;top:0;z-index:1;">'
                      + _col_labels.get(c, c) + '</th>' for c in _show_cols)

        _tb = ""
        for _ri, _row in _filtered.head(100).iterrows():
            _bg = "#0d1117" if _ri % 2 == 0 else "#0f1318"
            _row_cells = ""
            for _col in _show_cols:
                _v = _row.get(_col, "")
                if _col == "ticker":
                    _c = '<span style="color:#00b4d8;font-weight:700;font-family:IBM Plex Mono,monospace;font-size:12px;">' + str(_v) + '</span>'
                elif _col == "signal":    _c = _badge(_v)
                elif _col == "margin_of_safety": _c = _bar(_v)
                elif _col == "fundamental_score": _c = _ring(_v)
                elif _col in ("price","intrinsic_value"):
                    try: _c = '<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#e6edf3;">' + sym + '{:,.2f}'.format(float(_v)) + '</span>'
                    except (TypeError, ValueError): _c = str(_v)
                elif _col in ("revenue_growth","op_margin"):
                    try:
                        _fv = float(_v)*100 if abs(float(_v))<5 else float(_v)
                        _cc = "#10b981" if _fv>0 else "#ef4444"
                        _c = '<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:' + _cc + ';">' + '{:+.1f}%'.format(_fv) + '</span>'
                    except (TypeError, ValueError): _c = str(_v)
                elif _col == "rr_ratio":
                    try: _c = '<span style="font-family:IBM Plex Mono,monospace;font-size:11px;color:#8b949e;">' + '{:.1f}x'.format(float(_v)) + '</span>'
                    except (TypeError, ValueError): _c = str(_v)
                else:
                    _c = '<span style="font-size:11px;color:#8b949e;">' + str(_v) + '</span>'
                _row_cells += '<td style="padding:7px 12px;border-bottom:1px solid #161b22;background:' + _bg + ';">' + _c + '</td>'
            _tb += '<tr>' + _row_cells + '</tr>'

        st.html('<div style="overflow:auto;max-height:460px;border:1px solid #21262d;'
                'border-radius:10px;margin-bottom:14px;">'
                '<table style="width:100%;border-collapse:collapse;min-width:800px;">'
                '<thead><tr>' + _th + '</tr></thead>'
                '<tbody>' + _tb + '</tbody>'
                '</table></div>')

        # ── Top 15 chart
        ccard("Top 15 — highest model discount right now", "#10b981")
        _top15 = _filtered.head(15)
        if not _top15.empty:
            _bcolors = ["#10b981" if v>20 else "#f59e0b" if v>5 else "#3b82f6" if v>0 else "#ef4444"
                        for v in _top15["margin_of_safety"]]
            _fig_top = go.Figure(go.Bar(
                x=_top15["ticker"], y=_top15["margin_of_safety"],
                marker=dict(color=_bcolors, opacity=0.88, line=dict(width=0)),
                text=["{:.1f}%".format(v) for v in _top15["margin_of_safety"]],
                textposition="outside",
                textfont=dict(size=10, color="#8b949e", family="IBM Plex Mono"),
                hovertemplate="<b>%{x}</b><br>Discount: %{y:.1f}%<extra></extra>",
            ))
            apply_koyfin(_fig_top, height=300, extra_kw=dict(
                showlegend=False,
                yaxis=dict(title="Discount to model value (%)", gridcolor="#21262d",
                           tickfont=dict(color="#8b949e")),
                xaxis=dict(tickfont=dict(color="#e6edf3", size=11)),
                margin=dict(t=44, b=16, l=48, r=16),
            ))
            st.plotly_chart(_fig_top, width="stretch",
                config={"displayModeBar":True,"modeBarButtonsToRemove":["lasso2d","select2d"],
                        "toImageButtonOptions":{"filename":"screener_top15","scale":2}})
        ccard_end()

        st.caption(
            "⚠️ Model output only — not investment advice. "
            "YieldIQ is not a registered investment adviser. "
            "Past model performance does not predict future results."
        )

        # ── Export + Analyse top pick
        st.html('<div style="height:8px"></div>')
        _ex1, _ex2, _ex3 = st.columns(3)
        with _ex1:
            st.download_button("⬇️ Download filtered CSV",
                data=_filtered.to_csv(index=False).encode("utf-8"),
                file_name="screener_{}.csv".format(datetime.now().strftime("%Y%m%d")),
                mime="text/csv", width='stretch', type="primary")
        with _ex2:
            _buys_only = _filtered[_filtered["signal"].astype(str).str.contains("BUY", na=False)]
            st.download_button("🎯 BUY signals only",
                data=_buys_only.to_csv(index=False).encode("utf-8"),
                file_name="BUY_{}.csv".format(datetime.now().strftime("%Y%m%d")),
                mime="text/csv", width='stretch')
        with _ex3:
            if not _filtered.empty:
                if st.button("🚀 Analyse #1 ranked: " + str(_sc_best),
                             width='stretch', key="sc_analyse_top"):
                    st.session_state["_prefill_ticker"] = _sc_best
                    st.rerun()

