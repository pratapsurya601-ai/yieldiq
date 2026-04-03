# dashboard/ui/theme_css.py
# Generates the full CSS injection string for a given theme.

from __future__ import annotations
import importlib.util as _ilu, pathlib as _pl

# Load themes via file path to avoid utils/ name collision
_themes_path = _pl.Path(__file__).resolve().parent / "themes.py"
_themes_spec = _ilu.spec_from_file_location("_yiq_themes", _themes_path)
_themes_mod  = _ilu.module_from_spec(_themes_spec)
_themes_spec.loader.exec_module(_themes_mod)
get_theme = _themes_mod.get_theme


def build_theme_css(theme_name: str) -> str:
    t = get_theme(theme_name)
    return f"""
<style>
/* ── YieldIQ Theme: {t['name']} ── */
:root {{
    --yiq-bg:           {t['bg']};
    --yiq-bg2:          {t['bg2']};
    --yiq-bg3:          {t['bg3']};
    --yiq-bg4:          {t['bg4']};
    --yiq-bg5:          {t['bg5']};
    --yiq-border:       {t['border']};
    --yiq-border2:      {t['border2']};
    --yiq-text:         {t['text']};
    --yiq-text2:        {t['text2']};
    --yiq-text3:        {t['text3']};
    --yiq-accent:       {t['accent']};
    --yiq-accent-dim:   {t['accent_dim']};
    --yiq-positive:     {t['positive']};
    --yiq-positive-bg:  {t['positive_bg']};
    --yiq-negative:     {t['negative']};
    --yiq-negative-bg:  {t['negative_bg']};
    --yiq-warning:      {t['warning']};
    --yiq-warning-bg:   {t['warning_bg']};
    --yiq-neutral:      {t['neutral']};
    --yiq-neutral-bg:   {t['neutral_bg']};
    --yiq-bar-val:      {t['bar_valuation']};
    --yiq-bar-qual:     {t['bar_quality']};
    --yiq-bar-grow:     {t['bar_growth']};
    --yiq-bar-sent:     {t['bar_sentiment']};
}}

/* App background */
.stApp, .stApp > div {{
    background: {t['bg']} !important;
}}

/* Main content area */
section.main > div {{
    background: {t['bg']} !important;
}}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background: {t['sidebar_bg']} !important;
    border-right: 1px solid {t['sidebar_border']} !important;
}}
section[data-testid="stSidebar"] * {{
    color: {t['sidebar_text']} !important;
}}
section[data-testid="stSidebar"] .stButton > button {{
    background: {t['bg3']} !important;
    color: {t['text2']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 8px !important;
    width: 100% !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: {t['accent']} !important;
    color: {t['btn_primary_fg']} !important;
    border-color: transparent !important;
}}

/* Text inputs */
.stTextInput > div > div > input {{
    background: {t['bg3']} !important;
    color: {t['text']} !important;
    border: 1px solid {t['border2']} !important;
    border-radius: 8px !important;
    caret-color: {t['accent']} !important;
}}
.stTextInput > div > div > input:focus {{
    border-color: {t['accent']} !important;
    box-shadow: 0 0 0 2px {t['accent']}33 !important;
}}
.stTextInput > label {{
    color: {t['text2']} !important;
}}

/* Select boxes */
.stSelectbox > div > div {{
    background: {t['bg3']} !important;
    color: {t['text']} !important;
    border: 1px solid {t['border2']} !important;
    border-radius: 8px !important;
}}
.stSelectbox label {{
    color: {t['text2']} !important;
}}

/* Sliders */
.stSlider > div > div > div > div {{
    background: {t['accent']} !important;
}}
.stSlider label {{
    color: {t['text2']} !important;
}}

/* Metrics */
div[data-testid="metric-container"] {{
    background: {t['bg2']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
}}
div[data-testid="metric-container"] label {{
    color: {t['text3']} !important;
    font-size: 11px !important;
}}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {{
    color: {t['text']} !important;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    border-bottom: 1px solid {t['border']} !important;
    gap: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {t['text3']} !important;
    border-bottom: 2px solid transparent !important;
    padding: 8px 16px !important;
    font-size: 13px !important;
}}
.stTabs [aria-selected="true"] {{
    color: {t['text']} !important;
    border-bottom-color: {t['accent']} !important;
    font-weight: 600 !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    background: {t['bg']} !important;
    padding-top: 16px !important;
}}

/* Buttons */
.stButton > button {{
    background: {t['btn_secondary_bg']} !important;
    color: {t['btn_secondary_fg']} !important;
    border: 1px solid {t['border2']} !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.15s !important;
}}
.stButton > button:hover {{
    border-color: {t['accent']} !important;
    color: {t['accent']} !important;
}}
.stButton > button[kind="primary"] {{
    background: {t['btn_primary_bg']} !important;
    color: {t['btn_primary_fg']} !important;
    border-color: transparent !important;
}}
.stButton > button[kind="primary"]:hover {{
    opacity: 0.9 !important;
    color: {t['btn_primary_fg']} !important;
}}

/* Expanders */
.streamlit-expanderHeader {{
    background: {t['bg2']} !important;
    color: {t['text']} !important;
    border: 1px solid {t['border']} !important;
    border-radius: 8px !important;
}}
.streamlit-expanderContent {{
    background: {t['bg2']} !important;
    border: 1px solid {t['border']} !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px !important;
}}

/* Checkboxes */
.stCheckbox label {{
    color: {t['text2']} !important;
}}

/* Radio */
.stRadio label {{
    color: {t['text2']} !important;
}}

/* Text & headings */
h1, h2, h3, h4, h5, h6 {{
    color: {t['text']} !important;
}}
p, li, div.stMarkdown {{
    color: {t['text2']} !important;
}}
.stMarkdown a {{
    color: {t['accent']} !important;
}}

/* Dividers */
hr {{
    border-color: {t['border']} !important;
}}

/* Info/warning/error boxes */
.stAlert {{
    border-radius: 8px !important;
}}

/* Dataframes */
.stDataFrame {{
    border: 1px solid {t['border']} !important;
    border-radius: 8px !important;
}}
.stDataFrame th {{
    background: {t['bg3']} !important;
    color: {t['text']} !important;
}}
.stDataFrame td {{
    color: {t['text2']} !important;
    border-color: {t['border']} !important;
}}

/* Spinner */
.stSpinner > div {{
    border-top-color: {t['accent']} !important;
}}

/* Caption text */
.stCaption {{
    color: {t['text3']} !important;
}}

/* Number input */
.stNumberInput > div > div > input {{
    background: {t['bg3']} !important;
    color: {t['text']} !important;
    border-color: {t['border2']} !important;
    border-radius: 8px !important;
}}

/* Multiselect */
.stMultiSelect > div {{
    background: {t['bg3']} !important;
    border-color: {t['border2']} !important;
    border-radius: 8px !important;
}}

/* Download button */
.stDownloadButton > button {{
    background: {t['btn_secondary_bg']} !important;
    color: {t['btn_secondary_fg']} !important;
    border: 1px solid {t['border2']} !important;
    border-radius: 8px !important;
}}
</style>
"""


