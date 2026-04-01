# dashboard/tabs/moat_tab.py
# ═══════════════════════════════════════════════════════════════
# Moat Analysis tab module.
# Extracted from app.py moat computation block (lines 3625-3659)
# plus a dedicated render() to display moat results.
#
# Entry points:
#   compute(enriched, wacc, base_growth, terminal_g, iv_n)
#       -> (iv_n_moat, moat_grade, moat_score, moat_adj)
#   render(enriched)
#       -> renders moat analysis card (grade / score / types / summary)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st
from tab_helpers import ccard, ccard_end
from ui.helpers import add_tooltip, FINANCIAL_TOOLTIPS


# ══════════════════════════════════════════════════════════════
# COMPUTE — moat score + IV adjustment
# ══════════════════════════════════════════════════════════════

def compute(
    enriched:    dict,
    wacc:        float,
    base_growth: float,
    terminal_g:  float,
    iv_n:        float,
) -> tuple:
    """
    Compute economic moat score and apply IV premium/discount.
    Writes moat fields into `enriched` and st.session_state in-place.

    Returns
    -------
    (iv_n_moat, moat_grade, moat_score, moat_adj)
    """
    # Moat — compute first, then adjust IV before investment plan
    moat_grade   = "None"
    moat_score   = 0
    moat_types   = []
    moat_summary = ""
    moat_adj     = {"iv_delta_pct": 0}   # safe default — overwritten if moat succeeds
    try:
        from screener.moat_engine import compute_moat_score, apply_moat_adjustments
        moat_result  = compute_moat_score(enriched, wacc)
        moat_adj     = apply_moat_adjustments(
            moat_result, wacc, base_growth, terminal_g, iv_n,
            sector=enriched.get("sector", "general")
        )
        moat_grade   = moat_result.get("grade",      "None")
        moat_score   = moat_result.get("score",      0)
        moat_types   = moat_result.get("moat_types", [])
        moat_summary = moat_result.get("summary",    "")

        # Apply moat IV premium/discount to get moat-adjusted IV
        iv_delta_pct = moat_adj.get("iv_delta_pct", 0) / 100
        iv_n_moat    = iv_n * (1 + iv_delta_pct)

        enriched["moat_grade"]   = moat_grade
        enriched["moat_score"]   = moat_score
        enriched["moat_types"]   = moat_types
        enriched["moat_summary"] = moat_summary
        st.session_state["fin_moat"]     = moat_result
        st.session_state["fin_moat_adj"] = moat_adj
    except Exception as _me:
        iv_n_moat    = iv_n
        enriched["moat_grade"]   = "N/A"
        enriched["moat_score"]   = 0
        enriched["moat_types"]   = []
        enriched["moat_summary"] = ""


    # Return the moat-adjusted IV and key moat outputs
    return iv_n_moat, moat_grade, moat_score, moat_adj


# ══════════════════════════════════════════════════════════════
# RENDER — moat analysis display card
# ══════════════════════════════════════════════════════════════

def render(enriched: dict) -> None:
    """Render a compact moat analysis card from already-computed enriched data."""
    moat_grade   = enriched.get("moat_grade",   "N/A")
    moat_score   = enriched.get("moat_score",   0)
    moat_types   = enriched.get("moat_types",   [])
    moat_summary = enriched.get("moat_summary", "")

    GRADE_CFG = {
        "Wide":   ("#059669", "#ECFDF5", "#BBF7D0", "Strong competitive advantage"),
        "Narrow": ("#2563EB", "#EFF6FF", "#BFDBFE", "Some competitive advantages"),
        "None":   ("#DC2626", "#FEF2F2", "#FECACA", "No clear competitive advantage"),
        "N/A":    ("#64748B", "#F8FAFC", "#E2E8F0", "Competitive advantage unknown"),
    }
    fg, bg, bd, label = GRADE_CFG.get(moat_grade, GRADE_CFG["N/A"])

    ccard(add_tooltip("Economic Moat Analysis", FINANCIAL_TOOLTIPS["Economic Moat"]), fg)
    st.html(
        f'''<div style="display:flex;align-items:center;gap:20px;
                padding:16px 20px;background:#161b22;
                border:1.5px solid {fg}33;border-radius:12px;margin-bottom:14px;">
          <div style="min-width:80px;text-align:center;">
            <div style="font-size:28px;font-weight:800;color:{fg};
                        font-family:IBM Plex Mono,monospace;">{moat_score:.0f}</div>
            <div style="font-size:9px;font-weight:700;color:#8b949e;
                        text-transform:uppercase;letter-spacing:.12em;">Score</div>
          </div>
          <div style="width:1px;height:60px;background:#21262d;"></div>
          <div style="flex:1;">
            <div style="display:inline-block;padding:3px 14px;background:{bg};
                        border:1px solid {bd};border-radius:20px;margin-bottom:8px;">
              <span style="font-size:13px;font-weight:700;color:{fg};">{moat_grade} Moat</span>
            </div>
            <div style="font-size:13px;color:#8b949e;">{label}</div>
            <div style="font-size:12px;color:#8b949e;margin-top:4px;">
              {" · ".join(moat_types[:3]) if moat_types else "No identified moat sources"}
            </div>
          </div>
        </div>'''
    )
    if moat_summary:
        st.html(
            f'''<div style="padding:10px 14px;background:#0d1117;border:1px solid #21262d;
                    border-left:3px solid {fg};border-radius:8px;
                    font-size:13px;color:#8b949e;line-height:1.75;">
              {moat_summary}
            </div>'''
        )
    ccard_end()
