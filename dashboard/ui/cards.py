# dashboard/ui/cards.py
# Interactive HTML card components for YieldIQ.
# Works on clean Streamlit white background — no CSS fighting.

from __future__ import annotations
import streamlit as st


GLOBAL_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
.yiq-card {
  background:#fff;border:1px solid #E2E8F0;border-radius:12px;
  padding:16px;font-family:'Inter',-apple-system,sans-serif;
  transition:box-shadow 0.2s ease,transform 0.15s ease;
}
.yiq-card:hover {
  box-shadow:0 4px 20px rgba(0,0,0,0.08);transform:translateY(-1px);
}
.yiq-kpi-card {
  background:#fff;border:1px solid #E2E8F0;border-radius:10px;
  padding:12px 14px;font-family:'Inter',-apple-system,sans-serif;
  transition:all 0.2s ease;cursor:default;
}
.yiq-kpi-card:hover {border-color:#0F172A;box-shadow:0 2px 12px rgba(0,0,0,0.06);}
.yiq-grade-card {
  padding:14px 10px;text-align:center;border-right:1px solid #E2E8F0;
  font-family:'Inter',-apple-system,sans-serif;
  transition:background 0.2s ease;cursor:default;
}
.yiq-grade-card:hover {background:#F8FAFC!important;}
@keyframes countUp {
  from {opacity:0;transform:translateY(8px);}
  to {opacity:1;transform:translateY(0);}
}
.yiq-animate-in {animation:countUp 0.4s ease forwards;}
@keyframes pulse-ring {
  0% {box-shadow:0 0 0 0 rgba(0,0,0,0.15);}
  70% {box-shadow:0 0 0 8px rgba(0,0,0,0);}
  100% {box-shadow:0 0 0 0 rgba(0,0,0,0);}
}
.yiq-mos-pulse:hover {animation:pulse-ring 1s ease-out;}
</style>
"""


def inject_styles() -> None:
    st.markdown(GLOBAL_STYLES, unsafe_allow_html=True)


def _grade(score: int, max_score: int) -> tuple:
    p = score / max_score if max_score > 0 else 0
    if p >= 0.85: return "A+", "Excellent",  "#15803D", "#DCFCE7"
    if p >= 0.75: return "A",  "Strong",     "#16A34A", "#F0FDF4"
    if p >= 0.65: return "B+", "Above avg",  "#2563EB", "#EFF6FF"
    if p >= 0.50: return "B",  "Average",    "#2563EB", "#EFF6FF"
    if p >= 0.35: return "C+", "Below avg",  "#D97706", "#FFFBEB"
    if p >= 0.20: return "C",  "Weak",       "#DC2626", "#FEF2F2"
    return              "D",  "Poor",        "#991B1B", "#FEF2F2"


def verdict_card(
    ticker: str, company: str, exchange: str, sector: str,
    price: float, fair_value: float, mos_pct: float,
    summary: str, score_breakdown: dict, sym: str = "$",
) -> None:
    if mos_pct >= 10:
        sig_label, sig_color = "Undervalued", "#22C55E"
        mos_bg, mos_bc, mos_tc = "rgba(34,197,94,0.15)", "rgba(34,197,94,0.35)", "#86EFAC"
    elif mos_pct >= -5:
        sig_label, sig_color = "Near Fair Value", "#F59E0B"
        mos_bg, mos_bc, mos_tc = "rgba(245,158,11,0.15)", "rgba(245,158,11,0.35)", "#FCD34D"
    else:
        sig_label, sig_color = "Overvalued", "#EF4444"
        mos_bg, mos_bc, mos_tc = "rgba(239,68,68,0.15)", "rgba(239,68,68,0.35)", "#FCA5A5"

    vg, vl, vc, vbg = _grade(score_breakdown.get("valuation", 0), 40)
    qg, ql, qc, qbg = _grade(score_breakdown.get("quality", 0), 30)
    gg, gl, gc, gbg = _grade(score_breakdown.get("growth", 0), 20)
    sg, sl, sc_, sbg = _grade(score_breakdown.get("sentiment", 0), 10)
    vn = score_breakdown.get("valuation", 0)
    qn = score_breakdown.get("quality", 0)
    gn = score_breakdown.get("growth", 0)
    sn = score_breakdown.get("sentiment", 0)

    st.markdown(f"""
<div style="border-radius:14px;overflow:hidden;border:1px solid #E2E8F0;
            font-family:'Inter',-apple-system,sans-serif;margin-bottom:14px;
            box-shadow:0 1px 3px rgba(0,0,0,0.05);">
  <div style="background:linear-gradient(135deg,#0F172A 0%,#1E293B 100%);
              padding:20px 24px;display:grid;
              grid-template-columns:1fr auto;gap:20px;align-items:start;">
    <div>
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
        <div style="width:42px;height:42px;background:#fff;border-radius:10px;
                    display:flex;align-items:center;justify-content:center;
                    font-size:11px;font-weight:800;color:#0F172A;flex-shrink:0;">
          {ticker[:4]}
        </div>
        <div>
          <div style="font-size:22px;font-weight:900;color:#F8FAFC;
                      line-height:1.1;">{company}</div>
          <div style="font-size:10px;color:#94A3B8;margin-top:2px;">
            {ticker} \u00b7 {exchange} \u00b7 {sector}</div>
        </div>
      </div>
      <div style="font-size:12px;color:#CBD5E1;line-height:1.7;
                  max-width:500px;">{summary}</div>
      <div style="margin-top:10px;font-size:10px;color:#475569;
                  font-style:italic;">
        Model output only. Not personalized investment advice.</div>
    </div>
    <div  style="background:{mos_bg};border:1.5px solid {mos_bc};
                border-radius:14px;padding:16px 20px;text-align:center;min-width:130px;">
      <div style="font-size:10px;color:{mos_tc};letter-spacing:0.8px;
                  font-weight:700;margin-bottom:6px;">MARGIN OF SAFETY</div>
      <div  style="font-size:52px;font-weight:900;
                  color:{mos_tc};line-height:1;">{mos_pct:+.1f}%</div>
      <div style="font-size:13px;font-weight:700;color:{mos_tc};
                  margin-top:6px;">{sig_label}</div>
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid {mos_bc};">
        <div style="font-size:10px;color:{mos_tc};opacity:0.8;
                    margin-bottom:2px;">Fair value</div>
        <div style="font-size:16px;font-weight:800;
                    color:{mos_tc};">{sym}{fair_value:,.0f}</div>
      </div>
    </div>
  </div>
  <div style="background:#fff;display:grid;grid-template-columns:repeat(4,1fr);
              border-top:1px solid #E2E8F0;">
    <div style="padding:14px 10px;text-align:center;border-right:1px solid #E2E8F0;">
      <div style="font-size:9px;color:{vc};font-weight:700;
                  letter-spacing:0.8px;margin-bottom:5px;">VALUATION</div>
      <div style="font-size:32px;font-weight:900;color:{vc};
                  line-height:1;">{vg}</div>
      <div style="font-size:10px;color:{vc};opacity:0.75;
                  margin-top:3px;">{vl}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{vn}/40</div>
    </div>
    <div style="padding:14px 10px;text-align:center;border-right:1px solid #E2E8F0;">
      <div style="font-size:9px;color:{qc};font-weight:700;
                  letter-spacing:0.8px;margin-bottom:5px;">QUALITY</div>
      <div style="font-size:32px;font-weight:900;color:{qc};
                  line-height:1;">{qg}</div>
      <div style="font-size:10px;color:{qc};opacity:0.75;
                  margin-top:3px;">{ql}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{qn}/30</div>
    </div>
    <div style="padding:14px 10px;text-align:center;border-right:1px solid #E2E8F0;">
      <div style="font-size:9px;color:{gc};font-weight:700;
                  letter-spacing:0.8px;margin-bottom:5px;">GROWTH</div>
      <div style="font-size:32px;font-weight:900;color:{gc};
                  line-height:1;">{gg}</div>
      <div style="font-size:10px;color:{gc};opacity:0.75;
                  margin-top:3px;">{gl}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{gn}/20</div>
    </div>
    <div style="padding:14px 10px;text-align:center;">
      <div style="font-size:9px;color:{sc_};font-weight:700;
                  letter-spacing:0.8px;margin-bottom:5px;">SENTIMENT</div>
      <div style="font-size:32px;font-weight:900;color:{sc_};
                  line-height:1;">{sg}</div>
      <div style="font-size:10px;color:{sc_};opacity:0.75;
                  margin-top:3px;">{sl}</div>
      <div style="font-size:9px;color:#94A3B8;margin-top:2px;">{sn}/10</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)


def kpi_row(metrics: list) -> None:
    n = min(len(metrics), 4)
    cols = ""
    for m in metrics[:4]:
        c = m.get("color", "#0F172A")
        sub = m.get("sub", "")
        sub_html = f'<div style="font-size:10px;color:#94A3B8;margin-top:3px;">{sub}</div>' if sub else ""
        cols += f"""
    <div style="background:#fff;border:1px solid #E2E8F0;border-radius:10px;
                padding:12px 14px;font-family:'Inter',-apple-system,sans-serif;">
      <div style="font-size:9px;color:#94A3B8;letter-spacing:0.5px;
                  text-transform:uppercase;margin-bottom:5px;">{m['label']}</div>
      <div style="font-size:20px;font-weight:800;color:{c};
                  line-height:1.1;">{m['value']}</div>
      {sub_html}
    </div>"""
    st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat({n},1fr);gap:10px;
            margin-bottom:14px;">
  {cols}
</div>""", unsafe_allow_html=True)
