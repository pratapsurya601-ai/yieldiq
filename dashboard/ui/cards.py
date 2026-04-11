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

    st.html(f"""
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
""")


def valuation_gauge(price: float, fair_value: float, mos_pct: float, sym: str = "$") -> None:
    """
    GuruFocus-style 5-zone valuation gauge.
    Shows where the stock sits on a spectrum from Significantly Undervalued → Significantly Overvalued.
    """
    # 5 zones based on Margin of Safety %
    # MoS > 30%: Significantly Undervalued
    # MoS 10-30%: Undervalued
    # MoS -10% to +10%: Fairly Valued
    # MoS -10% to -30%: Overvalued
    # MoS < -30%: Significantly Overvalued

    zones = [
        {"label": "Significantly<br>Undervalued", "color": "#065F46", "bg": "#059669", "range": (30, 100)},
        {"label": "Undervalued",                  "color": "#16A34A", "bg": "#22C55E", "range": (10, 30)},
        {"label": "Fairly<br>Valued",             "color": "#CA8A04", "bg": "#EAB308", "range": (-10, 10)},
        {"label": "Overvalued",                   "color": "#DC2626", "bg": "#EF4444", "range": (-30, -10)},
        {"label": "Significantly<br>Overvalued",  "color": "#991B1B", "bg": "#DC2626", "range": (-100, -30)},
    ]

    # Clamp mos_pct to -60..+60 for needle position
    clamped = max(-60, min(60, mos_pct))
    # Map to 0-100% position (60 = 0%, 0 = 50%, -60 = 100%)
    needle_pct = ((60 - clamped) / 120) * 100

    # Determine active zone
    if mos_pct >= 30:
        active_idx, verdict = 0, "Significantly Undervalued"
        needle_color = "#065F46"
    elif mos_pct >= 10:
        active_idx, verdict = 1, "Undervalued"
        needle_color = "#16A34A"
    elif mos_pct >= -10:
        active_idx, verdict = 2, "Fairly Valued"
        needle_color = "#CA8A04"
    elif mos_pct >= -30:
        active_idx, verdict = 3, "Overvalued"
        needle_color = "#DC2626"
    else:
        active_idx, verdict = 4, "Significantly Overvalued"
        needle_color = "#991B1B"

    # Build zone segments HTML
    zone_html = ""
    for i, z in enumerate(zones):
        opacity = "1" if i == active_idx else "0.3"
        border_r = "0" if i < 4 else "8px"
        border_l = "0" if i > 0 else "8px"
        zone_html += (
            f'<div style="flex:1;height:12px;background:{z["bg"]};opacity:{opacity};'
            f'border-radius:{border_l} {border_r} {border_r} {border_l};'
            f'transition:opacity 0.3s;"></div>'
        )

    # Zone labels
    label_html = ""
    for i, z in enumerate(zones):
        weight = "700" if i == active_idx else "400"
        color = z["color"] if i == active_idx else "#94A3B8"
        label_html += (
            f'<div style="flex:1;text-align:center;font-size:9px;font-weight:{weight};'
            f'color:{color};line-height:1.3;font-family:Inter,sans-serif;">{z["label"]}</div>'
        )

    st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
            padding:20px 24px 18px;margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,0.04);">

  <!-- Header row -->
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <div style="font-size:11px;font-weight:700;color:#64748B;
                letter-spacing:0.1em;text-transform:uppercase;
                font-family:'IBM Plex Mono',monospace;">Valuation Gauge</div>
    <div style="display:flex;align-items:center;gap:12px;">
      <div style="font-size:11px;color:#94A3B8;">
        Price <span style="font-weight:700;color:#0F172A;font-family:'IBM Plex Mono',monospace;">
        {sym}{price:,.2f}</span></div>
      <div style="font-size:11px;color:#94A3B8;">
        Fair Value <span style="font-weight:700;color:{needle_color};font-family:'IBM Plex Mono',monospace;">
        {sym}{fair_value:,.2f}</span></div>
    </div>
  </div>

  <!-- Gauge bar -->
  <div style="position:relative;margin-bottom:8px;">
    <!-- Zone segments -->
    <div style="display:flex;gap:2px;">
      {zone_html}
    </div>

    <!-- Needle / marker -->
    <div style="position:absolute;top:-6px;left:{needle_pct:.1f}%;transform:translateX(-50%);
                display:flex;flex-direction:column;align-items:center;z-index:2;">
      <div style="width:0;height:0;border-left:6px solid transparent;
                  border-right:6px solid transparent;
                  border-top:8px solid {needle_color};"></div>
      <div style="width:3px;height:18px;background:{needle_color};border-radius:0 0 2px 2px;"></div>
    </div>
  </div>

  <!-- Zone labels -->
  <div style="display:flex;gap:2px;margin-top:6px;">
    {label_html}
  </div>

  <!-- Verdict text -->
  <div style="text-align:center;margin-top:14px;padding-top:12px;
              border-top:1px solid #F1F5F9;">
    <span style="font-size:13px;font-weight:700;color:{needle_color};
                 font-family:Inter,sans-serif;">{verdict}</span>
    <span style="font-size:12px;color:#94A3B8;margin-left:8px;">
      Model estimates {abs(mos_pct):.0f}% {'discount' if mos_pct > 0 else 'premium'} to fair value</span>
  </div>
</div>
""")


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
    st.html(f"""
<div style="display:grid;grid-template-columns:repeat({n},1fr);gap:10px;
            margin-bottom:14px;">
  {cols}
</div>""")
