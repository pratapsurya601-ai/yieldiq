"""dashboard/ui/disclaimer.py
Compliance disclaimer gate — shown once per session; persisted in localStorage.
Moved from app.py.
"""
from __future__ import annotations
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as _stc


_DISCLAIMER_TEXT = """\
YieldIQ is a quantitative research tool, not a registered investment adviser. \
All outputs are mathematical model results based on publicly available data and \
do not constitute personalized investment advice under the Investment Advisers Act of 1940.

YieldIQ is a quantitative research tool for **informational and educational purposes only**.
It is **NOT** investment advice and does **NOT** constitute a recommendation to buy, sell,
or hold any security.

**YieldIQ LLC is not registered as an Investment Adviser** under the Investment Advisers
Act of 1940 or any applicable state securities law.

All model outputs represent mathematical estimates based on publicly available financial
data. They do not account for your personal financial situation, risk tolerance, tax
circumstances, or investment objectives.

Always consult a **qualified, licensed financial professional** before making any
investment decisions. Past model accuracy is not indicative of future results.\
"""

_DISCLAIMER_LS_KEY  = "yiq_disclaimer_ts"
_DISCLAIMER_VALIDITY_DAYS = 365


def _disclaimer_write_localstorage() -> None:
    """Inject a zero-height script that stamps acceptance into localStorage."""
    import streamlit.components.v1 as _stc
    _stc.html(
        f"""<script>
(function(){{
  try {{ localStorage.setItem('{_DISCLAIMER_LS_KEY}', Date.now().toString()); }}
  catch(e) {{}}
}})();
</script>""",
        height=0,
    )


def _disclaimer_check_localstorage() -> None:
    """
    Inject a zero-height script that reads localStorage.
    If a valid acceptance stamp is found it appends ?da=1 to the parent URL,
    which Streamlit reads on the next rerun via st.query_params.
    """
    import streamlit.components.v1 as _stc
    _stc.html(
        f"""<script>
(function(){{
  try {{
    var ts = localStorage.getItem('{_DISCLAIMER_LS_KEY}');
    if (ts) {{
      var age = Date.now() - parseInt(ts, 10);
      if (age < {_DISCLAIMER_VALIDITY_DAYS} * 86400000) {{
        var u = new URL(window.parent.location.href);
        if (u.searchParams.get('da') !== '1') {{
          u.searchParams.set('da', '1');
          window.parent.location.replace(u.toString());
        }}
      }}
    }}
  }} catch(e) {{}}
}})();
</script>""",
        height=0,
    )


def show_disclaimer_if_needed() -> None:
    """
    Gate the entire app behind a one-time compliance disclaimer.

    Flow:
      1. If ?da=1 is in the URL (set by localStorage check), mark session accepted.
      2. If session already accepted → return immediately.
      3. Inject localStorage reader; if valid stamp exists it reloads with ?da=1.
      4. Show the disclaimer container with checkbox + button.
      5. Call st.stop() so nothing else renders until accepted.
    """
    # ── Fast-path: localStorage redirect already happened ────────
    if not st.session_state.get("_force_disclaimer"):
        try:
            if st.query_params.get("da") == "1":
                st.session_state["disclaimer_shown"] = True
        except Exception:
            pass

    if st.session_state.get("disclaimer_shown") and not st.session_state.get("_force_disclaimer"):
        return

    # ── Inject localStorage reader (triggers reload if valid) ───
    _disclaimer_check_localstorage()

    # ── Render disclaimer ────────────────────────────────────────
    st.html("""<style>
/* Centre the disclaimer card and hide everything else */
[data-testid="stAppViewContainer"] > .main > div:first-child {
    display: flex; flex-direction: column;
    align-items: center; justify-content: flex-start;
    padding-top: 48px !important;
}
</style>""")

    with st.container(border=True):
        # Header
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
            '<span style="font-size:28px;">⚖️</span>'
            '<span style="font-size:20px;font-weight:700;color:#0F172A;">Important Disclosure</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<hr style="margin:8px 0 16px;border:none;border-top:1.5px solid #E2E8F0;">',
            unsafe_allow_html=True,
        )

        # Body
        st.markdown(_DISCLAIMER_TEXT)

        st.markdown(
            '<div style="margin:16px 0 8px;padding:12px 16px;'
            'background:#FFF7ED;border:1px solid #FED7AA;border-radius:8px;'
            'font-size:12px;color:#9A3412;">'
            '⚠️ This disclosure must be acknowledged before using YieldIQ.'
            '</div>',
            unsafe_allow_html=True,
        )

        # Checkbox
        agreed = st.checkbox(
            "I understand this tool provides quantitative analysis only, not investment advice",
            key="_disclaimer_checkbox",
        )

        # Button (disabled until checkbox ticked)
        col_btn, col_gap = st.columns([2, 3])
        with col_btn:
            clicked = st.button(
                "Continue to YieldIQ →",
                disabled=not agreed,
                type="primary",
                width='stretch',
                key="_disclaimer_continue_btn",
            )

        if clicked and agreed:
            st.session_state["disclaimer_shown"] = True
            st.session_state["disclaimer_ts"]    = datetime.utcnow().isoformat()
            st.session_state.pop("_force_disclaimer", None)
            _disclaimer_write_localstorage()
            try:
                st.query_params["da"] = "1"
            except Exception:
                pass
            st.rerun()

    st.stop()  # nothing renders below until disclaimer accepted


def render_view_disclaimer_link() -> None:
    """Sidebar footer link that re-shows the disclaimer on demand."""
    st.sidebar.markdown(
        '<div style="text-align:center;margin-top:6px;">'
        '<span style="font-size:10px;color:#475569;">Legal </span>'
        '</div>',
        unsafe_allow_html=True,
    )
    if st.sidebar.button(
        "📋 View Disclaimer",
        key="_view_disclaimer_btn",
        width='stretch',
    ):
        st.session_state["_force_disclaimer"] = True
        st.session_state["disclaimer_shown"]  = False
        st.rerun()

