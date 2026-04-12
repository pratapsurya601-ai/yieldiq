# dashboard/ui/components/blur_gate.py
# ═══════════════════════════════════════════════════════════════
# Blur gate — shows number SHAPE blurred for free users
# Paid users see the actual value. Free users see the blur + "Unlock"
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_blurred_value(
    label: str,
    value: str,
    tier: str = None,
    unlock_text: str = "Unlock →",
    signals_seen: int = 4,
    signals_total: int = 12,
) -> None:
    """
    Show a metric value — blurred for free users, clear for paid.
    The blur shows the NUMBER SHAPE, not a placeholder block.
    """
    if tier is None:
        tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))

    if tier in ("starter", "pro"):
        # Paid users see the real value
        st.html(
            f'<div style="margin-bottom:8px;">'
            f'<div style="font-size:10px;color:#94A3B8;text-transform:uppercase;'
            f'letter-spacing:0.08em;font-weight:700;margin-bottom:4px;">{label}</div>'
            f'<div style="font-size:24px;font-weight:700;color:#0F172A;'
            f'font-family:IBM Plex Mono,monospace;">{value}</div>'
            f'</div>'
        )
    else:
        # Free users see blurred number shape + unlock link
        st.html(
            f'<div style="margin-bottom:8px;">'
            f'<div style="font-size:10px;color:#94A3B8;text-transform:uppercase;'
            f'letter-spacing:0.08em;font-weight:700;margin-bottom:4px;">{label}</div>'
            f'<div style="position:relative;display:inline-block;">'
            f'<span style="font-size:24px;font-weight:700;color:#0F172A;'
            f'font-family:IBM Plex Mono,monospace;'
            f'filter:blur(6px);user-select:none;pointer-events:none;">{value}</span>'
            f'<span style="position:absolute;top:50%;right:-70px;transform:translateY(-50%);">'
            f'<a style="font-size:11px;color:#1D4ED8;font-weight:600;text-decoration:none;">'
            f'{unlock_text}</a></span>'
            f'</div>'
            f'<div style="font-size:10px;color:#94A3B8;margin-top:4px;">'
            f'Seeing {signals_seen} of {signals_total} signals. This is the key number.</div>'
            f'</div>'
        )


def render_blurred_metric(
    label: str,
    value: str,
    tier: str = None,
) -> None:
    """Simpler blur — just the metric, no signal count."""
    if tier is None:
        tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))

    if tier in ("starter", "pro"):
        st.html(
            f'<div style="font-size:10px;color:#94A3B8;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:2px;">{label}</div>'
            f'<div style="font-size:18px;font-weight:700;color:#0F172A;'
            f'font-family:IBM Plex Mono,monospace;">{value}</div>'
        )
    else:
        st.html(
            f'<div style="font-size:10px;color:#94A3B8;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:2px;">{label}</div>'
            f'<div style="font-size:18px;font-weight:700;color:#0F172A;'
            f'font-family:IBM Plex Mono,monospace;'
            f'filter:blur(5px);user-select:none;">{value}</div>'
        )
