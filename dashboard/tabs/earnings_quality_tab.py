# dashboard/tabs/earnings_quality_tab.py
# ═══════════════════════════════════════════════════════════════
# Earnings Quality tab — Piotroski F-Score + Earnings Quality.
# Extracted from app.py  with _sub_ql:  block.
# Entry point: render(enriched)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
from screener.piotroski import compute_piotroski_fscore as _piotroski_raw
from screener.earnings_quality import compute_earnings_quality
from tab_helpers import ccard, ccard_end, render_score_dial


def render(enriched: dict) -> None:
    """Render the Business Health / Earnings Quality sub-tab."""
    if not enriched:
        st.warning("Business health data unavailable for this ticker.")
        return

    # Compute both scores upfront.
    # _piotroski_raw expects a plain dict — enriched is passed as-is (not JSON-serialised).
    _pf_ok = False; _eq_ok = False
    _pf_err = None; _eq_err = None
    try:
        pf        = _piotroski_raw(enriched)
        pf_score  = pf["score"]
        pf_grade  = pf["grade"]
        pf_cats   = pf["category_scores"]
        pf_sigs   = pf["signals"]
        _pf_ok    = True
    except Exception as _e:
        _pf_err = _e  # save before Python 3 deletes the as-bound name
        pf_score=0; pf_grade="N/A"; pf_cats={}; pf_sigs=[]
        pf={"summary":"","academic_note":""}
    try:
        eq        = compute_earnings_quality(enriched)
        eq_score  = eq["score"]
        eq_grade  = eq["grade"]
        eq_cats   = eq["category_scores"]
        eq_facts  = eq["factors"]
        _eq_ok    = True
    except Exception as _e:
        _eq_err = _e  # save before Python 3 deletes the as-bound name
        eq_score=0; eq_grade="N/A"; eq_cats={}; eq_facts=[]
        eq={"summary":"","red_flags":[],"green_flags":[],"academic_note":""}

    # ── DUAL DIAL HEADER ─────────────────────────────────
    ccard("Business Quality Score", "#7c3aed")
    _pf_clr = "#10b981" if pf_score>=6 else "#f59e0b" if pf_score>=4 else "#ef4444"
    _eq_clr = "#10b981" if eq_score>=70 else "#f59e0b" if eq_score>=50 else "#ef4444"
    _cg = ("Strong Quality" if pf_score>=6 and eq_score>=70 else
           "Good Quality"   if pf_score>=5 and eq_score>=55 else
           "Average"        if pf_score>=3 and eq_score>=40 else "Weak Quality")
    _cc = ("#10b981" if "Strong" in _cg else "#3b82f6" if "Good" in _cg
           else "#f59e0b" if "Average" in _cg else "#ef4444")
    _d1, _d2, _d3 = st.columns([1,1,3])
    with _d1:
        st.html('<div style="text-align:center;padding:16px 8px;">'
                + render_score_dial(pf_score, 9, "Business Health", _pf_clr, 130)
                + '</div>')
        if pf_score >= 8:
            st.caption("Top-tier quality — strong across nearly all 9 metrics")
        elif pf_score >= 6:
            st.caption("Above-average business quality")
        elif pf_score >= 4:
            st.caption("Mixed signals — review individual components")
        else:
            st.caption("Below-average on Piotroski financial health criteria")
    with _d2:
        st.html('<div style="text-align:center;padding:16px 8px;">'
                + render_score_dial(eq_score, 100, "Earnings Quality", _eq_clr, 130)
                + '</div>')
    with _d3:
        _vtxt = (pf.get("summary","")[:200] if _pf_ok
                 else eq.get("summary","")[:200])
        st.html(
            '<div style="padding:20px 22px;background:#161b22;border-radius:10px;'
            'border-left:4px solid ' + _cc + ';min-height:140px;'
            'display:flex;flex-direction:column;justify-content:center;">'
            '<div style="font-size:11px;font-weight:700;color:' + _cc + ';'
            'text-transform:uppercase;letter-spacing:0.12em;margin-bottom:6px;">'
            'Overall Verdict</div>'
            '<div style="font-size:20px;font-weight:800;color:' + _cc + ';'
            'margin-bottom:10px;letter-spacing:-0.01em;">' + _cg + '</div>'
            '<div style="font-size:13px;color:#8b949e;line-height:1.75;">'
            + _vtxt + '</div></div>'
        )

    # ── Piotroski category bars ───────────────────────────
    st.html('<div style="margin-top:20px;margin-bottom:10px;font-size:11px;'
            'font-weight:700;color:#8b949e;text-transform:uppercase;'
            'letter-spacing:0.12em;">Piotroski Category Scores</div>')
    _pb1, _pb2, _pb3 = st.columns(3)
    for _col, _lbl, _sc, _mx, _clr in [
        (_pb1, "Profitability",        pf_cats.get("Profitability",0), 4, "#10b981"),
        (_pb2, "Leverage & Liquidity", pf_cats.get("Leverage",0),      3, "#3b82f6"),
        (_pb3, "Operating Efficiency", pf_cats.get("Efficiency",0),    2, "#f59e0b"),
    ]:
        _pct = int(_sc / _mx * 100) if _mx else 0
        _col.html(
            '<div style="padding:14px 16px;background:#161b22;'
            'border:1px solid #21262d;border-radius:10px;">'
            '<div style="font-size:10px;font-weight:700;color:#8b949e;'
            'text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;">'
            + _lbl + '</div>'
            '<div style="font-size:26px;font-weight:800;color:' + _clr + ';'
            'font-family:IBM Plex Mono,monospace;margin-bottom:8px;">'
            + str(_sc) + '/' + str(_mx) + '</div>'
            '<div style="height:5px;background:#21262d;border-radius:3px;">'
            '<div style="height:100%;width:' + str(_pct) + '%;background:' + _clr + ';'
            'border-radius:3px;"></div></div></div>'
        )

    # ── 3×3 signal grid (no expanders) ───────────────────
    st.html('<div style="margin-top:20px;margin-bottom:10px;font-size:11px;'
            'font-weight:700;color:#8b949e;text-transform:uppercase;'
            'letter-spacing:0.12em;">9-Point Signal Breakdown</div>')
    if pf_sigs:
        _cells = ""
        for _sig in pf_sigs:
            _ok   = _sig.get("pass", False)
            _bg   = "#022c1d" if _ok else "#2d0606"
            _bdr  = "#10b981" if _ok else "#ef4444"
            _tc   = "#10b981" if _ok else "#ef4444"
            _ic   = "✅" if _ok else "❌"
            _key  = str(_sig.get("key","")).upper()
            _lbl2 = _sig.get("label","")
            _det  = _sig.get("detail","")
            _sc2  = _sig.get("score",0)
            _cells += (
                '<div style="padding:14px 14px 12px;background:' + _bg + ';'
                'border:1px solid ' + _bdr + '33;border-radius:10px;'
                'border-top:2px solid ' + _bdr + ';position:relative;">'
                '<div style="position:absolute;top:10px;right:12px;font-size:14px;">'
                + _ic + '</div>'
                '<div style="font-size:9px;font-weight:700;color:' + _tc + ';'
                'text-transform:uppercase;letter-spacing:0.15em;margin-bottom:4px;'
                'font-family:IBM Plex Mono,monospace;">' + _key + '</div>'
                '<div style="font-size:12px;font-weight:600;color:#e6edf3;'
                'margin-bottom:5px;padding-right:22px;">' + _lbl2 + '</div>'
                '<div style="font-size:11px;color:#8b949e;line-height:1.5;'
                'margin-bottom:8px;">' + _det + '</div>'
                '<div style="font-family:IBM Plex Mono,monospace;font-size:11px;'
                'font-weight:700;color:' + _tc + ';background:' + _bdr + '18;'
                'border:1px solid ' + _bdr + '33;border-radius:4px;'
                'padding:2px 8px;display:inline-block;">Score: ' + str(_sc2) + '</div>'
                '</div>'
            )
        st.html('<div style="display:grid;grid-template-columns:1fr 1fr 1fr;'
                'gap:10px;margin-bottom:12px;">' + _cells + '</div>')
    else:
        st.warning("Business health data unavailable for this ticker.")
    if _pf_ok:
        st.caption("📚 " + pf.get("academic_note",""))
    ccard_end()

    # ── EARNINGS QUALITY — dark-themed ────────────────────
    ccard("Are the company's profits backed by real cash?", "#0f766e")
    if not _eq_ok:
        st.warning("Earnings quality could not run: " + str(_eq_err))
    st.html(
        '<div style="display:flex;align-items:center;gap:20px;'
        'padding:18px 20px;background:#161b22;'
        'border:1.5px solid ' + _eq_clr + '33;'
        'border-radius:12px;margin-bottom:16px;">'
        '<div style="text-align:center;min-width:90px;">'
        + render_score_dial(eq_score, 100, "", _eq_clr, 100)
        + '</div><div style="width:1px;height:80px;background:#21262d"></div>'
        '<div style="flex:1">'
        '<div style="font-size:16px;font-weight:700;color:' + _eq_clr + ';'
        'margin-bottom:6px;">' + eq_grade + '</div>'
        '<div style="font-size:13px;color:#8b949e;line-height:1.7;">'
        + eq.get("summary","") + '</div></div></div>'
    )
    _cat_order = ["Cash Conversion","Earnings Stability","Balance Sheet","Growth Quality"]
    _cat_icons = {"Cash Conversion":"💵","Earnings Stability":"📊",
                  "Balance Sheet":"🏦","Growth Quality":"📈"}
    if eq_cats:
        _cat_cols  = st.columns(len(_cat_order))
        for _col, _cat in zip(_cat_cols, _cat_order):
            _val = eq_cats.get(_cat, 50)
            _vc  = "#10b981" if _val>=70 else "#f59e0b" if _val>=50 else "#ef4444"
            _col.html(
                '<div style="padding:12px 14px;background:#161b22;'
                'border:1px solid #21262d;border-radius:10px;text-align:center;">'
                '<div style="font-size:18px">' + _cat_icons.get(_cat,"📌") + '</div>'
                '<div style="font-size:10px;font-weight:700;color:#8b949e;'
                'text-transform:uppercase;letter-spacing:.07em;margin:4px 0;">'
                + _cat + '</div>'
                '<div style="font-size:22px;font-weight:800;color:' + _vc + ';'
                'font-family:IBM Plex Mono,monospace;">' + f"{_val:.0f}" + '</div>'
                '<div style="height:4px;background:#21262d;border-radius:2px;margin-top:6px;">'
                '<div style="height:100%;width:' + f"{_val:.0f}" + '%;background:' + _vc + ';'
                'border-radius:2px;"></div></div></div>'
            )
    if eq_facts:
        st.html('<div style="margin-top:16px;margin-bottom:8px;font-size:11px;'
                'font-weight:700;color:#8b949e;text-transform:uppercase;'
                'letter-spacing:.1em;">9-Factor Breakdown</div>')
        for _cat in _cat_order:
            _cf    = [f for f in eq_facts if f["category"]==_cat]
            _cv    = eq_cats.get(_cat,50)
            _clbl  = ("Excellent" if _cv>=85 else "Good" if _cv>=70
                      else "Moderate" if _cv>=50 else "Weak")
            with st.expander(f"{_cat}  —  {_cv:.0f}/100 ({_clbl})", expanded=(_cv<50)):
                for _f in _cf:
                    _fc = "#10b981" if _f["score"]>=70 else "#f59e0b" if _f["score"]>=50 else "#ef4444"
                    st.html(
                        '<div style="padding:10px 14px;background:#161b22;'
                        'border:1px solid #21262d;border-radius:8px;margin-bottom:6px;">'
                        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
                        '<div style="font-size:11px;font-weight:700;color:#8b949e;'
                        'text-transform:uppercase;width:22px;">' + _f["key"].upper() + '</div>'
                        '<div style="flex:1;font-size:13px;font-weight:600;color:#e6edf3;">'
                        + _f["label"] + '</div>'
                        '<div style="font-size:13px;font-weight:800;color:' + _fc + ';'
                        'font-family:IBM Plex Mono,monospace;min-width:36px;text-align:right;">'
                        + f"{_f['score']:.0f}" + '</div></div>'
                        '<div style="height:4px;background:#21262d;border-radius:2px;margin-bottom:6px;">'
                        '<div style="height:100%;width:' + f"{_f['score']:.0f}" + '%;background:' + _fc + ';'
                        'border-radius:2px;"></div></div>'
                        '<div style="font-size:12px;color:#8b949e;">' + _f["detail"] + '</div>'
                        '</div>'
                    )
    if eq.get("red_flags"):
        st.html('<div style="padding:10px 14px;background:#2d0606;'
                'border:1px solid #ef444433;border-radius:8px;'
                'font-size:12px;color:#ef4444;margin-top:8px;">'
                '⚠️ <strong>Red flags:</strong> ' + " · ".join(eq["red_flags"]) + '</div>')
    if eq.get("green_flags"):
        st.html('<div style="padding:10px 14px;background:#022c1d;'
                'border:1px solid #10b98133;border-radius:8px;'
                'font-size:12px;color:#10b981;margin-top:6px;">'
                '✅ <strong>Strengths:</strong> ' + " · ".join(eq["green_flags"]) + '</div>')
    if eq.get("academic_note"):
        st.caption("📚 " + eq.get("academic_note",""))
    ccard_end()

    # ══════════════════════════════════════════════════════════
    # EARNINGS TRACK RECORD
    # ══════════════════════════════════════════════════════════
    ccard("📊 Earnings Track Record — EPS vs Analyst Estimates", "#0f4c5c")

    _etr = enriched.get("earnings_track_record", {})

    if not _etr or _etr.get("num_quarters", 0) < 2:
        st.info("Earnings surprise data unavailable — requires Finnhub API key with market data access.")
        ccard_end()
        return

    _br       = _etr.get("beat_rate", 0)
    _avg_surp = _etr.get("avg_surprise_pct", 0)
    _trend    = _etr.get("trend", "Mixed")
    _n_q      = _etr.get("num_quarters", 0)
    _periods  = _etr.get("periods", [])
    _actuals  = _etr.get("actuals", [])
    _ests     = _etr.get("estimates", [])
    _surps    = _etr.get("surprises_pct", [])
    _beats    = _etr.get("beats", [])

    # ── Badge row ─────────────────────────────────────────────
    _TREND_CFG = {
        "Accelerating Beats": ("#065F46", "#D1FAE5", "🚀"),
        "Mixed":              ("#1E3A5F", "#DBEAFE", "〰️"),
        "Decelerating":       ("#92400E", "#FEF3C7", "📉"),
        "Consistent Misses":  ("#7F1D1D", "#FEE2E2", "🔴"),
    }
    _tr_fg, _tr_bg, _tr_ico = _TREND_CFG.get(_trend, ("#374151", "#F3F4F6", "—"))
    _br_pct   = _br * 100
    _br_color = "#059669" if _br >= 0.75 else "#D97706" if _br >= 0.50 else "#DC2626"
    _surp_sign = "+" if _avg_surp >= 0 else ""

    st.html(f"""
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;
                margin-bottom:16px;">
      <div style="background:{'#D1FAE5' if _br >= 0.75 else '#FEF3C7' if _br >= 0.50 else '#FEE2E2'};
                  color:{_br_color};font-size:22px;font-weight:800;
                  padding:10px 20px;border-radius:12px;font-family:'IBM Plex Mono',monospace;">
        {_br_pct:.0f}%
        <span style="font-size:13px;font-weight:600;margin-left:6px;">Beat Rate</span>
      </div>
      <div style="background:{_tr_bg};color:{_tr_fg};font-size:13px;font-weight:700;
                  padding:8px 16px;border-radius:20px;">
        {_tr_ico} {_trend}
      </div>
      <div style="font-size:13px;color:#475569;">
        Avg surprise: <b style="color:{'#059669' if _avg_surp >= 0 else '#DC2626'};">
          {_surp_sign}{_avg_surp:.1f}%
        </b>
        &nbsp;·&nbsp; {_n_q} quarters analysed
      </div>
    </div>
    """)

    # ── EPS Actual vs Estimate bar chart ──────────────────────
    if _periods and _actuals and _ests:
        # Short-form period labels for readability
        _xlabels = [p[-7:] if len(p) > 7 else p for p in _periods]

        _bar_colors = ["#059669" if b else "#DC2626" for b in _beats]

        _fig = go.Figure()
        _fig.add_trace(go.Bar(
            name="Estimate",
            x=_xlabels,
            y=_ests,
            marker_color="#CBD5E1",
            opacity=0.85,
            text=[f"${e:.2f}" for e in _ests],
            textposition="outside",
            textfont=dict(size=9, color="#64748B"),
        ))
        _fig.add_trace(go.Bar(
            name="Actual EPS",
            x=_xlabels,
            y=_actuals,
            marker_color=_bar_colors,
            opacity=0.90,
            text=[f"${a:.2f}" for a in _actuals],
            textposition="outside",
            textfont=dict(size=9),
        ))
        # Surprise % as scatter on secondary axis
        if _surps:
            _fig.add_trace(go.Scatter(
                name="Surprise %",
                x=_xlabels,
                y=_surps,
                mode="lines+markers",
                marker=dict(
                    size=8,
                    color=["#059669" if s >= 0 else "#DC2626" for s in _surps],
                    line=dict(width=1, color="#FFF"),
                ),
                line=dict(color="#7C3AED", width=1.5, dash="dot"),
                yaxis="y2",
            ))

        _fig.update_layout(
            barmode="group",
            height=320,
            margin=dict(t=30, b=40, l=50, r=60),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", y=-0.20, x=0),
            yaxis=dict(
                title="EPS ($)",
                gridcolor="rgba(0,0,0,0.04)",
                zeroline=True,
                zerolinecolor="#CBD5E1",
            ),
            yaxis2=dict(
                title="Surprise %",
                overlaying="y",
                side="right",
                showgrid=False,
                ticksuffix="%",
                zeroline=True,
                zerolinecolor="#CBD5E1",
            ),
            xaxis=dict(gridcolor="rgba(0,0,0,0.04)", title="Quarter"),
            shapes=[dict(
                type="line", y0=0, y1=0, x0=0, x1=1,
                xref="paper", yref="y",
                line=dict(color="#94A3B8", width=1),
            )],
        )
        # Annotate beats/misses
        for i, (b, s) in enumerate(zip(_beats, _surps)):
            _fig.add_annotation(
                x=_xlabels[i], y=max(_actuals[i], _ests[i]) if _actuals and _ests else 0,
                text="✓" if b else "✗",
                showarrow=False,
                font=dict(size=14, color="#059669" if b else "#DC2626"),
                yshift=18,
            )
        st.plotly_chart(_fig, width='stretch')

    # ── Summary insight ───────────────────────────────────────
    _insight = (
        f"Management has beaten consensus estimates {_br_pct:.0f}% of the time over the last {_n_q} quarters, "
        f"with an average EPS surprise of {_surp_sign}{_avg_surp:.1f}%. "
        f"The trend is <b>{_trend.lower()}</b>."
    )
    if _trend == "Accelerating Beats":
        _insight += " This accelerating pattern signals improving earnings visibility and management credibility."
    elif _trend == "Consistent Misses":
        _insight += " Consistent misses may indicate guidance is too optimistic or business conditions are deteriorating."
    elif _trend == "Decelerating":
        _insight += " The decelerating pattern warrants monitoring — earnings may be becoming less predictable."

    st.html(f"""
    <div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;
                padding:10px 16px;font-size:13px;color:#0F172A;line-height:1.7;
                margin-top:4px;">
      📋 {_insight}
    </div>
    """)

    ccard_end()
