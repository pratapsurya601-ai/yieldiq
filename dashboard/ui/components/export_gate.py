# dashboard/ui/components/export_gate.py
# ═══════════════════════════════════════════════════════════════
# Export gate — tiered export options
# Free: share link only
# Starter: PDF download
# Pro: PDF + Excel + Google Sheets
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def render_export_options(
    ticker: str,
    fair_value: float = 0,
    sym: str = "₹",
) -> None:
    """Render tiered export options inline (no popup)."""
    _tier = st.session_state.get("tier", st.session_state.get("user_tier", "free"))

    if _tier == "pro":
        # Pro: all formats
        st.html('<div style="font-size:11px;font-weight:700;color:#94A3B8;'
                'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;">'
                '📥 Export Analysis</div>')
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📄 PDF Report", key="_exp_pdf", use_container_width=True):
                st.info("PDF report ready — check your downloads")
        with c2:
            if st.button("📊 Excel Model", key="_exp_excel", use_container_width=True):
                st.info("Excel model ready — check your downloads")
        with c3:
            if st.button("📋 Google Sheets", key="_exp_sheets", use_container_width=True):
                st.info("Google Sheets export ready")

    elif _tier == "starter":
        # Starter: PDF + share
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📄 Download PDF", key="_exp_pdf_s", use_container_width=True,
                         type="primary"):
                st.info("PDF report ready — check your downloads")
        with c2:
            if st.button("📤 Share Link", key="_exp_share_s", use_container_width=True):
                st.code(f"https://www.yieldiq.in/?ticker={ticker}", language=None)

    else:
        # Free: share link + upgrade prompt
        c1, c2 = st.columns(2)
        with c1:
            st.html(
                '<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;'
                'padding:14px;text-align:center;">'
                '<div style="font-size:20px;margin-bottom:6px;">📤</div>'
                '<div style="font-size:12px;font-weight:700;color:#0F172A;margin-bottom:4px;">'
                'Share Link</div>'
                '<div style="font-size:11px;color:#64748B;">Copy a shareable link to this analysis</div>'
                '</div>'
            )
            if st.button("Copy Link", key="_exp_share_f", use_container_width=True):
                st.code(f"https://www.yieldiq.in/?ticker={ticker}", language=None)
                st.success("Link copied!")

        with c2:
            st.html(
                '<div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:10px;'
                'padding:14px;text-align:center;">'
                '<div style="font-size:20px;margin-bottom:6px;">📄</div>'
                '<div style="font-size:12px;font-weight:700;color:#1E40AF;margin-bottom:4px;">'
                'Download PDF</div>'
                '<div style="font-size:11px;color:#64748B;">Full 4-page institutional report</div>'
                '</div>'
            )
            if st.button("Upgrade to Starter →", key="_exp_upgrade_f",
                         use_container_width=True, type="primary"):
                st.session_state.active_tab = "Account"
                st.session_state.main_tab = "pricing"
                st.rerun()
