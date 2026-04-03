# dashboard/ui/right_panel.py
from __future__ import annotations
import streamlit as st
import importlib.util as _ilu, pathlib as _pl

_th_path = _pl.Path(__file__).resolve().parent / "themes.py"
_th_spec = _ilu.spec_from_file_location("_yiq_th_rp", _th_path)
_th_mod  = _ilu.module_from_spec(_th_spec)
_th_spec.loader.exec_module(_th_mod)
get_theme = _th_mod.get_theme


def render_right_panel(
    theme_name:    str,
    plain_english: str,
    earnings_data: dict,
    sector_heat:   list[dict],
    ai_snippet:    str,
    ticker:        str,
) -> None:
    t = get_theme(theme_name)

    ed = earnings_data or {}
    days_to   = ed.get("days_to",  "\u2014")
    date_str  = ed.get("date",     "\u2014")
    consensus = ed.get("consensus_eps", "\u2014")
    model_eps = ed.get("model_eps",     "\u2014")
    beat_rate = ed.get("beat_rate_pct", "\u2014")

    sector_rows = ""
    for s in (sector_heat or []):
        chg     = s.get("change_pct", 0)
        color   = t["positive"] if chg >= 0 else t["negative"]
        bg      = t["positive_bg"] if chg >= 0 else t["negative_bg"]
        sign    = "+" if chg >= 0 else ""
        sector_rows += f"""
        <div style="background:{bg};border-radius:7px;
                    padding:6px 8px;border:1px solid {color}22;">
          <div style="font-size:9px;font-weight:700;
                      color:{color};margin-bottom:1px;">
            {s.get('name','')[:6]}
          </div>
          <div style="font-size:11px;font-weight:800;
                      color:{color};">
            {sign}{chg:.1f}%
          </div>
        </div>"""

    st.markdown(f"""
<div style="display:flex;flex-direction:column;gap:10px;
            border-left:1px solid {t['border']};
            padding-left:16px;height:100%;">

  <div style="background:{t['accent']}11;border-radius:10px;
              padding:12px;border:1px solid {t['accent']}22;">
    <div style="font-size:9px;color:{t['accent']};
                letter-spacing:1px;font-weight:700;
                margin-bottom:6px;">PLAIN ENGLISH</div>
    <div style="font-size:12px;color:{t['text2']};
                line-height:1.7;">{plain_english}</div>
  </div>

  <div style="background:{t['warning_bg']};border-radius:10px;
              padding:12px;border:1px solid {t['warning']}22;">
    <div style="display:flex;justify-content:space-between;
                align-items:center;margin-bottom:8px;">
      <div style="font-size:9px;color:{t['warning']};
                  letter-spacing:1px;font-weight:700;">
        EARNINGS IN {days_to} DAYS
      </div>
      <div style="font-size:9px;color:{t['text3']};">
        {date_str}
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;
                gap:6px;">
      <div style="text-align:center;">
        <div style="font-size:9px;color:{t['text3']};
                    margin-bottom:2px;">Consensus</div>
        <div style="font-size:13px;font-weight:800;
                    color:{t['text']};">{consensus}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:9px;color:{t['text3']};
                    margin-bottom:2px;">Model</div>
        <div style="font-size:13px;font-weight:800;
                    color:{t['accent']};">{model_eps}</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:9px;color:{t['text3']};
                    margin-bottom:2px;">Beat rate</div>
        <div style="font-size:13px;font-weight:800;
                    color:{t['positive']};">{beat_rate}%</div>
      </div>
    </div>
  </div>

  <div>
    <div style="font-size:9px;color:{t['text3']};
                letter-spacing:1px;font-weight:700;
                margin-bottom:7px;">SECTOR TODAY</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;
                gap:5px;">{sector_rows}</div>
  </div>

  <div style="background:{t['bg3']};border-radius:10px;
              padding:12px;border:1px solid {t['border']};">
    <div style="font-size:9px;color:{t['text3']};
                letter-spacing:1px;font-weight:700;
                margin-bottom:6px;">AI ANALYST</div>
    <div style="font-size:11px;color:{t['text2']};
                line-height:1.65;font-style:italic;">
      &ldquo;{ai_snippet}&rdquo;
    </div>
  </div>

</div>
""", unsafe_allow_html=True)
