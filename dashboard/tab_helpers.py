# dashboard/tab_helpers.py
# ═══════════════════════════════════════════════════════════════
# Shared display helpers used by app.py and the tabs/ modules.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def _get_active_theme() -> dict:
    """Read the active theme dict from session_state."""
    import importlib.util as _ilu2, pathlib as _pl2
    _tp = _pl2.Path(__file__).resolve().parent / "ui" / "themes.py"
    _ts = _ilu2.spec_from_file_location("_yiq_th_tab", _tp)
    _tm = _ilu2.module_from_spec(_ts); _ts.loader.exec_module(_tm)
    _name = st.session_state.get("theme", "slate")
    return _tm.get_theme(_name)


# ── Number formatters ──────────────────────────────────────────
def fmt(v, sym, d=2):
    a = abs(v)
    if a >= 1e12: return f"{sym}{v/1e12:,.2f}T"
    if a >= 1e9:  return f"{sym}{v/1e9:,.2f}B"
    if a >= 1e6:  return f"{sym}{v/1e6:,.2f}M"
    return f"{sym}{v:,.{d}f}"

def fmts(v, sym): return f"{sym}{v:,.2f}"


# ── Theme-aware chart helpers ─────────────────────────────────
def KL(**kw):
    """Theme-aware chart layout dict."""
    t = _get_active_theme()
    base = dict(
        paper_bgcolor=t["chart_paper"],
        plot_bgcolor=t["chart_bg"],
        font=dict(family="Inter, DM Sans, system-ui, sans-serif",
                  color=t["chart_font"], size=11),
        margin=dict(l=48, r=24, t=48, b=44),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=t["bg3"],
            font=dict(color=t["text"],
                      family="IBM Plex Mono, monospace", size=12),
            bordercolor=t["border2"],
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor=t["border"],
            borderwidth=1,
            font=dict(color=t["text2"], size=11),
        ),
        xaxis=dict(
            gridcolor=t["chart_grid"], linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10), zeroline=False,
        ),
        yaxis=dict(
            gridcolor=t["chart_grid"], linecolor=t["border"],
            tickfont=dict(color=t["text3"], size=10), zeroline=False,
        ),
        colorway=[t["chart_line"], t["chart_accent2"], t["chart_accent3"],
                  t["chart_bar_pos"], t["chart_bar_neg"]],
    )
    base.update(kw)
    return base


def apply_koyfin(fig, accent=None, height=280,
                 title_txt="", extra_kw=None):
    """One-call upgrade: themed layout + accent top border + axis polish."""
    t = _get_active_theme()
    if accent is None:
        accent = t["accent"]
    kw = dict(height=height)
    if title_txt:
        kw["title"] = dict(
            text=title_txt,
            font=dict(color=t["text"], size=13, family="Inter, sans-serif"),
            x=0, pad=dict(l=4),
        )
    if extra_kw:
        kw.update(extra_kw)
    fig.update_layout(**KL(**kw))
    fig.update_xaxes(gridcolor=t["chart_grid"], linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))
    fig.update_yaxes(gridcolor=t["chart_grid"], linecolor=t["border"],
                     tickfont=dict(color=t["text3"], size=10))
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
