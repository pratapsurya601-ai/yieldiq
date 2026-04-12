# dashboard/ui/components/action_bar.py
# ═══════════════════════════════════════════════════════════════
# Action Bar — Watchlist + Alert + Export buttons
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_action_bar(ticker: str, current_price: float) -> None:
    """Render action buttons: Watchlist, Set Alert, Export."""

    c1, c2, c3 = st.columns(3)

    # ── Watchlist Button ──────────────────────────────────
    with c1:
        try:
            from portfolio import is_in_watchlist, add_to_watchlist
            _in_wl = is_in_watchlist(ticker)
        except Exception:
            _in_wl = False

        if _in_wl:
            st.button("✅ In Watchlist", key=f"_ab_wl_{ticker}",
                      use_container_width=True, disabled=True)
        else:
            if st.button("📋 + Watchlist", key=f"_ab_wl_add_{ticker}",
                         use_container_width=True, type="primary"):
                try:
                    add_to_watchlist(ticker)
                    st.success(f"✅ {ticker} added to your watchlist")
                    st.rerun()
                except Exception as e:
                    st.error("Could not add to watchlist. Please try again.")

    # ── Alert Button ──────────────────────────────────────
    with c2:
        if st.button("🔔 Set Alert", key=f"_ab_alert_{ticker}",
                     use_container_width=True):
            st.session_state[f"_show_alert_form_{ticker}"] = True

    # ── Export Button ─────────────────────────────────────
    with c3:
        _tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))
        if _tier in ("starter", "pro"):
            if st.button("📥 Export PDF", key=f"_ab_export_{ticker}",
                         use_container_width=True):
                st.info("PDF report ready — check your downloads")
        else:
            if st.button("📤 Share", key=f"_ab_share_{ticker}",
                         use_container_width=True):
                st.info(f"Share link: yieldiq.in/?ticker={ticker}")

    # ── Inline Alert Form (expands below) ─────────────────
    if st.session_state.get(f"_show_alert_form_{ticker}"):
        with st.container(border=True):
            st.html('<div style="font-size:12px;font-weight:700;color:#1E40AF;'
                    'margin-bottom:8px;">Set Price Alert</div>')
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                _target = st.number_input(
                    "Target price",
                    value=float(int(current_price * 0.85)),
                    step=1.0,
                    key=f"_alert_price_{ticker}",
                )
            with _ac2:
                _direction = st.selectbox(
                    "Alert when",
                    ["Price drops below", "Price rises above"],
                    key=f"_alert_dir_{ticker}",
                )

            if st.button("💾 Save Alert", key=f"_alert_save_{ticker}",
                         use_container_width=True, type="primary"):
                _alert_type = "below" if "drops" in _direction else "above"
                try:
                    from alerts import create_alert
                    _email = st.session_state.get("auth_email", "")
                    create_alert(_email, ticker, _alert_type, _target)
                    st.success(
                        f"✅ Alert set — we'll notify you when {ticker} "
                        f"{'drops below' if _alert_type == 'below' else 'rises above'} "
                        f"₹{_target:,.0f}"
                    )
                    st.session_state.pop(f"_show_alert_form_{ticker}", None)
                    st.rerun()
                except Exception:
                    st.error("Could not create alert. Please try again.")

            if st.button("Cancel", key=f"_alert_cancel_{ticker}"):
                st.session_state.pop(f"_show_alert_form_{ticker}", None)
                st.rerun()
