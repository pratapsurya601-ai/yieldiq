# dashboard/ui/components/transparency_strip.py
# ═══════════════════════════════════════════════════════════════
# Model transparency strip — shows key assumptions as ranges.
# Paradoxically, showing uncertainty increases trust more than hiding it.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_transparency_strip(
    wacc: float,
    wacc_industry_range: tuple[float, float] = (8.0, 12.0),
    fcf_growth: float = 0.0,
    fcf_growth_historical_avg: float = 0.0,
    confidence_score: int = 50,
    ticker: str = "",
) -> None:
    """
    Renders the model transparency strip.

    Example output:
    Model used: WACC 9.2% (industry 7.8–11.4%) ·
    FCF growth +8.2%/yr (historical avg +7.1%) · Confidence: High
    [Adjust assumptions]  [How we calculate this]
    """
    # WACC with industry range
    _wacc_str = f"WACC {wacc:.1f}%"
    _wacc_range = f"(industry {wacc_industry_range[0]:.1f}–{wacc_industry_range[1]:.1f}%)"

    # FCF growth with historical comparison + optimism indicator
    _fcf_str = f"FCF growth {fcf_growth:+.1f}%/yr"
    _fcf_hist = f"(historical avg {fcf_growth_historical_avg:+.1f}%)"

    _delta = fcf_growth - fcf_growth_historical_avg
    if _delta > 5:
        _optimism = '<span style="color:#DC2626;font-weight:600;">(significantly optimistic)</span>'
    elif _delta > 2:
        _optimism = '<span style="color:#D97706;font-weight:600;">(slightly optimistic)</span>'
    elif _delta < -2:
        _optimism = '<span style="color:#059669;font-weight:600;">(conservative)</span>'
    else:
        _optimism = ""

    # Confidence label
    if confidence_score >= 75:
        _conf_label = "High"
        _conf_color = "#185FA5"
    elif confidence_score >= 50:
        _conf_label = "Medium"
        _conf_color = "#D97706"
    else:
        _conf_label = "Low"
        _conf_color = "#DC2626"

    st.html(f"""
    <div style="font-size:11px;color:#94A3B8;padding:8px 0;margin-bottom:8px;
                border-top:1px solid #F1F5F9;border-bottom:1px solid #F1F5F9;
                line-height:1.8;">
      <span style="font-weight:600;color:#64748B;">Model:</span>
      {_wacc_str} <span style="color:#94A3B8;">{_wacc_range}</span> ·
      {_fcf_str} <span style="color:#94A3B8;">{_fcf_hist}</span>
      {_optimism} ·
      Confidence: <span style="color:{_conf_color};font-weight:600;">{_conf_label}</span>
    </div>
    """)

    # Action links
    _lc1, _lc2, _lc3 = st.columns([2, 2, 4])
    with _lc1:
        st.html(
            '<div style="font-size:10px;color:#1D4ED8;cursor:pointer;font-weight:600;">'
            'Adjust assumptions ↗</div>'
        )
    with _lc2:
        st.html(
            '<div style="font-size:10px;color:#94A3B8;cursor:pointer;">'
            'How we calculate this ↗</div>'
        )

    # Learn mode tip
    try:
        from utils.learn_mode import learn_tip
        learn_tip("wacc")
    except Exception:
        pass
