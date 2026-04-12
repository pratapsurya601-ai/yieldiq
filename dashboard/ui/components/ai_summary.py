# dashboard/ui/components/ai_summary.py
# ═══════════════════════════════════════════════════════════════
# AI Summary — 2-3 sentence plain-English stock analysis
# Uses Gemini/Groq if available, falls back to template.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import streamlit as st


def _template_summary(
    ticker: str, company_name: str,
    mos: float, moat: str,
    fcf_growth: float, confidence: int,
) -> str:
    """Generate plain-English summary without AI."""
    direction = "below" if mos > 0 else "above"
    pct = abs(round(mos))
    moat_text = (
        "wide moat" if moat == "Wide" else
        "narrow moat" if moat == "Narrow" else
        "no clear competitive moat"
    )
    conf_text = (
        "High" if confidence > 75 else
        "Medium" if confidence > 50 else
        "Low"
    )
    growth_text = (
        f"growing FCF at {fcf_growth:.1f}% annually" if fcf_growth > 2 else
        f"stable cash flows" if fcf_growth > -2 else
        f"declining cash flows ({fcf_growth:.1f}% annually)"
    )
    return (
        f"{company_name} ({ticker}) trades {pct}% {direction} our model's estimated fair value. "
        f"The business has a {moat_text} with {growth_text}. "
        f"{conf_text} confidence in this estimate based on data quality and model inputs."
    )


def render_ai_summary(
    ticker: str,
    company_name: str,
    mos: float,
    moat: str,
    fcf_growth: float,
    confidence: int,
) -> None:
    """Render AI-generated or template summary."""

    # Cache key to avoid regenerating on every rerun
    _cache_key = f"_ai_summary_{ticker}_{round(mos)}_{confidence}"

    if _cache_key in st.session_state:
        summary = st.session_state[_cache_key]
    else:
        # Try AI generation first
        summary = None
        try:
            from utils.data_helpers import generate_ai_summary
            _ai_text = generate_ai_summary(
                ticker=ticker,
                company_name=company_name,
                price=0,  # not needed for summary
                iv=0,
                mos_pct=mos,
                signal="",
                piotroski_score=0,
                wacc=0,
                rev_growth=0,
                fcf_growth=fcf_growth / 100 if fcf_growth > 1 else fcf_growth,
                op_margin=0,
                moat_grade=moat,
                sym="₹",
            )
            if _ai_text and "error" not in _ai_text.lower()[:50]:
                # Take first 2 sentences only
                sentences = _ai_text.split(". ")
                summary = ". ".join(sentences[:2]) + "."
        except Exception:
            pass

        # Fallback to template
        if not summary:
            summary = _template_summary(
                ticker, company_name, mos, moat, fcf_growth, confidence
            )

        # Cache it
        st.session_state[_cache_key] = summary

    # Render
    st.html(
        f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
        f'border-radius:10px;padding:12px 16px;margin-bottom:12px;">'
        f'<div style="font-size:10px;color:#94A3B8;font-weight:600;'
        f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">'
        f'✦ AI Summary</div>'
        f'<div style="font-size:13px;color:#475569;font-style:italic;'
        f'line-height:1.7;">{summary}</div>'
        f'<div style="font-size:9px;color:#CBD5E1;margin-top:4px;">'
        f'Model-generated summary · Not investment advice</div>'
        f'</div>'
    )
