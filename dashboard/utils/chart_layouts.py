"""
Chart layout utilities for YieldIQ visualizations.
Theme-aware: reads active theme from st.session_state.
"""
import streamlit as st


def _get_active_theme() -> dict:
    """Read the active theme dict from session_state."""
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent.parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_cl", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    _name = st.session_state.get("theme", "slate")
    return _tm.get_theme(_name)


def KL(**kw):
    """
    Theme-aware chart layout.
    Apply to figure.update_layout() for consistent theming.

    Usage:
        fig.update_layout(**KL(height=400, title="My Chart"))
    """
    t = _get_active_theme()
    base = dict(
        paper_bgcolor=t["chart_paper"],
        plot_bgcolor=t["chart_bg"],
        font=dict(family="Inter, DM Sans, system-ui, sans-serif", color=t["chart_font"], size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=t["bg3"],
            font=dict(color=t["text"], family="IBM Plex Mono, monospace", size=12),
            bordercolor=t["border2"],
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor=t["border"],
            borderwidth=1,
            font=dict(color=t["text2"], size=11),
        ),
        xaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False,
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base


def apply_koyfin(fig, accent=None, height=280, title_txt="", extra_kw=None):
    """
    One-call upgrade: themed layout + accent top border + axis polish.

    Usage:
        fig = go.Figure(...)
        fig = apply_koyfin(fig, height=350, title_txt="Revenue Growth")
    """
    t = _get_active_theme()
    if accent is None:
        accent = t["accent"]
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt,
            font=dict(color=t["text"], size=13, family="Inter, sans-serif"),
            x=0,
            pad=dict(l=4)
        )
    if extra_kw:
        kw.update(extra_kw)

    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["text3"], size=10))
    fig.update_yaxes(gridcolor=t["chart_grid"], linecolor=t["border"], tickfont=dict(color=t["text3"], size=10))

    fig.add_shape(
        type="line",
        xref="paper",
        yref="paper",
        x0=0, x1=1, y0=1, y1=1,
        line=dict(color=accent, width=2),
        layer="above"
    )
    return fig


def CL(**kw):
    """
    Theme-aware clean layout for charts.

    Usage:
        fig.update_layout(**CL(height=350))
    """
    t = _get_active_theme()
    base = dict(
        paper_bgcolor=t["chart_paper"],
        plot_bgcolor=t["chart_bg"],
        font=dict(family="Inter,sans-serif", color=t["text2"], size=11),
        margin=dict(t=20, b=40, l=10, r=10),
        xaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            zeroline=False,
            tickcolor=t["border2"],
            tickfont=dict(color=t["text3"])
        ),
        yaxis=dict(
            gridcolor=t["chart_grid"],
            linecolor=t["border"],
            zeroline=False,
            tickcolor=t["border2"],
            tickfont=dict(color=t["text3"])
        ),
        hoverlabel=dict(
            bgcolor=t["bg3"],
            bordercolor=t["accent"],
            font=dict(color=t["text"], family="IBM Plex Mono", size=12)
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base
