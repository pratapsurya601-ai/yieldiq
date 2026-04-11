"""
Chart layout utilities for YieldIQ visualizations.
Bloomberg Terminal / Koyfin quality — theme-aware.

Usage:
    from utils.chart_layouts import KL, CL, apply_koyfin, style_fig, T

    fig = go.Figure(go.Bar(x=..., y=..., marker_color=T()["chart_bar_pos"]))
    fig = apply_koyfin(fig, height=350, title_txt="Revenue Growth")

    # Or for simpler charts:
    fig.update_layout(**CL(height=300))

    # One-shot style any figure:
    style_fig(fig, height=280)
"""
import streamlit as st


# ═══════════════════════════════════════════════════════════════
# THEME ACCESS
# ═══════════════════════════════════════════════════════════════

def _get_active_theme() -> dict:
    """Read the active theme dict from session_state."""
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent.parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_cl", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    _name = st.session_state.get("theme", "slate")
    return _tm.get_theme(_name)


def T() -> dict:
    """Public shorthand — get current theme dict for direct color access.

    Usage:
        t = T()
        fig.add_trace(go.Bar(..., marker_color=t["chart_bar_pos"]))
    """
    return _get_active_theme()


def is_light() -> bool:
    """True if current theme is a light theme."""
    return not _get_active_theme().get("dark", True)


# ═══════════════════════════════════════════════════════════════
# CORE LAYOUT BUILDERS
# ═══════════════════════════════════════════════════════════════

def _grid() -> str:
    """Theme-aware subtle gridline color."""
    return "rgba(0,0,0,0.04)" if is_light() else _get_active_theme()["chart_grid"]


def _paper() -> str:
    """Chart paper (outer) background."""
    return "rgba(0,0,0,0)" if is_light() else _get_active_theme()["chart_paper"]


def _plot() -> str:
    """Chart plot (inner) background."""
    return "#FFFFFF" if is_light() else _get_active_theme()["chart_bg"]


def _hover_bg() -> str:
    """Hover label background."""
    return "#FFFFFF" if is_light() else _get_active_theme()["bg3"]


def KL(**kw):
    """
    Koyfin Layout — full-featured themed chart layout.

    Usage:
        fig.update_layout(**KL(height=400, title="My Chart"))
    """
    t = _get_active_theme()
    g = _grid()
    base = dict(
        paper_bgcolor=_paper(),
        plot_bgcolor=_plot(),
        font=dict(family="Inter, system-ui, sans-serif", color=t["chart_font"], size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=_hover_bg(),
            font=dict(color=t["text"], family="IBM Plex Mono, monospace", size=12),
            bordercolor=t["border2"],
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(color=t["text2"], size=11),
        ),
        xaxis=dict(
            gridcolor=g, linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False, showgrid=True, gridwidth=1,
        ),
        yaxis=dict(
            gridcolor=g, linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10),
            zeroline=False, showgrid=True, gridwidth=1,
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base


def CL(**kw):
    """
    Clean Layout — compact themed layout for small/embedded charts.

    Usage:
        fig.update_layout(**CL(height=250))
    """
    t = _get_active_theme()
    g = _grid()
    base = dict(
        paper_bgcolor=_paper(),
        plot_bgcolor=_plot(),
        font=dict(family="Inter,sans-serif", color=t["text2"], size=11),
        margin=dict(t=20, b=40, l=10, r=10),
        xaxis=dict(
            gridcolor=g, linecolor=t["border"],
            zeroline=False, tickcolor=t["border2"],
            tickfont=dict(color=t["text3"]),
            showgrid=True, gridwidth=1,
        ),
        yaxis=dict(
            gridcolor=g, linecolor=t["border"],
            zeroline=False, tickcolor=t["border2"],
            tickfont=dict(color=t["text3"]),
            showgrid=True, gridwidth=1,
        ),
        hoverlabel=dict(
            bgcolor=_hover_bg(),
            bordercolor=t["accent"],
            font=dict(color=t["text"], family="IBM Plex Mono", size=12)
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════
# APPLY FUNCTIONS — upgrade any figure in place
# ═══════════════════════════════════════════════════════════════

def apply_koyfin(fig, accent=None, height=280, title_txt="", extra_kw=None):
    """
    Premium upgrade: themed layout + accent top border + axis polish.
    The signature YieldIQ chart treatment — matches Koyfin/Bloomberg style.

    Usage:
        fig = go.Figure(...)
        fig = apply_koyfin(fig, height=350, title_txt="Revenue Growth")
    """
    t = _get_active_theme()
    g = _grid()
    if accent is None:
        accent = t["accent"]
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt,
            font=dict(color=t["text"], size=13, family="Inter, sans-serif"),
            x=0, pad=dict(l=4)
        )
    if extra_kw:
        kw.update(extra_kw)

    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor=g, linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))
    fig.update_yaxes(gridcolor=g, linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))

    # Signature accent top line
    fig.add_shape(
        type="line", xref="paper", yref="paper",
        x0=0, x1=1, y0=1, y1=1,
        line=dict(color=accent, width=2),
        layer="above"
    )
    return fig


