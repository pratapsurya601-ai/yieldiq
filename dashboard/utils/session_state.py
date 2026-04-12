# dashboard/utils/session_state.py
# Centralised session state initialisation for YieldIQ
# Call init_session_state() at the top of app.py before any rendering
from __future__ import annotations
import streamlit as st


def init_session_state():
    """
    Initialise all session state keys with safe defaults.
    Idempotent — safe to call on every rerun.
    """

    # ── Mode toggles ──────────────────────────────────────────────
    if "mode" not in st.session_state:
        st.session_state.mode = "simple"          # "simple" | "pro"

    if "learn_mode" not in st.session_state:
        st.session_state.learn_mode = True        # True by default

    # ── Onboarding ────────────────────────────────────────────────
    if "onboarding_complete" not in st.session_state:
        st.session_state.onboarding_complete = False

    if "investor_type" not in st.session_state:
        st.session_state.investor_type = None     # "beginner" | "intermediate" | "advanced"

    # ── Navigation ────────────────────────────────────────────────
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "Home"

    if "active_portfolio_tab" not in st.session_state:
        st.session_state.active_portfolio_tab = "Holdings"

    # ── Analysis state ────────────────────────────────────────────
    if "last_ticker" not in st.session_state:
        st.session_state.last_ticker = None

    if "analyses_today" not in st.session_state:
        st.session_state.analyses_today = 0

    if "analysis_limit" not in st.session_state:
        st.session_state.analysis_limit = 5       # Free tier default

    # ── User tier ─────────────────────────────────────────────────
    if "user_tier" not in st.session_state:
        st.session_state.user_tier = "free"       # "free" | "starter" | "pro"

    # ── Backward compatibility ────────────────────────────────────
    # Map old keys to new keys
    if "main_tab" not in st.session_state:
        st.session_state.main_tab = "stock"
    if "pro_mode" not in st.session_state:
        st.session_state.pro_mode = False


def is_pro() -> bool:
    """Returns True if user has Pro mode ON."""
    return st.session_state.get("mode") == "pro" or st.session_state.get("pro_mode", False)


def is_starter_or_above() -> bool:
    return st.session_state.get("user_tier") in ("starter", "pro") or st.session_state.get("tier") in ("starter", "pro")


def is_learn_mode() -> bool:
    return st.session_state.get("learn_mode", True)


def get_investor_type() -> str:
    return st.session_state.get("investor_type", "beginner")


def toggle_mode():
    """Toggle between simple and pro mode."""
    current = st.session_state.get("mode", "simple")
    st.session_state.mode = "pro" if current == "simple" else "simple"
    st.session_state.pro_mode = st.session_state.mode == "pro"


def toggle_learn_mode():
    st.session_state.learn_mode = not st.session_state.get("learn_mode", True)
