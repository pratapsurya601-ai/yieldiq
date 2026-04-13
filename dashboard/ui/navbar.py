# dashboard/ui/navbar.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ Top Navigation Bar — 5-tab horizontal pill nav
# Replaces sidebar navigation. Returns active tab name for routing.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


_TABS = [
    ("🏠", "Home"),
    ("🔍", "Discover"),
    ("📊", "Search"),
    ("💼", "Portfolio"),
    ("👤", "Account"),
]


def render_navbar() -> str:
    """Renders top navigation bar. Returns active tab name."""

    # ── Inject navbar CSS ─────────────────────────────────────
    st.markdown("""<style>
    .yiq-navbar {
        display: flex; justify-content: center; gap: 4px;
        padding: 6px 8px; background: #F1F5F9; border-radius: 14px;
        margin: 0 auto 16px; max-width: 600px;
    }
    .yiq-nav-btn {
        flex: 1; text-align: center; padding: 10px 8px;
        border-radius: 10px; font-size: 12px; font-weight: 600;
        font-family: Inter, sans-serif; cursor: pointer;
        transition: all 0.15s; border: none; background: transparent;
        color: #64748B;
    }
    .yiq-nav-btn:hover { background: #E2E8F0; color: #0F172A; }
    .yiq-nav-btn.active {
        background: #0F172A; color: #FFFFFF;
        box-shadow: 0 2px 8px rgba(15,23,42,0.15);
    }
    .yiq-nav-btn.search-btn {
        background: linear-gradient(135deg, #1D4ED8, #06B6D4);
        color: white; font-weight: 700;
    }
    .yiq-nav-btn.search-btn.active {
        background: linear-gradient(135deg, #1E40AF, #0891B2);
        box-shadow: 0 2px 12px rgba(29,78,216,0.3);
    }
    </style>""", unsafe_allow_html=True)

    # ── Get current active tab ────────────────────────────────
    active = st.session_state.get("active_tab", "Home")

    # ── Single row of functional nav buttons ─────────────────
    cols = st.columns(len(_TABS))
    for i, (icon, label) in enumerate(_TABS):
        with cols[i]:
            btn_type = "primary" if active == label else "secondary"
            if st.button(
                f"{icon} {label}",
                key=f"nav_{label}",
                use_container_width=True,
                type=btn_type,
            ):
                st.session_state.active_tab = label
                _TAB_MAP = {
                    "Home": "morning_brief",
                    "Discover": "yieldiq50",
                    "Search": "stock",
                    "Portfolio": "portfolio",
                    "Account": "about",
                }
                st.session_state.main_tab = _TAB_MAP.get(label, "stock")
                st.rerun()

    # ── Usage meter for free users ────────────────────────────
    _tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))
    if _tier == "free":
        used = st.session_state.get("analyses_today", 0)
        limit = st.session_state.get("analysis_limit", 5)
        pct = min(used / limit * 100, 100) if limit > 0 else 100
        if pct >= 100:
            bar_c = "#DC2626"
        elif pct >= 60:
            bar_c = "#D97706"
        else:
            bar_c = "#1D4ED8"
        st.html(
            f'<div style="max-width:600px;margin:0 auto 12px;padding:0 8px;">'
            f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#94A3B8;margin-bottom:3px;">'
            f'<span>{used}/{limit} analyses today</span>'
            f'<span style="color:{bar_c};font-weight:700;">{100-pct:.0f}% remaining</span></div>'
            f'<div style="height:4px;background:#F1F5F9;border-radius:2px;">'
            f'<div style="height:100%;width:{pct:.0f}%;background:{bar_c};border-radius:2px;"></div>'
            f'</div></div>'
        )

    # ── Notification bell + Mode toggles ─────────────────────
    _bell_c, _mode_c1, _mode_c2 = st.columns([1, 1, 1])
    with _bell_c:
        try:
            from utils.notifications import render_notification_dropdown
            render_notification_dropdown()
        except Exception:
            pass
    with _mode_c1:
        _learn = st.session_state.get("learn_mode", True)
        if st.checkbox("Learn Mode", value=_learn, key="_nav_learn"):
            st.session_state.learn_mode = True
        else:
            st.session_state.learn_mode = False
    with _mode_c2:
        if _tier in ("pro", "starter"):
            _pro = st.session_state.get("mode", "simple") == "pro"
            if st.checkbox("Pro Mode", value=_pro, key="_nav_pro"):
                st.session_state.mode = "pro"
                st.session_state.pro_mode = True
            else:
                st.session_state.mode = "simple"
                st.session_state.pro_mode = False

    return active