def style_fig(fig, height=280, title_txt="", compact=False):
    """
    Quick one-call style for ANY figure. No accent border.
    Use this for charts that don't need the full apply_koyfin treatment.

    Usage:
        style_fig(fig, height=260, title_txt="FCF Yield")
    """
    t = _get_active_theme()
    g = _grid()
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt,
            font=dict(color=t["text"], size=13, family="Inter, sans-serif"),
            x=0, pad=dict(l=4)
        )
    layout_fn = CL if compact else KL
    fig.update_layout(**layout_fn(**kw))
    fig.update_xaxes(gridcolor=g, linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))
    fig.update_yaxes(gridcolor=g, linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))
    return fig


# ═══════════════════════════════════════════════════════════════
# COLOR HELPERS — avoid hardcoded colors in chart code
# ═══════════════════════════════════════════════════════════════

def bar_colors(values=None) -> dict:
    """Get positive/negative bar colors from theme.

    Returns dict with 'pos', 'neg', 'neu' keys.
    If values list provided, returns a list of colors per value.

    Usage:
        bc = bar_colors()
        fig = go.Bar(marker_color=bc["pos"])

        # Or per-value coloring:
        colors = bar_colors(values=[10, -5, 3, -2])
        fig = go.Bar(marker_color=colors)
    """
    t = _get_active_theme()
    if values is not None:
        return [t["chart_bar_pos"] if v >= 0 else t["chart_bar_neg"] for v in values]
    return {
        "pos": t["chart_bar_pos"],
        "neg": t["chart_bar_neg"],
        "neu": t.get("chart_bar_neu", t["chart_line"]),
        "primary": t["chart_line"],
        "accent2": t["chart_accent2"],
        "accent3": t["chart_accent3"],
    }


def signal_colors() -> dict:
    """Get signal-level colors (positive, negative, warning, neutral).

    Usage:
        sc = signal_colors()
        color = sc["positive"] if value > 0 else sc["negative"]
    """
    t = _get_active_theme()
    return {
        "positive": t["positive"],
        "positive_bg": t["positive_bg"],
        "negative": t["negative"],
        "negative_bg": t["negative_bg"],
        "warning": t["warning"],
        "warning_bg": t["warning_bg"],
        "neutral": t["neutral"],
        "neutral_bg": t["neutral_bg"],
        "accent": t["accent"],
        "text": t["text"],
        "text2": t["text2"],
        "text3": t["text3"],
        "border": t["border"],
    }


def annotation_font(color=None, size=11) -> dict:
    """Themed annotation font dict.

    Usage:
        fig.add_hline(..., annotation_font=annotation_font("#DC2626"))
    """
    t = _get_active_theme()
    return dict(
        color=color or t["text2"],
        size=size,
        family="IBM Plex Mono, monospace",
    )


def plotly_config(filename="chart") -> dict:
    """Standard Plotly chart config — clean mode bar.

    Usage:
        st.plotly_chart(fig, config=plotly_config("revenue_chart"))
    """
    return {
        "displayModeBar": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "toImageButtonOptions": {"filename": filename, "scale": 2},
    }