def get_plotly_layout(theme_name: str) -> dict:
    """
    Returns a Plotly layout dict that applies the active theme.
    Merge this into every go.Figure().update_layout() call.
    Usage:
        fig.update_layout(**get_plotly_layout(theme_name))
    """
    t = get_theme(theme_name)
    return dict(
        paper_bgcolor = t["chart_paper"],
        plot_bgcolor  = t["chart_bg"],
        font          = dict(
            color  = t["chart_font"],
            family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
            size   = 12,
        ),
        xaxis = dict(
            gridcolor     = t["chart_grid"],
            linecolor     = t["border"],
            tickcolor     = t["border"],
            tickfont      = dict(color=t["chart_font"], size=11),
            title_font    = dict(color=t["text2"]),
            zerolinecolor = t["border"],
        ),
        yaxis = dict(
            gridcolor     = t["chart_grid"],
            linecolor     = t["border"],
            tickcolor     = t["border"],
            tickfont      = dict(color=t["chart_font"], size=11),
            title_font    = dict(color=t["text2"]),
            zerolinecolor = t["border"],
        ),
        legend = dict(
            bgcolor     = t["bg2"],
            bordercolor = t["border"],
            font        = dict(color=t["text2"]),
        ),
        colorway = [
            t["chart_line"],
            t["chart_accent2"],
            t["chart_accent3"],
            t["chart_bar_pos"],
            t["chart_bar_neg"],
        ],
        hoverlabel = dict(
            bgcolor   = t["bg3"],
            font_color= t["text"],
            bordercolor=t["border2"],
        ),
        margin = dict(l=40, r=20, t=40, b=40),
    )


def get_bar_colors(theme_name: str) -> dict:
    """
    Returns named colors for score breakdown bars.
    Usage:
        colors = get_bar_colors(theme)
        colors["valuation"]  # for the valuation bar
    """
    t = get_theme(theme_name)
    return {
        "valuation": t["bar_valuation"],
        "quality":   t["bar_quality"],
        "growth":    t["bar_growth"],
        "sentiment": t["bar_sentiment"],
        "positive":  t["chart_bar_pos"],
        "negative":  t["chart_bar_neg"],
        "neutral":   t["chart_bar_neu"],
        "line":      t["chart_line"],
        "fill":      t["chart_fill"],
        "heatmap":   t["chart_heatmap"],
        "scatter":   t["chart_line"],
    }


def get_signal_style(mos_pct: float, theme_name: str) -> dict:
    """
    Returns color + label for a given MoS value.
    No buy/sell language — only model output language.
    """
    t = get_theme(theme_name)
    if mos_pct >= 30:
        return {"label": "High Margin of Safety",
                "sub":   "Model: significantly undervalued",
                "color": t["positive"], "bg": t["positive_bg"]}
    elif mos_pct >= 10:
        return {"label": "Undervalued",
                "sub":   "Model estimate above current price",
                "color": t["positive"], "bg": t["positive_bg"]}
    elif mos_pct >= -5:
        return {"label": "Near Fair Value",
                "sub":   "Model estimate close to market price",
                "color": t["warning"],  "bg": t["warning_bg"]}
    elif mos_pct >= -20:
        return {"label": "Overvalued",
                "sub":   "Price above model fair value estimate",
                "color": t["negative"], "bg": t["negative_bg"]}
    else:
        return {"label": "Significantly Overvalued",
                "sub":   "Price well above model fair value",
                "color": t["negative"], "bg": t["negative_bg"]}
