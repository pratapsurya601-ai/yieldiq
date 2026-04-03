"""
Chart layout utilities for YieldIQ visualizations.
Provides consistent Koyfin-style dark themes and clean light themes.
"""

def KL(**kw):
    """
    Koyfin-style dark chart layout.
    Apply to figure.update_layout() for consistent dark theme.
    
    Args:
        **kw: Additional layout parameters to override defaults
    
    Returns:
        Dict of plotly layout parameters
    
    Usage:
        fig.update_layout(**KL(height=400, title="My Chart"))
    """
    base = dict(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        font=dict(family="Inter, DM Sans, system-ui, sans-serif", color="#e6edf3", size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#21262d",
            font=dict(color="#e6edf3", family="IBM Plex Mono, monospace", size=12),
            bordercolor="#30363d",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#8b949e", size=11),
        ),
        xaxis=dict(
            gridcolor="#21262d",
            linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10),
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#21262d",
            linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10),
            zeroline=False,
        ),
    )
    base.update(kw)
    return base


def apply_koyfin(fig, accent="#00b4d8", height=280, title_txt="", extra_kw=None):
    """
    One-call upgrade: dark layout + teal accent top border + axis polish.
    
    Args:
        fig: Plotly figure object
        accent: Accent color for top border (default teal)
        height: Chart height in pixels
        title_txt: Optional chart title
        extra_kw: Additional layout kwargs
    
    Returns:
        Modified figure object
    
    Usage:
        fig = go.Figure(...)
        fig = apply_koyfin(fig, accent="#00b4d8", height=350, title_txt="Revenue Growth")
    """
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt, 
            font=dict(color="#e6edf3", size=13, family="Inter, sans-serif"), 
            x=0, 
            pad=dict(l=4)
        )
    if extra_kw:
        kw.update(extra_kw)
    
    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor="#21262d", linecolor="#30363d", tickfont=dict(color="#8b949e", size=10))
    fig.update_yaxes(gridcolor="#21262d", linecolor="#30363d", tickfont=dict(color="#8b949e", size=10))
    
    # Teal top-border accent via annotation line
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
    Clean Light theme layout for charts.
    Professional light theme with subtle grids.
    
    Args:
        **kw: Additional layout parameters to override defaults
    
    Returns:
        Dict of plotly layout parameters
    
    Usage:
        fig.update_layout(**CL(height=350))
    """
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)", 
        plot_bgcolor="#FFFFFF",
        font=dict(family="Inter,sans-serif", color="#475569", size=11),
        margin=dict(t=20, b=40, l=10, r=10),
        xaxis=dict(
            gridcolor="#F1F5F9", 
            linecolor="#E2E8F0", 
            zeroline=False, 
            tickcolor="#CBD5E1", 
            tickfont=dict(color="#64748B")
        ),
        yaxis=dict(
            gridcolor="#F1F5F9", 
            linecolor="#E2E8F0", 
            zeroline=False, 
            tickcolor="#CBD5E1", 
            tickfont=dict(color="#64748B")
        ),
        hoverlabel=dict(
            bgcolor="#FFFFFF", 
            bordercolor="#1D4ED8",
            font=dict(color="#0F172A", family="IBM Plex Mono", size=12)
        ),
    )
    base.update(kw)
    return base
