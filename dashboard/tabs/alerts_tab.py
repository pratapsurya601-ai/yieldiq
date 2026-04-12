"""dashboard/tabs/alerts_tab.py
Alerts tab — moved from app.py.
"""
from __future__ import annotations
import streamlit as st
import time as _time
import alerts as _alerts_mod
from tier_gate import tier, upgrade_prompt


def render() -> None:
    """Render the Alerts tab."""


    _tal_email    = st.session_state.get("auth_email", "")
    _tal_is_guest = not _tal_email or _tal_email == "guest"
    _tal_uid      = None if _tal_is_guest else _alerts_mod._get_user_id(_tal_email)

    if _tal_is_guest or _tal_uid is None:
        st.html("""
        <div style="padding:40px 32px;text-align:center;background:#F8FAFC;
                    border:1.5px solid #E2E8F0;border-radius:14px;margin:20px 0;">
          <div style="font-size:36px;margin-bottom:12px;">&#128276;</div>
          <div style="font-size:17px;font-weight:700;color:#0F172A;margin-bottom:8px;">
            Sign in to use Price Alerts
          </div>
          <div style="font-size:13px;color:#475569;max-width:380px;margin:0 auto 20px;line-height:1.7;">
            Get notified when a stock crosses your model alert threshold or reaches its
            model fair value &#8212; even while you&#8217;re away from the dashboard.
          </div>
        </div>""")
        upgrade_prompt("action_plan", compact=True)

    else:
        _tal_tier     = tier()
        _tal_cap      = _alerts_mod.get_alert_limit(_tal_tier)
        _tal_active   = _alerts_mod.get_active_alerts(_tal_uid)
        _tal_count    = len(_tal_active)
        _tal_cap_str  = "Unlimited" if _tal_cap >= 9_999 else str(_tal_cap)
        _tal_pct      = min(_tal_count / _tal_cap * 100, 100) if _tal_cap < 9_999 else 0
        _tal_bar_clr  = ("#dc2626" if _tal_pct >= 100
                         else "#d97706" if _tal_pct >= 66 else "#059669")

        # ── Header ────────────────────────────────────────────
        _tal_c1, _tal_c2 = st.columns([3, 1])
        with _tal_c1:
            st.html(f"""
            <div style="margin-bottom:18px;">
              <div style="font-size:22px;font-weight:800;color:#0F172A;
                          letter-spacing:-0.02em;margin-bottom:4px;">
                &#128276; Price Alerts
              </div>
              <div style="font-size:13px;color:#475569;">
                Get notified when stocks hit your model alert threshold or model fair value.
              </div>
            </div>""")
        with _tal_c2:
            _tal_tier_clr = {"free":"#8492a6","starter":"#5046e4","premium":"#5046e4","pro":"#059669"}.get(_tal_tier,"#8492a6")
            _tal_bar_html = (
                f'<div style="height:4px;background:#E2E8F0;border-radius:2px;">'
                f'<div style="height:100%;width:{int(_tal_pct)}%;background:{_tal_bar_clr};'
                f'border-radius:2px;"></div></div>'
                if _tal_cap < 9_999 else ""
            )
            st.html(f"""
            <div style="text-align:right;padding-top:12px;">
              <div style="font-size:11px;font-weight:700;color:{_tal_tier_clr};
                          text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px;">
                {_tal_tier.capitalize()} &middot; {_tal_count} / {_tal_cap_str} alerts
              </div>
              {_tal_bar_html}
            </div>""")

        # ── Create new alert ──────────────────────────────────
        st.html('<div style="font-size:11px;font-weight:700;color:#64748B;'
                'text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">'
                'New Alert</div>')

        if _tal_count >= _tal_cap:
            if _tal_tier == "free":
                upgrade_prompt("action_plan", compact=True)
            else:
                st.info(
                    f"You've reached the {_tal_cap}-alert limit for "
                    f"{_tal_tier.capitalize()}. Upgrade to Pro for unlimited alerts."
                )
        else:
            with st.form("_alerts_create_form", clear_on_submit=True):
                _fc1, _fc2, _fc3, _fc4 = st.columns([2, 2, 2, 1])
                with _fc1:
                    _new_ticker = st.text_input(
                        "Ticker", placeholder="e.g. AAPL",
                        help="Stock ticker symbol (e.g. AAPL, MSFT, GOOGL, NVDA)"
                    ).strip().upper()
                with _fc2:
                    _new_type = st.selectbox(
                        "Alert type",
                        options=list(_alerts_mod.ALERT_TYPE_LABELS.keys()),
                        format_func=lambda k: _alerts_mod.ALERT_TYPE_LABELS[k],
                        help=(
                            "above: triggers when price rises above target\n"
                            "below: triggers when price falls below target\n"
                            "iv_reached: triggers when price falls to your IV estimate"
                        ),
                    )
                with _fc3:
                    _new_price = st.number_input(
                        "Target price", min_value=0.01, value=100.00, step=1.0,
                        help="Price level that will trigger this alert"
                    )
                with _fc4:
                    st.html("<div style='height:28px'></div>")
                    _create_btn = st.form_submit_button(
                        "Add alert", width='stretch', type="primary"
                    )

                if _create_btn:
                    _al_res = _alerts_mod.create_alert(
                        _tal_uid, _new_ticker, _new_type, _new_price, _tal_tier
                    )
                    if _al_res["ok"]:
                        _t = _new_ticker.replace(".NS", "").replace(".BO", "")
                        st.success(f"Alert set — we'll notify you when {_t} hits your target")
                        st.rerun()
                    else:
                        st.error(_al_res["error"])

        st.html('<div style="height:12px"></div>')

        # ── Active alerts list ────────────────────────────────
        st.html(
            '<div style="font-size:11px;font-weight:700;color:#64748B;'
            'text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">'
            f'Active Alerts ({_tal_count})</div>'
        )
        if not _tal_active:
            st.html("""
            <div style="padding:20px;text-align:center;background:#F8FAFC;
                        border:1px solid #E2E8F0;border-radius:10px;
                        color:#94A3B8;font-size:13px;">
              No active alerts. Create one above to get started.
            </div>""")
        else:
            for _al in _tal_active:
                _al_type_lbl = _alerts_mod.ALERT_TYPE_LABELS.get(_al["alert_type"], _al["alert_type"])
                _al_clr = ("#059669" if _al["alert_type"] == "above"
                           else "#1D4ED8" if _al["alert_type"] == "iv_reached"
                           else "#DC2626")
                _al_col_l, _al_col_r = st.columns([10, 1])
                with _al_col_l:
                    st.html(f"""
                    <div style="display:flex;align-items:center;gap:14px;
                                padding:12px 16px;background:#FFFFFF;
                                border:1px solid #E2E8F0;border-radius:10px;
                                border-left:3px solid {_al_clr};">
                      <div style="font-size:15px;font-weight:800;color:#0F172A;
                                  font-family:'IBM Plex Mono',monospace;min-width:80px;">
                        {_al['ticker']}
                      </div>
                      <div style="width:1px;height:28px;background:#E2E8F0;"></div>
                      <div style="flex:1;">
                        <div style="font-size:12px;font-weight:600;color:{_al_clr};">
                          {_al_type_lbl}
                        </div>
                        <div style="font-size:13px;color:#0F172A;font-weight:700;
                                    font-family:'IBM Plex Mono',monospace;">
                          ${_al['target_price']:,.2f}
                        </div>
                      </div>
                      <div style="font-size:11px;color:#94A3B8;">
                        Created {_al['created_at'][:10]}
                      </div>
                    </div>""")
                with _al_col_r:
                    if st.button("✕", key=f"_del_alert_{_al['id']}",
                                 help="Delete this alert",
                                 width='stretch'):
                        _del_res = _alerts_mod.delete_alert(_al["id"], _tal_uid)
                        if _del_res["ok"]:
                            st.rerun()
                        else:
                            st.error(_del_res["error"])

        st.html('<div style="height:20px"></div>')

        # ── Recently triggered ────────────────────────────────
        _tal_triggered = _alerts_mod.get_triggered_alerts(_tal_uid, hours=24)
        if _tal_triggered:
            st.html(
                '<div style="font-size:11px;font-weight:700;color:#64748B;'
                'text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;">'
                f'Triggered in the last 24 h ({len(_tal_triggered)})</div>'
            )
            for _tr in _tal_triggered:
                _tr_lbl = _alerts_mod.ALERT_TYPE_LABELS.get(_tr["alert_type"], _tr["alert_type"])
                st.html(f"""
                <div style="display:flex;align-items:center;gap:14px;
                            padding:10px 16px;background:#FFFBEB;
                            border:1px solid #FDE68A;border-radius:10px;
                            margin-bottom:6px;">
                  <span style="font-size:15px;">&#128276;</span>
                  <div style="flex:1;">
                    <span style="font-weight:700;color:#0F172A;">{_tr['ticker']}</span>
                    <span style="color:#475569;font-size:13px;">
                      &mdash; {_tr_lbl} ${_tr['target_price']:,.2f}
                    </span>
                  </div>
                  <div style="font-size:11px;color:#92400E;">
                    {_tr['triggered_at'][:16].replace('T', ' ')} UTC
                  </div>
                </div>""")

            if st.button("Clear triggered alerts", key="_al_clear_triggered"):
                _alerts_mod.delete_all_triggered(_tal_uid)
                st.session_state["_al_fired"] = []
                st.rerun()

        # ── Manual re-check ───────────────────────────────────
        st.html('<div style="height:8px"></div>')
        if st.button("&#128260; Check alerts now", key="_al_check_now",
                     help="Fetch live prices and check all alerts immediately"):
            with st.spinner("Checking prices\u2026"):
                _manual_fired = _alerts_mod.check_alerts(_tal_uid)
            st.session_state["_al_last_check_ts"] = _time.time()
            st.session_state["_al_fired"] = (
                st.session_state.get("_al_fired", []) + _manual_fired
            )
            if _manual_fired:
                st.success(f"{len(_manual_fired)} alert(s) triggered!")
            else:
                st.success("All prices within range \u2014 no alerts triggered.")
            st.rerun()

