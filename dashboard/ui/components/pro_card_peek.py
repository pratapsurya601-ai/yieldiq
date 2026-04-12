# dashboard/ui/components/pro_card_peek.py
# ═══════════════════════════════════════════════════════════════
# Pro Card Peek — teaser of advanced features for non-Pro users
# Shows a rendered but overlaid preview to drive upgrades
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_pro_card_peek(
    fair_value: float = 0,
    sym: str = "₹",
) -> None:
    """Show Pro feature teaser for non-Pro users."""
    _tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))

    if _tier == "pro":
        return  # Pro users see the real features in Layer 3

    # Calculate fake Monte Carlo values for teaser
    _base = fair_value if fair_value > 0 else 1000
    _bear = _base * 0.65
    _bull = _base * 1.35
    _p10 = _base * 0.72
    _p90 = _base * 1.28

    st.html(f"""
    <div style="margin-top:16px;position:relative;">
      <!-- Section header -->
      <div style="font-size:11px;font-weight:700;color:#94A3B8;text-transform:uppercase;
                  letter-spacing:0.14em;margin-bottom:10px;">
        ⚡ Advanced Signals — Pro Plan</div>

      <!-- Teaser cards with overlay -->
      <div style="position:relative;border-radius:16px;overflow:hidden;">

        <!-- Blurred content -->
        <div style="filter:blur(3px);pointer-events:none;user-select:none;opacity:0.5;
                    padding:20px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;">

          <!-- Monte Carlo teaser -->
          <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:12px;">
            🎲 Monte Carlo Simulation — 1,000 Scenarios</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:16px;">
            <div style="background:#FEF2F2;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:9px;color:#991B1B;font-weight:700;">BEAR (10th %ile)</div>
              <div style="font-size:16px;font-weight:800;color:#DC2626;font-family:IBM Plex Mono,monospace;">
                {sym}{_bear:,.0f}</div>
            </div>
            <div style="background:#FFFBEB;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:9px;color:#92400E;font-weight:700;">MEDIAN</div>
              <div style="font-size:16px;font-weight:800;color:#D97706;font-family:IBM Plex Mono,monospace;">
                {sym}{_base:,.0f}</div>
            </div>
            <div style="background:#F0FDF4;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:9px;color:#166534;font-weight:700;">BULL (90th %ile)</div>
              <div style="font-size:16px;font-weight:800;color:#16A34A;font-family:IBM Plex Mono,monospace;">
                {sym}{_bull:,.0f}</div>
            </div>
            <div style="background:#EFF6FF;border-radius:8px;padding:10px;text-align:center;">
              <div style="font-size:9px;color:#1E40AF;font-weight:700;">CONFIDENCE</div>
              <div style="font-size:16px;font-weight:800;color:#1D4ED8;font-family:IBM Plex Mono,monospace;">
                68%</div>
            </div>
          </div>

          <!-- Reverse DCF teaser -->
          <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:8px;">
            💡 Market Expectations — Implied Growth</div>
          <div style="font-size:12px;color:#475569;">
            The market is pricing in 14.2% annual growth. Historical average is 9.1%.
            You're paying a premium for optimism.</div>

          <div style="height:16px;"></div>

          <!-- Historical IV teaser -->
          <div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:8px;">
            📅 Historical Fair Value Tracking</div>
          <div style="height:60px;background:linear-gradient(90deg,#DBEAFE,#BBF7D0,#FDE68A,#FECACA);
                      border-radius:8px;"></div>
        </div>

        <!-- Overlay -->
        <div style="position:absolute;inset:0;display:flex;flex-direction:column;
                    align-items:center;justify-content:center;
                    background:rgba(255,255,255,0.6);backdrop-filter:blur(1px);
                    border-radius:16px;">
          <div style="font-size:32px;margin-bottom:8px;">🔒</div>
          <div style="font-size:16px;font-weight:700;color:#0F172A;margin-bottom:4px;">
            Advanced Analysis</div>
          <div style="font-size:12px;color:#64748B;margin-bottom:16px;text-align:center;max-width:300px;">
            Monte Carlo, market expectations, historical tracking, and more</div>
        </div>
      </div>
    </div>
    """)

    # Unlock button (outside the blur)
    _c1, _c2, _c3 = st.columns([1, 2, 1])
    with _c2:
        if st.button("⚡ Unlock Pro →", key="_pro_peek_unlock",
                     type="primary", use_container_width=True):
            st.session_state.active_tab = "Account"
            st.session_state.main_tab = "pricing"
            st.rerun()
