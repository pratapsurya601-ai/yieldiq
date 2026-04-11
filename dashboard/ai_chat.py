# dashboard/ai_chat.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Ask AI Analyst  (Google Gemini 2.0 Flash)
#
# API key is loaded exclusively from the GEMINI_API_KEY env var
# (set in .env — never hardcoded here).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date
from typing import Optional

import streamlit as st

# ── Load .env so GEMINI_API_KEY is available ──────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv optional; env var can be set directly

# ── AI backend: Gemini (preferred) or Groq (fallback) ─────────
try:
    from google import genai as _genai
    _GENAI_OK = True
except ImportError:
    _GENAI_OK = False

try:
    from groq import Groq as _Groq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
_GEMINI_MODEL = "gemini-2.0-flash"
_GROQ_MODEL   = "llama-3.3-70b-versatile"   # free on Groq
_MODEL_NAME   = _GEMINI_MODEL                # display name

_SYSTEM_PROMPT = (
    "You are YieldIQ's AI analyst. Answer questions ONLY about the provided "
    "stock analysis data. Be concise, use numbers from the context, and explain "
    "financial concepts in simple terms. Do not give generic investment advice. "
    "Always reference specific metrics from the analysis. "
    "Never use the words 'recommend', 'buy', 'sell', or 'rated' — instead "
    "say the model indicates, the analysis shows, or the DCF suggests. "
    "Every response must end with: "
    "This is model output, not personalized investment advice."
)

_AI_LIMITS: dict[str, int] = {
    "free":    5,
    "starter": 50,
    "premium": 50,    # backwards-compat alias
    "pro":     9999,
}

_CHAT_HISTORY_KEY = "ai_chat_history"
_PENDING_KEY      = "ai_pending_question"
_Q_COUNT_KEY      = "ai_questions_today"
_Q_DATE_KEY       = "ai_questions_date"


# ═══════════════════════════════════════════════════════════════
#  1. Context builder
# ═══════════════════════════════════════════════════════════════

