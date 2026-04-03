# dashboard/ui/verdict_card.py
from __future__ import annotations
import streamlit as st
import importlib.util as _ilu, pathlib as _pl

_th_path = _pl.Path(__file__).resolve().parent / "themes.py"
_th_spec = _ilu.spec_from_file_location("_yiq_th_vc", _th_path)
_th_mod  = _ilu.module_from_spec(_th_spec)
_th_spec.loader.exec_module(_th_mod)
get_theme = _th_mod.get_theme
get_signal_style = _th_mod.get_signal_style


def render_verdict_strip(
    ticker:      str,
    company:     str,
    exchange:    str,
    sector:      str,
    price:       float,
    fair_value:  float,
    mos_pct:     float,
    yieldiq_score: int,
    score_breakdown: dict,
    summary_text:  str,
    theme_name:    str = "forest",
) -> None:
    t   = get_theme(theme_name)
    sig = get_signal_style(mos_pct, theme_name)

    mos_display = f"{mos_pct:+.1f}%"
    iv_display  = f"${fair_value:,.2f}"
    px_display  = f"${price:,.2f}"
    score_arc   = int((min(max(yieldiq_score, 0), 100) / 100) * 188)
    score_off   = 188 - score_arc

    val_pct  = int(score_breakdown.get("valuation", 0) / 40 * 100) if score_breakdown.get("valuation") else 0
    qual_pct = int(score_breakdown.get("quality",   0) / 30 * 100) if score_breakdown.get("quality") else 0
    grow_pct = int(score_breakdown.get("growth",    0) / 20 * 100) if score_breakdown.get("growth") else 0
    sent_pct = int(score_breakdown.get("sentiment", 0) / 10 * 100) if score_breakdown.get("sentiment") else 0
    val_num  = score_breakdown.get("valuation", 0)
    qual_num = score_breakdown.get("quality",   0)
    grow_num = score_breakdown.get("growth",    0)
    sent_num = score_breakdown.get("sentiment", 0)

    st.markdown(f"""
<div style="
  background:{t['bg2']};
  border:1px solid {t['border2']};
  border-radius:14px;
  padding:18px 22px;
  display:grid;
  grid-template-columns:140px 1fr auto auto;
  gap:20px;
  align-items:center;
  margin-bottom:14px;
">
  <div style="
    background:{sig['bg']};
    border:1.5px solid {sig['color']}44;
    border-radius:12px;
    padding:14px 12px;
    text-align:center;
  ">
    <div style="font-size:9px;color:{t['text3']};
                letter-spacing:1px;margin-bottom:5px;">
      MODEL OUTPUT
    </div>
    <div style="font-size:15px;font-weight:900;
                color:{sig['color']};line-height:1.2;">
      {sig['label']}
    </div>
    <div style="font-size:9px;color:{t['text3']};
                margin-top:3px;line-height:1.3;">
      {sig['sub']}
    </div>
    <div style="margin-top:10px;font-size:18px;
                font-weight:900;color:{sig['color']};">
      {mos_display}
    </div>
    <div style="font-size:9px;color:{t['text3']};
                margin-top:1px;">margin of safety</div>
  </div>

  <div>
    <div style="font-size:20px;font-weight:800;
                color:{t['text']};margin-bottom:2px;
                line-height:1.1;">
      {company}
    </div>
    <div style="font-size:11px;color:{t['text3']};
                margin-bottom:10px;">
      {ticker} &nbsp;\u00b7&nbsp; {exchange} &nbsp;\u00b7&nbsp; {sector}
    </div>
    <div style="font-size:12px;color:{t['text2']};
                line-height:1.65;max-width:500px;
                margin-bottom:10px;">
      {summary_text}
    </div>
    <div style="display:flex;flex-direction:column;gap:5px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;color:{t['text3']};
                     width:58px;font-weight:600;">Valuation</span>
        <div style="flex:1;height:7px;border-radius:4px;
                    background:{t['bar_valuation']}22;">
          <div style="width:{val_pct}%;height:7px;border-radius:4px;
                      background:{t['bar_valuation']};
                      transition:width 0.8s ease;"></div>
        </div>
        <span style="font-size:10px;font-weight:700;
                     color:{t['text']};min-width:32px;
                     text-align:right;">{val_num}/40</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;color:{t['text3']};
                     width:58px;font-weight:600;">Quality</span>
        <div style="flex:1;height:7px;border-radius:4px;
                    background:{t['bar_quality']}22;">
          <div style="width:{qual_pct}%;height:7px;border-radius:4px;
                      background:{t['bar_quality']};
                      transition:width 0.8s ease;"></div>
        </div>
        <span style="font-size:10px;font-weight:700;
                     color:{t['text']};min-width:32px;
                     text-align:right;">{qual_num}/30</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;color:{t['text3']};
                     width:58px;font-weight:600;">Growth</span>
        <div style="flex:1;height:7px;border-radius:4px;
                    background:{t['bar_growth']}22;">
          <div style="width:{grow_pct}%;height:7px;border-radius:4px;
                      background:{t['bar_growth']};
                      transition:width 0.8s ease;"></div>
        </div>
        <span style="font-size:10px;font-weight:700;
                     color:{t['text']};min-width:32px;
                     text-align:right;">{grow_num}/20</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:10px;color:{t['text3']};
                     width:58px;font-weight:600;">Sentiment</span>
        <div style="flex:1;height:7px;border-radius:4px;
                    background:{t['bar_sentiment']}22;">
          <div style="width:{sent_pct}%;height:7px;border-radius:4px;
                      background:{t['bar_sentiment']};
                      transition:width 0.8s ease;"></div>
        </div>
        <span style="font-size:10px;font-weight:700;
                     color:{t['text']};min-width:32px;
                     text-align:right;">{sent_num}/10</span>
      </div>
    </div>
    <div style="margin-top:8px;font-size:10px;
                color:{t['text3']};font-style:italic;">
      Model output only. Not personalized investment advice.
      YieldIQ is not a registered investment adviser.
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;
              gap:8px;min-width:220px;">
    <div style="background:{t['bg3']};border-radius:9px;
                padding:10px 14px;border:1px solid {t['border']};">
      <div style="font-size:9px;color:{t['text3']};
                  margin-bottom:3px;">Model fair value</div>
      <div style="font-size:17px;font-weight:800;
                  color:{t['text']};">{iv_display}</div>
    </div>
    <div style="background:{t['bg3']};border-radius:9px;
                padding:10px 14px;border:1px solid {t['border']};">
      <div style="font-size:9px;color:{t['text3']};
                  margin-bottom:3px;">Market price</div>
      <div style="font-size:17px;font-weight:800;
                  color:{t['text']};">{px_display}</div>
    </div>
    <div style="background:{t['positive_bg']};border-radius:9px;
                padding:10px 14px;border:1px solid {t['positive']}22;">
      <div style="font-size:9px;color:{t['text3']};
                  margin-bottom:3px;">Quality score</div>
      <div style="font-size:17px;font-weight:800;
                  color:{t['positive']};">{qual_num}/30</div>
    </div>
    <div style="background:{t['bg3']};border-radius:9px;
                padding:10px 14px;border:1px solid {t['border']};">
      <div style="font-size:9px;color:{t['text3']};
                  margin-bottom:3px;">FCF growth</div>
      <div style="font-size:17px;font-weight:800;
                  color:{t['accent']};">
        {score_breakdown.get('fcf_growth_pct', 0):+.1f}%
      </div>
    </div>
  </div>

  <div style="text-align:center;min-width:80px;">
    <svg width="80" height="80" viewBox="0 0 80 80">
      <circle cx="40" cy="40" r="30" fill="none"
        stroke="{t['bg4']}" stroke-width="7"/>
      <circle cx="40" cy="40" r="30" fill="none"
        stroke="{t['accent']}" stroke-width="7"
        stroke-dasharray="188"
        stroke-dashoffset="{score_off}"
        stroke-linecap="round"
        transform="rotate(-90 40 40)"/>
      <text x="40" y="36" text-anchor="middle"
        font-size="20" font-weight="900"
        fill="{t['text']}">{yieldiq_score}</text>
      <text x="40" y="52" text-anchor="middle"
        font-size="9" fill="{t['text3']}">SCORE</text>
    </svg>
    <div style="font-size:9px;color:{t['text3']};
                margin-top:3px;">YieldIQ composite</div>
  </div>
</div>
""", unsafe_allow_html=True)
