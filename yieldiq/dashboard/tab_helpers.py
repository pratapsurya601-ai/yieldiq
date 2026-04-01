# dashboard/tab_helpers.py
# ═══════════════════════════════════════════════════════════════
# Shared display helpers used by app.py and the tabs/ modules.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


# ── Number formatters ──────────────────────────────────────────
def fmt(v, sym, d=2):
    a = abs(v)
    if a >= 1e12: return f"{sym}{v/1e12:,.2f}T"
    if a >= 1e9:  return f"{sym}{v/1e9:,.2f}B"
    if a >= 1e6:  return f"{sym}{v/1e6:,.2f}M"
    return f"{sym}{v:,.{d}f}"

def fmts(v, sym): return f"{sym}{v:,.2f}"


# ── Koyfin-style dark chart helpers ───────────────────────────
def KL(**kw):
    """Base Koyfin dark layout dict."""
    base = dict(
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        font=dict(family="Inter, DM Sans, system-ui, sans-serif",
                  color="#e6edf3", size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#21262d",
            font=dict(color="#e6edf3",
                      family="IBM Plex Mono, monospace", size=12),
            bordercolor="#30363d",
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(color="#8b949e", size=11),
        ),
        xaxis=dict(
            gridcolor="#21262d", linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10), zeroline=False,
        ),
        yaxis=dict(
            gridcolor="#21262d", linecolor="#30363d",
            tickfont=dict(color="#8b949e", size=10), zeroline=False,
        ),
    )
    base.update(kw)
    return base


def apply_koyfin(fig, accent="#00b4d8", height=280,
                 title_txt="", extra_kw=None):
    """One-call upgrade: dark layout + teal accent top border + axis polish."""
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt,
            font=dict(color="#e6edf3", size=13, family="Inter, sans-serif"),
            x=0, pad=dict(l=4),
        )
    if extra_kw:
        kw.update(extra_kw)
    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor="#21262d", linecolor="#30363d",
                     tickfont=dict(color="#8b949e", size=10))
    fig.update_yaxes(gridcolor="#21262d", linecolor="#30363d",
                     tickfont=dict(color="#8b949e", size=10))
    fig.add_shape(
        type="line", xref="paper", yref="paper",
        x0=0, x1=1, y0=1, y1=1,
        line=dict(color=accent, width=2),
        layer="above",
    )
    return fig


# ── Card wrappers ──────────────────────────────────────────────
def ccard(title, accent="#1D4ED8"):
    st.html(
        f'''<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
            padding:20px 24px 6px;margin-bottom:16px;position:relative;overflow:hidden;
            box-shadow:0 1px 4px rgba(15,23,42,0.06),0 1px 2px rgba(15,23,42,0.04);">
        <div style="position:absolute;top:0;left:0;right:0;height:3px;
            background:linear-gradient(90deg,{accent} 0%,rgba(6,182,212,0.6) 60%,transparent 100%);"></div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:600;
            letter-spacing:0.12em;text-transform:uppercase;color:#94A3B8;
            margin-bottom:14px;display:flex;align-items:center;gap:8px;">
          <span style="display:inline-block;width:5px;height:5px;border-radius:50%;
              background:{accent};flex-shrink:0;opacity:0.8;"></span>{title}</div>''',
    )


def ccard_end():
    st.html("</div>")


# ── SVG score dial ─────────────────────────────────────────────
def render_score_dial(score: float, max_score: float, label: str,
                      color: str, size: int = 120) -> str:
    """Circular SVG score dial — Bloomberg Intelligence style."""
    pct     = score / max_score if max_score else 0
    circumf = 283.0   # 2 * pi * r(45)
    dash    = pct * circumf
    gap     = circumf - dash
    track   = "#21262d"
    svg  = '<div style="display:inline-flex;flex-direction:column;align-items:center;">'
    svg += f'<svg width="{size}" height="{size}" viewBox="0 0 100 100">'
    svg += (f'<circle cx="50" cy="50" r="48" fill="none" stroke="{color}"'
            f' stroke-width="0.5" opacity="0.15"/>')
    svg += f'<circle cx="50" cy="50" r="45" fill="none" stroke="{track}" stroke-width="9"/>'
    svg += (f'<circle cx="50" cy="50" r="45" fill="none" stroke="{color}" stroke-width="9"'
            f' stroke-linecap="round" stroke-dasharray="{dash:.1f} {gap:.1f}"'
            f' transform="rotate(-90 50 50)"/>')
    svg += (f'<text x="50" y="46" text-anchor="middle" dominant-baseline="middle"'
            f' font-family="IBM Plex Mono, monospace" font-size="22"'
            f' font-weight="700" fill="{color}">{score:.0f}</text>')
    svg += (f'<text x="50" y="63" text-anchor="middle" dominant-baseline="middle"'
            f' font-family="IBM Plex Mono, monospace" font-size="10"'
            f' fill="#8b949e">/ {max_score:.0f}</text>')
    svg += '</svg>'
    if label:
        svg += (f'<div style="font-size:10px;font-weight:700;color:#8b949e;'
                f'text-transform:uppercase;letter-spacing:0.12em;'
                f'text-align:center;margin-top:5px;">{label}</div>')
    svg += '</div>'
    return svg