def build_stock_context(analysis_data: dict) -> str:
    """
    Format key metrics from the analysed stock into a structured
    context string that is injected into every Gemini request.
    """
    d   = analysis_data
    sym = d.get("sym", "$")

    def _pct(v: float | None, decimals: int = 1) -> str:
        if v is None: return "N/A"
        return f"{v * 100:.{decimals}f}%"

    def _money(v: float | None) -> str:
        if v is None: return "N/A"
        return f"{sym}{v:,.2f}"

    def _x(v: float | None) -> str:
        if v is None: return "N/A"
        return f"{v:.1f}x"

    # ── Core valuation ───────────────────────────────────────
    ticker     = d.get("ticker", "N/A")
    company    = d.get("company_name", ticker)
    sector     = d.get("sector", "N/A")
    price      = d.get("price",   0.0) or 0.0
    iv         = d.get("iv",      0.0) or 0.0
    mos_pct    = d.get("mos_pct", 0.0) or 0.0
    signal     = d.get("signal",  "N/A")
    wacc       = d.get("wacc",    0.0) or 0.0
    terminal_g = d.get("terminal_g", 0.0) or 0.0

    # ── Growth & margins ─────────────────────────────────────
    fcf_growth = d.get("fcf_growth",      0.0) or 0.0
    rev_growth = d.get("revenue_growth",  0.0) or 0.0
    op_margin  = d.get("op_margin",       0.0) or 0.0
    roe        = d.get("roe",             0.0) or 0.0
    roce       = d.get("roce",            0.0) or 0.0
    gross_mg   = d.get("gross_margin",    0.0) or 0.0
    net_mg     = d.get("net_margin",      0.0) or 0.0
    de_ratio   = d.get("de_ratio",        0.0) or 0.0

    # ── Moat ─────────────────────────────────────────────────
    moat_score = d.get("moat_score", 0) or 0
    moat_grade = d.get("moat_grade", "N/A")
    moat_types = d.get("moat_types", []) or []

    # ── Quality scores ───────────────────────────────────────
    piotroski  = d.get("piotroski_score", None)
    eq_grade   = d.get("earnings_quality_grade", "N/A")
    eq_score   = d.get("earnings_quality_score", None)

    # ── Valuation multiples ──────────────────────────────────
    fwd_pe    = d.get("forward_pe",  0.0) or 0.0
    ev_ebitda = d.get("ev_ebitda",   0.0) or 0.0
    fcf_yield = d.get("fcf_yield",   0.0) or 0.0

    # ── Scenarios ────────────────────────────────────────────
    scenarios = d.get("scenarios", {}) or {}
    bear_iv   = (scenarios.get("Bear 🐻", {}) or {}).get("iv", None)
    base_iv   = (scenarios.get("Base 📊", {}) or {}).get("iv", None)
    bull_iv   = (scenarios.get("Bull 🐂", {}) or {}).get("iv", None)

    # ── Earnings track record ─────────────────────────────────
    etr        = d.get("earnings_track_record", {}) or {}
    beat_rate  = etr.get("beat_rate", None)
    avg_surp   = etr.get("avg_surprise_pct", None)
    etr_trend  = etr.get("trend", "N/A")

    # ── Build context string ─────────────────────────────────
    lines = [
        f"STOCK: {company} ({ticker}) — Sector: {sector}",
        "",
        "=== VALUATION ===",
        f"Current Price:      {_money(price)}",
        f"Intrinsic Value:    {_money(iv)}",
        f"Margin of Safety:   {mos_pct:+.1f}%  "
        f"({'undervalued' if mos_pct > 0 else 'overvalued'})",
        f"YieldIQ Signal:     {signal}",
        f"WACC (discount):    {wacc * 100:.2f}%",
        f"Terminal Growth:    {terminal_g * 100:.2f}%",
        "",
        "=== GROWTH & PROFITABILITY ===",
        f"FCF Growth (YoY):   {_pct(fcf_growth)}",
        f"Revenue Growth:     {_pct(rev_growth)}",
        f"Operating Margin:   {_pct(op_margin)}",
        f"Gross Margin:       {_pct(gross_mg)}",
        f"Net Margin:         {_pct(net_mg)}",
        f"Return on Equity:   {_pct(roe)}",
        f"Return on Cap Emp:  {_pct(roce)}",
        f"Debt / Equity:      {de_ratio:.2f}x",
        "",
        "=== ECONOMIC MOAT ===",
        f"Moat Score:  {moat_score:.0f} / 100",
        f"Moat Grade:  {moat_grade}",
        f"Moat Types:  {', '.join(moat_types) if moat_types else 'None identified'}",
        "",
        "=== QUALITY SCORES ===",
        f"Piotroski F-Score:      {piotroski if piotroski is not None else 'N/A'} / 9",
        f"Earnings Quality Grade: {eq_grade}"
        + (f" ({eq_score:.0f}/100)" if eq_score is not None else ""),
        "",
        "=== VALUATION MULTIPLES ===",
        f"Forward P/E:    {fwd_pe:.1f}x" if fwd_pe else "Forward P/E:    N/A",
        f"EV / EBITDA:    {ev_ebitda:.1f}x" if ev_ebitda else "EV / EBITDA:    N/A",
        f"FCF Yield:      {_pct(fcf_yield)}",
    ]

    if bear_iv or base_iv or bull_iv:
        lines += [
            "",
            "=== SCENARIOS ===",
            f"Bear Case IV:  {_money(bear_iv)}" if bear_iv else "",
            f"Base Case IV:  {_money(base_iv)}" if base_iv else "",
            f"Bull Case IV:  {_money(bull_iv)}" if bull_iv else "",
        ]

    if beat_rate is not None:
        lines += [
            "",
            "=== EARNINGS TRACK RECORD ===",
            f"Analyst Beat Rate:    {beat_rate * 100:.1f}%",
            f"Avg Surprise:         {avg_surp:+.2f}%" if avg_surp is not None else "",
            f"Trend:                {etr_trend}",
        ]

    return "\n".join(l for l in lines if l is not None)


# ═══════════════════════════════════════════════════════════════
#  2. Gemini response function
# ═══════════════════════════════════════════════════════════════

def get_gemini_response(
    user_question: str,
    stock_context: str,
    chat_history:  list[dict],
) -> str:
    """
    Call Gemini 2.0 Flash and return the response text.

    Parameters
    ----------
    user_question : The user's current question.
    stock_context : Output of build_stock_context().
    chat_history  : List of {"question": str, "answer": str} dicts
                    (most-recent last).

    Returns
    -------
    Response text, or a user-friendly error message string.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key   = os.environ.get("GROQ_API_KEY",   "").strip()

    # Build the prompt (shared by both backends)
    contents = []
    for msg in chat_history:
        q = msg.get("question", "")
        a = msg.get("answer",   "")
        if q and a:
            contents.append(f"User: {q}")
            contents.append(f"Assistant: {a}")

    full_message = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"STOCK ANALYSIS DATA:\n{stock_context}\n\n"
    )
    if contents:
        full_message += "Previous conversation:\n" + "\n".join(contents) + "\n\n"
    full_message += f"User question: {user_question}"

    # ── Try Gemini first ──────────────────────────────────────
    if _GENAI_OK and gemini_key:
        try:
            client = _genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model=_GEMINI_MODEL,
                contents=full_message,
            )
            return response.text.strip()
        except Exception as exc:
            err = str(exc).lower()
            # If quota/region issue, fall through to Groq
            if any(k in err for k in ("quota", "429", "resource_exhausted", "limit: 0")):
                pass  # fall through to Groq
            elif any(k in err for k in ("api_key", "invalid", "401", "unauthorized")):
                return "⚠️ Invalid GEMINI_API_KEY. Check your .env file."
            else:
                return f"⚠️ Gemini error: {exc}"

    # ── Groq fallback ─────────────────────────────────────────
    if _GROQ_OK and groq_key:
        try:
            client = _Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=[{"role": "user", "content": full_message}],
                max_tokens=500,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            err = str(exc).lower()
            if "401" in err or "unauthorized" in err:
                return "⚠️ Invalid GROQ_API_KEY. Check your .env file."
            return f"⚠️ Groq error: {exc}"

    # ── No backend available ──────────────────────────────────
    if not gemini_key and not groq_key:
        return (
            "⚠️ No AI key configured. Add either:\n"
            "- `GEMINI_API_KEY` from aistudio.google.com/apikey\n"
            "- `GROQ_API_KEY` from console.groq.com (free, no region limits)"
        )
    if not _GENAI_OK and not _GROQ_OK:
        return "⚠️ Run: `pip install google-genai groq`"
    return "⚠️ AI service temporarily unavailable. Try again in a moment."


# ═══════════════════════════════════════════════════════════════
#  Tier helpers (reads session state — no circular import)
# ═══════════════════════════════════════════════════════════════

def _current_tier() -> str:
    return st.session_state.get("tier", "free")


def _ai_limit() -> int:
    return _AI_LIMITS.get(_current_tier(), 5)


def _ai_questions_used() -> int:
    today = str(date.today())
    if st.session_state.get(_Q_DATE_KEY) != today:
        st.session_state[_Q_DATE_KEY]  = today
        st.session_state[_Q_COUNT_KEY] = 0
    return st.session_state.get(_Q_COUNT_KEY, 0)


def _increment_ai_count() -> None:
    st.session_state[_Q_COUNT_KEY] = _ai_questions_used() + 1


def _can_ask() -> tuple[bool, str]:
    """Return (allowed, reason_string)."""
    used  = _ai_questions_used()
    limit = _ai_limit()
    if limit >= 9999:
        return True, "Unlimited (Pro)"
    if used >= limit:
        tier = _current_tier()
        if tier == "free":
            return False, (
                f"You've used all {limit} free AI questions today. "
                "Upgrade to Starter for 50/day or Pro for unlimited."
            )
        return False, (
            f"Daily limit of {limit} AI questions reached. "
            "Upgrade to Pro for unlimited AI analysis."
        )
    remaining = limit - used
    return True, f"{remaining} question{'s' if remaining != 1 else ''} remaining today"


# ═══════════════════════════════════════════════════════════════
#  3. Streamlit UI renderer
# ═══════════════════════════════════════════════════════════════

def render_ai_chat(analysis_data: dict) -> None:
    """
    Render the full 'Ask AI Analyst' chat UI inside any Streamlit container.

    Parameters
    ----------
    analysis_data : Dict built from session state — see app.py call site for keys.
    """
    if not analysis_data:
        st.info("Run a stock analysis first to enable the AI chat.")
        return

    ticker = analysis_data.get("ticker", "this stock")
    signal = analysis_data.get("signal", "")
    # Short signal label for button text
    _sig_short = (
        "undervalued"  if any(k in signal.upper() for k in ("BUY", "UNDERVALUED")) else
        "overvalued"   if any(k in signal.upper() for k in ("SELL", "OVERVALUED"))  else
        "near fair value"
    )

    # ── Section header ────────────────────────────────────────
    st.html("""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
      <div style="width:32px;height:32px;background:linear-gradient(135deg,#1D4ED8,#06B6D4);
                  border-radius:8px;display:flex;align-items:center;justify-content:center;
                  font-size:16px;">🤖</div>
      <div>
        <div style="font-size:15px;font-weight:700;color:#0F172A;">Ask AI Analyst</div>
        <div style="font-size:11px;color:#64748B;">
          Powered by Gemini 2.0 Flash · Answers are based on YieldIQ's analysis only
        </div>
      </div>
    </div>
    """)

    # ── Tier / quota check ────────────────────────────────────
    allowed, quota_msg = _can_ask()
    if not allowed:
        st.html(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:14px 16px;
                    background:#FEF2F2;border:1.5px solid #FECACA;border-radius:10px;
                    margin:8px 0;">
          <span style="font-size:22px">🔒</span>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:#991B1B;">
              Daily AI question limit reached
            </div>
            <div style="font-size:12px;color:#7F1D1D;margin-top:2px;">{quota_msg}</div>
          </div>
          <a href="https://yourdomain.com/pricing.html" target="_blank"
             style="background:#1D4ED8;color:#fff;font-size:12px;font-weight:600;
                    padding:7px 14px;border-radius:7px;text-decoration:none;white-space:nowrap;">
            Upgrade →
          </a>
        </div>
        """)
        # Still show history but disable input
        _show_history_readonly()
        return

    # ── Quota status bar ─────────────────────────────────────
    used  = _ai_questions_used()
    limit = _ai_limit()
    if limit < 9999:
        pct   = min(used / limit * 100, 100)
        clr   = "#dc2626" if pct >= 90 else "#d97706" if pct >= 60 else "#059669"
        st.html(f"""
        <div style="margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;
                      font-size:11px;color:#64748B;margin-bottom:3px;">
            <span>AI questions today</span>
            <span style="font-weight:600;color:{clr};">{used} / {limit}</span>
          </div>
          <div style="height:3px;background:#E2E8F0;border-radius:2px;">
            <div style="height:100%;width:{pct}%;background:{clr};border-radius:2px;
                        transition:width 0.3s;"></div>
          </div>
        </div>
        """)

    # ── Initialise chat history ───────────────────────────────
    if _CHAT_HISTORY_KEY not in st.session_state:
        st.session_state[_CHAT_HISTORY_KEY] = []
    history: list[dict] = st.session_state[_CHAT_HISTORY_KEY]

    # ── Display existing messages ─────────────────────────────
    for msg in history:
        with st.chat_message("user"):
            st.markdown(msg["question"])
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(msg["answer"])

    # ── Example question buttons ──────────────────────────────
    if not history:
        st.markdown(
            '<div style="font-size:11px;color:#94A3B8;margin:8px 0 4px;">Try asking:</div>',
            unsafe_allow_html=True,
        )

    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        if st.button(
            f"Why does the DCF model show {ticker} as {_sig_short.lower()}?",
            key="ai_eq1", width='stretch',
        ):
            st.session_state[_PENDING_KEY] = (
                f"Based on the DCF model data, why does the quantitative analysis "
                f"show {ticker} as {_sig_short.lower()}? Explain the key valuation "
                "metrics and growth assumptions driving this result."
            )
            st.rerun()
    with btn_col2:
        if st.button(
            "Biggest risks in this DCF?",
            key="ai_eq2", width='stretch',
        ):
            st.session_state[_PENDING_KEY] = (
                "What are the biggest risks in this DCF model? "
                "Which assumptions could be wrong and how would that affect intrinsic value?"
            )
            st.rerun()
    with btn_col3:
        if st.button(
            "Is the margin of safety attractive?",
            key="ai_eq3", width='stretch',
        ):
            st.session_state[_PENDING_KEY] = (
                "Is the current margin of safety attractive for investment? "
                "How does it compare to typical thresholds and what does it mean for risk?"
            )
            st.rerun()

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # ── Handle pending question from button clicks ────────────
    _pending = st.session_state.pop(_PENDING_KEY, None)

    # ── Chat input ────────────────────────────────────────────
    user_input = st.chat_input(
        f"Ask about {ticker}…",
        key="ai_chat_input",
    ) or _pending

    if user_input:
        # Show user message immediately
        with st.chat_message("user"):
            st.markdown(user_input)

        stock_context = build_stock_context(analysis_data)

        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Thinking…"):
                answer = get_gemini_response(
                    user_question=user_input,
                    stock_context=stock_context,
                    chat_history=history,
                )
            st.markdown(answer)

        # Persist to history
        history.append({"question": user_input, "answer": answer})
        st.session_state[_CHAT_HISTORY_KEY] = history

        # Increment counter only for successful responses
        if not answer.startswith("⚠️"):
            _increment_ai_count()

    # ── Clear chat ────────────────────────────────────────────
    if history:
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        if st.button("🗑 Clear chat", key="ai_clear_btn"):
            st.session_state[_CHAT_HISTORY_KEY] = []
            st.rerun()

    # ── Disclaimer ────────────────────────────────────────────
    st.html("""
    <div style="font-size:10px;color:#94A3B8;margin-top:10px;padding:6px 10px;
                background:#F8FAFC;border-radius:6px;line-height:1.6;">
      🤖 AI responses are generated by Gemini 2.0 Flash based on YieldIQ's analysis only.
      Not financial advice. Always do your own research before investing.
    </div>
    """)


def _show_history_readonly() -> None:
    """Show existing chat history without the input box."""
    history = st.session_state.get(_CHAT_HISTORY_KEY, [])
    for msg in history:
        with st.chat_message("user"):
            st.markdown(msg["question"])
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(msg["answer"])
